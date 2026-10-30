"""
integrations/bling_vendas_sync.py

Etapa 1 do plano: coleta INCREMENTAL e retomável dos pedidos do Bling para o armazenamento local
(database/vendas_bling_local.py), com a data REAL da venda (integrations/data_venda.py), e a conferência
contra os itens que o agente já guarda. Só lê o Bling e o Mercado Livre; grava apenas no arquivo local.
"""

import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

from database import vendas_bling_local as loja_local
from integrations.bling_vendas_canais import SITUACOES_CONTAM, canal_da_loja, itens_do_pedido
from integrations.data_venda import ORIGEM_APROX, ResolvedorDatas


def sincronizar_periodo(data_inicial: str, data_final: str, con, bling, resolvedor: ResolvedorDatas,
                        workers: int = 2, pausa: float = 0.35, log=print) -> dict:
    """
    Sincroniza um período. O detalhe (uma chamada por pedido) só é buscado para pedido que conta como venda e
    ainda não foi salvo; dos já salvos só a situação é atualizada pelo cabeçalho (barato), assim cancelamentos
    posteriores são pegos. Cada pedido é gravado inteiro quando chega: uma interrupção só obriga a repetir o comando.
    """
    resumo = defaultdict(int)
    cabecalhos = bling.listar_cabecalhos_pedidos_estrito(data_inicial, data_final)
    a_buscar = []
    for cab in cabecalhos:
        resumo["cabecalhos"] += 1
        canal, usa = canal_da_loja((cab.get("loja") or {}).get("id"))
        conta = (cab.get("situacao") or {}).get("id") in SITUACOES_CONTAM
        existente = loja_local.obter_pedido(con, cab["id"])
        if not conta or (existente is not None and existente["detalhe_ok"]):
            loja_local.salvar_cabecalho(con, cab, canal, usa, conta)
            resumo["so_cabecalho"] += 1
        else:
            a_buscar.append(cab)

    def buscar(cab):
        # Quedas de rede passageiras (ou do banco de tokens) são comuns: tenta 3 vezes antes de desistir do pedido.
        for tentativa in range(3):
            time.sleep(pausa)
            try:
                return cab, bling.obter_pedido_venda(cab["id"])
            except Exception:
                if tentativa == 2:
                    raise
                time.sleep(2.0 * (tentativa + 1))

    falhas = []
    feitos = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futuros = {pool.submit(buscar, cab): cab for cab in a_buscar}
        for futuro in as_completed(futuros):
            cab = futuros[futuro]
            try:
                _, detalhe = futuro.result()
                linhas, alertas = itens_do_pedido(detalhe, cab)
                if not linhas:
                    resumo["sem_itens"] += 1
                    loja_local.salvar_cabecalho(con, cab, *canal_da_loja((cab.get("loja") or {}).get("id")), True)
                else:
                    p = linhas[0]
                    data, origem, ordens = resolvedor.resolver(p["canal"], p["numero_loja"], p["data"])
                    loja_local.salvar_pedido_completo(con, linhas, alertas, data, origem, ordens, detalhe.get("totalProdutos"))
                    resumo["detalhes_salvos"] += 1
                    resumo["data_aproximada"] += int(origem == ORIGEM_APROX and p["usa_em_vendas"])
            except Exception as erro:  # um pedido ruim não derruba o período; fica para a próxima execução
                falhas.append((cab.get("numero"), str(erro)[:80]))
            feitos += 1
            if feitos % 50 == 0:
                log(f"  ... {feitos}/{len(a_buscar)} pedidos")
    for p in loja_local.pendentes_de_data(con, data_inicial, data_final):
        data, origem, ordens = resolvedor.resolver(p["canal"], p["numero_loja"], p["data_bling"])
        if origem != ORIGEM_APROX:
            loja_local.atualizar_data(con, p["pedido_id"], data, origem, ordens)
            resumo["datas_refeitas"] += 1
    resumo["falhas"] = len(falhas)
    if falhas:
        log(f"  falhas ({len(falhas)}): {falhas[:5]}")
    return dict(resumo)


def sincronizar_intervalo(data_inicial: str, data_final: str, con, bling, resolvedor, dias_por_bloco: int = 7,
                          workers: int = 2, log=print) -> dict:
    """Divide o intervalo em blocos de dias (pontos de retomada) e sincroniza um a um."""
    total = defaultdict(int)
    ini = date.fromisoformat(data_inicial)
    fim = date.fromisoformat(data_final)
    while ini <= fim:
        bloco_fim = min(ini + timedelta(days=dias_por_bloco - 1), fim)
        log(f"[{ini} a {bloco_fim}]")
        r = sincronizar_periodo(ini.isoformat(), bloco_fim.isoformat(), con, bling, resolvedor, workers=workers, log=log)
        log(f"  {r}")
        for k, v in r.items():
            total[k] += v
        ini = bloco_fim + timedelta(days=1)
    return dict(total)


def conferir_com_agente(data_inicial: str, data_final: str, con, conexao_agente) -> None:
    """Compara o armazenamento local (data REAL da venda) com os itens do agente, por conta do Mercado Livre."""
    locais = {r["canal"]: r for r in loja_local.totais(con, data_inicial, data_final)}
    agente = conexao_agente.execute(
        "SELECT conta_id, SUM(quantidade) un, SUM(preco_venda) bruto, COUNT(DISTINCT pedido_id) pedidos FROM itens_venda "
        "WHERE status = 'pago' AND data_venda BETWEEN %(i)s AND %(f)s GROUP BY conta_id ORDER BY conta_id",
        {"i": data_inicial, "f": data_final}).fetchall()
    print(f"\nConferência {data_inicial} a {data_final} (data REAL da venda)")
    print(f"{'conta':<8}{'ped Bling':>10}{'ped agente':>11}{'un Bling':>10}{'un agente':>10}{'R$ Bling':>13}{'R$ agente':>13}{'dif.':>8}")
    for a in agente:
        canal = f"ML {str(a['conta_id']).upper()}"
        b = locais.get(canal)
        pb, ub, vb = (b["pedidos"], b["unidades"], b["bruto"]) if b else (0, 0, 0.0)
        dif = (vb / float(a["bruto"]) - 1) if a["bruto"] else 0
        print(f"{canal:<8}{pb:>10}{a['pedidos']:>11}{ub:>10.0f}{float(a['un']):>10.0f}{vb:>13,.0f}{float(a['bruto']):>13,.0f}{dif:>8.1%}")
    ids_bling = set()
    for r in con.execute("SELECT ml_order_ids FROM pedidos WHERE usa_em_vendas = 1 AND conta_venda = 1 AND canal LIKE 'ML %' "
                         "AND data_venda BETWEEN ? AND ?", (data_inicial, data_final)):
        ids_bling.update(x for x in (r["ml_order_ids"] or "").split(",") if x)
    ids_agente = {r["pedido_id"] for r in conexao_agente.execute(
        "SELECT DISTINCT pedido_id FROM itens_venda WHERE status = 'pago' AND data_venda BETWEEN %(i)s AND %(f)s",
        {"i": data_inicial, "f": data_final}).fetchall()}
    print(f"\nPor pedido do ML: em ambos {len(ids_bling & ids_agente)} | só no Bling {len(ids_bling - ids_agente)} | só no agente {len(ids_agente - ids_bling)}")
