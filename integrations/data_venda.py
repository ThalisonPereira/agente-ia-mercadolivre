"""
integrations/data_venda.py

Data REAL da venda de um pedido do Bling. A data do pedido no Bling é a do REGISTRO (atraso de 0 a 13 dias,
fim de semana junto na segunda), então não serve para análise por dia nem para virada de mês.

- Mercado Livre: o numeroLoja do Bling é o número da venda/pacote (2000015...). A API do ML devolve a data de
  criação por /orders/{id} ou, para pacotes, /packs/{id} (que também lista os pedidos de dentro do pacote -
  o id que o agente usa em itens_venda).
- Shopee: o número do pedido começa com AAMMDD (ex.: 261026KR5YX7XF = 26/10/2026).
- Falhou ou outro canal: usa a data do Bling, marcada como 'bling_aprox' para ser refeita depois.
"""

import re
import time
from datetime import date, datetime, timedelta, timezone

FUSO_BRASILIA = timezone(timedelta(hours=-3))
ORIGEM_ML = "ml_api"
ORIGEM_SHOPEE = "shopee_numero"
ORIGEM_APROX = "bling_aprox"
_SHOPEE = re.compile(r"^(\d{2})(\d{2})(\d{2})[A-Z0-9]{6,}$")


def data_do_numero_shopee(numero_loja: str, data_bling: str) -> str | None:
    """AAAA-MM-DD a partir do número do pedido Shopee, se plausível (até 45 dias antes do registro no Bling)."""
    m = _SHOPEE.match(str(numero_loja or "").strip().upper())
    if not m:
        return None
    try:
        d = date(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
        ref = date.fromisoformat(data_bling[:10])
    except ValueError:
        return None
    return d.isoformat() if ref - timedelta(days=45) <= d <= ref + timedelta(days=1) else None


def _data_brasilia(date_created: str | None) -> str | None:
    if not date_created:
        return None
    return datetime.fromisoformat(date_created).astimezone(FUSO_BRASILIA).date().isoformat()


class ResolvedorDatas:
    """obter_adaptador(conta_id) devolve o adaptador do Mercado Livre da conta (criado só quando preciso)."""

    def __init__(self, obter_adaptador, pausa: float = 0.25):
        self._obter = obter_adaptador
        self._adaptadores: dict = {}
        self._pausa = pausa

    def _adaptador(self, conta: str):
        if conta not in self._adaptadores:
            self._adaptadores[conta] = self._obter(conta)
        return self._adaptadores[conta]

    def _consultar_ml(self, canal: str, numero_loja: str) -> tuple[str, list] | None:
        ad = self._adaptador(canal[3:].strip().lower())
        for caminho, extrair in (
            (f"/orders/{numero_loja}", lambda o: [o.get("id")]),
            (f"/packs/{numero_loja}", lambda o: [q.get("id") for q in (o.get("orders") or [])]),
        ):
            try:
                recurso = ad.obter_recurso(caminho)
            except Exception as erro:  # 404 = não é desse tipo; outros erros caem no próximo/aproximado
                status = getattr(getattr(erro, "response", None), "status_code", None)
                if status == 404:
                    continue
                return None
            finally:
                time.sleep(self._pausa)
            data = _data_brasilia(recurso.get("date_created"))
            if data:
                return data, [x for x in extrair(recurso) if x]
        return None

    def resolver(self, canal: str, numero_loja: str, data_bling: str) -> tuple[str, str, list]:
        """Retorna (data_venda 'AAAA-MM-DD', origem, ids dos pedidos do ML)."""
        data_bling = str(data_bling or "")[:10]
        if canal.startswith("ML ") and numero_loja:
            r = self._consultar_ml(canal, numero_loja)
            if r:
                return r[0], ORIGEM_ML, r[1]
        elif canal.startswith("SHOPEE"):
            d = data_do_numero_shopee(numero_loja, data_bling)
            if d:
                return d, ORIGEM_SHOPEE, []
        return data_bling, ORIGEM_APROX, []
