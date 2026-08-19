"""
database/tokens_oauth.py

Guarda e lê o token OAuth de cada conta como um blob JSON. Cada canal
(Mercado Livre, Shopee, Amazon...) tem um formato de token bem diferente
(access/refresh token simples vs. shop_id+partner_id vs. LWA+AWS), então não
tentamos normalizar isso em colunas fixas - cada adaptador de canal
(integrations/canais/*.py) sabe interpretar o próprio formato.

Substitui o arquivo local config/.ml_tokens.json que era usado antes - o
token precisa estar num lugar acessível tanto pela coleta local quanto por
uma futura automação rodando na nuvem (GitHub Actions), e o Mercado Livre
invalida o refresh_token antigo a cada renovação, então esse dado tem que
ficar persistido em algum lugar compartilhado, não só no disco local.
"""

import json
from datetime import datetime

from database.conexao_supabase import obter_conexao
from database.esquema import criar_tabelas

UPSERT_TOKEN = """
INSERT INTO tokens_oauth (conta_id, dados_json, atualizado_em)
VALUES (%(conta_id)s, %(dados_json)s, %(atualizado_em)s)
ON CONFLICT(conta_id) DO UPDATE SET
    dados_json = excluded.dados_json,
    atualizado_em = excluded.atualizado_em;
"""

QUERY_TOKEN = "SELECT dados_json FROM tokens_oauth WHERE conta_id = %(conta_id)s"


def salvar_token(conta_id: str, dados: dict) -> None:
    """Grava (ou atualiza) o token da conta informada."""
    criar_tabelas()
    conexao = obter_conexao()
    try:
        conexao.execute(UPSERT_TOKEN, {
            "conta_id": conta_id,
            "dados_json": json.dumps(dados),
            "atualizado_em": datetime.now().isoformat(timespec="seconds"),
        })
        conexao.commit()
    finally:
        conexao.close()


def obter_token(conta_id: str) -> dict | None:
    """Retorna o token salvo da conta informada, ou None se não existir."""
    conexao = obter_conexao()
    try:
        linha = conexao.execute(QUERY_TOKEN, {"conta_id": conta_id}).fetchone()
    finally:
        conexao.close()

    if linha is None:
        return None
    return json.loads(linha["dados_json"])
