"""
integrations/sales_navigator_vendas.py

Envia as vendas por canal (pedidos do Bling guardados em dados_locais/vendas_bling.db) ao Sales Navigator,
pelo endpoint protegido /api/public/sync-vendas. Lê só o arquivo local; nunca toca no Bling nem no banco do agente.

O corpo leva apenas campos de negócio (o servidor também descarta qualquer outro campo). Pedido que deixou de contar
como venda (ex.: virou cancelado) vai só como cabeçalho com conta_venda = false; o servidor nunca apaga ajustes manuais.
O segredo só vai no header x-sync-secret e nunca é impresso.
"""

import time

import requests

from config.settings import ConfiguracaoInvalidaError, carregar_configuracao_sales_navigator
from database import vendas_bling_local as loja_local
from integrations.sales_navigator_catalogo import ErroFatalEnvio

CAMINHO_ENDPOINT = "/api/public/sync-vendas"
PEDIDOS_POR_REQUISICAO = 500
TIMEOUT_SEGUNDOS = 120
TENTATIVAS = 3
ESPERA_ENTRE_TENTATIVAS = 2.0


def montar_pedidos(con, data_inicial: str, data_final: str) -> list[dict]:
    """
    Pedidos cuja data de referência está no período: data real da venda (data_venda) quando existe, senão a do
    registro no Bling (pedidos que não contam como venda não têm data real).
    """
    pedidos = []
    linhas = con.execute(
        "SELECT * FROM pedidos WHERE COALESCE(data_venda, data_bling) BETWEEN ? AND ? ORDER BY pedido_id",
        (data_inicial, data_final)).fetchall()
    for p in linhas:
        itens = []
        if p["conta_venda"] and p["detalhe_ok"]:
            itens = [
                {"linha": i["linha"], "sku": i["sku"], "quantidade": i["quantidade"],
                 "valor_bruto": i["valor_bruto"], "valor_liquido": i["valor_liquido"]}
                for i in con.execute("SELECT linha, sku, quantidade, valor_bruto, valor_liquido FROM itens "
                                     "WHERE pedido_id = ? ORDER BY linha", (p["pedido_id"],))]
        pedidos.append({
            "pedido_id": p["pedido_id"], "numero": p["numero"], "numero_loja": p["numero_loja"], "loja_id": p["loja_id"],
            "canal": p["canal"], "situacao_id": p["situacao_id"], "conta_venda": bool(p["conta_venda"]),
            "data_bling": p["data_bling"], "data_venda": p["data_venda"], "data_origem": p["data_origem"],
            "total_produtos": p["total_produtos"], "taxas_ausentes": bool(p["taxas_ausentes"]),
            "soma_diverge": bool(p["soma_diverge"]), "itens": itens,
        })
    return pedidos


def _post(url: str, segredo: str, pedidos: list[dict]) -> requests.Response:
    ultimo_erro: Exception | None = None
    for tentativa in range(TENTATIVAS):
        try:
            resposta = requests.post(url, json={"pedidos": pedidos}, headers={"x-sync-secret": segredo}, timeout=TIMEOUT_SEGUNDOS)
        except requests.RequestException as erro:
            ultimo_erro = erro
        else:
            if resposta.status_code < 500:
                return resposta
            ultimo_erro = RuntimeError(f"HTTP {resposta.status_code}")
        if tentativa < TENTATIVAS - 1:
            time.sleep(ESPERA_ENTRE_TENTATIVAS)
    raise ErroFatalEnvio(f"servidor indisponível após {TENTATIVAS} tentativas ({type(ultimo_erro).__name__})")


def enviar_pedidos(pedidos: list[dict], url_base: str, segredo: str, log=print) -> dict:
    """Envia em lotes de 500 pedidos. Retorna {total, gravados, rejeitados, requisicoes}. Levanta ErroFatalEnvio."""
    url = url_base + CAMINHO_ENDPOINT
    gravados, requisicoes, rejeitados = 0, 0, []
    for i in range(0, len(pedidos), PEDIDOS_POR_REQUISICAO):
        lote = pedidos[i:i + PEDIDOS_POR_REQUISICAO]
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
        log(f"  lote {requisicoes}: {len(lote)} pedidos enviados, {corpo.get('gravados', 0)} gravados")
    return {"total": len(pedidos), "gravados": gravados, "rejeitados": rejeitados, "requisicoes": requisicoes}


def sincronizar_vendas(data_inicial: str, data_final: str, con=None, simular: bool = False, log=print) -> dict | None:
    """
    Ponto de entrada. Com simular=True só lê o arquivo local e conta (sem rede e sem exigir configuração).
    Retorna None se o envio não estiver configurado (e não for simulação).
    """
    con = con or loja_local.abrir()
    pedidos = montar_pedidos(con, data_inicial, data_final)
    com_itens = sum(1 for p in pedidos if p["itens"])
    itens = sum(len(p["itens"]) for p in pedidos)
    log(f"Vendas {data_inicial} a {data_final}: {len(pedidos)} pedido(s), {com_itens} com itens ({itens} itens), "
        f"{len(pedidos) - com_itens} só cabeçalho (não contam como venda).")
    if simular:
        log("[simulação] Nada foi enviado ao Sales Navigator.")
        return {"total": len(pedidos), "gravados": 0, "rejeitados": [], "requisicoes": 0}
    try:
        config = carregar_configuracao_sales_navigator()
    except ConfiguracaoInvalidaError:
        log("Sales Navigator: envio de vendas não configurado (SALES_NAVIGATOR_URL/SECRET ausentes), pulando.")
        return None
    resultado = enviar_pedidos(pedidos, config.url_base, config.segredo, log=log)
    log(f"Sales Navigator: {resultado['gravados']}/{resultado['total']} pedido(s) gravado(s), "
        f"{len(resultado['rejeitados'])} rejeitado(s) ({resultado['requisicoes']} requisições).")
    for r in resultado["rejeitados"][:20]:
        log(f"  rejeitado: pedido {r.get('pedido_id')} - {r.get('motivo')}")
    return resultado
