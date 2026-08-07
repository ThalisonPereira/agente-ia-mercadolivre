"""
database/historico_completo.py

Utilitário usado pelo backfill para saber quais dias já foram coletados
(database/historico_completo.py::obter_datas_existentes) e evitar refazer
trabalho. A função obter_historico_completo() que existia aqui foi removida
- ela lia todo o histórico (todos os dias x todos os anúncios) pra publicar
numa aba "Histórico Completo" do Sheets e alimentar o chat antigo, que
mandava esse histórico inteiro como contexto em cada pergunta (caro e não
escala). O chat atual (agents/assistente_ia.py) consulta o banco de dados
direto, com ferramentas que buscam só o pedaço de dado necessário.
"""

from database.conexao_turso import obter_conexao


def obter_datas_existentes(conta_id: str) -> set[str]:
    """Retorna o conjunto de datas (YYYY-MM-DD) que já têm snapshot registrado pra essa conta."""
    conexao = obter_conexao()
    try:
        linhas = conexao.execute(
            "SELECT DISTINCT data_snapshot FROM historico_anuncios_diario WHERE conta_id = :conta_id",
            {"conta_id": conta_id},
        ).fetchall()
    finally:
        conexao.close()
    return {linha["data_snapshot"] for linha in linhas}
