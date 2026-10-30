"""
tests/teste_bling_vendas_sync.py

Testes OFFLINE da etapa 1 (armazenamento local, resolvedor de datas e sincronização incremental):
sem rede, sem Bling, sem Mercado Livre, banco SQLite em memória. Executar com:
python tests/teste_bling_vendas_sync.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from database import vendas_bling_local as loja  # noqa: E402
from integrations import bling_vendas_sync as sync  # noqa: E402
from integrations.data_venda import ORIGEM_APROX, ORIGEM_ML, ORIGEM_SHOPEE, ResolvedorDatas, data_do_numero_shopee  # noqa: E402


class AdaptadorFalso:
    """/orders/{id}: 404 para ids de pacote; /packs/{id}: devolve os pedidos de dentro."""

    def __init__(self, pacotes=None, pedidos=None, falha=False):
        self.pacotes, self.pedidos, self.falha, self.chamadas = pacotes or {}, pedidos or {}, falha, []

    def obter_recurso(self, caminho):
        self.chamadas.append(caminho)
        if self.falha:
            raise RuntimeError("API fora do ar")
        tipo, _id = caminho.strip("/").split("/")
        fonte = self.pedidos if tipo == "orders" else self.pacotes
        if _id not in fonte:
            erro = requests.HTTPError("404")
            erro.response = type("R", (), {"status_code": 404})()
            raise erro
        return fonte[_id]


def resolvedor(adaptador):
    return ResolvedorDatas(lambda conta: adaptador, pausa=0)


def cab(id_, loja_id, sit, numero_loja, data="2026-09-02", numero=1, total=100.0):
    return {"id": id_, "numero": numero, "numeroLoja": numero_loja, "data": data, "loja": {"id": loja_id},
            "situacao": {"id": sit}, "totalProdutos": total}


def det(c, itens=None, taxas=None):
    d = dict(c)
    d["itens"] = [{"codigo": s, "quantidade": q, "valor": v} for s, q, v in (itens or [("A", 1, 100.0)])]
    d["taxas"] = taxas or {"taxaComissao": 10.0, "custoFrete": 5.0}
    return d


class BlingFalso:
    def __init__(self, cabs, detalhes=None):
        self.cabs, self.detalhes, self.chamadas_detalhe = cabs, detalhes or {c["id"]: det(c) for c in cabs}, []

    def listar_cabecalhos_pedidos_estrito(self, ini, fim):
        return [c for c in self.cabs if ini <= c["data"] <= fim]

    def obter_pedido_venda(self, pid):
        self.chamadas_detalhe.append(pid)
        return self.detalhes[pid]


def teste_data_shopee_pelo_numero():
    assert data_do_numero_shopee("261026KR5YX7XF", "2026-10-27") == "2026-10-26"
    assert data_do_numero_shopee("261026KR5YX7XF", "2026-12-30") is None  # longe demais do registro
    assert data_do_numero_shopee("2000015290136511", "2026-09-30") is None  # numero do ML nao e Shopee
    assert data_do_numero_shopee("991399ABCDEF", "2026-10-27") is None  # data invalida


def teste_resolvedor_ml_pacote_pedido_e_fuso():
    ad = AdaptadorFalso(
        pacotes={"2000015111": {"date_created": "2026-09-30T23:30:00.000-03:00", "orders": [{"id": 2000018222}, {"id": 2000018223}]}},
        pedidos={"2000018999": {"id": 2000018999, "date_created": "2026-10-01T01:30:00.000+00:00"}})
    r = resolvedor(ad)
    assert r.resolver("ML CC", "2000015111", "2026-10-05") == ("2026-09-30", ORIGEM_ML, [2000018222, 2000018223])
    # 01:30 UTC de 01/10 = 22:30 de 30/09 em Brasilia
    assert r.resolver("ML CC", "2000018999", "2026-10-05") == ("2026-09-30", ORIGEM_ML, [2000018999])
    assert ad.chamadas[:2] == ["/orders/2000015111", "/packs/2000015111"]


def teste_resolvedor_falha_cai_na_data_do_bling_e_shopee_nao_chama_ml():
    r = resolvedor(AdaptadorFalso(falha=True))
    assert r.resolver("ML WC", "2000015222", "2026-09-10") == ("2026-09-10", ORIGEM_APROX, [])
    ad = AdaptadorFalso()
    assert resolvedor(ad).resolver("SHOPEE WC", "260928ABC123X", "2026-09-30") == ("2026-09-28", ORIGEM_SHOPEE, [])
    assert ad.chamadas == []


def teste_sincronizacao_grava_pedido_inteiro_com_data_real():
    con = loja.abrir(":memory:")
    c = cab(1, 203932527, 9, "2000015111", data="2026-09-03")
    ad = AdaptadorFalso(pacotes={"2000015111": {"date_created": "2026-08-31T10:00:00-03:00", "orders": [{"id": 2000018222}]}})
    r = sync.sincronizar_periodo("2026-09-01", "2026-09-30", con, BlingFalso([c]), resolvedor(ad), workers=1, pausa=0, log=lambda *_: None)
    assert r["detalhes_salvos"] == 1 and r["falhas"] == 0
    p = loja.obter_pedido(con, 1)
    assert (p["canal"], p["data_bling"], p["data_venda"], p["data_origem"], p["ml_order_ids"]) == ("ML CC", "2026-09-03", "2026-08-31", ORIGEM_ML, "2000018222")
    item = con.execute("SELECT * FROM itens WHERE pedido_id = 1").fetchone()
    assert (item["sku"], item["valor_bruto"], item["valor_liquido"]) == ("A", 100.0, 85.0)
    # o mes da venda e agosto, nao setembro
    assert loja.totais(con, "2026-09-01", "2026-09-30") == []
    assert loja.totais(con, "2026-08-01", "2026-08-31")[0]["bruto"] == 100.0


def teste_incremental_nao_rebusca_detalhe_e_pega_cancelamento_pelo_cabecalho():
    con = loja.abrir(":memory:")
    c = cab(2, 203930853, 9, "2000015333", data="2026-09-05")
    bling = BlingFalso([c])
    ad = AdaptadorFalso(pacotes={"2000015333": {"date_created": "2026-09-05T09:00:00-03:00", "orders": [{"id": 1}]}})
    kw = dict(workers=1, pausa=0, log=lambda *_: None)
    sync.sincronizar_periodo("2026-09-01", "2026-09-30", con, bling, resolvedor(ad), **kw)
    assert bling.chamadas_detalhe == [2]
    sync.sincronizar_periodo("2026-09-01", "2026-09-30", con, bling, resolvedor(ad), **kw)
    assert bling.chamadas_detalhe == [2]  # nada novo: nenhuma chamada de detalhe a mais
    c["situacao"] = {"id": 460765}  # virou CANCELADO AUT
    sync.sincronizar_periodo("2026-09-01", "2026-09-30", con, bling, resolvedor(ad), **kw)
    assert bling.chamadas_detalhe == [2]
    assert loja.obter_pedido(con, 2)["conta_venda"] == 0 and loja.totais(con, "2026-09-01", "2026-09-30") == []


def teste_pedido_ruim_nao_derruba_o_periodo_e_data_aproximada_e_refeita():
    con = loja.abrir(":memory:")
    ok, ruim = cab(3, 204007414, 9, "260905AAAAAA", data="2026-09-06"), cab(4, 203931530, 9, "2000015444", numero=2)
    bling = BlingFalso([ok, ruim], {3: det(ok), 4: None})  # 4 estoura ao processar (detalhe vazio)
    ad = AdaptadorFalso(falha=True)
    r = sync.sincronizar_periodo("2026-09-01", "2026-09-30", con, bling, resolvedor(ad), workers=1, pausa=0, log=lambda *_: None)
    assert r["detalhes_salvos"] == 1 and r["falhas"] == 1
    assert loja.obter_pedido(con, 3)["data_venda"] == "2026-09-05" and loja.obter_pedido(con, 4) is None
    # o ML volta a responder: o pedido 4 e salvo; um aproximado anterior seria refeito
    bling.detalhes[4] = det(ruim)
    ad2 = AdaptadorFalso(falha=True)
    sync.sincronizar_periodo("2026-09-01", "2026-09-30", con, bling, resolvedor(ad2), workers=1, pausa=0, log=lambda *_: None)
    assert loja.obter_pedido(con, 4)["data_origem"] == ORIGEM_APROX
    ad3 = AdaptadorFalso(pedidos={"2000015444": {"id": 2000015444, "date_created": "2026-09-03T08:00:00-03:00"}})
    r3 = sync.sincronizar_periodo("2026-09-01", "2026-09-30", con, bling, resolvedor(ad3), workers=1, pausa=0, log=lambda *_: None)
    assert r3["datas_refeitas"] == 1 and loja.obter_pedido(con, 4)["data_venda"] == "2026-09-03"


def teste_canais_fora_da_analise_ficam_guardados_mas_nao_entram_nos_totais():
    con = loja.abrir(":memory:")
    c = cab(5, 205673455, 9, "702-1234567-1234567")
    sync.sincronizar_periodo("2026-09-01", "2026-09-30", con, BlingFalso([c]), resolvedor(AdaptadorFalso()), workers=1, pausa=0, log=lambda *_: None)
    p = loja.obter_pedido(con, 5)
    assert p["canal"] == "AMAZON" and p["usa_em_vendas"] == 0 and p["detalhe_ok"] == 1
    assert loja.totais(con, "2026-09-01", "2026-09-30") == []


def teste_banco_local_nao_tem_coluna_de_comprador():
    con = loja.abrir(":memory:")
    colunas = {r[1] for t in ("pedidos", "itens") for r in con.execute(f"PRAGMA table_info({t})")}
    assert not ({"contato", "nome", "documento", "cpf", "cnpj", "endereco", "email", "telefone"} & colunas)


if __name__ == "__main__":
    testes = [v for k, v in sorted(globals().items()) if k.startswith("teste_")]
    for t in testes:
        t()
        print(f"[ok] {t.__name__}")
    print(f"\n{len(testes)}/{len(testes)} testes passaram.")
