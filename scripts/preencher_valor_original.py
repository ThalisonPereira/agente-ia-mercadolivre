"""
scripts/preencher_valor_original.py

Preenche itens_venda.preco_venda_original e itens_venda.data_fechamento dos dias JÁ gravados (a rotina diária só
reprocessa os últimos 5 dias). Mexe SOMENTE nessas duas colunas: não regrava preço, comissão, frete, status nem o custo
capturado (o snapshot de custo não pode mudar retroativamente). Lê só os pedidos no Mercado Livre (sem custo de frete).

Uso: python scripts/preencher_valor_original.py AAAA-MM-DD AAAA-MM-DD [--simular]
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.conexao_supabase import obter_conexao  # noqa: E402
from database.contas import obter_contas_ativas  # noqa: E402
from database.esquema import criar_tabelas  # noqa: E402
from integrations.canais import obter_adaptador  # noqa: E402

UPDATE = """
UPDATE itens_venda SET preco_venda_original = %(original)s, data_fechamento = %(fechamento)s
WHERE conta_id = %(conta)s AND pedido_id = %(pedido)s AND item_id = %(item)s
"""


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return
    ini, fim = date.fromisoformat(sys.argv[1]), date.fromisoformat(sys.argv[2])
    simular = "--simular" in sys.argv
    criar_tabelas()  # aplica a migração das colunas, se ainda não existirem
    for conta in obter_contas_ativas():
        a = obter_adaptador(conta["conta_id"], conta["canal"])
        seller = a.obter_id_vendedor()
        con = obter_conexao()
        dia, linhas, nao_achadas = ini, 0, 0
        while dia <= fim:
            for p in a._pedidos_do_dia_brasilia(seller, dia, status=None):
                fech = a._data_fechamento_em_brasilia(p)
                for it in p.get("order_items", []):
                    params = {"original": it.get("unit_price", 0) * it.get("quantity", 0), "fechamento": fech.isoformat() if fech else None,
                              "conta": conta["conta_id"], "pedido": str(p["id"]), "item": str(it.get("item", {}).get("id"))}
                    if simular:
                        linhas += 1
                        continue
                    con.execute(UPDATE, params)
                    linhas += 1
            dia += timedelta(days=1)
        if not simular:
            con.commit()
        con.close()
        print(f"[conta: {conta['conta_id']}] {linhas} item(ns) de pedido {'lidos (simulação)' if simular else 'atualizados'} de {ini} a {fim}.")


if __name__ == "__main__":
    main()
