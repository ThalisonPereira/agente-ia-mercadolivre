"""
integrations/canais/shopee.py

Adaptador do canal Shopee - AINDA NÃO IMPLEMENTADO. Existe só pra reservar
o encaixe na arquitetura (ver integrations/canais/__init__.py) até termos
credenciais de desenvolvedor da Shopee Open Platform cadastradas.
"""

from datetime import date


class ShopeeCanal:
    def __init__(self, conta_id: str):
        self.conta_id = conta_id

    def coletar_dados_do_dia(self, dia: date) -> list[dict]:
        raise NotImplementedError(
            "Integração com a Shopee ainda não foi implementada. "
            "Precisa cadastrar um app na Shopee Open Platform (partner_id/partner_key) "
            "antes de implementar este adaptador."
        )
