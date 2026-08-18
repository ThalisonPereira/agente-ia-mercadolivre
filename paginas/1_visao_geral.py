"""
paginas/1_visao_geral.py

KPIs consolidados (receita/visitas/vendas) do período selecionado, com
comparação ao período anterior de mesmo tamanho, gráfico de série diária,
e a última análise narrativa gerada pela IA. A análise é lida do banco
(já gerada pela rotina diária automática - ver main.py::_rotina_diaria) e
NÃO chama a API da Anthropic de novo aqui, pra não gerar custo extra só
de abrir o dashboard.
"""

from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from database.analises_diarias import obter_ultima_analise
from database.contas import obter_contas_ativas
from database.kpis import obter_data_mais_recente, obter_serie_diaria, obter_totais_periodo
from paginas._util_filtros import obter_filtros_sidebar

st.title("📊 Visão Geral")

conta_id, canal = obter_filtros_sidebar("visao_geral")

data_maxima = obter_data_mais_recente(conta_id, canal)
if data_maxima is None:
    st.info("Ainda não há dados coletados para esse filtro.")
    st.stop()

data_maxima_date = date.fromisoformat(data_maxima)
data_padrao_inicio = data_maxima_date - timedelta(days=29)

col_data1, col_data2 = st.columns(2)
data_inicio = col_data1.date_input("De", value=data_padrao_inicio, key="visao_geral_data_inicio")
data_fim = col_data2.date_input("Até", value=data_maxima_date, key="visao_geral_data_fim")

if data_inicio > data_fim:
    st.error("A data inicial não pode ser depois da data final.")
    st.stop()

totais = obter_totais_periodo(data_inicio.isoformat(), data_fim.isoformat(), conta_id, canal)

# Período anterior de mesmo tamanho, imediatamente antes do início do período
# escolhido - usado só pra calcular o delta mostrado em cada st.metric.
dias_periodo = (data_fim - data_inicio).days + 1
data_fim_anterior = data_inicio - timedelta(days=1)
data_inicio_anterior = data_fim_anterior - timedelta(days=dias_periodo - 1)
totais_anteriores = obter_totais_periodo(
    data_inicio_anterior.isoformat(), data_fim_anterior.isoformat(), conta_id, canal
)


def _delta_percentual(atual: float, anterior: float) -> str | None:
    if not anterior:
        return None
    return f"{(atual - anterior) / anterior * 100:+.1f}%"


col1, col2, col3 = st.columns(3)
col1.metric(
    "Receita",
    f"R$ {totais['receita']:,.2f}",
    _delta_percentual(totais["receita"], totais_anteriores["receita"]),
)
col2.metric(
    "Visitas",
    f"{totais['visitas']:,}",
    _delta_percentual(totais["visitas"], totais_anteriores["visitas"]),
)
col3.metric(
    "Vendas",
    f"{totais['vendas']:,}",
    _delta_percentual(totais["vendas"], totais_anteriores["vendas"]),
)

st.caption(f"Comparado a {data_inicio_anterior.isoformat()} — {data_fim_anterior.isoformat()} (período anterior de mesmo tamanho)")

serie = obter_serie_diaria(data_inicio.isoformat(), data_fim.isoformat(), conta_id, canal)
if serie:
    # Vendas (unidades, dezenas por dia) fica visualmente colada em zero se
    # dividir o mesmo eixo Y com receita (milhares de R$) - eixo Y próprio
    # pra vendas, via camadas do Altair com resolve_scale independente,
    # resolve isso sem mexer em nenhum dado.
    df_serie = pd.DataFrame(serie)
    cores = {"receita": "#4C78A8", "visitas": "#F58518", "vendas": "#54A24B"}

    base = alt.Chart(df_serie).encode(x=alt.X("data:T", title=None))

    camada_principal = base.transform_fold(
        ["receita", "visitas"], as_=["metrica", "valor"]
    ).mark_line().encode(
        y=alt.Y("valor:Q", title="Receita (R$) / Visitas"),
        color=alt.Color(
            "metrica:N",
            scale=alt.Scale(domain=["receita", "visitas"], range=[cores["receita"], cores["visitas"]]),
            legend=alt.Legend(title=None),
        ),
    )
    camada_vendas = base.mark_line(color=cores["vendas"]).encode(
        y=alt.Y("vendas:Q", title="Vendas", axis=alt.Axis(titleColor=cores["vendas"])),
    )

    grafico = alt.layer(camada_principal, camada_vendas).resolve_scale(y="independent")
    st.altair_chart(grafico, use_container_width=True)
else:
    st.info("Sem dados no período selecionado.")

st.subheader("Análise da IA")

if conta_id:
    # Filtro já restrito a 1 conta específica - 1 bloco só, como antes.
    analise = obter_ultima_analise(conta_id, canal)
    if analise is None:
        st.info("Ainda não há nenhuma análise gerada.")
    else:
        st.caption(f"Conta '{analise['conta_id']}' — {analise['data']} (gerada em {analise['gerado_em']})")
        st.markdown(analise["texto"])
else:
    # "Todas as contas" ou um canal inteiro - uma narrativa combinada
    # misturaria o contexto de contas diferentes numa leitura só. Seletor
    # no topo da seção pra escolher qual conta ver, em vez de empilhar
    # todas (accordion) - mais rápido de ler uma de cada vez.
    contas = obter_contas_ativas(canal)
    blocos = {}
    for conta in contas:
        analise = obter_ultima_analise(conta_id=conta["conta_id"])
        if analise is not None:
            blocos[f"{conta['nome']} ({conta['conta_id']})"] = analise

    if not blocos:
        st.info("Ainda não há nenhuma análise gerada.")
    else:
        escolha = st.selectbox("Conta", list(blocos.keys()), key="visao_geral_analise_conta")
        analise = blocos[escolha]
        st.caption(f"{analise['data']} (gerada em {analise['gerado_em']})")
        st.markdown(analise["texto"])
