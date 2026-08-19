"""
scripts/migrar_para_supabase.py

Script de uso único: copia todos os dados já coletados no Turso pro
Supabase (Postgres), que passa a ser a fonte de verdade a partir de
agora - mesmo espírito de scripts/migrar_para_turso.py, mas Turso -> Supabase
em vez de SQLite local -> Turso.

Roda uma vez (python -m scripts.migrar_para_supabase) e depois pode ser
descartado - não faz parte da operação diária do projeto. Não apaga nem
altera o Turso, que fica como caminho de rollback.

Reaproveita as instruções UPSERT_* já definidas em cada database/*.py
(agora apontando pro Supabase) - lê cada tabela do Turso, monta os
parâmetros a partir do nome das colunas (que já bate 1:1 com o nome dos
parâmetros nomeados de cada UPSERT) e grava em lote.
"""

import libsql_client

from config.settings import carregar_configuracao_turso
from database.conexao_supabase import obter_conexao as obter_conexao_supabase
from database.esquema import criar_tabelas

from database.contas import UPSERT_CONTA
from database.capturar_snapshot import UPSERT_ANUNCIO, UPSERT_SNAPSHOT
from database.analises_diarias import UPSERT_ANALISE as UPSERT_ANALISE_DIARIA
from database.tokens_oauth import UPSERT_TOKEN
from database.pedidos import UPSERT_PEDIDO
from database.custo_produtos import UPSERT_CUSTO
from database.extrato import UPSERT_ITEM_VENDA
from database.ads import UPSERT_CAMPANHA, UPSERT_ANUNCIO as UPSERT_ADS_ANUNCIO
from database.analises_ads_diarias import UPSERT_ANALISE as UPSERT_ANALISE_ADS

# (nome da tabela, SELECT * no Turso, instrução UPSERT correspondente no Supabase)
TABELAS = [
    ("contas", "SELECT conta_id, canal, nome, ativo, criado_em FROM contas", UPSERT_CONTA),
    ("anuncios", "SELECT conta_id, item_id, titulo, sku, atualizado_em FROM anuncios", UPSERT_ANUNCIO),
    (
        "historico_anuncios_diario",
        "SELECT conta_id, item_id, data_snapshot, visitas, vendas_quantidade, receita, capturado_em "
        "FROM historico_anuncios_diario",
        UPSERT_SNAPSHOT,
    ),
    ("analises_diarias", "SELECT conta_id, data, texto, gerado_em FROM analises_diarias", UPSERT_ANALISE_DIARIA),
    ("tokens_oauth", "SELECT conta_id, dados_json, atualizado_em FROM tokens_oauth", UPSERT_TOKEN),
    (
        "pedidos",
        "SELECT conta_id, pedido_id, data_pedido, status_envio, substatus_envio, logistic_type, valor_total, "
        "capturado_em FROM pedidos",
        UPSERT_PEDIDO,
    ),
    (
        "custo_produtos",
        "SELECT sku, produto_id_bling, nome, preco_custo, atualizado_em FROM custo_produtos",
        UPSERT_CUSTO,
    ),
    (
        "itens_venda",
        "SELECT conta_id, pedido_id, item_id, sku, titulo, data_venda, quantidade, preco_venda, comissao_ml, "
        "frete_vendedor, status, custo_unitario_capturado, capturado_em FROM itens_venda",
        UPSERT_ITEM_VENDA,
    ),
    (
        "ads_campanhas_diario",
        "SELECT conta_id, campaign_id, data, nome, status, strategy, budget, acos_target, roas_target, clicks, "
        "prints, cost, cpc, ctr, acos, cvr, roas, direct_amount, indirect_amount, total_amount, "
        "direct_units_quantity, indirect_units_quantity, units_quantity, capturado_em FROM ads_campanhas_diario",
        UPSERT_CAMPANHA,
    ),
    (
        "ads_anuncios_diario",
        "SELECT conta_id, item_id, campaign_id, data, titulo, status, clicks, prints, cost, cpc, acos, "
        "direct_amount, indirect_amount, total_amount, units_quantity, capturado_em FROM ads_anuncios_diario",
        UPSERT_ADS_ANUNCIO,
    ),
    ("analises_ads_diarias", "SELECT conta_id, data, texto, gerado_em FROM analises_ads_diarias", UPSERT_ANALISE_ADS),
]


def migrar() -> None:
    print("Criando tabelas no Supabase (se ainda não existirem)...")
    criar_tabelas()

    config = carregar_configuracao_turso()
    url = config.database_url.replace("libsql://", "https://", 1)
    cliente_turso = libsql_client.create_client_sync(url, auth_token=config.auth_token)

    conexao_supabase = obter_conexao_supabase()
    try:
        for nome_tabela, query_select, upsert_sql in TABELAS:
            resultado = cliente_turso.execute(query_select)
            colunas = resultado.columns
            linhas = resultado.rows

            instrucoes = [
                (upsert_sql, dict(zip(colunas, linha)))
                for linha in linhas
            ]
            conexao_supabase.executar_em_lote(instrucoes)
            conexao_supabase.commit()
            print(f"{nome_tabela}: {len(instrucoes)} linha(s) migrada(s).")
    finally:
        cliente_turso.close()
        conexao_supabase.close()

    print("\nConferindo contagens (Turso vs Supabase)...")
    tudo_bateu = True
    cliente_turso = libsql_client.create_client_sync(url, auth_token=config.auth_token)
    conexao_supabase = obter_conexao_supabase()
    try:
        for nome_tabela, query_select, _ in TABELAS:
            total_turso = len(cliente_turso.execute(query_select).rows)
            total_supabase = conexao_supabase.execute(f"SELECT COUNT(*) AS total FROM {nome_tabela}").fetchone()["total"]
            bateu = total_turso == total_supabase
            tudo_bateu = tudo_bateu and bateu
            marcador = "OK" if bateu else "DIVERGENTE"
            print(f"  {nome_tabela}: turso={total_turso} supabase={total_supabase} [{marcador}]")
    finally:
        cliente_turso.close()
        conexao_supabase.close()

    if tudo_bateu:
        print("\nMIGRAÇÃO CONFIRMADA COM SUCESSO.")
    else:
        print("\nATENÇÃO: as contagens não batem - revisar antes de considerar a migração concluída.")


if __name__ == "__main__":
    migrar()
