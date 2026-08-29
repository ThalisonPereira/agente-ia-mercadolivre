"""
agents/analista_ads_ia.py

Camada de IA especializada em publicidade (Mercado Ads/Product Ads):
recebe as campanhas do dia (já coletadas em database/ads.py) e usa a API
do Gemini pra gerar uma análise focada em conversão e uso do
orçamento, com recomendações concretas pro vendedor aplicar manualmente
(não há endpoint público de escrita confirmado pra aplicar automático -
ver plano). Espelha agents/analista_ia.py.
"""

from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import types

from config.settings import carregar_configuracao_gemini
from database.analises_ads_diarias import salvar_analise_ads

CAMINHO_PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "analise_publicidade.md"

MODELO = "gemini-3.6-flash"


def _montar_tabela_campanhas(campanhas: list[dict]) -> str:
    """Formata as campanhas do dia como uma tabela compacta em texto para o prompt."""
    cabecalho = (
        "Campanha | Status | Orçamento/dia | Meta ROAS | Cliques | Impressões | CTR | "
        "Custo (R$) | CPC | ACOS | ROAS | Vendas diretas | Vendas indiretas"
    )
    corpo = [cabecalho, "-" * len(cabecalho)]
    for c in campanhas:
        corpo.append(
            f"{c['nome']} | {c['status']} | R$ {c['budget']:.2f} | {c.get('roas_target') or '—'} | "
            f"{c['clicks']} | {c['prints']} | {c['ctr']}% | {c['cost']:.2f} | {c['cpc']:.2f} | "
            f"{c['acos']}% | {c['roas']}x | {c['direct_units_quantity']} | {c['indirect_units_quantity']}"
        )
    return "\n".join(corpo)


def _montar_resumo_precalculado(campanhas: list[dict]) -> str:
    """Soma os totais em Python (mesmo motivo já documentado em analista_ia.py: modelo erra contagem em tabelas grandes)."""
    custo_total = sum(c["cost"] for c in campanhas)
    receita_total = sum(c["total_amount"] for c in campanhas)
    unidades_total = sum(c["units_quantity"] for c in campanhas)
    campanhas_sem_gasto = sum(1 for c in campanhas if c["cost"] == 0)
    roas_geral = round(receita_total / custo_total, 2) if custo_total else None

    return (
        f"Resumo pré-calculado (números exatos, some/conte a partir daqui - NÃO reconte a partir da tabela):\n"
        f"- Total de campanhas: {len(campanhas)}\n"
        f"- Custo total do dia: R$ {custo_total:.2f}\n"
        f"- Receita atribuída total: R$ {receita_total:.2f}\n"
        f"- Unidades vendidas por publicidade: {unidades_total}\n"
        f"- ROAS geral do dia: {roas_geral if roas_geral is not None else '—'}\n"
        f"- Campanhas sem nenhum gasto no dia: {campanhas_sem_gasto}"
    )


def gerar_analise_ads(campanhas: list[dict], data: str) -> str:
    """Chama a API do Gemini e retorna a análise de publicidade em texto para o dia."""
    config = carregar_configuracao_gemini()
    client = genai.Client(api_key=config.api_key)

    instrucoes = CAMINHO_PROMPT.read_text(encoding="utf-8")
    resumo_precalculado = _montar_resumo_precalculado(campanhas)
    tabela = _montar_tabela_campanhas(campanhas)

    resposta = client.models.generate_content(
        model=MODELO,
        config=types.GenerateContentConfig(system_instruction=instrucoes, max_output_tokens=2048),
        contents=(
            f"Campanhas de publicidade de {data} ({len(campanhas)} campanha(s)):\n\n"
            f"{resumo_precalculado}\n\n"
            f"Tabela detalhada (pra citar campanhas específicas, não pra recontar totais):\n\n{tabela}"
        ),
    )

    return resposta.text or ""


def analisar_e_salvar_ads(campanhas: list[dict], data: str | None, conta_id: str) -> str:
    """Gera a análise de publicidade e salva no banco, pra uma conta. Retorna o texto."""
    data = data or datetime.now().date().isoformat()
    texto = gerar_analise_ads(campanhas, data)
    salvar_analise_ads(data, texto, conta_id=conta_id)
    print(f"[conta: {conta_id}] Análise de publicidade de {data} gerada e salva no banco de dados.")
    return texto
