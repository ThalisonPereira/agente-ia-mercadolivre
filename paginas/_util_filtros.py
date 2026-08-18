"""
paginas/_util_filtros.py

Filtro de conta/canal usado pelas páginas de dados do dashboard (Visão
Geral, Ranking, Variação, Consultar Anúncio, Pedidos, Extrato) - não
usado pelo Chat IA, que já deixa o modelo decidir o filtro a partir da
pergunta em linguagem natural (ver agents/assistente_ia.py).

Fica na barra lateral. Cada página tem sua PRÓPRIA seleção, independente
das outras (por escolha do usuário - selecionar uma conta no Ranking não
deve afetar o que a Variação mostra) - por isso a chave de
st.session_state inclui o identificador da página, em vez de uma chave
fixa compartilhada por todo o app.
"""

import streamlit as st

from database.contas import obter_contas_ativas


def obter_filtros_sidebar(pagina: str) -> tuple[str | None, str | None]:
    """
    Renderiza o seletor de canal/conta na sidebar e retorna (conta_id, canal)
    - None significa "todas". `pagina` é um identificador curto e único
    (ex: "ranking", "extrato") que isola a seleção dessa página das demais -
    cada página nasce em "Todos os canais"/"Todas as contas" e mantém sua
    própria escolha entre reruns, sem interferir nem ser afetada pelas
    outras páginas.
    """
    chave_canal = f"filtro_canal_label__{pagina}"
    chave_conta = f"filtro_conta_label__{pagina}"

    contas = obter_contas_ativas()

    canais = sorted({conta["canal"] for conta in contas})
    opcoes_canal = ["Todos os canais"] + canais
    if st.session_state.get(chave_canal) not in opcoes_canal:
        st.session_state[chave_canal] = "Todos os canais"
    canal_escolhido = st.sidebar.selectbox("Canal", opcoes_canal, key=chave_canal)
    canal = None if canal_escolhido == "Todos os canais" else canal_escolhido

    contas_do_canal = [c for c in contas if canal is None or c["canal"] == canal]
    opcoes_conta = {"Todas as contas": None}
    opcoes_conta.update({f"{c['nome']} ({c['conta_id']})": c["conta_id"] for c in contas_do_canal})
    if st.session_state.get(chave_conta) not in opcoes_conta:
        st.session_state[chave_conta] = "Todas as contas"
    nome_conta_escolhida = st.sidebar.selectbox("Conta", list(opcoes_conta.keys()), key=chave_conta)
    conta_id = opcoes_conta[nome_conta_escolhida]

    return conta_id, canal
