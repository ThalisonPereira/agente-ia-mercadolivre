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


def gerar_analise(linhas: list[dict], data: str) -> str:
    """Chama a API da Anthropic e retorna o resumo em texto para o dia."""
    config = carregar_configuracao_anthropic()
    client = anthropic.Anthropic(api_key=config.api_key)

    instrucoes = CAMINHO_PROMPT.read_text(encoding="utf-8")
    tabela = _montar_tabela_dados(linhas)

    resposta = client.messages.create(
        model=MODELO,
        max_tokens=2048,
        system=instrucoes,
        messages=[{
            "role": "user",
            "content": f"Dados de {data} ({len(linhas)} anúncio(s) monitorado(s)):\n\n{tabela}",
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


def analisar_e_salvar(linhas: list[dict], data: str | None = None) -> str:
    """Gera a análise, salva em disco e retorna o texto (para publicar no Sheets, por ex.)."""
    data = data or datetime.now().date().isoformat()
    texto = gerar_analise(linhas, data)
    caminho = salvar_relatorio(texto, data)
    print(f"Análise gerada e salva em {caminho}.")
    return texto
