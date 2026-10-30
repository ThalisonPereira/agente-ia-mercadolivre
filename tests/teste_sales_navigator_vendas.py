"""
tests/teste_sales_navigator_vendas.py

Testes OFFLINE do envio de vendas ao Sales Navigator (integrations/sales_navigator_vendas.py): sem rede, SQLite em
memória, servidor falso. Executar com:  python tests/teste_sales_navigator_vendas.py
"""

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

import integrations.sales_navigator_vendas as sv  # noqa: E402
from config.settings import ConfiguracaoInvalidaError, SalesNavigatorConfig  # noqa: E402
from database import vendas_bling_local as loja  # noqa: E402

SEGREDO = "segredo-vendas-xyz"
URL = "https://app.exemplo.lovable.app"
CAMPOS_PEDIDO = {"pedido_id", "numero", "numero_loja", "loja_id", "canal", "situacao_id", "conta_venda", "data_bling",
                 "data_venda", "data_origem", "total_produtos", "taxas_ausentes", "soma_diverge", "itens"}
CAMPOS_ITEM = {"linha", "sku", "quantidade", "valor_bruto", "valor_liquido"}


class Resp:
    def __init__(self, status, corpo=None):
        self.status_code, self._corpo = status, corpo if corpo is not None else {}

    def json(self):
        return self._corpo


def banco():
    con = loja.abrir(":memory:")
    cab = lambda i, sit, data: {"id": i, "numero": i, "numeroLoja": f"L{i}", "data": data, "loja": {"id": 203930853},
                                "situacao": {"id": sit}, "totalProdutos": 100.0}
    loja.salvar_cabecalho(con, cab(1, 12, "2026-09-22"), "ML WC", True, False)  # cancelado: só cabeçalho
    linhas = [{"pedido_id": 2, "numero": 2, "numero_loja": "L2", "data": "2026-09-23", "loja_id": 203930853, "canal": "ML WC",
               "usa_em_vendas": True, "situacao_id": 9, "sku": "A", "quantidade": 2.0, "valor_bruto": 200.0, "valor_liquido": 170.0},
              {"pedido_id": 2, "numero": 2, "numero_loja": "L2", "data": "2026-09-23", "loja_id": 203930853, "canal": "ML WC",
               "usa_em_vendas": True, "situacao_id": 9, "sku": "B", "quantidade": 1.0, "valor_bruto": 50.0, "valor_liquido": 42.5}]
    # vendido em 30/08 e registrado no Bling só em 03/09: data real (venda) fora do período de setembro
    loja.salvar_pedido_completo(con, linhas, {"taxas_ausentes": False, "soma_diverge": False}, "2026-09-21", "ml_api", [2000018], 250.0)
    antigo = [dict(linhas[0], pedido_id=3, numero=3, numero_loja="L3", data="2026-09-03")]
    loja.salvar_pedido_completo(con, antigo, {"taxas_ausentes": True, "soma_diverge": False}, "2026-08-30", "ml_api", [1], 200.0)
    return con


def teste_payload_so_tem_campos_de_negocio_e_filtra_pela_data_real():
    con = banco()
    pedidos = montar_ids(sv.montar_pedidos(con, "2026-09-01", "2026-09-30"))
    assert set(pedidos) == {1, 2}  # o pedido 3 foi vendido em agosto, embora registrado em setembro
    for p in pedidos.values():
        assert set(p) == CAMPOS_PEDIDO
    assert pedidos[2]["itens"] and all(set(i) == CAMPOS_ITEM for i in pedidos[2]["itens"])
    assert pedidos[2]["data_venda"] == "2026-09-21" and pedidos[2]["conta_venda"] is True
    assert sorted(i["sku"] for i in pedidos[2]["itens"]) == ["A", "B"]


def montar_ids(lista):
    return {p["pedido_id"]: p for p in lista}


def teste_cancelado_vai_so_como_cabecalho_sem_itens():
    p = montar_ids(sv.montar_pedidos(banco(), "2026-09-01", "2026-09-30"))[1]
    assert p["conta_venda"] is False and p["itens"] == [] and p["data_venda"] is None and p["data_bling"] == "2026-09-22"


def teste_flags_viram_booleanos():
    p = montar_ids(sv.montar_pedidos(banco(), "2026-08-01", "2026-08-31"))[3]
    assert p["taxas_ausentes"] is True and p["soma_diverge"] is False


def teste_envio_em_lotes_de_500_e_cabecalho():
    chamadas = []

    def post(url, json=None, headers=None, timeout=None):
        chamadas.append((url, len(json["pedidos"]), dict(headers)))
        return Resp(200, {"ok": True, "gravados": len(json["pedidos"]), "rejeitados": [{"pedido_id": 7, "motivo": "m"}] if len(chamadas) == 1 else []})

    pedidos = [{"pedido_id": i} for i in range(1100)]
    with mock.patch.object(sv.requests, "post", post):
        r = sv.enviar_pedidos(pedidos, URL, SEGREDO, log=lambda *_: None)
    assert [c[1] for c in chamadas] == [500, 500, 100]
    assert all(c[0] == URL + "/api/public/sync-vendas" and c[2] == {"x-sync-secret": SEGREDO} for c in chamadas)
    assert r["gravados"] == 1100 and r["rejeitados"] == [{"pedido_id": 7, "motivo": "m"}] and r["requisicoes"] == 3


def teste_erros_controlados_sem_vazar_segredo():
    for status, trecho in ((401, "segredo recusado"), (404, "404"), (400, "HTTP 400")):
        with mock.patch.object(sv.requests, "post", lambda *a, _s=status, **k: Resp(_s, {"error": "falhou"})):
            try:
                sv.enviar_pedidos([{"pedido_id": 1}], URL, SEGREDO, log=lambda *_: None)
            except sv.ErroFatalEnvio as erro:
                assert trecho in str(erro) and SEGREDO not in str(erro)
            else:
                raise AssertionError(f"status {status} deveria falhar")


def teste_servidor_instavel_tenta_de_novo_e_rede_caida_falha_controlada():
    estados = [Resp(503), Resp(200, {"ok": True, "gravados": 1, "rejeitados": []})]
    with mock.patch.object(sv.requests, "post", lambda *a, **k: estados.pop(0)), mock.patch.object(sv.time, "sleep"):
        assert sv.enviar_pedidos([{"pedido_id": 1}], URL, SEGREDO, log=lambda *_: None)["gravados"] == 1

    def cai(*a, **k):
        raise requests.ConnectionError("sem rede")

    with mock.patch.object(sv.requests, "post", cai), mock.patch.object(sv.time, "sleep"):
        try:
            sv.enviar_pedidos([{"pedido_id": 1}], URL, SEGREDO, log=lambda *_: None)
        except sv.ErroFatalEnvio as erro:
            assert "ConnectionError" in str(erro)
        else:
            raise AssertionError("deveria falhar")


def teste_simulacao_nao_chama_rede_nem_exige_configuracao():
    saida = io.StringIO()
    with mock.patch.object(sv.requests, "post") as post, redirect_stdout(saida):
        r = sv.sincronizar_vendas("2026-09-01", "2026-09-30", con=banco(), simular=True, log=print)
    assert not post.called and r["total"] == 2 and "simulação" in saida.getvalue()


def teste_nao_configurado_pula_e_segredo_nunca_aparece():
    with mock.patch.object(sv, "carregar_configuracao_sales_navigator", side_effect=ConfiguracaoInvalidaError("x")), \
         mock.patch.object(sv.requests, "post") as post:
        assert sv.sincronizar_vendas("2026-09-01", "2026-09-30", con=banco(), log=lambda *_: None) is None
        assert not post.called
    cfg = SalesNavigatorConfig(url_base=URL, segredo=SEGREDO)
    saida = io.StringIO()
    with mock.patch.object(sv, "carregar_configuracao_sales_navigator", return_value=cfg), \
         mock.patch.object(sv.requests, "post", lambda *a, **k: Resp(200, {"ok": True, "gravados": 2, "rejeitados": []})), redirect_stdout(saida):
        r = sv.sincronizar_vendas("2026-09-01", "2026-09-30", con=banco(), log=print)
    assert r["gravados"] == 2 and SEGREDO not in saida.getvalue()


if __name__ == "__main__":
    testes = [v for k, v in sorted(globals().items()) if k.startswith("teste_")]
    for t in testes:
        t()
        print(f"[ok] {t.__name__}")
    print(f"\n{len(testes)}/{len(testes)} testes passaram.")
