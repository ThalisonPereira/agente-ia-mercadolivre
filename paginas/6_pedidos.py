"""
paginas/6_pedidos.py

Pedidos do dia mais recente coletado, por status de envio - "prontos pra
envio" (imediato) vs "aguardando preparo" (postergado), já enviados e
cancelados. Não confundir com o KPI "Vendas" das outras páginas (esse
conta unidades vendidas); aqui é número de PEDIDOS.

Sempre mostra o snapshot de UMA data específica (a mais recente
disponível pro filtro escolhido), não uma soma ao longo de um período -
o status de envio é capturado 1x no dia do pedido e não é atualizado
depois, então somar datas antigas junto com recentes distorceria a
leitura (ver database/pedidos.py).
"""

import streamlit as st

from database.pedidos import obter_contas_desatualizadas, obter_data_mais_recente, obter_pedidos, obter_resumo
from paginas._util_filtros import obter_filtros_sidebar

st.title("📦 Pedidos")

conta_id, canal = obter_filtros_sidebar()

data_maxima = obter_data_mais_recente(conta_id, canal)
if data_maxima is None:
    st.info("Ainda não há pedidos coletados para esse filtro.")
    st.stop()

st.caption(f"Snapshot de {data_maxima} - status capturado no dia do pedido, não é atualizado depois.")

if not conta_id:
    contas_atrasadas = obter_contas_desatualizadas(data_maxima, canal)
    if contas_atrasadas:
        st.warning(
            f"⚠️ Conta(s) {', '.join(contas_atrasadas)} ainda não tem pedido de {data_maxima} "
            "coletado - o(s) pedido(s) dela(s) não aparece(m) neste snapshot."
        )

resumo = obter_resumo(data_maxima, conta_id, canal)

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total de pedidos", resumo["total"])
col2.metric("🟢 Pronto pra envio", resumo["imediato"])
col3.metric("🟡 Aguardando preparo", resumo["postergado"])
col4.metric("🔵 Já enviado", resumo["enviado"])
col5.metric("🔴 Cancelado", resumo["cancelado"])

st.caption(f"Valor total dos pedidos do dia: R$ {resumo['valor_total']:,.2f}")

pedidos = obter_pedidos(data_maxima, conta_id, canal)
if pedidos:
    st.dataframe(
        pedidos,
        column_config={
            "valor_total": st.column_config.NumberColumn("Valor", format="R$ %.2f"),
        },
        hide_index=True,
        use_container_width=True,
    )
