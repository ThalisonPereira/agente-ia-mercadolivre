"""
scripts/analise_skus_oferta.py

Planilha "Análise de SKUs para oferta" (xlsx): por SKU, nos últimos 60 dias do Mercado Livre (3 contas): visitas,
unidades, receita, conversão, tendência, margem estimada e estoque do Bling, com uma CLASSIFICAÇÃO de onde faz sentido
uma oferta agressiva (estoque sobrando + margem para desconto + tráfego) e onde NÃO (estoque curto ou sem estoque).
Só lê o banco (e o arquivo local de vendas do Bling); nada é gravado nem enviado.

Uso: python scripts/analise_skus_oferta.py [caminho_de_saida.xlsx]
"""

import sqlite3
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openpyxl import Workbook  # noqa: E402
from openpyxl.formatting.rule import FormulaRule  # noqa: E402
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402

from database.conexao_supabase import obter_conexao  # noqa: E402

SAIDA_PADRAO = Path(__file__).resolve().parent.parent / "dados_locais" / "Analise_SKUs_Oferta.xlsx"
IMPOSTO = 0.14  # mesma alíquota do extrato de margem (database/extrato.py)
# --- limites das regras (ajustáveis) ---
COB_SOBRANDO = 60          # dias de cobertura a partir dos quais o estoque "sobra"
COB_CURTO = 15             # abaixo disso não se promove
MARGEM_MIN = 0.15          # margem mínima (sobre o preço bruto) para ter folga de desconto
USAR_MARGEM = False        # False: a margem só informa (coluna), não exclui SKU de oferta (pedido do usuário em 11/11/2026)
MIN_UNID_TENDENCIA = 5     # unidades nos 30 dias anteriores para falar em queda
QUEDA = 0.70               # últimos 30 dias < 70% dos 30 anteriores = em queda

AZUL = "1F3864"
f_cab = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
f_n = Font(name="Calibri", size=10)
fill_cab = PatternFill("solid", start_color=AZUL, end_color=AZUL)
fino = Side(style="thin", color="D9D9D9")
CORES = {"OFERTA AGRESSIVA": "C6E0B4", "OFERTA: TRÁFEGO SEM CONVERSÃO": "DDEBF7", "RECUPERAR: EM QUEDA": "FFE699",
         "ESTOQUE SOBRANDO: POUCO TRÁFEGO": "E2EFDA", "ESTOQUE SOBRANDO: MARGEM BAIXA": "FCE4D6",
         "PROTEGER: ESTOQUE CURTO": "F8CBAD", "SEM ESTOQUE": "F4B6B6", "MANTER": "FFFFFF", "SEM SKU / SEM DADO": "EDEDED"}


def d(v):
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def carregar():
    c = obter_conexao()
    fim = d(c.execute("select max(data_snapshot) m from historico_anuncios_diario").fetchone()["m"])
    ini60, ini30 = fim - timedelta(days=59), fim - timedelta(days=29)
    ant_ini = ini60
    p = {"i60": ini60.isoformat(), "i30": ini30.isoformat(), "f": fim.isoformat()}
    # anúncios ativos e o SKU de cada um (cadastro, senão o das vendas do mesmo anúncio)
    skus_vendas = {(r["conta_id"], r["item_id"]): r["sku"] for r in c.execute(
        "select conta_id, item_id, max(nullif(sku,'')) sku from itens_venda group by 1,2").fetchall() if r["sku"]}
    anuncios = {}
    for r in c.execute("select conta_id, item_id, titulo, sku, status, estoque_disponivel from anuncios").fetchall():
        sku = (r["sku"] or "").strip() or skus_vendas.get((r["conta_id"], r["item_id"]), "")
        anuncios[(r["conta_id"], r["item_id"])] = {"titulo": r["titulo"], "sku": sku.upper(), "status": r["status"], "pub": r["estoque_disponivel"]}
    visitas = defaultdict(lambda: [0, 0])  # (conta,item) -> [visitas60, visitas30]
    for r in c.execute("select conta_id, item_id, data_snapshot d, visitas from historico_anuncios_diario where data_snapshot between %(i60)s and %(f)s", p).fetchall():
        v = visitas[(r["conta_id"], r["item_id"])]
        v[0] += r["visitas"] or 0
        if str(r["d"]) >= p["i30"]:
            v[1] += r["visitas"] or 0
    vendas = c.execute(
        "select conta_id, item_id, data_venda d, pedido_id, quantidade, preco_venda, comissao_ml, frete_vendedor, custo_unitario_capturado, sku "
        "from itens_venda where status in ('pago','pago_com_reclamacao') and data_venda between %(i60)s and %(f)s", p).fetchall()
    custos = {r["sku"].upper(): float(r["preco_custo"] or 0) for r in c.execute("select sku, preco_custo from custo_produtos").fetchall()}
    saldos = {r["sku"].upper(): (r["nome"], r["estoque_saldo"]) for r in c.execute("select sku, nome, estoque_saldo from custo_produtos where estoque_saldo is not null").fetchall()}
    ult_banco = {(r["conta_id"], r["item_id"]): d(r["m"]) for r in c.execute(
        "select conta_id, item_id, max(data_venda) m from itens_venda where status in ('pago','pago_com_reclamacao') group by 1,2").fetchall()}
    c.close() if hasattr(c, "close") else None
    lite = sqlite3.connect(Path(__file__).resolve().parent.parent / "dados_locais" / "vendas_bling.db")
    ritmo = {r[0].upper(): float(r[1]) for r in lite.execute(
        "select i.sku, sum(i.quantidade) from itens i join pedidos p on p.pedido_id=i.pedido_id where p.conta_venda=1 and p.detalhe_ok=1 "
        "and COALESCE(p.data_venda,p.data_bling) >= ? and coalesce(i.sku,'')<>'' group by 1", ((fim - timedelta(days=29)).isoformat(),)).fetchall()}
    lite.close()
    return fim, ini30, anuncios, visitas, vendas, custos, saldos, ritmo, ult_banco


def analisar():
    fim, ini30, anuncios, visitas, vendas, custos, saldos, ritmo, ult_banco = carregar()
    sku_de = lambda conta, item, sku_linha: ((sku_linha or "").strip().upper() or anuncios.get((conta, item), {}).get("sku", ""))  # noqa: E731
    skus = defaultdict(lambda: {"anuncios": set(), "titulo": "", "vis60": 0, "vis30": 0, "un60": 0, "un30": 0, "unAnt": 0, "rec60": 0.0,
                                "ped": set(), "liq": 0.0, "custo": 0.0, "ultima": None, "pub": 0})
    for (conta, item), a in anuncios.items():
        if a["status"] != "active":
            continue
        s = skus[a["sku"] or "(sem SKU)"]
        s["anuncios"].add((conta, item))
        s["titulo"] = s["titulo"] or a["titulo"]
        s["pub"] += a["pub"] or 0
        v = visitas.get((conta, item), [0, 0])
        s["vis60"] += v[0]
        s["vis30"] += v[1]
    por_item = defaultdict(lambda: [0, 0.0])
    for r in vendas:
        pi = por_item[(r["conta_id"], r["item_id"])]
        pi[0] += r["quantidade"] or 0
        pi[1] += float(r["preco_venda"] or 0)
        sku = sku_de(r["conta_id"], r["item_id"], r["sku"]) or "(sem SKU)"
        s = skus[sku]
        q, bruto = r["quantidade"] or 0, float(r["preco_venda"] or 0)
        s["un60"] += q
        if str(r["d"]) >= ini30.isoformat():
            s["un30"] += q
        else:
            s["unAnt"] += q
        s["rec60"] += bruto
        s["ped"].add((r["conta_id"], r["pedido_id"]))
        liq = bruto - float(r["comissao_ml"] or 0) - float(r["frete_vendedor"] or 0) - bruto * IMPOSTO
        cu = float(r["custo_unitario_capturado"] or 0) or custos.get(sku, 0.0)
        s["liq"] += liq
        s["custo"] += cu * q if cu else 0.0
        s["comcusto"] = s.get("comcusto", 0.0) + (bruto if cu else 0.0)
        dv = d(r["d"])
        s["ultima"] = dv if s["ultima"] is None or dv > s["ultima"] else s["ultima"]
    linhas = []
    convs = sorted(s["un60"] / s["vis60"] for s in skus.values() if s["vis60"] >= 100 and s["un60"] >= 0)
    conv_med = convs[len(convs) // 2] if convs else 0
    vis_ord = sorted(s["vis60"] for s in skus.values() if s["vis60"] > 0)
    vis_med = vis_ord[len(vis_ord) // 2] if vis_ord else 0
    for sku, s in skus.items():
        nome, saldo = saldos.get(sku, ("", None))
        saldo = float(saldo) if saldo is not None else None
        rit = ritmo.get(sku, 0.0) / 30
        cob = None if saldo is None else (0 if saldo <= 0 else (999 if rit == 0 else saldo / rit))
        preco = s["rec60"] / s["un60"] if s["un60"] else None
        margem = ((s["liq"] - s["custo"]) / s["rec60"]) if s["rec60"] and s.get("comcusto", 0) >= 0.9 * s["rec60"] else None
        conv = s["un60"] / s["vis60"] if s["vis60"] else None
        queda = s["unAnt"] >= MIN_UNID_TENDENCIA and s["un30"] < QUEDA * s["unAnt"]
        if sku == "(sem SKU)" or saldo is None:
            cat, motivo = "SEM SKU / SEM DADO", "SKU não identificado ou sem saldo no Bling"
        elif saldo <= 0:
            cat, motivo = "SEM ESTOQUE", "Saldo zerado no Bling"
        elif cob is not None and cob < COB_CURTO:
            cat, motivo = "PROTEGER: ESTOQUE CURTO", f"Cobertura de {cob:.0f} dias: oferta aceleraria a ruptura"
        elif cob >= COB_SOBRANDO and (not USAR_MARGEM or margem is None or margem >= MARGEM_MIN) and s["vis60"] >= vis_med:
            cat, motivo = "OFERTA AGRESSIVA", f"Estoque para {('mais de 999' if cob >= 999 else f'{cob:.0f}')} dias, tráfego acima da mediana" + ("" if margem is None else f", margem {margem:.0%}")
        elif s["vis60"] >= vis_med and conv is not None and conv_med and conv < 0.5 * conv_med and (not USAR_MARGEM or margem is None or margem >= MARGEM_MIN):
            cat, motivo = "OFERTA: TRÁFEGO SEM CONVERSÃO", f"Conversão {conv:.2%} contra mediana de {conv_med:.2%} com bom tráfego"
        elif queda:
            cat, motivo = "RECUPERAR: EM QUEDA", f"Vendas dos últimos 30 dias em {s['un30']} un contra {s['unAnt']} nos 30 anteriores"
        elif USAR_MARGEM and cob >= COB_SOBRANDO and margem is not None and margem < MARGEM_MIN:
            cat, motivo = "ESTOQUE SOBRANDO: MARGEM BAIXA", f"Estoque para {('mais de 999' if cob >= 999 else f'{cob:.0f}')} dias, mas margem de {margem:.0%}: sem folga para desconto (revise custo ou preço)"
        elif cob >= COB_SOBRANDO:
            cat, motivo = "ESTOQUE SOBRANDO: POUCO TRÁFEGO", f"Estoque para {('mais de 999' if cob >= 999 else f'{cob:.0f}')} dias, mas só {s['vis60']} visitas em 60 dias: falta visibilidade (anúncio, Ads) antes do desconto"
        else:
            cat, motivo = "MANTER", "Sem sinal claro para oferta"
        linhas.append({"sku": sku, "desc": nome or s["titulo"], "anuncios": len(s["anuncios"]), "ids": ", ".join(sorted(i for _, i in s["anuncios"])), "vis60": s["vis60"], "un60": s["un60"],
                       "ped": len(s["ped"]), "rec60": s["rec60"], "conv": conv, "preco": preco, "un30": s["un30"], "unAnt": s["unAnt"],
                       "margem": margem, "saldo": saldo, "rit": rit, "cob": cob, "ultima": s["ultima"],
                       "est_valor": (saldo * preco) if (saldo and preco) else None, "cat": cat, "motivo": motivo})
    cat_do_sku = {l["sku"]: l["cat"] for l in linhas}
    lista = []
    for (conta, item), a in anuncios.items():
        if a["status"] != "active":
            continue
        sku = a["sku"] or "(sem SKU)"
        v = visitas.get((conta, item), [0, 0])
        un, rec = por_item.get((conta, item), [0, 0.0])
        lista.append({"cat": cat_do_sku.get(sku, ""), "sku": sku, "mlb": item, "conta": conta.upper(), "titulo": a["titulo"], "vis60": v[0],
                      "un60": un, "rec60": rec, "conv": (un / v[0]) if v[0] else None, "pub": a["pub"],
                      "ultima": ult_banco.get((conta, item)), "origem": "banco" if (conta, item) in ult_banco else "", "vendas_total": None})
    return fim, linhas, conv_med, vis_med, lista


def buscar_api(lista, log=print):
    """Data exata da última venda PAGA (orders/search por anúncio) dos anúncios sem venda no banco + vendas totais (sold_quantity) de todos.
    Só leitura. Guarda em dados_locais/ultima_venda_cache.json para não repetir chamadas."""
    import json
    from integrations.canais import obter_adaptador
    from integrations.canais.mercado_livre import BASE_URL
    cache_path = Path(__file__).resolve().parent.parent / "dados_locais" / "ultima_venda_cache.json"
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    por_conta = defaultdict(list)
    for l in lista:
        por_conta[l["conta"].lower()].append(l)
    for conta, itens in por_conta.items():
        a = obter_adaptador(conta, "mercado_livre")
        seller = a.obter_id_vendedor()
        # vendas totais (multi-get, 20 por chamada)
        for i in range(0, len(itens), 20):
            lote = itens[i:i + 20]
            r = a._get_com_retry(f"{BASE_URL}/items", params={"ids": ",".join(x["mlb"] for x in lote), "attributes": "id,sold_quantity"}, rotulo="vendas_totais", repetir_403=True)
            r.raise_for_status()
            vt = {e["body"]["id"]: e["body"].get("sold_quantity") for e in r.json() if e.get("code") == 200}
            for x in lote:
                x["vendas_total"] = vt.get(x["mlb"])
        faltam = [x for x in itens if x["ultima"] is None]
        log(f"[{conta}] {len(itens)} anúncios; buscando a última venda de {len(faltam)} na API...")
        for n, x in enumerate(faltam, 1):
            chave = f"{conta}:{x['mlb']}"
            if chave in cache and cache[chave].get("em") == date.today().isoformat():
                dado = cache[chave]
            else:
                r = a._get_com_retry(f"{BASE_URL}/orders/search", params={"seller": seller, "item": x["mlb"], "order.status": "paid", "sort": "date_desc", "limit": 1}, rotulo="ultima_venda")
                if r.status_code != 200:
                    continue
                j = r.json()
                res = j.get("results", [])
                dado = {"data": res[0]["date_created"][:10] if res else None, "total": j.get("paging", {}).get("total", 0), "em": date.today().isoformat()}
                cache[chave] = dado
            x["ultima"] = date.fromisoformat(dado["data"]) if dado["data"] else None
            x["origem"] = "API" if dado["data"] else "sem venda paga"
            if n % 100 == 0:
                log(f"  {conta}: {n}/{len(faltam)}")
        cache_path.write_text(json.dumps(cache), encoding="utf-8")


def escrever(caminho, fim, linhas, conv_med, vis_med, lista):
    wb = Workbook()
    ws = wb.active
    ws.title = "SKUs"
    heads = ["Classificação", "SKU", "Descrição", "Anúncios ativos", "Visitas 60d", "Unidades 60d", "Pedidos 60d", "Receita bruta 60d",
             "Conversão (un/visitas)", "Preço médio", "Un. últimos 30d", "Un. 30d anteriores", "Variação", "Margem estimada",
             "Saldo Bling", "Ritmo (un/dia)", "Cobertura (dias)", "Estoque a preço de venda", "Última venda", "Motivo", "IDs dos anúncios (MLB)", "Dias sem vender"]
    ws.append(heads)
    for i in range(1, len(heads) + 1):
        c = ws.cell(1, i)
        c.font, c.fill, c.alignment = f_cab, fill_cab, Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 34
    ordem = {k: i for i, k in enumerate(CORES)}
    for l in sorted(linhas, key=lambda x: (ordem[x["cat"]], -(x["est_valor"] or 0), -(x["rec60"] or 0))):
        var = (l["un30"] / l["unAnt"] - 1) if l["unAnt"] else None
        ws.append([l["cat"], l["sku"], l["desc"], l["anuncios"], l["vis60"], l["un60"], l["ped"], round(l["rec60"], 2), l["conv"],
                   None if l["preco"] is None else round(l["preco"], 2), l["un30"], l["unAnt"], var, l["margem"], l["saldo"],
                   round(l["rit"], 2), None if l["cob"] is None else round(l["cob"]), None if l["est_valor"] is None else round(l["est_valor"], 2),
                   l["ultima"], l["motivo"], l["ids"], (date.today() - l["ultima"]).days if l["ultima"] else None])
    fm = {8: '"R$" #,##0.00', 9: "0.00%", 10: '"R$" #,##0.00', 13: "0%", 14: "0%", 15: "#,##0", 16: "0.00", 17: "0", 18: '"R$" #,##0.00', 19: "dd/mm/yyyy", 5: "#,##0", 6: "#,##0"}
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for c in row:
            c.font, c.border = f_n, Border(bottom=fino)
            if c.column in fm:
                c.number_format = fm[c.column]
    for cat, cor in CORES.items():
        ws.conditional_formatting.add(f"A2:A{ws.max_row}", FormulaRule(formula=[f'$A2="{cat}"'], fill=PatternFill("solid", start_color=cor, end_color=cor)))
    for i, w in enumerate([30, 18, 44, 9, 10, 10, 9, 14, 12, 12, 10, 11, 10, 11, 10, 10, 11, 15, 12, 70, 40, 12], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:V{ws.max_row}"

    wa = wb.create_sheet("Anúncios", 1)
    heads_a = ["Classificação do SKU", "SKU", "ID do anúncio (MLB)", "Conta", "Título", "Visitas 60d", "Unidades 60d", "Receita bruta 60d",
               "Conversão (un/visitas)", "Estoque publicado", "Última venda", "Dias sem vender", "Origem da data", "Vendas totais (histórico ML)", "Link"]
    wa.append(heads_a)
    for i in range(1, len(heads_a) + 1):
        c = wa.cell(1, i)
        c.font, c.fill, c.alignment = f_cab, fill_cab, Alignment(horizontal="center", vertical="center", wrap_text=True)
    wa.row_dimensions[1].height = 34
    ordem_a = {k: i for i, k in enumerate(CORES)}
    for l in sorted(lista, key=lambda x: (ordem_a.get(x["cat"], 99), x["sku"], -x["vis60"])):
        wa.append([l["cat"], l["sku"], l["mlb"], l["conta"], l["titulo"], l["vis60"], l["un60"], round(l["rec60"], 2), l["conv"], l["pub"],
                   l["ultima"], (date.today() - l["ultima"]).days if l["ultima"] else None, l["origem"], l["vendas_total"],
                   f"https://produto.mercadolivre.com.br/MLB-{l['mlb'].replace('MLB', '')}"])
    for row in wa.iter_rows(min_row=2, max_row=wa.max_row):
        for c in row:
            c.font, c.border = f_n, Border(bottom=fino)
        row[5].number_format, row[6].number_format, row[7].number_format, row[8].number_format = "#,##0", "#,##0", '"R$" #,##0.00', "0.00%"
        row[2].number_format = "@"
        row[10].number_format = "dd/mm/yyyy"
        row[13].number_format = "#,##0"
    for cat, cor in CORES.items():
        wa.conditional_formatting.add(f"A2:A{wa.max_row}", FormulaRule(formula=[f'$A2="{cat}"'], fill=PatternFill("solid", start_color=cor, end_color=cor)))
    for i, w in enumerate([30, 18, 20, 7, 60, 10, 10, 14, 12, 11, 12, 11, 14, 14, 52], 1):
        wa.column_dimensions[get_column_letter(i)].width = w
    wa.freeze_panes = "D2"
    wa.auto_filter.ref = f"A1:O{wa.max_row}"

    resumo = wb.create_sheet("Leia-me", 0)
    resumo.sheet_view.showGridLines = False
    resumo.column_dimensions["A"].width = 3
    resumo.column_dimensions["B"].width = 34
    resumo.column_dimensions["C"].width = 105
    resumo["B2"] = "Análise de SKUs para oferta agressiva"
    resumo["B2"].font = Font(name="Calibri", size=16, bold=True, color=AZUL)
    resumo["B3"] = f"Mercado Livre (WC, HC e CC), últimos 60 dias até {fim:%d/%m/%Y}. Só anúncios ativos; vendas pagas (sem cancelados)."
    resumo["B3"].font = Font(name="Calibri", size=10, italic=True, color="595959")
    cont = defaultdict(lambda: [0, 0.0])
    for l in linhas:
        cont[l["cat"]][0] += 1
        cont[l["cat"]][1] += l["est_valor"] or 0
    regras = {
        "OFERTA AGRESSIVA": f"Estoque cobre {COB_SOBRANDO}+ dias e tráfego acima da mediana ({vis_med} visitas em 60 dias). A margem aparece na coluna, mas não exclui o SKU. Prioridade 1.",
        "OFERTA: TRÁFEGO SEM CONVERSÃO": f"Tráfego acima da mediana e conversão menos da metade da mediana ({conv_med:.2%}), com estoque ok: o preço ou o anúncio não convence quem visita.",
        "ESTOQUE SOBRANDO: POUCO TRÁFEGO": f"Estoque cobre {COB_SOBRANDO}+ dias, mas tráfego abaixo da mediana: o problema é visibilidade; teste Ads, título e foto junto com a oferta.",
        "ESTOQUE SOBRANDO: MARGEM BAIXA": f"Estoque cobre {COB_SOBRANDO}+ dias, mas margem estimada abaixo de {MARGEM_MIN:.0%}: desconto agressivo dá prejuízo. Revise custo (fornecedor) ou preço-base.",
        "RECUPERAR: EM QUEDA": f"Vendas dos últimos 30 dias abaixo de {QUEDA:.0%} dos 30 anteriores (mínimo de {MIN_UNID_TENDENCIA} un. antes) e estoque disponível.",
        "PROTEGER: ESTOQUE CURTO": f"Cobertura abaixo de {COB_CURTO} dias: não promover; a oferta só aceleraria a ruptura.",
        "SEM ESTOQUE": "Saldo zerado no Bling. Se o anúncio segue ativo, revise o saldo ou pause.",
        "MANTER": "Sem sinal claro para oferta agora.",
        "SEM SKU / SEM DADO": "O anúncio não tem SKU identificável ou o SKU não tem saldo no Bling.",
    }
    r = 5
    resumo.cell(r, 2, "Classificação").font = resumo.cell(r, 3, "Regra").font = Font(name="Calibri", size=10, bold=True)
    resumo.cell(r, 3, "Regra  |  SKUs  |  estoque a preço de venda").font = Font(name="Calibri", size=10, bold=True)
    for cat, texto in regras.items():
        if cat == "ESTOQUE SOBRANDO: MARGEM BAIXA" and not USAR_MARGEM:
            continue
        r += 1
        c = resumo.cell(r, 2, cat)
        c.font, c.fill = Font(name="Calibri", size=10, bold=True), PatternFill("solid", start_color=CORES[cat], end_color=CORES[cat])
        n, v = cont[cat]
        t = resumo.cell(r, 3, f"{texto}  |  {n} SKUs  |  R$ {v:,.0f}".replace(",", "."))
        t.font, t.alignment = f_n, Alignment(wrap_text=True, vertical="top")
        resumo.row_dimensions[r].height = 30
    notas = ["Margem estimada = (preço - comissão ML - frete - imposto de 14% - custo do Bling) ÷ preço, só quando a venda tem custo cadastrado.",
             "Cobertura = saldo do Bling ÷ ritmo de venda de 30 dias de TODOS os canais (kits não são abertos em peças: o ritmo de componentes pode estar subestimado).",
             "Visitas são a soma por anúncio (o ML conta visitantes únicos, ~15% menos). Conversão = unidades ÷ visitas.",
             "Estoque a preço de venda = saldo × preço médio praticado: quanto de faturamento está parado, para ordenar as ofertas.",
             "ATENÇÃO: kits compartilham o estoque físico dos componentes (o saldo do kit no Bling é virtual). Não some o 'estoque a preço de venda' de um SKU com o dos seus kits: o mesmo produto aparece nos dois."]
    r += 2
    for n in notas:
        resumo.cell(r, 2, "•").alignment = Alignment(horizontal="right")
        t = resumo.cell(r, 3, n)
        t.font, t.alignment = f_n, Alignment(wrap_text=True, vertical="top")
        resumo.row_dimensions[r].height = 28
        r += 1
    caminho.parent.mkdir(parents=True, exist_ok=True)
    wb.save(caminho)
    return cont


def main():
    caminho = Path(sys.argv[1]) if len(sys.argv) > 1 else SAIDA_PADRAO
    fim, linhas, conv_med, vis_med, lista = analisar()
    if "--sem-api" not in sys.argv:
        buscar_api(lista)
    ultima_sku = {}
    for l in lista:
        if l["ultima"] and (l["sku"] not in ultima_sku or l["ultima"] > ultima_sku[l["sku"]]):
            ultima_sku[l["sku"]] = l["ultima"]
    for l in linhas:
        cands = [x for x in (l["ultima"], ultima_sku.get(l["sku"])) if x]
        l["ultima"] = max(cands) if cands else None
    cont = escrever(caminho, fim, linhas, conv_med, vis_med, lista)
    print(f"salvo em {caminho} | janela até {fim} | {len(linhas)} SKUs | {len(lista)} anúncios ativos | mediana de visitas {vis_med}, conversão mediana {conv_med:.2%}")
    for cat in CORES:
        n, v = cont[cat]
        print(f"  {cat:32} {n:4} SKUs   estoque a preço de venda R$ {v:,.0f}")


if __name__ == "__main__":
    main()
