"""
tests/teste_bling_vendas_canais.py

Testes OFFLINE da coleta de vendas por canal a partir dos pedidos do Bling
(integrations/bling_vendas_canais.py): sem rede, sem Bling. Executar com:
python tests/teste_bling_vendas_canais.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import integrations.bling_vendas_canais as bv  # noqa: E402


def pedido(id_, loja, sit, itens, total=None, taxas=None, numero=1, numero_loja="X1", data="2026-10-10"):
    soma = sum(i[1] * i[2] for i in itens)
    return {
        "id": id_, "numero": numero, "numeroLoja": numero_loja, "data": data,
        "loja": {"id": loja}, "situacao": {"id": sit}, "totalProdutos": soma if total is None else total,
        "taxas": taxas if taxas is not None else {"taxaComissao": 0, "custoFrete": 0},
        "itens": [{"codigo": c, "quantidade": q, "valor": v} for c, q, v in itens],
    }


class BlingFalso:
    def __init__(self, pedidos):
        self.pedidos = {p["id"]: p for p in pedidos}

    def listar_cabecalhos_pedidos_estrito(self, ini, fim):
        # cabeçalho = só id, loja, situação, data (como a lista real)
        return [{"id": p["id"], "loja": p["loja"], "situacao": p["situacao"], "data": p["data"], "numero": p["numero"]}
                for p in self.pedidos.values()]

    def obter_pedido_venda(self, pid):
        return self.pedidos[pid]


def teste_liquido_rateia_taxas_pelos_itens():
    p = pedido(1, 203930853, 9, [("A", 1, 600.0), ("B", 2, 200.0)], taxas={"taxaComissao": 100.0, "custoFrete": 50.0})
    linhas, alertas = bv.itens_do_pedido(p, p)
    a, b = linhas
    assert (a["valor_bruto"], b["valor_bruto"]) == (600.0, 400.0)
    assert (a["valor_liquido"], b["valor_liquido"]) == (510.0, 340.0)  # 150 de taxas: 60% / 40%
    assert round(a["valor_liquido"] + b["valor_liquido"], 2) == 1000.0 - 150.0
    assert a["canal"] == "ML WC" and a["usa_em_vendas"] and not alertas["taxas_ausentes"]


def teste_taxas_zeradas_viram_alerta_e_liquido_igual_ao_bruto():
    p = pedido(2, 205718407, 9, [("A", 1, 651.6)])
    linhas, alertas = bv.itens_do_pedido(p, p)
    assert alertas["taxas_ausentes"] and linhas[0]["valor_liquido"] == linhas[0]["valor_bruto"] == 651.6
    assert linhas[0]["canal"] == "SHOPEE CC"


def teste_alertas_de_soma_e_sku():
    p = pedido(3, 203931530, 9, [("", 1, 100.0)], total=90.0)
    _, alertas = bv.itens_do_pedido(p, p)
    assert alertas["soma_diverge"] and alertas["sem_sku"]


def teste_situacao_pelo_id_e_nunca_pelo_valor():
    # "CANCELADO AUT" (460765) tem situacao.valor 0 (igual a "Em aberto") mas NÃO conta.
    cancelado = pedido(10, 203930853, 460765, [("A", 1, 100.0)])
    cancelado["situacao"]["valor"] = 0
    atendido = pedido(11, 203930853, 9, [("A", 1, 100.0)])
    r = bv.coletar("2026-10-01", "2026-10-31", BlingFalso([cancelado, atendido]), pausa=0)
    assert [l["pedido_id"] for l in r["linhas"]] == [11]
    assert r["resumo"]["ignorados_por_situacao"] == 1


def teste_situacoes_que_nao_contam_e_desconhecidas():
    ps = [pedido(i, 203930853, s, [("A", 1, 10.0)]) for i, s in enumerate([73561, 21, 18, 462095, 73015, 125515, 99999], start=20)]
    r = bv.coletar("2026-10-01", "2026-10-31", BlingFalso(ps), pausa=0)
    assert r["linhas"] == []
    assert r["resumo"]["ignorados_por_situacao"] == 6 and r["resumo"]["situacao_desconhecida"] == 1
    assert r["resumo"]["situacoes_desconhecidas"] == {99999: 1}


def teste_canais_fora_da_analise_so_contam_como_observacao():
    ps = [pedido(30, 205673455, 9, [("A", 3, 100.0)]), pedido(31, 203953569, 9, [("B", 1, 50.0)]),
          pedido(32, 999, 9, [("C", 2, 10.0)]), pedido(33, 204007414, 9, [("A", 1, 100.0)])]
    r = bv.coletar("2026-10-01", "2026-10-31", BlingFalso(ps), pausa=0)
    assert [l["canal"] for l in r["linhas"]] == ["SHOPEE WC"]
    fora = {(f["canal"], f["sku"]): f["quantidade"] for f in r["fora_da_analise"]}
    assert fora == {("AMAZON", "A"): 3.0, ("SITE", "B"): 1.0, ("OUTROS", "C"): 2.0}
    assert r["resumo"]["pedidos_fora_da_analise"] == 3 and r["resumo"]["pedidos_contados"] == 1


def teste_nao_copia_dados_do_comprador():
    p = pedido(40, 203932527, 9, [("A", 1, 100.0)])
    p["contato"] = {"nome": "NOME SECRETO", "numeroDocumento": "000.000.000-00"}
    r = bv.coletar("2026-10-01", "2026-10-31", BlingFalso([p]), pausa=0)
    assert "SECRETO" not in str(r) and "000.000" not in str(r)
    assert set(r["linhas"][0]) == {"pedido_id", "numero", "numero_loja", "data", "loja_id", "canal", "usa_em_vendas",
                                   "situacao_id", "sku", "quantidade", "valor_bruto", "valor_liquido"}


def teste_totais_por_canal():
    ps = [pedido(50, 203930853, 9, [("A", 2, 100.0)], taxas={"taxaComissao": 20.0, "custoFrete": 0}),
          pedido(51, 203930853, 9, [("B", 1, 50.0)]), pedido(52, 203931530, 9, [("A", 1, 10.0)])]
    r = bv.coletar("2026-10-01", "2026-10-31", BlingFalso(ps), pausa=0)
    t = bv.totais_por_canal(r["linhas"])
    assert t["ML WC"] == {"pedidos": 2, "unidades": 3.0, "bruto": 250.0, "liquido": 230.0}
    assert t["ML HC"]["pedidos"] == 1


if __name__ == "__main__":
    testes = [v for k, v in sorted(globals().items()) if k.startswith("teste_")]
    for t in testes:
        t()
        print(f"[ok] {t.__name__}")
    print(f"\n{len(testes)}/{len(testes)} testes passaram.")
