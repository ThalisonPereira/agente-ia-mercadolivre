"""
database/kpis.py

Agregações usadas pela página "Visão Geral" do dashboard: totais do
período (visitas/vendas/receita somados, todos os anúncios), série diária
para o gráfico de linha, e a data mais recente disponível (default do
seletor de período). Segue o mesmo padrão de LEFT JOIN contas com filtro
opcional por conta_id/canal usado em database/ranking.py.
"""

from database.conexao_supabase import obter_conexao


def _filtros(conta_id: str | None, canal: str | None) -> tuple[str, dict]:
    parametros: dict = {}
    filtros_extra = ""
    if conta_id:
        filtros_extra += " AND h.conta_id = %(conta_id)s"
        parametros["conta_id"] = conta_id
    if canal:
        filtros_extra += " AND c.canal = %(canal)s"
        parametros["canal"] = canal
    return filtros_extra, parametros


def obter_totais_periodo(
    data_inicio: str,
    data_fim: str,
    conta_id: str | None = None,
    canal: str | None = None,
) -> dict:
    """Soma visitas/vendas/receita de todos os anúncios no período, opcionalmente restrito a uma conta/canal."""
    filtros_extra, parametros = _filtros(conta_id, canal)
    parametros["data_inicio"] = data_inicio
    parametros["data_fim"] = data_fim

    sql = f"""
        SELECT
            COALESCE(SUM(h.visitas), 0) AS total_visitas,
            COALESCE(SUM(h.vendas_quantidade), 0) AS total_vendas,
            COALESCE(SUM(h.receita), 0) AS total_receita
        FROM historico_anuncios_diario h
        LEFT JOIN contas c ON c.conta_id = h.conta_id
        WHERE h.data_snapshot >= %(data_inicio)s AND h.data_snapshot <= %(data_fim)s
        {filtros_extra}
    """
    conexao = obter_conexao()
    try:
        linha = conexao.execute(sql, parametros).fetchone()
    finally:
        conexao.close()

    return {
        "visitas": linha["total_visitas"],
        "vendas": linha["total_vendas"],
        "receita": linha["total_receita"],
    }


def obter_serie_diaria(
    data_inicio: str,
    data_fim: str,
    conta_id: str | None = None,
    canal: str | None = None,
) -> list[dict]:
    """Totais somados por dia (todos os anúncios), pra alimentar um gráfico de linha."""
    filtros_extra, parametros = _filtros(conta_id, canal)
    parametros["data_inicio"] = data_inicio
    parametros["data_fim"] = data_fim

    sql = f"""
        SELECT
            h.data_snapshot AS data,
            COALESCE(SUM(h.visitas), 0) AS total_visitas,
            COALESCE(SUM(h.vendas_quantidade), 0) AS total_vendas,
            COALESCE(SUM(h.receita), 0) AS total_receita
        FROM historico_anuncios_diario h
        LEFT JOIN contas c ON c.conta_id = h.conta_id
        WHERE h.data_snapshot >= %(data_inicio)s AND h.data_snapshot <= %(data_fim)s
        {filtros_extra}
        GROUP BY h.data_snapshot
        ORDER BY h.data_snapshot ASC
    """
    conexao = obter_conexao()
    try:
        linhas = conexao.execute(sql, parametros).fetchall()
    finally:
        conexao.close()

    return [
        {
            "data": linha["data"],
            "visitas": linha["total_visitas"],
            "vendas": linha["total_vendas"],
            "receita": linha["total_receita"],
        }
        for linha in linhas
    ]


def obter_data_mais_recente(conta_id: str | None = None, canal: str | None = None) -> str | None:
    """
    Retorna a data (AAAA-MM-DD) mais recente com snapshot registrado,
    restrita a uma conta/canal se informado. Usada como padrão do seletor
    de período no dashboard - historico_completo.py::obter_datas_existentes
    não serve aqui porque exige conta_id obrigatório.
    """
    filtros_extra, parametros = _filtros(conta_id, canal)

    sql = f"""
        SELECT MAX(h.data_snapshot) AS maxima
        FROM historico_anuncios_diario h
        LEFT JOIN contas c ON c.conta_id = h.conta_id
        WHERE 1=1 {filtros_extra}
    """
    conexao = obter_conexao()
    try:
        linha = conexao.execute(sql, parametros).fetchone()
    finally:
        conexao.close()

    return linha["maxima"] if linha else None
