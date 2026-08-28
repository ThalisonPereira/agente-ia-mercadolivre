"""
integrations/bling.py

Integração OAuth2 com o Bling (ERP) - fonte do custo de produto pra
cálculo de margem (Fase B). Diferente de integrations/canais/, o Bling
NÃO é um canal de venda - é uma credencial única, compartilhada por toda
a operação (não por conta), por isso a classe abaixo não recebe
conta_id, diferente de MercadoLivreCanal. O token é guardado na mesma
tabela genérica database/tokens_oauth.py, sob a chave fixa CONTA_ID_BLING.

Diferença importante em relação ao fluxo do Mercado Livre
(integrations/canais/mercado_livre.py): a troca do authorization_code
(e a renovação via refresh_token) usa HTTP Basic Auth com
client_id:client_secret em base64 no header Authorization, em vez de
mandar client_id/client_secret no corpo do POST.

Este módulo é a "Parte 1" da integração (bootstrap OAuth + descoberta):
a API v3 do Bling não tem uma referência pública fácil de raspar pra
confirmar com 100% de certeza os nomes exatos de parâmetro/campo -
testar_chamada_real() existe justamente pra ver o JSON de verdade de um
produto (e confirmar o campo de custo) antes de escrever a Parte 2
(tabela de custo + cálculo de margem). Ver o plano da Fase B.
"""

import base64
import json
import secrets
import time
from urllib.parse import urlencode

import requests

from config.settings import BlingConfig, carregar_configuracao_bling
from database.tokens_oauth import obter_token, salvar_token

AUTHORIZE_URL = "https://www.bling.com.br/Api/v3/oauth/authorize"
TOKEN_URL = "https://www.bling.com.br/Api/v3/oauth/token"
BASE_URL = "https://www.bling.com.br/Api/v3"

# Chave fixa em tokens_oauth - o Bling não é uma "conta" de venda, é uma
# credencial única compartilhada por toda a operação.
CONTA_ID_BLING = "bling"

MARGEM_SEGURANCA_SEGUNDOS = 60
MAX_TENTATIVAS_RATE_LIMIT = 5

# Máximo de produtos por página aceito pela API do Bling.
REGISTROS_POR_PAGINA = 100

# Pausa entre páginas, em segundos - o Bling permite até 3 chamadas/segundo;
# margem de segurança bem menor que o limite (mesmo valor já comprovado no
# projeto analista-estoque-ia).
PAUSA_ENTRE_REQUISICOES = 0.4


class BlingClient:
    """Cliente OAuth2 do Bling - credencial única, sem conta_id."""

    def __init__(self):
        self._config: BlingConfig = carregar_configuracao_bling()

    # ------------------------------------------------------------------
    # Fluxo de autorização OAuth2
    # ------------------------------------------------------------------

    def gerar_link_autorizacao(self) -> str:
        """Gera a URL de autorização que deve ser aberta manualmente no navegador."""
        state = secrets.token_urlsafe(16)
        parametros = {
            "response_type": "code",
            "client_id": self._config.client_id,
            "state": state,
        }
        url = f"{AUTHORIZE_URL}?{urlencode(parametros)}"

        print("Abra esta URL no navegador, faça login no Bling e autorize o aplicativo:\n")
        print(url)
        print(
            "\nApós autorizar, o navegador vai tentar carregar a redirect_uri "
            "configurada no app do Bling e provavelmente mostrará erro de página "
            "não encontrada - isso é esperado, pois não há servidor rodando ali. "
            "Copie o valor do parâmetro 'code' que aparece na barra de endereço "
            "(o código expira em poucos minutos, use-o logo em seguida)."
        )
        return url

    def _cabecalho_basic(self) -> dict:
        """
        A troca de code/refresh_token por access_token no Bling usa HTTP
        Basic Auth (client_id:client_secret em base64) no header
        Authorization - diferente do Mercado Livre, que manda essas
        credenciais no corpo do POST.
        """
        credencial = f"{self._config.client_id}:{self._config.client_secret}"
        credencial_b64 = base64.b64encode(credencial.encode("ascii")).decode("ascii")
        return {"Authorization": f"Basic {credencial_b64}", "Accept": "application/json"}

    def trocar_code_por_token(self, authorization_code: str) -> dict:
        """Troca o authorization_code (validade curta) pelos tokens de acesso reais."""
        resposta = requests.post(
            TOKEN_URL,
            headers={**self._cabecalho_basic(), "Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "code": authorization_code,
            },
            timeout=15,
        )

        if resposta.status_code != 200:
            print(f"Erro ao trocar o code por token (status {resposta.status_code}).")
            print(f"Resposta: {resposta.text}")
            print("Verifique se o code não expirou (validade de 1 minuto) e tente gerar um novo link.")
            return {}

        tokens = resposta.json()
        self._salvar_tokens(tokens)

        print("Tokens obtidos e salvos com sucesso.")
        print(f"Tipo do token: {tokens.get('token_type')}")
        print(f"Expira em (segundos): {tokens.get('expires_in')}")
        print(f"Escopos autorizados: {tokens.get('scope')}")
        return tokens

    def testar_chamada_real(self) -> None:
        """Usa o access_token salvo (renovando automaticamente se necessário) pra listar produtos."""
        headers = {"Authorization": f"Bearer {self._token_valido()}"}
        resposta = requests.get(f"{BASE_URL}/produtos", headers=headers, params={"limite": 5}, timeout=15)

        if resposta.status_code != 200:
            print(f"Erro na chamada de teste (status {resposta.status_code}): {resposta.text}")
            return

        corpo = resposta.json()
        produtos = corpo.get("data", [])
        print(f"Chamada realizada com sucesso. {len(produtos)} produto(s) retornado(s) nesta página.")

        for produto in produtos:
            print(f" - {produto.get('codigo', '(sem SKU)')} | {produto.get('nome')} | custo: {produto.get('precoCusto')}")

        if produtos:
            print("\nJSON bruto do primeiro produto:\n")
            print(json.dumps(produtos[0], indent=2, ensure_ascii=False, default=str))

    # ------------------------------------------------------------------
    # Leitura de produtos (fonte do custo por SKU)
    # ------------------------------------------------------------------

    def listar_produtos(self) -> list[dict]:
        """
        Busca todos os produtos cadastrados no Bling, percorrendo todas as
        páginas automaticamente. Cada item traz (entre outros campos)
        'codigo' (SKU), 'nome' e 'precoCusto' - já confirmados via chamada
        real (ver testar_chamada_real()).

        Produtos "pai" (kits/variações, têm idProdutoPai) vêm com
        precoCusto=0 - o custo real fica nas variações filhas. Não filtramos
        isso aqui; quem consome a lista (database/custo_produtos.py) decide
        como tratar custo zero.
        """
        headers = {"Authorization": f"Bearer {self._token_valido()}"}
        todos_os_produtos: list[dict] = []
        pagina = 1

        while True:
            resposta = requests.get(
                f"{BASE_URL}/produtos",
                headers=headers,
                params={"pagina": pagina, "limite": REGISTROS_POR_PAGINA},
                timeout=15,
            )

            if resposta.status_code != 200:
                print(f"Erro ao buscar página {pagina} de produtos (status {resposta.status_code}): {resposta.text}")
                break

            produtos_da_pagina = resposta.json().get("data", [])
            todos_os_produtos.extend(produtos_da_pagina)

            if len(produtos_da_pagina) < REGISTROS_POR_PAGINA:
                break

            pagina += 1
            time.sleep(PAUSA_ENTRE_REQUISICOES)

        return todos_os_produtos

    # ------------------------------------------------------------------
    # Leitura de pedidos de venda (cruzamento com o pedido do Mercado Livre)
    # ------------------------------------------------------------------

    def listar_pedidos_vendas(self, data_inicial: str, data_final: str) -> list[dict]:
        """
        Busca os pedidos de venda do Bling criados entre data_inicial e
        data_final (ambos 'AAAA-MM-DD', inclusive), percorrendo todas as
        páginas. Cada pedido traz (confirmado via chamada real) 'numero'
        (número simples do Bling, ex: 51208) e 'numeroLoja' - quando o
        pedido veio da integração automática Mercado Livre → Bling,
        'numeroLoja' é exatamente o mesmo pedido_id que já usamos (ex:
        "2000014521882473"); pedidos de outros canais ou lançados
        manualmente têm outro formato (ou 'numeroLoja' vazio) e
        simplesmente não vão casar com nenhum item_venda nosso - sem
        risco de casamento errado, já que a comparação é exata.
        """
        headers = {"Authorization": f"Bearer {self._token_valido()}"}
        todos_os_pedidos: list[dict] = []
        pagina = 1

        while True:
            resposta = requests.get(
                f"{BASE_URL}/pedidos/vendas",
                headers=headers,
                params={
                    "pagina": pagina,
                    "limite": REGISTROS_POR_PAGINA,
                    "dataInicial": data_inicial,
                    "dataFinal": data_final,
                },
                timeout=15,
            )

            if resposta.status_code != 200:
                print(f"Erro ao buscar página {pagina} de pedidos de venda (status {resposta.status_code}): {resposta.text}")
                break

            pedidos_da_pagina = resposta.json().get("data", [])
            todos_os_pedidos.extend(pedidos_da_pagina)

            if len(pedidos_da_pagina) < REGISTROS_POR_PAGINA:
                break

            pagina += 1
            time.sleep(PAUSA_ENTRE_REQUISICOES)

        return todos_os_pedidos

    # ------------------------------------------------------------------
    # Gerenciamento de token (mesmo padrão de MercadoLivreCanal)
    # ------------------------------------------------------------------

    def _salvar_tokens(self, tokens: dict) -> None:
        salvar_token(CONTA_ID_BLING, {**tokens, "obtido_em": time.time()})

    def _token_expirado(self, tokens: dict) -> bool:
        obtido_em = tokens.get("obtido_em", 0)
        expires_in = tokens.get("expires_in", 0)
        expira_em = obtido_em + expires_in
        return time.time() >= (expira_em - MARGEM_SEGURANCA_SEGUNDOS)

    def _renovar_tokens(self, refresh_token: str) -> dict:
        resposta = requests.post(
            TOKEN_URL,
            headers={**self._cabecalho_basic(), "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            timeout=15,
        )

        if resposta.status_code != 200:
            raise RuntimeError(f"Falha ao renovar o token do Bling (status {resposta.status_code}): {resposta.text}")

        novos_tokens = resposta.json()
        self._salvar_tokens(novos_tokens)
        return novos_tokens

    def _token_valido(self) -> str:
        tokens = obter_token(CONTA_ID_BLING)

        if not tokens:
            raise RuntimeError(
                "Nenhum token do Bling salvo. Rode 'python main.py bling_passo1' e "
                "'python main.py bling_passo2 <code>' primeiro."
            )

        if self._token_expirado(tokens):
            print("Access token do Bling expirado ou perto de expirar - renovando...")
            tokens = self._renovar_tokens(tokens["refresh_token"])
            print("Token renovado com sucesso.")

        return tokens["access_token"]
