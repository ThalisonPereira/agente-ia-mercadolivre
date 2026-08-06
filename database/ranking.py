"""
database/ranking.py

Ranking (top N) de anúncios por receita, visitas ou vendas, somados num
intervalo de datas. Usado pela ferramenta ranking_periodo do assistente de
IA (agents/assistente_ia.py).
"""

from database.conexao_turso import obter_conexao

# Whitelist fixa de expressões SQL válidas por métrica - nunca interpolar a
# métrica recebida diretamente na query (ela vem de uma ferramenta que o
# modelo de IA escolhe o valor, então tratamos como entrada não confiável).
_METRICAS_VALIDAS = {
    "receita": "SUM(h.receita)",
    "visitas": "SUM(h.visitas)",
    "vendas": "SUM(h.vendas_quantidade)",
}


def obter_ranking(metrica: str, data_inicio: str, data_fim: str, top_n: int = 10) -> list[dict]:
    """
    Retorna o ranking (top N) de anúncios por 'receita', 'visitas' ou
    'vendas', somados entre data_inicio e data_fim (inclusive).
    """
    if metrica not in _METRICAS_VALIDAS:
        raise ValueError(f"Métrica inválida: {metrica!r}. Use uma de {sorted(_METRICAS_VALIDAS)}.")

    expressao_ordenacao = _METRICAS_VALIDAS[metrica]
    sql = f"""
        SELECT
            a.item_id,
            a.titulo,
            a.sku,
            SUM(h.visitas) AS total_visitas,
            SUM(h.vendas_quantidade) AS total_vendas,
            SUM(h.receita) AS total_receita
        FROM historico_anuncios_diario h
        JOIN anuncios a ON a.item_id = h.item_id
        WHERE h.data_snapshot >= :data_inicio AND h.data_snapshot <= :data_fim
        GROUP BY a.item_id, a.titulo, a.sku
        ORDER BY {expressao_ordenacao} DESC
        LIMIT :top_n
    """

    conexao = obter_conexao()
    try:
        linhas = conexao.execute(sql, {
            "data_inicio": data_inicio,
            "data_fim": data_fim,
            "top_n": top_n,
        }).fetchall()
    finally:
        conexao.close()

    return [
        {
            "item_id": linha["item_id"],
            "anuncio": linha["titulo"] or linha["item_id"],
            "sku": linha["sku"] or "",
            "visitas": linha["total_visitas"],
            "vendas": linha["total_vendas"],
            "receita": linha["total_receita"],
        }
        for linha in linhas
    ]
