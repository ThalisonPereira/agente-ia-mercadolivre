"""
database/vendas_bling_local.py

Armazenamento LOCAL (SQLite, arquivo dados_locais/vendas_bling.db, ignorado pelo git) dos pedidos de venda
do Bling por canal. É a etapa 1 do plano: coletar e conferir em Python antes de levar qualquer coisa ao
Lovable. Não toca no banco de produção. Só guarda campos de negócio (nenhum dado de comprador).
"""

import sqlite3
from datetime import datetime
from pathlib import Path

CAMINHO_PADRAO = Path(__file__).resolve().parent.parent / "dados_locais" / "vendas_bling.db"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS pedidos (
    pedido_id        INTEGER PRIMARY KEY,
    numero           INTEGER,
    numero_loja      TEXT,
    loja_id          INTEGER,
    canal            TEXT,
    usa_em_vendas    INTEGER NOT NULL DEFAULT 0,
    situacao_id      INTEGER,
    conta_venda      INTEGER NOT NULL DEFAULT 0,
    data_bling       TEXT,
    data_venda       TEXT,
    data_origem      TEXT,
    ml_order_ids     TEXT,
    total_produtos   REAL,
    taxas_ausentes   INTEGER NOT NULL DEFAULT 0,
    soma_diverge     INTEGER NOT NULL DEFAULT 0,
    detalhe_ok       INTEGER NOT NULL DEFAULT 0,
    atualizado_em    TEXT
);
CREATE TABLE IF NOT EXISTS itens (
    pedido_id      INTEGER NOT NULL,
    linha          INTEGER NOT NULL,
    sku            TEXT,
    quantidade     REAL,
    valor_bruto    REAL,
    valor_liquido  REAL,
    PRIMARY KEY (pedido_id, linha)
);
CREATE INDEX IF NOT EXISTS idx_pedidos_data ON pedidos (data_venda);
CREATE INDEX IF NOT EXISTS idx_pedidos_loja ON pedidos (numero_loja);
"""


def abrir(caminho: Path | str | None = None) -> sqlite3.Connection:
    caminho = Path(caminho) if caminho else CAMINHO_PADRAO
    if str(caminho) != ":memory:":
        caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(caminho))
    con.row_factory = sqlite3.Row
    con.executescript(ESQUEMA)
    return con


def obter_pedido(con: sqlite3.Connection, pedido_id: int) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM pedidos WHERE pedido_id = ?", (pedido_id,)).fetchone()


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def salvar_cabecalho(con: sqlite3.Connection, cab: dict, canal: str, usa: bool, conta_venda: bool) -> None:
    """Pedido que não conta como venda (ou ainda sem detalhe): guarda só o cabeçalho, sem apagar um detalhe já salvo."""
    existente = obter_pedido(con, cab["id"])
    if existente is None:
        con.execute(
            "INSERT INTO pedidos (pedido_id, numero, numero_loja, loja_id, canal, usa_em_vendas, situacao_id, conta_venda,"
            " data_bling, total_produtos, atualizado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (cab["id"], cab.get("numero"), str(cab.get("numeroLoja") or ""), (cab.get("loja") or {}).get("id"), canal,
             int(usa), (cab.get("situacao") or {}).get("id"), int(conta_venda), str(cab.get("data") or "")[:10],
             cab.get("totalProdutos"), _agora()))
    else:
        con.execute("UPDATE pedidos SET situacao_id = ?, conta_venda = ?, atualizado_em = ? WHERE pedido_id = ?",
                    ((cab.get("situacao") or {}).get("id"), int(conta_venda), _agora(), cab["id"]))
    con.commit()


def salvar_pedido_completo(con: sqlite3.Connection, linhas: list[dict], alertas: dict, data_venda: str,
                           data_origem: str, ml_order_ids: list | None, total_produtos: float | None) -> None:
    """Grava o pedido com seus itens de uma vez (transação única): ou entra inteiro, ou não entra."""
    if not linhas:
        return
    p = linhas[0]
    with con:
        con.execute("DELETE FROM itens WHERE pedido_id = ?", (p["pedido_id"],))
        con.execute(
            "INSERT OR REPLACE INTO pedidos (pedido_id, numero, numero_loja, loja_id, canal, usa_em_vendas, situacao_id,"
            " conta_venda, data_bling, data_venda, data_origem, ml_order_ids, total_produtos, taxas_ausentes, soma_diverge,"
            " detalhe_ok, atualizado_em) VALUES (?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,1,?)",
            (p["pedido_id"], p["numero"], p["numero_loja"], p["loja_id"], p["canal"], int(p["usa_em_vendas"]), p["situacao_id"],
             p["data"], data_venda, data_origem, ",".join(str(x) for x in (ml_order_ids or [])), total_produtos,
             int(alertas["taxas_ausentes"]), int(alertas["soma_diverge"]), _agora()))
        con.executemany(
            "INSERT INTO itens (pedido_id, linha, sku, quantidade, valor_bruto, valor_liquido) VALUES (?,?,?,?,?,?)",
            [(l["pedido_id"], i, l["sku"], l["quantidade"], l["valor_bruto"], l["valor_liquido"]) for i, l in enumerate(linhas)])


def atualizar_data(con: sqlite3.Connection, pedido_id: int, data_venda: str, data_origem: str, ml_order_ids: list | None) -> None:
    con.execute("UPDATE pedidos SET data_venda = ?, data_origem = ?, ml_order_ids = ?, atualizado_em = ? WHERE pedido_id = ?",
                (data_venda, data_origem, ",".join(str(x) for x in (ml_order_ids or [])), _agora(), pedido_id))
    con.commit()


def pendentes_de_data(con: sqlite3.Connection, data_ini: str, data_fim: str) -> list[sqlite3.Row]:
    """Pedidos de marketplace de vendas com data só aproximada (a consulta ao ML falhou antes)."""
    return con.execute(
        "SELECT * FROM pedidos WHERE usa_em_vendas = 1 AND conta_venda = 1 AND data_origem = 'bling_aprox' "
        "AND data_bling BETWEEN ? AND ? ORDER BY pedido_id", (data_ini, data_fim)).fetchall()


def totais(con: sqlite3.Connection, data_ini: str, data_fim: str) -> list[sqlite3.Row]:
    """Por canal (só os usados em vendas): pedidos, unidades, bruto e líquido, pela data REAL da venda."""
    return con.execute(
        "SELECT p.canal, COUNT(DISTINCT p.pedido_id) pedidos, SUM(i.quantidade) unidades, ROUND(SUM(i.valor_bruto), 2) bruto,"
        " ROUND(SUM(i.valor_liquido), 2) liquido FROM pedidos p JOIN itens i ON i.pedido_id = p.pedido_id "
        "WHERE p.usa_em_vendas = 1 AND p.conta_venda = 1 AND p.data_venda BETWEEN ? AND ? GROUP BY p.canal ORDER BY p.canal",
        (data_ini, data_fim)).fetchall()
