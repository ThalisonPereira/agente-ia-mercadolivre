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
from database.analises_diarias import obter_ultima_analise


def _obter_chave_gemini() -> str:
    return st.secrets["GEMINI_API_KEY"]


st.title("🤖 Assistente IA")
st.caption("Pergunte sobre visitas, vendas e receita dos seus anúncios")

if "mensagens" not in st.session_state:
    st.session_state.mensagens_api = []

    # Mostra a análise mais recente automaticamente ao abrir o chat, sem o
    # usuário precisar perguntar nada primeiro - lida direto do banco (mesma
    # fonte da página Visão Geral), sem chamar a Anthropic: essa análise já
    # foi gerada pela rotina diária, não precisa gastar uma chamada de IA só
    # pra reformular um texto que já existe pronto.
    analise = obter_ultima_analise()
    if analise is None:
        texto = "Ainda não há nenhuma análise gerada. Pode perguntar algo que eu busco os dados."
    else:
        texto = f"Análise mais recente (conta '{analise['conta_id']}' — {analise['data']}):\n\n{analise['texto']}"

    st.session_state.mensagens = [{"role": "assistant", "content": texto}]

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
