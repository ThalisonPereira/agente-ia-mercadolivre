"""
database/ads.py

Publicidade (Mercado Ads / Product Ads): grava e consulta as campanhas e
anúncios patrocinados coletados diariamente. Cada linha (campanha ou
anúncio, por dia) já vem com as métricas somadas pra aquele dia direto da
API do Mercado Livre - por isso somar linhas de dias diferentes é seguro
(não há dupla contagem), diferente de médias/percentuais (ACOS, ROAS,
CTR, CPC), que são recalculados a partir dos valores brutos somados, não
a média dos percentuais diários.
"""

from datetime import date, datetime

from database.conexao_turso import obter_conexao
from database.esquema import criar_tabelas

UPSERT_CAMPANHA = """
INSERT INTO ads_campanhas_diario (
    conta_id, campaign_id, data, nome, status, strategy, budget, acos_target, roas_target,
    clicks, prints, cost, cpc, ctr, acos, cvr, roas,
    direct_amount, indirect_amount, total_amount,
    direct_units_quantity, indirect_units_quantity, units_quantity, capturado_em
)
VALUES (
    :conta_id, :campaign_id, :data, :nome, :status, :strategy, :budget, :acos_target, :roas_target,
    :clicks, :prints, :cost, :cpc, :ctr, :acos, :cvr, :roas,
    :direct_amount, :indirect_amount, :total_amount,
    :direct_units_quantity, :indirect_units_quantity, :units_quantity, :capturado_em
)
ON CONFLICT(conta_id, campaign_id, data) DO UPDATE SET
    nome = excluded.nome, status = excluded.status, strategy = excluded.strategy,
    budget = excluded.budget, acos_target = excluded.acos_target, roas_target = excluded.roas_target,
    clicks = excluded.clicks, prints = excluded.prints, cost = excluded.cost, cpc = excluded.cpc,
    ctr = excluded.ctr, acos = excluded.acos, cvr = excluded.cvr, roas = excluded.roas,
    direct_amount = excluded.direct_amount, indirect_amount = excluded.indirect_amount,
    total_amount = excluded.total_amount, direct_units_quantity = excluded.direct_units_quantity,
    indirect_units_quantity = excluded.indirect_units_quantity, units_quantity = excluded.units_quantity,
    capturado_em = excluded.capturado_em;
"""

UPSERT_ANUNCIO = """
INSERT INTO ads_anuncios_diario (
    conta_id, item_id, campaign_id, data, titulo, status,
    clicks, prints, cost, cpc, acos, direct_amount, indirect_amount, total_amount,
    units_quantity, capturado_em
)
VALUES (
    :conta_id, :item_id, :campaign_id, :data, :titulo, :status,
    :clicks, :prints, :cost, :cpc, :acos, :direct_amount, :indirect_amount, :total_amount,
    :units_quantity, :capturado_em
)
ON CONFLICT(conta_id, item_id, data) DO UPDATE SET
    campaign_id = excluded.campaign_id, titulo = excluded.titulo, status = excluded.status,
    clicks = excluded.clicks, prints = excluded.prints, cost = excluded.cost, cpc = excluded.cpc,
    acos = excluded.acos, direct_amount = excluded.direct_amount, indirect_amount = excluded.indirect_amount,
    total_amount = excluded.total_amount, units_quantity = excluded.units_quantity,
    capturado_em = excluded.capturado_em;
"""


def _filtros(alias: str, conta_id: str | None, canal: str | None) -> tuple[str, dict]:
    parametros: dict = {}
    filtros_extra = ""
    if conta_id:
        filtros_extra += f" AND {alias}.conta_id = :conta_id"
        parametros["conta_id"] = conta_id
    if canal:
        filtros_extra += " AND c.canal = :canal"
        parametros["canal"] = canal
    return filtros_extra, parametros


def salvar_campanhas_do_dia(conta_id: str, campanhas: list[dict], dia: date | None = None) -> None:
    """Grava (ou atualiza) as campanhas de Ads do dia informado (padrão: hoje) pra uma conta específica."""
    criar_tabelas()
    data_str = (dia or datetime.now().date()).isoformat()
    agora = datetime.now().isoformat(timespec="seconds")

    conexao = obter_conexao()
    try:
        instrucoes = [
            (UPSERT_CAMPANHA, {
                "conta_id": conta_id,
                "campaign_id": campanha["campaign_id"],
                "data": data_str,
                "nome": campanha.get("nome", ""),
                "status": campanha.get("status", ""),
                "strategy": campanha.get("strategy", ""),
                "budget": campanha.get("budget", 0.0),
                "acos_target": campanha.get("acos_target"),
                "roas_target": campanha.get("roas_target"),
                "clicks": campanha.get("clicks", 0),
                "prints": campanha.get("prints", 0),
                "cost": campanha.get("cost", 0.0),
                "cpc": campanha.get("cpc", 0.0),
                "ctr": campanha.get("ctr", 0.0),
                "acos": campanha.get("acos", 0.0),
                "cvr": campanha.get("cvr", 0.0),
                "roas": campanha.get("roas", 0.0),
                "direct_amount": campanha.get("direct_amount", 0.0),
                "indirect_amount": campanha.get("indirect_amount", 0.0),
                "total_amount": campanha.get("total_amount", 0.0),
                "direct_units_quantity": campanha.get("direct_units_quantity", 0),
                "indirect_units_quantity": campanha.get("indirect_units_quantity", 0),
                "units_quantity": campanha.get("units_quantity", 0),
                "capturado_em": agora,
            })
            for campanha in campanhas
        ]
        conexao.executar_em_lote(instrucoes)
        conexao.commit()
        print(f"[conta: {conta_id}] {len(campanhas)} campanha(s) de Ads de {data_str} registrada(s).")
    finally:
        conexao.close()


def salvar_anuncios_do_dia(conta_id: str, anuncios: list[dict], dia: date | None = None) -> None:
    """Grava (ou atualiza) os anúncios em Ads do dia informado (padrão: hoje) pra uma conta específica."""
    criar_tabelas()
    data_str = (dia or datetime.now().date()).isoformat()
    agora = datetime.now().isoformat(timespec="seconds")

    conexao = obter_conexao()
    try:
        instrucoes = [
            (UPSERT_ANUNCIO, {
                "conta_id": conta_id,
                "item_id": anuncio["item_id"],
                "campaign_id": anuncio.get("campaign_id"),
                "data": data_str,
                "titulo": anuncio.get("titulo", ""),
                "status": anuncio.get("status", ""),
                "clicks": anuncio.get("clicks", 0),
                "prints": anuncio.get("prints", 0),
                "cost": anuncio.get("cost", 0.0),
                "cpc": anuncio.get("cpc", 0.0),
                "acos": anuncio.get("acos", 0.0),
                "direct_amount": anuncio.get("direct_amount", 0.0),
                "indirect_amount": anuncio.get("indirect_amount", 0.0),
                "total_amount": anuncio.get("total_amount", 0.0),
                "units_quantity": anuncio.get("units_quantity", 0),
                "capturado_em": agora,
            })
            for anuncio in anuncios
        ]
        conexao.executar_em_lote(instrucoes)
        conexao.commit()
        print(f"[conta: {conta_id}] {len(anuncios)} anúncio(s) de Ads de {data_str} registrado(s).")
    finally:
        conexao.close()


def obter_data_mais_recente(conta_id: str | None = None, canal: str | None = None) -> str | None:
    """Retorna a data (AAAA-MM-DD) mais recente com campanhas de Ads capturadas, restrita a conta/canal se informado."""
    filtros_extra, parametros = _filtros("a", conta_id, canal)
    sql = f"""
        SELECT MAX(a.data) AS maxima
        FROM ads_campanhas_diario a
        LEFT JOIN contas c ON c.conta_id = a.conta_id
        WHERE 1=1 {filtros_extra}
    """
    conexao = obter_conexao()
    try:
        linha = conexao.execute(sql, parametros).fetchone()
    finally:
        conexao.close()
    return linha["maxima"] if linha else None


def _recalcular_derivadas(bruto: dict) -> dict:
    """Recalcula ACOS/ROAS/CTR/CPC a partir dos valores brutos somados - nunca a média dos percentuais diários/por campanha."""
    cost = bruto["cost"]
    clicks = bruto["clicks"]
    prints = bruto["prints"]
    total_amount = bruto["total_amount"]
    return {
        **bruto,
        "ctr": round(clicks / prints * 100, 2) if prints else 0.0,
        "cpc": round(cost / clicks, 2) if clicks else 0.0,
        "acos": round(cost / total_amount * 100, 2) if total_amount else 0.0,
        "roas": round(total_amount / cost, 2) if cost else 0.0,
    }


def obter_resumo(data_inicio: str, data_fim: str, conta_id: str | None = None, canal: str | None = None) -> dict:
    """Totais de publicidade num intervalo de datas (inclusive), com ACOS/ROAS/CTR/CPC recalculados a partir dos brutos somados."""
    filtros_extra, parametros = _filtros("a", conta_id, canal)
    parametros["data_inicio"] = data_inicio
    parametros["data_fim"] = data_fim
    sql = f"""
        SELECT
            COALESCE(SUM(a.clicks), 0) AS clicks,
            COALESCE(SUM(a.prints), 0) AS prints,
            COALESCE(SUM(a.cost), 0) AS cost,
            COALESCE(SUM(a.direct_amount), 0) AS direct_amount,
            COALESCE(SUM(a.indirect_amount), 0) AS indirect_amount,
            COALESCE(SUM(a.total_amount), 0) AS total_amount,
            COALESCE(SUM(a.direct_units_quantity), 0) AS direct_units_quantity,
            COALESCE(SUM(a.indirect_units_quantity), 0) AS indirect_units_quantity,
            COALESCE(SUM(a.units_quantity), 0) AS units_quantity
        FROM ads_campanhas_diario a
        LEFT JOIN contas c ON c.conta_id = a.conta_id
        WHERE a.data BETWEEN :data_inicio AND :data_fim {filtros_extra}
    """
    conexao = obter_conexao()
    try:
        linha = conexao.execute(sql, parametros).fetchone()
    finally:
        conexao.close()

    bruto = {
        "clicks": linha["clicks"], "prints": linha["prints"], "cost": linha["cost"],
        "direct_amount": linha["direct_amount"], "indirect_amount": linha["indirect_amount"],
        "total_amount": linha["total_amount"], "direct_units_quantity": linha["direct_units_quantity"],
        "indirect_units_quantity": linha["indirect_units_quantity"], "units_quantity": linha["units_quantity"],
    }
    return _recalcular_derivadas(bruto)


def obter_campanhas(
    data_inicio: str, data_fim: str, conta_id: str | None = None, canal: str | None = None
) -> list[dict]:
    """Campanhas de Ads (1 linha por campanha) com métricas somadas num intervalo de datas, ordenado por gasto."""
    filtros_extra, parametros = _filtros("a", conta_id, canal)
    parametros["data_inicio"] = data_inicio
    parametros["data_fim"] = data_fim
    sql = f"""
        SELECT
            a.conta_id, a.campaign_id,
            MAX(a.nome) AS nome, MAX(a.status) AS status, MAX(a.strategy) AS strategy,
            MAX(a.budget) AS budget, MAX(a.acos_target) AS acos_target, MAX(a.roas_target) AS roas_target,
            COALESCE(SUM(a.clicks), 0) AS clicks,
            COALESCE(SUM(a.prints), 0) AS prints,
            COALESCE(SUM(a.cost), 0) AS cost,
            COALESCE(SUM(a.direct_amount), 0) AS direct_amount,
            COALESCE(SUM(a.indirect_amount), 0) AS indirect_amount,
            COALESCE(SUM(a.total_amount), 0) AS total_amount,
            COALESCE(SUM(a.direct_units_quantity), 0) AS direct_units_quantity,
            COALESCE(SUM(a.indirect_units_quantity), 0) AS indirect_units_quantity,
            COALESCE(SUM(a.units_quantity), 0) AS units_quantity
        FROM ads_campanhas_diario a
        LEFT JOIN contas c ON c.conta_id = a.conta_id
        WHERE a.data BETWEEN :data_inicio AND :data_fim {filtros_extra}
        GROUP BY a.conta_id, a.campaign_id
        ORDER BY cost DESC
    """
    conexao = obter_conexao()
    try:
        linhas = conexao.execute(sql, parametros).fetchall()
    finally:
        conexao.close()

    resultado = []
    for linha in linhas:
        bruto = {
            "clicks": linha["clicks"], "prints": linha["prints"], "cost": linha["cost"],
            "direct_amount": linha["direct_amount"], "indirect_amount": linha["indirect_amount"],
            "total_amount": linha["total_amount"], "direct_units_quantity": linha["direct_units_quantity"],
            "indirect_units_quantity": linha["indirect_units_quantity"], "units_quantity": linha["units_quantity"],
        }
        resultado.append({
            "conta_id": linha["conta_id"],
            "campaign_id": linha["campaign_id"],
            "nome": linha["nome"],
            "status": linha["status"],
            "strategy": linha["strategy"],
            "budget": linha["budget"],
            "acos_target": linha["acos_target"],
            "roas_target": linha["roas_target"],
            **_recalcular_derivadas(bruto),
        })
    return resultado


def obter_anuncios(
    data_inicio: str, data_fim: str, conta_id: str | None = None, canal: str | None = None, top_n: int = 20
) -> list[dict]:
    """Anúncios em Ads (1 linha por anúncio) com métricas somadas num intervalo de datas, top N por gasto."""
    filtros_extra, parametros = _filtros("a", conta_id, canal)
    parametros["data_inicio"] = data_inicio
    parametros["data_fim"] = data_fim
    parametros["top_n"] = top_n
    sql = f"""
        SELECT
            a.conta_id, a.item_id,
            MAX(a.titulo) AS titulo, MAX(a.status) AS status,
            COALESCE(SUM(a.clicks), 0) AS clicks,
            COALESCE(SUM(a.prints), 0) AS prints,
            COALESCE(SUM(a.cost), 0) AS cost,
            COALESCE(SUM(a.direct_amount), 0) AS direct_amount,
            COALESCE(SUM(a.indirect_amount), 0) AS indirect_amount,
            COALESCE(SUM(a.total_amount), 0) AS total_amount,
            COALESCE(SUM(a.units_quantity), 0) AS units_quantity
        FROM ads_anuncios_diario a
        LEFT JOIN contas c ON c.conta_id = a.conta_id
        WHERE a.data BETWEEN :data_inicio AND :data_fim {filtros_extra}
        GROUP BY a.conta_id, a.item_id
        ORDER BY cost DESC
        LIMIT :top_n
    """
    conexao = obter_conexao()
    try:
        linhas = conexao.execute(sql, parametros).fetchall()
    finally:
        conexao.close()

    resultado = []
    for linha in linhas:
        cost = linha["cost"]
        clicks = linha["clicks"]
        total_amount = linha["total_amount"]
        resultado.append({
            "conta_id": linha["conta_id"],
            "item_id": linha["item_id"],
            "titulo": linha["titulo"],
            "status": linha["status"],
            "clicks": clicks,
            "prints": linha["prints"],
            "cost": cost,
            "cpc": round(cost / clicks, 2) if clicks else 0.0,
            "acos": round(cost / total_amount * 100, 2) if total_amount else 0.0,
            "total_amount": total_amount,
            "units_quantity": linha["units_quantity"],
        })
    return resultado
