"""
integrations/google_sheets_ads.py

Publicidade (Mercado Ads) no Google Sheets: duas abas de DADOS (regravadas por
inteiro a cada rodada, últimos 90 dias, todas as contas juntas) e uma aba
"Painel Ads" feita de FÓRMULAS sobre elas, com diagnósticos por regra.

O painel é criado uma única vez (criar_painel_ads) e NUNCA é regravado pela
rotina diária - assim os filtros e parâmetros que o usuário ajustar na
planilha não são sobrescritos. Reaproveita a autenticação e a planilha de
integrations/google_sheets.py (mesma conta de serviço, mesmo GOOGLE_SHEETS_ID).

As fórmulas usam a sintaxe da API do Sheets (nomes em inglês, vírgulas).
"""

import gspread

from integrations.google_sheets import _obter_ou_criar_aba, _obter_planilha

ABA_ADS_CAMPANHAS = "Ads Campanhas"
ABA_ADS_ANUNCIOS = "Ads Anúncios"
ABA_PAINEL_ADS = "Painel Ads"

CABECALHO_ADS_CAMPANHAS = [
    "Data", "Conta", "Campanha", "ID", "Status", "Orçamento/dia (R$)", "Meta ROAS", "Meta ACOS (%)",
    "Impressões", "Cliques", "Investimento (R$)", "Receita direta (R$)", "Receita indireta (R$)",
    "Receita total (R$)", "Unid. diretas", "Unid. indiretas", "Unid. totais",
]

CABECALHO_ADS_ANUNCIOS = [
    "Data", "Conta", "ID anúncio", "ID campanha", "Anúncio", "Status", "Impressões", "Cliques",
    "Investimento (R$)", "Receita direta (R$)", "Receita indireta (R$)", "Receita total (R$)", "Unidades",
]

LINHAS_PAINEL = 60  # campanhas que o painel comporta (linhas de fórmula)
PRIMEIRA_LINHA_PAINEL = 13
ULTIMA_LINHA_PAINEL = PRIMEIRA_LINHA_PAINEL + LINHAS_PAINEL - 1
LINHAS_SERIE = 91
COLUNAS_PAINEL = "ABCDEFGHIJKLMNOPQRSTUVWXY"

CABECALHO_PAINEL = [
    "Conta", "ID", "Campanha", "Status", "Orçamento/dia", "Meta ROAS", "Meta ACOS", "Investimento", "Receita",
    "ROAS", "ACOS", "Impressões", "Cliques", "CTR", "CPC", "Vendas diretas (R$)", "Vendas indiretas (R$)",
    "Unid. diretas", "Unid. indiretas", "Diagnóstico", "Último dia c/ dado", "Invest. avaliável",
    "Receita avaliável", "Cliques avaliáveis", "Dias avaliáveis",
]


def _numero(valor, casas: int = 2):
    """None vira célula vazia (ausente != 0 real); número vira float arredondado."""
    if valor is None:
        return ""
    return round(float(valor), casas)


def montar_linhas_ads_campanhas(campanhas: list[dict]) -> list[list]:
    linhas = [CABECALHO_ADS_CAMPANHAS]
    for c in campanhas:
        linhas.append([
            c["data"], c["conta_id"], c["nome"], c["campaign_id"], c["status"],
            _numero(c["budget"]), _numero(c["roas_target"]), _numero(c["acos_target"]),
            c["prints"], c["clicks"], _numero(c["cost"]),
            _numero(c["direct_amount"]), _numero(c["indirect_amount"]), _numero(c["total_amount"]),
            c["direct_units_quantity"], c["indirect_units_quantity"], c["units_quantity"],
        ])
    return linhas


def montar_linhas_ads_anuncios(anuncios: list[dict]) -> list[list]:
    linhas = [CABECALHO_ADS_ANUNCIOS]
    for a in anuncios:
        linhas.append([
            a["data"], a["conta_id"], a["item_id"], a["campaign_id"], a["titulo"], a["status"],
            a["prints"], a["clicks"], _numero(a["cost"]),
            _numero(a["direct_amount"]), _numero(a["indirect_amount"]), _numero(a["total_amount"]),
            a["units_quantity"],
        ])
    return linhas


_IDIOMAS_PONTO_E_VIRGULA = {
    "pt", "de", "fr", "it", "nl", "ru", "pl", "tr", "sv", "da", "nb", "fi", "cs", "sk", "hu", "ro", "bg",
    "el", "uk", "id", "vi", "es",
}
_LOCALES_VIRGULA_MESMO_COM_IDIOMA = {"es_MX", "es_US", "es_419"}


def usa_ponto_e_virgula(locale: str) -> bool:
    """
    Planilhas em localidades com vírgula decimal (ex: pt_BR) exigem ";" entre os
    argumentos das fórmulas, mesmo escritas pela API (confirmado na planilha real:
    com vírgula, dá "Formula parse error"). Nas demais (ex: en_US) vale a vírgula.
    """
    if locale in _LOCALES_VIRGULA_MESMO_COM_IDIOMA:
        return False
    return locale.split("_")[0].lower() in _IDIOMAS_PONTO_E_VIRGULA


def localizar_formula(formula, locale: str):
    """
    Converte uma fórmula escrita com vírgulas (sintaxe en_US) para a localidade da planilha:
    argumentos separados por ";" e, dentro de {...}, colunas separadas por "\\" (como no pt_BR).
    Vírgulas dentro de textos entre aspas ficam como estão. Valores que não são fórmulas passam direto.
    """
    if not isinstance(formula, str) or not formula.startswith("=") or not usa_ponto_e_virgula(locale):
        return formula
    saida, em_texto, chaves = [], False, 0
    for ch in formula:
        if ch == '"':
            em_texto = not em_texto
        elif not em_texto:
            if ch == "{":
                chaves += 1
            elif ch == "}":
                chaves -= 1
            elif ch == ",":
                saida.append("\\" if chaves > 0 else ";")
                continue
        saida.append(ch)
    return "".join(saida)


def _localizar_conteudo(valor, locale: str):
    if isinstance(valor, list):
        return [_localizar_conteudo(v, locale) for v in valor]
    return localizar_formula(valor, locale)


def _escrever_aba_bruta(planilha, titulo: str, valores: list[list]) -> None:
    aba = _obter_ou_criar_aba(planilha, titulo, linhas=len(valores) + 100, colunas=len(valores[0]) + 1)
    aba.clear()
    if aba.row_count < len(valores) + 50:
        aba.resize(rows=len(valores) + 100)
    # raw=False (USER_ENTERED): datas "AAAA-MM-DD" viram datas de verdade, que o painel filtra por período.
    aba.update(values=valores, range_name="A1", raw=False)
    print(f"{len(valores) - 1} linha(s) publicada(s) na aba '{aba.title}'.")


def publicar_ads_no_sheets(campanhas: list[dict], anuncios: list[dict]) -> None:
    """Regrava as duas abas brutas de publicidade (todas as contas, últimos 90 dias)."""
    planilha = _obter_planilha()
    _escrever_aba_bruta(planilha, ABA_ADS_CAMPANHAS, montar_linhas_ads_campanhas(campanhas))
    _escrever_aba_bruta(planilha, ABA_ADS_ANUNCIOS, montar_linhas_ads_anuncios(anuncios))


def _rng(coluna: str) -> str:
    """Intervalo aberto de uma coluna da aba de campanhas (a partir da linha 2)."""
    return f"'{ABA_ADS_CAMPANHAS}'!${coluna}$2:${coluna}"


def montar_formulas_painel(r: int) -> dict[str, str]:
    """Fórmulas da linha `r` do painel (colunas D..Y). A:C vêm do spill da fórmula de chaves."""
    a, b = f"$A{r}", f"$B{r}"
    chave = f"{_rng('B')},{a},{_rng('D')},{b}"
    periodo = f'{_rng("A")},">="&$B$4,{_rng("A")},"<="&$B$5'
    ate_aval = f'{_rng("A")},">="&$B$4,{_rng("A")},"<="&($B$5-$B$6)'
    vazio = f'IF({a}="","",'

    def soma(coluna: str, filtro_data: str) -> str:
        return f"={vazio}SUMIFS({_rng(coluna)},{chave},{filtro_data}))"

    diagnostico = (
        f"={vazio}"
        f'IF($D{r}="paused","Pausada (status no último dia do período)",'
        f'IF(AND($H{r}=0,$L{r}=0,$M{r}=0),"Sem atividade no período",'
        f'IF(OR($V{r}<$B$7,$X{r}<$B$8),"Volume insuficiente para avaliar",'
        f'IF($W{r}=0,"Investimento sem vendas atribuídas",'
        f'IF($F{r}=0,"Sem meta de ROAS configurada",'
        f'IF($W{r}/$V{r}<$F{r},"ROAS abaixo da meta",'
        f"IF(AND($E{r}>0,$V{r}/MAX($Y{r},1)>=$B$9*$E{r}),"
        f'"ROAS na meta e orçamento quase esgotado","ROAS na meta"))))))))'
    )
    return {
        "D": f'={vazio}IFERROR(INDEX(FILTER({_rng("E")},{_rng("B")}={a},{_rng("D")}={b},{_rng("A")}=$U{r}),1),""))',
        "E": soma("F", f"{_rng('A')},$U{r}"),
        "F": soma("G", f"{_rng('A')},$U{r}"),
        "G": f"={vazio}SUMIFS({_rng('H')},{chave},{_rng('A')},$U{r})/100)",
        "H": soma("K", periodo),
        "I": soma("N", periodo),
        "J": f'={vazio}IF($H{r}>0,$I{r}/$H{r},"—"))',
        "K": f'={vazio}IF($I{r}>0,$H{r}/$I{r},"—"))',
        "L": soma("I", periodo),
        "M": soma("J", periodo),
        "N": f'={vazio}IF($L{r}>0,$M{r}/$L{r},"—"))',
        "O": f'={vazio}IF($M{r}>0,$H{r}/$M{r},"—"))',
        "P": soma("L", periodo),
        "Q": soma("M", periodo),
        "R": soma("O", periodo),
        "S": soma("P", periodo),
        "T": diagnostico,
        "U": f'={vazio}MAXIFS({_rng("A")},{_rng("B")},{a},{_rng("D")},{b},{_rng("A")},"<="&$B$5,{_rng("A")},">="&$B$4))',
        "V": soma("K", ate_aval),
        "W": soma("N", ate_aval),
        "X": soma("J", ate_aval),
        "Y": f"={vazio}MAX(0,($B$5-$B$6)-$B$4+1))",
    }


def montar_valores_painel() -> dict:
    """Todo o conteúdo (valores e fórmulas) do painel, sem tocar na API - testável offline."""
    chaves = (
        f"=IFERROR(SORT(UNIQUE(FILTER({{{_rng('B')},{_rng('D')},{_rng('C')}}},"
        f'(({_rng("B")}=$B$3)+($B$3="todas")>0)*({_rng("A")}>=$B$4)*({_rng("A")}<=$B$5)*({_rng("A")}<>""))),'
        f'1,TRUE,3,TRUE),"")'
    )
    topo = [
        ["Painel de Publicidade (Mercado Ads)", "", ""],
        ["Dados: abas 'Ads Campanhas' e 'Ads Anúncios' (últimos 90 dias, atualizadas pela rotina diária). Altere as células amarelas.", "", ""],
        ["Conta (todas, ou o código da conta)", "todas", ""],
        ["De", "=TODAY()-30", ""],
        ["Até (o dado mais recente costuma ser o dia anterior)", "=TODAY()-1", ""],
        ["Dias recentes a ignorar nos diagnósticos", 2, "A atribuição de vendas pode chegar com atraso; os últimos dias não entram nos diagnósticos."],
        ["Investimento mínimo para avaliar (R$)", 30, "Abaixo disso o diagnóstico é 'Volume insuficiente'. Ajuste conforme sua operação."],
        ["Cliques mínimos para avaliar", 30, "Idem."],
        ["Orçamento 'quase esgotado' a partir de (fração do orçamento diário)", 0.9, "Gasto médio diário ÷ orçamento/dia."],
        ["Última data coletada", f"=MAX({_rng('A')})", '=IF(B10<TODAY()-2,"⚠ dados desatualizados","ok")'],
    ]
    aviso = (
        f'=IF(COUNTA(A{PRIMEIRA_LINHA_PAINEL}:A)>{LINHAS_PAINEL},'
        f'"⚠ há mais de {LINHAS_PAINEL} campanhas no filtro: copie as fórmulas das linhas para baixo","")'
    )
    formulas = {r: montar_formulas_painel(r) for r in range(PRIMEIRA_LINHA_PAINEL, ULTIMA_LINHA_PAINEL + 1)}
    matriz = [
        [formulas[r][c] for c in COLUNAS_PAINEL[3:]]  # colunas D..Y
        for r in range(PRIMEIRA_LINHA_PAINEL, ULTIMA_LINHA_PAINEL + 1)
    ]
    serie = [["Data", "Investimento", "Receita"]]
    for i in range(LINHAS_SERIE):
        r = PRIMEIRA_LINHA_PAINEL + i
        serie.append([
            f'=IF($B$4+{i}>$B$5,"",$B$4+{i})',
            f'=IF($AA{r}="","",SUMIFS({_rng("K")},{_rng("A")},$AA{r},{_rng("B")},IF($B$3="todas","*",$B$3)))',
            f'=IF($AA{r}="","",SUMIFS({_rng("N")},{_rng("A")},$AA{r},{_rng("B")},IF($B$3="todas","*",$B$3)))',
        ])
    return {
        "topo": topo,
        "aviso": aviso,
        "cabecalho": CABECALHO_PAINEL,
        "chaves": chaves,
        "formulas_d_y": matriz,
        "serie": serie,
    }


def _requests_formatacao(sheet_id: int, contas_ids: list[str]) -> list[dict]:
    def cel(l1, l2, c1, c2):  # 0-based, fim exclusivo
        return {"sheetId": sheet_id, "startRowIndex": l1, "endRowIndex": l2, "startColumnIndex": c1, "endColumnIndex": c2}

    def formato(intervalo, tipo, padrao):
        return {"repeatCell": {
            "range": intervalo,
            "cell": {"userEnteredFormat": {"numberFormat": {"type": tipo, "pattern": padrao}}},
            "fields": "userEnteredFormat.numberFormat",
        }}

    ini, fim = PRIMEIRA_LINHA_PAINEL - 1, ULTIMA_LINHA_PAINEL
    col = {c: i for i, c in enumerate(COLUNAS_PAINEL)}
    reqs = [
        {"repeatCell": {
            "range": cel(2, 9, 1, 2),
            "cell": {"userEnteredFormat": {"backgroundColor": {"red": 1, "green": 0.96, "blue": 0.7}}},
            "fields": "userEnteredFormat.backgroundColor",
        }},
        {"repeatCell": {
            "range": cel(0, 1, 0, 1),
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "fontSize": 14}}},
            "fields": "userEnteredFormat.textFormat",
        }},
        {"repeatCell": {
            "range": cel(PRIMEIRA_LINHA_PAINEL - 2, PRIMEIRA_LINHA_PAINEL - 1, 0, len(COLUNAS_PAINEL)),
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9}}},
            "fields": "userEnteredFormat(textFormat,backgroundColor)",
        }},
        {"setDataValidation": {
            "range": cel(2, 3, 1, 2),
            "rule": {
                "condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": v} for v in ["todas", *contas_ids]]},
                "showCustomUi": True, "strict": True,
            },
        }},
        formato(cel(3, 5, 1, 2), "DATE", "dd/mm/yyyy"),
        formato(cel(9, 10, 1, 2), "DATE", "dd/mm/yyyy"),
        formato(cel(6, 7, 1, 2), "CURRENCY", '"R$" #,##0.00'),
        formato(cel(8, 9, 1, 2), "PERCENT", "0%"),
    ]
    for letras, tipo, padrao in (
        ("EHIOPQ", "CURRENCY", '"R$" #,##0.00'),
        ("GKN", "PERCENT", "0.0%"),
        ("FJ", "NUMBER", '0.00"x"'),
        ("LMRS", "NUMBER", "#,##0"),
        ("U", "DATE", "dd/mm/yyyy"),
        ("VW", "CURRENCY", '"R$" #,##0.00'),
    ):
        for letra in letras:
            reqs.append(formato(cel(ini, fim, col[letra], col[letra] + 1), tipo, padrao))
    reqs.append(formato(cel(ini, ini + LINHAS_SERIE, 26, 27), "DATE", "dd/mm/yyyy"))
    reqs.append(formato(cel(ini, ini + LINHAS_SERIE, 27, 29), "CURRENCY", '"R$" #,##0.00'))

    alvo = cel(ini, fim, col["T"], col["T"] + 1)
    vermelho = {"red": 0.96, "green": 0.8, "blue": 0.8}
    verde = {"red": 0.8, "green": 0.93, "blue": 0.8}
    cinza = {"red": 0.9, "green": 0.9, "blue": 0.9}
    amarelo = {"red": 1, "green": 0.95, "blue": 0.8}
    for texto, cor in (
        ("abaixo da meta", vermelho), ("sem vendas", vermelho), ("ROAS na meta", verde),
        ("insuficiente", cinza), ("Sem atividade", cinza), ("Pausada", cinza), ("Sem meta", amarelo),
    ):
        reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [alvo],
            "booleanRule": {
                "condition": {"type": "TEXT_CONTAINS", "values": [{"userEnteredValue": texto}]},
                "format": {"backgroundColor": cor},
            },
        }}})

    reqs.append({"addChart": {"chart": {
        "spec": {
            "title": "Investimento x receita por dia (conta e período do painel)",
            "basicChart": {
                "chartType": "COMBO", "legendPosition": "BOTTOM_LEGEND",
                "domains": [{"domain": {"sourceRange": {"sources": [cel(ini, ini + LINHAS_SERIE, 26, 27)]}}}],
                "series": [
                    {"series": {"sourceRange": {"sources": [cel(ini, ini + LINHAS_SERIE, 27, 28)]}}, "type": "COLUMN"},
                    {"series": {"sourceRange": {"sources": [cel(ini, ini + LINHAS_SERIE, 28, 29)]}}, "type": "LINE"},
                ],
                "headerCount": 0,
            },
        },
        "position": {"overlayPosition": {
            "anchorCell": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 4},
            "widthPixels": 700, "heightPixels": 215,
        }},
    }}})
    return reqs


def criar_painel_ads(contas_ids: list[str], recriar: bool = False) -> None:
    """
    Cria a aba "Painel Ads" (fórmulas sobre as abas brutas). Se ela já existe,
    NÃO mexe (preserva os ajustes do usuário), a menos que `recriar=True`
    (apaga e refaz a aba - os ajustes manuais nela são perdidos).
    """
    planilha = _obter_planilha()
    try:
        existente = planilha.worksheet(ABA_PAINEL_ADS)
        if not recriar:
            print(f"A aba '{ABA_PAINEL_ADS}' já existe - nada foi alterado (use recriar=True pra refazer).")
            return
        planilha.del_worksheet(existente)
    except gspread.WorksheetNotFound:
        pass

    try:
        planilha.worksheet(ABA_ADS_CAMPANHAS)
    except gspread.WorksheetNotFound as erro:
        raise RuntimeError(
            f"A aba '{ABA_ADS_CAMPANHAS}' não existe - rode antes a publicação dos dados de publicidade."
        ) from erro

    locale = planilha.fetch_sheet_metadata()["properties"].get("locale", "en_US")
    conteudo = {
        chave: _localizar_conteudo(valor, locale) for chave, valor in montar_valores_painel().items()
    }
    aba = planilha.add_worksheet(title=ABA_PAINEL_ADS, rows=ULTIMA_LINHA_PAINEL + 40, cols=30)
    aba.update(values=conteudo["topo"], range_name="A1", raw=False)
    aba.update(values=[[conteudo["aviso"]]], range_name="E10", raw=False)
    aba.update(values=[conteudo["cabecalho"]], range_name=f"A{PRIMEIRA_LINHA_PAINEL - 1}", raw=False)
    aba.update(values=[[conteudo["chaves"]]], range_name=f"A{PRIMEIRA_LINHA_PAINEL}", raw=False)
    aba.update(values=conteudo["formulas_d_y"], range_name=f"D{PRIMEIRA_LINHA_PAINEL}", raw=False)
    aba.update(values=conteudo["serie"], range_name=f"AA{PRIMEIRA_LINHA_PAINEL - 1}", raw=False)
    planilha.batch_update({"requests": _requests_formatacao(aba.id, contas_ids)})
    print(f"Aba '{ABA_PAINEL_ADS}' criada ({LINHAS_PAINEL} linhas de campanhas).")
