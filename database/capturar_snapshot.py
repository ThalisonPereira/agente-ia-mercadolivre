"""
database/capturar_snapshot.py

Registra o snapshot de hoje (visitas, vendas e receita por anúncio) no
histórico diário, e mantém a tabela 'anuncios' com o título/SKU/estoque/
status mais recente de cada item. Deve rodar uma vez por dia, por conta,
depois de coletar os dados na API do canal correspondente (Mercado
Livre, Shopee...).
"""

from datetime import date, datetime

from database.conexao_supabase import obter_conexao
from database.esquema import criar_tabelas

UPSERT_ANUNCIO = """
INSERT INTO anuncios (conta_id, item_id, titulo, sku, estoque_disponivel, status, grupo_estoque_id, atualizado_em)
VALUES (%(conta_id)s, %(item_id)s, %(titulo)s, %(sku)s, %(estoque_disponivel)s, %(status)s, %(grupo_estoque_id)s, %(atualizado_em)s)
ON CONFLICT(conta_id, item_id) DO UPDATE SET
    titulo = excluded.titulo,
    sku = excluded.sku,
    estoque_disponivel = excluded.estoque_disponivel,
    status = excluded.status,
    grupo_estoque_id = excluded.grupo_estoque_id,
    atualizado_em = excluded.atualizado_em;
"""

UPSERT_SNAPSHOT = """
INSERT INTO historico_anuncios_diario (
    conta_id, item_id, data_snapshot, visitas, vendas_quantidade, receita, capturado_em
)
VALUES (%(conta_id)s, %(item_id)s, %(data_snapshot)s, %(visitas)s, %(vendas_quantidade)s, %(receita)s, %(capturado_em)s)
ON CONFLICT(conta_id, item_id, data_snapshot) DO UPDATE SET
    visitas = excluded.visitas,
    vendas_quantidade = excluded.vendas_quantidade,
    receita = excluded.receita,
    capturado_em = excluded.capturado_em;
"""


def capturar_snapshot_diario(conta_id: str, dados_anuncios: list[dict], dia: date | None = None) -> None:
    """
    Grava o snapshot do dia informado (padrão: hoje) pra uma conta
    específica, a partir de uma lista de dicionários já coletados na API,
    cada um com as chaves: item_id, titulo, sku, visitas,
    vendas_quantidade, receita.

    O parâmetro 'dia' existe para permitir backfill de dias passados (ver
    comando 'backfill' em main.py) - na rotina diária normal, é omitido e
    o snapshot é gravado com a data de hoje.
    """
    criar_tabelas()

    data_snapshot = (dia or datetime.now().date()).isoformat()
    agora = datetime.now().isoformat(timespec="seconds")

    conexao = obter_conexao()
    try:
        # Manda tudo em poucas requisições em lote, em vez de uma requisição
        # HTTP por upsert (~380 chamadas sequenciais já esbarraram num
        # timeout de rede isolado na prática) - mais rápido e mais confiável.
        instrucoes = []
        for item in dados_anuncios:
            instrucoes.append((UPSERT_ANUNCIO, {
                "conta_id": conta_id,
                "item_id": item["item_id"],
                "titulo": item["titulo"],
                "sku": item.get("sku", ""),
                "estoque_disponivel": item.get("estoque_disponivel"),
                "status": item.get("status"),
                "grupo_estoque_id": item.get("grupo_estoque_id"),
                "atualizado_em": agora,
            }))
            instrucoes.append((UPSERT_SNAPSHOT, {
                "conta_id": conta_id,
                "item_id": item["item_id"],
                "data_snapshot": data_snapshot,
                "visitas": item["visitas"],
                "vendas_quantidade": item["vendas_quantidade"],
                "receita": item["receita"],
                "capturado_em": agora,
            }))
        conexao.executar_em_lote(instrucoes)
        conexao.commit()
        print(f"[conta: {conta_id}] Snapshot de {data_snapshot} registrado para {len(dados_anuncios)} anúncio(s).")
    finally:
        conexao.close()
