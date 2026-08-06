"""
integrations/google_sheets.py

Publica o resultado diário de visitas/vendas por anúncio numa aba do
Google Sheets, usando uma conta de serviço (sem interação manual), e escreve
o resumo em texto gerado pela IA numa segunda aba.
"""
import gspread
from google.oauth2.service_account import Credentials

from config.settings import carregar_configuracao_sheets

ESCOPOS = ["https://www.googleapis.com/auth/spreadsheets"]

ABA_DADOS = "Dados"
ABA_ANALISE = "Análise IA"
ABA_HISTORICO = "Histórico Completo"

CABECALHO_HISTORICO = ["Data", "Anúncio", "SKU/ID", "Visitas", "Vendas", "Receita (R$)"]

CABECALHO = [
    "Data", "Anúncio", "SKU/ID", "Visitas", "Vendas", "Receita (R$)",
    "Variação de Visitas", "Variação de Vendas", "Status",
]


def _autenticar() -> gspread.Client:
    config = carregar_configuracao_sheets()
    credenciais = Credentials.from_service_account_file(
        str(config.service_account_path), scopes=ESCOPOS
    )
    return gspread.authorize(credenciais)


def _obter_planilha():
    config = carregar_configuracao_sheets()
    cliente = _autenticar()
    return cliente.open_by_key(config.sheets_id)


def _obter_ou_criar_aba(planilha, titulo: str, linhas: int = 1000, colunas: int = 12):
    try:
        return planilha.worksheet(titulo)
    except gspread.WorksheetNotFound:
        return planilha.add_worksheet(title=titulo, rows=linhas, cols=colunas)


def publicar_resultado_no_sheets(linhas: list[dict]) -> None:
    """
    Sobrescreve a aba de dados com o cabeçalho e as linhas mais recentes
    (uma linha por anúncio monitorado no dia).
    """
    planilha = _obter_planilha()
    aba = _obter_ou_criar_aba(planilha, ABA_DADOS)

    aba.clear()

    valores = [CABECALHO]
    for linha in linhas:
        valores.append([
            linha["data"],
            linha["anuncio"],
            linha["item_id"],
            linha["visitas"],
            linha["vendas"],
            linha["receita"],
            linha["variacao_visitas"],
            linha["variacao_vendas"],
            linha["status"],
        ])

    aba.update(values=valores, range_name="A1")
    print(f"{len(linhas)} linha(s) publicada(s) na aba '{ABA_DADOS}'.")


def publicar_analise_no_sheets(texto_analise: str, data: str) -> None:
    """Escreve o resumo em linguagem natural gerado pela IA na aba de análise."""
    planilha = _obter_planilha()
    aba = _obter_ou_criar_aba(planilha, ABA_ANALISE)

    aba.clear()
    aba.update(values=[[f"Análise de {data}"], [texto_analise]], range_name="A1")
    print(f"Análise publicada na aba '{ABA_ANALISE}'.")


def publicar_historico_completo_no_sheets(linhas: list[dict]) -> None:
    """
    Sobrescreve a aba de histórico completo com uma linha por (dia, anúncio)
    já registrado no banco local - serve de base de dados para o chat de IA
    na planilha (Apps Script) responder perguntas sobre qualquer período já
    coletado, não só o snapshot mais recente.
    """
    planilha = _obter_planilha()
    linhas_necessarias = len(linhas) + 1  # +1 pelo cabeçalho

    aba = _obter_ou_criar_aba(planilha, ABA_HISTORICO, linhas=max(1000, linhas_necessarias + 100), colunas=8)
    if aba.row_count < linhas_necessarias:
        aba.resize(rows=linhas_necessarias + 100)

    aba.clear()

    valores = [CABECALHO_HISTORICO]
    for linha in linhas:
        valores.append([
            linha["data"],
            linha["anuncio"],
            linha["sku"] or linha["item_id"],
            linha["visitas"],
            linha["vendas"],
            linha["receita"],
        ])

    aba.update(values=valores, range_name="A1")
    print(f"{len(linhas)} linha(s) de histórico publicada(s) na aba '{ABA_HISTORICO}'.")


def testar_conexao_sheets() -> None:
    """Escreve uma linha de teste simples, só para validar a conexão hoje."""
    from datetime import datetime

    planilha = _obter_planilha()
    aba = _obter_ou_criar_aba(planilha, ABA_DADOS)
    aba.clear()
    aba.update(
        values=[
            ["Teste de conexão"],
            [f"Conectado com sucesso em {datetime.now().isoformat(timespec='seconds')}"],
        ],
        range_name="A1",
    )
    print("Teste escrito na planilha com sucesso. Confira no navegador.")
