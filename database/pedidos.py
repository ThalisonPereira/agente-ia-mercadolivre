"""
database/pedidos.py

Rastreia o status de envio dos pedidos pagos do dia (pronto pra envio,
aguardando preparo, já enviado, cancelado) - métrica operacional
diferente de "Vendas" (que no resto do dashboard conta unidades
vendidas, soma de vendas_quantidade): aqui contamos PEDIDOS (transações).

Cada pedido é capturado uma única vez, no dia em que foi criado (mesma
lógica de "ontem" usada pra visitas/vendas). O status_envio reflete o
momento da captura - um pedido "pending" há vários dias provavelmente já
foi enviado de verdade, mas este módulo não re-consulta pedidos antigos
pra atualizar isso (rotina separada, fora de escopo por ora). Por isso
toda consulta aqui é sempre pra UMA data específica (o snapshot mais
recente), nunca uma soma de status ao longo de um período.
"""

from datetime import date, datetime

from database.conexao_turso import obter_conexao
from database.esquema import criar_tabelas

UPSERT_PEDIDO = """
INSERT INTO pedidos (
    conta_id, pedido_id, data_pedido, status_envio, substatus_envio, logistic_type, valor_total, capturado_em
)
VALUES (:conta_id, :pedido_id, :data_pedido, :status_envio, :substatus_envio, :logistic_type, :valor_total, :capturado_em)
ON CONFLICT(conta_id, pedido_id) DO UPDATE SET
    status_envio = excluded.status_envio,
    substatus_envio = excluded.substatus_envio,
    logistic_type = excluded.logistic_type,
    valor_total = excluded.valor_total,
    capturado_em = excluded.capturado_em;
"""

# Classificação do status bruto do Mercado Livre em categoria operacional -
# fica aqui (não gravada no banco) pra poder ajustar a régua sem precisar
# reprocessar dados já capturados.
_CATEGORIA_POR_STATUS = {
    "ready_to_ship": "imediato",
    "pending": "postergado",
    "handling": "postergado",
    "shipped": "enviado",
    "delivered": "enviado",
    "cancelled": "cancelado",
    "not_delivered": "cancelado",
}


def _categoria(status_envio: str | None) -> str:
    return _CATEGORIA_POR_STATUS.get(status_envio or "", "outro")


def _filtros(conta_id: str | None, canal: str | None) -> tuple[str, dict]:
    parametros: dict = {}
    filtros_extra = ""
    if conta_id:
        filtros_extra += " AND p.conta_id = :conta_id"
        parametros["conta_id"] = conta_id
    if canal:
        filtros_extra += " AND c.canal = :canal"
        parametros["canal"] = canal
    return filtros_extra, parametros


def salvar_pedidos_do_dia(conta_id: str, pedidos: list[dict], dia: date | None = None) -> None:
    """
    Grava (ou atualiza) os pedidos do dia informado (padrão: hoje) pra uma
    conta específica, a partir de uma lista de dicionários já coletados na
    API, cada um com as chaves: pedido_id, status_envio, substatus_envio,
    logistic_type, valor_total.
    """
    criar_tabelas()

    data_pedido = (dia or datetime.now().date()).isoformat()
    agora = datetime.now().isoformat(timespec="seconds")

    conexao = obter_conexao()
    try:
        instrucoes = [
            (UPSERT_PEDIDO, {
                "conta_id": conta_id,
                "pedido_id": pedido["pedido_id"],
                "data_pedido": data_pedido,
                "status_envio": pedido.get("status_envio"),
                "substatus_envio": pedido.get("substatus_envio"),
                "logistic_type": pedido.get("logistic_type"),
                "valor_total": pedido.get("valor_total", 0.0),
                "capturado_em": agora,
            })
            for pedido in pedidos
        ]
        conexao.executar_em_lote(instrucoes)
        conexao.commit()
        print(f"[conta: {conta_id}] {len(pedidos)} pedido(s) de {data_pedido} registrado(s).")
    finally:
        conexao.close()


def obter_data_mais_recente(conta_id: str | None = None, canal: str | None = None) -> str | None:
    """Retorna a data (AAAA-MM-DD) mais recente com pedidos capturados, restrita a conta/canal se informado."""
    filtros_extra, parametros = _filtros(conta_id, canal)
    sql = f"""
        SELECT MAX(p.data_pedido) AS maxima
        FROM pedidos p
        LEFT JOIN contas c ON c.conta_id = p.conta_id
        WHERE 1=1 {filtros_extra}
    """
    conexao = obter_conexao()
    try:
        linha = conexao.execute(sql, parametros).fetchone()
    finally:
        conexao.close()
    return linha["maxima"] if linha else None


def obter_resumo(data: str, conta_id: str | None = None, canal: str | None = None) -> dict:
    """Contagem de pedidos por categoria (imediato/postergado/enviado/cancelado/outro) + valor total, numa data específica."""
    filtros_extra, parametros = _filtros(conta_id, canal)
    parametros["data"] = data
    sql = f"""
        SELECT p.status_envio, p.valor_total
        FROM pedidos p
        LEFT JOIN contas c ON c.conta_id = p.conta_id
        WHERE p.data_pedido = :data {filtros_extra}
    """
    conexao = obter_conexao()
    try:
        linhas = conexao.execute(sql, parametros).fetchall()
    finally:
        conexao.close()

    resumo = {"total": 0, "imediato": 0, "postergado": 0, "enviado": 0, "cancelado": 0, "outro": 0, "valor_total": 0.0}
    for linha in linhas:
        resumo["total"] += 1
        resumo[_categoria(linha["status_envio"])] += 1
        resumo["valor_total"] += linha["valor_total"] or 0.0
    return resumo


def obter_pedidos(data: str, conta_id: str | None = None, canal: str | None = None) -> list[dict]:
    """Lista detalhada dos pedidos de uma data específica, já com a categoria calculada."""
    filtros_extra, parametros = _filtros(conta_id, canal)
    parametros["data"] = data
    sql = f"""
        SELECT p.conta_id, p.pedido_id, p.status_envio, p.substatus_envio, p.logistic_type, p.valor_total
        FROM pedidos p
        LEFT JOIN contas c ON c.conta_id = p.conta_id
        WHERE p.data_pedido = :data {filtros_extra}
        ORDER BY p.valor_total DESC
    """
    conexao = obter_conexao()
    try:
        linhas = conexao.execute(sql, parametros).fetchall()
    finally:
        conexao.close()

    return [
        {
            "conta_id": linha["conta_id"],
            "pedido_id": linha["pedido_id"],
            "categoria": _categoria(linha["status_envio"]),
            "status_envio": linha["status_envio"],
            "substatus_envio": linha["substatus_envio"],
            "logistic_type": linha["logistic_type"],
            "valor_total": linha["valor_total"],
        }
        for linha in linhas
    ]
