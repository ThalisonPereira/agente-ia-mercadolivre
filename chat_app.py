"""
chat_app.py

Chat de IA sobre o desempenho dos anúncios no Mercado Livre - responde
perguntas usando um assistente com tool-calling (agents/assistente_ia.py)
que consulta o banco de dados (Turso) direto, buscando só o dado necessário
pra cada pergunta em vez de mandar todo o histórico como contexto (o
design antigo chegou a mandar ~318 mil tokens por pergunta).

Roda tanto localmente (streamlit run chat_app.py) quanto hospedado de
graça no Streamlit Community Cloud (share.streamlit.io).

Credenciais (chave da Anthropic, credenciais do Turso) vêm de st.secrets,
não do .env - isso porque, quando hospedado na nuvem, o app não tem acesso
ao .env local; essas informações ficam configuradas separadamente no painel
do Streamlit Cloud (ver .streamlit/secrets.toml.example). st.secrets é
espelhado nas variáveis de ambiente pra que agents/assistente_ia.py e o
resto do database/*.py (que leem config via config/settings.py + .env)
funcionem sem precisar de dois sistemas de configuração paralelos dentro
deste processo.
"""

import os

import streamlit as st

for _chave in ("GEMINI_API_KEY", "TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN"):
    if _chave in st.secrets:
        os.environ.setdefault(_chave, st.secrets[_chave])

from agents.assistente_ia import responder_pergunta  # noqa: E402 (precisa vir depois do os.environ acima)

PERGUNTA_RESUMO_INICIAL = "Me dê um resumo objetivo da análise mais recente disponível."


def _obter_chave_gemini() -> str:
    return st.secrets["GEMINI_API_KEY"]


st.set_page_config(page_title="Assistente IA - Anúncios", page_icon="🤖")
st.title("🤖 Assistente IA")
st.caption("Pergunte sobre visitas, vendas e receita dos seus anúncios no Mercado Livre")

if "mensagens" not in st.session_state:
    st.session_state.mensagens = []
    st.session_state.mensagens_api = []

    # Mostra a análise mais recente automaticamente ao abrir o chat, sem o
    # usuário precisar perguntar nada primeiro.
    with st.spinner("Carregando resumo do dia..."):
        try:
            texto, mensagens_api, _uso = responder_pergunta(
                PERGUNTA_RESUMO_INICIAL, [], _obter_chave_gemini()
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
                    pergunta, st.session_state.mensagens_api, _obter_chave_gemini()
                )
                st.session_state.mensagens_api = mensagens_api
            except Exception as erro:
                resposta = f"Erro ao consultar: {erro}"
            st.markdown(resposta)

    st.session_state.mensagens.append({"role": "assistant", "content": resposta})
