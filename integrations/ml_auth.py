"""
integrations/ml_auth.py

Fluxo de autorização OAuth2 (Authorization Code) com a API do Mercado Livre.

Dividido em 3 funções de teste manual, no mesmo espírito passo1/passo2/passo3
usado no projeto de estoque para o Bling:

    passo1_gerar_link()                 -> gera a URL para abrir no navegador
    passo2_trocar_code_por_token(code)  -> troca o authorization_code pelos tokens
    passo3_testar_chamada_real()        -> usa o access_token salvo para uma chamada real

Nenhuma dessas funções imprime client_secret, access_token ou refresh_token
inteiros na tela - apenas metadados não sensíveis (expiração, escopo, etc.).
"""
import time
import json
import secrets
from pathlib import Path
from urllib.parse import urlencode

import requests

from config.settings import MercadoLivreConfig, carregar_configuracao_ml

AUTHORIZE_URL = "https://auth.mercadolivre.com.br/authorization"
TOKEN_URL = "https://api.mercadolibre.com/oauth/token"

# Arquivo local (fora do controle de versão) onde os tokens ficam guardados
# entre uma execução e outra do programa.
CAMINHO_TOKENS = Path(__file__).resolve().parent.parent / "config" / ".ml_tokens.json"


def passo1_gerar_link() -> str:
    """
    Gera a URL de autorização que deve ser aberta manualmente no navegador.
    """
    config = carregar_configuracao_ml()

    # 'state' é um valor aleatório usado para confirmar que o retorno do
    # Mercado Livre corresponde a esta mesma solicitação (proteção contra CSRF).
    state = secrets.token_urlsafe(16)

    parametros = {
        "response_type": "code",
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "state": state,
    }
    url = f"{AUTHORIZE_URL}?{urlencode(parametros)}"

    print("Abra esta URL no navegador, faça login no Mercado Livre e autorize o aplicativo:\n")
    print(url)
    print(
        "\nApós autorizar, o navegador vai tentar carregar a redirect_uri "
        "configurada e provavelmente mostrará erro de página não encontrada "
        "- isso é esperado, pois não há servidor rodando ali. "
        "Copie o valor do parâmetro 'code' que aparece na barra de endereço "
        "(o código expira em poucos minutos, use-o logo em seguida)."
    )
    return url


def passo2_trocar_code_por_token(authorization_code: str) -> dict:
    """
    Troca o authorization_code (validade curta) pelos tokens de acesso reais,
    e salva o resultado em disco (fora do Git).
    """
    config = carregar_configuracao_ml()

    dados = {
        "grant_type": "authorization_code",
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "code": authorization_code,
        "redirect_uri": config.redirect_uri,
    }

    resposta = requests.post(TOKEN_URL, data=dados, timeout=15)

    if resposta.status_code != 200:
        print(f"Erro ao trocar o code por token (status {resposta.status_code}).")
        print(f"Resposta: {resposta.text}")
        print("Verifique se o code não expirou e tente gerar um novo link.")
        return {}

    tokens = resposta.json()
    _salvar_tokens(tokens)

    print("Tokens obtidos e salvos com sucesso.")
    print(f"Tipo do token: {tokens.get('token_type')}")
    print(f"Expira em (segundos): {tokens.get('expires_in')}")
    print(f"Escopos autorizados: {tokens.get('scope')}")
    print(f"User ID do vendedor: {tokens.get('user_id')}")
    return tokens


def passo3_testar_chamada_real() -> None:
    """
    Usa o access_token salvo (renovando automaticamente se necessário) para
    fazer uma chamada real e simples à API do Mercado Livre (dados da conta).
    """
    access_token = obter_access_token_valido()
    headers = {"Authorization": f"Bearer {access_token}"}

    resposta = requests.get(
        "https://api.mercadolibre.com/users/me",
        headers=headers,
        timeout=15,
    )

    if resposta.status_code != 200:
        print(f"Erro na chamada de teste (status {resposta.status_code}): {resposta.text}")
        return

    usuario = resposta.json()
    print("Chamada realizada com sucesso.")
    print(f"Conta: {usuario.get('nickname')} (id {usuario.get('id')})")
    print(f"Site: {usuario.get('site_id')}")


def _salvar_tokens(tokens: dict) -> None:
    """Salva os tokens em disco, incluindo o horário em que foram obtidos."""
    tokens_com_metadados = {
        **tokens,
        "obtido_em": time.time(),  # timestamp Unix (segundos desde 1970)
    }
    CAMINHO_TOKENS.write_text(json.dumps(tokens_com_metadados, indent=2), encoding="utf-8")


def _carregar_tokens() -> dict | None:
    if not CAMINHO_TOKENS.exists():
        return None
    return json.loads(CAMINHO_TOKENS.read_text(encoding="utf-8"))


# Margem de segurança: renovamos o token um pouco antes dele expirar de
# verdade, para nunca correr o risco de uma chamada cair bem no instante
# da expiração.
MARGEM_SEGURANCA_SEGUNDOS = 60


def _token_expirado(tokens: dict) -> bool:
    """Verifica se o access_token já expirou (ou está perto de expirar)."""
    obtido_em = tokens.get("obtido_em", 0)
    expires_in = tokens.get("expires_in", 0)
    expira_em = obtido_em + expires_in
    agora = time.time()
    return agora >= (expira_em - MARGEM_SEGURANCA_SEGUNDOS)


def _renovar_tokens(config: MercadoLivreConfig, refresh_token: str) -> dict:
    """
    Troca um refresh_token por um novo par access_token/refresh_token.

    Importante: o Mercado Livre invalida o refresh_token antigo a cada
    renovação e devolve um novo. Por isso sempre salvamos o resultado
    imediatamente - se perdermos esse novo refresh_token, o antigo já não
    funciona mais.
    """
    dados = {
        "grant_type": "refresh_token",
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "refresh_token": refresh_token,
    }

    resposta = requests.post(TOKEN_URL, data=dados, timeout=15)

    if resposta.status_code != 200:
        raise RuntimeError(
            f"Falha ao renovar o token (status {resposta.status_code}): {resposta.text}"
        )

    novos_tokens = resposta.json()
    _salvar_tokens(novos_tokens)
    return novos_tokens


def obter_access_token_valido() -> str:
    """
    Ponto único de acesso a um access_token garantidamente válido.

    Todo código que precisar chamar a API do Mercado Livre deve usar esta
    função em vez de ler o arquivo de tokens diretamente - ela decide
    sozinha se precisa renovar antes de devolver o token.
    """
    config = carregar_configuracao_ml()
    tokens = _carregar_tokens()

    if not tokens:
        raise RuntimeError(
            "Nenhum token salvo. Rode 'python main.py passo1' e "
            "'python main.py passo2 <code>' primeiro."
        )

    if _token_expirado(tokens):
        print("Access token expirado ou perto de expirar - renovando automaticamente...")
        tokens = _renovar_tokens(config, tokens["refresh_token"])
        print("Token renovado com sucesso.")

    return tokens["access_token"]


def obter_seller_id() -> str:
    """Retorna o user_id do vendedor associado ao token salvo."""
    tokens = _carregar_tokens()
    if not tokens or "user_id" not in tokens:
        raise RuntimeError(
            "user_id não encontrado nos tokens salvos. Rode o fluxo de autorização novamente."
        )
    return str(tokens["user_id"])
