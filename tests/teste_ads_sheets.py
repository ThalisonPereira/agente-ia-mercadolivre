"""
tests/teste_ads_sheets.py

Testes OFFLINE da publicação de publicidade no Google Sheets
(integrations/google_sheets_ads.py + comandos do main.py): sem rede, sem
Sheets real, sem banco. Executar com:  python tests/teste_ads_sheets.py

O que NÃO é testável aqui: se o Google Sheets calcula as fórmulas como
esperado (isso só se confirma lendo os valores calculados na planilha real).
"""

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gspread  # noqa: E402

import integrations.google_sheets_ads as ga  # noqa: E402
import main as main_mod  # noqa: E402

CAMPANHA = {
    "conta_id": "hc", "data": "2026-10-12", "campaign_id": 359531439, "nome": "BANCADA 160 IND 1005 1809",
    "status": "active", "budget": 30.0, "roas_target": 10.0, "acos_target": 10.0,
    "prints": 8375, "clicks": 51, "cost": 30.0, "direct_amount": 0.0, "indirect_amount": 849.59,
    "total_amount": 849.59, "direct_units_quantity": 0, "indirect_units_quantity": 1, "units_quantity": 1,
}
ANUNCIO = {
    "conta_id": "hc", "data": "2026-10-12", "item_id": "MLB3891204923", "campaign_id": 359531439,
    "titulo": "Bancada Gourmet", "status": "active", "prints": 100, "clicks": 5, "cost": 3.456,
    "direct_amount": 0.0, "indirect_amount": 0.0, "total_amount": 0.0, "units_quantity": 0,
}


def teste_linhas_campanhas():
    linhas = ga.montar_linhas_ads_campanhas([CAMPANHA, {**CAMPANHA, "budget": None, "roas_target": None, "acos_target": None}])
    assert linhas[0] == ga.CABECALHO_ADS_CAMPANHAS
    assert len(linhas) == 3 and all(len(l) == len(ga.CABECALHO_ADS_CAMPANHAS) for l in linhas)
    assert linhas[1][3] == 359531439 and linhas[1][5] == 30.0 and linhas[1][6] == 10.0
    # ausente (None) vira célula vazia, e zero real continua 0 (não são a mesma coisa)
    assert linhas[2][5] == "" and linhas[2][6] == "" and linhas[2][7] == ""
    assert linhas[1][11] == 0.0 and linhas[1][14] == 0
    print("[linhas] campanhas: cabeçalho, tamanho, ausente x zero real: OK")


def teste_linhas_anuncios_e_arredondamento():
    linhas = ga.montar_linhas_ads_anuncios([ANUNCIO])
    assert linhas[0] == ga.CABECALHO_ADS_ANUNCIOS and len(linhas[1]) == len(ga.CABECALHO_ADS_ANUNCIOS)
    assert linhas[1][8] == 3.46  # 3.456 arredondado a 2 casas
    print("[linhas] anúncios e arredondamento a 2 casas: OK")


def _balanceada(formula: str) -> bool:
    return formula.count("(") == formula.count(")") and formula.count('"') % 2 == 0 and formula.count("{") == formula.count("}")


def teste_formulas_bem_formadas():
    c = ga.montar_valores_painel()
    todas = [c["chaves"], c["aviso"]]
    for linha in c["formulas_d_y"]:
        todas += linha
    for linha in c["serie"][1:]:
        todas += linha
    todas += [v for linha in c["topo"] for v in linha if isinstance(v, str) and v.startswith("=")]
    assert all(f.startswith("=") for f in todas)
    ruins = [f for f in todas if not _balanceada(f)]
    assert not ruins, ruins[:2]
    assert len(c["formulas_d_y"]) == ga.LINHAS_PAINEL
    assert all(len(l) == 22 for l in c["formulas_d_y"])  # colunas D..Y
    assert len(c["serie"]) == ga.LINHAS_SERIE + 1
    assert len(c["cabecalho"]) == len(ga.COLUNAS_PAINEL)
    # toda referência a aba usa o nome real da aba de campanhas
    assert all("'Ads Campanhas'!" in f for f in c["formulas_d_y"][0] if "SUMIFS" in f or "MAXIFS" in f or "FILTER" in f)
    print(f"[painel] {len(todas)} fórmulas com parênteses/aspas/chaves balanceados, 60 linhas x 22 colunas, série de 91 dias: OK")


def teste_regras_do_diagnostico_e_ordem():
    t = ga.montar_formulas_painel(13)["T"]
    ordem = [
        "Pausada", "Sem atividade no período", "Volume insuficiente para avaliar",
        "Investimento sem vendas atribuídas", "Sem meta de ROAS configurada", "ROAS abaixo da meta",
        "ROAS na meta e orçamento quase esgotado", "ROAS na meta",
    ]
    posicoes = [t.index(x) for x in ordem]
    assert posicoes == sorted(posicoes), "ordem das regras mudou"
    # usa só os parâmetros visíveis do painel (B6 dias a ignorar, B7 invest. mín., B8 cliques mín., B9 fração do orçamento)
    for p in ("$B$7", "$B$8", "$B$9"):
        assert p in t
    # volume/vendas/ROAS usam as colunas "avaliáveis" (sem os dias recentes), não o período inteiro
    assert "$V13" in t and "$W13" in t and "$X13" in t
    print("[painel] diagnóstico: 8 regras na ordem certa, parâmetros visíveis, janela sem dias recentes: OK")


def teste_metricas_sem_denominador():
    f = ga.montar_formulas_painel(13)
    for coluna, den in (("J", "$H13>0"), ("K", "$I13>0"), ("N", "$L13>0"), ("O", "$M13>0")):
        assert den in f[coluna] and '"—"' in f[coluna], coluna
    assert "/100" in f["G"]  # meta ACOS vem em % (10 = 10%) e vira fração pro formato percentual
    print("[painel] ROAS/ACOS/CTR/CPC mostram '—' sem denominador; meta ACOS convertida: OK")


def teste_orcamento_e_metas_do_ultimo_dia():
    f = ga.montar_formulas_painel(13)
    for coluna in ("E", "F", "G"):
        assert "$U13" in f[coluna] and "SUMIFS" in f[coluna]
    assert "MAXIFS" in f["U"] and '"<="&$B$5' in f["U"] and '">="&$B$4' in f["U"]
    # orçamento/metas NÃO usam o filtro de período inteiro (não somam entre dias)
    assert '">="&$B$4,' not in f["E"]
    print("[painel] orçamento/metas pegam só o último dia com dado do período: OK")


class AbaFalsa:
    def __init__(self, titulo, row_count=1000):
        self.title, self.row_count, self.id = titulo, row_count, 7
        self.chamadas = []

    def clear(self):
        self.chamadas.append(("clear",))

    def resize(self, rows=None, cols=None):
        self.chamadas.append(("resize", rows))
        self.row_count = rows

    def update(self, values, range_name, raw=True):
        self.chamadas.append(("update", range_name, raw, values))


class PlanilhaFalsa:
    def __init__(self, abas=(), locale="pt_BR"):
        self.abas = {a.title: a for a in abas}
        self.eventos = []
        self.locale = locale

    def fetch_sheet_metadata(self):
        return {"properties": {"locale": self.locale}}

    def worksheet(self, titulo):
        if titulo not in self.abas:
            raise gspread.WorksheetNotFound(titulo)
        return self.abas[titulo]

    def add_worksheet(self, title, rows, cols):
        self.eventos.append(("add", title))
        self.abas[title] = AbaFalsa(title, rows)
        return self.abas[title]

    def del_worksheet(self, aba):
        self.eventos.append(("del", aba.title))
        del self.abas[aba.title]

    def batch_update(self, body):
        self.eventos.append(("batch", len(body["requests"])))


def teste_publicar_regrava_abas_brutas_com_raw_false():
    planilha = PlanilhaFalsa()
    with mock.patch.object(ga, "_obter_planilha", return_value=planilha):
        ga.publicar_ads_no_sheets([CAMPANHA], [ANUNCIO])
    assert set(planilha.abas) == {"Ads Campanhas", "Ads Anúncios"}
    for aba in planilha.abas.values():
        assert aba.chamadas[0] == ("clear",)
        atualizar = [c for c in aba.chamadas if c[0] == "update"][0]
        assert atualizar[1] == "A1" and atualizar[2] is False  # USER_ENTERED: datas viram datas
    assert "Painel Ads" not in planilha.abas  # a rotina diária nunca cria/toca no painel
    print("[publicar] regrava as 2 abas brutas (clear + update raw=False) e não toca no painel: OK")


def teste_painel_nao_sobrescreve_existente():
    painel = AbaFalsa("Painel Ads")
    planilha = PlanilhaFalsa([painel, AbaFalsa("Ads Campanhas")])
    with mock.patch.object(ga, "_obter_planilha", return_value=planilha):
        ga.criar_painel_ads(["hc", "wc", "cc"])
    assert planilha.eventos == [] and painel.chamadas == []
    print("[painel] aba já existente NÃO é alterada sem --recriar: OK")


def teste_painel_recriar_e_criacao():
    planilha = PlanilhaFalsa([AbaFalsa("Painel Ads"), AbaFalsa("Ads Campanhas")])
    with mock.patch.object(ga, "_obter_planilha", return_value=planilha):
        ga.criar_painel_ads(["hc", "wc", "cc"], recriar=True)
    assert planilha.eventos[0] == ("del", "Painel Ads") and planilha.eventos[1] == ("add", "Painel Ads")
    assert planilha.eventos[2][0] == "batch" and planilha.eventos[2][1] > 20
    novo = planilha.abas["Painel Ads"]
    faixas = [c[1] for c in novo.chamadas if c[0] == "update"]
    assert faixas[0] == "A1" and "A13" in faixas and "D13" in faixas and "AA12" in faixas
    assert all(c[2] is False for c in novo.chamadas if c[0] == "update")  # fórmulas precisam de USER_ENTERED
    print("[painel] --recriar apaga e refaz; criação escreve topo, chaves, fórmulas D..Y, série e formatação: OK")


def teste_painel_exige_aba_de_dados():
    planilha = PlanilhaFalsa()
    with mock.patch.object(ga, "_obter_planilha", return_value=planilha):
        try:
            ga.criar_painel_ads(["hc"])
        except RuntimeError as erro:
            assert "Ads Campanhas" in str(erro)
        else:
            raise AssertionError("deveria exigir a aba de dados")
    assert planilha.eventos == []
    print("[painel] sem a aba 'Ads Campanhas' falha com mensagem clara e sem escrever nada: OK")


def teste_localizacao_das_formulas_pt_br():
    assert ga.usa_ponto_e_virgula("pt_BR") and ga.usa_ponto_e_virgula("de_DE")
    assert not ga.usa_ponto_e_virgula("en_US") and not ga.usa_ponto_e_virgula("es_MX")
    f = '=IF(A1="a, b",SUMIFS(X,Y,1),{A,B})'
    assert ga.localizar_formula(f, "pt_BR") == '=IF(A1="a, b";SUMIFS(X;Y;1);{A\\B})'  # vírgula em texto fica; {} usa "\"
    assert ga.localizar_formula(f, "en_US") == f
    assert ga.localizar_formula("texto, solto", "pt_BR") == "texto, solto"  # não é fórmula
    assert ga.localizar_formula(0.9, "pt_BR") == 0.9
    todas = ga._localizar_conteudo(ga.montar_valores_painel()["formulas_d_y"], "pt_BR")
    achatadas = [f for linha in todas for f in linha]
    # nenhuma vírgula de argumento sobra fora de textos entre aspas
    for f in achatadas[:50]:
        fora = "".join(p for i, p in enumerate(f.split('"')) if i % 2 == 0)
        assert "," not in fora, f
    print("[painel] fórmulas convertidas para pt_BR (';' nos argumentos, '\\' nas matrizes, textos intactos): OK")


def teste_painel_grava_formulas_localizadas():
    planilha = PlanilhaFalsa([AbaFalsa("Ads Campanhas")], locale="pt_BR")
    with mock.patch.object(ga, "_obter_planilha", return_value=planilha):
        ga.criar_painel_ads(["hc"])
    escritas = [c for c in planilha.abas["Painel Ads"].chamadas if c[0] == "update"]
    chaves = [c for c in escritas if c[1] == "A13"][0][3][0][0]
    assert ";" in chaves and "\\" in chaves and "{'Ads Campanhas'" in chaves
    d13 = [c for c in escritas if c[1] == "D13"][0][3][0][0]
    assert "," not in "".join(p for i, p in enumerate(d13.split('"')) if i % 2 == 0)
    ingles = PlanilhaFalsa([AbaFalsa("Ads Campanhas")], locale="en_US")
    with mock.patch.object(ga, "_obter_planilha", return_value=ingles):
        ga.criar_painel_ads(["hc"])
    assert "," in [c for c in ingles.abas["Painel Ads"].chamadas if c[0] == "update" and c[1] == "A13"][0][3][0][0]
    print("[painel] a planilha pt_BR recebe fórmulas com ';' e a en_US mantém vírgulas: OK")


def teste_validacao_de_conta_e_formatacao():
    reqs = ga._requests_formatacao(7, ["hc", "wc", "cc"])
    validacao = [r for r in reqs if "setDataValidation" in r][0]["setDataValidation"]
    valores = [v["userEnteredValue"] for v in validacao["rule"]["condition"]["values"]]
    assert valores == ["todas", "hc", "wc", "cc"]
    assert sum("addConditionalFormatRule" in r for r in reqs) == 7
    assert sum("addChart" in r for r in reqs) == 1
    print("[painel] lista de contas, 7 regras de cor e 1 gráfico: OK")


def teste_rotina_diaria_chama_publicacao_sem_derrubar():
    with mock.patch.object(main_mod, "obter_campanhas_diarias", return_value=[CAMPANHA]) as c, \
            mock.patch.object(main_mod, "obter_anuncios_diarios", return_value=[ANUNCIO]) as a, \
            mock.patch.object(main_mod, "publicar_ads_no_sheets") as p:
        main_mod._publicar_ads_na_planilha()
    c.assert_called_once_with(90)
    a.assert_called_once_with(90)
    p.assert_called_once_with([CAMPANHA], [ANUNCIO])
    print("[main] lê 90 dias de campanhas e anúncios e publica: OK")


if __name__ == "__main__":
    testes = [v for k, v in sorted(globals().items()) if k.startswith("teste_") and callable(v)]
    with mock.patch.object(gspread, "authorize", side_effect=AssertionError("tentou usar o Sheets real")):
        for t in testes:
            t()
    print(f"\n{len(testes)}/{len(testes)} testes passaram.")
