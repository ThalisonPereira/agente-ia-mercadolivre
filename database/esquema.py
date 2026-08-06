"""
database/esquema.py

Define a estrutura (schema) das tabelas do banco local.
"""

from database.conexao import obter_conexao

CRIAR_TABELA_ANUNCIOS = """
CREATE TABLE IF NOT EXISTS anuncios (
    item_id        TEXT PRIMARY KEY,
    titulo         TEXT,
    sku            TEXT,
    atualizado_em  TEXT
);
"""

CRIAR_TABELA_HISTORICO_DIARIO = """
CREATE TABLE IF NOT EXISTS historico_anuncios_diario (
    item_id            TEXT,
    data_snapshot      TEXT,
    visitas            INTEGER,
    vendas_quantidade  INTEGER,
    receita            REAL,
    capturado_em       TEXT,
    PRIMARY KEY (item_id, data_snapshot)
);
"""


def criar_tabelas() -> None:
    """Cria todas as tabelas do banco, se ainda não existirem."""
    conexao = obter_conexao()
    try:
        conexao.execute(CRIAR_TABELA_ANUNCIOS)
        conexao.execute(CRIAR_TABELA_HISTORICO_DIARIO)
        conexao.commit()
        print("Tabelas 'anuncios' e 'historico_anuncios_diario' prontas.")
    finally:
        conexao.close()
