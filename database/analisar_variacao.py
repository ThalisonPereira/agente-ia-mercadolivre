"""
database/analisar_variacao.py

Compara dois snapshots diários (mais antigo vs. mais recente) de visitas e
vendas por anúncio, calcula a variação percentual e classifica cada anúncio
em 'Queda', 'Alta' ou 'Estável'.
"""

from database.conexao import obter_conexao

QUERY_COMPARACAO = """
SELECT
    h_novo.item_id,
    a.titulo,
    a.sku,
    h_antigo.visitas AS visitas_anterior,
    h_novo.visitas AS visitas_atual,
    h_antigo.vendas_quantidade AS vendas_anterior,
    h_novo.vendas_quantidade AS vendas_atual,
    h_novo.receita AS receita
FROM historico_anuncios_diario h_novo
JOIN historico_anuncios_diario h_antigo
    ON h_antigo.item_id = h_novo.item_id
    AND h_antigo.data_snapshot = :data_inicial
LEFT JOIN anuncios a ON a.item_id = h_novo.item_id
WHERE h_novo.data_snapshot = :data_final
"""

# Variação percentual (para cima ou para baixo) a partir da qual um anúncio
# é sinalizado como 'Queda' ou 'Alta' em vez de 'Estável'.
LIMIAR_VARIACAO = 0.30


def _variacao_percentual(anterior: float, atual: float) -> float:
    if anterior == 0:
        return 1.0 if atual > 0 else 0.0
    return (atual - anterior) / anterior


def _classificar(variacao_visitas: float, variacao_vendas: float) -> str:
    if variacao_visitas <= -LIMIAR_VARIACAO or variacao_vendas <= -LIMIAR_VARIACAO:
        return "Queda"
    if variacao_visitas >= LIMIAR_VARIACAO or variacao_vendas >= LIMIAR_VARIACAO:
        return "Alta"
    return "Estável"


def _obter_duas_datas_mais_recentes() -> tuple[str, str] | None:
    """Acha as duas datas de snapshot mais recentes já registradas."""
    conexao = obter_conexao()
    try:
        linhas = conexao.execute(
            "SELECT DISTINCT data_snapshot FROM historico_anuncios_diario "
            "ORDER BY data_snapshot DESC LIMIT 2"
        ).fetchall()
    finally:
        conexao.close()

    if len(linhas) < 2:
        return None

    data_final = linhas[0]["data_snapshot"]
    data_inicial = linhas[1]["data_snapshot"]
    return data_inicial, data_final


def obter_variacao_anuncios(
    data_inicial: str | None = None, data_final: str | None = None
) -> list[dict] | None:
    """
    Calcula a variação de visitas/vendas entre duas datas e retorna uma
    lista de dicionários (um por anúncio), já com 'status' calculado.
    Retorna None se não houver snapshots suficientes para comparar.
    """
    if not data_inicial or not data_final:
        datas = _obter_duas_datas_mais_recentes()
        if not datas:
            return None
        data_inicial, data_final = datas

    conexao = obter_conexao()
    try:
        linhas = conexao.execute(
            QUERY_COMPARACAO, {"data_inicial": data_inicial, "data_final": data_final}
        ).fetchall()
    finally:
        conexao.close()

    resultado = []
    for linha in linhas:
        variacao_visitas = _variacao_percentual(linha["visitas_anterior"], linha["visitas_atual"])
        variacao_vendas = _variacao_percentual(linha["vendas_anterior"], linha["vendas_atual"])

        resultado.append({
            "data": data_final,
            "item_id": linha["item_id"],
            "anuncio": linha["titulo"] or linha["item_id"],
            "sku": linha["sku"] or "",
            "visitas": linha["visitas_atual"],
            "vendas": linha["vendas_atual"],
            "receita": linha["receita"],
            "variacao_visitas": round(variacao_visitas * 100, 1),
            "variacao_vendas": round(variacao_vendas * 100, 1),
            "status": _classificar(variacao_visitas, variacao_vendas),
        })
    return resultado
