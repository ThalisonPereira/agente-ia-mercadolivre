"""
app.py

Ponto de entrada do dashboard multipágina (Streamlit): reúne o chat de IA
e as páginas de KPIs/ranking/variação/consulta num só app, hospedado de
graça no Streamlit Community Cloud. Substitui chat_app.py como main file
do deploy.

Credenciais (Anthropic, Turso) vêm de st.secrets, não do .env - porque,
hospedado na nuvem, o app não tem acesso ao .env local (ver
.streamlit/secrets.toml.example). Espelhadas em os.environ aqui, uma
única vez, ANTES de importar qualquer coisa de database/*.py ou
agents/*.py (usado por todas as páginas) - esses módulos leem config via
config/settings.py + variável de ambiente, então essa cópia evita ter
dois sistemas de configuração paralelos dentro do processo.

Usa a API moderna st.navigation/st.Page (Streamlit >=1.36) em vez da
convenção antiga de pasta "pages/" com auto-discovery, pra ter controle
explícito de título/ícone/ordem e poder centralizar esse bootstrap aqui.
As páginas ficam em "paginas/" (nome deliberadamente diferente de
"pages/", pra não colidir com o auto-discovery nativo do Streamlit).
"""

import os

import streamlit as st

for _chave in ("ANTHROPIC_API_KEY", "TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN"):
    if _chave in st.secrets:
        os.environ.setdefault(_chave, st.secrets[_chave])

st.set_page_config(page_title="Painel de Contas", page_icon="📊", layout="wide")

paginas = st.navigation([
    st.Page("paginas/1_visao_geral.py", title="Visão Geral", icon="📊", default=True),
    st.Page("paginas/2_ranking.py", title="Ranking", icon="🏆"),
    st.Page("paginas/3_variacao.py", title="Variação", icon="📈"),
    st.Page("paginas/4_consultar_anuncio.py", title="Consultar Anúncio", icon="🔍"),
    st.Page("paginas/6_pedidos.py", title="Pedidos", icon="📦"),
    st.Page("paginas/5_chat_ia.py", title="Chat IA", icon="🤖"),
])
paginas.run()
