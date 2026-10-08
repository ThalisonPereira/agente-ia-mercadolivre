"""
database/contas.py

Cadastro de contas - uma credencial específica, num canal específico (ex:
"Mercado Livre - HC", "Shopee - Principal"). Toda coleta e consulta de
dados é feita por conta, pra suportar múltiplas contas do mesmo canal e
múltiplos canais (Mercado Livre, Shopee, Amazon...).
"""

from datetime import datetime

from config.settings import carregar_configuracao_ml
from database.conexao_supabase import obter_conexao
from database.esquema import criar_tabelas

UPSERT_CONTA = """
INSERT INTO contas (conta_id, canal, nome, ativo, criado_em)
VALUES (%(conta_id)s, %(canal)s, %(nome)s, %(ativo)s, %(criado_em)s)
ON CONFLICT(conta_id) DO UPDATE SET
    canal = excluded.canal,
    nome = excluded.nome,
    ativo = excluded.ativo;
"""


def cadastrar_conta(conta_id: str, canal: str, nome: str, ativo: bool = True) -> None:
    """Cria (ou atualiza) o cadastro de uma conta."""
    criar_tabelas()
    conexao = obter_conexao()
    try:
        conexao.execute(UPSERT_CONTA, {
            "conta_id": conta_id,
            "canal": canal,
            "nome": nome,
            "ativo": 1 if ativo else 0,
            "criado_em": datetime.now().isoformat(timespec="seconds"),
        })
        conexao.commit()
    finally:
        conexao.close()


def obter_contas_ativas(canal: str | None = None) -> list[dict]:
    """Retorna as contas ativas, opcionalmente filtradas por canal."""
    sql = "SELECT conta_id, canal, nome FROM contas WHERE ativo = 1"
    parametros = {}
    if canal:
        sql += " AND canal = %(canal)s"
        parametros["canal"] = canal

    conexao = obter_conexao()
    try:
        linhas = conexao.execute(sql, parametros).fetchall()
    finally:
        conexao.close()

    return [{"conta_id": l["conta_id"], "canal": l["canal"], "nome": l["nome"]} for l in linhas]


def obter_mapa_application_id_conta() -> dict[str, str]:
    """
    Mapa {application_id (= client_id do app OAuth) -> conta_id}, pra
    resolver de qual conta é um evento de webhook do Mercado Livre (Fase 3.3
    - Central de Alertas). Cada conta ML ativa tem seu próprio app cadastrado
    (client_id/client_secret diferentes por conta, confirmado desde o
    bootstrap do projeto) - application_id no payload do webhook é
    justamente esse client_id, então não precisa de nenhuma tabela nova de
    vínculo. Não usa ML user_id (também disponível em tokens_oauth.dados_json)
    porque application_id é a fonte mais direta e não exige desserializar o
    token de cada conta pra montar o mapa.

    Conta ativa sem ML_<CONTA>_CLIENT_ID configurado (erro de config) faz
    essa conta ficar de fora do mapa silenciosamente - fica evidente como
    'conta não resolvida' no processamento do evento, não como exceção
    aqui (evitar que uma conta mal configurada derrube a resolução de
    todas as outras).
    """
    mapa: dict[str, str] = {}
    for conta in obter_contas_ativas(canal="mercado_livre"):
        try:
            config = carregar_configuracao_ml(conta["conta_id"])
        except Exception:  # noqa: BLE001 - config ausente/errada dessa conta não deve quebrar as demais
            continue
        mapa[config.client_id] = conta["conta_id"]
    return mapa
