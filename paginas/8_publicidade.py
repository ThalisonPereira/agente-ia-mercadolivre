"""
paginas/8_publicidade.py

Publicidade (Mercado Ads/Product Ads): pra um intervalo de datas (1 dia,
por padrão o mais recente coletado, ou um período customizado), mostra
gasto, cliques, impressões, CTR, CPC, ACOS, ROAS e vendas atribuídas
(diretas + indiretas) - por campanha e por anúncio - além da análise da
IA especializada em publicidade (uma por conta, quando o filtro reúne
mais de uma). Ver database/ads.py pra fórmula (ACOS/ROAS/CTR/CPC sempre
recalculados a partir dos valores brutos somados, nunca a média de
percentuais). Recomendações da IA são só sugestão em texto - não há
aplicação automática (sem endpoint de escrita confirmado na API do
Mercado Livre).
"""

from datetime import date

import pandas as pd
import streamlit as st

from database.ads import obter_anuncios, obter_campanhas, obter_data_mais_recente, obter_resumo
from database.analises_ads_diarias import obter_ultima_analise_ads
from database.contas import obter_contas_ativas
from paginas._util_filtros import obter_filtros_sidebar

st.title("📣 Publicidade")

conta_id, canal = obter_filtros_sidebar("publicidade")

data_maxima = obter_data_mais_recente(conta_id, canal)
if data_maxima is None:
    st.info("Ainda não há dados de publicidade coletados para esse filtro.")
    st.stop()

data_maxima_date = date.fromisoformat(data_maxima)

col_data1, col_data2 = st.columns(2)
data_inicio = col_data1.date_input("De", value=data_maxima_date, key="publicidade_data_inicio")
data_fim = col_data2.date_input("Até", value=data_maxima_date, key="publicidade_data_fim")

if data_inicio > data_fim:
    st.error("A data inicial não pode ser depois da data final.")
    st.stop()

if data_inicio == data_fim:
    st.caption(f"Dia {data_inicio.isoformat()}")
else:
    st.caption(f"Período de {data_inicio.isoformat()} a {data_fim.isoformat()}")

resumo = obter_resumo(data_inicio.isoformat(), data_fim.isoformat(), conta_id, canal)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Investido", f"R$ {resumo['cost']:,.2f}")
col2.metric("Vendas atribuídas", f"R$ {resumo['total_amount']:,.2f}")
col3.metric("ACOS", f"{resumo['acos']:.1f}%", help="Custo de publicidade sobre a receita gerada por ela - quanto menor, melhor.")
col4.metric("ROAS", f"{resumo['roas']:.1f}x", help="Receita gerada pra cada R$1 investido - quanto maior, melhor.")

col5, col6, col7, col8 = st.columns(4)
col5.metric("Cliques", f"{resumo['clicks']:,}")
col6.metric("Impressões", f"{resumo['prints']:,}")
col7.metric("CTR", f"{resumo['ctr']:.2f}%")
col8.metric("Unidades vendidas", f"{resumo['units_quantity']:,}")

st.caption(
    f"Vendas diretas (clicou e comprou o mesmo anúncio): {resumo['direct_units_quantity']} "
    f"(R$ {resumo['direct_amount']:,.2f}) - "
    f"Vendas indiretas (clicou e comprou outro produto do vendedor): {resumo['indirect_units_quantity']} "
    f"(R$ {resumo['indirect_amount']:,.2f})"
)

if conta_id is None:
    contas = obter_contas_ativas(canal)
    if len(contas) > 1:
        st.subheader("Resumo por conta")
        linhas_por_conta = []
        for conta in contas:
            resumo_conta = obter_resumo(data_inicio.isoformat(), data_fim.isoformat(), conta_id=conta["conta_id"])
            if resumo_conta["cost"] == 0 and resumo_conta["clicks"] == 0:
                continue
            linhas_por_conta.append({
                "conta_id": conta["conta_id"],
                "nome": conta["nome"],
                "cost": resumo_conta["cost"],
                "total_amount": resumo_conta["total_amount"],
                "acos": resumo_conta["acos"],
                "roas": resumo_conta["roas"],
                "clicks": resumo_conta["clicks"],
            })
        if linhas_por_conta:
            st.dataframe(
                pd.DataFrame(linhas_por_conta),
                column_config={
                    "conta_id": st.column_config.TextColumn("Conta"),
                    "nome": st.column_config.TextColumn("Nome"),
                    "cost": st.column_config.NumberColumn("Investido", format="R$ %.2f"),
                    "total_amount": st.column_config.NumberColumn("Vendas atribuídas", format="R$ %.2f"),
                    "acos": st.column_config.NumberColumn("ACOS", format="%.1f%%"),
                    "roas": st.column_config.NumberColumn("ROAS", format="%.1fx"),
                    "clicks": st.column_config.NumberColumn("Cliques"),
                },
                hide_index=True,
                use_container_width=True,
            )

st.subheader("Campanhas")
campanhas = obter_campanhas(data_inicio.isoformat(), data_fim.isoformat(), conta_id, canal)
if campanhas:
    df_campanhas = pd.DataFrame(campanhas)
    colunas_iniciais = ["conta_id"] if conta_id is None else []
    st.dataframe(
        df_campanhas,
        column_order=colunas_iniciais + [
            "nome", "status", "budget", "roas_target", "clicks", "prints", "ctr",
            "cost", "cpc", "acos", "roas", "direct_units_quantity", "indirect_units_quantity",
        ],
        column_config={
            "conta_id": st.column_config.TextColumn("Conta"),
            "nome": st.column_config.TextColumn("Campanha"),
            "status": st.column_config.TextColumn("Status", help="'active' = veiculando, 'paused' = pausada pelo vendedor."),
            "budget": st.column_config.NumberColumn("Orçamento/dia", format="R$ %.2f"),
            "roas_target": st.column_config.NumberColumn("Meta ROAS", format="%.1fx", help="Meta de retorno definida pro vendedor pra essa campanha."),
            "clicks": st.column_config.NumberColumn("Cliques"),
            "prints": st.column_config.NumberColumn("Impressões"),
            "ctr": st.column_config.NumberColumn("CTR", format="%.2f%%"),
            "cost": st.column_config.NumberColumn("Investido", format="R$ %.2f"),
            "cpc": st.column_config.NumberColumn("CPC", format="R$ %.2f", help="Custo médio por clique."),
            "acos": st.column_config.NumberColumn("ACOS", format="%.1f%%"),
            "roas": st.column_config.NumberColumn("ROAS", format="%.1fx"),
            "direct_units_quantity": st.column_config.NumberColumn("Vendas diretas"),
            "indirect_units_quantity": st.column_config.NumberColumn("Vendas indiretas"),
        },
        hide_index=True,
        use_container_width=True,
    )
else:
    st.info("Nenhuma campanha nesse intervalo, pra esse filtro.")

st.subheader("Anúncios (top gasto)")
anuncios = obter_anuncios(data_inicio.isoformat(), data_fim.isoformat(), conta_id, canal)
if anuncios:
    df_anuncios = pd.DataFrame(anuncios)
    colunas_iniciais = ["conta_id"] if conta_id is None else []
    st.dataframe(
        df_anuncios,
        column_order=colunas_iniciais + ["item_id", "titulo", "status", "clicks", "prints", "cost", "cpc", "acos", "total_amount", "units_quantity"],
        column_config={
            "conta_id": st.column_config.TextColumn("Conta"),
            "item_id": st.column_config.TextColumn("ID (Mercado Livre)"),
            "titulo": st.column_config.TextColumn("Anúncio"),
            "status": st.column_config.TextColumn("Status"),
            "clicks": st.column_config.NumberColumn("Cliques"),
            "prints": st.column_config.NumberColumn("Impressões"),
            "cost": st.column_config.NumberColumn("Investido", format="R$ %.2f"),
            "cpc": st.column_config.NumberColumn("CPC", format="R$ %.2f"),
            "acos": st.column_config.NumberColumn("ACOS", format="%.1f%%"),
            "total_amount": st.column_config.NumberColumn("Vendas atribuídas", format="R$ %.2f"),
            "units_quantity": st.column_config.NumberColumn("Unidades"),
        },
        hide_index=True,
        use_container_width=True,
    )
else:
    st.info("Nenhum anúncio nesse intervalo, pra esse filtro.")

st.subheader("Análise da IA")
st.caption("Recomendações em texto pra você aplicar manualmente no painel do Mercado Livre - não há aplicação automática.")

if conta_id:
    analise = obter_ultima_analise_ads(conta_id, canal)
    if analise is None:
        st.info("Ainda não há nenhuma análise de publicidade gerada pra essa conta.")
    else:
        st.caption(f"Conta '{analise['conta_id']}' — {analise['data']} (gerada em {analise['gerado_em']})")
        st.markdown(analise["texto"])
else:
    contas = obter_contas_ativas(canal)
    blocos = []
    for conta in contas:
        analise = obter_ultima_analise_ads(conta_id=conta["conta_id"])
        if analise is not None:
            blocos.append((conta, analise))

    if not blocos:
        st.info("Ainda não há nenhuma análise de publicidade gerada.")
    else:
        for conta, analise in blocos:
            with st.expander(f"{conta['nome']} ({conta['conta_id']})", expanded=True):
                st.caption(f"{analise['data']} (gerada em {analise['gerado_em']})")
                st.markdown(analise["texto"])
