"""
Suite de testes RECONSTRUÍDA da Central de Alertas (2026-09-26).

IMPORTANTE - proveniência: esta suite foi recriada do zero, lendo o código
ATUAL de database/eventos_alertas.py, database/normalizador_alertas.py e
main.py::_processar_eventos_alertas_pendentes nesta sessão - não foi copiada
de um arquivo anterior (a suite de ontem existia só no scratchpad da sessão
passada, que é efêmero, e não está mais disponível). Onde a lembrança desta
conversa de ontem influenciou o desenho de um caso de teste, isso está
anotado explicitamente no comentário do teste.

Diferenças estruturais deliberadas em relação à suite histórica (documentadas
por pedido explícito do usuário):
  - Reorganizada por CATEGORIA DE COMPORTAMENTO (idempotência, reabertura,
    conta_id, transação, falhas, isolamento, normalizador) em vez de por
    letra A-M do documento da Fase 3.3 - mais fácil de mapear cada teste ao
    requisito de negócio que ele prova.
  - Teste dedicado novo: "conta_id persistido no sucesso" (cobre o bug
    encontrado e corrigido na revisão de ontem - não existia antes da
    correção, então não fazia sentido existir na suite original nesse
    formato).
  - Mantido o mesmo mecanismo de guarda dupla contra banco real (psycopg2.connect
    bloqueado + config Supabase falsa) - isso não é "lembrança", é releitura
    direta do padrão já presente no próprio projeto (mesmo texto de erro).

Zero chamada real a Supabase/Postgres/Mercado Livre. Projeto ainda não usa
pytest (sem essa dependência em requirements.txt) - roda como script direto,
mesmo padrão de todo teste anterior desta sessão:
    ./venv/Scripts/python.exe tests/teste_central_alertas.py
"""
import sys
from contextlib import contextmanager, ExitStack
from pathlib import Path
from unittest import mock

# Raiz do projeto = pasta pai de tests/ - relativo ao arquivo, não a um
# caminho de máquina fixo (diferente da versão de scratchpad, que rodava de
# um diretório temporário e precisava do caminho absoluto).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2  # noqa: E402
import config.settings as settings_mod  # noqa: E402
import database.esquema as esquema  # noqa: E402
import database.eventos_alertas as ea  # noqa: E402
import database.normalizador_alertas as norm  # noqa: E402
import main as main_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Isolamento do banco - camada 1 (rede de segurança global) + camada 2
# (fake por teste, com asserção de conteúdo)
# ---------------------------------------------------------------------------

def _psycopg2_connect_bloqueado(*args, **kwargs):
    raise RuntimeError(
        "BLOQUEIO DE SEGURANCA: um teste da Central de Alertas tentou abrir uma "
        "conexao REAL via psycopg2.connect(). Falta mockar obter_conexao em algum "
        "modulo. Corrija o teste, NAO remova esta guarda."
    )


@contextmanager
def _guarda_global_sem_producao():
    """Torna fisicamente impossível qualquer teste alcançar o Postgres real, mesmo se algum obter_conexao() novo for esquecido de mockar."""
    with ExitStack() as pilha:
        pilha.enter_context(mock.patch.object(psycopg2, "connect", side_effect=_psycopg2_connect_bloqueado))
        pilha.enter_context(mock.patch.object(
            settings_mod, "carregar_configuracao_supabase",
            return_value=settings_mod.SupabaseConfig(database_url="postgresql://BLOQUEADO-NAO-USAR/teste"),
        ))
        yield


class ConexaoFake:
    """Simula ConexaoSupabase (execute/commit/close) sem tocar rede/banco. Casa resultado por SUBSTRING do SQL, não por posição."""

    def __init__(self, resultado_por_sql=None, explodir_no_sql=None):
        self.chamadas: list[tuple[str, dict]] = []
        self.commit_chamado = False
        self.close_chamado = False
        self._resultado_por_sql = resultado_por_sql or {}
        self._explodir_no_sql = explodir_no_sql

    def _resultado_para(self, sql):
        for trecho, valor in self._resultado_por_sql.items():
            if trecho in sql:
                return valor
        return None

    def execute(self, sql, params=None):
        self.chamadas.append((sql, params or {}))
        if self._explodir_no_sql is not None and self._explodir_no_sql in sql:
            raise RuntimeError("falha simulada")
        valor = self._resultado_para(sql)
        resultado = mock.Mock()
        if isinstance(valor, list):
            resultado.fetchone.return_value = valor[0] if valor else None
            resultado.fetchall.return_value = valor
        else:
            resultado.fetchone.return_value = valor
            resultado.fetchall.return_value = [valor] if valor is not None else []
        return resultado

    def commit(self):
        self.commit_chamado = True

    def close(self):
        self.close_chamado = True


@contextmanager
def _conexao_fake_em(*modulos, fake: ConexaoFake):
    """Mocka obter_conexao em todos os módulos passados simultaneamente - evita o bug do incidente (mockar só 1 referência)."""
    with ExitStack() as pilha:
        for modulo in modulos:
            pilha.enter_context(mock.patch.object(modulo, "obter_conexao", return_value=fake))
        yield fake


# ---------------------------------------------------------------------------
# 1. ISOLAMENTO DO BANCO
# ---------------------------------------------------------------------------

def teste_guarda_global_bloqueia_conexao_real():
    from database.conexao_supabase import obter_conexao
    try:
        obter_conexao()
        raise AssertionError("obter_conexao() real deveria ter sido bloqueada")
    except RuntimeError as erro:
        assert "BLOQUEIO DE SEGURANCA" in str(erro)
    print("[isolamento] guarda global bloqueia psycopg2.connect real: OK")


def teste_sem_ddl_no_runtime_alertas():
    """Confirma que a correção de ontem (DDL fora do runtime) continua valendo hoje."""
    import inspect
    codigo = inspect.getsource(ea)
    assert "criar_tabelas" not in codigo
    for termo in ("CREATE TABLE", "ALTER TABLE", "DROP TABLE", "CREATE INDEX", "CREATE POLICY"):
        assert termo not in codigo.upper(), f"eventos_alertas.py não deve conter DDL ('{termo}')"
    print("[isolamento] eventos_alertas.py sem DDL/criar_tabelas no runtime: OK")


# ---------------------------------------------------------------------------
# 2. IDEMPOTÊNCIA
# ---------------------------------------------------------------------------

def teste_webhook_duplicado_nao_duplica():
    fake1 = ConexaoFake(resultado_por_sql={"INSERT INTO eventos_ml_webhook": {"id": "evt-dup"}})
    with _conexao_fake_em(ea, fake=fake1):
        primeiro = ea.registrar_evento_webhook(
            id="evt-dup", conta_id=None, topico="questions", recurso="/questions/9",
            user_id_ml="123", application_id="app1", actions=None, ml_attempts=None,
            sent_em=None, payload_bruto={"_id": "evt-dup"},
        )
    fake2 = ConexaoFake()  # sem override -> fetchone() None, simula ON CONFLICT DO NOTHING
    with _conexao_fake_em(ea, fake=fake2):
        segundo = ea.registrar_evento_webhook(
            id="evt-dup", conta_id=None, topico="questions", recurso="/questions/9",
            user_id_ml="123", application_id="app1", actions=None, ml_attempts=None,
            sent_em=None, payload_bruto={"_id": "evt-dup"},
        )
    assert primeiro is True and segundo is False
    assert "ON CONFLICT (id) DO NOTHING" in ea.INSERT_EVENTO_WEBHOOK
    assert len(fake1.chamadas) == 1, "não deve haver nenhum statement de DDL, só o INSERT de negócio"
    print("[idempotência] webhook duplicado (mesmo id) não gera nova linha: OK")


def teste_dois_eventos_mesmo_recurso_geram_duas_notificacoes():
    fake = ConexaoFake()
    with _conexao_fake_em(ea, fake=fake):
        for evt_id in ("evt-A", "evt-B"):
            ea.processar_evento_completo(
                evento_webhook_id=evt_id, conta_id="hc", tipo="pergunta",
                recurso_original="/questions/1", recurso_id="1", data_evento_ml=None,
                snapshot_ml={}, identificadores=None, titulo=None, resumo=None,
                texto=None, status_externo=None, dados_auxiliares=None,
            )
    notificacoes = [c for c in fake.chamadas if "INSERT INTO notificacoes_alerta" in c[0]]
    ids = {c[1]["evento_webhook_id"] for c in notificacoes}
    assert ids == {"evt-A", "evt-B"}, ids
    print("[idempotência] 2 eventos legítimos do mesmo recurso -> 2 notificações distintas: OK")


def teste_claim_usa_skip_locked_e_limite_de_tentativas():
    assert "FOR UPDATE SKIP LOCKED" in ea.CLAIM_EVENTOS_PENDENTES
    assert ea.MAX_TENTATIVAS_PROCESSAMENTO_EVENTO == 5
    fake = ConexaoFake()
    with _conexao_fake_em(ea, fake=fake):
        ea.reivindicar_eventos_pendentes(limite=10)
    _, params = fake.chamadas[0]
    assert params["max_tentativas"] == 5
    print("[idempotência/concorrência] claim usa FOR UPDATE SKIP LOCKED + limite=5 passado como parâmetro real (prova estrutural, não teste de concorrência com 2 processos de verdade): OK")


def teste_timeout_de_processando_calculado_certo():
    from datetime import datetime, timedelta
    fake = ConexaoFake()
    antes = datetime.now()
    with _conexao_fake_em(ea, fake=fake):
        ea.reivindicar_eventos_pendentes(limite=5)
    _, params = fake.chamadas[0]
    limite_timeout = datetime.fromisoformat(params["limite_timeout"])
    diferenca = antes - limite_timeout
    assert timedelta(minutes=9) < diferenca < timedelta(minutes=11), diferenca
    print("[idempotência/retry] timeout de 'processando' (10min) calculado e passado ao claim: OK")


# ---------------------------------------------------------------------------
# 3. REABERTURA DE ALERTAS
# ---------------------------------------------------------------------------

def teste_reabertura_incondicional_estrutural():
    """
    O UPSERT hardcoda status_interno='aberto' e visto_pelo_usuario=0 no
    DO UPDATE (não usa excluded.*, não depende de nenhum parâmetro vindo do
    status anterior) - portanto reabrir a partir de aberto/em_andamento/
    resolvido é garantido pela própria query, sem exceção possível.
    """
    assert "status_interno = 'aberto'" in ea.UPSERT_ALERTA
    assert "visto_pelo_usuario = 0" in ea.UPSERT_ALERTA
    assert "excluded.status_interno" not in ea.UPSERT_ALERTA
    assert "excluded.visto_pelo_usuario" not in ea.UPSERT_ALERTA
    print("[reabertura] UPSERT força aberto/0 incondicionalmente, sem exceção pra nenhum status anterior: OK")


def teste_detectado_em_nunca_sobrescrito():
    """detectado_em só aparece no INSERT (VALUES), nunca no DO UPDATE SET - preserva a data da primeira detecção."""
    upsert_sem_values = ea.UPSERT_ALERTA.split("DO UPDATE SET")[1]
    assert "detectado_em" not in upsert_sem_values
    print("[reabertura] detectado_em nunca é sobrescrito num evento novo pro mesmo recurso: OK")


# ---------------------------------------------------------------------------
# 4. PERSISTÊNCIA DE conta_id
# ---------------------------------------------------------------------------

def teste_conta_id_persistido_no_sucesso():
    """
    Cobre o bug encontrado e corrigido na revisão de ontem: o UPDATE final
    de eventos_ml_webhook precisa gravar o conta_id resolvido, não só o
    status. Este teste não existia antes da correção.
    """
    fake = ConexaoFake()
    with _conexao_fake_em(ea, fake=fake):
        ea.processar_evento_completo(
            evento_webhook_id="evt-conta", conta_id="wc", tipo="mensagem",
            recurso_original="/messages/5", recurso_id="5", data_evento_ml=None,
            snapshot_ml={}, identificadores=None, titulo=None, resumo=None,
            texto=None, status_externo=None, dados_auxiliares=None,
        )
    update_webhook = [c for c in fake.chamadas if "UPDATE eventos_ml_webhook" in c[0]]
    assert len(update_webhook) == 1
    assert update_webhook[0][1].get("conta_id") == "wc", "conta_id deve ser gravado no UPDATE final de sucesso"
    assert "conta_id = %(conta_id)s" in ea.MARCAR_WEBHOOK_PROCESSADO
    print("[conta_id] conta_id resolvido é gravado de volta em eventos_ml_webhook no sucesso: OK")


def teste_mapa_application_id_conta_ignora_conta_mal_configurada():
    """obter_mapa_application_id_conta não deve quebrar se 1 conta tiver config ausente/errada."""
    import database.contas as contas_mod

    contas_fake = [
        {"conta_id": "hc", "canal": "mercado_livre", "nome": "HC"},
        {"conta_id": "quebrada", "canal": "mercado_livre", "nome": "Quebrada"},
    ]

    def config_fake(conta_id):
        if conta_id == "quebrada":
            raise RuntimeError("config ausente")
        cfg = mock.Mock()
        cfg.client_id = "client-hc"
        return cfg

    with ExitStack() as pilha:
        pilha.enter_context(mock.patch.object(contas_mod, "obter_contas_ativas", return_value=contas_fake))
        pilha.enter_context(mock.patch.object(contas_mod, "carregar_configuracao_ml", side_effect=config_fake))
        mapa = contas_mod.obter_mapa_application_id_conta()

    assert mapa == {"client-hc": "hc"}, mapa
    print("[conta_id] resolução application_id->conta_id ignora conta com config quebrada, sem derrubar as demais: OK")


# ---------------------------------------------------------------------------
# 5. TRANSAÇÃO (tudo ou nada)
# ---------------------------------------------------------------------------

def teste_transacao_completa_grava_as_4_operacoes():
    fake = ConexaoFake()
    with _conexao_fake_em(ea, fake=fake):
        ea.processar_evento_completo(
            evento_webhook_id="evt-tx", conta_id="hc", tipo="pergunta",
            recurso_original="/questions/1", recurso_id="1", data_evento_ml=None,
            snapshot_ml={"text": "oi"}, identificadores=None, titulo=None,
            resumo="Pergunta", texto="oi", status_externo=None, dados_auxiliares=None,
        )
    assert len(fake.chamadas) == 4
    assert "eventos_ml_processados" in fake.chamadas[0][0]
    assert "alertas_pos_venda" in fake.chamadas[1][0]
    assert "notificacoes_alerta" in fake.chamadas[2][0]
    assert "eventos_ml_webhook" in fake.chamadas[3][0]
    assert fake.commit_chamado and fake.close_chamado
    print("[transação] evento novo grava processado+alerta+notificação+webhook, nesta ordem, com 1 commit: OK")


def teste_rollback_sem_estado_parcial():
    fake = ConexaoFake(explodir_no_sql="INSERT INTO notificacoes_alerta")
    with _conexao_fake_em(ea, fake=fake):
        try:
            ea.processar_evento_completo(
                evento_webhook_id="evt-fail", conta_id="hc", tipo="pergunta",
                recurso_original="/questions/1", recurso_id="1", data_evento_ml=None,
                snapshot_ml={}, identificadores=None, titulo=None, resumo=None,
                texto=None, status_externo=None, dados_auxiliares=None,
            )
            raise AssertionError("deveria ter propagado a exceção simulada")
        except RuntimeError as erro:
            assert str(erro) == "falha simulada"
    assert fake.commit_chamado is False, "commit nunca deve rodar se uma etapa falhou"
    assert fake.close_chamado is True, "close() sempre roda (finally) - descarta a transação (rollback implícito do psycopg2)"
    print("[transação] falha no meio do processamento não deixa estado parcial (sem commit): OK")


def teste_broadcast_nao_faz_parte_do_processamento():
    import inspect
    codigo = inspect.getsource(ea.processar_evento_completo)
    for termo in ("broadcast", "Broadcast", "realtime", "Realtime", "supabaseAdmin"):
        assert termo not in codigo
    print("[transação] processar_evento_completo nunca publica Broadcast (só cria notificação 'pendente'; publicação é do backend Lovable): OK")


# ---------------------------------------------------------------------------
# 6. TRATAMENTO DE FALHAS
# ---------------------------------------------------------------------------

def teste_marcar_erro_incrementa_tentativas():
    fake = ConexaoFake()
    with _conexao_fake_em(ea, fake=fake):
        ea.marcar_erro("evt-erro", "timeout ao chamar o Mercado Livre")
    assert "tentativas_processamento = tentativas_processamento + 1" in ea.MARCAR_ERRO_WEBHOOK
    assert fake.chamadas[0][1]["id"] == "evt-erro"
    assert fake.chamadas[0][1]["mensagem"] == "timeout ao chamar o Mercado Livre"
    print("[falhas] marcar_erro incrementa tentativas_processamento e grava a mensagem: OK")


def teste_falha_no_get_ml_isola_o_evento_sem_alerta_parcial():
    evento_fake = {"id": "evt-J", "application_id": "app_hc", "topico": "questions", "recurso": "/questions/1"}
    with ExitStack() as pilha:
        pilha.enter_context(mock.patch.object(main_mod, "reivindicar_eventos_pendentes", return_value=[evento_fake]))
        pilha.enter_context(mock.patch.object(main_mod, "obter_mapa_application_id_conta", return_value={"app_hc": "hc"}))
        canal_mock = mock.Mock()
        canal_mock.obter_recurso.side_effect = RuntimeError("timeout ML")
        pilha.enter_context(mock.patch.object(main_mod, "MercadoLivreCanal", return_value=canal_mock))
        processar_mock = pilha.enter_context(mock.patch.object(main_mod, "processar_evento_completo"))
        marcar_erro_mock = pilha.enter_context(mock.patch.object(main_mod, "marcar_erro_evento_alerta"))

        main_mod._processar_eventos_alertas_pendentes(limite=10)

    processar_mock.assert_not_called()
    marcar_erro_mock.assert_called_once()
    assert marcar_erro_mock.call_args[0][0] == "evt-J"
    print("[falhas] falha no GET do Mercado Livre nunca chama processar_evento_completo, só marca erro: OK")


def teste_conta_nao_resolvida_marca_erro_sem_travar_lote():
    """application_id sem correspondência em nenhuma conta ativa - deve isolar o evento, não travar o lote."""
    evento_sem_conta = {"id": "evt-sem-conta", "application_id": "app_desconhecido", "topico": "questions", "recurso": "/questions/1"}
    evento_ok = {"id": "evt-ok", "application_id": "app_hc", "topico": "questions", "recurso": "/questions/2"}
    with ExitStack() as pilha:
        pilha.enter_context(mock.patch.object(main_mod, "reivindicar_eventos_pendentes", return_value=[evento_sem_conta, evento_ok]))
        pilha.enter_context(mock.patch.object(main_mod, "obter_mapa_application_id_conta", return_value={"app_hc": "hc"}))
        canal_mock = mock.Mock()
        canal_mock.obter_recurso.return_value = {"text": "oi"}
        pilha.enter_context(mock.patch.object(main_mod, "MercadoLivreCanal", return_value=canal_mock))
        processar_mock = pilha.enter_context(mock.patch.object(main_mod, "processar_evento_completo"))
        marcar_erro_mock = pilha.enter_context(mock.patch.object(main_mod, "marcar_erro_evento_alerta"))

        main_mod._processar_eventos_alertas_pendentes(limite=10)

    # evento sem conta -> erro isolado; evento ok -> processado normalmente
    assert marcar_erro_mock.call_args_list[0][0][0] == "evt-sem-conta"
    assert processar_mock.call_count == 1
    assert processar_mock.call_args.kwargs["evento_webhook_id"] == "evt-ok"
    print("[falhas] application_id sem conta correspondente isola só aquele evento, resto do lote segue: OK")


# ---------------------------------------------------------------------------
# 7. MUDANÇA MANUAL DE STATUS (isolada de notificação)
# ---------------------------------------------------------------------------

def teste_mudar_status_interno_nao_toca_notificacao():
    fake = ConexaoFake()
    with _conexao_fake_em(ea, fake=fake):
        ea.mudar_status_interno("hc", "pergunta", "1", "resolvido")
    assert len(fake.chamadas) == 1
    assert "alertas_pos_venda" in fake.chamadas[0][0]
    assert "notificacoes_alerta" not in fake.chamadas[0][0]
    print("[status manual] mudar_status_interno só toca alertas_pos_venda, nunca notificacoes_alerta: OK")


# ---------------------------------------------------------------------------
# 8. NORMALIZADOR
# ---------------------------------------------------------------------------

def teste_normalizador_recurso_id_extraido_do_path():
    dados = norm.normalizar("pergunta", "/questions/998877", {"text": "quanto custa?", "item_id": "MLB1"})
    assert dados["recurso_id"] == "998877"
    assert dados["texto"] == "quanto custa?"
    assert dados["identificadores"] == {"item_id": "MLB1"}
    print("[normalizador] recurso_id sempre extraído do path do recurso, não do snapshot: OK")


def teste_normalizador_topico_fora_do_escopo_retorna_none():
    assert norm.resolver_tipo_normalizado("orders_feedback") is None
    assert norm.resolver_tipo_normalizado("shipments") is None
    print("[normalizador] tópico fora do escopo da V1 retorna None, não inventa tipo: OK")


def teste_normalizador_campo_ausente_nao_quebra():
    dados = norm.normalizar("reclamacao", "/post_purchase/1", {})
    assert dados["recurso_id"] == "1"
    assert dados["texto"] is None
    assert dados["identificadores"] is None
    print("[normalizador] snapshot sem os campos esperados não lança exceção (extração defensiva): OK")


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    with _guarda_global_sem_producao():
        testes = [
            teste_guarda_global_bloqueia_conexao_real,
            teste_sem_ddl_no_runtime_alertas,
            teste_webhook_duplicado_nao_duplica,
            teste_dois_eventos_mesmo_recurso_geram_duas_notificacoes,
            teste_claim_usa_skip_locked_e_limite_de_tentativas,
            teste_timeout_de_processando_calculado_certo,
            teste_reabertura_incondicional_estrutural,
            teste_detectado_em_nunca_sobrescrito,
            teste_conta_id_persistido_no_sucesso,
            teste_mapa_application_id_conta_ignora_conta_mal_configurada,
            teste_transacao_completa_grava_as_4_operacoes,
            teste_rollback_sem_estado_parcial,
            teste_broadcast_nao_faz_parte_do_processamento,
            teste_marcar_erro_incrementa_tentativas,
            teste_falha_no_get_ml_isola_o_evento_sem_alerta_parcial,
            teste_conta_nao_resolvida_marca_erro_sem_travar_lote,
            teste_mudar_status_interno_nao_toca_notificacao,
            teste_normalizador_recurso_id_extraido_do_path,
            teste_normalizador_topico_fora_do_escopo_retorna_none,
            teste_normalizador_campo_ausente_nao_quebra,
        ]
        falhas = 0
        for teste in testes:
            try:
                teste()
            except Exception as erro:
                falhas += 1
                print(f"FALHOU: {teste.__name__}: {erro}")
        print(f"\n{len(testes) - falhas}/{len(testes)} testes passaram.")
        if falhas:
            sys.exit(1)
