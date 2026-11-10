"""
tests/teste_pega_atraso.py

Testes OFFLINE do pega-atraso (main._pega_atraso): contas, datas e rotina falsas, marcador em pasta temporária.
Executar com:  python tests/teste_pega_atraso.py
"""

import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402

CONTAS = [{"conta_id": "wc"}, {"conta_id": "hc"}, {"conta_id": "cc"}]


def cenario(datas, hora=11, rotina_ok=True, marcador=None):
    chamadas = []

    def rotina():
        chamadas.append(1)
        return rotina_ok

    tmp = marcador or Path(tempfile.mkdtemp()) / "pega.json"
    agora = datetime(2026, 11, 10, hora, 0)
    r = main._pega_atraso(agora=agora, marcador=tmp, contas=CONTAS, datas_existentes=lambda c: datas.get(c, set()), rotina=rotina)
    return r, len(chamadas), tmp


TODAS = {"wc": {"2026-11-09"}, "hc": {"2026-11-09"}, "cc": {"2026-11-09"}}
SEM_WC = {"wc": {"2026-11-08"}, "hc": {"2026-11-09"}, "cc": {"2026-11-09"}}


def teste_em_dia_nao_roda_nada():
    assert cenario(TODAS)[:2] == (True, 0)


def teste_falta_dado_mas_antes_das_10h_espera():
    assert cenario(SEM_WC, hora=9)[:2] == (True, 0)


def teste_falta_dado_depois_das_10h_roda_a_rotina_uma_vez():
    r, n, marc = cenario(SEM_WC, hora=11)
    assert (r, n) == (True, 1) and '"tentativas": 1' in marc.read_text(encoding="utf-8")


def teste_rotina_que_falha_devolve_false():
    assert cenario(SEM_WC, rotina_ok=False)[:2] == (False, 1)


def teste_no_maximo_duas_tentativas_por_dia():
    _, n1, marc = cenario(SEM_WC, hora=10)
    _, n2, _ = cenario(SEM_WC, hora=11, marcador=marc)
    r3, n3, _ = cenario(SEM_WC, hora=12, marcador=marc)
    assert (n1, n2, n3, r3) == (1, 1, 0, True)


def teste_marcador_de_outro_dia_nao_conta():
    _, _, marc = cenario(SEM_WC, hora=10)
    marc.write_text('{"dia": "2026-11-08", "tentativas": 5}', encoding="utf-8")
    assert cenario(SEM_WC, hora=11, marcador=marc)[1] == 1


def teste_simular_nao_roda_nem_grava_marcador():
    tmp = Path(tempfile.mkdtemp()) / "pega.json"
    chamadas = []
    r = main._pega_atraso(simular=True, agora=datetime(2026, 11, 10, 11, 0), marcador=tmp, contas=CONTAS,
                          datas_existentes=lambda c: SEM_WC.get(c, set()), rotina=lambda: chamadas.append(1))
    assert r is True and not chamadas and not tmp.exists()


if __name__ == "__main__":
    testes = [v for k, v in sorted(globals().items()) if k.startswith("teste_")]
    for t in testes:
        t()
        print(f"[ok] {t.__name__}")
    print(f"\n{len(testes)}/{len(testes)} testes passaram.")
