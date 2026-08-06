"""
scripts/migrar_para_turso.py

Script de uso único: copia todos os dados já coletados no SQLite local
(database/monitoramento.db) para o banco de dados hospedado (Turso), que
passa a ser a fonte de verdade a partir de agora.

Roda uma vez (python -m scripts.migrar_para_turso) e depois pode ser
descartado - não faz parte da operação diária do projeto. Não apaga o
SQLite local, que fica como backup.
"""

import libsql_client

from config.settings import carregar_configuracao_turso
from database.conexao import obter_conexao as obter_conexao_local
from database.conexao_turso import obter_conexao as obter_conexao_turso
from database.esquema import criar_tabelas
from database.capturar_snapshot import UPSERT_ANUNCIO, UPSERT_SNAPSHOT

QUERY_ANUNCIOS = "SELECT item_id, titulo, sku, atualizado_em FROM anuncios"
QUERY_HISTORICO = (
    "SELECT item_id, data_snapshot, visitas, vendas_quantidade, receita, capturado_em "
    "FROM historico_anuncios_diario"
)

TAMANHO_LOTE = 500  # instruções por chamada batch() - evita requisições HTTP individuais


def _enviar_em_lotes(cliente: "libsql_client.ClientSync", instrucoes: list) -> None:
    for i in range(0, len(instrucoes), TAMANHO_LOTE):
        lote = instrucoes[i:i + TAMANHO_LOTE]
        cliente.batch(lote)
        print(f"  Lote {i // TAMANHO_LOTE + 1}: {len(lote)} instrução(ões) enviada(s).")


def migrar() -> None:
    print("Criando tabelas no Turso (se ainda não existirem)...")
    criar_tabelas()

    conexao_local = obter_conexao_local()
    try:
        anuncios = conexao_local.execute(QUERY_ANUNCIOS).fetchall()
        historico = conexao_local.execute(QUERY_HISTORICO).fetchall()
    finally:
        conexao_local.close()

    print(f"Lido do SQLite local: {len(anuncios)} anúncio(s), {len(historico)} linha(s) de histórico.")

    config = carregar_configuracao_turso()
    url = config.database_url.replace("libsql://", "https://", 1)
    cliente = libsql_client.create_client_sync(url, auth_token=config.auth_token)

    try:
        instrucoes_anuncios = [
            libsql_client.Statement(UPSERT_ANUNCIO, {
                "item_id": linha["item_id"],
                "titulo": linha["titulo"],
                "sku": linha["sku"],
                "atualizado_em": linha["atualizado_em"],
            })
            for linha in anuncios
        ]
        print(f"Enviando {len(instrucoes_anuncios)} anúncio(s) em lotes de {TAMANHO_LOTE}...")
        _enviar_em_lotes(cliente, instrucoes_anuncios)

        instrucoes_historico = [
            libsql_client.Statement(UPSERT_SNAPSHOT, {
                "item_id": linha["item_id"],
                "data_snapshot": linha["data_snapshot"],
                "visitas": linha["visitas"],
                "vendas_quantidade": linha["vendas_quantidade"],
                "receita": linha["receita"],
                "capturado_em": linha["capturado_em"],
            })
            for linha in historico
        ]
        print(f"Enviando {len(instrucoes_historico)} linha(s) de histórico em lotes de {TAMANHO_LOTE}...")
        _enviar_em_lotes(cliente, instrucoes_historico)
    finally:
        cliente.close()

    print("Escrita no Turso concluída. Conferindo contagens...")

    conexao_turso = obter_conexao_turso()
    try:
        total_anuncios_turso = conexao_turso.execute("SELECT COUNT(*) AS total FROM anuncios").fetchone()["total"]
        total_historico_turso = conexao_turso.execute(
            "SELECT COUNT(*) AS total FROM historico_anuncios_diario"
        ).fetchone()["total"]
        datas_turso = {
            linha["data_snapshot"]
            for linha in conexao_turso.execute("SELECT DISTINCT data_snapshot FROM historico_anuncios_diario").fetchall()
        }
    finally:
        conexao_turso.close()

    conexao_local = obter_conexao_local()
    try:
        datas_local = {
            linha["data_snapshot"]
            for linha in conexao_local.execute("SELECT DISTINCT data_snapshot FROM historico_anuncios_diario").fetchall()
        }
    finally:
        conexao_local.close()

    print(f"anuncios: local={len(anuncios)} turso={total_anuncios_turso}")
    print(f"historico_anuncios_diario: local={len(historico)} turso={total_historico_turso}")
    print(f"datas distintas batem? {datas_local == datas_turso}")

    if len(anuncios) == total_anuncios_turso and len(historico) == total_historico_turso and datas_local == datas_turso:
        print("\nMIGRAÇÃO CONFIRMADA COM SUCESSO.")
    else:
        print("\nATENÇÃO: as contagens não batem - revisar antes de considerar a migração concluída.")


if __name__ == "__main__":
    migrar()
