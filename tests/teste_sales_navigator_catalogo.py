"""
tests/teste_sales_navigator_catalogo.py

Testes OFFLINE do envio do catálogo do Bling ao Sales Navigator
(integrations/sales_navigator_catalogo.py): sem rede, sem Bling, sem banco.
Executar com:  python tests/teste_sales_navigator_catalogo.py
"""

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

import integrations.sales_navigator_catalogo as cat  # noqa: E402
from config.settings import SalesNavigatorConfig  # noqa: E402

SEGREDO = "segredo-catalogo-xyz"
URL = "https://app.exemplo.lovable.app"


class Resp:
    def __init__(self, status, corpo=None):
        self.status_code = status
        self._corpo = corpo if corpo is not None else {}

    def json(self):
        return self._corpo


def teste_fornecedor_padrao_tem_prioridade():
    vinculos = [
        {"produto": {"id": 1}, "fornecedor": {"id": 10}, "padrao": False},
        {"produto": {"id": 1}, "fornecedor": {"id": 20}, "padrao": True},
        {"produto": {"id": 2}, "fornecedor": {"id": 30}, "padrao": False},
        {"produto": {"id": 2}, "fornecedor": {"id": 31}, "padrao": False},
        {"produto": {"id": 3}, "fornecedor": {}, "padrao": True},
    ]
    assert cat.escolher_fornecedor_por_produto(vinculos) == {1: 20, 2: 30}


def teste_montagem_do_catalogo():
    produtos = [
        {"id": 1, "codigo": " 12043 ", "nome": "Tampo", "precoCusto": 55.5, "situacao": "A"},
        {"id": 2, "codigo": "KIT1", "nome": "Kit", "precoCusto": 0, "situacao": "A"},
        {"id": 3, "codigo": "", "nome": "sem sku", "precoCusto": 9, "situacao": "A"},
        {"id": 4, "codigo": "OLD", "nome": "antigo", "precoCusto": 9, "situacao": "E"},
        {"id": 5, "codigo": "INAT", "nome": "inativo", "precoCusto": 3, "situacao": "I"},
        {"id": 6, "codigo": "12043", "nome": "duplicado", "precoCusto": 1, "situacao": "A"},
        {"id": 7, "codigo": "SEMFORN", "nome": "x", "situacao": "A"},
    ]
    itens, r = cat.montar_catalogo(produtos, {1: 100, 2: 100, 5: 200}, {100: "WITH QUALITY LTDA", 200: None})
    por_sku = {i["sku"]: i for i in itens}
    assert set(por_sku) == {"12043", "KIT1", "INAT", "SEMFORN"}
    assert por_sku["12043"] == {"sku": "12043", "nome": "Tampo", "fornecedor": "WITH QUALITY LTDA", "situacao": "ativo", "custo": 55.5}
    assert por_sku["KIT1"]["custo"] is None  # custo zero = desconhecido, nunca zero
    assert por_sku["INAT"]["situacao"] == "inativo" and por_sku["INAT"]["fornecedor"] == ""
    assert por_sku["SEMFORN"]["custo"] is None
    assert (r["sem_sku"], r["situacao_ignorada"], r["itens"]) == (1, 1, 4)


def teste_apelido_unifica_grafias_do_mesmo_fornecedor():
    produtos = [{"id": 1, "codigo": "D1", "nome": "x", "precoCusto": 1, "situacao": "A"},
                {"id": 2, "codigo": "D2", "nome": "y", "precoCusto": 1, "situacao": "A"}]
    nomes = {1: "DEISS INDUSTRIA E COMERCIO DE MOVEIS", 2: " deiss industria e comercio de moveis "}
    itens, _ = cat.montar_catalogo(produtos, {1: 1, 2: 2}, nomes)
    assert {i["fornecedor"] for i in itens} == {"DEISS INDUSTRIA E COMERCIO DE MOVEIS LTDA"}


def teste_envio_em_lotes_e_cabecalho():
    chamadas = []

    def post(url, json=None, headers=None, timeout=None):
        chamadas.append((url, len(json), dict(headers)))
        return Resp(200, {"ok": True, "gravados": len(json), "rejeitados": [{"sku": "X", "motivo": "m"}] if len(chamadas) == 1 else []})

    itens = [{"sku": f"S{i}", "nome": "n", "fornecedor": "F", "situacao": "ativo", "custo": 1.0} for i in range(1100)]
    with mock.patch.object(cat.requests, "post", post):
        r = cat.enviar_itens(itens, URL, SEGREDO)
    assert [c[1] for c in chamadas] == [500, 500, 100]
    assert all(c[0] == URL + "/api/public/sync-produtos" and c[2] == {"x-sync-secret": SEGREDO} for c in chamadas)
    assert r["gravados"] == 1100 and r["rejeitados"] == [{"sku": "X", "motivo": "m"}]


def teste_erros_viram_falha_controlada_sem_vazar_segredo():
    for status, trecho in ((401, "segredo recusado"), (404, "404"), (400, "HTTP 400")):
        with mock.patch.object(cat.requests, "post", lambda *a, _s=status, **k: Resp(_s, {"error": "falhou"})):
            try:
                cat.enviar_itens([{"sku": "A"}], URL, SEGREDO)
            except cat.ErroFatalEnvio as erro:
                assert trecho in str(erro) and SEGREDO not in str(erro)
            else:
                raise AssertionError(f"status {status} deveria falhar")


def teste_servidor_instavel_tenta_de_novo():
    estados = [Resp(503), Resp(503), Resp(200, {"ok": True, "gravados": 1, "rejeitados": []})]
    with mock.patch.object(cat.requests, "post", lambda *a, **k: estados.pop(0)), mock.patch.object(cat.time, "sleep"):
        assert cat.enviar_itens([{"sku": "A"}], URL, SEGREDO)["gravados"] == 1

    def cai(*a, **k):
        raise requests.ConnectionError("x")

    with mock.patch.object(cat.requests, "post", cai), mock.patch.object(cat.time, "sleep"):
        try:
            cat.enviar_itens([{"sku": "A"}], URL, SEGREDO)
        except cat.ErroFatalEnvio as erro:
            assert "ConnectionError" in str(erro)
        else:
            raise AssertionError("deveria falhar")


class BlingFalso:
    def listar_produtos(self):
        return [{"id": 1, "codigo": "A1", "nome": "Um", "precoCusto": 10, "situacao": "A"}]

    def listar_vinculos_fornecedor(self):
        return [{"produto": {"id": 1}, "fornecedor": {"id": 7}, "padrao": True}]

    def obter_nome_contato(self, cid):
        return "Fornecedor Sete"


def teste_simulacao_nao_envia_e_nao_exige_configuracao():
    with mock.patch.object(cat, "BlingClient", BlingFalso), mock.patch.object(cat.time, "sleep"), \
         mock.patch.object(cat.requests, "post") as post:
        buf = io.StringIO()
        with redirect_stdout(buf):
            r = cat.sincronizar_catalogo(simular=True)
    assert not post.called and r["total"] == 1 and "simulação" in buf.getvalue()


def teste_fluxo_completo_e_nao_configurado():
    cfg = SalesNavigatorConfig(url_base=URL, segredo=SEGREDO)
    enviados = []

    def post(url, json=None, headers=None, timeout=None):
        enviados.extend(json)
        return Resp(200, {"ok": True, "gravados": len(json), "rejeitados": []})

    with mock.patch.object(cat, "BlingClient", BlingFalso), mock.patch.object(cat.time, "sleep"), \
         mock.patch.object(cat, "carregar_configuracao_sales_navigator", return_value=cfg), \
         mock.patch.object(cat.requests, "post", post):
        buf = io.StringIO()
        with redirect_stdout(buf):
            r = cat.sincronizar_catalogo()
    assert enviados == [{"sku": "A1", "nome": "Um", "fornecedor": "Fornecedor Sete", "situacao": "ativo", "custo": 10.0}]
    assert r["gravados"] == 1 and SEGREDO not in buf.getvalue()

    from config.settings import ConfiguracaoInvalidaError

    with mock.patch.object(cat, "BlingClient") as bc, \
         mock.patch.object(cat, "carregar_configuracao_sales_navigator", side_effect=ConfiguracaoInvalidaError("x")):
        assert cat.sincronizar_catalogo() is None and not bc.called


if __name__ == "__main__":
    testes = [v for k, v in sorted(globals().items()) if k.startswith("teste_")]
    for t in testes:
        t()
        print(f"[ok] {t.__name__}")
    print(f"\n{len(testes)}/{len(testes)} testes passaram.")
