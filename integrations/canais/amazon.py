"""
integrations/canais/amazon.py

Adaptador do canal Amazon (SP-API) - AINDA NÃO IMPLEMENTADO. Existe só pra
reservar o encaixe na arquitetura (ver integrations/canais/__init__.py) até
termos credenciais de desenvolvedor da Amazon (LWA + AWS) cadastradas.
"""

from datetime import date


class AmazonCanal:
    def __init__(self, conta_id: str):
        self.conta_id = conta_id

    def coletar_dados_do_dia(self, dia: date) -> list[dict]:
        raise NotImplementedError(
            "Integração com a Amazon (SP-API) ainda não foi implementada. "
            "Precisa cadastrar um app na Amazon Selling Partner API (credenciais LWA + AWS) "
            "antes de implementar este adaptador."
        )

    def coletar_pedidos_do_dia(self, dia: date) -> list[dict]:
        raise NotImplementedError(
            "Integração com a Amazon (SP-API) ainda não foi implementada. "
            "Precisa cadastrar um app na Amazon Selling Partner API (credenciais LWA + AWS) "
            "antes de implementar este adaptador."
        )
