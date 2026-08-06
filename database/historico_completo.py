"""
database/historico_completo.py

Busca todo o histórico já registrado (todos os dias, todos os anúncios),
usado para publicar numa aba dedicada da planilha - essa aba serve de
"memória" para o chat de IA na planilha (Apps Script) responder perguntas
sobre qualquer período já coletado, não só o snapshot mais recente.
"""

from database.conexao import obter_conexao

QUERY_HISTORICO_COMPLETO = """
SELECT
    h.data_snapshot,
    a.titulo,
    a.sku,
    h.item_id,
    h.visitas,
    h.vendas_quantidade,
    h.receita
FROM historico_anuncios_diario h
LEFT JOIN anuncios a ON a.item_id = h.item_id
ORDER BY h.data_snapshot, a.titulo
"""


def obter_datas_existentes() -> set[str]:
    """Retorna o conjunto de datas (YYYY-MM-DD) que já têm snapshot registrado."""
    conexao = obter_conexao()
    try:
        linhas = conexao.execute("SELECT DISTINCT data_snapshot FROM historico_anuncios_diario").fetchall()
    finally:
        conexao.close()
    return {linha["data_snapshot"] for linha in linhas}


def obter_historico_completo() -> list[dict]:
    """Retorna uma linha por (dia, anúncio) já registrado no banco local, em ordem cronológica."""
    conexao = obter_conexao()
    try:
        linhas = conexao.execute(QUERY_HISTORICO_COMPLETO).fetchall()
    finally:
        conexao.close()

    return [
        {
            "data": linha["data_snapshot"],
            "anuncio": linha["titulo"] or linha["item_id"],
            "sku": linha["sku"] or "",
            "item_id": linha["item_id"],
            "visitas": linha["visitas"],
            "vendas": linha["vendas_quantidade"],
            "receita": linha["receita"],
        }
        for linha in linhas
    ]
