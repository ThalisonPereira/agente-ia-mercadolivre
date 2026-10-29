"""
tests/teste_sales_navigator.py

Testes OFFLINE do envio de estoque ao Sales Navigator (integrations/sales_navigator.py):
sem rede, sem banco. Um servidor falso imita o endpoint /api/public/sync-estoque (recusa o
lote inteiro com 400 se houver SKU fora do cadastro, como a chave estrangeira real).
Executar com:  python tests/teste_sales_navigator.py
"""

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

import integrations.sales_navigator as sn  # noqa: E402
from config.settings import ConfiguracaoInvalidaError, SalesNavigatorConfig  # noqa: E402

SEGREDO = "segredo-super-secreto-123"
URL = "https://app.exemplo.lovable.app"


class Resp:
    def __init__(self, status, corpo=None):
        self.status_code = status
        self._corpo = corpo if corpo is not None else {}

    def json(self):
        return self._corpo


class Servidor:
    """Imita o endpoint: 401 sem segredo certo; 400 se algum SKU não está no cadastro."""

    def __init__(self, cadastro, falhas_5xx=0):
        self.cadastro = set(cadastro)
        self.falhas_5xx = falhas_5xx
        self.chamadas = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.chamadas.append({"url": url, "n": len(json), "headers": dict(headers), "timeout": timeout})
        if self.falhas_5xx > 0:
            self.falhas_5xx -= 1
            return Resp(503)
        if headers.get("x-sync-secret") != SEGREDO:
            return Resp(401, {"error": "Unauthorized"})
        if any(i["sku"] not in self.cadastro for i in json):
            return Resp(400, {"error": "violates foreign key constraint estoque_sku_fkey"})
        return Resp(200, {"ok": True, "atualizados": len(json)})


def saldos(n):
    return [{"sku": f"S{i:04d}", "saldo": float(i)} for i in range(n)]


def teste_lotes_de_500_e_sem_recusados():
    srv = Servidor({s["sku"] for s in saldos(1200)})
    with mock.patch.object(sn.requests, "post", srv.post):
        r = sn.enviar_estoque(saldos(1200), URL, SEGREDO)
    assert r["total"] == 1200 and r["enviados"] == 1200 and r["recusados"] == []
    assert [c["n"] for c in srv.chamadas] == [500, 500, 200]
    assert all(c["url"] == URL + "/api/public/sync-estoque" for c in srv.chamadas)
    assert all(c["headers"] == {"x-sync-secret": SEGREDO} for c in srv.chamadas)


def teste_isola_sku_recusado_e_envia_o_resto():
    todos = saldos(600)
    cadastro = {s["sku"] for s in todos} - {"S0007", "S0450"}
    srv = Servidor(cadastro)
    with mock.patch.object(sn.requests, "post", srv.post):
        r = sn.enviar_estoque(todos, URL, SEGREDO)
    assert r["enviados"] == 598
    assert sorted(x["sku"] for x in r["recusados"]) == ["S0007", "S0450"]
    assert all("foreign key" in x["motivo"] for x in r["recusados"])


def teste_segredo_errado_para_na_primeira_chamada():
    srv = Servidor({s["sku"] for s in saldos(50)})
    with mock.patch.object(sn.requests, "post", srv.post):
        try:
            sn.enviar_estoque(saldos(50), URL, "errado")
        except sn.ErroFatalEnvio as erro:
            assert "segredo recusado" in str(erro) and "errado" not in str(erro)
        else:
            raise AssertionError("deveria ter levantado ErroFatalEnvio")
    assert len(srv.chamadas) == 1


def teste_servidor_instavel_tenta_de_novo_e_depois_falha():
    srv = Servidor({s["sku"] for s in saldos(10)}, falhas_5xx=2)
    with mock.patch.object(sn.requests, "post", srv.post), mock.patch.object(sn.time, "sleep"):
        r = sn.enviar_estoque(saldos(10), URL, SEGREDO)
    assert r["enviados"] == 10 and len(srv.chamadas) == 3

    srv2 = Servidor({s["sku"] for s in saldos(10)}, falhas_5xx=99)
    with mock.patch.object(sn.requests, "post", srv2.post), mock.patch.object(sn.time, "sleep"):
        try:
            sn.enviar_estoque(saldos(10), URL, SEGREDO)
        except sn.ErroFatalEnvio as erro:
            assert "indisponível" in str(erro)
        else:
            raise AssertionError("deveria ter falhado")
    assert len(srv2.chamadas) == sn.TENTATIVAS


def teste_erro_de_rede_vira_falha_controlada():
    def cai(*a, **k):
        raise requests.ConnectionError("sem rede")

    with mock.patch.object(sn.requests, "post", cai), mock.patch.object(sn.time, "sleep"):
        try:
            sn.enviar_estoque(saldos(3), URL, SEGREDO)
        except sn.ErroFatalEnvio as erro:
            assert "ConnectionError" in str(erro)
        else:
            raise AssertionError("deveria ter falhado")


def teste_nao_configurado_pula_sem_rede():
    with mock.patch.object(sn, "obter_saldos", return_value=saldos(3)), \
         mock.patch.object(sn, "carregar_configuracao_sales_navigator", side_effect=ConfiguracaoInvalidaError("x")), \
         mock.patch.object(sn.requests, "post") as post:
        buf = io.StringIO()
        with redirect_stdout(buf):
            assert sn.sincronizar_estoque() is None
    assert not post.called and "não configurado" in buf.getvalue()


def teste_simulacao_nao_chama_rede_e_nao_mostra_segredo():
    with mock.patch.object(sn, "obter_saldos", return_value=saldos(7)), mock.patch.object(sn.requests, "post") as post:
        buf = io.StringIO()
        with redirect_stdout(buf):
            r = sn.sincronizar_estoque(simular=True)
    assert not post.called and r["total"] == 7 and "7 SKU" in buf.getvalue()


def teste_resumo_nunca_imprime_o_segredo():
    srv = Servidor({s["sku"] for s in saldos(5)} - {"S0001"})
    cfg = SalesNavigatorConfig(url_base=URL, segredo=SEGREDO)
    with mock.patch.object(sn, "obter_saldos", return_value=saldos(5)), \
         mock.patch.object(sn, "carregar_configuracao_sales_navigator", return_value=cfg), \
         mock.patch.object(sn.requests, "post", srv.post):
        buf = io.StringIO()
        with redirect_stdout(buf):
            r = sn.sincronizar_estoque()
    saida = buf.getvalue()
    assert SEGREDO not in saida and "S0001" in saida and r["enviados"] == 4


def teste_teto_de_requisicoes_evita_laco_infinito():
    srv = Servidor(set())  # nenhum SKU aceito: força isolar todos
    with mock.patch.object(sn.requests, "post", srv.post), mock.patch.object(sn, "MAX_REQUISICOES", 20):
        try:
            sn.enviar_estoque(saldos(400), URL, SEGREDO)
        except sn.ErroFatalEnvio as erro:
            assert "limite" in str(erro)
        else:
            raise AssertionError("deveria ter parado no teto")
    assert len(srv.chamadas) == 20


def teste_url_exige_https():
    from config import settings

    with mock.patch.dict("os.environ", {"SALES_NAVIGATOR_URL": "http://x", "SALES_NAVIGATOR_SECRET": "s"}):
        try:
            settings.carregar_configuracao_sales_navigator()
        except ConfiguracaoInvalidaError:
            pass
        else:
            raise AssertionError("deveria exigir https")
    with mock.patch.dict("os.environ", {"SALES_NAVIGATOR_URL": "https://x.app/", "SALES_NAVIGATOR_SECRET": " s "}):
        c = settings.carregar_configuracao_sales_navigator()
        assert c.url_base == "https://x.app" and c.segredo == "s"


if __name__ == "__main__":
    testes = [v for k, v in sorted(globals().items()) if k.startswith("teste_")]
    for t in testes:
        t()
        print(f"[ok] {t.__name__}")
    print(f"\n{len(testes)}/{len(testes)} testes passaram.")
