"""
database/esquema.py

Define a estrutura (schema) das tabelas do banco (Turso). Multi-conta desde
2026-08-06: todo dado pertence a uma "conta" (uma credencial específica, num
canal específico - ex: "Mercado Livre - HC", "Shopee - Principal"), pra
suportar múltiplas contas do Mercado Livre e, no futuro, outros canais
(Shopee, Amazon).
"""

from database.conexao_supabase import obter_conexao

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

# Cache local do número de pedido do Bling, cruzado pelo pedido do
# Mercado Livre (campo 'numeroLoja' do Bling == pedido_id do ML, quando o
# pedido veio da integração automática ML->Bling). Não é multi-conta -
# mesmo princípio de custo_produtos (credencial única do Bling). Ver
# integrations/bling.py::listar_pedidos_vendas e database/pedidos_bling.py.
CRIAR_TABELA_PEDIDOS_BLING = """
CREATE TABLE IF NOT EXISTS pedidos_bling (
    numero_loja     TEXT PRIMARY KEY,
    numero_bling    TEXT,
    id_bling        TEXT,
    atualizado_em   TEXT
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

# Pedidos criados num dia mas só pagos (fechados) em outro dia (comum com
# boleto) - o relatório oficial do Mercado Livre parece contar pela data de
# PAGAMENTO, enquanto itens_venda conta pela data de CRIAÇÃO (decisão
# consciente do usuário, ver database/extrato.py). Essa tabela não altera
# esse critério - só guarda uma referência do pedido no dia em que ele
# apareceria no relatório oficial, pra explicar a diferença de totais sem
# o usuário precisar investigar de novo toda vez que aparecer. Nunca conta
# em nenhum total (ver database/extrato_referencia.py) - é só observação.
CRIAR_TABELA_ITENS_VENDA_REFERENCIA = """
CREATE TABLE IF NOT EXISTS itens_venda_referencia (
    conta_id             TEXT,
    pedido_id            TEXT,
    item_id              TEXT,
    sku                  TEXT,
    titulo               TEXT,
    data_pagamento       TEXT,
    data_criacao         TEXT,
    quantidade           INTEGER,
    preco_venda          REAL,
    numero_pedido_bling  TEXT,
    capturado_em         TEXT,
    PRIMARY KEY (conta_id, pedido_id, item_id, data_pagamento)
);
"""

# Publicidade (Mercado Ads / Product Ads) - 1 linha por campanha/anúncio por
# dia (mesmo princípio de historico_anuncios_diario), com as métricas já
# somadas pro dia pela própria API do Mercado Livre (date_from == date_to).
# item_id segue a mesma convenção da tabela anuncios, pra permitir cruzar
# custo de publicidade com margem no futuro (não implementado ainda).
CRIAR_TABELA_ADS_CAMPANHAS_DIARIO = """
CREATE TABLE IF NOT EXISTS ads_campanhas_diario (
    conta_id                TEXT,
    campaign_id              INTEGER,
    data                     TEXT,
    nome                     TEXT,
    status                   TEXT,
    strategy                 TEXT,
    budget                   REAL,
    acos_target              REAL,
    roas_target              REAL,
    clicks                   INTEGER,
    prints                   INTEGER,
    cost                     REAL,
    cpc                      REAL,
    ctr                      REAL,
    acos                     REAL,
    cvr                      REAL,
    roas                     REAL,
    direct_amount            REAL,
    indirect_amount          REAL,
    total_amount             REAL,
    direct_units_quantity    INTEGER,
    indirect_units_quantity  INTEGER,
    units_quantity           INTEGER,
    capturado_em             TEXT,
    PRIMARY KEY (conta_id, campaign_id, data)
);
"""

CRIAR_TABELA_ADS_ANUNCIOS_DIARIO = """
CREATE TABLE IF NOT EXISTS ads_anuncios_diario (
    conta_id         TEXT,
    item_id          TEXT,
    campaign_id      INTEGER,
    data             TEXT,
    titulo           TEXT,
    status           TEXT,
    clicks           INTEGER,
    prints           INTEGER,
    cost             REAL,
    cpc              REAL,
    acos             REAL,
    direct_amount    REAL,
    indirect_amount  REAL,
    total_amount     REAL,
    units_quantity   INTEGER,
    capturado_em     TEXT,
    PRIMARY KEY (conta_id, item_id, data)
);
"""

# Análise narrativa diária da IA especializada em publicidade - mesmo shape
# de analises_diarias, em tabela separada porque o conteúdo/prompt é bem
# diferente (foco em ACOS/ROAS/orçamento, não visitas/vendas orgânicas).
CRIAR_TABELA_ANALISES_ADS_DIARIAS = """
CREATE TABLE IF NOT EXISTS analises_ads_diarias (
    conta_id     TEXT,
    data         TEXT,
    texto        TEXT,
    gerado_em    TEXT,
    PRIMARY KEY (conta_id, data)
);
"""

# Análise narrativa diária de estoque (divergência Bling x Mercado Livre +
# anúncios ranqueados em risco de pausar) - SEM conta_id, diferente das
# outras análises: estoque é compartilhado pelas 3 contas (mesmo depósito
# físico no Bling), então é sempre uma análise única "geral" por dia.
CRIAR_TABELA_ANALISES_ESTOQUE_DIARIAS = """
CREATE TABLE IF NOT EXISTS analises_estoque_diarias (
    data         TEXT PRIMARY KEY,
    texto        TEXT,
    gerado_em    TEXT
);
"""

# Snapshot do resultado já calculado por database/estoque.py::obter_divergencias()
# - sempre reflete só o estado ATUAL (não é histórico por dia, é
# sobrescrita completa a cada rodada da rotina, ver
# database/estoque.py::salvar_divergencias). Existe pra o painel Lovable
# (e qualquer outro consumidor) só LER o resultado já pronto, sem
# duplicar a lógica de dedup de anúncios vinculados em outro lugar.
# Uma linha por ANÚNCIO (ou grupo de anúncios vinculados dentro da mesma
# conta - ver database/estoque.py) - NÃO por SKU somado entre anúncios
# não vinculados (mudança de desenho: somar gerava falso positivo quando
# vários anúncios independentes coincidem no mesmo SKU, achado real do
# usuário testando SKU '22001').
CRIAR_TABELA_ESTOQUE_DIVERGENCIAS = """
CREATE TABLE IF NOT EXISTS estoque_divergencias (
    conta_id                    TEXT,
    item_id                     TEXT,
    titulo                      TEXT,
    sku                         TEXT,
    publicado                   INTEGER,
    saldo_bling                 INTEGER,
    diferenca                   INTEGER,
    categoria                   TEXT,
    outros_anuncios_mesmo_sku   INTEGER,
    atualizado_em                TEXT,
    PRIMARY KEY (conta_id, item_id)
);
"""

# Mesmo princípio, pro resultado de obter_anuncios_em_risco().
CRIAR_TABELA_ESTOQUE_RISCO = """
CREATE TABLE IF NOT EXISTS estoque_risco (
    conta_id                   TEXT,
    item_id                    TEXT,
    anuncio                    TEXT,
    sku                        TEXT,
    receita_periodo            REAL,
    estoque_disponivel         INTEGER,
    media_diaria_vendas        REAL,
    dias_restantes_estimados   REAL,
    atualizado_em              TEXT,
    PRIMARY KEY (conta_id, item_id)
);
"""

# --------------------------------------------------------------------------
# Central de Alertas (Fase 3.3) - captura de eventos pós-venda (perguntas,
# mensagens, reclamações, devoluções) via webhook do Mercado Livre,
# processados por um worker Python, alertando o painel Lovable via Realtime.
# Ver auditoria/desenho completo nas Fases 2.x/3.x desta sessão - JSONB/
# TIMESTAMPTZ/FK são um desvio deliberado do resto do schema (que usa só
# TEXT/INTEGER/REAL), justificado pela necessidade real de consulta
# estruturada (claim de fila, histórico por recurso) que essas 4 tabelas
# têm e as demais não.
#
# Evento bruto recebido do webhook do Mercado Livre (gravado pelo endpoint
# no Lovable) - nunca alterado depois de inserido, exceto pelos campos de
# controle de processamento (status/erro/tentativas). `id` é o próprio id
# do evento gerado pelo Mercado Livre - reentrega do mesmo webhook (mesmo
# id) é ignorada na inserção (ON CONFLICT DO NOTHING), garantindo
# idempotência na entrada. `conta_id` fica NULL até o worker resolver
# application_id -> conta_id (não se resolve no recebimento do webhook,
# que precisa responder rápido e sem lógica pesada).
CRIAR_TABELA_EVENTOS_ML_WEBHOOK = """
CREATE TABLE IF NOT EXISTS eventos_ml_webhook (
    id                          TEXT PRIMARY KEY,
    conta_id                    TEXT NULL,
    topico                      TEXT NOT NULL,
    recurso                     TEXT NOT NULL,
    user_id_ml                  TEXT NOT NULL,
    application_id              TEXT NOT NULL,
    actions                     JSONB NULL,
    ml_attempts                 INTEGER NULL,
    sent_em                     TIMESTAMPTZ NULL,
    recebido_em                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload_bruto               JSONB NOT NULL,
    processando_em              TIMESTAMPTZ NULL,
    processado_em                TIMESTAMPTZ NULL,
    status_processamento        TEXT NOT NULL DEFAULT 'pendente'
        CHECK (status_processamento IN ('pendente','processando','processado','erro')),
    erro_processamento           TEXT NULL,
    tentativas_processamento     INTEGER NOT NULL DEFAULT 0
        CHECK (tentativas_processamento >= 0)
);
"""

# Resultado normalizado de um evento processado com sucesso - histórico
# completo (nunca sobrescrito), 1 linha por evento bruto processado (PK
# reaproveita o id do evento_webhook, propagando a mesma idempotência).
# Eventos legítimos diferentes do mesmo recurso (ex: 2 perguntas separadas
# no mesmo anúncio) geram 2 linhas aqui, com PKs diferentes - não há
# unicidade por recurso_id, só por evento_webhook_id.
CRIAR_TABELA_EVENTOS_ML_PROCESSADOS = """
CREATE TABLE IF NOT EXISTS eventos_ml_processados (
    evento_webhook_id       TEXT PRIMARY KEY,
    conta_id                 TEXT NOT NULL,
    tipo_normalizado         TEXT NOT NULL
        CHECK (tipo_normalizado IN ('pergunta','mensagem','reclamacao','devolucao')),
    recurso_original          TEXT NOT NULL,
    recurso_id                TEXT NOT NULL,
    data_evento_ml             TIMESTAMPTZ NULL,
    snapshot_ml                JSONB NOT NULL,
    identificadores            JSONB NULL,
    versao_normalizador        INTEGER NOT NULL DEFAULT 1,
    processado_em               TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

# Estado ATUAL da ocorrência (não histórico - isso é eventos_ml_processados).
# status_interno é controlado manualmente pelo usuário no painel (aberto/em_
# andamento/resolvido); visto_pelo_usuario é global (não por usuário - a V1
# decidiu que todos os usuários do painel recebem os mesmos alertas, ver
# Fase 3.1). Um evento novo para um recurso já existente SEMPRE reabre o
# alerta (status_interno volta pra 'aberto', visto_pelo_usuario volta pra 0),
# mesmo que estivesse 'resolvido' - ver database/eventos_alertas.py.
CRIAR_TABELA_ALERTAS_POS_VENDA = """
CREATE TABLE IF NOT EXISTS alertas_pos_venda (
    conta_id                    TEXT NOT NULL,
    tipo                        TEXT NOT NULL
        CHECK (tipo IN ('pergunta','mensagem','reclamacao','devolucao')),
    recurso_id                   TEXT NOT NULL,
    titulo                       TEXT NULL,
    resumo                       TEXT NULL,
    texto                        TEXT NULL,
    status_externo                TEXT NULL,
    status_interno                TEXT NOT NULL DEFAULT 'aberto'
        CHECK (status_interno IN ('aberto','em_andamento','resolvido')),
    visto_pelo_usuario             INTEGER NOT NULL DEFAULT 0
        CHECK (visto_pelo_usuario IN (0,1)),
    data_evento_ml                  TIMESTAMPTZ NULL,
    detectado_em                     TIMESTAMPTZ NOT NULL,
    atualizado_em                     TIMESTAMPTZ NOT NULL,
    ultimo_evento_webhook_id           TEXT NULL,
    dados_auxiliares                   JSONB NULL,
    PRIMARY KEY (conta_id, tipo, recurso_id)
);
"""

# Obrigação de notificação (wake-up via Realtime) - 1 linha por evento
# processado (PK reaproveita evento_processado_id, mesma cadeia de
# idempotência). O Broadcast em si NUNCA é fonte de verdade - esta tabela
# é. status='publicada' é setado pelo publicador (Lovable, via chave
# privilegiada), nunca pelo worker Python que só cria a obrigação como
# 'pendente'.
CRIAR_TABELA_NOTIFICACOES_ALERTA = """
CREATE TABLE IF NOT EXISTS notificacoes_alerta (
    evento_processado_id     TEXT PRIMARY KEY,
    conta_id                  TEXT NOT NULL,
    tipo                       TEXT NOT NULL
        CHECK (tipo IN ('pergunta','mensagem','reclamacao','devolucao')),
    recurso_id                  TEXT NOT NULL,
    status                       TEXT NOT NULL DEFAULT 'pendente'
        CHECK (status IN ('pendente','publicada')),
    criado_em                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    publicada_em                   TIMESTAMPTZ NULL
);
"""

# FKs das 4 tabelas acima - aplicadas incrementalmente (ver _aplicar_fks),
# porque "CREATE TABLE IF NOT EXISTS" não adiciona constraint a uma tabela
# já existente. Prioridade é preservar histórico (RESTRICT), não facilitar
# deletes - só o ponteiro auxiliar ultimo_evento_webhook_id usa SET NULL.
_FKS_ALERTAS = [
    ("eventos_ml_webhook", "fk_eventos_webhook_conta", "(conta_id)", "contas(conta_id)", "RESTRICT"),
    ("eventos_ml_processados", "fk_eventos_processados_webhook", "(evento_webhook_id)", "eventos_ml_webhook(id)", "RESTRICT"),
    ("eventos_ml_processados", "fk_eventos_processados_conta", "(conta_id)", "contas(conta_id)", "RESTRICT"),
    ("alertas_pos_venda", "fk_alertas_conta", "(conta_id)", "contas(conta_id)", "RESTRICT"),
    ("alertas_pos_venda", "fk_alertas_ultimo_evento", "(ultimo_evento_webhook_id)", "eventos_ml_webhook(id)", "SET NULL"),
    ("notificacoes_alerta", "fk_notificacoes_evento_processado", "(evento_processado_id)", "eventos_ml_processados(evento_webhook_id)", "RESTRICT"),
    ("notificacoes_alerta", "fk_notificacoes_alerta", "(conta_id, tipo, recurso_id)", "alertas_pos_venda(conta_id, tipo, recurso_id)", "RESTRICT"),
]

# Índices das 4 tabelas - só os que sustentam uma query real do fluxo (claim
# de fila, listagem mais recente, contagem de não-vistos, publicador de
# notificação) - CREATE INDEX IF NOT EXISTS já é nativamente idempotente no
# Postgres, sem precisar do mesmo tipo de checagem manual das colunas/FKs.
_INDICES_ALERTAS = [
    "CREATE INDEX IF NOT EXISTS ix_eventos_webhook_pendente ON eventos_ml_webhook (recebido_em) WHERE status_processamento = 'pendente'",
    "CREATE INDEX IF NOT EXISTS ix_eventos_webhook_processando ON eventos_ml_webhook (processando_em) WHERE status_processamento = 'processando'",
    "CREATE INDEX IF NOT EXISTS ix_eventos_webhook_erro ON eventos_ml_webhook (tentativas_processamento) WHERE status_processamento = 'erro'",
    "CREATE INDEX IF NOT EXISTS ix_eventos_processados_recurso ON eventos_ml_processados (conta_id, tipo_normalizado, recurso_id)",
    "CREATE INDEX IF NOT EXISTS ix_alertas_atualizado ON alertas_pos_venda (atualizado_em DESC)",
    "CREATE INDEX IF NOT EXISTS ix_alertas_nao_vistos ON alertas_pos_venda (atualizado_em DESC) WHERE visto_pelo_usuario = 0",
    "CREATE INDEX IF NOT EXISTS ix_notificacoes_pendente ON notificacoes_alerta (criado_em) WHERE status = 'pendente'",
    "CREATE INDEX IF NOT EXISTS ix_notificacoes_alerta_fk ON notificacoes_alerta (conta_id, tipo, recurso_id)",
]

# As 4 tabelas ficam com RLS habilitada e SEM NENHUMA policy (deny total
# pra 'anon'/'authenticated') - mais rígido que o resto do schema (que não
# tem RLS nenhuma, ver auditoria da Fase 2.2), de propósito: só uma chave
# service_role (nunca anon) deve ler/escrever aqui. Ver Fase 3.2 seção 8 -
# essa chave privilegiada pro projeto EXTERNO ainda não existe, é uma
# pendência de infraestrutura a criar antes do Lovable conseguir ler estas
# tabelas. ALTER TABLE ... ENABLE ROW LEVEL SECURITY é idempotente (seguro
# re-executar).
_TABELAS_RLS_ALERTAS = [
    "eventos_ml_webhook", "eventos_ml_processados", "alertas_pos_venda", "notificacoes_alerta",
]


def _aplicar_fks(conexao) -> None:
    for tabela, nome_fk, colunas, referencia, on_delete in _FKS_ALERTAS:
        existe = conexao.execute(
            "SELECT 1 FROM pg_constraint WHERE conname = %(nome)s", {"nome": nome_fk}
        ).fetchone()
        if not existe:
            conexao.execute(
                f"ALTER TABLE {tabela} ADD CONSTRAINT {nome_fk} "
                f"FOREIGN KEY {colunas} REFERENCES {referencia} ON DELETE {on_delete}"
            )


def _aplicar_indices_alertas(conexao) -> None:
    for sql in _INDICES_ALERTAS:
        conexao.execute(sql)


def _aplicar_rls_alertas(conexao) -> None:
    for tabela in _TABELAS_RLS_ALERTAS:
        conexao.execute(f"ALTER TABLE {tabela} ENABLE ROW LEVEL SECURITY")


# Migrações incrementais - adicionam coluna a tabelas que já existiam antes
# dela ser criada. "CREATE TABLE IF NOT EXISTS" não altera tabela já
# existente, por isso precisa desse passo à parte. Cada entrada é
# (tabela, coluna, definição) - só tenta o ALTER se a coluna ainda não
# existir (checado via information_schema.columns antes, equivalente ao
# PRAGMA table_info do SQLite/Turso - Postgres não tem PRAGMA).
_MIGRACOES_COLUNA = [
    ("itens_venda", "status", "TEXT DEFAULT 'pago'"),
    # Custo unitário do produto (Bling) capturado no MOMENTO da coleta, não
    # buscado por JOIN dinâmico na consulta - assim a margem de uma venda
    # antiga não muda retroativamente se o custo mudar depois no Bling, e o
    # cálculo já multiplica pela quantidade da linha (ver database/extrato.py).
    ("itens_venda", "custo_unitario_capturado", "REAL"),
    # Estoque (Bling: estoque.saldoVirtualTotal; ML: available_quantity +
    # status) - os dois já vêm de graça nas chamadas que o projeto já faz
    # todo dia (listar_produtos/coletar_dados_do_dia), só não eram gravados
    # até agora. Ver database/estoque.py pro cálculo de divergência/risco.
    ("custo_produtos", "estoque_saldo", "INTEGER"),
    ("anuncios", "estoque_disponivel", "INTEGER"),
    ("anuncios", "status", "TEXT"),
    # Identificador do "produto vinculado" do Mercado Livre (inventory_id
    # ou, na ausência, user_product_id) - quando 2+ anúncios da MESMA conta
    # compartilham esse id, o ML sincroniza o estoque entre eles sozinho
    # (vender em um desconta dos outros); por isso NÃO dá pra somar
    # estoque_disponivel por SKU sem antes deduplicar por esse grupo,
    # senão o mesmo estoque físico é contado 2x (achado real testando: SKU
    # com 2 anúncios vinculados, 9 unidades reais, contado como 18).
    ("anuncios", "grupo_estoque_id", "TEXT"),
    # Número do pedido no Bling (cruzado pelo numeroLoja == pedido_id do
    # ML) - capturado no momento da gravação do item de venda, mesmo
    # princípio de custo_unitario_capturado (snapshot, não JOIN dinâmico).
    ("itens_venda", "numero_pedido_bling", "TEXT"),
]


def _aplicar_migracoes(conexao) -> None:
    for tabela, coluna, definicao in _MIGRACOES_COLUNA:
        colunas_existentes = {
            linha["column_name"]
            for linha in conexao.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %(tabela)s",
                {"tabela": tabela},
            ).fetchall()
        }
        if coluna not in colunas_existentes:
            conexao.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}")


def _migrar_estoque_divergencias(conexao) -> None:
    """
    estoque_divergencias mudou de "1 linha por SKU somado" pra "1 linha
    por anúncio" (chave/colunas diferentes - ver database/estoque.py) -
    "CREATE TABLE IF NOT EXISTS" não altera uma tabela já existente no
    formato antigo, então descarta e recria. Seguro: é só um snapshot
    sempre sobrescrito por completo a cada rodada (salvar_divergencias),
    não guarda histórico.
    """
    colunas_existentes = {
        linha["column_name"]
        for linha in conexao.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'estoque_divergencias'"
        ).fetchall()
    }
    if colunas_existentes and "item_id" not in colunas_existentes:
        conexao.execute("DROP TABLE estoque_divergencias")


def criar_tabelas() -> None:
    """Cria todas as tabelas do banco, se ainda não existirem, e aplica migrações incrementais."""
    conexao = obter_conexao()
    try:
        _migrar_estoque_divergencias(conexao)
        conexao.execute(CRIAR_TABELA_CONTAS)
        conexao.execute(CRIAR_TABELA_ANUNCIOS)
        conexao.execute(CRIAR_TABELA_HISTORICO_DIARIO)
        conexao.execute(CRIAR_TABELA_ANALISES_DIARIAS)
        conexao.execute(CRIAR_TABELA_TOKENS_OAUTH)
        conexao.execute(CRIAR_TABELA_PEDIDOS)
        conexao.execute(CRIAR_TABELA_CUSTO_PRODUTOS)
        conexao.execute(CRIAR_TABELA_PEDIDOS_BLING)
        conexao.execute(CRIAR_TABELA_ITENS_VENDA)
        conexao.execute(CRIAR_TABELA_ITENS_VENDA_REFERENCIA)
        conexao.execute(CRIAR_TABELA_ADS_CAMPANHAS_DIARIO)
        conexao.execute(CRIAR_TABELA_ADS_ANUNCIOS_DIARIO)
        conexao.execute(CRIAR_TABELA_ANALISES_ADS_DIARIAS)
        conexao.execute(CRIAR_TABELA_ANALISES_ESTOQUE_DIARIAS)
        conexao.execute(CRIAR_TABELA_ESTOQUE_DIVERGENCIAS)
        conexao.execute(CRIAR_TABELA_ESTOQUE_RISCO)
        conexao.execute(CRIAR_TABELA_EVENTOS_ML_WEBHOOK)
        conexao.execute(CRIAR_TABELA_EVENTOS_ML_PROCESSADOS)
        conexao.execute(CRIAR_TABELA_ALERTAS_POS_VENDA)
        conexao.execute(CRIAR_TABELA_NOTIFICACOES_ALERTA)
        _aplicar_migracoes(conexao)
        _aplicar_fks(conexao)
        _aplicar_indices_alertas(conexao)
        _aplicar_rls_alertas(conexao)
        conexao.commit()
        print(
            "Tabelas prontas: contas, anuncios, historico_anuncios_diario, "
            "analises_diarias, tokens_oauth, pedidos, custo_produtos, itens_venda, "
            "ads_campanhas_diario, ads_anuncios_diario, analises_ads_diarias, "
            "analises_estoque_diarias, estoque_divergencias, estoque_risco, pedidos_bling, "
            "itens_venda_referencia, eventos_ml_webhook, eventos_ml_processados, "
            "alertas_pos_venda, notificacoes_alerta."
        )
    finally:
        conexao.close()
