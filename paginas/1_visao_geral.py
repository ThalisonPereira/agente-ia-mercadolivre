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

import pandas as pd
import streamlit as st

from database.analises_diarias import obter_ultima_analise
from database.kpis import obter_data_mais_recente, obter_serie_diaria, obter_totais_periodo
from paginas._util_filtros import obter_filtros_sidebar

st.title("📊 Visão Geral")

conta_id, canal = obter_filtros_sidebar()

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
    df_serie = pd.DataFrame(serie).set_index("data")
    st.line_chart(df_serie[["receita", "visitas", "vendas"]])
else:
    st.info("Sem dados no período selecionado.")

st.subheader("Análise da IA")
analise = obter_ultima_analise(conta_id, canal)
if analise is None:
    st.info("Ainda não há nenhuma análise gerada.")
else:
    st.caption(f"Conta '{analise['conta_id']}' — {analise['data']} (gerada em {analise['gerado_em']})")
    st.markdown(analise["texto"])
