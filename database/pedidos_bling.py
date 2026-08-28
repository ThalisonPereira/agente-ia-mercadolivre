"""
database/pedidos_bling.py

Cache local do número de pedido do Bling, cruzado pelo pedido do Mercado
Livre - fonte pro extrato de margem (database/extrato.py) exibir os dois
números lado a lado (venda no ML, pedido no Bling), pra facilitar
conferência manual entre os sistemas. Não é multi-conta: o Bling é uma
credencial única (ver integrations/bling.py).
"""

from datetime import datetime

from database.conexao_supabase import obter_conexao
from database.esquema import criar_tabelas

UPSERT_PEDIDO_BLING = """
INSERT INTO pedidos_bling (numero_loja, numero_bling, id_bling, atualizado_em)
VALUES (%(numero_loja)s, %(numero_bling)s, %(id_bling)s, %(atualizado_em)s)
ON CONFLICT(numero_loja) DO UPDATE SET
    numero_bling = excluded.numero_bling,
    id_bling = excluded.id_bling,
    atualizado_em = excluded.atualizado_em;
"""


def sincronizar(pedidos_bling: list[dict]) -> int:
    """
    Grava (ou atualiza) o cruzamento de cada pedido retornado por
    BlingClient.listar_pedidos_vendas() - cada item deve ter as chaves
    'numero' (número simples do Bling), 'numeroLoja' e 'id'. Pedidos sem
    'numeroLoja' (não vieram de nenhum canal/loja integrada, ex: venda
    balcão lançada manualmente) são ignorados - não têm o que cruzar.
    """
    criar_tabelas()
    agora = datetime.now().isoformat(timespec="seconds")

    instrucoes = []
    ignorados = 0
    for pedido in pedidos_bling:
        numero_loja = pedido.get("numeroLoja")
        if not numero_loja:
            ignorados += 1
            continue
        instrucoes.append((UPSERT_PEDIDO_BLING, {
            "numero_loja": numero_loja,
            "numero_bling": str(pedido.get("numero", "")),
            "id_bling": str(pedido.get("id", "")),
            "atualizado_em": agora,
        }))

    if instrucoes:
        conexao = obter_conexao()
        try:
            conexao.executar_em_lote(instrucoes)
            conexao.commit()
        finally:
            conexao.close()

    print(f"{len(instrucoes)} pedido(s) do Bling cruzado(s) com o canal ({ignorados} sem número de loja, ignorado(s)).")
    return len(instrucoes)


def obter_numero_bling(numero_loja: str) -> str | None:
    """Retorna o número simples do pedido no Bling pro pedido_id (numeroLoja) informado, ou None se não houver."""
    if not numero_loja:
        return None
    conexao = obter_conexao()
    try:
        linha = conexao.execute(
            "SELECT numero_bling FROM pedidos_bling WHERE numero_loja = %(numero_loja)s",
            {"numero_loja": numero_loja},
        ).fetchone()
    finally:
        conexao.close()
    return linha["numero_bling"] if linha else None
