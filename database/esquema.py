"""
database/esquema.py

Define a estrutura (schema) das tabelas do banco (Turso). Multi-conta desde
2026-08-06: todo dado pertence a uma "conta" (uma credencial específica, num
canal específico - ex: "Mercado Livre - HC", "Shopee - Principal"), pra
suportar múltiplas contas do Mercado Livre e, no futuro, outros canais
(Shopee, Amazon).
"""

from database.conexao_turso import obter_conexao

CRIAR_TABELA_CONTAS = """
CREATE TABLE IF NOT EXISTS contas (
    conta_id    TEXT PRIMARY KEY,
    canal       TEXT NOT NULL,
    nome        TEXT,
    ativo       INTEGER DEFAULT 1,
    criado_em   TEXT
);
"""

CRIAR_TABELA_ANUNCIOS = """
CREATE TABLE IF NOT EXISTS anuncios (
    conta_id       TEXT,
    item_id        TEXT,
    titulo         TEXT,
    sku            TEXT,
    atualizado_em  TEXT,
    PRIMARY KEY (conta_id, item_id)
);
"""

CRIAR_TABELA_HISTORICO_DIARIO = """
CREATE TABLE IF NOT EXISTS historico_anuncios_diario (
    conta_id           TEXT,
    item_id            TEXT,
    data_snapshot      TEXT,
    visitas            INTEGER,
    vendas_quantidade  INTEGER,
    receita            REAL,
    capturado_em       TEXT,
    PRIMARY KEY (conta_id, item_id, data_snapshot)
);
"""

# Guarda a análise narrativa diária no banco (além de reports/*.md e da aba
# "Análise IA" do Sheets) porque reports/*.md só existe na máquina onde a
# rotina diária roda - o chat hospedado no Streamlit Cloud não tem acesso a
# esse arquivo, mas consegue ler esta tabela. conta_id='geral' é usado pra
# análises que combinam todas as contas.
CRIAR_TABELA_ANALISES_DIARIAS = """
CREATE TABLE IF NOT EXISTS analises_diarias (
    conta_id     TEXT,
    data         TEXT,
    texto        TEXT,
    gerado_em    TEXT,
    PRIMARY KEY (conta_id, data)
);
"""

# Token OAuth guardado como JSON porque cada canal tem formato de credencial
# bem diferente (ML: access/refresh token; Shopee: shop_id + partner_id +
# tokens; Amazon SP-API: refresh token LWA + credenciais AWS) - um blob JSON
# evita forçar um schema rígido comum que não existe de verdade.
CRIAR_TABELA_TOKENS_OAUTH = """
CREATE TABLE IF NOT EXISTS tokens_oauth (
    conta_id       TEXT PRIMARY KEY,
    dados_json     TEXT,
    atualizado_em  TEXT
);
"""

# Um pedido é capturado uma única vez, no dia em que foi criado (mesma
# lógica de "ontem" usada pra visitas/vendas) - o status de envio reflete
# o momento da coleta, não é atualizado depois (ver database/pedidos.py).
CRIAR_TABELA_PEDIDOS = """
CREATE TABLE IF NOT EXISTS pedidos (
    conta_id          TEXT,
    pedido_id         TEXT,
    data_pedido       TEXT,
    status_envio      TEXT,
    substatus_envio   TEXT,
    logistic_type     TEXT,
    valor_total       REAL,
    capturado_em      TEXT,
    PRIMARY KEY (conta_id, pedido_id)
);
"""


def criar_tabelas() -> None:
    """Cria todas as tabelas do banco, se ainda não existirem."""
    conexao = obter_conexao()
    try:
        conexao.execute(CRIAR_TABELA_CONTAS)
        conexao.execute(CRIAR_TABELA_ANUNCIOS)
        conexao.execute(CRIAR_TABELA_HISTORICO_DIARIO)
        conexao.execute(CRIAR_TABELA_ANALISES_DIARIAS)
        conexao.execute(CRIAR_TABELA_TOKENS_OAUTH)
        conexao.execute(CRIAR_TABELA_PEDIDOS)
        conexao.commit()
        print(
            "Tabelas prontas: contas, anuncios, historico_anuncios_diario, "
            "analises_diarias, tokens_oauth, pedidos."
        )
    finally:
        conexao.close()
