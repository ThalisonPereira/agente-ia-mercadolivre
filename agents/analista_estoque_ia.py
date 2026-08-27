"""
agents/analista_estoque_ia.py

Camada de IA especializada em estoque: recebe as divergências Bling x
Mercado Livre e os anúncios ranqueados em risco de pausar (já calculados
em database/estoque.py) e usa a API da Anthropic pra gerar um alerta em
texto - só leitura/alerta, nunca escreve estoque em nenhum sistema
externo. Espelha agents/analista_ads_ia.py.
"""

from datetime import datetime
from pathlib import Path

import anthropic

from config.settings import carregar_configuracao_anthropic
from database.analises_estoque_diarias import salvar_analise_estoque

CAMINHO_PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "analise_estoque.md"

MODELO = "claude-haiku-4-5"


def _montar_resumo_precalculado(divergencias: list[dict], em_risco: list[dict]) -> str:
    """Números exatos pré-contados em Python (mesmo motivo já documentado nos outros analistas: modelo erra contagem)."""
    por_categoria = {"risco_venda_sem_estoque": 0, "estoque_nao_publicado": 0, "sem_controle_bling": 0}
    for d in divergencias:
        por_categoria[d["categoria"]] = por_categoria.get(d["categoria"], 0) + 1

    return (
        f"Resumo pré-calculado (números exatos, não reconte a partir das tabelas abaixo):\n"
        f"- SKUs com risco de venda sem estoque: {por_categoria['risco_venda_sem_estoque']}\n"
        f"- SKUs com estoque não publicado (oportunidade perdida): {por_categoria['estoque_nao_publicado']}\n"
        f"- SKUs sem controle de estoque no Bling: {por_categoria['sem_controle_bling']}\n"
        f"- Anúncios ranqueados em risco de pausar: {len(em_risco)}"
    )


def _montar_tabela_divergencias(divergencias: list[dict]) -> str:
    if not divergencias:
        return "(nenhuma divergência encontrada)"
    cabecalho = "SKU | Categoria | Publicado (soma ML, já sem contar 2x anúncios vinculados) | Estoque Bling | Diferença | Grupos de estoque distintos"
    corpo = [cabecalho, "-" * len(cabecalho)]
    for d in divergencias:
        corpo.append(
            f"{d['sku']} | {d['categoria']} | {d['soma_ml']} | "
            f"{d['saldo_bling'] if d['saldo_bling'] is not None else '—'} | "
            f"{d['diferenca'] if d['diferenca'] is not None else '—'} | {d['grupos_estoque']}"
        )
    return "\n".join(corpo)


def _montar_tabela_risco(em_risco: list[dict]) -> str:
    if not em_risco:
        return "(nenhum anúncio ranqueado em risco)"
    cabecalho = "Anúncio | SKU | Conta | Receita recente | Estoque atual | Vendas/dia (média) | Dias restantes"
    corpo = [cabecalho, "-" * len(cabecalho)]
    for a in em_risco:
        dias = a["dias_restantes_estimados"] if a["dias_restantes_estimados"] is not None else "—"
        corpo.append(
            f"{a['anuncio']} | {a['sku'] or a['item_id']} | {a['conta_id']} | "
            f"R$ {a['receita_periodo']:.2f} | {a['estoque_disponivel']} | "
            f"{a['media_diaria_vendas']} | {dias}"
        )
    return "\n".join(corpo)


def gerar_analise_estoque(divergencias: list[dict], em_risco: list[dict], data: str) -> str:
    """Chama a API da Anthropic e retorna a análise de estoque em texto para o dia."""
    config = carregar_configuracao_anthropic()
    client = anthropic.Anthropic(api_key=config.api_key)

    instrucoes = CAMINHO_PROMPT.read_text(encoding="utf-8")
    resumo_precalculado = _montar_resumo_precalculado(divergencias, em_risco)
    tabela_divergencias = _montar_tabela_divergencias(divergencias)
    tabela_risco = _montar_tabela_risco(em_risco)

    resposta = client.messages.create(
        model=MODELO,
        max_tokens=2048,
        system=instrucoes,
        messages=[{
            "role": "user",
            "content": (
                f"Estoque em {data}:\n\n"
                f"{resumo_precalculado}\n\n"
                f"Divergências de estoque (Bling x Mercado Livre):\n\n{tabela_divergencias}\n\n"
                f"Anúncios ranqueados em risco de pausar:\n\n{tabela_risco}"
            ),
        }],
    )

    texto = next((bloco.text for bloco in resposta.content if bloco.type == "text"), "")
    return texto


def analisar_e_salvar_estoque(divergencias: list[dict], em_risco: list[dict], data: str | None = None) -> str:
    """Gera a análise de estoque e salva no banco (1x por dia, não é por conta). Retorna o texto."""
    data = data or datetime.now().date().isoformat()
    texto = gerar_analise_estoque(divergencias, em_risco, data)
    salvar_analise_estoque(data, texto)
    print(f"Análise de estoque de {data} gerada e salva no banco de dados.")
    return texto
