"""
paginas/4_consultar_anuncio.py

Busca o desempenho de um anúncio específico por SKU ou parte do título -
reaproveita database/consultar_anuncio.py::buscar_por_sku_ou_titulo.
"""

import streamlit as st

from database.consultar_anuncio import buscar_por_sku_ou_titulo
from paginas._util_filtros import obter_filtros_sidebar

st.title("🔍 Consultar Anúncio")

conta_id, canal = obter_filtros_sidebar()

termo = st.text_input("SKU ou parte do título", key="consulta_termo", placeholder="ex: bancada 120cm")

col1, col2 = st.columns(2)
data_inicio = col1.date_input("De (opcional)", value=None, key="consulta_data_inicio")
data_fim = col2.date_input("Até (opcional)", value=None, key="consulta_data_fim")

if not termo:
    st.info("Digite um SKU ou parte do título pra buscar.")
else:
    resultado = buscar_por_sku_ou_titulo(
        termo,
        data_inicio.isoformat() if data_inicio else None,
        data_fim.isoformat() if data_fim else None,
        conta_id,
        canal,
    )
    if not resultado:
        st.info("Nenhum anúncio encontrado com esse termo, nesse filtro/período.")
    else:
        st.dataframe(
            resultado,
            column_config={
                "receita": st.column_config.NumberColumn("Receita", format="R$ %.2f"),
            },
            hide_index=True,
            use_container_width=True,
        )
