"""
database/esquema.py

Define a estrutura (schema) das tabelas do banco local.
"""

from database.conexao_turso import obter_conexao

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

# Guarda a análise narrativa diária no banco (além de reports/*.md e da aba
# "Análise IA" do Sheets) porque reports/*.md só existe na máquina onde a
# rotina diária roda - o chat hospedado no Streamlit Cloud não tem acesso a
# esse arquivo, mas consegue ler esta tabela.
CRIAR_TABELA_ANALISES_DIARIAS = """
CREATE TABLE IF NOT EXISTS analises_diarias (
    data         TEXT PRIMARY KEY,
    texto        TEXT,
    gerado_em    TEXT
);
"""


def criar_tabelas() -> None:
    """Cria todas as tabelas do banco, se ainda não existirem."""
    conexao = obter_conexao()
    try:
        conexao.execute(CRIAR_TABELA_ANUNCIOS)
        conexao.execute(CRIAR_TABELA_HISTORICO_DIARIO)
        conexao.execute(CRIAR_TABELA_ANALISES_DIARIAS)
        conexao.commit()
        print("Tabelas 'anuncios', 'historico_anuncios_diario' e 'analises_diarias' prontas.")
    finally:
        conexao.close()
