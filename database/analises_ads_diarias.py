"""
database/analises_ads_diarias.py

Grava e consulta as análises narrativas diárias de publicidade geradas
pela IA (agents/analista_ads_ia.py) - espelha database/analises_diarias.py
numa tabela separada (analises_ads_diarias), porque o conteúdo é bem
diferente (foco em ACOS/ROAS/orçamento de campanhas, não visitas/vendas
orgânicas).
"""

from datetime import datetime

from database.conexao_supabase import obter_conexao
from database.esquema import criar_tabelas

UPSERT_ANALISE = """
INSERT INTO analises_ads_diarias (conta_id, data, texto, gerado_em)
VALUES (%(conta_id)s, %(data)s, %(texto)s, %(gerado_em)s)
ON CONFLICT(conta_id, data) DO UPDATE SET
    texto = excluded.texto,
    gerado_em = excluded.gerado_em;
"""

QUERY_ULTIMA_ANALISE = """
SELECT conta_id, data, texto, gerado_em
FROM analises_ads_diarias
WHERE conta_id = %(conta_id)s
ORDER BY data DESC
LIMIT 1
"""

QUERY_ULTIMA_ANALISE_QUALQUER_CONTA = """
SELECT conta_id, data, texto, gerado_em
FROM analises_ads_diarias
ORDER BY data DESC, gerado_em DESC
LIMIT 1
"""

QUERY_ULTIMA_ANALISE_POR_CANAL = """
SELECT a.conta_id, a.data, a.texto, a.gerado_em
FROM analises_ads_diarias a
JOIN contas c ON c.conta_id = a.conta_id
WHERE c.canal = %(canal)s
ORDER BY a.data DESC, a.gerado_em DESC
LIMIT 1
"""


def salvar_analise_ads(data: str, texto: str, conta_id: str) -> None:
    """Grava (ou atualiza) a análise narrativa de publicidade do dia informado, pra uma conta."""
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


def obter_ultima_analise_ads(conta_id: str | None = None, canal: str | None = None) -> dict | None:
    """Mesmo comportamento de database/analises_diarias.py::obter_ultima_analise, pra publicidade."""
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
