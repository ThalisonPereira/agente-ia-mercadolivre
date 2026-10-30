"""
integrations/bling_vendas_canais.py

Vendas por canal a partir dos PEDIDOS do Bling (fonte única para o Sales Navigator): lista os pedidos
de um período, abre cada um que conta como venda e devolve uma linha por item com canal, quantidade,
valor bruto e líquido (bruto menos comissão e frete que o próprio Bling guarda no pedido).

Regras (decididas com o usuário em 2026-10-29):
- Conta pela situacao.id (NUNCA situacao.valor: "CANCELADO AUT" vem com valor 0, igual a "Em aberto").
- Só as lojas de marketplace usadas em vendas (ML WC/HC/CC, Shopee WC/CC). Amazon, TikTok, manual/B2B,
  site e outras entram só como contagem de "saída fora da análise" (observação de estoque).
- Dados do comprador NUNCA são copiados: só campos de negócio saem do detalhe do pedido.
- Nada é gravado: este módulo só lê o Bling.
"""

import time
from collections import defaultdict

from integrations.bling import BlingClient, PAUSA_ENTRE_REQUISICOES

# loja.id -> (canal, usa_em_vendas)
LOJAS = {
    203930853: ("ML WC", True),
    203931530: ("ML HC", True),
    203932527: ("ML CC", True),
    204007414: ("SHOPEE WC", True),
    205718407: ("SHOPEE CC", True),
    205673455: ("AMAZON", False),
    205716062: ("TIKTOK", False),
    204193670: ("MANUAL/B2B", False),
    203953569: ("SITE", False),
}
CANAL_OUTROS = "OUTROS"

# situacao.id que CONTAM como venda.
SITUACOES_CONTAM = {6, 15, 9, 24, 57297, 64793, 105288, 65728, 67513}
# Situações conhecidas que NÃO contam (só para o relatório separar "ignorado" de "desconhecido").
SITUACOES_IGNORADAS = {12, 460765, 460766, 73015, 125515, 54642, 73561, 21, 18, 462095}


def canal_da_loja(loja_id) -> tuple[str, bool]:
    return LOJAS.get(loja_id, (CANAL_OUTROS, False))


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def itens_do_pedido(detalhe: dict, cabecalho: dict) -> tuple[list[dict], dict]:
    """
    Converte o detalhe de um pedido em linhas de venda. Retorna (linhas, alertas).
    Líquido do item = bruto - (comissão + frete) x participação do item no total dos produtos.
    Alertas: taxas_ausentes (comissão e frete zerados), soma_diverge (itens != totalProdutos), sem_sku.
    """
    loja_id = (detalhe.get("loja") or cabecalho.get("loja") or {}).get("id")
    canal, usa = canal_da_loja(loja_id)
    itens = detalhe.get("itens") or []
    brutos = [_num(i.get("valor")) * _num(i.get("quantidade")) for i in itens]
    soma = sum(brutos)
    taxas = detalhe.get("taxas") or {}
    comissao, frete = _num(taxas.get("taxaComissao")), _num(taxas.get("custoFrete"))
    alertas = {
        "taxas_ausentes": comissao == 0 and frete == 0,
        "soma_diverge": abs(soma - _num(detalhe.get("totalProdutos"))) > 0.05,
        "sem_sku": any(not str(i.get("codigo") or "").strip() for i in itens),
    }
    linhas = []
    for item, bruto in zip(itens, brutos):
        parte = (bruto / soma) if soma else 0.0
        linhas.append({
            "pedido_id": detalhe.get("id") or cabecalho.get("id"),
            "numero": detalhe.get("numero") or cabecalho.get("numero"),
            "numero_loja": str(detalhe.get("numeroLoja") or cabecalho.get("numeroLoja") or ""),
            "data": str(detalhe.get("data") or cabecalho.get("data") or "")[:10],
            "loja_id": loja_id, "canal": canal, "usa_em_vendas": usa,
            "situacao_id": (detalhe.get("situacao") or cabecalho.get("situacao") or {}).get("id"),
            "sku": str(item.get("codigo") or "").strip(),
            "quantidade": _num(item.get("quantidade")),
            "valor_bruto": round(bruto, 2),
            "valor_liquido": round(bruto - (comissao + frete) * parte, 2),
        })
    return linhas, alertas


def coletar(data_inicial: str, data_final: str, bling: BlingClient | None = None, pausa: float = PAUSA_ENTRE_REQUISICOES) -> dict:
    """
    Coleta o período. Retorna {linhas, fora_da_analise, resumo}. linhas = só canais usados em vendas e
    situações que contam. fora_da_analise = unidades por canal/dia dos demais canais (observação de estoque).
    """
    bling = bling or BlingClient()
    cabecalhos = bling.listar_cabecalhos_pedidos_estrito(data_inicial, data_final)
    resumo = defaultdict(int)
    linhas: list[dict] = []
    fora: dict[tuple, float] = defaultdict(float)
    desconhecidas: dict = defaultdict(int)
    for cab in cabecalhos:
        resumo["pedidos_no_periodo"] += 1
        sit = (cab.get("situacao") or {}).get("id")
        if sit in SITUACOES_IGNORADAS:
            resumo["ignorados_por_situacao"] += 1
            continue
        if sit not in SITUACOES_CONTAM:
            desconhecidas[sit] += 1
            resumo["situacao_desconhecida"] += 1
            continue
        _, usa = canal_da_loja((cab.get("loja") or {}).get("id"))
        detalhe = bling.obter_pedido_venda(cab["id"])
        time.sleep(pausa)
        ls, alertas = itens_do_pedido(detalhe, cab)
        for chave, ativo in alertas.items():
            if ativo and usa:
                resumo[chave] += 1
        if not usa:
            for l in ls:
                fora[(l["canal"], l["data"], l["sku"])] += l["quantidade"]
            resumo["pedidos_fora_da_analise"] += 1
            continue
        linhas.extend(ls)
        resumo["pedidos_contados"] += 1
    resumo["situacoes_desconhecidas"] = dict(desconhecidas)
    return {
        "linhas": linhas,
        "fora_da_analise": [{"canal": c, "data": d, "sku": s, "quantidade": q} for (c, d, s), q in sorted(fora.items())],
        "resumo": dict(resumo),
    }


def totais_por_canal(linhas: list[dict]) -> dict:
    """{canal: {pedidos, unidades, bruto, liquido}} - para conferir com o relatório do marketplace."""
    t: dict = defaultdict(lambda: {"pedidos": set(), "unidades": 0.0, "bruto": 0.0, "liquido": 0.0})
    for l in linhas:
        x = t[l["canal"]]
        x["pedidos"].add(l["pedido_id"])
        x["unidades"] += l["quantidade"]
        x["bruto"] += l["valor_bruto"]
        x["liquido"] += l["valor_liquido"]
    return {c: {"pedidos": len(v["pedidos"]), "unidades": v["unidades"], "bruto": round(v["bruto"], 2), "liquido": round(v["liquido"], 2)}
            for c, v in sorted(t.items())}


def simular_e_conferir(data_inicial: str, data_final: str) -> dict:
    """Só leitura. Coleta o período no Bling, imprime os totais por canal e, para o Mercado Livre,
    compara unidades e valor com os itens que o agente já guarda (soma de preco_venda, que é o valor da linha)."""
    r = coletar(data_inicial, data_final)
    totais = totais_por_canal(r["linhas"])
    print(f"\nBling, {data_inicial} a {data_final}: {r['resumo']}")
    print(f"{'canal':<11}{'pedidos':>8}{'unid.':>8}{'bruto':>13}{'liquido':>13}")
    for canal, t in totais.items():
        print(f"{canal:<11}{t['pedidos']:>8}{t['unidades']:>8.0f}{t['bruto']:>13,.2f}{t['liquido']:>13,.2f}")
    fora = {}
    for f in r["fora_da_analise"]:
        fora[f["canal"]] = fora.get(f["canal"], 0) + f["quantidade"]
    print("fora da análise (unidades):", {c: int(q) for c, q in fora.items()} or "nenhuma")

    from database.conexao_supabase import obter_conexao
    conexao = obter_conexao()
    try:
        linhas = conexao.execute(
            "SELECT conta_id, SUM(quantidade) un, SUM(preco_venda) bruto FROM itens_venda "
            "WHERE status = 'pago' AND data_venda BETWEEN %(i)s AND %(f)s GROUP BY conta_id ORDER BY conta_id",
            {"i": data_inicial, "f": data_final}).fetchall()
    finally:
        conexao.close()
    print("\nConferência com o agente (Mercado Livre):")
    print(f"{'canal':<8}{'un Bling':>10}{'un agente':>11}{'bruto Bling':>14}{'bruto agente':>14}{'dif. valor':>12}")
    for l in linhas:
        canal = f"ML {str(l['conta_id']).upper()}"
        b = totais.get(canal, {"unidades": 0, "bruto": 0.0})
        dif = (b["bruto"] / float(l["bruto"]) - 1) if l["bruto"] else 0
        print(f"{canal:<8}{b['unidades']:>10.0f}{float(l['un']):>11.0f}{b['bruto']:>14,.2f}{float(l['bruto']):>14,.2f}{dif:>11.1%}")
    return {"totais": totais, "resumo": r["resumo"]}
