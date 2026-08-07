"""
paginas/5_chat_ia.py

Chat de IA sobre o desempenho dos anúncios - responde perguntas usando um
assistente com tool-calling (agents/assistente_ia.py) que consulta o
banco de dados (Turso) direto, buscando só o dado necessário pra cada
pergunta em vez de mandar todo o histórico como contexto (o design antigo
chegou a mandar ~318 mil tokens por pergunta).

Não tem filtro de conta/canal na sidebar (diferente das outras páginas) -
o próprio modelo decide o filtro certo a partir da pergunta em linguagem
natural ("como foi a Shopee esse mês", "compara as contas do Mercado
Livre"), usando os parâmetros conta_id/canal já expostos nas ferramentas.

Bootstrap de secrets → os.environ já foi feito em app.py, antes desta
página ser executada.
"""

import streamlit as st

from agents.assistente_ia import responder_pergunta

PERGUNTA_RESUMO_INICIAL = "Me dê um resumo objetivo da análise mais recente disponível."


def _obter_chave_anthropic() -> str:
    return st.secrets["ANTHROPIC_API_KEY"]


st.title("🤖 Assistente IA")
st.caption("Pergunte sobre visitas, vendas e receita dos seus anúncios")

if "mensagens" not in st.session_state:
    st.session_state.mensagens = []
    st.session_state.mensagens_api = []

    # Mostra a análise mais recente automaticamente ao abrir o chat, sem o
    # usuário precisar perguntar nada primeiro.
    with st.spinner("Carregando resumo do dia..."):
        try:
            texto, mensagens_api, _uso = responder_pergunta(
                PERGUNTA_RESUMO_INICIAL, [], _obter_chave_anthropic()
            )
        except Exception as erro:
            texto = f"Não consegui carregar o resumo automático: {erro}"
            mensagens_api = []

    st.session_state.mensagens.append({"role": "assistant", "content": texto})
    st.session_state.mensagens_api = mensagens_api

for mensagem in st.session_state.mensagens:
    with st.chat_message(mensagem["role"]):
        st.markdown(mensagem["content"])

pergunta = st.chat_input("Escreva sua pergunta...")
if pergunta:
    st.session_state.mensagens.append({"role": "user", "content": pergunta})
    with st.chat_message("user"):
        st.markdown(pergunta)

    with st.chat_message("assistant"):
        with st.spinner("Consultando os dados..."):
            try:
                resposta, mensagens_api, _uso = responder_pergunta(
                    pergunta, st.session_state.mensagens_api, _obter_chave_anthropic()
                )
                st.session_state.mensagens_api = mensagens_api
            except Exception as erro:
                resposta = f"Erro ao consultar: {erro}"
            st.markdown(resposta)

    st.session_state.mensagens.append({"role": "assistant", "content": resposta})
