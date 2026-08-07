"""
paginas/2_ranking.py

Ranking (top N) de anúncios por receita, visitas ou vendas, num período -
reaproveita database/ranking.py::obter_ranking direto, sem alteração.
"""

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from database.kpis import obter_data_mais_recente
from database.ranking import obter_ranking
from paginas._util_filtros import obter_filtros_sidebar

st.title("🏆 Ranking")

conta_id, canal = obter_filtros_sidebar()

data_maxima = obter_data_mais_recente(conta_id, canal)
if data_maxima is None:
    st.info("Ainda não há dados coletados para esse filtro.")
    st.stop()

data_maxima_date = date.fromisoformat(data_maxima)

col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
data_inicio = col1.date_input("De", value=data_maxima_date - timedelta(days=29), key="ranking_data_inicio")
data_fim = col2.date_input("Até", value=data_maxima_date, key="ranking_data_fim")
metrica = col3.selectbox("Métrica", ["receita", "visitas", "vendas"], key="ranking_metrica")
top_n = col4.number_input("Top N", min_value=1, max_value=100, value=10, key="ranking_top_n")

if data_inicio > data_fim:
    st.error("A data inicial não pode ser depois da data final.")
    st.stop()

resultado = obter_ranking(metrica, data_inicio.isoformat(), data_fim.isoformat(), int(top_n), conta_id, canal)

if not resultado:
    st.info("Sem dados no período selecionado.")
else:
    df_ranking = pd.DataFrame(resultado)
    df_ranking["anuncio_curto"] = df_ranking["anuncio"].str.slice(0, 40)
    st.bar_chart(df_ranking.set_index("anuncio_curto")[[metrica]], horizontal=True)
    st.dataframe(
        resultado,
        column_config={
            "receita": st.column_config.NumberColumn("Receita", format="R$ %.2f"),
        },
        hide_index=True,
        use_container_width=True,
    )
