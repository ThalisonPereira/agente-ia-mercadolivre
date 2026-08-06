"""
database/capturar_snapshot.py

Registra o snapshot de hoje (visitas, vendas e receita por anúncio) no
histórico diário, e mantém a tabela 'anuncios' com o título/SKU mais
recente de cada item. Deve rodar uma vez por dia, depois de coletar os
dados na API do Mercado Livre.
"""

from datetime import date, datetime

from database.conexao import obter_conexao
from database.esquema import criar_tabelas

UPSERT_ANUNCIO = """
INSERT INTO anuncios (item_id, titulo, sku, atualizado_em)
VALUES (:item_id, :titulo, :sku, :atualizado_em)
ON CONFLICT(item_id) DO UPDATE SET
    titulo = excluded.titulo,
    sku = excluded.sku,
    atualizado_em = excluded.atualizado_em;
"""

UPSERT_SNAPSHOT = """
INSERT INTO historico_anuncios_diario (
    item_id, data_snapshot, visitas, vendas_quantidade, receita, capturado_em
)
VALUES (:item_id, :data_snapshot, :visitas, :vendas_quantidade, :receita, :capturado_em)
ON CONFLICT(item_id, data_snapshot) DO UPDATE SET
    visitas = excluded.visitas,
    vendas_quantidade = excluded.vendas_quantidade,
    receita = excluded.receita,
    capturado_em = excluded.capturado_em;
"""


def capturar_snapshot_diario(dados_anuncios: list[dict], dia: date | None = None) -> None:
    """
    Grava o snapshot do dia informado (padrão: hoje) a partir de uma lista de
    dicionários já coletados na API, cada um com as chaves:
        item_id, titulo, sku, visitas, vendas_quantidade, receita

    O parâmetro 'dia' existe para permitir backfill de dias passados (ver
    comando 'backfill' em main.py) - na rotina diária normal, é omitido e
    o snapshot é gravado com a data de hoje.
    """
    criar_tabelas()

    data_snapshot = (dia or datetime.now().date()).isoformat()
    agora = datetime.now().isoformat(timespec="seconds")

    conexao = obter_conexao()
    try:
        for item in dados_anuncios:
            conexao.execute(UPSERT_ANUNCIO, {
                "item_id": item["item_id"],
                "titulo": item["titulo"],
                "sku": item.get("sku", ""),
                "atualizado_em": agora,
            })
            conexao.execute(UPSERT_SNAPSHOT, {
                "item_id": item["item_id"],
                "data_snapshot": data_snapshot,
                "visitas": item["visitas"],
                "vendas_quantidade": item["vendas_quantidade"],
                "receita": item["receita"],
                "capturado_em": agora,
            })
        conexao.commit()
        print(f"Snapshot de {data_snapshot} registrado para {len(dados_anuncios)} anúncio(s).")
    finally:
        conexao.close()
