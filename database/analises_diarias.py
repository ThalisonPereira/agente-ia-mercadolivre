"""
database/analises_diarias.py

Grava e consulta as análises narrativas diárias geradas pela IA
(agents/analista_ia.py) no banco de dados - além de reports/*.md e da aba
"Análise IA" do Sheets, pra que o chat hospedado no Streamlit Cloud também
consiga responder "qual a análise de hoje?" sem depender de arquivo local.

Cada análise pertence a uma conta (conta_id), ou usa o valor especial
'geral' pra uma análise combinando todas as contas.
"""

from datetime import datetime

from database.conexao_supabase import obter_conexao
from database.esquema import criar_tabelas

CONTA_GERAL = "geral"

UPSERT_ANALISE = """
INSERT INTO analises_diarias (conta_id, data, texto, gerado_em)
VALUES (%(conta_id)s, %(data)s, %(texto)s, %(gerado_em)s)
ON CONFLICT(conta_id, data) DO UPDATE SET
    texto = excluded.texto,
    gerado_em = excluded.gerado_em;
"""

QUERY_ULTIMA_ANALISE = """
SELECT conta_id, data, texto, gerado_em
FROM analises_diarias
WHERE conta_id = %(conta_id)s
ORDER BY data DESC
LIMIT 1
"""

QUERY_ULTIMA_ANALISE_QUALQUER_CONTA = """
SELECT conta_id, data, texto, gerado_em
FROM analises_diarias
ORDER BY data DESC, gerado_em DESC
LIMIT 1
"""

QUERY_ULTIMA_ANALISE_POR_CANAL = """
SELECT a.conta_id, a.data, a.texto, a.gerado_em
FROM analises_diarias a
JOIN contas c ON c.conta_id = a.conta_id
WHERE c.canal = %(canal)s
ORDER BY a.data DESC, a.gerado_em DESC
LIMIT 1
"""


def salvar_analise(data: str, texto: str, conta_id: str = CONTA_GERAL) -> None:
    """Grava (ou atualiza) a análise narrativa do dia informado, pra uma conta (ou 'geral')."""
    criar_tabelas()

    conexao = obter_conexao()
    try:
        conexao.execute(UPSERT_ANALISE, {
            "conta_id": conta_id,
            "data": data,
            "texto": texto,
            "gerado_em": datetime.now().isoformat(timespec="seconds"),
        })
        conexao.commit()
    finally:
        conexao.close()


def obter_ultima_analise(conta_id: str | None = None, canal: str | None = None) -> dict | None:
    """
    Retorna a análise mais recente já gravada. Se `conta_id` for informado,
    restringe a essa conta (ou 'geral'). Senão, se `canal` for informado,
    restringe à análise mais recente entre as contas desse canal (evita
    mostrar a narrativa de uma conta de outro canal quando o dashboard está
    filtrado por canal). Sem nenhum dos dois, pega a mais recente entre
    todas as contas.
    """
    conexao = obter_conexao()
    try:
        if conta_id:
            linha = conexao.execute(QUERY_ULTIMA_ANALISE, {"conta_id": conta_id}).fetchone()
        elif canal:
            linha = conexao.execute(QUERY_ULTIMA_ANALISE_POR_CANAL, {"canal": canal}).fetchone()
        else:
            linha = conexao.execute(QUERY_ULTIMA_ANALISE_QUALQUER_CONTA).fetchone()
    finally:
        conexao.close()

    if linha is None:
        return None
    return {
        "conta_id": linha["conta_id"],
        "data": linha["data"],
        "texto": linha["texto"],
        "gerado_em": linha["gerado_em"],
    }
