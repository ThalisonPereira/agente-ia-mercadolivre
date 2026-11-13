"""
scripts/analise_curva_a.py

Planilha "Curva A: onde focar" (xlsx): para a lista de SKUs da curva A, cruza a meta de novembro e o ritmo do mês (Sales Navigator,
todos os canais), o estoque REAL (kits limitados pelo componente que falta), o desempenho no Mercado Livre (visitas, conversão,
contas com anúncio) e os Ads, e diz em cada SKU onde agir para vender mais. Só lê (banco do agente, arquivo local de vendas do Bling e
o JSON com os dados do Sales Navigator); nada é gravado nem enviado.

Entrada: dados_locais/curva_a_sales_navigator.json (gerado a partir do Sales Navigator em 11/11/2026).
Uso: python scripts/analise_curva_a.py [caminho_de_saida.xlsx]
"""

import importlib.util
import json
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402

from database.conexao_supabase import obter_conexao  # noqa: E402

ENTRADA = RAIZ / "dados_locais" / "curva_a_sales_navigator.json"
SAIDA_PADRAO = RAIZ / "dados_locais" / "Curva_A_Onde_Focar.xlsx"
DIAS_MES = 30
COB_CURTA = 15      # dias de cobertura abaixo dos quais o estoque é curto
COB_OFERTA = 45     # a partir daqui há folga para oferta agressiva
VIS_BAIXA = 150     # visitas em 60 dias no ML abaixo das quais falta tráfego
CONV_BAIXA = 0.004  # conversão (unidades/visitas) abaixo da qual o tráfego não converte

AZUL = "1F3864"
f_cab = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
f_n = Font(name="Calibri", size=10)
f_b = Font(name="Calibri", size=10, bold=True)
fill_cab = PatternFill("solid", start_color=AZUL, end_color=AZUL)
fino = Side(style="thin", color="D9D9D9")
CORES = {"SEM ESTOQUE": "F4B6B6", "ESTOQUE LIMITA A META": "F8CBAD", "ATRASADO (demanda)": "FFE699",
         "QUASE NO RITMO": "DDEBF7", "NO RITMO": "C6E0B4"}


def carregar_json():
    j = json.loads(ENTRADA.read_text(encoding="utf-8"))
    return date.fromisoformat(j["dados_ate"]), [dict(zip(j["campos"], l)) for l in j["linhas"]]


def modulo_ml():
    spec = importlib.util.spec_from_file_location("oferta", RAIZ / "scripts" / "analise_skus_oferta.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def ads_por_sku(fim):
    """SKU -> {investimento 7d, campanhas ativas}. SKU do anúncio: cadastro ou, se vazio, o das vendas do mesmo anúncio."""
    c = obter_conexao()
    ini = (fim - timedelta(days=7)).isoformat()
    ultimo = c.execute("select max(data) m from ads_campanhas_diario").fetchone()["m"]
    linhas = c.execute(
        "with vendas as (select conta_id, item_id, max(nullif(sku,'')) sku from itens_venda group by 1,2) "
        "select upper(coalesce(nullif(an.sku,''), v.sku)) sku, a.conta_id, a.campaign_id, max(cm.nome) nome, "
        "sum(a.cost) inv, bool_or(cm.status = 'active' and cm.data = %(u)s) ativa "
        "from ads_anuncios_diario a left join anuncios an on an.conta_id=a.conta_id and an.item_id=a.item_id "
        "left join vendas v on v.conta_id=a.conta_id and v.item_id=a.item_id "
        "left join ads_campanhas_diario cm on cm.conta_id=a.conta_id and cm.campaign_id=a.campaign_id and cm.data=a.data "
        "where a.data >= %(i)s and coalesce(nullif(an.sku,''), v.sku) is not null group by 1,2,3", {"u": ultimo, "i": ini}).fetchall()
    saida = defaultdict(lambda: {"inv": 0.0, "camps": set()})
    for r in linhas:
        s = saida[r["sku"]]
        s["inv"] += float(r["inv"] or 0)
        if r["ativa"]:
            s["camps"].add(f"{r['conta_id'].upper()}: {r['nome']}")
    return saida


def janelas(skus, fim):
    """Por SKU (Mercado Livre): visitas e unidades de 1-10/out x 1-10/nov e o maior estoque PUBLICADO entre os anúncios."""
    c = obter_conexao()
    n = (fim - date(fim.year, fim.month, 1)).days  # dias completos de novembro
    o_ini, o_fim = date(fim.year, fim.month - 1, 1).isoformat(), date(fim.year, fim.month - 1, n).isoformat()
    n_ini, n_fim = date(fim.year, fim.month, 1).isoformat(), (fim - timedelta(days=1)).isoformat()
    rows = c.execute(
        "with vendas as (select conta_id, item_id, max(nullif(sku,'')) sku from itens_venda group by 1,2), "
        "it as (select an.conta_id, an.item_id, upper(coalesce(nullif(an.sku,''), v.sku)) sku, an.estoque_disponivel pub, an.status "
        "       from anuncios an left join vendas v on v.conta_id=an.conta_id and v.item_id=an.item_id) "
        "select it.sku, max(it.pub) filter (where it.status='active') pub_max, "
        " coalesce(sum(h.visitas) filter (where h.data_snapshot between %(oi)s and %(of)s),0) vo, "
        " coalesce(sum(h.visitas) filter (where h.data_snapshot between %(ni)s and %(nf)s),0) vn, "
        " coalesce(sum(h.vendas_quantidade) filter (where h.data_snapshot between %(oi)s and %(of)s),0) uo, "
        " coalesce(sum(h.vendas_quantidade) filter (where h.data_snapshot between %(ni)s and %(nf)s),0) un "
        "from it left join historico_anuncios_diario h on h.conta_id=it.conta_id and h.item_id=it.item_id "
        "where it.sku = ANY(%(s)s) group by 1",
        {"oi": o_ini, "of": o_fim, "ni": n_ini, "nf": n_fim, "s": [x.upper() for x in skus]}).fetchall()
    return {r["sku"]: {"pub": r["pub_max"], "vo": int(r["vo"]), "vn": int(r["vn"]), "uo": int(r["uo"]), "un": int(r["un"]), "n": n} for r in rows}


def componentes(txt):
    """'12028x3(37), 12064x1(0)' -> [(12028, 3, 37), (12064, 1, 0)]"""
    out = []
    for parte in txt.split(", "):
        m = re.match(r"^(.*)x(\d+)\((\?|\d+)\)$", parte.strip())
        if m:
            out.append((m.group(1), int(m.group(2)), None if m.group(3) == "?" else int(m.group(3))))
    return out


def analisar():
    fim, linhas = carregar_json()
    dias = (fim - date(fim.year, fim.month, 1)).days + 0.5  # dias completos + o dia de hoje pela metade
    oferta = modulo_ml()
    _, ml_linhas, conv_med, vis_med, ml_lista = oferta.analisar()
    ml = {l["sku"].upper(): l for l in ml_linhas}
    anuncios = defaultdict(list)
    for a in ml_lista:
        anuncios[a["sku"].upper()].append(a)
    ads = ads_por_sku(fim)
    jan = janelas([r["sku"] for r in linhas], fim)
    saida = []
    for r in linhas:
        sku = r["sku"].upper()
        meta = r["meta_nov"]
        comps = componentes(r["composicao"])
        limit = None
        if comps:
            limit = min(comps, key=lambda c: ((c[2] or 0) // c[1]) if c[2] is not None else 10**9)
        disp = r["disp_real"] or 0
        preco = (r["br_nov"] / r["un_nov"]) if r["un_nov"] else ((r["br_out"] / r["un_out"]) if r["un_out"] else 0.0)
        ritmo = r["un_nov"] / dias
        proj_demanda = ritmo * DIAS_MES
        proj = proj_demanda if disp > 0 else r["un_nov"]
        proj = min(proj, r["un_nov"] + disp)
        ref_ritmo = max(ritmo, r["un_out"] / 31)
        cob = None if disp <= 0 else (999 if ref_ritmo == 0 else disp / ref_ritmo)
        pct = (proj / meta) if meta else None
        gap = max(0.0, (meta or 0) - proj)
        m = ml.get(sku, {})
        ats = anuncios.get(sku, [])
        contas = sorted({a["conta"] for a in ats})
        a_ = ads.get(sku, {"inv": 0.0, "camps": set()})
        j = jan.get(sku, {})
        vis60, conv = m.get("vis60", 0), m.get("conv")
        # situação
        if disp <= 0:
            sit = "SEM ESTOQUE"
        elif meta and r["un_nov"] + disp < meta:
            sit = "ESTOQUE LIMITA A META"
        elif pct is None or pct >= 0.95:
            sit = "NO RITMO"
        elif pct >= 0.8:
            sit = "QUASE NO RITMO"
        else:
            sit = "ATRASADO (demanda)"
        # foco
        foco = []
        lim_txt = f"{limit[0]} ({limit[2]} un)" if limit and limit[2] is not None else ""
        alerta = []
        if j and j.get("uo", 0) >= 3 and j["vn"] >= 0.7 * j["vo"] and j["un"] <= 0.3 * j["uo"]:
            alerta.append(f"QUEDA DE CONVERSÃO: tráfego mantido ({j['vo']}→{j['vn']} visitas) e vendas {j['uo']}→{j['un']} no ML (1-{j['n']}/nov contra 1-{j['n']}/out); veja preço, concorrência e se acabou promoção")
        elif j and j.get("vo", 0) >= 30 and j["vn"] < 0.6 * j["vo"]:
            alerta.append(f"QUEDA DE TRÁFEGO: visitas {j['vo']}→{j['vn']} (1-{j['n']}/nov contra 1-{j['n']}/out); revise posição, título e Ads")
        if j and j.get("pub") is not None and disp >= 20 and j["pub"] < 0.3 * disp:
            alerta.append(f"ESTOQUE PUBLICADO baixo: anúncio mostra {j['pub']} un e o Bling tem {disp}; atualize o anúncio")
        foco.extend(alerta)
        if sit == "SEM ESTOQUE":
            falta = [f"{c[0]}" for c in comps if (c[2] or 0) // c[1] <= 0]
            foco.append(f"REPOR: zerado ({', '.join(falta) or r['sku']}). Em outubro vendeu {r['un_out']} un (R$ {r['br_out']:,.0f}); a venda está travada".replace(",", "."))
        elif sit == "ESTOQUE LIMITA A META":
            repor = max(0, meta - r["un_nov"] - disp)
            foco.append(f"REPOR ~{repor} un: com {disp} un disponíveis ({lim_txt}) não fecha a meta de {meta}; cobertura de {cob:.0f} dias")
        elif sit in ("ATRASADO (demanda)", "QUASE NO RITMO"):
            if vis60 and vis60 < VIS_BAIXA:
                foco.append(f"TRÁFEGO: só {vis60} visitas no ML em 60 dias; Ads e anúncio nas contas que ainda não têm")
            elif vis60 and conv is not None and conv < CONV_BAIXA:
                foco.append(f"CONVERSÃO: {vis60} visitas e só {conv:.2%} convertem; rever preço, fotos e frete")
            elif not ats:
                foco.append("Sem anúncio ativo no Mercado Livre identificado para este SKU")
            if cob is not None and cob >= COB_OFERTA:
                foco.append(f"OFERTA AGRESSIVA: estoque para {'mais de 999' if cob >= 999 else f'{cob:.0f}'} dias")
        if ats and len(contas) < 3 and sit in ("ATRASADO (demanda)", "QUASE NO RITMO", "NO RITMO") and disp > 0 and not sku.endswith("SHOP"):
            faltam = [c for c in ("CC", "HC", "WC") if c not in contas]
            foco.append(f"Anúncio só em {'/'.join(contas)}: replicar em {'/'.join(faltam)}")
        if sit in ("ATRASADO (demanda)", "QUASE NO RITMO") and a_["inv"] == 0 and disp > 0:
            foco.append("Sem Ads nos últimos 7 dias")
        if r["sh_out"] == 0 and r["sh_nov"] == 0 and r["ml_out"] >= 5 and disp > 0 and sit != "SEM ESTOQUE" and not sku.endswith("SHOP"):
            foco.append("Não vende na Shopee: testar anúncio lá")
        if sit == "NO RITMO":
            foco.append("No ritmo da meta" + ("; estoque confortável: dá para escalar com Ads" if cob and cob >= COB_OFERTA else ""))
        var = (r["un_nov"] / dias * DIAS_MES / r["un_out"] - 1) if r["un_out"] else None
        saida.append({**r, "sku_u": sku, "dias": dias, "ritmo": ritmo, "proj": proj, "pct": pct, "gap": gap, "gap_r": gap * preco, "preco": preco,
                      "cob": cob, "j": j, "limit": lim_txt, "var": var, "vis60": vis60, "conv": conv, "contas": "/".join(contas), "n_anuncios": len(ats),
                      "ads_inv": a_["inv"], "camps": "; ".join(sorted(a_["camps"])), "sit": sit, "foco": " | ".join(foco) or "-",
                      "mlbs": ", ".join(a["mlb"] for a in ats), "anuncios": ats})
    return fim, saida, conv_med, vis_med


def escrever(caminho, fim, linhas):
    wb = Workbook()
    ws = wb.active
    ws.title = "Foco"
    heads = ["Prioridade", "Curva A (posição)", "SKU", "Fornecedor", "Situação", "Onde focar", "Meta nov", "Un. até hoje", "Ritmo (un/dia)",
             "Projeção do mês", "% da meta", "Faltam (un)", "Faltam (R$)", "Un. outubro", "Variação vs out.", "Preço médio",
             "Disponível real", "Cobertura (dias)", "Componente limitante", "ML un. nov", "Shopee un. nov", "Visitas ML 60d", "Conversão ML",
             "Anúncios (contas)", "Ads 7d (R$)", "Campanhas ativas", "Última venda", "Composição (saldo)", "IDs MLB", "Visitas ML 1-10/out", "Visitas ML 1-10/nov", "Vendas ML 1-10/out", "Vendas ML 1-10/nov", "Estoque publicado (máx.)"]
    ws.append(heads)
    for i in range(1, len(heads) + 1):
        c = ws.cell(1, i)
        c.font, c.fill, c.alignment = f_cab, fill_cab, Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 36
    ordem = sorted(linhas, key=lambda x: (-x["gap_r"], x["ord"]))
    for p, r in enumerate(ordem, 1):
        ws.append([p, r["ord"], r["sku"], r["fornecedor"], r["sit"], r["foco"], r["meta_nov"], r["un_nov"], round(r["ritmo"], 2), round(r["proj"], 1),
                   r["pct"], round(r["gap"], 1), round(r["gap_r"], 2), r["un_out"], r["var"], round(r["preco"], 2), r["disp_real"],
                   None if r["cob"] is None else round(r["cob"]), r["limit"], r["ml_nov"], r["sh_nov"], r["vis60"], r["conv"],
                   f"{r['n_anuncios']} ({r['contas']})" if r["n_anuncios"] else "0", round(r["ads_inv"], 2), r["camps"],
                   date.fromisoformat(r["ultima_venda"]), r["composicao"], r["mlbs"],
                   r["j"].get("vo"), r["j"].get("vn"), r["j"].get("uo"), r["j"].get("un"), r["j"].get("pub")])
    fm = {11: "0%", 13: '"R$" #,##0', 15: "0%", 16: '"R$" #,##0.00', 23: "0.00%", 25: '"R$" #,##0.00', 27: "dd/mm/yyyy"}
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for c in row:
            c.font, c.border = f_n, Border(bottom=fino)
            if c.column in fm:
                c.number_format = fm[c.column]
        row[2].font = f_b
        row[4].fill = PatternFill("solid", start_color=CORES[row[4].value], end_color=CORES[row[4].value])
        row[5].alignment = Alignment(wrap_text=True, vertical="top")
    for i, w in enumerate([9, 9, 18, 18, 22, 90, 8, 9, 9, 10, 8, 9, 11, 9, 10, 11, 10, 10, 20, 9, 10, 10, 10, 14, 10, 40, 12, 34, 40, 11, 11, 11, 11, 11], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(heads))}{ws.max_row}"

    wa = wb.create_sheet("Anúncios (MLB)")
    h2 = ["SKU", "Situação do SKU", "ID do anúncio (MLB)", "Conta", "Título", "Visitas 60d", "Unidades 60d", "Receita 60d", "Conversão", "Estoque publicado", "Link"]
    wa.append(h2)
    for i in range(1, len(h2) + 1):
        c = wa.cell(1, i)
        c.font, c.fill, c.alignment = f_cab, fill_cab, Alignment(horizontal="center", vertical="center", wrap_text=True)
    for r in ordem:
        for a in sorted(r["anuncios"], key=lambda x: -x["vis60"]):
            wa.append([r["sku"], r["sit"], a["mlb"], a["conta"], a["titulo"], a["vis60"], a["un60"], round(a["rec60"], 2), a["conv"], a["pub"],
                       f"https://produto.mercadolivre.com.br/MLB-{a['mlb'].replace('MLB', '')}"])
    for row in wa.iter_rows(min_row=2, max_row=wa.max_row):
        for c in row:
            c.font, c.border = f_n, Border(bottom=fino)
        row[2].number_format, row[7].number_format, row[8].number_format = "@", '"R$" #,##0.00', "0.00%"
        row[1].fill = PatternFill("solid", start_color=CORES[row[1].value], end_color=CORES[row[1].value])
    for i, w in enumerate([18, 22, 18, 7, 60, 10, 10, 13, 10, 11, 50], 1):
        wa.column_dimensions[get_column_letter(i)].width = w
    wa.freeze_panes = "C2"
    wa.auto_filter.ref = f"A1:K{wa.max_row}"

    wl = wb.create_sheet("Leia-me", 0)
    wl.sheet_view.showGridLines = False
    wl.column_dimensions["A"].width = 3
    wl.column_dimensions["B"].width = 32
    wl.column_dimensions["C"].width = 110
    wl["B2"] = "Curva A: onde focar para vender mais"
    wl["B2"].font = Font(name="Calibri", size=16, bold=True, color=AZUL)
    wl["B3"] = f"Meta e vendas de novembro até {fim:%d/%m/%Y} (todos os canais, Sales Navigator); estoque do Bling; ML = Mercado Livre WC+HC+CC."
    wl["B3"].font = Font(name="Calibri", size=10, italic=True, color="595959")
    cont = defaultdict(lambda: [0, 0.0])
    for r in linhas:
        cont[r["sit"]][0] += 1
        cont[r["sit"]][1] += r["gap_r"]
    regras = {"SEM ESTOQUE": "Estoque real zerado (em kit, o componente que falta zera o kit). A venda está travada: reposição é a prioridade, antes de qualquer oferta.",
              "ESTOQUE LIMITA A META": "Tem estoque, mas ele não cobre a meta do mês (vendidos + disponível < meta).",
              "ATRASADO (demanda)": "Estoque ok, mas a projeção do mês fica abaixo de 80% da meta: o problema é demanda (tráfego, conversão, preço ou cobertura de contas).",
              "QUASE NO RITMO": "Projeção entre 80% e 95% da meta.",
              "NO RITMO": "Projeção a partir de 95% da meta."}
    r_ = 5
    wl.cell(r_, 2, "Situação").font = f_b
    wl.cell(r_, 3, "Regra  |  SKUs  |  falta para a meta (R$)").font = f_b
    for k, texto in regras.items():
        r_ += 1
        c = wl.cell(r_, 2, k)
        c.font, c.fill = f_b, PatternFill("solid", start_color=CORES[k], end_color=CORES[k])
        n, v = cont[k]
        t = wl.cell(r_, 3, f"{texto}  |  {n} SKUs  |  R$ {v:,.0f}".replace(",", "."))
        t.font, t.alignment = f_n, Alignment(wrap_text=True, vertical="top")
        wl.row_dimensions[r_].height = 30
    notas = ["Projeção do mês = ritmo atual × 30 dias, limitada pelo estoque (vendidos + disponível). Para SKU sem estoque, projeção = o que já vendeu.",
             "Disponível real: para kits, é o menor saldo entre os componentes (÷ quantidade usada). O saldo do kit no Bling é virtual.",
             "Faltam (R$) = unidades que faltam para a meta × preço médio do mês (ou de outubro, se ainda não vendeu em novembro). Ordena a aba Foco.",
             "Cobertura = disponível ÷ ritmo (o maior entre o ritmo de novembro e o de outubro).",
             "Visitas e conversão são do Mercado Livre (soma por anúncio, ~15% acima das visitas únicas do ML). SKUs sem anúncio no ML (ex.: sufixo SHOP) aparecem com 0.",
             "Os SKUs de kit compartilham peças: repor o 12064, por exemplo, destrava 12064 e os kits 12064.3.12028, 12064.3.12063, 12064.4.12063 e 12064.4.12028."]
    r_ += 2
    for n in notas:
        wl.cell(r_, 2, "•").alignment = Alignment(horizontal="right", vertical="top")
        t = wl.cell(r_, 3, n)
        t.font, t.alignment = f_n, Alignment(wrap_text=True, vertical="top")
        wl.row_dimensions[r_].height = 28
        r_ += 1
    caminho.parent.mkdir(parents=True, exist_ok=True)
    wb.save(caminho)
    return cont, ordem


def main():
    caminho = Path(sys.argv[1]) if len(sys.argv) > 1 else SAIDA_PADRAO
    fim, linhas, conv_med, vis_med = analisar()
    cont, ordem = escrever(caminho, fim, linhas)
    print(f"salvo em {caminho} | {len(linhas)} SKUs | dados até {fim}")
    for k in CORES:
        n, v = cont[k]
        print(f"  {k:24} {n:3} SKUs   falta para a meta R$ {v:,.0f}")
    print("\nTop 12 por valor que falta para a meta:")
    for r in ordem[:12]:
        print(f"  {r['sku']:16} {r['sit']:22} meta={r['meta_nov']} vendeu={r['un_nov']} proj={r['proj']:.0f} faltam R$ {r['gap_r']:,.0f} | {r['foco'][:90]}")


if __name__ == "__main__":
    main()
