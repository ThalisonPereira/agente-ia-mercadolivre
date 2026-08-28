"""
database/extrato_referencia.py

Referência de pedidos que o relatório oficial do Mercado Livre conta num
dia diferente do que database/extrato.py conta - pedidos criados num dia
mas só pagos (fechados) no dia seguinte (comum com boleto). O Extrato de
margem continua contando pela data de CRIAÇÃO (decisão confirmada com o
usuário mais de uma vez); esta tabela só guarda o pedido no dia em que ele
apareceria no relatório oficial (data de pagamento), pra exibir como
observação no painel - nunca entra em nenhum total.

Ver integrations/canais/mercado_livre.py::coletar_referencias_pagamento_do_dia.
"""

from datetime import date, datetime

from database.conexao_supabase import obter_conexao
from database.esquema import criar_tabelas
from database.pedidos_bling import obter_numero_bling

UPSERT_REFERENCIA = """
INSERT INTO itens_venda_referencia (
    conta_id, pedido_id, item_id, sku, titulo, data_pagamento, data_criacao,
    quantidade, preco_venda, numero_pedido_bling, capturado_em
)
VALUES (
    %(conta_id)s, %(pedido_id)s, %(item_id)s, %(sku)s, %(titulo)s, %(data_pagamento)s, %(data_criacao)s,
    %(quantidade)s, %(preco_venda)s, %(numero_pedido_bling)s, %(capturado_em)s
)
ON CONFLICT(conta_id, pedido_id, item_id, data_pagamento) DO UPDATE SET
    sku = excluded.sku,
    titulo = excluded.titulo,
    data_criacao = excluded.data_criacao,
    quantidade = excluded.quantidade,
    preco_venda = excluded.preco_venda,
    numero_pedido_bling = excluded.numero_pedido_bling,
    capturado_em = excluded.capturado_em;
"""


def salvar_referencias_do_dia(conta_id: str, itens: list[dict], dia: date | None = None) -> None:
    """
    Grava (ou atualiza) as referências de pagamento do dia informado (padrão:
    hoje) pra uma conta - cada item vem de
    MercadoLivreCanal.coletar_referencias_pagamento_do_dia, com as chaves:
    pedido_id, item_id, sku, titulo, quantidade, preco_venda, data_criacao.
    """
    if not itens:
        return

    criar_tabelas()
    data_pagamento = (dia or datetime.now().date()).isoformat()
    agora = datetime.now().isoformat(timespec="seconds")

    conexao = obter_conexao()
    try:
        instrucoes = [
            (UPSERT_REFERENCIA, {
                "conta_id": conta_id,
                "pedido_id": item["pedido_id"],
                "item_id": item["item_id"],
                "sku": item.get("sku", ""),
                "titulo": item.get("titulo", ""),
                "data_pagamento": data_pagamento,
                "data_criacao": item.get("data_criacao"),
                "quantidade": item.get("quantidade", 0),
                "preco_venda": item.get("preco_venda", 0.0),
                "numero_pedido_bling": obter_numero_bling(item["pedido_id"]),
                "capturado_em": agora,
            })
            for item in itens
        ]
        conexao.executar_em_lote(instrucoes)
        conexao.commit()
        print(f"[conta: {conta_id}] {len(itens)} referência(s) de pagamento de {data_pagamento} registrada(s).")
    finally:
        conexao.close()


def obter_referencias(
    data_inicio: str, data_fim: str, conta_id: str | None = None, canal: str | None = None
) -> list[dict]:
    """
    Pedidos criados em outro dia mas pagos (fechados) dentro do intervalo
    informado - pra exibir como observação no Extrato, explicando por que o
    relatório oficial do Mercado Livre pode mostrar um total diferente pra
    esse dia. Nunca soma em nenhum total (ver database/extrato.py).
    """
    filtros_extra = ""
    parametros: dict = {"data_inicio": data_inicio, "data_fim": data_fim}
    if conta_id:
        filtros_extra += " AND r.conta_id = %(conta_id)s"
        parametros["conta_id"] = conta_id
    if canal:
        filtros_extra += " AND c.canal = %(canal)s"
        parametros["canal"] = canal

    sql = f"""
        SELECT r.conta_id, c.canal, r.pedido_id, r.item_id, r.sku, r.titulo,
               r.data_pagamento, r.data_criacao, r.quantidade, r.preco_venda,
               r.numero_pedido_bling
        FROM itens_venda_referencia r
        LEFT JOIN contas c ON c.conta_id = r.conta_id
        WHERE r.data_pagamento BETWEEN %(data_inicio)s AND %(data_fim)s {filtros_extra}
        ORDER BY r.data_pagamento DESC, r.preco_venda DESC
    """
    conexao = obter_conexao()
    try:
        linhas = conexao.execute(sql, parametros).fetchall()
    finally:
        conexao.close()

    return [dict(linha) for linha in linhas]
