"""
tests/teste_variacao_nulos.py

Testes OFFLINE da variação de anúncios com visitas/vendas vazias (NULL). Executar com:  python tests/teste_variacao_nulos.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import analisar_variacao as av  # noqa: E402


def teste_sem_dado_em_um_dos_lados_nao_quebra_e_fica_em_zero():
    assert av._variacao_percentual(None, 5) == 0.0
    assert av._variacao_percentual(5, None) == 0.0
    assert av._variacao_percentual(None, None) == 0.0


def teste_calculo_normal_continua_igual():
    assert av._variacao_percentual(10, 15) == 0.5
    assert av._variacao_percentual(10, 5) == -0.5
    assert av._variacao_percentual(0, 3) == 1.0 and av._variacao_percentual(0, 0) == 0.0


def teste_anuncio_com_visita_vazia_sai_como_estavel_na_variacao_completa():
    linhas = [{"conta_id": "wc", "item_id": "MLB1", "titulo": "t", "sku": "S", "visitas_anterior": None, "visitas_atual": 40,
               "vendas_anterior": 2, "vendas_atual": 2, "receita": 100.0}]

    class Cx:
        def execute(self, sql, params=None):
            return type("R", (), {"fetchall": lambda s: linhas})()

        def close(self):
            pass

    original = av.obter_conexao
    av.obter_conexao = lambda: Cx()
    try:
        r = av.obter_variacao_anuncios("2026-11-22", "2026-11-23", conta_id="wc")
    finally:
        av.obter_conexao = original
    assert len(r) == 1 and r[0]["variacao_visitas"] == 0.0 and r[0]["status"] == "Estável"


if __name__ == "__main__":
    testes = [v for k, v in sorted(globals().items()) if k.startswith("teste_")]
    for t in testes:
        t()
        print(f"[ok] {t.__name__}")
    print(f"\n{len(testes)}/{len(testes)} testes passaram.")
