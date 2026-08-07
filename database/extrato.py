"""
database/extrato.py

Extrato diário de margem por venda (linha de pedido/SKU): preço de
venda, comissão do Mercado Livre, frete pago pelo vendedor, imposto e
custo do produto (Bling), chegando na margem líquida de cada venda.

Só os valores BRUTOS ficam gravados na tabela itens_venda (ver
database/esquema.py); imposto e margem são calculados aqui, na consulta -
mesmo princípio já usado em database/pedidos.py, pra poder ajustar a
alíquota sem precisar reprocessar dados já coletados.

Assim como em database/pedidos.py, cada item é capturado 1x, no dia da
venda - por isso toda consulta aqui é pra UMA data específica, não uma
soma de período.
"""

from datetime import date, datetime

from database.conexao_turso import obter_conexao
from database.esquema import criar_tabelas

# Alíquota de imposto aplicada sobre o preço de venda BRUTO (confirmado
# com o usuário - não é sobre o valor já líquido de comissão/frete).
# Constante isolada aqui pra ser fácil de ajustar sem mexer no resto.
ALIQUOTA_IMPOSTO = 0.14

UPSERT_ITEM_VENDA = """
INSERT INTO itens_venda (
    conta_id, pedido_id, item_id, sku, titulo, data_venda,
    quantidade, preco_venda, comissao_ml, frete_vendedor, capturado_em
)
VALUES (
    :conta_id, :pedido_id, :item_id, :sku, :titulo, :data_venda,
    :quantidade, :preco_venda, :comissao_ml, :frete_vendedor, :capturado_em
)
ON CONFLICT(conta_id, pedido_id, item_id) DO UPDATE SET
    sku = excluded.sku,
    titulo = excluded.titulo,
    quantidade = excluded.quantidade,
    preco_venda = excluded.preco_venda,
    comissao_ml = excluded.comissao_ml,
    frete_vendedor = excluded.frete_vendedor,
    capturado_em = excluded.capturado_em;
"""


def _filtros(conta_id: str | None, canal: str | None) -> tuple[str, dict]:
    parametros: dict = {}
    filtros_extra = ""
    if conta_id:
        filtros_extra += " AND v.conta_id = :conta_id"
        parametros["conta_id"] = conta_id
    if canal:
        filtros_extra += " AND c.canal = :canal"
        parametros["canal"] = canal
    return filtros_extra, parametros


def salvar_itens_venda_do_dia(conta_id: str, itens: list[dict], dia: date | None = None) -> None:
    """
    Grava (ou atualiza) os itens vendidos do dia informado (padrão: hoje)
    pra uma conta específica, a partir de uma lista de dicionários já
    coletados na API, cada um com as chaves: pedido_id, item_id, sku,
    titulo, quantidade, preco_venda, comissao_ml, frete_vendedor.
    """
    criar_tabelas()

    data_venda = (dia or datetime.now().date()).isoformat()
    agora = datetime.now().isoformat(timespec="seconds")

    conexao = obter_conexao()
    try:
        instrucoes = [
            (UPSERT_ITEM_VENDA, {
                "conta_id": conta_id,
                "pedido_id": item["pedido_id"],
                "item_id": item["item_id"],
                "sku": item.get("sku", ""),
                "titulo": item.get("titulo", ""),
                "data_venda": data_venda,
                "quantidade": item.get("quantidade", 0),
                "preco_venda": item.get("preco_venda", 0.0),
                "comissao_ml": item.get("comissao_ml", 0.0),
                "frete_vendedor": item.get("frete_vendedor", 0.0),
                "capturado_em": agora,
            })
            for item in itens
        ]
        conexao.executar_em_lote(instrucoes)
        conexao.commit()
        print(f"[conta: {conta_id}] {len(itens)} item(ns) de venda de {data_venda} registrado(s).")
    finally:
        conexao.close()


def obter_data_mais_recente(conta_id: str | None = None, canal: str | None = None) -> str | None:
    """Retorna a data (AAAA-MM-DD) mais recente com itens de venda capturados, restrita a conta/canal se informado."""
    filtros_extra, parametros = _filtros(conta_id, canal)
    sql = f"""
        SELECT MAX(v.data_venda) AS maxima
        FROM itens_venda v
        LEFT JOIN contas c ON c.conta_id = v.conta_id
        WHERE 1=1 {filtros_extra}
    """
    conexao = obter_conexao()
    try:
        linha = conexao.execute(sql, parametros).fetchone()
    finally:
        conexao.close()
    return linha["maxima"] if linha else None


def _calcular_linha(linha) -> dict:
    preco_venda = linha["preco_venda"] or 0.0
    comissao_ml = linha["comissao_ml"] or 0.0
    frete_vendedor = linha["frete_vendedor"] or 0.0
    custo_produto = linha["preco_custo"] if linha["preco_custo"] else None

    valor_liquido_sem_imposto = preco_venda - comissao_ml - frete_vendedor
    imposto = preco_venda * ALIQUOTA_IMPOSTO
    valor_liquido = valor_liquido_sem_imposto - imposto
    margem = (valor_liquido - custo_produto) if custo_produto is not None else None

    return {
        "conta_id": linha["conta_id"],
        "pedido_id": linha["pedido_id"],
        "sku": linha["sku"],
        "titulo": linha["titulo"],
        "quantidade": linha["quantidade"],
        "preco_venda": preco_venda,
        "comissao_ml": comissao_ml,
        "frete_vendedor": frete_vendedor,
        "valor_liquido_sem_imposto": round(valor_liquido_sem_imposto, 2),
        "imposto": round(imposto, 2),
        "valor_liquido": round(valor_liquido, 2),
        "custo_produto": custo_produto,
        "margem": round(margem, 2) if margem is not None else None,
    }


def obter_extrato(data: str, conta_id: str | None = None, canal: str | None = None) -> list[dict]:
    """Extrato detalhado (1 linha por item vendido) de uma data específica, já com imposto/margem calculados."""
    filtros_extra, parametros = _filtros(conta_id, canal)
    parametros["data"] = data
    sql = f"""
        SELECT v.conta_id, v.pedido_id, v.sku, v.titulo, v.quantidade,
               v.preco_venda, v.comissao_ml, v.frete_vendedor,
               cp.preco_custo
        FROM itens_venda v
        LEFT JOIN contas c ON c.conta_id = v.conta_id
        LEFT JOIN custo_produtos cp ON cp.sku = v.sku
        WHERE v.data_venda = :data {filtros_extra}
        ORDER BY v.preco_venda DESC
    """
    conexao = obter_conexao()
    try:
        linhas = conexao.execute(sql, parametros).fetchall()
    finally:
        conexao.close()

    return [_calcular_linha(linha) for linha in linhas]


def obter_resumo_extrato(data: str, conta_id: str | None = None, canal: str | None = None) -> dict:
    """Totais do extrato numa data específica, incluindo quantos itens ficaram sem custo encontrado no Bling."""
    itens = obter_extrato(data, conta_id, canal)

    resumo = {
        "total_itens": len(itens),
        "total_vendido": 0.0,
        "total_comissao": 0.0,
        "total_frete": 0.0,
        "total_liquido_sem_imposto": 0.0,
        "total_imposto": 0.0,
        "total_custo": 0.0,
        "total_margem": 0.0,
        "itens_sem_custo": 0,
    }
    for item in itens:
        resumo["total_vendido"] += item["preco_venda"]
        resumo["total_comissao"] += item["comissao_ml"]
        resumo["total_frete"] += item["frete_vendedor"]
        resumo["total_liquido_sem_imposto"] += item["valor_liquido_sem_imposto"]
        resumo["total_imposto"] += item["imposto"]
        if item["custo_produto"] is None:
            resumo["itens_sem_custo"] += 1
        else:
            resumo["total_custo"] += item["custo_produto"]
            resumo["total_margem"] += item["margem"]

    return resumo
