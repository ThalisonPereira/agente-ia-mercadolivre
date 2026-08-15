"""
paginas/_util_auth.py

Trava de acesso simples pro dashboard: hospedado no Streamlit Community
Cloud, sem isso qualquer pessoa com o link via margem, custo de produto e
faturamento (dado sensível do negócio) e conseguia conversar com o chat
que tem acesso a tudo isso. Não é um sistema de contas/usuários - é uma
senha única compartilhada, suficiente pro caso de uso (1 painel interno,
poucas pessoas de confiança), guardada em st.secrets (nunca no código).
"""

import hmac

import streamlit as st


def exigir_login() -> None:
    """
    Bloqueia o app inteiro até a senha certa ser digitada. Chamar uma
    única vez, no topo de app.py, antes de renderizar qualquer página -
    st.session_state guarda o resultado pra não pedir de novo a cada
    troca de página dentro da mesma sessão do navegador.
    """
    if st.session_state.get("autenticado"):
        return

    senha_configurada = st.secrets.get("APP_PASSWORD")
    if not senha_configurada:
        st.error(
            "APP_PASSWORD não configurado em st.secrets - o dashboard não pode abrir sem uma "
            "senha definida. Configure em .streamlit/secrets.toml (local) ou no painel do "
            "Streamlit Community Cloud (Settings > Secrets)."
        )
        st.stop()

    st.title("🔒 Painel de Contas")
    senha_digitada = st.text_input("Senha", type="password", key="campo_senha_login")

    if senha_digitada:
        # compare_digest evita vazar, por tempo de resposta, quantos
        # caracteres da senha estão certos - não é o risco principal aqui,
        # mas não custa nada.
        if hmac.compare_digest(senha_digitada, senha_configurada):
            st.session_state["autenticado"] = True
            st.rerun()
        else:
            st.error("Senha incorreta.")

    st.stop()
