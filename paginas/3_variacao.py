"""
paginas/3_variacao.py

Comparação de visitas/vendas entre as duas datas de snapshot mais
recentes disponíveis (mesma lógica usada pelo chat) - reaproveita
database/analisar_variacao.py::obter_variacao_anuncios sem alteração de
comportamento, só passando o filtro de conta/canal da sidebar.
"""

import pandas as pd
import streamlit as st

from database.analisar_variacao import obter_variacao_anuncios
from paginas._util_filtros import obter_filtros_sidebar

st.title("📈 Variação")

conta_id, canal = obter_filtros_sidebar()

resultado = obter_variacao_anuncios(conta_id=conta_id, canal=canal)

if not resultado:
    st.info(
        "Ainda não há snapshots suficientes pra comparar (precisa de pelo "
        "menos 2 dias de histórico) para esse filtro."
    )
else:
    data_comparacao = resultado[0]["data"]
    st.caption(f"Comparando com o dia de snapshot anterior, até {data_comparacao}.")

    contagem_status = pd.Series([linha["status"] for linha in resultado]).value_counts()
    col1, col2, col3 = st.columns(3)
    col1.metric("📈 Alta", int(contagem_status.get("Alta", 0)))
    col2.metric("📉 Queda", int(contagem_status.get("Queda", 0)))
    col3.metric("➖ Estável", int(contagem_status.get("Estável", 0)))

    filtro_status = st.multiselect(
        "Status", ["Queda", "Alta", "Estável"], default=["Queda", "Alta", "Estável"], key="variacao_status"
    )
    ordem_status = {"Queda": 0, "Alta": 1, "Estável": 2}
    linhas_filtradas = sorted(
        (linha for linha in resultado if linha["status"] in filtro_status),
        key=lambda linha: ordem_status.get(linha["status"], 99),
    )

    if not linhas_filtradas:
        st.info("Nenhum anúncio com o status selecionado.")
    else:
        st.dataframe(
            pd.DataFrame(linhas_filtradas),
            column_config={
                "receita": st.column_config.NumberColumn("Receita", format="R$ %.2f"),
                "variacao_visitas": st.column_config.NumberColumn("Var. Visitas", format="%.1f%%"),
                "variacao_vendas": st.column_config.NumberColumn("Var. Vendas", format="%.1f%%"),
            },
            hide_index=True,
            use_container_width=True,
        )
