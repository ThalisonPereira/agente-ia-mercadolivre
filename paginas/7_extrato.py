"""
paginas/7_extrato.py

Extrato de margem por venda: pra cada item vendido (SKU) num intervalo de
datas (1 dia, por padrão o mais recente coletado, ou um período
customizado), mostra preço de venda, comissão do Mercado Livre, frete
pago pelo vendedor, valor líquido sem imposto, imposto (14%), valor
líquido final e o custo do produto (Bling), chegando na margem líquida.
Cada coluna tem uma dica (tooltip) explicando o que representa. Quando o
filtro reúne mais de uma conta/canal, a tabela mostra de qual conta/canal
cada linha veio, pra não misturar tudo sem distinção. Ver
database/extrato.py pra fórmula e limitações (ex: SKUs sem custo
cadastrado no Bling ficam sinalizados, não silenciosamente tratados como
custo zero).
"""

from datetime import date

import pandas as pd
import streamlit as st

from database.contas import obter_contas_ativas
from database.extrato import ALIQUOTA_IMPOSTO, obter_data_mais_recente, obter_extrato, obter_resumo_extrato
from paginas._util_filtros import obter_filtros_sidebar

st.title("📋 Extrato")

conta_id, canal = obter_filtros_sidebar()

data_maxima = obter_data_mais_recente(conta_id, canal)
if data_maxima is None:
    st.info("Ainda não há extrato coletado para esse filtro.")
    st.stop()

data_maxima_date = date.fromisoformat(data_maxima)

col_data1, col_data2 = st.columns(2)
data_inicio = col_data1.date_input("De", value=data_maxima_date, key="extrato_data_inicio")
data_fim = col_data2.date_input("Até", value=data_maxima_date, key="extrato_data_fim")

if data_inicio > data_fim:
    st.error("A data inicial não pode ser depois da data final.")
    st.stop()

if data_inicio == data_fim:
    st.caption(f"Dia {data_inicio.isoformat()} - imposto estimado em {ALIQUOTA_IMPOSTO:.0%} sobre o preço de venda bruto.")
else:
    st.caption(
        f"Período de {data_inicio.isoformat()} a {data_fim.isoformat()} - "
        f"imposto estimado em {ALIQUOTA_IMPOSTO:.0%} sobre o preço de venda bruto."
    )

resumo = obter_resumo_extrato(data_inicio.isoformat(), data_fim.isoformat(), conta_id, canal)

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total vendido", f"R$ {resumo['total_vendido']:,.2f}")
col2.metric("Comissão + Frete", f"R$ {resumo['total_comissao'] + resumo['total_frete']:,.2f}")
col3.metric("Imposto (14%)", f"R$ {resumo['total_imposto']:,.2f}")
col4.metric("Margem líquida", f"R$ {resumo['total_margem']:,.2f}")
col5.metric(
    "Margem de contribuição",
    f"{resumo['margem_percentual']:.1f}%" if resumo["margem_percentual"] is not None else "—",
)

if resumo["itens_sem_custo"]:
    st.warning(
        f"⚠️ {resumo['itens_sem_custo']} de {resumo['total_itens']} item(ns) sem custo encontrado no "
        "Bling (SKU não cadastrado, ou custo zerado - comum em produtos 'pai'/kit) - a 'Margem líquida' "
        "acima NÃO inclui esses itens, pra não distorcer o número. Os outros totais ('Total vendido', "
        "'Comissão + Frete', 'Imposto') continuam somando esses itens normalmente."
    )
if resumo["itens_cancelados"]:
    st.info(
        f"🚫 {resumo['itens_cancelados']} pedido(s) cancelado(s) aparecem na tabela abaixo com "
        "valores zerados - a venda não se concretizou, então não entram em nenhum total acima."
    )
if resumo["itens_pendentes"]:
    st.info(
        f"⏳ {resumo['itens_pendentes']} item(ns) ainda aguardando confirmação de pagamento (ex: boleto) "
        "aparecem com valores zerados - não entram em nenhum total acima. Assim que o pagamento for "
        "confirmado, a próxima coleta corrige a linha automaticamente pra 'Pago', sem precisar de ação manual."
    )
if resumo["itens_com_reclamacao"]:
    st.warning(
        f"⚠️ {resumo['itens_com_reclamacao']} pedido(s) com possível reclamação/mediação em aberto - "
        "os valores mostrados são os do pedido original (pode haver reembolso parcial que este sistema "
        "ainda não calcula). Vale conferir manualmente no Mercado Livre."
    )

if conta_id is None:
    contas = obter_contas_ativas(canal)
    if len(contas) > 1:
        st.subheader("Resumo por conta")
        linhas_por_conta = []
        for conta in contas:
            resumo_conta = obter_resumo_extrato(
                data_inicio.isoformat(), data_fim.isoformat(), conta_id=conta["conta_id"], canal=None
            )
            if resumo_conta["total_itens"] == 0:
                continue
            linhas_por_conta.append({
                "conta_id": conta["conta_id"],
                "nome": conta["nome"],
                "total_vendido": resumo_conta["total_vendido"],
                "comissao_frete": resumo_conta["total_comissao"] + resumo_conta["total_frete"],
                "imposto": resumo_conta["total_imposto"],
                "margem_liquida": resumo_conta["total_margem"],
                "margem_percentual": resumo_conta["margem_percentual"],
            })
        if linhas_por_conta:
            st.dataframe(
                pd.DataFrame(linhas_por_conta),
                column_config={
                    "conta_id": st.column_config.TextColumn("Conta"),
                    "nome": st.column_config.TextColumn("Nome"),
                    "total_vendido": st.column_config.NumberColumn("Total vendido", format="R$ %.2f"),
                    "comissao_frete": st.column_config.NumberColumn("Comissão + Frete", format="R$ %.2f"),
                    "imposto": st.column_config.NumberColumn(f"Imposto ({ALIQUOTA_IMPOSTO:.0%})", format="R$ %.2f"),
                    "margem_liquida": st.column_config.NumberColumn("Margem líquida", format="R$ %.2f"),
                    "margem_percentual": st.column_config.NumberColumn(
                        "Margem %", format="%.1f%%",
                        help="Não inclui itens sem custo encontrado no Bling, mesmo critério do resumo combinado acima.",
                    ),
                },
                hide_index=True,
                use_container_width=True,
            )

itens = obter_extrato(data_inicio.isoformat(), data_fim.isoformat(), conta_id, canal)
if itens:
    df = pd.DataFrame(itens)
    df["sku"] = df.apply(
        lambda linha: linha["sku"]
        if linha["status"] in ("cancelado", "pendente") or linha["custo_produto"] is not None
        else f"⚠️ {linha['sku'] or '(sem SKU)'}",
        axis=1,
    )
    df["status"] = df["status"].map({
        "pago": "✅ Pago",
        "cancelado": "🚫 Cancelado",
        "pendente": "⏳ Pendente",
        "pago_com_reclamacao": "⚠️ Pago (reclamação)",
    }).fillna(df["status"])

    # Conta/canal e data só aparecem na tabela quando fazem diferença -
    # filtro numa conta específica ou num único dia não precisa repetir a
    # mesma informação em toda linha.
    mostrar_conta = conta_id is None
    mostrar_data = data_inicio != data_fim

    colunas_iniciais = (["conta_id", "canal"] if mostrar_conta else []) + (["data_venda"] if mostrar_data else [])
    st.dataframe(
        df,
        column_order=colunas_iniciais + [
            "status", "sku", "titulo", "quantidade", "preco_venda", "comissao_ml", "frete_vendedor",
            "valor_liquido_sem_imposto", "imposto", "valor_liquido", "custo_produto", "margem", "margem_percentual",
        ],
        column_config={
            "conta_id": st.column_config.TextColumn("Conta", help="Conta do Mercado Livre (ou outro canal) de origem dessa venda."),
            "canal": st.column_config.TextColumn("Canal", help="Canal de venda (ex: mercado_livre, shopee)."),
            "data_venda": st.column_config.TextColumn("Data", help="Dia em que o pedido foi criado."),
            "status": st.column_config.TextColumn("Status", help="'Pago' = venda confirmada, entra nos totais. 'Cancelado'/'Pendente' = valores zerados, não entram nos totais. 'Pago (reclamação)' = venda confirmada mas com possível reembolso em aberto, revisar manualmente."),
            "sku": st.column_config.TextColumn("SKU", help="Código do produto no momento da venda - ⚠️ significa que não foi encontrado (ou tinha custo zerado) no Bling."),
            "titulo": st.column_config.TextColumn("Anúncio", help="Título do anúncio no Mercado Livre."),
            "quantidade": st.column_config.NumberColumn("Qtd", help="Quantidade vendida nessa linha."),
            "preco_venda": st.column_config.NumberColumn("Preço Venda", format="R$ %.2f", help="Valor bruto da venda (preço unitário × quantidade), antes de qualquer desconto."),
            "comissao_ml": st.column_config.NumberColumn("Comissão ML", format="R$ %.2f", help="Comissão cobrada pelo Mercado Livre sobre essa venda."),
            "frete_vendedor": st.column_config.NumberColumn("Frete", format="R$ %.2f", help="Custo do frete pago pelo vendedor (não o valor cobrado do comprador)."),
            "valor_liquido_sem_imposto": st.column_config.NumberColumn("Valor Líquido (sem imposto)", format="R$ %.2f", help="Preço de venda menos comissão do ML e frete - ainda SEM descontar o imposto."),
            "imposto": st.column_config.NumberColumn(f"Imposto ({ALIQUOTA_IMPOSTO:.0%})", format="R$ %.2f", help=f"Estimativa de imposto: {ALIQUOTA_IMPOSTO:.0%} sobre o preço de venda bruto."),
            "valor_liquido": st.column_config.NumberColumn("Valor Líquido", format="R$ %.2f", help="Valor líquido (sem imposto) menos o imposto estimado - o que sobra da venda antes do custo do produto."),
            "custo_produto": st.column_config.NumberColumn("Custo", format="R$ %.2f", help="Custo total da linha (custo unitário do Bling × quantidade), capturado no momento da coleta - não muda retroativamente se o custo mudar depois no Bling."),
            "margem": st.column_config.NumberColumn("Margem", format="R$ %.2f", help="Lucro real da venda: valor líquido menos o custo do produto."),
            "margem_percentual": st.column_config.NumberColumn("Margem %", format="%.1f%%", help="Margem de contribuição: margem (R$) dividida pelo preço de venda bruto, em %."),
        },
        hide_index=True,
        use_container_width=True,
    )
else:
    st.info("Nenhum item vendido nesse intervalo, pra esse filtro.")
