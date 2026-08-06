"""
chat_app.py

Chat de IA sobre o desempenho dos anúncios no Mercado Livre - lê o
histórico direto da aba "Histórico Completo" da planilha do Google Sheets
e usa a API da Anthropic para responder perguntas em linguagem natural.

Roda tanto localmente (streamlit run chat_app.py) quanto hospedado de
graça no Streamlit Community Cloud (share.streamlit.io).

Credenciais (chave da Anthropic, credencial da service account do Google e
o ID da planilha) vêm de st.secrets, não do .env - isso porque, quando
hospedado na nuvem, o app não tem acesso ao .env local nem ao arquivo
google_service_account.json; essas informações ficam configuradas
separadamente no painel do Streamlit Cloud (ver .streamlit/secrets.toml.example).
"""

import anthropic
import gspread
import streamlit as st
from google.oauth2.service_account import Credentials

MODELO = "claude-sonnet-5"  # janela de contexto de 1M tokens (Haiku 4.5 tem só 200K, insuficiente pro histórico completo)
ESCOPOS = ["https://www.googleapis.com/auth/spreadsheets"]
ABA_HISTORICO = "Histórico Completo"
ABA_ANALISE = "Análise IA"

SYSTEM_PROMPT = (
    "Você é um assistente que responde perguntas sobre o desempenho de "
    "anúncios de um vendedor no Mercado Livre, com base no histórico diário "
    "de visitas, vendas e receita por anúncio fornecido abaixo. Responda em "
    "português, de forma direta e objetiva, citando números quando fizer "
    "sentido. Se a pergunta não puder ser respondida com os dados "
    "disponíveis, diga isso claramente em vez de inventar números."
)


@st.cache_resource
def _conectar_planilha():
    """Autentica com a service account e abre a planilha (cacheado - roda 1 vez por sessão)."""
    info_credenciais = dict(st.secrets["google_service_account"])
    credenciais = Credentials.from_service_account_info(info_credenciais, scopes=ESCOPOS)
    cliente = gspread.authorize(credenciais)
    return cliente.open_by_key(st.secrets["GOOGLE_SHEETS_ID"])


@st.cache_data(ttl=300)
def _carregar_contexto() -> tuple[str, str]:
    """
    Lê a aba de histórico (e a de análise, se existir) e monta um texto
    compacto para servir de contexto ao modelo. Cacheado por 5 minutos para
    não reler a planilha inteira a cada pergunta do chat.
    """
    planilha = _conectar_planilha()

    aba_historico = planilha.worksheet(ABA_HISTORICO)
    linhas = aba_historico.get_all_values()
    contexto_historico = "\n".join(" | ".join(linha) for linha in linhas)

    try:
        aba_analise = planilha.worksheet(ABA_ANALISE)
        contexto_analise = "\n".join(" ".join(linha) for linha in aba_analise.get_all_values())
    except gspread.WorksheetNotFound:
        contexto_analise = ""

    return contexto_historico, contexto_analise


def _responder(pergunta: str, contexto_historico: str, contexto_analise: str) -> str:
    client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])

    mensagem_usuario = f"DADOS HISTÓRICOS (uma linha por dia/anúncio):\n{contexto_historico}\n\n"
    if contexto_analise:
        mensagem_usuario += f"ÚLTIMA ANÁLISE GERADA:\n{contexto_analise}\n\n"
    mensagem_usuario += f"PERGUNTA: {pergunta}"

    resposta = client.messages.create(
        model=MODELO,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": mensagem_usuario}],
    )
    return next((bloco.text for bloco in resposta.content if bloco.type == "text"), "")


st.set_page_config(page_title="Assistente IA - Anúncios", page_icon="🤖")
st.title("🤖 Assistente IA")
st.caption("Pergunte sobre visitas, vendas e receita dos seus anúncios no Mercado Livre")

if "mensagens" not in st.session_state:
    st.session_state.mensagens = []

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
                contexto_historico, contexto_analise = _carregar_contexto()
                resposta = _responder(pergunta, contexto_historico, contexto_analise)
            except Exception as erro:
                resposta = f"Erro ao consultar: {erro}"
            st.markdown(resposta)

    st.session_state.mensagens.append({"role": "assistant", "content": resposta})
