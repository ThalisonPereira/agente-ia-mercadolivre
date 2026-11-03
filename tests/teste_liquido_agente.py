"""
tests/teste_liquido_agente.py

Testes OFFLINE do preenchimento do líquido pelo agente (integrations/liquido_agente.py): SQLite em memória e um
"agente" falso. Executar com:  python tests/teste_liquido_agente.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import vendas_bling_local as loja  # noqa: E402
from integrations import liquido_agente as la  # noqa: E402


class AgenteFalso:
    """execute(sql, params).fetchall() -> linhas já agregadas por pedido (como o SELECT real devolveria)."""

    def __init__(self, por_pedido):
        self.por_pedido, self.consultas = por_pedido, []

    def execute(self, sql, params):
        self.consultas.append(params["ids"])
        rows = [{"pedido_id": k, "com": v[0], "fr": v[1], "com_informada": v[2]} for k, v in self.por_pedido.items() if k in params["ids"]]
        return type("R", (), {"fetchall": lambda s: rows})()


def pedido(con, pid, canal, itens, taxas_ausentes=True, ml_ids=("9001",), usa=True, conta=True):
    linhas = [{"pedido_id": pid, "numero": pid, "numero_loja": f"L{pid}", "data": "2026-10-20", "loja_id": 203930853, "canal": canal,
               "usa_em_vendas": usa, "situacao_id": 9, "sku": f"S{i}", "quantidade": 1.0, "valor_bruto": b, "valor_liquido": b}
              for i, b in enumerate(itens)]
    loja.salvar_pedido_completo(con, linhas, {"taxas_ausentes": taxas_ausentes, "soma_diverge": False}, "2026-10-20", "ml_api", list(ml_ids), sum(itens))
    if not conta:
        con.execute("UPDATE pedidos SET conta_venda = 0 WHERE pedido_id = ?", (pid,))
        con.commit()


def liquidos(con, pid):
    return [r[0] for r in con.execute("SELECT valor_liquido FROM itens WHERE pedido_id = ? ORDER BY linha", (pid,))]


def teste_ratear_fecha_exatamente_e_respeita_proporcao():
    assert la.ratear_taxas([600.0, 400.0], 150.0) == [510.0, 340.0]
    r = la.ratear_taxas([10.0, 10.0, 10.0], 1.0)  # 0,33 + 0,33 + 0,33 + 0,01 de sobra no maior
    assert round(sum(r), 2) == 29.0 and all(0 < x < 10 for x in r)
    assert la.ratear_taxas([0.0, 0.0], 5.0) == [0.0, 0.0]


def teste_preenche_pedido_do_ml_sem_taxa_no_bling():
    con = loja.abrir(":memory:")
    pedido(con, 1, "ML WC", [600.0, 400.0])
    r = la.preencher_liquido_pelo_agente(con, AgenteFalso({"9001": (100.0, 50.0, 2)}), log=lambda *_: None)
    assert r["preenchidos"] == 1
    assert liquidos(con, 1) == [510.0, 340.0]
    p = loja.obter_pedido(con, 1)
    assert p["taxas_ausentes"] == 0 and p["liquido_origem"] == la.ORIGEM_AGENTE


def teste_pacote_com_dois_pedidos_soma_as_taxas_dos_dois():
    con = loja.abrir(":memory:")
    pedido(con, 2, "ML CC", [200.0], ml_ids=("9001", "9002"))
    la.preencher_liquido_pelo_agente(con, AgenteFalso({"9001": (10.0, 5.0, 1), "9002": (20.0, 0.0, 1)}), log=lambda *_: None)
    assert liquidos(con, 2) == [165.0]


def teste_nao_mexe_no_que_nao_deve():
    con = loja.abrir(":memory:")
    pedido(con, 3, "ML WC", [100.0], taxas_ausentes=False)                 # o Bling já tinha taxa
    pedido(con, 4, "SHOPEE WC", [100.0], ml_ids=())                         # não é ML
    pedido(con, 5, "ML WC", [100.0], conta=False)                           # cancelado: não conta
    pedido(con, 6, "ML HC", [100.0], ml_ids=("8888",))                      # agente não tem o pedido
    pedido(con, 7, "ML HC", [100.0], ml_ids=("9001",))                      # taxa maior que o bruto: algo errado
    pedido(con, 8, "ML HC", [100.0], ml_ids=("7777",))                      # agente sem comissão informada
    agente = AgenteFalso({"9001": (80.0, 40.0, 1), "7777": (0.0, 0.0, 0)})
    r = la.preencher_liquido_pelo_agente(con, agente, log=lambda *_: None)
    assert r == {"candidatos": 3, "preenchidos": 0, "sem_dado_no_agente": 2, "taxa_maior_que_bruto": 1}
    assert all(liquidos(con, p) == [100.0] for p in (3, 4, 5, 6, 7, 8))
    assert loja.obter_pedido(con, 6)["taxas_ausentes"] == 1


def teste_depois_de_preenchido_nao_e_mais_candidato_e_consulta_em_lotes():
    con = loja.abrir(":memory:")
    pedido(con, 9, "ML WC", [100.0])
    agente = AgenteFalso({"9001": (10.0, 5.0, 1)})
    la.preencher_liquido_pelo_agente(con, agente, log=lambda *_: None)
    r2 = la.preencher_liquido_pelo_agente(con, agente, log=lambda *_: None)
    assert r2["candidatos"] == 0 and len(agente.consultas) == 1


def pedido_com_taxa_do_bling(con, pid, bruto, taxas_bling, ml_ids=("9001",), canal="ML WC", data="2026-10-20"):
    """Pedido em que o Bling trouxe taxa (líquido = bruto - taxas_bling), já com taxas_ausentes = 0."""
    pedido(con, pid, canal, [bruto], taxas_ausentes=False, ml_ids=ml_ids)
    con.execute("UPDATE itens SET valor_liquido = ? WHERE pedido_id = ?", (round(bruto - taxas_bling, 2), pid))
    con.execute("UPDATE pedidos SET data_bling = ? WHERE pedido_id = ?", (data, pid))
    con.commit()


def teste_completa_taxa_incompleta_do_bling_e_nunca_reduz():
    from datetime import date

    con = loja.abrir(":memory:")
    pedido_com_taxa_do_bling(con, 20, 1760.0, 127.45, ml_ids=("1",))          # Bling só com o frete; agente 290,40 + 127,45
    pedido_com_taxa_do_bling(con, 21, 500.0, 90.0, ml_ids=("2",))             # Bling igual ao agente: não mexe
    pedido_com_taxa_do_bling(con, 22, 500.0, 150.0, ml_ids=("3",))            # Bling cobra MAIS que o agente: não reduz
    pedido_com_taxa_do_bling(con, 23, 500.0, 90.0, ml_ids=("4",))             # diferença de R$ 1 (dentro da tolerância)
    agente = AgenteFalso({"1": (290.40, 127.45, 1), "2": (60.0, 30.0, 1), "3": (60.0, 30.0, 1), "4": (61.0, 30.0, 1)})
    r = la.completar_liquido_pelo_agente(con, agente, hoje=date(2026, 11, 3), log=lambda *_: None)
    assert r == {"candidatos": 4, "completados": 1, "sem_dado_no_agente": 0, "taxa_maior_que_bruto": 0}
    assert liquidos(con, 20) == [1342.15]                  # 1760 - (290,40 + 127,45)
    assert liquidos(con, 21) == [410.0] and liquidos(con, 22) == [350.0] and liquidos(con, 23) == [410.0]
    assert loja.obter_pedido(con, 20)["liquido_origem"] == la.ORIGEM_AGENTE
    # segunda passada: o completado não é mais candidato
    assert la.completar_liquido_pelo_agente(con, agente, hoje=date(2026, 11, 3), log=lambda *_: None)["candidatos"] == 3


def teste_completar_respeita_o_limite_de_dias_e_dados_ausentes():
    from datetime import date

    con = loja.abrir(":memory:")
    pedido_com_taxa_do_bling(con, 30, 1000.0, 100.0, ml_ids=("5",), data="2026-08-01")   # antigo
    pedido_com_taxa_do_bling(con, 31, 1000.0, 100.0, ml_ids=("6",), data="2026-10-30")   # recente, mas o agente não tem
    pedido_com_taxa_do_bling(con, 32, 100.0, 10.0, ml_ids=("7",), data="2026-10-30")     # taxa do agente maior que o bruto
    agente = AgenteFalso({"5": (300.0, 0.0, 1), "7": (80.0, 40.0, 1)})
    r = la.completar_liquido_pelo_agente(con, agente, dias=30, hoje=date(2026, 11, 3), log=lambda *_: None)
    assert r == {"candidatos": 2, "completados": 0, "sem_dado_no_agente": 1, "taxa_maior_que_bruto": 1}
    assert liquidos(con, 30) == [900.0]                     # fora da janela de 30 dias: intocado
    r_tudo = la.completar_liquido_pelo_agente(con, agente, dias=None, hoje=date(2026, 11, 3), log=lambda *_: None)
    assert r_tudo["candidatos"] == 3 and r_tudo["completados"] == 1 and liquidos(con, 30) == [700.0]


def teste_banco_antigo_ganha_a_coluna_sem_perder_dados():
    import sqlite3

    antigo = sqlite3.connect(":memory:")
    antigo.executescript(loja.ESQUEMA)  # sem liquido_origem
    antigo.row_factory = sqlite3.Row
    assert "liquido_origem" not in {r[1] for r in antigo.execute("PRAGMA table_info(pedidos)")}
    # a mesma lógica do abrir(): ALTER TABLE quando falta
    if "liquido_origem" not in {r[1] for r in antigo.execute("PRAGMA table_info(pedidos)")}:
        antigo.execute("ALTER TABLE pedidos ADD COLUMN liquido_origem TEXT")
    assert "liquido_origem" in {r[1] for r in antigo.execute("PRAGMA table_info(pedidos)")}


if __name__ == "__main__":
    testes = [v for k, v in sorted(globals().items()) if k.startswith("teste_")]
    for t in testes:
        t()
        print(f"[ok] {t.__name__}")
    print(f"\n{len(testes)}/{len(testes)} testes passaram.")
