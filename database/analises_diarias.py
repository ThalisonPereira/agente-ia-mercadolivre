"""
database/analises_diarias.py

Grava e consulta as análises narrativas diárias geradas pela IA
(agents/analista_ia.py) no banco de dados - além de reports/*.md e da aba
"Análise IA" do Sheets, pra que o chat hospedado no Streamlit Cloud também
consiga responder "qual a análise de hoje?" sem depender de arquivo local.
"""

from datetime import datetime

from database.conexao_turso import obter_conexao
from database.esquema import criar_tabelas

UPSERT_ANALISE = """
INSERT INTO analises_diarias (data, texto, gerado_em)
VALUES (:data, :texto, :gerado_em)
ON CONFLICT(data) DO UPDATE SET
    texto = excluded.texto,
    gerado_em = excluded.gerado_em;
"""

QUERY_ULTIMA_ANALISE = """
SELECT data, texto, gerado_em
FROM analises_diarias
ORDER BY data DESC
LIMIT 1
"""


def salvar_analise(data: str, texto: str) -> None:
    """Grava (ou atualiza) a análise narrativa do dia informado."""
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


def obter_ultima_analise() -> dict | None:
    """Retorna a análise mais recente já gravada, ou None se nenhuma existir."""
    conexao = obter_conexao()
    try:
        linha = conexao.execute(QUERY_ULTIMA_ANALISE).fetchone()
    finally:
        conexao.close()

    if linha is None:
        return None
    return {"data": linha["data"], "texto": linha["texto"], "gerado_em": linha["gerado_em"]}
