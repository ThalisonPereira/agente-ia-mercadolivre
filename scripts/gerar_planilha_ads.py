"""
scripts/gerar_planilha_ads.py

Gera o MODELO da planilha "Central de Ads" (xlsx, para importar no Google Sheets) com dados reais do banco do
agente (somente leitura). As abas de dados (Dados Ads, Faturamento, Estoque, Campanha x SKU, Insights) são o que a
rotina Python vai publicar depois; Resumo, Campanhas e Config são fórmulas e células amarelas (ajustáveis).

Uso: python scripts/gerar_planilha_ads.py [caminho_de_saida.xlsx]
"""

import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openpyxl import Workbook  # noqa: E402
from openpyxl.chart import BarChart, Reference  # noqa: E402
from openpyxl.formatting.rule import FormulaRule  # noqa: E402
from openpyxl.formula import Tokenizer  # noqa: E402
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402
from openpyxl.workbook.defined_name import DefinedName  # noqa: E402
from openpyxl.worksheet.datavalidation import DataValidation  # noqa: E402

from database.conexao_supabase import obter_conexao  # noqa: E402

SAIDA_PADRAO = Path(__file__).resolve().parent.parent / "dados_locais" / "Central_ADS_Modelo.xlsx"
CANAL_DA_CONTA = {"wc": "ML WC", "hc": "ML HC", "cc": "ML CC"}
CANAIS = ["ML WC", "ML HC", "ML CC", "SHOPEE WC", "SHOPEE CC", "AMAZON", "TIKTOK"]
DIAS_HISTORICO = 90
ULT_DADOS, ULT_MAP, ULT_EST, ULT_FAT = 20000, 3000, 5000, 5000
PRIM_CAMP, N_CAMP = 7, 80
ULT_CAMP = PRIM_CAMP + N_CAMP - 1

# --- estilo -----------------------------------------------------------------------------------------------------
AZUL, AZUL_CLARO, CINZA, AMARELO, BRANCO = "1F3864", "D9E2F3", "F2F2F2", "FFF2CC", "FFFFFF"
FONTE = "Calibri"
f_normal = Font(name=FONTE, size=10)
f_negrito = Font(name=FONTE, size=10, bold=True)
f_cab = Font(name=FONTE, size=10, bold=True, color=BRANCO)
f_titulo = Font(name=FONTE, size=16, bold=True, color=AZUL)
f_sub = Font(name=FONTE, size=10, italic=True, color="595959")
f_card = Font(name=FONTE, size=18, bold=True, color=AZUL)
fill_cab = PatternFill("solid", start_color=AZUL, end_color=AZUL)
fill_input = PatternFill("solid", start_color=AMARELO, end_color=AMARELO)
fill_card = PatternFill("solid", start_color=AZUL_CLARO, end_color=AZUL_CLARO)
fill_total = PatternFill("solid", start_color=CINZA, end_color=CINZA)
fino = Side(style="thin", color="D0D0D0")
borda = Border(bottom=fino)
borda_box = Border(left=fino, right=fino, top=fino, bottom=fino)
centro = Alignment(horizontal="center", vertical="center", wrap_text=True)
esq_wrap = Alignment(horizontal="left", vertical="top", wrap_text=True)

BRL = '"R$" #,##0.00'
BRL0 = '"R$" #,##0'
PCT = "0.0%"
PCT0 = "0%"
ROAS_F = '0.00"x"'
INT = "#,##0"
DATA_F = "dd/mm/yyyy"


def cabecalho(ws, linha, titulos, altura=32):
    for i, t in enumerate(titulos, 1):
        c = ws.cell(linha, i, t)
        c.font, c.fill, c.alignment = f_cab, fill_cab, centro
    ws.row_dimensions[linha].height = altura


def larguras(ws, valores):
    for i, w in enumerate(valores, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def como_data(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def ref(sheet, col, ini, fim):
    return f"'{sheet}'!${col}${ini}:${col}${fim}"


# --- dados do banco -----------------------------------------------------------------------------------------------
def carregar():
    c = obter_conexao()
    fim = c.execute("select max(data) m from ads_campanhas_diario").fetchone()["m"]
    fim = como_data(fim)
    ini = fim - timedelta(days=DIAS_HISTORICO - 1)
    camp = c.execute(
        "select data, conta_id, campaign_id, nome, status, budget, roas_target, acos_target, prints, clicks, cost, "
        "direct_amount, indirect_amount, total_amount, units_quantity from ads_campanhas_diario "
        "where data >= %s order by data, conta_id, campaign_id", (ini.isoformat(),)).fetchall()
    fat = c.execute(
        "select data_venda d, conta_id, sum(preco_venda) fat, count(distinct pedido_id) ped, sum(quantidade) un "
        "from itens_venda where status not in ('cancelado','pendente') and data_venda >= %s group by 1,2 order by 1,2",
        (ini.isoformat(),)).fetchall()
    # SKU do anúncio: o do cadastro (anuncios.sku) e, quando ele vem vazio (28 de 37 anúncios em campanha em 11/2026),
    # o que aparece nas vendas desse mesmo anúncio (itens_venda).
    mapa = c.execute(
        "with vendas as (select conta_id, item_id, max(nullif(sku,'')) sku from itens_venda group by 1,2) "
        "select distinct a.campaign_id, a.conta_id, coalesce(nullif(an.sku,''), v.sku) as sku from ads_anuncios_diario a "
        "left join anuncios an on an.conta_id = a.conta_id and an.item_id = a.item_id "
        "left join vendas v on v.conta_id = a.conta_id and v.item_id = a.item_id "
        "where a.data >= %s and a.campaign_id is not null and coalesce(nullif(an.sku,''), v.sku) is not null order by 1,3",
        ((fim - timedelta(days=30)).isoformat(),)).fetchall()
    # Estoque: TODOS os SKUs com saldo (assim uma campanha de outro canal, mapeada à mão, também acha o estoque).
    saldos = {r["sku"]: (r["nome"], r["estoque_saldo"]) for r in c.execute(
        "select sku, nome, estoque_saldo from custo_produtos where estoque_saldo is not null").fetchall()}
    insights = c.execute(
        "select distinct on (conta_id) conta_id, data, texto from analises_ads_diarias order by conta_id, data desc").fetchall()
    c.close() if hasattr(c, "close") else None
    # Ritmo de venda e faturamento dos demais canais: pedidos do Bling (arquivo local da coleta de vendas), todos os canais.
    import sqlite3
    lite = sqlite3.connect(Path(__file__).resolve().parent.parent / "dados_locais" / "vendas_bling.db")
    lite.row_factory = sqlite3.Row
    data_real = "COALESCE(p.data_venda, p.data_bling)"
    vend30 = {r["sku"]: float(r["q"]) for r in lite.execute(
        f"select i.sku, sum(i.quantidade) q from itens i join pedidos p on p.pedido_id = i.pedido_id "
        f"where p.conta_venda = 1 and p.detalhe_ok = 1 and {data_real} > ? and coalesce(i.sku,'') <> '' group by 1",
        ((fim - timedelta(days=30)).isoformat(),)).fetchall()}
    outros = ",".join(f"'{x}'" for x in ("SHOPEE WC", "SHOPEE CC", "AMAZON", "TIKTOK"))
    fat_outros = [{"d": r["d"], "conta_id": r["canal"], "fat": r["fat"], "ped": r["ped"], "un": r["un"]} for r in lite.execute(
        f"select {data_real} d, p.canal, sum(i.valor_bruto) fat, count(distinct p.pedido_id) ped, sum(i.quantidade) un "
        f"from itens i join pedidos p on p.pedido_id = i.pedido_id where p.conta_venda = 1 and p.detalhe_ok = 1 "
        f"and p.canal in ({outros}) and {data_real} >= ? group by 1, 2 order by 1, 2", (ini.isoformat(),)).fetchall()]
    lite.close()
    return fim, camp, list(fat) + fat_outros, mapa, saldos, vend30, insights


# --- abas ---------------------------------------------------------------------------------------------------------
def aba_leia_me(wb):
    ws = wb.active
    ws.title = "Leia-me"
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = AZUL
    larguras(ws, [3, 28, 110])
    ws["B2"], ws["B2"].font = "Central de Ads", f_titulo
    ws["B3"], ws["B3"].font = "Mercado Ads e demais canais num só lugar: KPIs, TACOS, estoque e veredito por campanha.", f_sub
    linhas = [
        ("Abas", ""),
        ("Resumo", "KPIs por canal e total no período escolhido (altere De/Até nas células amarelas), comparação com o período anterior e TACOS contra a meta."),
        ("Campanhas", "Uma linha por campanha, com ROAS, ACOS, CTR, CPC, CR, uso do orçamento, cobertura de estoque dos SKUs e o VEREDITO com o motivo."),
        ("Config", "Limites das regras (células amarelas). Mudar aqui muda o veredito de todas as campanhas."),
        ("Dados Ads", "Dados diários das campanhas do Mercado Livre, vindos do banco (a rotina regrava esta aba: não digite nela)."),
        ("Entrada Manual", "Shopee, Amazon e TikTok: você digita aqui (células amarelas). A rotina nunca mexe nesta aba."),
        ("Faturamento", "Faturamento total por dia e canal (base do TACOS = investimento em Ads ÷ faturamento total)."),
        ("Estoque", "Saldo (Bling), ritmo de venda (30 dias) e cobertura em dias dos SKUs das campanhas."),
        ("Campanha x SKU", "Quais SKUs cada campanha anuncia. Linhas 'Manual' podem ser adicionadas por você; a cobertura da campanha é a MENOR entre seus SKUs."),
        ("Insights", "Texto da análise de IA de publicidade do dia, por conta."),
        ("", ""),
        ("Vereditos", ""),
        ("PAUSAR / REDUZIR", "Cobertura de estoque de algum SKU abaixo do mínimo (Config), mesmo com ROAS bom."),
        ("REVISAR", "ROAS (sem os últimos dias de atribuição) abaixo da meta da campanha."),
        ("ALERTA", "Investiu acima do mínimo, com cliques suficientes e nenhuma venda atribuída."),
        ("ESCALAR", "ROAS na meta, orçamento quase esgotado e estoque confortável: candidata a mais orçamento."),
        ("MANTER", "ROAS na meta; se o estoque estiver baixo, o motivo avisa que ele limita a escala."),
        ("AGUARDAR", "Pouco volume (investimento ou cliques abaixo do mínimo) para avaliar."),
        ("SEM META", "A campanha não tem meta de ROAS no Mercado Ads."),
        ("Pausada / Sem atividade / Sem dados", "Campanha pausada, sem investimento no período, ou sem linhas na aba Dados Ads."),
        ("", ""),
        ("Outros canais", "Digite na aba Entrada Manual (uma linha por campanha e dia): canal, ID ou nome da campanha, status, investimento, receita e cliques. "
                          "Campos que a plataforma não informa ficam vazios. Depois inclua a campanha na aba Campanhas (células amarelas A, B e T) para ela aparecer no painel e receber veredito."),
        ("Atualização", "Os dados do Mercado Livre são publicados pela rotina diária em Python. As regras e a leitura são fórmulas: não digite nas colunas calculadas."),
        ("Observação", "As avaliações ignoram os últimos dias do período (Config: dias de atraso), porque o Mercado Ads atribui as vendas com atraso."),
    ]
    r = 5
    for titulo, texto in linhas:
        if titulo and not texto:
            ws.cell(r, 2, titulo).font = Font(name=FONTE, size=12, bold=True, color=AZUL)
        else:
            ws.cell(r, 2, titulo).font = f_negrito
            c = ws.cell(r, 3, texto)
            c.font, c.alignment = f_normal, esq_wrap
            ws.row_dimensions[r].height = 15 if len(texto) < 110 else 15 * (len(texto) // 105 + 1)
        r += 1


def aba_config(wb):
    ws = wb.create_sheet("Config")
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = "BF9000"
    larguras(ws, [38, 14, 78, 4, 4, 18])
    ws["A1"], ws["A1"].font = "Configuração das regras", f_titulo
    ws["A2"], ws["A2"].font = "Células amarelas são suas. Os limites são pontos de partida, não regras universais.", f_sub
    cabecalho(ws, 3, ["Parâmetro", "Valor", "O que faz"], 22)
    params = [
        ("dias_atraso", "Dias de atraso da atribuição", 2, INT, "Os últimos N dias do período não entram na avaliação (o Mercado Ads atribui vendas com atraso)."),
        ("inv_min", "Investimento mínimo para avaliar (R$)", 30, BRL0, "Abaixo disso a campanha fica em AGUARDAR."),
        ("cliques_min", "Cliques mínimos para avaliar", 30, INT, "Abaixo disso a campanha fica em AGUARDAR."),
        ("cob_critica", "Cobertura crítica (dias)", 7, INT, "SKU com cobertura menor que isso: PAUSAR / REDUZIR."),
        ("cob_ok", "Cobertura confortável (dias)", 15, INT, "Só escala se todos os SKUs tiverem pelo menos isso."),
        ("pct_orc", "Uso do orçamento para escalar", 0.9, PCT0, "Investimento ÷ (orçamento diário × dias com dado) a partir do qual a campanha é candidata a ESCALAR."),
        ("tol_roas", "Tolerância abaixo da meta de ROAS", 0, PCT0, "0% = qualquer ROAS abaixo da meta vira REVISAR. Ex.: 10% aceita até 10% abaixo."),
        ("meta_tacos", "Meta de TACOS", 0.02, PCT, "Investimento em Ads ÷ faturamento total. Usado na aba Resumo."),
        ("dias_ritmo", "Dias para o ritmo de venda", 30, INT, "Janela usada na aba Estoque para o ritmo diário de vendas."),
    ]
    for i, (nome, rotulo, valor, fmt, desc) in enumerate(params, 4):
        ws.cell(i, 1, rotulo).font = f_normal
        v = ws.cell(i, 2, valor)
        v.font, v.fill, v.number_format, v.alignment, v.border = f_negrito, fill_input, fmt, centro, borda_box
        d = ws.cell(i, 3, desc)
        d.font, d.alignment = f_normal, esq_wrap
        ws.row_dimensions[i].height = 28
        wb.defined_names[nome] = DefinedName(nome, attr_text=f"Config!$B${i}")
    ws["F3"] = "Canais"
    ws["F3"].font, ws["F3"].fill, ws["F3"].alignment = f_cab, fill_cab, centro
    for i, canal in enumerate(["TODOS"] + CANAIS, 4):
        ws.cell(i, 6, canal).font = f_normal
    ws["H3"] = "Outros canais"
    ws["H3"].font, ws["H3"].fill, ws["H3"].alignment = f_cab, fill_cab, centro
    for i, canal in enumerate(["SHOPEE WC", "SHOPEE CC", "AMAZON", "TIKTOK"], 4):
        ws.cell(i, 8, canal).font = f_normal
    ws.column_dimensions["H"].width = 16
    wb.defined_names["outros_canais"] = DefinedName("outros_canais", attr_text="Config!$H$4:$H$7")
    wb.defined_names["lista_canais"] = DefinedName("lista_canais", attr_text=f"Config!$F$4:$F${3 + len(CANAIS) + 1}")
    return ws


def aba_dados(wb, camp):
    ws = wb.create_sheet("Dados Ads")
    ws.sheet_properties.tabColor = "7F7F7F"
    heads = ["Data", "Canal", "Conta", "ID campanha", "Campanha", "Status", "Orçamento/dia (R$)", "Meta ROAS",
             "Meta ACOS (%)", "Impressões", "Cliques", "Investimento (R$)", "Receita direta (R$)",
             "Receita indireta (R$)", "Receita total (R$)", "Unid. totais", "Origem"]
    cabecalho(ws, 1, heads)
    for r in camp:
        ws.append([como_data(r["data"]), CANAL_DA_CONTA.get(r["conta_id"], r["conta_id"].upper()), r["conta_id"],
                   str(r["campaign_id"]), r["nome"], r["status"], _n(r["budget"]), _n(r["roas_target"]), _n(r["acos_target"]),
                   _n(r["prints"]), _n(r["clicks"]), _n(r["cost"]), _n(r["direct_amount"]), _n(r["indirect_amount"]),
                   _n(r["total_amount"]), _n(r["units_quantity"]), "API Mercado Livre"])
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        row[0].number_format = DATA_F
        for i in (6, 11, 12, 13, 14):
            row[i].number_format = BRL
        for i in (9, 10, 15):
            row[i].number_format = INT
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:Q{max(ws.max_row, 2)}"
    larguras(ws, [11, 11, 7, 14, 34, 9, 14, 10, 11, 12, 10, 14, 14, 14, 14, 10, 18])
    cols = {"d_data": "A", "d_canal": "B", "d_id": "D", "d_status": "F", "d_orc": "G", "d_meta": "H", "d_imp": "J",
            "d_cliques": "K", "d_inv": "L", "d_rec": "O", "d_un": "P"}
    for nome, col in cols.items():
        wb.defined_names[nome] = DefinedName(nome, attr_text=ref("Dados Ads", col, 2, ULT_DADOS))


def _n(v):
    return None if v is None else float(v)


def aba_faturamento(wb, fat):
    ws = wb.create_sheet("Faturamento")
    ws.sheet_properties.tabColor = "7F7F7F"
    cabecalho(ws, 1, ["Data", "Canal", "Faturamento total (R$)", "Pedidos", "Unidades"])
    for r in fat:
        ws.append([como_data(r["d"]), CANAL_DA_CONTA.get(r["conta_id"], r["conta_id"].upper()), float(r["fat"]), int(r["ped"]), float(r["un"])])
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        row[0].number_format, row[2].number_format = DATA_F, BRL
    ws.freeze_panes = "A2"
    larguras(ws, [12, 12, 22, 10, 10])
    for nome, col in {"f_data": "A", "f_canal": "B", "f_fat": "C"}.items():
        wb.defined_names[nome] = DefinedName(nome, attr_text=ref("Faturamento", col, 2, ULT_FAT))


def aba_manual(wb):
    """Entrada manual dos canais sem coleta automática. Fica numa aba própria porque Dados Ads é regravada pela rotina."""
    ws = wb.create_sheet("Entrada Manual")
    ws.sheet_properties.tabColor = "BF9000"
    heads = ["Data", "Canal", "ID ou nome da campanha", "Status", "Orçamento/dia (R$)", "Meta ROAS", "Impressões", "Cliques",
             "Investimento (R$)", "Receita total (R$)", "Unid. vendidas"]
    cabecalho(ws, 1, heads, 36)
    larguras(ws, [12, 13, 34, 11, 15, 11, 13, 10, 16, 16, 14])
    ws.freeze_panes = "A2"
    for r in range(2, 502):
        ws.cell(r, 1).number_format = DATA_F
        for col in (5, 9, 10):
            ws.cell(r, col).number_format = BRL
        for col in (6,):
            ws.cell(r, col).number_format = ROAS_F
        for col in (7, 8, 11):
            ws.cell(r, col).number_format = INT
        for col in range(1, 12):
            ws.cell(r, col).fill = fill_input
            ws.cell(r, col).font = f_normal
            ws.cell(r, col).border = borda
    dv_canal = DataValidation(type="list", formula1="=outros_canais", allow_blank=True)
    dv_status = DataValidation(type="list", formula1='"active,paused"', allow_blank=True)
    dv_data = DataValidation(type="date", operator="greaterThan", formula1="36526", allow_blank=True,
                             errorTitle="Data inválida", error="Digite uma data (dd/mm/aaaa).")
    for dv, faixa in ((dv_canal, "B2:B501"), (dv_status, "D2:D501"), (dv_data, "A2:A501")):
        ws.add_data_validation(dv)
        dv.add(faixa)
    ws["M1"], ws["M1"].font = "Como usar", f_negrito
    dicas = ["Uma linha por campanha e por dia. Se a plataforma só dá o total do período, lance numa única data (a do fim do período).",
             "A chave é a coluna C: use sempre o mesmo ID ou nome para a mesma campanha. Se a plataforma não tem ID, use o nome.",
             "Status: active ou paused. Orçamento, meta de ROAS, impressões e unidades são opcionais (vazio = sem dado).",
             "Depois, na aba Campanhas, inclua a campanha nas células amarelas: canal (A), nome (B) e a mesma chave da coluna C (T).",
             "Para o estoque valer nessas campanhas, relacione os SKUs na aba Campanha x SKU (origem 'Manual')."]
    for i, d in enumerate(dicas, 2):
        ws.cell(i, 13, d).font = f_sub
    ws.column_dimensions["M"].width = 100
    cols = {"x_data": "A", "x_canal": "B", "x_id": "C", "x_status": "D", "x_orc": "E", "x_meta": "F", "x_imp": "G",
            "x_cliques": "H", "x_inv": "I", "x_rec": "J", "x_un": "K"}
    for nome, col in cols.items():
        wb.defined_names[nome] = DefinedName(nome, attr_text=ref("Entrada Manual", col, 2, 5000))


def aba_estoque(wb, mapa, saldos, vend30):
    ws = wb.create_sheet("Estoque")
    ws.sheet_properties.tabColor = "7F7F7F"
    cabecalho(ws, 1, ["SKU", "Descrição", "Saldo (Bling)", "Vendas 30d (un)", "Ritmo (un/dia)", "Cobertura (dias)", "Status"])
    skus = sorted(saldos)
    for i, sku in enumerate(skus, 2):
        nome, saldo = saldos.get(sku, ("", None))
        ws.append([sku, nome, float(saldo) if saldo is not None else 0, vend30.get(sku, 0.0),
                   f"=IF(A{i}=\"\",\"\",D{i}/dias_ritmo)",
                   f"=IF(A{i}=\"\",\"\",IF(C{i}<=0,0,IF(E{i}=0,999,C{i}/E{i})))",
                   f"=IF(A{i}=\"\",\"\",IF(C{i}<=0,\"Zerado\",IF(F{i}<cob_critica,\"Crítico\",IF(F{i}<cob_ok,\"Baixo\",\"OK\"))))"])
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        row[2].number_format, row[3].number_format, row[4].number_format, row[5].number_format = INT, INT, "0.00", "0"
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:G{max(ws.max_row, 2)}"
    larguras(ws, [20, 46, 13, 15, 14, 16, 11])
    for col, cor in (("Zerado", "F4B6B6"), ("Crítico", "F8CBAD"), ("Baixo", "FFE699"), ("OK", "C6E0B4")):
        ws.conditional_formatting.add(f"G2:G{ULT_EST}", FormulaRule(formula=[f'$G2="{col}"'], fill=PatternFill("solid", start_color=cor, end_color=cor)))
    wb.defined_names["e_sku"] = DefinedName("e_sku", attr_text=ref("Estoque", "A", 2, ULT_EST))
    wb.defined_names["e_cob"] = DefinedName("e_cob", attr_text=ref("Estoque", "F", 2, ULT_EST))


def aba_mapa(wb, camp, mapa):
    ws = wb.create_sheet("Campanha x SKU")
    ws.sheet_properties.tabColor = "7F7F7F"
    cabecalho(ws, 1, ["ID campanha", "Campanha", "Canal", "SKU", "Cobertura (dias)", "Saldo", "Origem"])
    nomes = {}
    for r in camp:
        nomes[(str(r["campaign_id"]))] = r["nome"]
    for i, r in enumerate(mapa, 2):
        cid = str(r["campaign_id"])
        ws.append([cid, nomes.get(cid, ""), CANAL_DA_CONTA.get(r["conta_id"], r["conta_id"].upper()), r["sku"],
                   f"=IF(D{i}=\"\",\"\",IFERROR(INDEX(e_cob,MATCH(D{i},e_sku,0)),\"\"))",
                   f"=IF(D{i}=\"\",\"\",IFERROR(INDEX(Estoque!$C$2:$C${ULT_EST},MATCH(D{i},e_sku,0)),\"\"))", "Auto (banco)"])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:G{max(ws.max_row, 2)}"
    larguras(ws, [16, 38, 11, 22, 16, 11, 14])
    wb.defined_names["m_id"] = DefinedName("m_id", attr_text=ref("Campanha x SKU", "A", 2, ULT_MAP))
    wb.defined_names["m_cob"] = DefinedName("m_cob", attr_text=ref("Campanha x SKU", "E", 2, ULT_MAP))


def aba_insights(wb, insights):
    ws = wb.create_sheet("Insights")
    ws.sheet_properties.tabColor = "548235"
    ws.sheet_view.showGridLines = False
    cabecalho(ws, 1, ["Conta", "Data da análise", "Análise de IA (publicidade)"], 24)
    larguras(ws, [10, 15, 150])
    for i, r in enumerate(insights, 2):
        ws.cell(i, 1, CANAL_DA_CONTA.get(r["conta_id"], r["conta_id"].upper())).font = f_negrito
        d = ws.cell(i, 2, como_data(r["data"]))
        d.number_format, d.font = DATA_F, f_normal
        t = ws.cell(i, 3, r["texto"])
        t.font, t.alignment = f_normal, esq_wrap
        ws.row_dimensions[i].height = min(409, max(30, 14 * (len(r["texto"]) // 140 + r["texto"].count("\n") + 1)))
        for c in (1, 2):
            ws.cell(i, c).alignment = Alignment(vertical="top")


def aba_campanhas(wb, camp, fim):
    ws = wb.create_sheet("Campanhas", 1)
    ws.sheet_properties.tabColor = "C00000"
    ws.sheet_view.showGridLines = False
    ws["A1"], ws["A1"].font = "Campanhas: veredito por campanha", f_titulo
    ws["A2"], ws["A2"].font = "Período definido na aba Resumo. Regras e limites na aba Config.", f_sub
    ws["A3"], ws["A3"].font = "Canal", f_negrito
    ws["B3"] = "TODOS"
    ws["B3"].font, ws["B3"].fill, ws["B3"].alignment, ws["B3"].border = f_negrito, fill_input, centro, borda_box
    wb.defined_names["canal_sel"] = DefinedName("canal_sel", attr_text="Campanhas!$B$3")
    dv = DataValidation(type="list", formula1="=lista_canais", allow_blank=False)
    ws.add_data_validation(dv)
    dv.add("B3")
    ws["D3"], ws["D3"].font = "De", f_negrito
    ws["E3"], ws["E3"].number_format, ws["E3"].font = "=p_de", DATA_F, f_normal
    ws["F3"], ws["F3"].font = "Até", f_negrito
    ws["G3"], ws["G3"].number_format, ws["G3"].font = "=p_ate", DATA_F, f_normal
    heads = ["Canal", "Campanha", "Status", "Veredito", "Motivo", "Cobertura mín. (dias)", "ROAS", "Meta ROAS", "Investimento",
             "Receita", "ACOS", "Impressões", "Cliques", "CTR", "CPC", "Unid.", "CR", "Orçamento/dia", "Uso do orçamento",
             "ID campanha", "Último dia c/ dado", "Invest. avaliável", "Receita avaliável", "Cliques avaliáveis", "ROAS avaliável",
             "Visível", "Status do estoque"]
    cabecalho(ws, 6, heads, 36)
    # campanhas únicas (mais recente primeiro por investimento)
    info, invest = {}, defaultdict(float)
    for r in camp:
        cid = str(r["campaign_id"])
        info[cid] = (CANAL_DA_CONTA.get(r["conta_id"], r["conta_id"].upper()), r["nome"])
        invest[cid] += float(r["cost"] or 0)
    ordenadas = sorted(info, key=lambda k: (info[k][0], -invest[k]))[:N_CAMP]
    janela = lambda fim_expr: (f'd_id,$T{{r}},d_data,">="&p_de,d_data,"<="&{fim_expr}')  # noqa: E731
    for i in range(N_CAMP):
        r = PRIM_CAMP + i
        if i < len(ordenadas):
            cid = ordenadas[i]
            ws.cell(r, 1, info[cid][0])
            ws.cell(r, 2, info[cid][1])
            ws.cell(r, 20, cid)
        per = janela("p_ate").format(r=r)
        av = janela("(p_ate-dias_atraso)").format(r=r)
        perx = per.replace("d_id", "x_id").replace("d_data", "x_data")
        avx = av.replace("d_id", "x_id").replace("d_data", "x_data")
        dois = lambda nome, janela_d, janela_x: f"SUMIFS(d_{nome},{janela_d})+SUMIFS(x_{nome},{janela_x})"  # noqa: E731
        g = lambda f: f'=IF($T{r}="","",{f})'  # noqa: E731
        ws.cell(r, 21, g(f'IF(MAX(MAXIFS(d_data,d_id,$T{r}),MAXIFS(x_data,x_id,$T{r}))=0,"",MAX(MAXIFS(d_data,d_id,$T{r}),MAXIFS(x_data,x_id,$T{r})))'))
        ws.cell(r, 3, g(f'IF($U{r}="","",IF(COUNTIFS(d_id,$T{r},d_data,$U{r},d_status,"active")+COUNTIFS(x_id,$T{r},x_data,$U{r},x_status,"active")>0,"active","paused"))'))
        ws.cell(r, 8, g(f'IF($U{r}="","",SUMIFS(d_meta,d_id,$T{r},d_data,$U{r})+SUMIFS(x_meta,x_id,$T{r},x_data,$U{r}))'))
        ws.cell(r, 18, g(f'IF($U{r}="","",SUMIFS(d_orc,d_id,$T{r},d_data,$U{r})+SUMIFS(x_orc,x_id,$T{r},x_data,$U{r}))'))
        ws.cell(r, 9, g(dois("inv", per, perx)))
        ws.cell(r, 10, g(dois("rec", per, perx)))
        ws.cell(r, 7, g(f'IF(I{r}>0,J{r}/I{r},"")'))
        ws.cell(r, 11, g(f'IF(J{r}>0,I{r}/J{r},"")'))
        ws.cell(r, 12, g(dois("imp", per, perx)))
        ws.cell(r, 13, g(dois("cliques", per, perx)))
        ws.cell(r, 14, g(f'IF(L{r}>0,M{r}/L{r},"")'))
        ws.cell(r, 15, g(f'IF(M{r}>0,I{r}/M{r},"")'))
        ws.cell(r, 16, g(dois("un", per, perx)))
        ws.cell(r, 17, g(f'IF(M{r}>0,P{r}/M{r},"")'))
        ws.cell(r, 19, g(f'IF(AND(N(R{r})>0,COUNTIFS({per})+COUNTIFS({perx})>0),I{r}/(R{r}*(COUNTIFS({per})+COUNTIFS({perx}))),"")'))
        ws.cell(r, 22, g(dois("inv", av, avx)))
        ws.cell(r, 23, g(dois("rec", av, avx)))
        ws.cell(r, 24, g(dois("cliques", av, avx)))
        ws.cell(r, 25, g(f'IF(V{r}>0,W{r}/V{r},"")'))
        ws.cell(r, 26, g(f'OR(canal_sel="TODOS",$A{r}=canal_sel)'))
        ws.cell(r, 6, g(f'IF(COUNTIFS(m_id,$T{r},m_cob,">=0")=0,"",MINIFS(m_cob,m_id,$T{r}))'))
        ws.cell(r, 27, g(f'IF(F{r}="","",IF(F{r}<cob_critica,"Crítico",IF(F{r}<cob_ok,"Baixo","OK")))'))
        ws.cell(r, 4, g(
            f'IF(NOT(Z{r}),"",IF(U{r}="","Sem dados",IF(C{r}<>"active","Pausada",IF(I{r}=0,"Sem atividade",'
            f'IF(AND(F{r}<>"",N(F{r})<cob_critica),"PAUSAR / REDUZIR",IF(OR(V{r}<inv_min,X{r}<cliques_min),"AGUARDAR",'
            f'IF(W{r}=0,"ALERTA",IF(N(H{r})<=0,"SEM META",IF(Y{r}<H{r}*(1-tol_roas),"REVISAR",'
            f'IF(AND(S{r}<>"",N(S{r})>=pct_orc,OR(F{r}="",N(F{r})>=cob_ok)),"ESCALAR","MANTER"))))))))))'))
        ws.cell(r, 5, g(
            f'IF(D{r}="","",IF(D{r}="Sem dados","Nenhuma linha na aba Dados Ads",IF(D{r}="Pausada","Campanha pausada no Mercado Ads",'
            f'IF(D{r}="Sem atividade","Sem investimento no período",'
            f'IF(D{r}="PAUSAR / REDUZIR","Cobertura mínima de "&ROUND(F{r},0)&" dias (limite "&cob_critica&")",'
            f'IF(D{r}="AGUARDAR","Pouco volume: R$ "&ROUND(V{r},0)&" e "&ROUND(X{r},0)&" cliques (mín. R$ "&inv_min&" e "&cliques_min&")",'
            f'IF(D{r}="ALERTA","Investiu R$ "&ROUND(V{r},0)&" sem venda atribuída",'
            f'IF(D{r}="SEM META","Defina a meta de ROAS no Mercado Ads",'
            f'IF(D{r}="REVISAR","ROAS "&ROUND(Y{r},1)&"x abaixo da meta de "&ROUND(H{r},1)&"x",'
            f'IF(D{r}="ESCALAR","ROAS "&ROUND(Y{r},1)&"x na meta, "&ROUND(S{r}*100,0)&"% do orçamento usado, estoque ok",'
            f'"ROAS "&ROUND(Y{r},1)&"x na meta"&IF(AND(F{r}<>"",N(F{r})<cob_ok)," (estoque limita a escala)","")))))))))))'))
        formatos = {7: ROAS_F, 8: ROAS_F, 9: BRL, 10: BRL, 11: PCT, 12: INT, 13: INT, 14: "0.00%", 15: BRL, 16: INT, 17: "0.00%",
                    18: BRL, 19: PCT0, 21: DATA_F, 22: BRL, 23: BRL, 24: INT, 25: ROAS_F, 6: "0"}
        for col in range(1, 28):
            c = ws.cell(r, col)
            c.font, c.border = f_normal, borda
            if col in formatos:
                c.number_format = formatos[col]
            if col in (1, 3, 4, 6, 27):
                c.alignment = Alignment(horizontal="center", vertical="center")
        ws.cell(r, 4).font = f_negrito
        ws.cell(r, 5).alignment = Alignment(vertical="center", wrap_text=False)
        for col in (1, 2, 20):
            ws.cell(r, col).fill = fill_input
    larguras(ws, [11, 34, 9, 17, 52, 12, 9, 9, 13, 13, 8, 12, 9, 8, 9, 7, 8, 12, 11, 15, 12, 13, 13, 11, 11, 8, 11])
    ws.freeze_panes = "C7"
    ws.auto_filter.ref = f"A6:AA{ULT_CAMP}"
    for col in "TUVWXYZ":
        ws.column_dimensions[col].outlineLevel = 1
        ws.column_dimensions[col].hidden = False
    # formatação condicional (só referências da própria aba)
    cores = {"PAUSAR / REDUZIR": "F4B6B6", "ALERTA": "F4B6B6", "REVISAR": "F8CBAD", "AGUARDAR": "E7E6E6", "MANTER": "DDEBF7",
             "ESCALAR": "C6E0B4", "SEM META": "FFE699", "Pausada": "EDEDED", "Sem atividade": "EDEDED", "Sem dados": "EDEDED"}
    for texto, cor in cores.items():
        ws.conditional_formatting.add(f"D{PRIM_CAMP}:D{ULT_CAMP}", FormulaRule(formula=[f'$D{PRIM_CAMP}="{texto}"'], fill=PatternFill("solid", start_color=cor, end_color=cor)))
    for texto, cor in (("Crítico", "F4B6B6"), ("Baixo", "FFE699"), ("OK", "C6E0B4")):
        ws.conditional_formatting.add(f"F{PRIM_CAMP}:F{ULT_CAMP}", FormulaRule(formula=[f'$AA{PRIM_CAMP}="{texto}"'], fill=PatternFill("solid", start_color=cor, end_color=cor)))
    ws.conditional_formatting.add(f"G{PRIM_CAMP}:G{ULT_CAMP}", FormulaRule(formula=[f'AND($G{PRIM_CAMP}<>"",N($H{PRIM_CAMP})>0,$G{PRIM_CAMP}>=$H{PRIM_CAMP})'], font=Font(color="375623", bold=True)))
    ws.conditional_formatting.add(f"G{PRIM_CAMP}:G{ULT_CAMP}", FormulaRule(formula=[f'AND($G{PRIM_CAMP}<>"",N($H{PRIM_CAMP})>0,$G{PRIM_CAMP}<$H{PRIM_CAMP})'], font=Font(color="C00000", bold=True)))
    ws.conditional_formatting.add(f"A{PRIM_CAMP}:AA{ULT_CAMP}", FormulaRule(formula=[f'$Z{PRIM_CAMP}=FALSE'], font=Font(color="BFBFBF")))
    return ordenadas, info


def aba_resumo(wb, fim):
    ws = wb.create_sheet("Resumo", 1)
    ws.sheet_properties.tabColor = "1F3864"
    ws.sheet_view.showGridLines = False
    ws["A1"], ws["A1"].font = "Resumo de Ads", f_titulo
    ws["A2"], ws["A2"].font = "Todos os canais no período escolhido. Altere as datas nas células amarelas.", f_sub
    ws["A4"], ws["A4"].font = "De", f_negrito
    ws["B4"], ws["D4"] = fim - timedelta(days=6), fim
    for cel in ("B4", "D4"):
        ws[cel].number_format, ws[cel].fill, ws[cel].font, ws[cel].alignment, ws[cel].border = DATA_F, fill_input, f_negrito, centro, borda_box
    ws["C4"], ws["C4"].font = "até", f_negrito
    ws["C4"].alignment = centro
    ws["E4"], ws["E4"].font = "Dias", f_negrito
    ws["F4"] = "=D4-B4+1"
    ws["F4"].font, ws["F4"].alignment = f_negrito, centro
    wb.defined_names["p_de"] = DefinedName("p_de", attr_text="Resumo!$B$4")
    wb.defined_names["p_ate"] = DefinedName("p_ate", attr_text="Resumo!$D$4")
    wb.defined_names["p_dias"] = DefinedName("p_dias", attr_text="Resumo!$F$4")
    heads = ["Canal", "Investimento", "Receita (Ads)", "ROAS", "ACOS", "Impressões", "Cliques", "CTR", "CPC", "Unidades", "CR",
             "Faturamento total", "TACOS", "TACOS vs meta", "Invest. período anterior", "Δ Invest.", "Receita período anterior", "Δ Receita"]
    cabecalho(ws, 11, heads, 38)
    PR, UR, TR = 12, 12 + len(CANAIS) - 1, 12 + len(CANAIS)
    per = 'd_canal,$A{r},d_data,">="&p_de,d_data,"<="&p_ate'
    ant = 'd_canal,$A{r},d_data,">="&(p_de-p_dias),d_data,"<="&(p_de-1)'
    fper = 'f_canal,$A{r},f_data,">="&p_de,f_data,"<="&p_ate'
    perx = per.replace("d_canal", "x_canal").replace("d_data", "x_data")
    antx = ant.replace("d_canal", "x_canal").replace("d_data", "x_data")
    soma = lambda nome, a, b, r: f"=SUMIFS(d_{nome},{a.format(r=r)})+SUMIFS(x_{nome},{b.format(r=r)})"  # noqa: E731
    for i, canal in enumerate(CANAIS):
        r = PR + i
        ws.cell(r, 1, canal)
        ws.cell(r, 2, soma("inv", per, perx, r))
        ws.cell(r, 3, soma("rec", per, perx, r))
        ws.cell(r, 6, soma("imp", per, perx, r))
        ws.cell(r, 7, soma("cliques", per, perx, r))
        ws.cell(r, 10, soma("un", per, perx, r))
        ws.cell(r, 12, f"=SUMIFS(f_fat,{fper.format(r=r)})")
        ws.cell(r, 15, soma("inv", ant, antx, r))
        ws.cell(r, 17, soma("rec", ant, antx, r))
    for col in (1, 2, 3, 6, 7, 10, 12, 15, 17):
        ws.cell(TR, col, "TOTAL" if col == 1 else f"=SUM({get_column_letter(col)}{PR}:{get_column_letter(col)}{UR})")
    for r in range(PR, TR + 1):
        ws.cell(r, 4, f'=IF(B{r}>0,C{r}/B{r},"")')
        ws.cell(r, 5, f'=IF(C{r}>0,B{r}/C{r},"")')
        ws.cell(r, 8, f'=IF(F{r}>0,G{r}/F{r},"")')
        ws.cell(r, 9, f'=IF(G{r}>0,B{r}/G{r},"")')
        ws.cell(r, 11, f'=IF(G{r}>0,J{r}/G{r},"")')
        ws.cell(r, 13, f'=IF(L{r}>0,B{r}/L{r},"")')
        ws.cell(r, 14, f'=IF(M{r}="","",IF(M{r}<=meta_tacos,"Dentro da meta","Acima da meta"))')
        ws.cell(r, 16, f'=IF(O{r}>0,B{r}/O{r}-1,"")')
        ws.cell(r, 18, f'=IF(Q{r}>0,C{r}/Q{r}-1,"")')
        fm = {2: BRL, 3: BRL, 4: ROAS_F, 5: PCT, 6: INT, 7: INT, 8: "0.00%", 9: BRL, 10: INT, 11: "0.00%", 12: BRL, 13: PCT,
              15: BRL, 16: PCT0, 17: BRL, 18: PCT0}
        for col in range(1, 19):
            c = ws.cell(r, col)
            c.font = f_negrito if (r == TR or col == 1) else f_normal
            c.border = borda
            if col in fm:
                c.number_format = fm[col]
            if r == TR:
                c.fill = fill_total
            if col in (14,):
                c.alignment = Alignment(horizontal="center")
    ws.conditional_formatting.add(f"N{PR}:N{TR}", FormulaRule(formula=[f'$N{PR}="Dentro da meta"'], fill=PatternFill("solid", start_color="C6E0B4", end_color="C6E0B4")))
    ws.conditional_formatting.add(f"N{PR}:N{TR}", FormulaRule(formula=[f'$N{PR}="Acima da meta"'], fill=PatternFill("solid", start_color="F4B6B6", end_color="F4B6B6")))
    ws.conditional_formatting.add(f"R{PR}:R{TR}", FormulaRule(formula=[f'AND($R{PR}<>"",$R{PR}<0)'], font=Font(color="C00000")))
    ws.conditional_formatting.add(f"R{PR}:R{TR}", FormulaRule(formula=[f'AND($R{PR}<>"",$R{PR}>0)'], font=Font(color="375623")))
    # cartões
    cards = [("A", "C", "Investimento", f"=B{TR}", BRL0, f'=IF(O{TR}>0,"Anterior: R$ "&ROUND(O{TR},0)&" ("&ROUND(P{TR}*100,0)&"%)","")'),
             ("D", "F", "Receita (Ads)", f"=C{TR}", BRL0, f'=IF(Q{TR}>0,"Anterior: R$ "&ROUND(Q{TR},0)&" ("&ROUND(R{TR}*100,0)&"%)","")'),
             ("G", "I", "ROAS", f"=D{TR}", ROAS_F, '="Receita ÷ investimento"'),
             ("J", "L", "TACOS (Ads ÷ faturamento)", f"=M{TR}", "0.0%", f'=IF(M{TR}="","Sem faturamento no período",N{TR}&" ("&ROUND(meta_tacos*100,1)&"%)")')]
    for ini, fim_c, rot, formula, fmt, sub in cards:
        for linha in (6, 7, 8):
            ws.merge_cells(f"{ini}{linha}:{fim_c}{linha}")
        a, b, c = ws[f"{ini}6"], ws[f"{ini}7"], ws[f"{ini}8"]
        a.value, b.value, c.value = rot, formula, sub
        a.font, b.font, c.font = Font(name=FONTE, size=10, bold=True, color="595959"), f_card, f_sub
        b.number_format = fmt
        for x in (a, b, c):
            x.alignment = centro
        for col in range(ord(ini), ord(fim_c) + 1):
            for linha in (6, 7, 8):
                ws[f"{chr(col)}{linha}"].fill = fill_card
    ws.row_dimensions[7].height = 34
    # situação das campanhas
    ws["A22"], ws["A22"].font = "Situação das campanhas (aba Campanhas)", Font(name=FONTE, size=12, bold=True, color=AZUL)
    for i, v in enumerate(["PAUSAR / REDUZIR", "ALERTA", "REVISAR", "ESCALAR", "MANTER", "AGUARDAR", "SEM META"], 23):
        ws.cell(i, 1, v).font = f_negrito
        c = ws.cell(i, 2, f'=COUNTIF(Campanhas!$D${PRIM_CAMP}:$D${ULT_CAMP},A{i})')
        c.font, c.alignment = f_normal, centro
    # gráfico
    ch = BarChart()
    ch.type, ch.title, ch.style = "col", "Investimento x Receita por canal", 10
    ch.add_data(Reference(ws, min_col=2, max_col=3, min_row=11, max_row=UR), titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=1, min_row=PR, max_row=UR))
    ch.height, ch.width = 8, 18
    ws.add_chart(ch, "D22")
    larguras(ws, [24, 14, 14, 9, 9, 12, 10, 9, 10, 10, 9, 15, 9, 15, 15, 10, 15, 10])
    ws.freeze_panes = "A12"


# --- validação ----------------------------------------------------------------------------------------------------
def validar(wb):
    nomes = set(wb.defined_names.keys())
    erros, n = [], 0
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if isinstance(v, str) and v.startswith("="):
                    n += 1
                    try:
                        tok = Tokenizer(v)
                    except Exception as e:  # noqa: BLE001
                        erros.append((ws.title, c.coordinate, f"não tokeniza: {e}"))
                        continue
                    if v.count("(") != v.count(")"):
                        erros.append((ws.title, c.coordinate, "parênteses desbalanceados"))
                    for t in tok.items:
                        if t.type == "OPERAND" and t.subtype == "RANGE" and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", t.value) \
                                and not re.fullmatch(r"[A-Z]{1,3}\d+", t.value) and t.value not in nomes:
                            erros.append((ws.title, c.coordinate, f"nome desconhecido {t.value}"))
    return n, erros


def espelho(camp, mapa, saldos, vend30, ordenadas, info, fim):
    """Recalcula o veredito em Python com as mesmas regras, só para conferir o resultado esperado e mostrar um resumo."""
    dias_atraso, inv_min, cliq_min, cob_c, cob_ok, pct_orc, tol = 2, 30, 30, 7, 15, 0.9, 0
    de, ate = fim - timedelta(days=6), fim
    cob_sku = {}
    for sku in {r["sku"] for r in mapa}:
        s = float((saldos.get(sku) or ("", 0))[1] or 0)
        rit = vend30.get(sku, 0.0) / 30
        cob_sku[sku] = 0 if s <= 0 else (999 if rit == 0 else s / rit)
    cob_camp = defaultdict(list)
    for r in mapa:
        cob_camp[str(r["campaign_id"])].append(cob_sku[r["sku"]])
    saida = {}
    for cid in ordenadas:
        linhas = [r for r in camp if str(r["campaign_id"]) == cid]
        per = [r for r in linhas if de <= como_data(r["data"]) <= ate]
        av = [r for r in linhas if de <= como_data(r["data"]) <= ate - timedelta(days=dias_atraso)]
        ult = max(como_data(r["data"]) for r in linhas)
        ult_l = [r for r in linhas if como_data(r["data"]) == ult]
        ativa = any(r["status"] == "active" for r in ult_l)
        meta = sum(float(r["roas_target"] or 0) for r in ult_l)
        orc = sum(float(r["budget"] or 0) for r in ult_l)
        inv = sum(float(r["cost"] or 0) for r in per)
        invv, recv, clv = (sum(float(r[k] or 0) for r in av) for k in ("cost", "total_amount", "clicks"))
        dias = len(per)
        uso = inv / (orc * dias) if orc > 0 and dias else None
        cob = min(cob_camp[cid]) if cob_camp.get(cid) else None
        roas_av = recv / invv if invv > 0 else None
        if not ativa: v = "Pausada"
        elif inv == 0: v = "Sem atividade"
        elif cob is not None and cob < cob_c: v = "PAUSAR / REDUZIR"
        elif invv < inv_min or clv < cliq_min: v = "AGUARDAR"
        elif recv == 0: v = "ALERTA"
        elif meta <= 0: v = "SEM META"
        elif roas_av < meta * (1 - tol): v = "REVISAR"
        elif uso is not None and uso >= pct_orc and (cob is None or cob >= cob_ok): v = "ESCALAR"
        else: v = "MANTER"
        saida[cid] = (info[cid][0], info[cid][1], v, None if cob is None else round(cob, 1), None if roas_av is None else round(roas_av, 2), meta)
    return saida


def main():
    caminho = Path(sys.argv[1]) if len(sys.argv) > 1 else SAIDA_PADRAO
    fim, camp, fat, mapa, saldos, vend30, insights = carregar()
    wb = Workbook()
    aba_leia_me(wb)
    aba_config(wb)
    aba_dados(wb, camp)
    aba_manual(wb)
    aba_faturamento(wb, fat)
    aba_estoque(wb, mapa, saldos, vend30)
    aba_mapa(wb, camp, mapa)
    aba_insights(wb, insights)
    ordenadas, info = aba_campanhas(wb, camp, fim)
    aba_resumo(wb, fim)
    wb._sheets = [wb[n] for n in ["Leia-me", "Resumo", "Campanhas", "Config", "Dados Ads", "Entrada Manual", "Faturamento", "Estoque", "Campanha x SKU", "Insights"]]
    n, erros = validar(wb)
    print(f"{n} fórmulas conferidas; problemas: {erros if erros else 'nenhum'}")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    wb.save(caminho)
    print("salvo em", caminho)
    print("\nVeredito esperado hoje (mesmas regras, calculado em Python):")
    for cid, (canal, nome, v, cob, roas, meta) in espelho(camp, mapa, saldos, vend30, ordenadas, info, fim).items():
        print(f"  {canal:7} {nome[:34]:34} {v:17} cobertura={cob} roas={roas} meta={meta}")


if __name__ == "__main__":
    main()
