"""
integrations/sales_navigator.py

Envia o saldo de estoque do Bling (tabela custo_produtos, já sincronizada pela
rotina diária) para o app Sales Navigator (Lovable), pelo endpoint protegido
/api/public/sync-estoque. O Python é o único dono da credencial do Bling; o
Sales Navigator só recebe {sku, saldo}.

O endpoint recusa o lote inteiro se algum SKU não existir no cadastro de
produtos do Sales Navigator (chave estrangeira). Por isso, ao receber 400, o
lote é dividido ao meio até isolar o SKU recusado: os válidos entram e os
recusados são listados no resumo (nunca se perde silenciosamente).

O segredo só vai no header x-sync-secret; nunca é impresso nem aparece em log.
"""

import time

import requests

from config.settings import ConfiguracaoInvalidaError, carregar_configuracao_sales_navigator
from database.conexao_supabase import obter_conexao

CAMINHO_ENDPOINT = "/api/public/sync-estoque"
TAMANHO_LOTE = 500
TIMEOUT_SEGUNDOS = 60
TENTATIVAS = 3
ESPERA_ENTRE_TENTATIVAS = 2.0
MAX_REQUISICOES = 300  # teto de segurança (o isolamento por divisão ao meio faz várias chamadas)


class ErroFatalEnvio(Exception):
    """Falha que torna inútil continuar (segredo recusado, servidor fora do ar)."""


def obter_saldos() -> list[dict]:
    """Lê (só leitura) SKU e saldo do Bling. Ignora SKU vazio e saldo desconhecido (NULL)."""
    conexao = obter_conexao()
    try:
        linhas = conexao.execute(
            "SELECT sku, estoque_saldo FROM custo_produtos "
            "WHERE sku IS NOT NULL AND TRIM(sku) <> '' AND estoque_saldo IS NOT NULL ORDER BY sku"
        ).fetchall()
    finally:
        conexao.close()
    return [{"sku": str(l["sku"]).strip(), "saldo": float(l["estoque_saldo"])} for l in linhas]


class _Enviador:
    def __init__(self, url: str, segredo: str):
        self._url = url
        self._segredo = segredo
        self.requisicoes = 0
        self.enviados = 0
        self.recusados: list[dict] = []  # [{"sku":..., "motivo":...}]

    def _post(self, itens: list[dict]) -> requests.Response:
        ultimo_erro: Exception | None = None
        for tentativa in range(TENTATIVAS):
            if self.requisicoes >= MAX_REQUISICOES:
                raise ErroFatalEnvio(f"limite de {MAX_REQUISICOES} requisições atingido")
            self.requisicoes += 1
            try:
                resposta = requests.post(
                    self._url, json=itens, headers={"x-sync-secret": self._segredo}, timeout=TIMEOUT_SEGUNDOS
                )
            except requests.RequestException as erro:
                ultimo_erro = erro
            else:
                if resposta.status_code < 500:
                    return resposta
                ultimo_erro = RuntimeError(f"HTTP {resposta.status_code}")
            if tentativa < TENTATIVAS - 1:
                time.sleep(ESPERA_ENTRE_TENTATIVAS)
        raise ErroFatalEnvio(f"servidor indisponível após {TENTATIVAS} tentativas ({type(ultimo_erro).__name__})")

    def enviar(self, itens: list[dict]) -> None:
        if not itens:
            return
        resposta = self._post(itens)
        if resposta.status_code == 200:
            self.enviados += len(itens)
            return
        if resposta.status_code in (401, 403):
            raise ErroFatalEnvio("segredo recusado pelo Sales Navigator (401/403)")
        if resposta.status_code == 400:
            if len(itens) == 1:
                self.recusados.append({"sku": itens[0]["sku"], "motivo": _motivo(resposta)})
                return
            meio = len(itens) // 2
            self.enviar(itens[:meio])
            self.enviar(itens[meio:])
            return
        raise ErroFatalEnvio(f"resposta inesperada HTTP {resposta.status_code}")


def _motivo(resposta: requests.Response) -> str:
    try:
        return str(resposta.json().get("error", ""))[:200] or f"HTTP {resposta.status_code}"
    except ValueError:
        return f"HTTP {resposta.status_code}"


def enviar_estoque(saldos: list[dict], url_base: str, segredo: str) -> dict:
    """Envia em lotes. Retorna {total, enviados, recusados:[{sku,motivo}], requisicoes}. Levanta ErroFatalEnvio."""
    enviador = _Enviador(url_base + CAMINHO_ENDPOINT, segredo)
    for i in range(0, len(saldos), TAMANHO_LOTE):
        enviador.enviar(saldos[i:i + TAMANHO_LOTE])
    return {
        "total": len(saldos),
        "enviados": enviador.enviados,
        "recusados": enviador.recusados,
        "requisicoes": enviador.requisicoes,
    }


def sincronizar_estoque(simular: bool = False) -> dict | None:
    """
    Ponto de entrada. Retorna None se o envio não está configurado (variáveis ausentes) - não é erro.
    Com simular=True só lê o banco e conta, sem nenhuma chamada de rede.
    """
    saldos = obter_saldos()
    if simular:
        print(f"[simulação] {len(saldos)} SKU(s) com saldo seriam enviados ao Sales Navigator. Nada foi enviado.")
        return {"total": len(saldos), "enviados": 0, "recusados": [], "requisicoes": 0}
    try:
        config = carregar_configuracao_sales_navigator()
    except ConfiguracaoInvalidaError:
        print("Sales Navigator: envio de estoque não configurado (SALES_NAVIGATOR_URL/SECRET ausentes), pulando.")
        return None
    resultado = enviar_estoque(saldos, config.url_base, config.segredo)
    print(
        f"Sales Navigator: {resultado['enviados']}/{resultado['total']} saldo(s) enviado(s), "
        f"{len(resultado['recusados'])} recusado(s) ({resultado['requisicoes']} requisições)."
    )
    for r in resultado["recusados"][:20]:
        print(f"  recusado: {r['sku']} - {r['motivo']}")
    if len(resultado["recusados"]) > 20:
        print(f"  ... e mais {len(resultado['recusados']) - 20} recusado(s).")
    return resultado
