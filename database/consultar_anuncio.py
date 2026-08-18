"""
database/consultar_anuncio.py

Busca o desempenho agregado de um anúncio específico, por SKU ou termo do
título. Usado pela ferramenta consultar_sku do assistente de IA
(agents/assistente_ia.py) - retorna só o total do período pedido, não uma
linha por dia, pra manter a resposta compacta.
"""

from datetime import date, timedelta

from database.conexao_turso import obter_conexao


def buscar_por_sku_ou_titulo(
    termo: str,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    conta_id: str | None = None,
    canal: str | None = None,
) -> list[dict]:
    """
    Busca o desempenho (visitas/vendas/receita somados) de anúncios cujo SKU,
    item_id (ex: colado direto da URL/painel do Mercado Livre, com ou sem o
    prefixo "MLB") ou título contenha TODAS as palavras do termo informado
    (cada palavra pode aparecer em qualquer ordem/posição - "bancada 120cm"
    casa com "Bancada Gourmet Ilha ... 120cm", não exige a frase inteira como
    substring contínua), num intervalo de datas. Restringe a uma conta
    específica (`conta_id`) ou a um canal inteiro (`canal`) se informado;
    senão, busca em todas as contas.

    Se data_inicio/data_fim não forem informados, usa os últimos 30 dias a
    partir do dado mais recente disponível no banco - já respeitando o
    filtro de conta_id/canal, pra não cair numa data em que essa conta
    específica não tem histórico. Pode casar mais de um anúncio (ex: termo
    genérico, ou o mesmo produto em contas diferentes) - retorna um item
    por (conta, anúncio) encontrado.
    """
    palavras = termo.split()
    if not palavras:
        return []

    condicoes = " AND ".join(
        f"(a.sku LIKE :palavra{i} OR a.titulo LIKE :palavra{i} OR a.item_id LIKE :palavra{i})"
        for i in range(len(palavras))
    )
    parametros = {f"palavra{i}": f"%{palavra}%" for i, palavra in enumerate(palavras)}

    filtros_extra = ""
    if conta_id:
        filtros_extra += " AND h.conta_id = :conta_id"
    if canal:
        filtros_extra += " AND c.canal = :canal"

    sql = f"""
        SELECT
            h.conta_id,
            a.item_id,
            a.titulo,
            a.sku,
            COALESCE(SUM(h.visitas), 0) AS total_visitas,
            COALESCE(SUM(h.vendas_quantidade), 0) AS total_vendas,
            COALESCE(SUM(h.receita), 0) AS total_receita,
            MIN(h.data_snapshot) AS data_inicio,
            MAX(h.data_snapshot) AS data_fim
        FROM historico_anuncios_diario h
        JOIN anuncios a ON a.conta_id = h.conta_id AND a.item_id = h.item_id
        LEFT JOIN contas c ON c.conta_id = h.conta_id
        WHERE {condicoes}
          AND h.data_snapshot >= :data_inicio
          AND h.data_snapshot <= :data_fim
          {filtros_extra}
        GROUP BY h.conta_id, a.item_id, a.titulo, a.sku
        ORDER BY total_receita DESC
    """

    conexao = obter_conexao()
    try:
        if not data_inicio or not data_fim:
            filtros_data_maxima = ""
            parametros_data_maxima = {}
            if conta_id:
                filtros_data_maxima += " AND h.conta_id = :conta_id"
                parametros_data_maxima["conta_id"] = conta_id
            if canal:
                filtros_data_maxima += " AND c.canal = :canal"
                parametros_data_maxima["canal"] = canal
            linha = conexao.execute(
                f"""
                SELECT MAX(h.data_snapshot) AS maxima
                FROM historico_anuncios_diario h
                LEFT JOIN contas c ON c.conta_id = h.conta_id
                WHERE 1=1 {filtros_data_maxima}
                """,
                parametros_data_maxima,
            ).fetchone()
            if linha is None or linha["maxima"] is None:
                return []
            maxima = linha["maxima"]
            data_fim = data_fim or maxima
            data_inicio = data_inicio or (date.fromisoformat(maxima) - timedelta(days=30)).isoformat()

        parametros["data_inicio"] = data_inicio
        parametros["data_fim"] = data_fim
        if conta_id:
            parametros["conta_id"] = conta_id
        if canal:
            parametros["canal"] = canal
        linhas = conexao.execute(sql, parametros).fetchall()
    finally:
        conexao.close()

    return [
        {
            "conta_id": linha["conta_id"],
            "item_id": linha["item_id"],
            "anuncio": linha["titulo"] or linha["item_id"],
            "sku": linha["sku"] or "",
            "periodo": f"{linha['data_inicio']} a {linha['data_fim']}",
            "visitas": linha["total_visitas"],
            "vendas": linha["total_vendas"],
            "receita": linha["total_receita"],
        }
        for linha in linhas
    ]
