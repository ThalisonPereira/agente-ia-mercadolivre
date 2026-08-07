"""
paginas/7_extrato.py

Extrato diário de margem por venda: pra cada item vendido (SKU) do dia
mais recente coletado, mostra preço de venda, comissão do Mercado Livre,
frete pago pelo vendedor, valor líquido sem imposto, imposto (14%),
valor líquido final e o custo do produto (Bling), chegando na margem
líquida. Cada coluna tem uma dica (tooltip) explicando o que representa.
Ver database/extrato.py pra fórmula e limitações (ex: SKUs sem custo
cadastrado no Bling ficam sinalizados, não silenciosamente tratados como
custo zero).
"""

import pandas as pd
import streamlit as st

from database.extrato import ALIQUOTA_IMPOSTO, obter_data_mais_recente, obter_extrato, obter_resumo_extrato
from paginas._util_filtros import obter_filtros_sidebar

st.title("📋 Extrato Diário")

conta_id, canal = obter_filtros_sidebar()

data_maxima = obter_data_mais_recente(conta_id, canal)
if data_maxima is None:
    st.info("Ainda não há extrato coletado para esse filtro.")
    st.stop()

st.caption(f"Snapshot de {data_maxima} - imposto estimado em {ALIQUOTA_IMPOSTO:.0%} sobre o preço de venda bruto.")

resumo = obter_resumo_extrato(data_maxima, conta_id, canal)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total vendido", f"R$ {resumo['total_vendido']:,.2f}")
col2.metric("Comissão + Frete", f"R$ {resumo['total_comissao'] + resumo['total_frete']:,.2f}")
col3.metric("Imposto (14%)", f"R$ {resumo['total_imposto']:,.2f}")
col4.metric("Margem líquida", f"R$ {resumo['total_margem']:,.2f}")

if resumo["itens_sem_custo"]:
    st.warning(
        f"⚠️ {resumo['itens_sem_custo']} de {resumo['total_itens']} item(ns) sem custo encontrado no "
        "Bling (SKU não cadastrado, ou custo zerado - comum em produtos 'pai'/kit) - a margem total "
        "acima NÃO inclui esses itens, pra não distorcer o número."
    )

itens = obter_extrato(data_maxima, conta_id, canal)
if itens:
    df = pd.DataFrame(itens)
    df["sku"] = df.apply(lambda linha: linha["sku"] if linha["custo_produto"] is not None else f"⚠️ {linha['sku'] or '(sem SKU)'}", axis=1)
    st.dataframe(
        df,
        column_order=[
            "sku", "titulo", "quantidade", "preco_venda", "comissao_ml", "frete_vendedor",
            "valor_liquido_sem_imposto", "imposto", "valor_liquido", "custo_produto", "margem",
        ],
        column_config={
            "sku": st.column_config.TextColumn("SKU", help="Código do produto no momento da venda - ⚠️ significa que não foi encontrado (ou tinha custo zerado) no Bling."),
            "titulo": st.column_config.TextColumn("Anúncio", help="Título do anúncio no Mercado Livre."),
            "quantidade": st.column_config.NumberColumn("Qtd", help="Quantidade vendida nessa linha."),
            "preco_venda": st.column_config.NumberColumn("Preço Venda", format="R$ %.2f", help="Valor bruto da venda (preço unitário × quantidade), antes de qualquer desconto."),
            "comissao_ml": st.column_config.NumberColumn("Comissão ML", format="R$ %.2f", help="Comissão cobrada pelo Mercado Livre sobre essa venda."),
            "frete_vendedor": st.column_config.NumberColumn("Frete", format="R$ %.2f", help="Custo do frete pago pelo vendedor (não o valor cobrado do comprador)."),
            "valor_liquido_sem_imposto": st.column_config.NumberColumn("Valor Líquido (sem imposto)", format="R$ %.2f", help="Preço de venda menos comissão do ML e frete - ainda SEM descontar o imposto."),
            "imposto": st.column_config.NumberColumn(f"Imposto ({ALIQUOTA_IMPOSTO:.0%})", format="R$ %.2f", help=f"Estimativa de imposto: {ALIQUOTA_IMPOSTO:.0%} sobre o preço de venda bruto."),
            "valor_liquido": st.column_config.NumberColumn("Valor Líquido", format="R$ %.2f", help="Valor líquido (sem imposto) menos o imposto estimado - o que sobra da venda antes do custo do produto."),
            "custo_produto": st.column_config.NumberColumn("Custo", format="R$ %.2f", help="Custo do produto cadastrado no Bling (campo precoCusto), pelo SKU."),
            "margem": st.column_config.NumberColumn("Margem", format="R$ %.2f", help="Lucro real da venda: valor líquido menos o custo do produto."),
        },
        hide_index=True,
        use_container_width=True,
    )
