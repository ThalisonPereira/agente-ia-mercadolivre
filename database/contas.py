"""
database/contas.py

Cadastro de contas - uma credencial específica, num canal específico (ex:
"Mercado Livre - HC", "Shopee - Principal"). Toda coleta e consulta de
dados é feita por conta, pra suportar múltiplas contas do mesmo canal e
múltiplos canais (Mercado Livre, Shopee, Amazon...).
"""

from datetime import datetime

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
