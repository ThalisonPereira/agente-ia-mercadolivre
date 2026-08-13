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


def publicar_resultado_no_sheets(linhas: list[dict], conta_id: str) -> None:
    """
    Sobrescreve a aba de dados dessa conta com o cabeçalho e as linhas
    mais recentes (uma linha por anúncio monitorado no dia). Cada conta
    tem sua própria aba ("Dados - <conta_id>") - com 2+ contas ativas,
    cada uma publica na sua, sem sobrescrever a das outras.
    """
    planilha = _obter_planilha()
    aba = _obter_ou_criar_aba(planilha, f"{ABA_DADOS} - {conta_id}")

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
    print(f"{len(linhas)} linha(s) publicada(s) na aba '{aba.title}'.")


def publicar_analise_no_sheets(texto_analise: str, data: str, conta_id: str) -> None:
    """Escreve o resumo em linguagem natural gerado pela IA na aba de análise dessa conta."""
    planilha = _obter_planilha()
    aba = _obter_ou_criar_aba(planilha, f"{ABA_ANALISE} - {conta_id}")

    aba.clear()
    aba.update(values=[[f"Análise de {data}"], [texto_analise]], range_name="A1")
    print(f"Análise publicada na aba '{aba.title}'.")


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
