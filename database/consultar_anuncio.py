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
    termo: str, data_inicio: str | None = None, data_fim: str | None = None
) -> list[dict]:
    """
    Busca o desempenho (visitas/vendas/receita somados) de anúncios cujo SKU
    ou título contenha TODAS as palavras do termo informado (cada palavra
    pode aparecer em qualquer ordem/posição - "bancada 120cm" casa com
    "Bancada Gourmet Ilha ... 120cm", não exige a frase inteira como
    substring contínua), num intervalo de datas.

    Se data_inicio/data_fim não forem informados, usa os últimos 30 dias a
    partir do dado mais recente disponível no banco. Pode casar mais de um
    anúncio (ex: termo genérico) - retorna um item por anúncio encontrado.
    """
    palavras = termo.split()
    if not palavras:
        return []

    condicoes = " AND ".join(
        f"(a.sku LIKE :palavra{i} OR a.titulo LIKE :palavra{i})" for i in range(len(palavras))
    )
    parametros = {f"palavra{i}": f"%{palavra}%" for i, palavra in enumerate(palavras)}

    sql = f"""
        SELECT
            a.item_id,
            a.titulo,
            a.sku,
            SUM(h.visitas) AS total_visitas,
            SUM(h.vendas_quantidade) AS total_vendas,
            SUM(h.receita) AS total_receita,
            MIN(h.data_snapshot) AS data_inicio,
            MAX(h.data_snapshot) AS data_fim
        FROM historico_anuncios_diario h
        JOIN anuncios a ON a.item_id = h.item_id
        WHERE {condicoes}
          AND h.data_snapshot >= :data_inicio
          AND h.data_snapshot <= :data_fim
        GROUP BY a.item_id, a.titulo, a.sku
        ORDER BY total_receita DESC
    """

    conexao = obter_conexao()
    try:
        if not data_inicio or not data_fim:
            linha = conexao.execute(
                "SELECT MAX(data_snapshot) AS maxima FROM historico_anuncios_diario"
            ).fetchone()
            if linha is None or linha["maxima"] is None:
                return []
            maxima = linha["maxima"]
            data_fim = data_fim or maxima
            data_inicio = data_inicio or (date.fromisoformat(maxima) - timedelta(days=30)).isoformat()

        parametros["data_inicio"] = data_inicio
        parametros["data_fim"] = data_fim
        linhas = conexao.execute(sql, parametros).fetchall()
    finally:
        conexao.close()

    return [
        {
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
