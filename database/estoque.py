"""
database/estoque.py

Alerta de inconsistência de estoque entre o Bling (estoque físico real,
único, compartilhado pelas 3 contas do Mercado Livre) e o que está
publicado nos anúncios ativos de cada conta - e sinaliza anúncios bem
ranqueados perto de pausar por falta de estoque.

Somente leitura/alerta - este módulo NUNCA escreve estoque em nenhum
sistema externo (Bling ou Mercado Livre), só compara o que já foi
coletado (database/custo_produtos.py, database/capturar_snapshot.py).
"""

from datetime import date, timedelta

from database.conexao_supabase import obter_conexao
from database.ranking import obter_ranking

# Um anúncio ranqueado entra na lista de risco quando o estoque restante
# não deve durar mais que esse tanto de dias, pelo ritmo médio de venda
# recente - ou quando o estoque absoluto já é baixíssimo (cobre o caso de
# item com pouquíssima venda mas quase zerado, ex: 1 unidade).
LIMITE_DIAS_RESTANTES = 5
ESTOQUE_MINIMO_ABSOLUTO = 3


def obter_divergencias() -> list[dict]:
    """
    Compara, por SKU, o estoque real no Bling com a soma do estoque
    publicado em todos os anúncios ATIVOS (de qualquer conta) daquele SKU.

    categoria:
    - "risco_venda_sem_estoque": publicado mais do que existe de verdade -
      pode vender sem ter o produto (o caso grave).
    - "estoque_nao_publicado": tem mais estoque real do que publicado -
      oportunidade perdida de venda, não é urgente.
    - "sem_controle_bling": SKU tem anúncio ativo mas nunca foi
      sincronizado do Bling (sem linha em custo_produtos) - sinalizado,
      não escondido, mesmo princípio já usado pro custo desconhecido no
      Extrato.
    """
    sql = """
        SELECT
            a.sku,
            SUM(a.estoque_disponivel) AS soma_ml,
            COUNT(*) AS anuncios_ativos,
            MAX(cp.estoque_saldo) AS saldo_bling,
            BOOL_OR(cp.sku IS NULL) AS sem_bling
        FROM anuncios a
        LEFT JOIN custo_produtos cp ON cp.sku = a.sku
        WHERE a.status = 'active' AND a.sku IS NOT NULL AND a.sku != ''
        GROUP BY a.sku
    """
    conexao = obter_conexao()
    try:
        linhas = conexao.execute(sql).fetchall()
    finally:
        conexao.close()

    resultado = []
    for linha in linhas:
        soma_ml = linha["soma_ml"] or 0
        sem_bling = linha["sem_bling"]
        saldo_bling = linha["saldo_bling"]

        if sem_bling or saldo_bling is None:
            categoria = "sem_controle_bling"
            diferenca = None
        else:
            diferenca = soma_ml - saldo_bling
            categoria = (
                "risco_venda_sem_estoque" if diferenca > 0
                else "estoque_nao_publicado" if diferenca < 0
                else "ok"
            )

        if categoria == "ok":
            continue

        resultado.append({
            "sku": linha["sku"],
            "soma_ml": soma_ml,
            "anuncios_ativos": linha["anuncios_ativos"],
            "saldo_bling": saldo_bling,
            "diferenca": diferenca,
            "categoria": categoria,
        })

    resultado.sort(key=lambda x: (x["diferenca"] is None, -(x["diferenca"] or 0)))
    return resultado


def _anuncios_ativos_com_media_diaria(data_inicio: str) -> dict[str, dict]:
    """
    Item_id -> {estoque_disponivel, media_diaria} pra todos os anúncios
    ativos. 'data_inicio' já vem calculada em Python (mesma convenção de
    database/ranking.py) porque data_snapshot é TEXT (ISO 'AAAA-MM-DD'),
    comparação lexicográfica direta - sem aritmética de data no SQL.
    """
    sql = """
        SELECT
            a.conta_id, a.item_id, a.estoque_disponivel,
            COALESCE(AVG(h.vendas_quantidade), 0) AS media_diaria
        FROM anuncios a
        LEFT JOIN historico_anuncios_diario h
            ON h.conta_id = a.conta_id AND h.item_id = a.item_id
            AND h.data_snapshot >= %(data_inicio)s
        WHERE a.status = 'active'
        GROUP BY a.conta_id, a.item_id, a.estoque_disponivel
    """
    conexao = obter_conexao()
    try:
        linhas = conexao.execute(sql, {"data_inicio": data_inicio}).fetchall()
    finally:
        conexao.close()
    return {
        f"{linha['conta_id']}::{linha['item_id']}": {
            "estoque_disponivel": linha["estoque_disponivel"],
            "media_diaria": float(linha["media_diaria"]),
        }
        for linha in linhas
    }


def obter_anuncios_em_risco(
    dias_janela_velocidade: int = 14,
    limite_dias_restantes: int = LIMITE_DIAS_RESTANTES,
    estoque_minimo: int = ESTOQUE_MINIMO_ABSOLUTO,
    top_n: int = 30,
) -> list[dict]:
    """
    Cruza o top N anúncios por receita no período (mesmo ranking de
    database/ranking.py) com o estoque atual e o ritmo médio de venda
    recente, pra achar anúncios importantes perto de pausar por falta de
    estoque - situação cara, porque um anúncio pausado por estoque perde
    posição no ranking do Mercado Livre e demora a recuperar depois.
    """
    data_fim = date.today().isoformat()
    data_inicio = (date.today() - timedelta(days=dias_janela_velocidade)).isoformat()

    top_receita = obter_ranking("receita", data_inicio, data_fim, top_n=top_n)
    estado = _anuncios_ativos_com_media_diaria(data_inicio)

    resultado = []
    for anuncio in top_receita:
        chave = f"{anuncio['conta_id']}::{anuncio['item_id']}"
        info = estado.get(chave)
        if info is None:
            continue  # não está mais ativo, ou sem estoque cadastrado ainda

        estoque = info["estoque_disponivel"]
        media_diaria = info["media_diaria"]
        if estoque is None:
            continue

        dias_restantes = (estoque / media_diaria) if media_diaria > 0 else None
        em_risco = (dias_restantes is not None and dias_restantes <= limite_dias_restantes) or (
            estoque <= estoque_minimo
        )
        if not em_risco:
            continue

        resultado.append({
            "conta_id": anuncio["conta_id"],
            "item_id": anuncio["item_id"],
            "anuncio": anuncio["anuncio"],
            "sku": anuncio["sku"],
            "receita_periodo": anuncio["receita"],
            "estoque_disponivel": estoque,
            "media_diaria_vendas": round(media_diaria, 2),
            "dias_restantes_estimados": round(dias_restantes, 1) if dias_restantes is not None else None,
        })

    resultado.sort(key=lambda x: (x["dias_restantes_estimados"] is None, x["dias_restantes_estimados"] or 0))
    return resultado
