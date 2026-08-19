"""
database/analisar_variacao.py

Compara dois snapshots diários (mais antigo vs. mais recente) de visitas e
vendas por anúncio, calcula a variação percentual e classifica cada anúncio
em 'Queda', 'Alta' ou 'Estável'. Pode ser restrito a uma conta específica,
ou combinar todas as contas (o join sempre casa por conta_id + item_id, pra
nunca misturar anúncios de contas/canais diferentes que tenham o mesmo id).
"""

from database.conexao_supabase import obter_conexao
from database.contas import obter_contas_ativas
from database.kpis import obter_data_mais_recente as _obter_data_mais_recente_conta

QUERY_COMPARACAO = """
SELECT
    h_novo.conta_id,
    h_novo.item_id,
    a.titulo,
    a.sku,
    h_antigo.visitas AS visitas_anterior,
    h_novo.visitas AS visitas_atual,
    h_antigo.vendas_quantidade AS vendas_anterior,
    h_novo.vendas_quantidade AS vendas_atual,
    COALESCE(h_novo.receita, 0) AS receita
FROM historico_anuncios_diario h_novo
JOIN historico_anuncios_diario h_antigo
    ON h_antigo.conta_id = h_novo.conta_id
    AND h_antigo.item_id = h_novo.item_id
    AND h_antigo.data_snapshot = %(data_inicial)s
LEFT JOIN anuncios a
    ON a.conta_id = h_novo.conta_id
    AND a.item_id = h_novo.item_id
LEFT JOIN contas c
    ON c.conta_id = h_novo.conta_id
WHERE h_novo.data_snapshot = %(data_final)s
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


def _obter_duas_datas_mais_recentes(
    conta_id: str | None = None, canal: str | None = None
) -> tuple[str, str] | None:
    """Acha as duas datas de snapshot mais recentes já registradas (opcionalmente restrito a conta/canal)."""
    sql = "SELECT DISTINCT h.data_snapshot FROM historico_anuncios_diario h LEFT JOIN contas c ON c.conta_id = h.conta_id"
    parametros = {}
    filtros = []
    if conta_id:
        filtros.append("h.conta_id = %(conta_id)s")
        parametros["conta_id"] = conta_id
    if canal:
        filtros.append("c.canal = %(canal)s")
        parametros["canal"] = canal
    if filtros:
        sql += " WHERE " + " AND ".join(filtros)
    sql += " ORDER BY h.data_snapshot DESC LIMIT 2"

    conexao = obter_conexao()
    try:
        linhas = conexao.execute(sql, parametros).fetchall()
    finally:
        conexao.close()

    if len(linhas) < 2:
        return None

    data_final = linhas[0]["data_snapshot"]
    data_inicial = linhas[1]["data_snapshot"]
    return data_inicial, data_final


def obter_contas_desatualizadas(data_referencia: str, canal: str | None = None) -> list[str]:
    """
    Retorna os conta_id das contas ATIVAS do canal (ou de todos os canais,
    se `canal` não for informado) cujo snapshot mais recente é anterior a
    `data_referencia` - usado pra avisar quando a comparação de Variação
    está mostrando só um subconjunto das contas do filtro escolhido (uma
    conta atrasada na coleta some silenciosamente da comparação, já que
    ela não tem linha na data escolhida - ver paginas/3_variacao.py).
    """
    contas = obter_contas_ativas(canal)
    desatualizadas = []
    for conta in contas:
        maxima = _obter_data_mais_recente_conta(conta_id=conta["conta_id"])
        if maxima is None or maxima < data_referencia:
            desatualizadas.append(conta["conta_id"])
    return desatualizadas


def obter_variacao_anuncios(
    data_inicial: str | None = None,
    data_final: str | None = None,
    conta_id: str | None = None,
    canal: str | None = None,
) -> list[dict] | None:
    """
    Calcula a variação de visitas/vendas entre duas datas e retorna uma
    lista de dicionários (um por anúncio), já com 'status' calculado.
    Restringe a uma conta específica (`conta_id`) ou a um canal inteiro
    (`canal`) se informado; senão, combina todas as contas. Retorna None se
    não houver snapshots suficientes para comparar.
    """
    if not data_inicial or not data_final:
        datas = _obter_duas_datas_mais_recentes(conta_id, canal)
        if not datas:
            return None
        data_inicial, data_final = datas

    sql = QUERY_COMPARACAO
    parametros = {"data_inicial": data_inicial, "data_final": data_final}
    if conta_id:
        sql += " AND h_novo.conta_id = %(conta_id)s"
        parametros["conta_id"] = conta_id
    if canal:
        sql += " AND c.canal = %(canal)s"
        parametros["canal"] = canal

    conexao = obter_conexao()
    try:
        linhas = conexao.execute(sql, parametros).fetchall()
    finally:
        conexao.close()

    resultado = []
    for linha in linhas:
        variacao_visitas = _variacao_percentual(linha["visitas_anterior"], linha["visitas_atual"])
        variacao_vendas = _variacao_percentual(linha["vendas_anterior"], linha["vendas_atual"])

        resultado.append({
            "data": data_final,
            "conta_id": linha["conta_id"],
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
