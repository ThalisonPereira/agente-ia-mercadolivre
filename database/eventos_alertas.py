"""
database/eventos_alertas.py

Persistência da Central de Alertas (Fase 3.3): captura, processamento e
notificação de eventos pós-venda do Mercado Livre (perguntas, mensagens,
reclamações, devoluções). Ver desenho completo nas Fases 2.x/3.x desta sessão.

Quatro conceitos deliberadamente independentes (não confundir):
  1. evento novo         - novo eventos_ml_webhook.id
  2. webhook duplicado    - mesmo id, ignorado por idempotência (ON CONFLICT DO NOTHING)
  3. estado de atendimento - alertas_pos_venda.status_interno (usuário controla)
  4. estado de publicação  - notificacoes_alerta.status (sistema controla)

O worker Python (ver main.py::_processar_eventos_pendentes) só cria a
notificação como 'pendente' - nunca publica Broadcast. Quem publica e marca
'publicada' é o backend Lovable (usa a chave privilegiada do Realtime
interno, que o Python não tem e não deveria ter).
"""

import json
from datetime import datetime, timedelta

from database.conexao_supabase import obter_conexao

MAX_TENTATIVAS_PROCESSAMENTO_EVENTO = 5
TIMEOUT_PROCESSANDO_MINUTOS = 10

INSERT_EVENTO_WEBHOOK = """
INSERT INTO eventos_ml_webhook (
    id, conta_id, topico, recurso, user_id_ml, application_id,
    actions, ml_attempts, sent_em, payload_bruto
) VALUES (
    %(id)s, %(conta_id)s, %(topico)s, %(recurso)s, %(user_id_ml)s, %(application_id)s,
    %(actions)s, %(ml_attempts)s, %(sent_em)s, %(payload_bruto)s
)
ON CONFLICT (id) DO NOTHING
RETURNING id;
"""

CLAIM_EVENTOS_PENDENTES = """
UPDATE eventos_ml_webhook
SET status_processamento = 'processando', processando_em = %(agora)s
WHERE id IN (
    SELECT id FROM eventos_ml_webhook
    WHERE
        status_processamento = 'pendente'
        OR (status_processamento = 'processando' AND processando_em < %(limite_timeout)s)
        OR (status_processamento = 'erro' AND tentativas_processamento < %(max_tentativas)s)
    ORDER BY recebido_em ASC
    LIMIT %(limite)s
    FOR UPDATE SKIP LOCKED
)
RETURNING *;
"""

MARCAR_ERRO_WEBHOOK = """
UPDATE eventos_ml_webhook
SET status_processamento = 'erro',
    erro_processamento = %(mensagem)s,
    tentativas_processamento = tentativas_processamento + 1
WHERE id = %(id)s;
"""

INSERT_EVENTO_PROCESSADO = """
INSERT INTO eventos_ml_processados (
    evento_webhook_id, conta_id, tipo_normalizado, recurso_original, recurso_id,
    data_evento_ml, snapshot_ml, identificadores, versao_normalizador, processado_em
) VALUES (
    %(evento_webhook_id)s, %(conta_id)s, %(tipo)s, %(recurso_original)s, %(recurso_id)s,
    %(data_evento_ml)s, %(snapshot_ml)s, %(identificadores)s, 1, %(agora)s
);
"""

# ON CONFLICT DO UPDATE força status_interno='aberto' e visto_pelo_usuario=0
# incondicionalmente - um evento novo SEMPRE reabre o alerta, mesmo que
# estivesse 'resolvido' (regra de negócio obrigatória, ver Fase 3.2/3.3).
# detectado_em NUNCA é sobrescrito no UPDATE (fica com o valor do primeiro
# INSERT) - é a data de primeira detecção, não de última atualização.
UPSERT_ALERTA = """
INSERT INTO alertas_pos_venda (
    conta_id, tipo, recurso_id, titulo, resumo, texto, status_externo,
    status_interno, visto_pelo_usuario, data_evento_ml, detectado_em,
    atualizado_em, ultimo_evento_webhook_id, dados_auxiliares
) VALUES (
    %(conta_id)s, %(tipo)s, %(recurso_id)s, %(titulo)s, %(resumo)s, %(texto)s, %(status_externo)s,
    'aberto', 0, %(data_evento_ml)s, %(agora)s,
    %(agora)s, %(evento_webhook_id)s, %(dados_auxiliares)s
)
ON CONFLICT (conta_id, tipo, recurso_id) DO UPDATE SET
    titulo = excluded.titulo,
    resumo = excluded.resumo,
    texto = excluded.texto,
    status_externo = excluded.status_externo,
    status_interno = 'aberto',
    visto_pelo_usuario = 0,
    data_evento_ml = excluded.data_evento_ml,
    atualizado_em = excluded.atualizado_em,
    ultimo_evento_webhook_id = excluded.ultimo_evento_webhook_id,
    dados_auxiliares = excluded.dados_auxiliares;
"""

INSERT_NOTIFICACAO = """
INSERT INTO notificacoes_alerta (evento_processado_id, conta_id, tipo, recurso_id, status, criado_em)
VALUES (%(evento_webhook_id)s, %(conta_id)s, %(tipo)s, %(recurso_id)s, 'pendente', %(agora)s);
"""

MARCAR_WEBHOOK_PROCESSADO = """
UPDATE eventos_ml_webhook SET status_processamento = 'processado', processado_em = %(agora)s, conta_id = %(conta_id)s
WHERE id = %(id)s;
"""

MUDAR_STATUS_INTERNO = """
UPDATE alertas_pos_venda
SET status_interno = %(status_interno)s, atualizado_em = %(agora)s
WHERE conta_id = %(conta_id)s AND tipo = %(tipo)s AND recurso_id = %(recurso_id)s;
"""


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def registrar_evento_webhook(
    id: str,
    conta_id: str | None,
    topico: str,
    recurso: str,
    user_id_ml: str,
    application_id: str,
    actions: list | None,
    ml_attempts: int | None,
    sent_em: str | None,
    payload_bruto: dict,
) -> bool:
    """
    Grava o evento bruto do webhook. Idempotente: webhook duplicado (mesmo
    id) não gera nova linha - retorna False nesse caso, True se inseriu de
    verdade. Não altera alertas_pos_venda/notificacoes_alerta - isso só
    acontece no processamento (processar_evento_completo).

    Deliberadamente não garante a existência das tabelas aqui (diferente do
    padrão usado em outros módulos de database/*.py, ex: tokens_oauth.py/
    contas.py) - a Central de Alertas trata schema/DDL como operação de
    infraestrutura explícita e separada do caminho de runtime (que aqui
    inclui uma rota de webhook, exposta publicamente no Lovable - DDL
    implícito nesse caminho é um risco desnecessário). As 4 tabelas
    precisam existir de antemão, criadas deliberadamente numa etapa própria
    de setup (função em database/esquema.py), antes de qualquer uso real
    deste módulo.
    """
    conexao = obter_conexao()
    try:
        resultado = conexao.execute(INSERT_EVENTO_WEBHOOK, {
            "id": id,
            "conta_id": conta_id,
            "topico": topico,
            "recurso": recurso,
            "user_id_ml": user_id_ml,
            "application_id": application_id,
            "actions": json.dumps(actions) if actions is not None else None,
            "ml_attempts": ml_attempts,
            "sent_em": sent_em,
            "payload_bruto": json.dumps(payload_bruto),
        })
        conexao.commit()
        return resultado.fetchone() is not None
    finally:
        conexao.close()


def reivindicar_eventos_pendentes(limite: int = 10) -> list[dict]:
    """
    Claim atômico (FOR UPDATE SKIP LOCKED) de eventos elegíveis pra
    processar: pendentes, presos em 'processando' há mais de
    TIMEOUT_PROCESSANDO_MINUTOS (worker anterior pode ter morrido), ou em
    'erro' com tentativas ainda abaixo do limite. Marca como 'processando'
    antes de retornar - dois workers concorrentes nunca pegam o mesmo evento
    (mesmo padrão de fila já usado no desenho da Fase 2.1).
    """
    conexao = obter_conexao()
    try:
        agora = datetime.now()
        # Limite de timeout calculado em Python (não "now() - interval" no
        # SQL) pra manter a query simples de testar com mocks.
        limite_timeout = (agora - timedelta(minutes=TIMEOUT_PROCESSANDO_MINUTOS)).isoformat(timespec="seconds")
        linhas = conexao.execute(CLAIM_EVENTOS_PENDENTES, {
            "agora": _agora(),
            "limite_timeout": limite_timeout,
            "max_tentativas": MAX_TENTATIVAS_PROCESSAMENTO_EVENTO,
            "limite": limite,
        }).fetchall()
        conexao.commit()
        return linhas
    finally:
        conexao.close()


def marcar_erro(evento_webhook_id: str, mensagem: str) -> None:
    """Registra falha de processamento (fora de qualquer transação maior - sempre deve conseguir gravar, mesmo quando o que falhou foi a própria transação de processamento)."""
    conexao = obter_conexao()
    try:
        conexao.execute(MARCAR_ERRO_WEBHOOK, {"id": evento_webhook_id, "mensagem": mensagem[:2000]})
        conexao.commit()
    finally:
        conexao.close()


def processar_evento_completo(
    evento_webhook_id: str,
    conta_id: str,
    tipo: str,
    recurso_original: str,
    recurso_id: str,
    data_evento_ml: str | None,
    snapshot_ml: dict,
    identificadores: dict | None,
    titulo: str | None,
    resumo: str | None,
    texto: str | None,
    status_externo: str | None,
    dados_auxiliares: dict | None,
) -> None:
    """
    Transação única (Fase 3.2/3.3, seção "transação final"): insere o
    evento processado (histórico, nunca sobrescrito), faz UPSERT do alerta
    (sempre reabre, mesmo se estava resolvido), cria a notificação
    'pendente' e marca o evento bruto como 'processado' - tudo ou nada.
    Uma exceção aqui, antes do commit, deixa a conexão sem commit; close()
    no finally descarta a transação (ROLLBACK implícito do psycopg2) - o
    evento bruto permanece elegível pra retry via reivindicar_eventos_pendentes.
    """
    agora = _agora()
    conexao = obter_conexao()
    try:
        conexao.execute(INSERT_EVENTO_PROCESSADO, {
            "evento_webhook_id": evento_webhook_id,
            "conta_id": conta_id,
            "tipo": tipo,
            "recurso_original": recurso_original,
            "recurso_id": recurso_id,
            "data_evento_ml": data_evento_ml,
            "snapshot_ml": json.dumps(snapshot_ml),
            "identificadores": json.dumps(identificadores) if identificadores is not None else None,
            "agora": agora,
        })
        conexao.execute(UPSERT_ALERTA, {
            "conta_id": conta_id,
            "tipo": tipo,
            "recurso_id": recurso_id,
            "titulo": titulo,
            "resumo": resumo,
            "texto": texto,
            "status_externo": status_externo,
            "data_evento_ml": data_evento_ml,
            "agora": agora,
            "evento_webhook_id": evento_webhook_id,
            "dados_auxiliares": json.dumps(dados_auxiliares) if dados_auxiliares is not None else None,
        })
        conexao.execute(INSERT_NOTIFICACAO, {
            "evento_webhook_id": evento_webhook_id,
            "conta_id": conta_id,
            "tipo": tipo,
            "recurso_id": recurso_id,
            "agora": agora,
        })
        conexao.execute(MARCAR_WEBHOOK_PROCESSADO, {"id": evento_webhook_id, "agora": agora, "conta_id": conta_id})
        conexao.commit()
    finally:
        conexao.close()


def mudar_status_interno(conta_id: str, tipo: str, recurso_id: str, status_interno: str) -> None:
    """
    Caminho do USUÁRIO (mudança manual de atendimento) - toca só
    status_interno + atualizado_em. NUNCA cria/altera notificacoes_alerta,
    nunca dispara Broadcast, nunca chama o Mercado Livre (ver Fase 3.2
    addendum). Validação do valor permitido fica pro CHECK constraint do
    banco (mesmos 3 valores já usados em toda a stack).
    """
    conexao = obter_conexao()
    try:
        conexao.execute(MUDAR_STATUS_INTERNO, {
            "conta_id": conta_id,
            "tipo": tipo,
            "recurso_id": recurso_id,
            "status_interno": status_interno,
            "agora": _agora(),
        })
        conexao.commit()
    finally:
        conexao.close()
