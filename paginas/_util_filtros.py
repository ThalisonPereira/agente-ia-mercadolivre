"""
paginas/_util_filtros.py

Filtro de conta/canal compartilhado entre as páginas de dados do
dashboard (Visão Geral, Ranking, Variação, Consultar Anúncio) - não usado
pelo Chat IA, que já deixa o modelo decidir o filtro a partir da pergunta
em linguagem natural (ver agents/assistente_ia.py).

Fica na barra lateral; o valor escolhido persiste em st.session_state
entre trocas de página (st.navigation preserva o estado da sessão, não
reseta a cada navegação).
"""

import streamlit as st

from database.contas import obter_contas_ativas


def obter_filtros_sidebar() -> tuple[str | None, str | None]:
    """Renderiza o seletor de canal/conta na sidebar e retorna (conta_id, canal) - None significa "todas"."""
    contas = obter_contas_ativas()

    canais = sorted({conta["canal"] for conta in contas})
    opcoes_canal = ["Todos os canais"] + canais
    if st.session_state.get("filtro_canal_label") not in opcoes_canal:
        st.session_state["filtro_canal_label"] = "Todos os canais"
    canal_escolhido = st.sidebar.selectbox("Canal", opcoes_canal, key="filtro_canal_label")
    canal = None if canal_escolhido == "Todos os canais" else canal_escolhido

    contas_do_canal = [c for c in contas if canal is None or c["canal"] == canal]
    opcoes_conta = {"Todas as contas": None}
    opcoes_conta.update({f"{c['nome']} ({c['conta_id']})": c["conta_id"] for c in contas_do_canal})
    if st.session_state.get("filtro_conta_label") not in opcoes_conta:
        st.session_state["filtro_conta_label"] = "Todas as contas"
    nome_conta_escolhida = st.sidebar.selectbox("Conta", list(opcoes_conta.keys()), key="filtro_conta_label")
    conta_id = opcoes_conta[nome_conta_escolhida]

    return conta_id, canal
