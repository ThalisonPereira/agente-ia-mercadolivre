"""
integrations/canais/

Interface comum que cada canal de venda (Mercado Livre, Shopee, Amazon...)
implementa, pra que main.py e o resto do projeto não precisem saber nada
específico de cada plataforma - só instanciam o adaptador certo pra cada
conta (conforme o campo `canal` cadastrado em database/contas.py) e chamam
os mesmos métodos.

Cada canal é bem diferente por baixo dos panos (autenticação, formato de
pedidos, conceito de "visita", etc.) - por isso a interface é deliberadamente
enxuta: um único método de alto nível (`coletar_dados_do_dia`) que já
devolve os dados no formato comum usado pelo resto do projeto, em vez de
expor métodos granulares (listar itens, buscar pedidos etc.) que exigiriam
o chamador conhecer os detalhes de cada canal pra combinar os resultados.
"""

from datetime import date
from typing import Protocol


class CanalAdapter(Protocol):
    """
    Interface que todo adaptador de canal deve implementar. Cada instância
    representa uma conta específica (não o canal genérico) - por isso o
    construtor de cada implementação recebe um conta_id.
    """

    def coletar_dados_do_dia(self, dia: date) -> list[dict]:
        """
        Retorna uma lista de dicionários (um por anúncio ativo dessa conta),
        cada um com as chaves: item_id, titulo, sku, visitas,
        vendas_quantidade, receita - já no formato que
        database/capturar_snapshot.py::capturar_snapshot_diario() espera.
        """
        ...


def obter_adaptador(conta_id: str, canal: str) -> CanalAdapter:
    """
    Fábrica: devolve o adaptador certo pra um canal, já configurado pra uma
    conta específica. Import interno (não no topo do módulo) pra não forçar
    a carga de credenciais de canais que a conta não usa.
    """
    if canal == "mercado_livre":
        from integrations.canais.mercado_livre import MercadoLivreCanal
        return MercadoLivreCanal(conta_id)
    if canal == "shopee":
        from integrations.canais.shopee import ShopeeCanal
        return ShopeeCanal(conta_id)
    if canal == "amazon":
        from integrations.canais.amazon import AmazonCanal
        return AmazonCanal(conta_id)

    raise ValueError(f"Canal desconhecido: {canal!r}")
