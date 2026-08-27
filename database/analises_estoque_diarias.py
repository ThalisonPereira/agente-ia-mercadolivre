"""
database/analises_estoque_diarias.py

Grava e consulta a análise narrativa diária de estoque gerada pela IA
(agents/analista_estoque_ia.py) - espelha database/analises_ads_diarias.py,
mas SEM conta_id: estoque é compartilhado pelas 3 contas (mesmo depósito
físico no Bling), então é sempre uma análise única "geral" por dia.
"""

from datetime import datetime

from database.conexao_supabase import obter_conexao
from database.esquema import criar_tabelas

UPSERT_ANALISE = """
INSERT INTO analises_estoque_diarias (data, texto, gerado_em)
VALUES (%(data)s, %(texto)s, %(gerado_em)s)
ON CONFLICT(data) DO UPDATE SET
    texto = excluded.texto,
    gerado_em = excluded.gerado_em;
"""

QUERY_ULTIMA_ANALISE = """
SELECT data, texto, gerado_em
FROM analises_estoque_diarias
ORDER BY data DESC
LIMIT 1
"""


def salvar_analise_estoque(data: str, texto: str) -> None:
    """Grava (ou atualiza) a análise narrativa de estoque do dia informado."""
    criar_tabelas()

    conexao = obter_conexao()
    try:
        conexao.execute(UPSERT_ANALISE, {
            "data": data,
            "texto": texto,
            "gerado_em": datetime.now().isoformat(timespec="seconds"),
        })
        conexao.commit()
    finally:
        conexao.close()


def obter_ultima_analise_estoque() -> dict | None:
    """Retorna a análise de estoque mais recente, ou None se nenhuma foi gerada ainda."""
    conexao = obter_conexao()
    try:
        linha = conexao.execute(QUERY_ULTIMA_ANALISE).fetchone()
    finally:
        conexao.close()

    if linha is None:
        return None
    return {"data": linha["data"], "texto": linha["texto"], "gerado_em": linha["gerado_em"]}
