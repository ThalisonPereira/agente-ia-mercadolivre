"""
tests/teste_ml_extrato_cancelados.py

Testes OFFLINE de coletar_extrato_do_dia: o valor original e o dia de fechamento dos pedidos cancelados/pendentes
(usados para conciliar o painel com o resumo de desempenho do Mercado Livre). Pedidos e API falsos.
Executar com:  python tests/teste_ml_extrato_cancelados.py
"""

import sys
from contextlib import nullcontext
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from integrations.canais import mercado_livre as ml  # noqa: E402


def pedido(pid, status, itens, criado="2026-11-09T09:54:14.000-03:00", fechado="2026-11-09T09:54:16.000-03:00", tags=None):
    return {"id": pid, "status": status, "date_created": criado, "date_closed": fechado, "tags": tags or [],
            "shipping": {"id": None},
            "order_items": [{"item": {"id": f"MLB{i}", "seller_sku": f"S{i}", "title": "t"}, "quantity": q, "unit_price": preco,
                             "sale_fee": 10.0} for i, (q, preco) in enumerate(itens, 1)]}


def canal(pedidos):
    c = object.__new__(ml.MercadoLivreCanal)
    c.conta_id = "teste"
    c.obter_id_vendedor = lambda: "1"
    c._bloco = lambda nome: nullcontext()
    c._pedidos_do_dia_brasilia = lambda seller, dia, status=None: pedidos
    c._obter_custo_frete_vendedor = lambda shipping_id: 0.0
    return c


def teste_cancelado_zera_o_valor_mas_guarda_o_original_e_a_data_de_fechamento():
    linhas = canal([pedido("1", "cancelled", [(5, 26.99)])]).coletar_extrato_do_dia(date(2026, 11, 9))
    assert len(linhas) == 1
    l = linhas[0]
    assert l["status"] == "cancelado" and l["preco_venda"] == 0.0 and l["comissao_ml"] == 0.0
    assert round(l["preco_venda_original"], 2) == 134.95 and l["data_fechamento"] == "2026-11-09"


def teste_pago_tem_original_igual_ao_valor_e_pendente_tambem_guarda():
    linhas = canal([pedido("2", "paid", [(2, 100.0), (1, 50.0)]), pedido("3", "confirmed", [(1, 80.0)], fechado=None)]
                   ).coletar_extrato_do_dia(date(2026, 11, 9))
    pagos = [l for l in linhas if l["status"] == "pago"]
    assert [l["preco_venda"] for l in pagos] == [200.0, 50.0] and [l["preco_venda_original"] for l in pagos] == [200.0, 50.0]
    pendente = [l for l in linhas if l["status"] == "pendente"][0]
    assert pendente["preco_venda"] == 0.0 and pendente["preco_venda_original"] == 80.0 and pendente["data_fechamento"] is None


def teste_data_de_fechamento_usa_o_calendario_de_brasilia():
    # 00:30 UTC do dia 10 = 21:30 do dia 9 em Brasília
    l = canal([pedido("4", "paid", [(1, 10.0)], fechado="2026-11-10T00:30:00.000+00:00")]).coletar_extrato_do_dia(date(2026, 11, 9))[0]
    assert l["data_fechamento"] == "2026-11-09"


def teste_upsert_nao_apaga_o_valor_original_ja_gravado():
    from database.extrato import UPSERT_ITEM_VENDA

    assert "COALESCE(excluded.preco_venda_original, itens_venda.preco_venda_original)" in UPSERT_ITEM_VENDA
    assert "COALESCE(excluded.data_fechamento, itens_venda.data_fechamento)" in UPSERT_ITEM_VENDA


if __name__ == "__main__":
    testes = [v for k, v in sorted(globals().items()) if k.startswith("teste_")]
    for t in testes:
        t()
        print(f"[ok] {t.__name__}")
    print(f"\n{len(testes)}/{len(testes)} testes passaram.")
