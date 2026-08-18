"""
integrations/canais/mercado_livre.py

Adaptador do canal Mercado Livre - implementa a interface comum de canais
(integrations/canais/__init__.py). Substitui os antigos integrations/
ml_auth.py + integrations/ml_client.py, agora organizados como uma classe:
cada instância representa UMA conta específica (ex: "hc"), com suas
próprias credenciais (config/settings.py::carregar_configuracao_ml) e seu
próprio token OAuth (guardado no Turso via database/tokens_oauth.py, não
mais num arquivo local - importante pra funcionar tanto na coleta local
quanto numa futura automação rodando na nuvem).
"""

import secrets
import time
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

import requests

from config.settings import MercadoLivreConfig, carregar_configuracao_ml
from database.tokens_oauth import obter_token, salvar_token

AUTHORIZE_URL = "https://auth.mercadolivre.com.br/authorization"
TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
BASE_URL = "https://api.mercadolibre.com"

# A API do Mercado Livre limita a 20 ids por chamada nos endpoints multiget (itens).
TAMANHO_LOTE = 20

# Pausa entre cada chamada de /items/{id}/visits (feita 1 item por vez) para
# não estourar o rate limit da API em coletas grandes.
PAUSA_ENTRE_VISITAS_SEGUNDOS = 0.3

MAX_TENTATIVAS_RATE_LIMIT = 5

# Margem de segurança: renovamos o token um pouco antes dele expirar de
# verdade, para nunca correr o risco de uma chamada cair bem no instante da
# expiração.
MARGEM_SEGURANCA_SEGUNDOS = 60

# Fuso usado pelo Mercado Livre no campo date_created dos pedidos desse site
# (MLB) - confirmado empiricamente (7 pedidos reais checados, todos com
# offset "-04:00", inclusive fora do horário de verão). Usar "-00:00" (UTC)
# aqui causava um bug real: pedidos das 21h-23h59 (nesse fuso) do dia D
# apareciam na janela de coleta do dia D+1, porque a diferença de 4h
# empurrava o timestamp UTC pro dia seguinte.
FUSO_DATE_CREATED_PEDIDOS = "-04:00"


def _em_lotes(itens: list, tamanho: int = TAMANHO_LOTE):
    for i in range(0, len(itens), tamanho):
        yield itens[i:i + tamanho]


class MercadoLivreCanal:
    """Adaptador do Mercado Livre para uma conta específica."""

    def __init__(self, conta_id: str):
        self.conta_id = conta_id
        self._config: MercadoLivreConfig = carregar_configuracao_ml(conta_id)

    # ------------------------------------------------------------------
    # Fluxo de autorização OAuth2 (equivalente ao antigo ml_auth.py)
    # ------------------------------------------------------------------

    def gerar_link_autorizacao(self) -> str:
        """Gera a URL de autorização que deve ser aberta manualmente no navegador."""
        # 'state' é um valor aleatório usado para confirmar que o retorno do
        # Mercado Livre corresponde a esta mesma solicitação (proteção contra CSRF).
        state = secrets.token_urlsafe(16)
        parametros = {
            "response_type": "code",
            "client_id": self._config.client_id,
            "redirect_uri": self._config.redirect_uri,
            "state": state,
        }
        url = f"{AUTHORIZE_URL}?{urlencode(parametros)}"

        print(f"[conta: {self.conta_id}] Abra esta URL no navegador, faça login no Mercado "
              "Livre e autorize o aplicativo:\n")
        print(url)
        print(
            "\nApós autorizar, o navegador vai tentar carregar a redirect_uri "
            "configurada e provavelmente mostrará erro de página não encontrada "
            "- isso é esperado, pois não há servidor rodando ali. "
            "Copie o valor do parâmetro 'code' que aparece na barra de endereço "
            "(o código expira em poucos minutos, use-o logo em seguida)."
        )
        return url

    def trocar_code_por_token(self, authorization_code: str) -> dict:
        """Troca o authorization_code (validade curta) pelos tokens de acesso reais."""
        dados = {
            "grant_type": "authorization_code",
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
            "code": authorization_code,
            "redirect_uri": self._config.redirect_uri,
        }

        resposta = requests.post(TOKEN_URL, data=dados, timeout=15)

        if resposta.status_code != 200:
            print(f"Erro ao trocar o code por token (status {resposta.status_code}).")
            print(f"Resposta: {resposta.text}")
            print("Verifique se o code não expirou e tente gerar um novo link.")
            return {}

        tokens = resposta.json()
        self._salvar_tokens(tokens)

        print("Tokens obtidos e salvos com sucesso.")
        print(f"Tipo do token: {tokens.get('token_type')}")
        print(f"Expira em (segundos): {tokens.get('expires_in')}")
        print(f"Escopos autorizados: {tokens.get('scope')}")
        print(f"User ID do vendedor: {tokens.get('user_id')}")
        return tokens

    def testar_chamada_real(self) -> None:
        """Usa o access_token salvo (renovando automaticamente se necessário) pra uma chamada de teste."""
        headers = {"Authorization": f"Bearer {self._token_valido()}"}
        resposta = requests.get(f"{BASE_URL}/users/me", headers=headers, timeout=15)

        if resposta.status_code != 200:
            print(f"Erro na chamada de teste (status {resposta.status_code}): {resposta.text}")
            return

        usuario = resposta.json()
        print("Chamada realizada com sucesso.")
        print(f"Conta: {usuario.get('nickname')} (id {usuario.get('id')})")
        print(f"Site: {usuario.get('site_id')}")

    def testar_chamada_advertising(self) -> None:
        """
        Verifica se a permissão de Advertising (Mercado Ads/Product Ads) está
        liberada pra essa conta - é um escopo separado da API core, precisa
        ser habilitado à parte no painel do Mercado Livre Developers. Usa o
        mesmo access_token da API core (a API de Advertising não tem OAuth
        próprio), só chama um endpoint diferente.
        """
        headers = {**self._cabecalho(), "Api-Version": "1"}
        resposta = requests.get(f"{BASE_URL}/advertising/advertisers", headers=headers,
                                 params={"product_id": "PADS"}, timeout=15)

        if resposta.status_code in (401, 403):
            print(f"[conta: {self.conta_id}] Permissão de Advertising NÃO liberada "
                  f"(status {resposta.status_code}). Resposta: {resposta.text}")
            print("Solicite a permissão 'Advertising' no painel do Mercado Livre "
                  "Developers para o app dessa conta antes de continuar.")
            return

        if resposta.status_code != 200:
            print(f"[conta: {self.conta_id}] Erro inesperado ao consultar Advertising "
                  f"(status {resposta.status_code}): {resposta.text}")
            return

        corpo = resposta.json()
        advertisers = corpo.get("advertisers", corpo if isinstance(corpo, list) else [])
        print(f"[conta: {self.conta_id}] Permissão de Advertising liberada.")
        print(f"Advertiser(s) encontrado(s): {advertisers}")

    def _salvar_tokens(self, tokens: dict) -> None:
        """Salva os tokens no banco, incluindo o horário em que foram obtidos."""
        salvar_token(self.conta_id, {**tokens, "obtido_em": time.time()})

    def _token_expirado(self, tokens: dict) -> bool:
        obtido_em = tokens.get("obtido_em", 0)
        expires_in = tokens.get("expires_in", 0)
        expira_em = obtido_em + expires_in
        return time.time() >= (expira_em - MARGEM_SEGURANCA_SEGUNDOS)

    def _renovar_tokens(self, refresh_token: str) -> dict:
        """
        Troca um refresh_token por um novo par access_token/refresh_token.

        Importante: o Mercado Livre invalida o refresh_token antigo a cada
        renovação e devolve um novo. Por isso sempre salvamos o resultado
        imediatamente - se perdermos esse novo refresh_token, o antigo já
        não funciona mais.
        """
        dados = {
            "grant_type": "refresh_token",
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
            "refresh_token": refresh_token,
        }
        resposta = requests.post(TOKEN_URL, data=dados, timeout=15)

        if resposta.status_code != 200:
            raise RuntimeError(f"Falha ao renovar o token (status {resposta.status_code}): {resposta.text}")

        novos_tokens = resposta.json()
        self._salvar_tokens(novos_tokens)
        return novos_tokens

    def _token_valido(self) -> str:
        """Ponto único de acesso a um access_token garantidamente válido pra essa conta."""
        tokens = obter_token(self.conta_id)

        if not tokens:
            raise RuntimeError(
                f"Nenhum token salvo pra conta '{self.conta_id}'. Rode "
                "'python main.py passo1 <conta_id>' e 'python main.py passo2 <conta_id> <code>' primeiro."
            )

        if self._token_expirado(tokens):
            print(f"[conta: {self.conta_id}] Access token expirado ou perto de expirar - renovando...")
            tokens = self._renovar_tokens(tokens["refresh_token"])
            print("Token renovado com sucesso.")

        return tokens["access_token"]

    def obter_id_vendedor(self) -> str:
        """Retorna o user_id do vendedor associado ao token salvo dessa conta."""
        tokens = obter_token(self.conta_id)
        if not tokens or "user_id" not in tokens:
            raise RuntimeError(
                f"user_id não encontrado nos tokens salvos da conta '{self.conta_id}'. "
                "Rode o fluxo de autorização novamente."
            )
        return str(tokens["user_id"])

    # ------------------------------------------------------------------
    # Chamadas de leitura à API (equivalente ao antigo ml_client.py)
    # ------------------------------------------------------------------

    def _cabecalho(self) -> dict:
        return {"Authorization": f"Bearer {self._token_valido()}"}

    def _get_com_retry(
        self, url: str, params: dict, timeout: int = 15, headers_extra: dict | None = None
    ) -> requests.Response:
        """
        GET com retry automático em caso de rate limit (429) ou erro
        temporário do servidor (5xx): espera o tempo indicado em
        'Retry-After' (ou um backoff crescente) e tenta de novo, em vez de
        derrubar o script inteiro. `headers_extra` complementa (não
        substitui) o cabeçalho de autenticação - usado por endpoints que
        exigem um header extra, como 'api-version' na API de Ads.
        """
        headers = {**self._cabecalho(), **(headers_extra or {})}
        for tentativa in range(MAX_TENTATIVAS_RATE_LIMIT):
            resposta = requests.get(url, headers=headers, params=params, timeout=timeout)
            if resposta.status_code != 429 and resposta.status_code < 500:
                return resposta

            espera = int(resposta.headers.get("Retry-After", 2 ** (tentativa + 1)))
            print(f"Erro temporário da API do Mercado Livre ({resposta.status_code}). "
                  f"Aguardando {espera}s antes de tentar de novo...")
            time.sleep(espera)

        return resposta

    def _listar_itens_ativos(self, seller_id: str) -> list[str]:
        ids: list[str] = []
        offset = 0
        limite = 100

        while True:
            resposta = self._get_com_retry(
                f"{BASE_URL}/users/{seller_id}/items/search",
                params={"status": "active", "limit": limite, "offset": offset},
            )
            resposta.raise_for_status()
            corpo = resposta.json()

            pagina = corpo.get("results", [])
            ids.extend(pagina)

            total = corpo.get("paging", {}).get("total", 0)
            offset += limite
            if offset >= total or not pagina:
                break

        return ids

    def _obter_detalhes_itens(self, item_ids: list[str]) -> list[dict]:
        detalhes: list[dict] = []
        for lote in _em_lotes(item_ids):
            resposta = self._get_com_retry(f"{BASE_URL}/items", params={"ids": ",".join(lote)})
            resposta.raise_for_status()
            for entrada in resposta.json():
                if entrada.get("code") == 200:
                    detalhes.append(entrada["body"])
        return detalhes

    def _obter_visitas_itens(self, item_ids: list[str], data_de: str, data_ate: str) -> dict[str, int]:
        """
        data_de/data_ate no formato 'YYYY-MM-DD' (só a data, sem hora).

        Importante: o endpoint /visits/items (multiget) IGNORA o filtro de
        data e sempre devolve o total acumulado desde a criação do anúncio -
        por isso usamos /items/{item_id}/visits, que é por item (só aceita 1
        de cada vez) e realmente respeita date_from/date_to. date_to é
        exclusivo (vai até o início do dia de date_to, não até o fim dele).
        """
        visitas: dict[str, int] = {}
        for item_id in item_ids:
            resposta = self._get_com_retry(
                f"{BASE_URL}/items/{item_id}/visits",
                params={"date_from": data_de, "date_to": data_ate},
            )
            resposta.raise_for_status()
            visitas[item_id] = resposta.json().get("total_visits", 0)
            time.sleep(PAUSA_ENTRE_VISITAS_SEGUNDOS)
        return visitas

    def _obter_pedidos_periodo(
        self, seller_id: str, data_de: str, data_ate: str, status: str | None = "paid"
    ) -> list[dict]:
        """
        data_de/data_ate no formato 'YYYY-MM-DDTHH:MM:SS.000-00:00' (ISO 8601).

        status=None omite o filtro 'order.status' e traz pedidos de QUALQUER
        status criados na janela (confirmado ao vivo: omitir o parâmetro
        retorna o mesmo total que somar as buscas por status individual,
        incluindo 'cancelled') - usado por coletar_extrato_do_dia, que
        precisa ver pedidos ainda não pagos pra não perdê-los depois.
        """
        pedidos: list[dict] = []
        offset = 0
        limite = 50

        params_base = {
            "seller": seller_id,
            "order.date_created.from": data_de,
            "order.date_created.to": data_ate,
            "limit": limite,
        }
        if status is not None:
            params_base["order.status"] = status

        while True:
            resposta = self._get_com_retry(
                f"{BASE_URL}/orders/search",
                params={**params_base, "offset": offset},
            )
            resposta.raise_for_status()
            corpo = resposta.json()

            pagina = corpo.get("results", [])
            pedidos.extend(pagina)

            total = corpo.get("paging", {}).get("total", 0)
            offset += limite
            if offset >= total or not pagina:
                break

        return pedidos

    def _obter_status_envio(self, shipping_id: int) -> dict:
        """
        GET /shipments/{id} - o /orders/search só devolve o id do envio, não
        o status; o status/substatus/tipo logístico vêm dessa chamada
        separada, uma por pedido (volume diário baixo o suficiente pra não
        precisar de lote/throttle como em _obter_visitas_itens).
        """
        resposta = self._get_com_retry(f"{BASE_URL}/shipments/{shipping_id}", params={})
        resposta.raise_for_status()
        corpo = resposta.json()
        return {
            "status_envio": corpo.get("status"),
            "substatus_envio": corpo.get("substatus"),
            "logistic_type": corpo.get("logistic_type"),
        }

    def _obter_custo_frete_vendedor(self, shipping_id: int) -> float:
        """
        GET /shipments/{id}/costs - retorna o custo do frete separado por
        quem paga (senders = vendedor, receiver = comprador). Diferente do
        'shipping_option.cost' do endpoint de status (esse é o valor pago
        pelo comprador) - aqui pegamos o que sai do bolso do vendedor,
        somando todos os 'senders' (normalmente só 1).
        """
        resposta = self._get_com_retry(f"{BASE_URL}/shipments/{shipping_id}/costs", params={})
        resposta.raise_for_status()
        corpo = resposta.json()
        return sum(sender.get("cost", 0.0) for sender in corpo.get("senders", []))

    # ------------------------------------------------------------------
    # Interface comum de canal
    # ------------------------------------------------------------------

    def coletar_dados_do_dia(self, dia: date) -> list[dict]:
        """Busca anúncios ativos, visitas e vendas de um dia calendário completo, pra essa conta."""
        seller_id = self.obter_id_vendedor()

        item_ids = self._listar_itens_ativos(seller_id)
        print(f"[conta: {self.conta_id}] {len(item_ids)} anúncio(s) ativo(s) encontrado(s).")

        detalhes = self._obter_detalhes_itens(item_ids)

        visitas_data_de = dia.isoformat()
        visitas_data_ate = (dia + timedelta(days=1)).isoformat()
        pedidos_data_de = f"{dia.isoformat()}T00:00:00.000{FUSO_DATE_CREATED_PEDIDOS}"
        pedidos_data_ate = f"{dia.isoformat()}T23:59:59.000{FUSO_DATE_CREATED_PEDIDOS}"

        visitas_por_item = self._obter_visitas_itens(item_ids, visitas_data_de, visitas_data_ate)
        pedidos = self._obter_pedidos_periodo(seller_id, pedidos_data_de, pedidos_data_ate)

        vendas_por_item: dict[str, dict] = {}
        for pedido in pedidos:
            for item in pedido.get("order_items", []):
                item_id = str(item.get("item", {}).get("id"))
                quantidade = item.get("quantity", 0)
                valor = item.get("unit_price", 0) * quantidade
                registro = vendas_por_item.setdefault(item_id, {"quantidade": 0, "receita": 0.0})
                registro["quantidade"] += quantidade
                registro["receita"] += valor

        dados_anuncios = []
        for item in detalhes:
            item_id = str(item["id"])
            vendas = vendas_por_item.get(item_id, {"quantidade": 0, "receita": 0.0})
            dados_anuncios.append({
                "item_id": item_id,
                "titulo": item.get("title", ""),
                "sku": item.get("seller_custom_field") or "",
                "visitas": visitas_por_item.get(item_id, 0),
                "vendas_quantidade": vendas["quantidade"],
                "receita": vendas["receita"],
            })

        return dados_anuncios

    def coletar_pedidos_do_dia(self, dia: date) -> list[dict]:
        """
        Busca os pedidos pagos de um dia calendário completo e o status de
        envio de cada um, pra essa conta. Retorna uma lista de dicionários
        com as chaves: pedido_id, status_envio, substatus_envio,
        logistic_type, valor_total - formato que
        database/pedidos.py::salvar_pedidos_do_dia() espera.
        """
        seller_id = self.obter_id_vendedor()

        pedidos_data_de = f"{dia.isoformat()}T00:00:00.000{FUSO_DATE_CREATED_PEDIDOS}"
        pedidos_data_ate = f"{dia.isoformat()}T23:59:59.000{FUSO_DATE_CREATED_PEDIDOS}"
        pedidos = self._obter_pedidos_periodo(seller_id, pedidos_data_de, pedidos_data_ate)

        resultado = []
        for pedido in pedidos:
            shipping_id = pedido.get("shipping", {}).get("id")
            status_envio = self._obter_status_envio(shipping_id) if shipping_id else {}
            resultado.append({
                "pedido_id": str(pedido["id"]),
                "valor_total": pedido.get("total_amount", 0.0),
                **status_envio,
            })

        return resultado

    # Tags do Mercado Livre que indicam reclamação/mediação em andamento -
    # pedido segue com status "paid", mas pode terminar em reembolso parcial
    # que este código não sabe calcular. Lista curta e best-effort: nenhum
    # pedido real com esse caso apareceu ainda pra confirmar o nome exato
    # (ver nota em coletar_extrato_do_dia) - se um caso real aparecer e a
    # tag não bater, é o primeiro lugar a revisar.
    _TAGS_RECLAMACAO = {"mediation", "fraud_risk_detected", "claim"}

    def coletar_extrato_do_dia(self, dia: date) -> list[dict]:
        """
        Busca os pedidos de um dia calendário completo (de QUALQUER status -
        confirmado ao vivo que omitir 'order.status' traz o mesmo total que
        somar as buscas por status individual) e monta uma linha por item
        vendido (SKU), com os valores brutos necessários pro cálculo de
        margem em database/extrato.py: preço de venda, comissão do Mercado
        Livre e frete pago pelo vendedor.

        Cada linha carrega o status real do pedido, mapeado para:
        - "pago": status "paid" - conta na margem.
        - "cancelado": status "cancelled" - valores zerados, aparece no
          extrato pra não sumir silenciosamente (o vendedor via essa venda
          na tela "Anúncios" do próprio Mercado Livre), mas não conta em
          nenhum total.
        - "pendente": qualquer outro status (aguardando pagamento, boleto
          não compensado etc.) - valores zerados, não conta em nenhum
          total, mas fica visível. Como a rotina diária reprocessa uma
          janela dos últimos dias (não só ontem - ver main.py), um pedido
          "pendente" que confirme o pagamento depois é corrigido pra
          "pago" automaticamente na próxima rodada que reprocessar aquele
          dia, sem precisar de nenhuma ação manual. Antes desta mudança, um
          pedido que só confirmava pagamento 1+ dia depois de criado
          simplesmente nunca era visto (a busca só olhava status=paid do
          dia seguinte), e a venda sumia do extrato pra sempre.

        Pedidos com tag de reclamação/mediação (ver _TAGS_RECLAMACAO) ficam
        marcados com status "pago_com_reclamacao" em vez de "pago" - os
        valores continuam os do pedido original (não sabemos o valor exato
        de um eventual reembolso parcial), servindo só de sinalização
        visual pra revisão manual, não de cálculo automático.

        'sale_fee' é tratado aqui como valor POR UNIDADE (mesma convenção
        de 'unit_price') - ainda sem um pedido real com quantity > 1 pra
        confirmar isso com certeza; quando isso acontece de verdade, um
        aviso é impresso no console (ver abaixo) em vez de assumir em
        silêncio.

        Quando um pedido tem mais de 1 item compartilhando o mesmo envio, o
        custo de frete do pedido é rateado proporcionalmente ao valor de
        venda de cada item - ou dividido igualmente se todos os itens do
        pedido tiverem preço 0 (senão o frete inteiro desaparecia sem ser
        alocado a nenhum item).
        """
        seller_id = self.obter_id_vendedor()

        pedidos_data_de = f"{dia.isoformat()}T00:00:00.000{FUSO_DATE_CREATED_PEDIDOS}"
        pedidos_data_ate = f"{dia.isoformat()}T23:59:59.000{FUSO_DATE_CREATED_PEDIDOS}"
        pedidos = self._obter_pedidos_periodo(seller_id, pedidos_data_de, pedidos_data_ate, status=None)

        resultado = []
        for pedido in pedidos:
            itens = pedido.get("order_items", [])
            if not itens:
                continue

            status_ml = pedido.get("status")
            if status_ml == "paid":
                tags = set(pedido.get("tags") or [])
                status = "pago_com_reclamacao" if tags & self._TAGS_RECLAMACAO else "pago"
            elif status_ml == "cancelled":
                status = "cancelado"
            else:
                status = "pendente"

            if status in ("cancelado", "pendente"):
                for item in itens:
                    resultado.append({
                        "pedido_id": str(pedido["id"]),
                        "item_id": str(item.get("item", {}).get("id")),
                        "sku": item.get("item", {}).get("seller_sku") or "",
                        "titulo": item.get("item", {}).get("title", ""),
                        "quantidade": item.get("quantity", 0),
                        "preco_venda": 0.0,
                        "comissao_ml": 0.0,
                        "frete_vendedor": 0.0,
                        "status": status,
                    })
                continue

            shipping_id = pedido.get("shipping", {}).get("id")
            frete_pedido = self._obter_custo_frete_vendedor(shipping_id) if shipping_id else 0.0

            precos_dos_itens = [item.get("unit_price", 0) * item.get("quantity", 0) for item in itens]
            soma_precos = sum(precos_dos_itens)

            for item, preco_item in zip(itens, precos_dos_itens):
                quantidade = item.get("quantity", 0)
                if quantidade > 1:
                    print(
                        f"[conta: {self.conta_id}] Pedido {pedido['id']} tem item com quantidade={quantidade} - "
                        "comissão (sale_fee) tratada como valor por unidade, assumção ainda não confirmada "
                        "contra um caso real. Revisar a margem desse pedido manualmente."
                    )
                if soma_precos:
                    frete_alocado = frete_pedido * (preco_item / soma_precos)
                else:
                    frete_alocado = frete_pedido / len(itens)
                resultado.append({
                    "pedido_id": str(pedido["id"]),
                    "item_id": str(item.get("item", {}).get("id")),
                    "sku": item.get("item", {}).get("seller_sku") or "",
                    "titulo": item.get("item", {}).get("title", ""),
                    "quantidade": quantidade,
                    "preco_venda": preco_item,
                    "comissao_ml": item.get("sale_fee", 0.0) * quantidade,
                    "frete_vendedor": frete_alocado,
                    "status": status,
                })

        return resultado

    # ------------------------------------------------------------------
    # Publicidade (Mercado Ads / Product Ads)
    # ------------------------------------------------------------------

    def _obter_advertiser_id(self) -> tuple[int, str] | None:
        """
        GET /advertising/advertisers - retorna (advertiser_id, site_id) da
        conta pra Product Ads (product_id=PADS), ou None se a conta não
        tiver a permissão de Advertising liberada (não é erro - permite
        contas futuras sem esse produto habilitado sem quebrar a rotina).
        """
        headers = {**self._cabecalho(), "Api-Version": "1"}
        resposta = requests.get(
            f"{BASE_URL}/advertising/advertisers", headers=headers, params={"product_id": "PADS"}, timeout=15
        )
        if resposta.status_code != 200:
            return None

        corpo = resposta.json()
        advertisers = corpo.get("advertisers", corpo if isinstance(corpo, list) else [])
        for anunciante in advertisers:
            if anunciante.get("site_id") == "MLB":
                return anunciante["advertiser_id"], "MLB"
        return None

    # Lista completa de métricas documentadas pra campanhas/anúncios -
    # pedidas sempre juntas, pra guardar o máximo de dado possível de uma
    # vez (alinhado com o usuário) sem múltiplas chamadas por métrica.
    _METRICAS_ADS = (
        "clicks,prints,ctr,cost,cpc,acos,cvr,roas,"
        "direct_amount,indirect_amount,total_amount,"
        "direct_units_quantity,indirect_units_quantity,units_quantity"
    )

    def coletar_campanhas_ads_do_dia(self, dia: date) -> list[dict]:
        """
        Busca as campanhas de Product Ads e suas métricas de um dia
        calendário completo (date_from == date_to), pra essa conta. Retorna
        [] se a conta não tiver Advertising liberado.
        """
        advertiser = self._obter_advertiser_id()
        if advertiser is None:
            return []
        advertiser_id, site_id = advertiser

        resultado: list[dict] = []
        offset = 0
        limite = 50
        while True:
            resposta = self._get_com_retry(
                f"{BASE_URL}/advertising/{site_id}/advertisers/{advertiser_id}/product_ads/campaigns/search",
                params={
                    "limit": limite, "offset": offset,
                    "date_from": dia.isoformat(), "date_to": dia.isoformat(),
                    "metrics": self._METRICAS_ADS,
                },
                headers_extra={"api-version": "2"},
            )
            resposta.raise_for_status()
            corpo = resposta.json()
            pagina = corpo.get("results", [])

            for campanha in pagina:
                metricas = campanha.get("metrics", {})
                resultado.append({
                    "campaign_id": campanha["id"],
                    "nome": campanha.get("name", ""),
                    "status": campanha.get("status", ""),
                    "strategy": campanha.get("strategy", ""),
                    "budget": campanha.get("budget", 0.0),
                    "acos_target": campanha.get("acos_target"),
                    "roas_target": campanha.get("roas_target"),
                    "clicks": metricas.get("clicks", 0),
                    "prints": metricas.get("prints", 0),
                    "cost": metricas.get("cost", 0.0),
                    "cpc": metricas.get("cpc", 0.0),
                    "ctr": metricas.get("ctr", 0.0),
                    "acos": metricas.get("acos", 0.0),
                    "cvr": metricas.get("cvr", 0.0),
                    "roas": metricas.get("roas", 0.0),
                    "direct_amount": metricas.get("direct_amount", 0.0),
                    "indirect_amount": metricas.get("indirect_amount", 0.0),
                    "total_amount": metricas.get("total_amount", 0.0),
                    "direct_units_quantity": metricas.get("direct_units_quantity", 0),
                    "indirect_units_quantity": metricas.get("indirect_units_quantity", 0),
                    "units_quantity": metricas.get("units_quantity", 0),
                })

            total = corpo.get("paging", {}).get("total", 0)
            offset += limite
            if offset >= total or not pagina:
                break

        return resultado

    def coletar_anuncios_ads_do_dia(self, dia: date) -> list[dict]:
        """
        Busca os anúncios em Product Ads (ativos/pausados - ignora
        'idle'/'hold'/'delegated'/'revoked', que não têm métrica nenhuma)
        e suas métricas de um dia calendário completo, pra essa conta.
        Retorna [] se a conta não tiver Advertising liberado.
        """
        advertiser = self._obter_advertiser_id()
        if advertiser is None:
            return []
        advertiser_id, site_id = advertiser

        resultado: list[dict] = []
        offset = 0
        limite = 50
        while True:
            resposta = self._get_com_retry(
                f"{BASE_URL}/advertising/{site_id}/advertisers/{advertiser_id}/product_ads/ads/search",
                params={
                    "limit": limite, "offset": offset,
                    "date_from": dia.isoformat(), "date_to": dia.isoformat(),
                    "metrics": self._METRICAS_ADS,
                    "filters[statuses]": "active,paused",
                },
                headers_extra={"api-version": "2"},
            )
            resposta.raise_for_status()
            corpo = resposta.json()
            pagina = corpo.get("results", [])

            for anuncio in pagina:
                metricas = anuncio.get("metrics", {})
                resultado.append({
                    "item_id": anuncio.get("item_id", ""),
                    "campaign_id": anuncio.get("campaign_id"),
                    "titulo": anuncio.get("title", ""),
                    "status": anuncio.get("status", ""),
                    "clicks": metricas.get("clicks", 0),
                    "prints": metricas.get("prints", 0),
                    "cost": metricas.get("cost", 0.0),
                    "cpc": metricas.get("cpc", 0.0),
                    "acos": metricas.get("acos", 0.0),
                    "direct_amount": metricas.get("direct_amount", 0.0),
                    "indirect_amount": metricas.get("indirect_amount", 0.0),
                    "total_amount": metricas.get("total_amount", 0.0),
                    "units_quantity": metricas.get("units_quantity", 0),
                })

            total = corpo.get("paging", {}).get("total", 0)
            offset += limite
            if offset >= total or not pagina:
                break

        return resultado
