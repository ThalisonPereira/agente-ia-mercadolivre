"""
paginas/4_consultar_anuncio.py

Busca o desempenho de um anúncio específico por SKU ou parte do título -
reaproveita database/consultar_anuncio.py::buscar_por_sku_ou_titulo.
"""

import streamlit as st

from database.consultar_anuncio import buscar_por_sku_ou_titulo
from paginas._util_filtros import obter_filtros_sidebar

st.title("🔍 Consultar Anúncio")

conta_id, canal = obter_filtros_sidebar("consultar_anuncio")

termo = st.text_input(
    "SKU, ID do Mercado Livre ou parte do título",
    key="consulta_termo",
    placeholder="ex: bancada 120cm, 12064, ou MLB1234567890",
)

col1, col2 = st.columns(2)
data_inicio = col1.date_input("De (opcional)", value=None, key="consulta_data_inicio")
data_fim = col2.date_input("Até (opcional)", value=None, key="consulta_data_fim")

if not termo:
    st.info("Digite um SKU, ID do Mercado Livre ou parte do título pra buscar.")
else:
    resultado = buscar_por_sku_ou_titulo(
        termo,
        data_inicio.isoformat() if data_inicio else None,
        data_fim.isoformat() if data_fim else None,
        conta_id,
        canal,
    )
    if not resultado:
        mensagem = "Nenhum anúncio encontrado com esse termo."
        if data_inicio or data_fim:
            mensagem += " Tente limpar o período acima (o anúncio pode existir fora dessas datas)."
        mensagem += " Confira também o filtro de Canal/Conta na barra lateral."
        st.info(mensagem)
    else:
        st.dataframe(
            resultado,
            column_config={
                "conta_id": st.column_config.TextColumn("Conta"),
                "item_id": st.column_config.TextColumn("ID (Mercado Livre)", help="Identificador do anúncio no Mercado Livre."),
                "anuncio": st.column_config.TextColumn("Anúncio", help="Título do anúncio."),
                "sku": st.column_config.TextColumn("SKU", help="Código do produto cadastrado no anúncio."),
                "periodo": st.column_config.TextColumn("Período", help="Intervalo de datas com dado coletado, somado nesta linha."),
                "visitas": st.column_config.NumberColumn("Visitas", help="Total de visitas no período."),
                "vendas": st.column_config.NumberColumn("Vendas", help="Unidades vendidas no período."),
                "receita": st.column_config.NumberColumn("Receita", format="R$ %.2f", help="Receita total no período."),
            },
            hide_index=True,
            use_container_width=True,
        )
