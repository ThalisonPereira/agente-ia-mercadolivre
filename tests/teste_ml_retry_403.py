"""
tests/teste_ml_retry_403.py

Testes OFFLINE do retry de 403 temporário em MercadoLivreCanal._get_com_retry (sessão HTTP e sleep falsos).
Executar com:  python tests/teste_ml_retry_403.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from integrations.canais import mercado_livre as ml  # noqa: E402


class Resp:
    def __init__(self, status, corpo=None):
        self.status_code, self.headers, self._corpo = status, {}, corpo or []

    def json(self):
        return self._corpo

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class Sessao:
    def __init__(self, respostas):
        self.respostas, self.chamadas = list(respostas), 0

    def get(self, *a, **k):
        self.chamadas += 1
        return self.respostas.pop(0)


def canal(respostas):
    c = object.__new__(ml.MercadoLivreCanal)
    c._sessao, c._metricas, c.conta_id = Sessao(respostas), None, "teste"
    c._cabecalho = lambda: {}
    return c


def sem_espera():
    esperas = []
    ml.time.sleep = esperas.append
    return esperas


def teste_403_passageiro_e_repetido_so_quando_pedido():
    esperas = sem_espera()
    c = canal([Resp(403), Resp(403), Resp(200)])
    r = c._get_com_retry("u", {}, repetir_403=True)
    assert r.status_code == 200 and c._sessao.chamadas == 3
    assert esperas == [5, 10]


def teste_403_sem_o_pedido_continua_sendo_devolvido_na_hora():
    esperas = sem_espera()
    c = canal([Resp(403), Resp(200)])
    assert c._get_com_retry("u", {}).status_code == 403 and c._sessao.chamadas == 1 and esperas == []


def teste_403_persistente_desiste_e_devolve_o_403():
    esperas = sem_espera()
    c = canal([Resp(403)] * ml.MAX_TENTATIVAS_RATE_LIMIT)
    assert c._get_com_retry("u", {}, repetir_403=True).status_code == 403
    assert c._sessao.chamadas == ml.MAX_TENTATIVAS_RATE_LIMIT


def teste_429_continua_como_antes():
    esperas = sem_espera()
    c = canal([Resp(429), Resp(200)])
    assert c._get_com_retry("u", {}).status_code == 200 and esperas == [2]


def teste_detalhes_de_itens_se_recupera_de_403():
    sem_espera()
    c = canal([Resp(403), Resp(200, [{"code": 200, "body": {"id": "MLB1"}}])])
    assert c._obter_detalhes_itens(["MLB1"]) == [{"id": "MLB1"}]


if __name__ == "__main__":
    testes = [v for k, v in sorted(globals().items()) if k.startswith("teste_")]
    for t in testes:
        t()
        print(f"[ok] {t.__name__}")
    print(f"\n{len(testes)}/{len(testes)} testes passaram.")
