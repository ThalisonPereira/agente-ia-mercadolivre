"""
database/ranking.py

Ranking (top N) de anúncios por receita, visitas ou vendas, somados num
intervalo de datas. Usado pela ferramenta ranking_periodo do assistente de
IA (agents/assistente_ia.py).
"""

from database.conexao_supabase import obter_conexao

# Whitelist fixa de expressões SQL válidas por métrica - nunca interpolar a
# métrica recebida diretamente na query (ela vem de uma ferramenta que o
# modelo de IA escolhe o valor, então tratamos como entrada não confiável).
_METRICAS_VALIDAS = {
    "receita": "SUM(h.receita)",
    "visitas": "SUM(h.visitas)",
    "vendas": "SUM(h.vendas_quantidade)",
}


def obter_ranking(
    metrica: str,
    data_inicio: str,
    data_fim: str,
    top_n: int = 10,
    conta_id: str | None = None,
    canal: str | None = None,
) -> list[dict]:
    """
    Retorna o ranking (top N) de anúncios por 'receita', 'visitas' ou
    'vendas', somados entre data_inicio e data_fim (inclusive). Restringe a
    uma conta específica (`conta_id`) ou a um canal inteiro (`canal`, ex:
    "mercado_livre") se informado; senão, combina todas as contas.
    """
    if metrica not in _METRICAS_VALIDAS:
        raise ValueError(f"Métrica inválida: {metrica!r}. Use uma de {sorted(_METRICAS_VALIDAS)}.")

    expressao_ordenacao = _METRICAS_VALIDAS[metrica]
    parametros = {"data_inicio": data_inicio, "data_fim": data_fim, "top_n": top_n}

    filtros_extra = ""
    if conta_id:
        filtros_extra += " AND h.conta_id = %(conta_id)s"
        parametros["conta_id"] = conta_id
    if canal:
        filtros_extra += " AND c.canal = %(canal)s"
        parametros["canal"] = canal

    sql = f"""
        SELECT
            h.conta_id,
            a.item_id,
            a.titulo,
            a.sku,
            COALESCE(SUM(h.visitas), 0) AS total_visitas,
            COALESCE(SUM(h.vendas_quantidade), 0) AS total_vendas,
            COALESCE(SUM(h.receita), 0) AS total_receita
        FROM historico_anuncios_diario h
        JOIN anuncios a ON a.conta_id = h.conta_id AND a.item_id = h.item_id
        LEFT JOIN contas c ON c.conta_id = h.conta_id
        WHERE h.data_snapshot >= %(data_inicio)s AND h.data_snapshot <= %(data_fim)s
        {filtros_extra}
        GROUP BY h.conta_id, a.item_id, a.titulo, a.sku
        ORDER BY {expressao_ordenacao} DESC
        LIMIT %(top_n)s
    """

    conexao = obter_conexao()
    try:
        linhas = conexao.execute(sql, parametros).fetchall()
    finally:
        conexao.close()

    return [
        {
            "conta_id": linha["conta_id"],
            "item_id": linha["item_id"],
            "anuncio": linha["titulo"] or linha["item_id"],
            "sku": linha["sku"] or "",
            "visitas": linha["total_visitas"],
            "vendas": linha["total_vendas"],
            "receita": linha["total_receita"],
        }
        for linha in linhas
    ]
