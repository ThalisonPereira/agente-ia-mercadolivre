"""
agents/analista_ia.py

Camada de IA: recebe a variação de visitas/vendas por anúncio (já calculada
em database/analisar_variacao.py) e usa a API da Anthropic para gerar um
resumo em linguagem natural - o "olhar clínico" sobre os dados do dia.
"""

from datetime import datetime
from pathlib import Path

import anthropic

from config.settings import carregar_configuracao_anthropic
from database.analises_diarias import CONTA_GERAL, salvar_analise

CAMINHO_PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "analise_anuncios.md"
PASTA_REPORTS = Path(__file__).resolve().parent.parent / "reports"

MODELO = "claude-haiku-4-5"


def _montar_tabela_dados(linhas: list[dict]) -> str:
    """Formata as linhas de variação como uma tabela compacta em texto para o prompt."""
    cabecalho = "Anúncio | Visitas | Vendas | Receita (R$) | Var. Visitas | Var. Vendas | Status"
    corpo = [cabecalho, "-" * len(cabecalho)]
    for linha in linhas:
        corpo.append(
            f"{linha['anuncio']} | {linha['visitas']} | {linha['vendas']} | "
            f"{linha['receita']:.2f} | {linha['variacao_visitas']}% | "
            f"{linha['variacao_vendas']}% | {linha['status']}"
        )
    return "\n".join(corpo)


def _montar_resumo_precalculado(linhas: list[dict]) -> str:
    """
    Soma os totais em Python (não pede pro modelo contar) - tabelas grandes
    (185+ anúncios) fazem até o modelo errar contagem simples ao escrever o
    resumo (visto na prática: disse "2 vendas concretizadas" quando eram
    3). Esses números são exatos e devem ser usados como estão, sem
    recontar a partir da tabela.
    """
    anuncios_com_venda = sum(1 for l in linhas if l["vendas"] > 0)
    unidades_vendidas = sum(l["vendas"] for l in linhas)
    receita_total = sum(l["receita"] for l in linhas)
    em_queda = sum(1 for l in linhas if l["status"] == "Queda")
    em_alta = sum(1 for l in linhas if l["status"] == "Alta")

    return (
        f"Resumo pré-calculado (números exatos, some/conte a partir daqui - NÃO reconte a partir da tabela):\n"
        f"- Total de anúncios monitorados: {len(linhas)}\n"
        f"- Anúncios com pelo menos 1 venda no dia: {anuncios_com_venda}\n"
        f"- Unidades vendidas no total: {unidades_vendidas}\n"
        f"- Receita total do dia: R$ {receita_total:.2f}\n"
        f"- Anúncios em Queda: {em_queda}\n"
        f"- Anúncios em Alta: {em_alta}"
    )


def gerar_analise(linhas: list[dict], data: str) -> str:
    """Chama a API da Anthropic e retorna o resumo em texto para o dia."""
    config = carregar_configuracao_anthropic()
    client = anthropic.Anthropic(api_key=config.api_key)

    instrucoes = CAMINHO_PROMPT.read_text(encoding="utf-8")
    resumo_precalculado = _montar_resumo_precalculado(linhas)
    tabela = _montar_tabela_dados(linhas)

    resposta = client.messages.create(
        model=MODELO,
        max_tokens=2048,
        system=instrucoes,
        messages=[{
            "role": "user",
            "content": (
                f"Dados de {data} ({len(linhas)} anúncio(s) monitorado(s)):\n\n"
                f"{resumo_precalculado}\n\n"
                f"Tabela detalhada (pra citar anúncios específicos, não pra recontar totais):\n\n{tabela}"
            ),
        }],
    )

    texto = next((bloco.text for bloco in resposta.content if bloco.type == "text"), "")
    return texto


def salvar_relatorio(texto: str, data: str) -> Path:
    """Salva o resumo gerado em reports/, para manter histórico local."""
    PASTA_REPORTS.mkdir(exist_ok=True)
    caminho = PASTA_REPORTS / f"analise_{data}.md"
    caminho.write_text(texto, encoding="utf-8")
    return caminho


def analisar_e_salvar(linhas: list[dict], data: str | None = None, conta_id: str = CONTA_GERAL) -> str:
    """Gera a análise, salva em disco + banco (pra uma conta, ou 'geral') e retorna o texto (para publicar no Sheets, por ex.)."""
    data = data or datetime.now().date().isoformat()
    texto = gerar_analise(linhas, data)
    caminho = salvar_relatorio(texto, data)
    salvar_analise(data, texto, conta_id=conta_id)
    print(f"Análise gerada e salva em {caminho} e no banco de dados.")
    return texto
