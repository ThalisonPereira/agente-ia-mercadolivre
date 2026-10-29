"""
integrations/sales_navigator_catalogo.py

Envia o catálogo do Bling (SKU, nome, situação, fornecedor padrão e custo) ao
Sales Navigator, pelo endpoint protegido /api/public/sync-produtos. O Python
continua sendo o único dono da credencial do Bling.

O endpoint valida item a item (um item ruim não derruba o lote) e só grava o
fornecedor quando ele vem preenchido; custo ausente ou zero é enviado como
null (custo desconhecido, nunca zero). O segredo só vai no header
x-sync-secret e nunca é impresso.
"""

import time

import requests

from config.settings import ConfiguracaoInvalidaError, carregar_configuracao_sales_navigator
from integrations.bling import BlingClient

CAMINHO_ENDPOINT = "/api/public/sync-produtos"
TAMANHO_LOTE = 500
TIMEOUT_SEGUNDOS = 90
TENTATIVAS = 3
ESPERA_ENTRE_TENTATIVAS = 2.0
PAUSA_ENTRE_CONTATOS = 0.4
SITUACOES = {"A": "ativo", "I": "inativo"}  # outras (ex: E = excluído) não são enviadas

# Nome do contato no Bling (chave, em maiúsculas) -> nome usado no cadastro do Sales Navigator.
# Existe porque o mesmo fornecedor aparece com grafias diferentes (ex: com e sem "LTDA") e o
# Sales Navigator agrupa por nome exato. Acrescente aqui quando surgir outro caso.
ALIAS_FORNECEDOR = {
    "DEISS INDUSTRIA E COMERCIO DE MOVEIS": "DEISS INDUSTRIA E COMERCIO DE MOVEIS LTDA",
}


class ErroFatalEnvio(Exception):
    """Falha que torna inútil continuar (segredo recusado, servidor fora do ar, erro de gravação)."""


def escolher_fornecedor_por_produto(vinculos: list[dict]) -> dict[int, int]:
    """produto_id -> fornecedor_id. Prefere o vínculo 'padrao'; senão o primeiro encontrado."""
    escolhido: dict[int, tuple[bool, int]] = {}
    for v in vinculos:
        produto_id = (v.get("produto") or {}).get("id")
        fornecedor_id = (v.get("fornecedor") or {}).get("id")
        if not produto_id or not fornecedor_id:
            continue
        padrao = bool(v.get("padrao"))
        atual = escolhido.get(produto_id)
        if atual is None or (padrao and not atual[0]):
            escolhido[produto_id] = (padrao, fornecedor_id)
    return {pid: forn for pid, (_, forn) in escolhido.items()}


def montar_catalogo(produtos: list[dict], fornecedor_por_produto: dict[int, int], nomes: dict[int, str | None]) -> tuple[list[dict], dict]:
    """Monta os itens do envio. Retorna (itens, resumo). Produto sem SKU ou com situação não enviável é ignorado."""
    itens: list[dict] = []
    resumo = {"produtos": len(produtos), "sem_sku": 0, "situacao_ignorada": 0, "sem_fornecedor": 0, "sem_custo": 0}
    vistos: set[str] = set()
    for p in produtos:
        sku = str(p.get("codigo") or "").strip()
        if not sku:
            resumo["sem_sku"] += 1
            continue
        situacao = SITUACOES.get(str(p.get("situacao") or "").strip().upper())
        if situacao is None:
            resumo["situacao_ignorada"] += 1
            continue
        if sku.lower() in vistos:
            continue
        vistos.add(sku.lower())
        fornecedor = nomes.get(fornecedor_por_produto.get(p.get("id")))
        if fornecedor:
            fornecedor = ALIAS_FORNECEDOR.get(fornecedor.strip().upper(), fornecedor.strip())
        custo = p.get("precoCusto")
        custo = float(custo) if isinstance(custo, (int, float)) and custo > 0 else None
        if not fornecedor:
            resumo["sem_fornecedor"] += 1
        if custo is None:
            resumo["sem_custo"] += 1
        itens.append({"sku": sku, "nome": str(p.get("nome") or "").strip(), "fornecedor": fornecedor or "", "situacao": situacao, "custo": custo})
    resumo["itens"] = len(itens)
    return itens, resumo


def resolver_nomes(bling: BlingClient, ids: set[int]) -> dict[int, str | None]:
    """ID do fornecedor -> nome (uma chamada por fornecedor distinto)."""
    nomes: dict[int, str | None] = {}
    for fid in sorted(ids):
        nomes[fid] = bling.obter_nome_contato(fid)
        time.sleep(PAUSA_ENTRE_CONTATOS)
    return nomes


def _post(url: str, segredo: str, itens: list[dict]) -> requests.Response:
    ultimo_erro: Exception | None = None
    for tentativa in range(TENTATIVAS):
        try:
            resposta = requests.post(url, json=itens, headers={"x-sync-secret": segredo}, timeout=TIMEOUT_SEGUNDOS)
        except requests.RequestException as erro:
            ultimo_erro = erro
        else:
            if resposta.status_code < 500:
                return resposta
            ultimo_erro = RuntimeError(f"HTTP {resposta.status_code}")
        if tentativa < TENTATIVAS - 1:
            time.sleep(ESPERA_ENTRE_TENTATIVAS)
    raise ErroFatalEnvio(f"servidor indisponível após {TENTATIVAS} tentativas ({type(ultimo_erro).__name__})")


def enviar_itens(itens: list[dict], url_base: str, segredo: str) -> dict:
    """Envia em lotes. Retorna {total, gravados, rejeitados:[{sku,motivo}], requisicoes}. Levanta ErroFatalEnvio."""
    url = url_base + CAMINHO_ENDPOINT
    gravados, requisicoes, rejeitados = 0, 0, []
    for i in range(0, len(itens), TAMANHO_LOTE):
        lote = itens[i:i + TAMANHO_LOTE]
        resposta = _post(url, segredo, lote)
        requisicoes += 1
        if resposta.status_code in (401, 403):
            raise ErroFatalEnvio("segredo recusado pelo Sales Navigator (401/403)")
        if resposta.status_code == 404:
            raise ErroFatalEnvio("endpoint não encontrado (404): o Sales Navigator já foi publicado com a rota nova?")
        if resposta.status_code != 200:
            try:
                detalhe = str(resposta.json().get("error", ""))[:200]
            except ValueError:
                detalhe = ""
            raise ErroFatalEnvio(f"resposta inesperada HTTP {resposta.status_code} {detalhe}".strip())
        corpo = resposta.json()
        gravados += int(corpo.get("gravados", 0))
        rejeitados.extend(corpo.get("rejeitados") or [])
    return {"total": len(itens), "gravados": gravados, "rejeitados": rejeitados, "requisicoes": requisicoes}


def sincronizar_catalogo(simular: bool = False) -> dict | None:
    """
    Ponto de entrada. Lê o Bling (só leitura), monta o catálogo e envia. Com simular=True
    não envia nada ao Sales Navigator (só imprime a contagem). Retorna None se o envio
    não estiver configurado (e não for simulação).
    """
    config = None
    if not simular:
        try:
            config = carregar_configuracao_sales_navigator()
        except ConfiguracaoInvalidaError:
            print("Sales Navigator: envio de catálogo não configurado (SALES_NAVIGATOR_URL/SECRET ausentes), pulando.")
            return None

    bling = BlingClient()
    produtos = bling.listar_produtos()
    vinculos = bling.listar_vinculos_fornecedor()
    por_produto = escolher_fornecedor_por_produto(vinculos)
    nomes = resolver_nomes(bling, set(por_produto.values()))
    itens, resumo = montar_catalogo(produtos, por_produto, nomes)
    print(
        f"Catálogo Bling: {resumo['itens']} item(ns) a enviar de {resumo['produtos']} produto(s) "
        f"({resumo['sem_fornecedor']} sem fornecedor, {resumo['sem_custo']} sem custo, "
        f"{resumo['sem_sku']} sem SKU, {resumo['situacao_ignorada']} com situação ignorada)."
    )
    if simular:
        print("[simulação] Nada foi enviado ao Sales Navigator.")
        return {"total": len(itens), "gravados": 0, "rejeitados": [], "requisicoes": 0, "resumo": resumo}

    resultado = enviar_itens(itens, config.url_base, config.segredo)
    print(
        f"Sales Navigator: {resultado['gravados']}/{resultado['total']} produto(s) gravado(s), "
        f"{len(resultado['rejeitados'])} rejeitado(s) ({resultado['requisicoes']} requisições)."
    )
    for r in resultado["rejeitados"][:20]:
        print(f"  rejeitado: {r.get('sku')} - {r.get('motivo')}")
    resultado["resumo"] = resumo
    return resultado
