"""
database/normalizador_alertas.py

Normaliza o snapshot bruto (JSON) de um recurso do Mercado Livre (pergunta,
mensagem, reclamação/post_purchase, devolução) pro formato comum usado por
alertas_pos_venda (titulo/resumo/texto/status_externo/identificadores).

Funções puras, sem I/O (banco/rede) - fáceis de testar com mocks/fixtures.

ATENÇÃO (gap conhecido, ver Fase 3.3 relatório final): os nomes de campo
abaixo (`text`, `status`, `date_created`, etc.) seguem a documentação
pública do Mercado Livre e a pesquisa já feita em fases anteriores desta
sessão, mas NÃO foram confirmados contra um payload real de webhook
processado de ponta a ponta (a fase de auditoria não permite processar
evento real). Cada extração usa `.get()` defensivo (nunca quebra se o
campo não existir) e `snapshot_ml` sempre guarda o JSON bruto completo -
então nenhuma informação é perdida mesmo se um destes campos estiver
errado; só titulo/resumo/texto ficariam incompletos até confirmar.
"""

TOPICO_PARA_TIPO = {
    "questions": "pergunta",
    "messages": "mensagem",
    "post_purchase": "reclamacao",
    "returns": "devolucao",
}


def resolver_tipo_normalizado(topico: str) -> str | None:
    """None se o tópico não faz parte do escopo da V1 (ver Fase 3.3 seção 18) - não inventa um tipo."""
    return TOPICO_PARA_TIPO.get(topico)


def _texto_pergunta(snapshot: dict) -> tuple[str | None, str | None, str | None, str | None]:
    texto = snapshot.get("text")
    item_id = snapshot.get("item_id")
    resumo = f"Pergunta no anúncio {item_id}" if item_id else "Nova pergunta"
    return None, resumo, texto, snapshot.get("status")


def _texto_mensagem(snapshot: dict) -> tuple[str | None, str | None, str | None, str | None]:
    mensagem_aninhada = snapshot.get("message")
    texto_aninhado = mensagem_aninhada.get("text") if isinstance(mensagem_aninhada, dict) else None
    texto = snapshot.get("text") or texto_aninhado
    return None, "Nova mensagem pós-venda", texto, snapshot.get("status")


def _texto_reclamacao(snapshot: dict) -> tuple[str | None, str | None, str | None, str | None]:
    tipo_reclamacao = snapshot.get("type") or snapshot.get("stage")
    resumo = f"Reclamação ({tipo_reclamacao})" if tipo_reclamacao else "Nova reclamação"
    texto = snapshot.get("reason") or snapshot.get("description")
    return None, resumo, texto, snapshot.get("status")


def _texto_devolucao(snapshot: dict) -> tuple[str | None, str | None, str | None, str | None]:
    motivo = snapshot.get("reason") or snapshot.get("type")
    resumo = f"Devolução ({motivo})" if motivo else "Nova devolução"
    return None, resumo, None, snapshot.get("status")


_EXTRATORES = {
    "pergunta": _texto_pergunta,
    "mensagem": _texto_mensagem,
    "reclamacao": _texto_reclamacao,
    "devolucao": _texto_devolucao,
}


def normalizar(tipo: str, recurso: str, snapshot: dict) -> dict:
    """
    Retorna os campos prontos pra database.eventos_alertas.processar_evento_completo:
    recurso_id, titulo, resumo, texto, status_externo, identificadores,
    data_evento_ml. `recurso_id` é sempre extraído do próprio `recurso`
    (ex: '/questions/123456' -> '123456'), nunca do snapshot - é o único
    identificador garantido em qualquer tópico.
    """
    recurso_id = recurso.rstrip("/").rsplit("/", 1)[-1]
    extrator = _EXTRATORES.get(tipo)
    titulo, resumo, texto, status_externo = extrator(snapshot) if extrator else (None, None, None, None)

    identificadores = {}
    for chave in ("item_id", "order_id", "shipment_id", "pack_id"):
        if snapshot.get(chave) is not None:
            identificadores[chave] = snapshot[chave]

    data_evento_ml = snapshot.get("date_created") or snapshot.get("date_created_utc")

    return {
        "recurso_id": recurso_id,
        "titulo": titulo,
        "resumo": resumo,
        "texto": texto,
        "status_externo": status_externo,
        "identificadores": identificadores or None,
        "data_evento_ml": data_evento_ml,
    }
