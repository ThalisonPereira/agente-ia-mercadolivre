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

# Cache local do custo de produto do Bling (fonte: GET /produtos, campo
# precoCusto), sincronizado 1x por dia junto da rotina - não é uma tabela
# multi-conta, o Bling é uma credencial única compartilhada (ver
# integrations/bling.py). sku é a mesma convenção de código usada no
# Mercado Livre (seller_sku).
CRIAR_TABELA_CUSTO_PRODUTOS = """
CREATE TABLE IF NOT EXISTS custo_produtos (
    sku               TEXT PRIMARY KEY,
    produto_id_bling  TEXT,
    nome              TEXT,
    preco_custo       REAL,
    atualizado_em     TEXT
);
"""

# Extrato diário de margem por venda (linha de pedido/SKU) - valores BRUTOS
# capturados (preço, comissão, frete); imposto e margem são calculados na
# consulta (database/extrato.py), não aqui, pra poder ajustar a alíquota
# sem precisar reprocessar dados já coletados. status='pago' (venda de
# verdade) ou 'cancelado' (aparece no extrato pra não sumir silenciosamente,
# mas com valores zerados - não conta na margem).
CRIAR_TABELA_ITENS_VENDA = """
CREATE TABLE IF NOT EXISTS itens_venda (
    conta_id         TEXT,
    pedido_id        TEXT,
    item_id          TEXT,
    sku              TEXT,
    titulo           TEXT,
    data_venda       TEXT,
    quantidade       INTEGER,
    preco_venda      REAL,
    comissao_ml      REAL,
    frete_vendedor   REAL,
    status           TEXT DEFAULT 'pago',
    capturado_em     TEXT,
    PRIMARY KEY (conta_id, pedido_id, item_id)
);
"""

# Migrações incrementais - adicionam coluna a tabelas que já existiam antes
# dela ser criada. "CREATE TABLE IF NOT EXISTS" não altera tabela já
# existente, por isso precisa desse passo à parte. Cada entrada é
# (tabela, coluna, definição) - só tenta o ALTER se a coluna ainda não
# existir (checado via PRAGMA table_info antes). Importante: NÃO dá pra
# só tentar o ALTER e capturar o erro de "coluna já existe" - o cliente
# HTTP do Turso (libsql_client) quebra com KeyError genérico nesse caso
# específico (a API do Turso responde HTTP 200 com o erro dentro do corpo,
# em vez de um status de erro; a lib só olha o status HTTP e tenta ler um
# campo que não existe na resposta de erro) - então o ALTER redundante
# derrubava toda escrita no banco (criar_tabelas roda em quase todo save).
_MIGRACOES_COLUNA = [
    ("itens_venda", "status", "TEXT DEFAULT 'pago'"),
    # Custo unitário do produto (Bling) capturado no MOMENTO da coleta, não
    # buscado por JOIN dinâmico na consulta - assim a margem de uma venda
    # antiga não muda retroativamente se o custo mudar depois no Bling, e o
    # cálculo já multiplica pela quantidade da linha (ver database/extrato.py).
    ("itens_venda", "custo_unitario_capturado", "REAL"),
]


def _aplicar_migracoes(conexao) -> None:
    for tabela, coluna, definicao in _MIGRACOES_COLUNA:
        colunas_existentes = {
            linha["name"] for linha in conexao.execute(f"PRAGMA table_info({tabela})").fetchall()
        }
        if coluna not in colunas_existentes:
            conexao.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}")


def criar_tabelas() -> None:
    """Cria todas as tabelas do banco, se ainda não existirem, e aplica migrações incrementais."""
    conexao = obter_conexao()
    try:
        conexao.execute(CRIAR_TABELA_CONTAS)
        conexao.execute(CRIAR_TABELA_ANUNCIOS)
        conexao.execute(CRIAR_TABELA_HISTORICO_DIARIO)
        conexao.execute(CRIAR_TABELA_ANALISES_DIARIAS)
        conexao.execute(CRIAR_TABELA_TOKENS_OAUTH)
        conexao.execute(CRIAR_TABELA_PEDIDOS)
        conexao.execute(CRIAR_TABELA_CUSTO_PRODUTOS)
        conexao.execute(CRIAR_TABELA_ITENS_VENDA)
        _aplicar_migracoes(conexao)
        conexao.commit()
        print(
            "Tabelas prontas: contas, anuncios, historico_anuncios_diario, "
            "analises_diarias, tokens_oauth, pedidos, custo_produtos, itens_venda."
        )
    finally:
        conexao.close()
