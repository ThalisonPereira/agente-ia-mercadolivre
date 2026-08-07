"""
database/custo_produtos.py

Cache local do custo de produto do Bling (por SKU), sincronizado 1x por
dia junto da rotina - fonte pro cálculo de margem em database/extrato.py.
Não é multi-conta: o Bling é uma credencial única (ver integrations/bling.py).
"""

from datetime import datetime

from database.conexao_turso import obter_conexao
from database.esquema import criar_tabelas

UPSERT_CUSTO = """
INSERT INTO custo_produtos (sku, produto_id_bling, nome, preco_custo, atualizado_em)
VALUES (:sku, :produto_id_bling, :nome, :preco_custo, :atualizado_em)
ON CONFLICT(sku) DO UPDATE SET
    produto_id_bling = excluded.produto_id_bling,
    nome = excluded.nome,
    preco_custo = excluded.preco_custo,
    atualizado_em = excluded.atualizado_em;
"""


def sincronizar(produtos_bling: list[dict]) -> int:
    """
    Grava (ou atualiza) o custo de cada produto retornado por
    BlingClient.listar_produtos() - cada item deve ter as chaves
    'codigo' (SKU), 'id', 'nome', 'precoCusto'. Produtos sem 'codigo'
    (SKU vazio) são ignorados - não dá pra cruzar com o Mercado Livre
    sem SKU.
    """
    criar_tabelas()
    agora = datetime.now().isoformat(timespec="seconds")

    instrucoes = []
    ignorados = 0
    for produto in produtos_bling:
        sku = produto.get("codigo")
        if not sku:
            ignorados += 1
            continue
        instrucoes.append((UPSERT_CUSTO, {
            "sku": sku,
            "produto_id_bling": str(produto.get("id", "")),
            "nome": produto.get("nome", ""),
            "preco_custo": produto.get("precoCusto", 0.0),
            "atualizado_em": agora,
        }))

    conexao = obter_conexao()
    try:
        conexao.executar_em_lote(instrucoes)
        conexao.commit()
    finally:
        conexao.close()

    print(f"Custo de {len(instrucoes)} produto(s) sincronizado(s) do Bling ({ignorados} sem SKU, ignorado(s)).")
    return len(instrucoes)


def obter_custo(sku: str) -> float | None:
    """
    Retorna o custo de um SKU, ou None se o SKU não foi encontrado no
    Bling OU o custo cadastrado é zero (produto "pai"/kit sem custo
    próprio - ver integrations/bling.py) - None sinaliza "custo
    desconhecido" pro cálculo de margem, pra não inflar a margem
    tratando esses casos como custo real igual a zero.
    """
    conexao = obter_conexao()
    try:
        linha = conexao.execute(
            "SELECT preco_custo FROM custo_produtos WHERE sku = :sku", {"sku": sku}
        ).fetchone()
    finally:
        conexao.close()

    if linha is None or not linha["preco_custo"]:
        return None
    return linha["preco_custo"]
