"""
tests/teste_ml_visitas_repeticao.py

Testes OFFLINE da coleta de visitas do ML: repetição dos itens que falharam e retentativa de erro de rede.
API e sleep falsos. Executar com:  python tests/teste_ml_visitas_repeticao.py
"""

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from integrations.canais import mercado_livre as ml  # noqa: E402

ml.time.sleep = lambda s: None


def canal(falham_na_1a=(), sempre_falham=(), workers=3):
    c = object.__new__(ml.MercadoLivreCanal)
    c.conta_id, c._metricas = "teste", None
    chamadas = {}

    def uma_visita(item_id, de, ate):
        chamadas[item_id] = chamadas.get(item_id, 0) + 1
        if item_id in sempre_falham or (item_id in falham_na_1a and chamadas[item_id] == 1):
            raise RuntimeError("429 esgotado")
        return 7

    c._obter_visita_um_item = uma_visita
    ml.obter_workers_visitas = lambda: workers
    return c, chamadas


def teste_item_que_falha_so_na_primeira_vez_e_recuperado():
    for w in (3, 1):  # modo concorrente e modo legado
        c, chamadas = canal(falham_na_1a={"MLB2"}, workers=w)
        v = c._obter_visitas_itens([f"MLB{i}" for i in range(1, 31)], "2026-11-22", "2026-11-23")
        assert v["MLB2"] == 7 and all(x == 7 for x in v.values()), (w, v["MLB2"])
        assert chamadas["MLB2"] == 2 and chamadas["MLB1"] == 1


def teste_item_que_nunca_responde_continua_none_sem_derrubar_a_conta():
    c, _ = canal(sempre_falham={"MLB3"})
    v = c._obter_visitas_itens([f"MLB{i}" for i in range(1, 31)], "2026-11-22", "2026-11-23")
    assert v["MLB3"] is None and sum(1 for x in v.values() if x == 7) == 29


def teste_falha_generalizada_continua_abortando():
    c, _ = canal(sempre_falham={f"MLB{i}" for i in range(1, 11)})
    try:
        c._obter_visitas_itens([f"MLB{i}" for i in range(1, 21)], "2026-11-22", "2026-11-23")
        assert False, "devia abortar"
    except RuntimeError as erro:
        assert "falharam" in str(erro)


class Resp:
    status_code, headers = 200, {}

    def json(self):
        return {}


class Sessao:
    def __init__(self, excecoes):
        self.excecoes, self.chamadas = list(excecoes), 0

    def get(self, *a, **k):
        self.chamadas += 1
        if self.excecoes:
            raise self.excecoes.pop(0)
        return Resp()


def teste_timeout_e_erro_de_conexao_sao_repetidos():
    c = object.__new__(ml.MercadoLivreCanal)
    c._metricas, c.conta_id = None, "t"
    c._cabecalho = lambda: {}
    c._sessao = Sessao([requests.exceptions.Timeout(), requests.exceptions.ConnectionError()])
    assert c._get_com_retry("u", {}).status_code == 200 and c._sessao.chamadas == 3


def teste_erro_de_rede_persistente_sobe_na_ultima_tentativa():
    c = object.__new__(ml.MercadoLivreCanal)
    c._metricas, c.conta_id = None, "t"
    c._cabecalho = lambda: {}
    c._sessao = Sessao([requests.exceptions.Timeout()] * ml.MAX_TENTATIVAS_RATE_LIMIT)
    try:
        c._get_com_retry("u", {})
        assert False, "devia levantar"
    except requests.exceptions.Timeout:
        assert c._sessao.chamadas == ml.MAX_TENTATIVAS_RATE_LIMIT


if __name__ == "__main__":
    testes = [v for k, v in sorted(globals().items()) if k.startswith("teste_")]
    for t in testes:
        t()
        print(f"[ok] {t.__name__}")
    print(f"\n{len(testes)}/{len(testes)} testes passaram.")
