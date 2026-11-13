"""
tests/teste_bling_token_concorrencia.py

Testes OFFLINE da renovação do token do Bling (integrations/bling.py): várias threads com o token expirado, outro processo que renova
primeiro e falha ao salvar no banco. Banco e API do Bling falsos. Executar com:  python tests/teste_bling_token_concorrencia.py
"""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from integrations import bling  # noqa: E402


class Banco:
    """Guarda o token como o Supabase guardaria; salvar pode falhar N vezes."""

    def __init__(self, token, falhas_ao_salvar=0):
        self.token, self.falhas, self.salvamentos = token, falhas_ao_salvar, 0

    def obter(self, conta):
        return dict(self.token)

    def salvar(self, conta, dados):
        if self.falhas > 0:
            self.falhas -= 1
            raise RuntimeError("connection already closed")
        self.token = dict(dados)
        self.salvamentos += 1


class Resposta:
    def __init__(self, status, corpo):
        self.status_code, self._corpo, self.text = status, corpo, str(corpo)

    def json(self):
        return self._corpo


class ApiBling:
    """Refresh token de uso único: só o refresh_token atual funciona; usá-lo gera outro."""

    def __init__(self):
        self.atual, self.n, self.chamadas = "R1", 1, 0
        self.lock = threading.Lock()

    def post(self, url, headers=None, data=None, timeout=None):
        time.sleep(0.01)
        with self.lock:
            self.chamadas += 1
            if data["refresh_token"] != self.atual:
                return Resposta(400, {"error": {"type": "invalid_grant"}})
            self.n += 1
            self.atual = f"R{self.n}"
            return Resposta(200, {"access_token": f"A{self.n}", "refresh_token": self.atual, "expires_in": 21600})


def montar(banco, api):
    bling.obter_token, bling.salvar_token = banco.obter, banco.salvar
    bling.requests.post = api.post
    bling.time.sleep = lambda s: None
    c = object.__new__(bling.BlingClient)
    c._cabecalho_basic = lambda: {}
    return c


EXPIRADO = {"access_token": "A1", "refresh_token": "R1", "expires_in": 21600, "obtido_em": 0}


def teste_varias_threads_renovam_uma_vez_so():
    banco, api = Banco(EXPIRADO), ApiBling()
    cli = montar(banco, api)
    achados = []
    ts = [threading.Thread(target=lambda: achados.append(cli._token_valido())) for _ in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert api.chamadas == 1, api.chamadas            # sem a trava seriam 12 chamadas e 11 invalid_grant
    assert set(achados) == {"A2"} and banco.token["refresh_token"] == "R2"


def teste_outro_processo_ja_renovou_usa_o_token_do_banco():
    banco, api = Banco(EXPIRADO), ApiBling()
    cli = montar(banco, api)
    api.atual = "R9"                                   # alguém já usou o R1 e o Bling rotacionou
    novo = {"access_token": "A9", "refresh_token": "R9", "expires_in": 21600, "obtido_em": time.time()}
    leituras = iter([dict(EXPIRADO), dict(EXPIRADO), novo])   # 1ª leitura, releitura sob a trava, depois do invalid_grant
    bling.obter_token = lambda conta: next(leituras)
    assert cli._token_valido() == "A9"


def teste_salvar_o_token_novo_tenta_de_novo_quando_a_conexao_cai():
    banco, api = Banco(EXPIRADO, falhas_ao_salvar=2), ApiBling()
    cli = montar(banco, api)
    assert cli._token_valido() == "A2" and banco.token["refresh_token"] == "R2" and banco.salvamentos == 1


def teste_se_o_banco_nunca_responde_o_erro_manda_reautorizar():
    banco, api = Banco(EXPIRADO, falhas_ao_salvar=99), ApiBling()
    cli = montar(banco, api)
    try:
        cli._token_valido()
        assert False, "devia falhar"
    except RuntimeError as erro:
        assert "reautorize" in str(erro)


def teste_token_valido_nao_renova():
    banco, api = Banco({**EXPIRADO, "obtido_em": time.time()}), ApiBling()
    cli = montar(banco, api)
    assert cli._token_valido() == "A1" and api.chamadas == 0


if __name__ == "__main__":
    testes = [v for k, v in sorted(globals().items()) if k.startswith("teste_")]
    for t in testes:
        t()
        print(f"[ok] {t.__name__}")
    print(f"\n{len(testes)}/{len(testes)} testes passaram.")
