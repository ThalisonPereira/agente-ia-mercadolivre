"""
integrations/ml_client.py

Chamadas de leitura à API do Mercado Livre necessárias para a rotina diária:
lista de anúncios ativos, detalhes de cada anúncio, pedidos do período e
visitas por anúncio.

Todas as funções usam o access_token válido fornecido por
integrations.ml_auth.obter_access_token_valido() - nenhuma delas lida com
autenticação diretamente.
"""
import time

import requests

from integrations.ml_auth import obter_access_token_valido

BASE_URL = "https://api.mercadolibre.com"

# A API do Mercado Livre limita a 20 ids por chamada nos endpoints multiget
# (itens e visitas).
TAMANHO_LOTE = 20

# Pausa entre cada chamada de /items/{id}/visits (feita 1 item por vez) para
# não estourar o rate limit da API em coletas grandes (ex: backfill de vários
# dias, com centenas de chamadas seguidas).
PAUSA_ENTRE_VISITAS_SEGUNDOS = 0.3

MAX_TENTATIVAS_RATE_LIMIT = 5


def _cabecalho() -> dict:
    return {"Authorization": f"Bearer {obter_access_token_valido()}"}


def _em_lotes(itens: list, tamanho: int = TAMANHO_LOTE):
    for i in range(0, len(itens), tamanho):
        yield itens[i:i + tamanho]


def _get_com_retry(url: str, headers: dict, params: dict, timeout: int = 15) -> requests.Response:
    """
    GET com retry automático em caso de rate limit (429) ou erro temporário
    do servidor (5xx: 500, 502, 503, 504): espera o tempo indicado em
    'Retry-After' (ou um backoff crescente, se o cabeçalho não vier) e tenta
    de novo, em vez de derrubar o script inteiro.
    """
    for tentativa in range(MAX_TENTATIVAS_RATE_LIMIT):
        resposta = requests.get(url, headers=headers, params=params, timeout=timeout)
        if resposta.status_code != 429 and resposta.status_code < 500:
            return resposta

        espera = int(resposta.headers.get("Retry-After", 2 ** (tentativa + 1)))
        print(f"Erro temporário da API do Mercado Livre ({resposta.status_code}). "
              f"Aguardando {espera}s antes de tentar de novo...")
        time.sleep(espera)

    return resposta


def listar_itens_ativos(seller_id: str) -> list[str]:
    """Retorna os ids de todos os anúncios ativos do vendedor."""
    ids: list[str] = []
    offset = 0
    limite = 100

    while True:
        resposta = _get_com_retry(
            f"{BASE_URL}/users/{seller_id}/items/search",
            headers=_cabecalho(),
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


def obter_detalhes_itens(item_ids: list[str]) -> list[dict]:
    """
    Retorna título, preço, quantidade vendida e status de cada item, em lotes
    de até 20 ids por chamada (limite da API).
    """
    detalhes: list[dict] = []

    for lote in _em_lotes(item_ids):
        resposta = _get_com_retry(
            f"{BASE_URL}/items",
            headers=_cabecalho(),
            params={"ids": ",".join(lote)},
        )
        resposta.raise_for_status()

        for entrada in resposta.json():
            if entrada.get("code") == 200:
                detalhes.append(entrada["body"])

    return detalhes


def obter_visitas_itens(item_ids: list[str], data_de: str, data_ate: str) -> dict[str, int]:
    """
    Retorna o total de visitas por item no período informado.

    data_de/data_ate no formato 'YYYY-MM-DD' (só a data, sem hora).

    Importante: o endpoint /visits/items (multiget) IGNORA o filtro de data e
    sempre devolve o total acumulado desde a criação do anúncio - por isso
    usamos aqui /items/{item_id}/visits, que é por item (só aceita 1 de cada
    vez de qualquer forma) e realmente respeita date_from/date_to. Esse
    endpoint só aceita data pura (sem hora/offset) - qualquer outro formato
    retorna 400 "Invalid request unknown date format".

    date_to é exclusivo (o período vai até o início do dia de date_to, não
    até o fim dele) - por isso, para cobrir o dia D inteiro, data_ate deve
    ser o dia seguinte a D.

    Retorna um dicionário {item_id: total_visitas}.
    """
    visitas: dict[str, int] = {}

    for item_id in item_ids:
        resposta = _get_com_retry(
            f"{BASE_URL}/items/{item_id}/visits",
            headers=_cabecalho(),
            params={"date_from": data_de, "date_to": data_ate},
        )
        resposta.raise_for_status()
        visitas[item_id] = resposta.json().get("total_visits", 0)
        time.sleep(PAUSA_ENTRE_VISITAS_SEGUNDOS)

    return visitas


def obter_pedidos_periodo(seller_id: str, data_de: str, data_ate: str) -> list[dict]:
    """
    Retorna todos os pedidos pagos do vendedor criados no período informado.

    data_de/data_ate no formato 'YYYY-MM-DDTHH:MM:SS.000-00:00' (ISO 8601).
    """
    pedidos: list[dict] = []
    offset = 0
    limite = 50

    while True:
        resposta = _get_com_retry(
            f"{BASE_URL}/orders/search",
            headers=_cabecalho(),
            params={
                "seller": seller_id,
                "order.status": "paid",
                "order.date_created.from": data_de,
                "order.date_created.to": data_ate,
                "limit": limite,
                "offset": offset,
            },
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
