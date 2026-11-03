"""
integrations/liquido_agente.py

Preenche o líquido dos pedidos do Mercado Livre em que o Bling NÃO trouxe taxa nenhuma (comissão e frete zerados),
usando a comissão e o frete que o agente já guarda em itens_venda para os mesmos pedidos do ML.

Validação feita em 1.810 pedidos que têm taxa nos dois lados: diferença mediana R$ 0,00 e total a 2%; quando
divergem, o agente cobra mais (o Bling às vezes traz só o frete ou só a comissão), nunca menos.

Só toca no arquivo local. Só considera pedidos do ML cujos pedidos de dentro do pacote estão TODOS no agente com
status 'pago' e com algum valor de taxa; senão deixa como está (continua pendente). Nunca grava taxa maior que o bruto.
"""

from database import vendas_bling_local as loja_local

ORIGEM_AGENTE = "agente"
LOTE_IDS = 500


def ratear_taxas(brutos: list[float], taxas: float) -> list[float]:
    """Líquido por item: bruto menos a parte proporcional das taxas; os centavos fecham no maior item."""
    total = sum(brutos)
    if total <= 0:
        return [round(b, 2) for b in brutos]
    partes = [round(taxas * b / total, 2) for b in brutos]
    partes[brutos.index(max(brutos))] += round(taxas - sum(partes), 2)
    return [round(b - p, 2) for b, p in zip(brutos, partes)]


def _taxas_do_agente(conexao_agente, ids: list[str]) -> dict[str, tuple[float, float]]:
    """pedido do ML -> (comissão, frete), só de itens 'pago' com comissão informada."""
    saida: dict[str, tuple[float, float]] = {}
    for i in range(0, len(ids), LOTE_IDS):
        lote = ids[i:i + LOTE_IDS]
        for r in conexao_agente.execute(
            "SELECT pedido_id, SUM(COALESCE(comissao_ml, 0)) AS com, SUM(COALESCE(frete_vendedor, 0)) AS fr, "
            "COUNT(comissao_ml) AS com_informada FROM itens_venda WHERE status = 'pago' AND pedido_id = ANY(%(ids)s) "
            "GROUP BY pedido_id", {"ids": lote}).fetchall():
            if r["com_informada"]:
                saida[str(r["pedido_id"])] = (float(r["com"]), float(r["fr"]))
    return saida


def preencher_liquido_pelo_agente(con, conexao_agente, log=print) -> dict:
    """Retorna {candidatos, preenchidos, sem_dado_no_agente, taxa_maior_que_bruto}."""
    pedidos = con.execute(
        "SELECT pedido_id, ml_order_ids FROM pedidos WHERE usa_em_vendas = 1 AND conta_venda = 1 AND detalhe_ok = 1 "
        "AND taxas_ausentes = 1 AND canal LIKE 'ML %' AND COALESCE(ml_order_ids, '') <> ''").fetchall()
    resumo = {"candidatos": len(pedidos), "preenchidos": 0, "sem_dado_no_agente": 0, "taxa_maior_que_bruto": 0}
    if not pedidos:
        return resumo
    todos = sorted({x for p in pedidos for x in p["ml_order_ids"].split(",") if x})
    taxas = _taxas_do_agente(conexao_agente, todos)
    for p in pedidos:
        ids = [x for x in p["ml_order_ids"].split(",") if x]
        if not all(i in taxas for i in ids):
            resumo["sem_dado_no_agente"] += 1
            continue
        total_taxas = round(sum(taxas[i][0] + taxas[i][1] for i in ids), 2)
        itens = con.execute("SELECT linha, valor_bruto FROM itens WHERE pedido_id = ? ORDER BY linha", (p["pedido_id"],)).fetchall()
        brutos = [float(i["valor_bruto"]) for i in itens]
        if total_taxas <= 0:
            resumo["sem_dado_no_agente"] += 1
            continue
        if total_taxas > sum(brutos):
            resumo["taxa_maior_que_bruto"] += 1
            continue
        liquidos = ratear_taxas(brutos, total_taxas)
        with con:
            con.executemany("UPDATE itens SET valor_liquido = ? WHERE pedido_id = ? AND linha = ?",
                            [(liq, p["pedido_id"], i["linha"]) for liq, i in zip(liquidos, itens)])
            con.execute("UPDATE pedidos SET taxas_ausentes = 0, liquido_origem = ? WHERE pedido_id = ?", (ORIGEM_AGENTE, p["pedido_id"]))
        resumo["preenchidos"] += 1
    log(f"Líquido pelo agente: {resumo}")
    return resumo


def completar_liquido_pelo_agente(con, conexao_agente, dias: int | None = None, tolerancia: float = 2.0, hoje=None, log=print) -> dict:
    """
    Pedidos do ML em que o Bling trouxe taxa, mas INCOMPLETA (só o frete ou só a comissão): se o agente tem
    comissão + frete maiores que as taxas do Bling por mais que a tolerância (R$), usa as do agente.
    Nunca REDUZ taxa: se o Bling tiver taxa igual ou maior, não mexe. dias=None olha todo o histórico; com um número,
    só os pedidos registrados nos últimos N dias. Retorna {candidatos, completados, sem_dado_no_agente, taxa_maior_que_bruto}.
    """
    from datetime import date, timedelta

    hoje = hoje or date.today()
    filtro, params = "", ()
    if dias is not None:
        filtro, params = " AND data_bling >= ?", ((hoje - timedelta(days=dias)).isoformat(),)
    pedidos = con.execute(
        "SELECT pedido_id, ml_order_ids FROM pedidos WHERE usa_em_vendas = 1 AND conta_venda = 1 AND detalhe_ok = 1 "
        "AND taxas_ausentes = 0 AND canal LIKE 'ML %' AND COALESCE(ml_order_ids, '') <> '' "
        "AND COALESCE(liquido_origem, 'bling') <> ?" + filtro, (ORIGEM_AGENTE,) + params).fetchall()
    resumo = {"candidatos": len(pedidos), "completados": 0, "sem_dado_no_agente": 0, "taxa_maior_que_bruto": 0}
    if not pedidos:
        return resumo
    taxas = _taxas_do_agente(conexao_agente, sorted({x for p in pedidos for x in p["ml_order_ids"].split(",") if x}))
    for p in pedidos:
        ids = [x for x in p["ml_order_ids"].split(",") if x]
        if not all(i in taxas for i in ids):
            resumo["sem_dado_no_agente"] += 1
            continue
        taxas_agente = round(sum(taxas[i][0] + taxas[i][1] for i in ids), 2)
        itens = con.execute("SELECT linha, valor_bruto, valor_liquido FROM itens WHERE pedido_id = ? ORDER BY linha", (p["pedido_id"],)).fetchall()
        brutos = [float(i["valor_bruto"]) for i in itens]
        taxas_bling = round(sum(float(i["valor_bruto"]) - float(i["valor_liquido"]) for i in itens), 2)
        if taxas_agente - taxas_bling <= tolerancia:
            continue
        if taxas_agente > sum(brutos):
            resumo["taxa_maior_que_bruto"] += 1
            continue
        liquidos = ratear_taxas(brutos, taxas_agente)
        with con:
            con.executemany("UPDATE itens SET valor_liquido = ? WHERE pedido_id = ? AND linha = ?",
                            [(liq, p["pedido_id"], i["linha"]) for liq, i in zip(liquidos, itens)])
            con.execute("UPDATE pedidos SET liquido_origem = ? WHERE pedido_id = ?", (ORIGEM_AGENTE, p["pedido_id"]))
        resumo["completados"] += 1
    log(f"Líquido completado pelo agente: {resumo}")
    return resumo
