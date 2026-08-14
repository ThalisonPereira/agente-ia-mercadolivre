"""
agents/assistente_ia.py

Assistente de e-commerce com tool-calling: em vez de mandar todo o
histórico como contexto (caro e não escala - ver o design antigo do
chat_app.py, que chegou a mandar 318 mil tokens por pergunta), o modelo
pede só o dado específico que precisa pra responder cada pergunta, através
de ferramentas que consultam o banco de dados (Turso).

Não importa Streamlit - pode ser testado isolado (bloco __main__ abaixo,
`python -m agents.assistente_ia`) e é usado por chat_app.py sem acoplamento
com a interface.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic
from anthropic import beta_tool

FUSO_BRASILIA = ZoneInfo("America/Sao_Paulo")

from database.analisar_variacao import obter_variacao_anuncios
from database.analises_diarias import obter_ultima_analise
from database.consultar_anuncio import buscar_por_sku_ou_titulo
from database.extrato import obter_data_mais_recente as obter_data_mais_recente_extrato
from database.extrato import obter_resumo_extrato
from database.pedidos import obter_data_mais_recente as obter_data_mais_recente_pedidos
from database.pedidos import obter_resumo as obter_resumo_pedidos
from database.ranking import obter_ranking

MODELO = "claude-sonnet-5"

SYSTEM_PROMPT_BASE = """\
Você é um assistente de e-commerce que ajuda um vendedor a entender o \
desempenho dos seus anúncios (visitas, vendas, receita) em um ou mais \
canais de venda (Mercado Livre, Shopee, Amazon) e, dentro de cada canal, \
em uma ou mais contas. Use as ferramentas disponíveis para buscar \
exatamente o dado necessário para responder cada pergunta - nunca invente \
números que não vieram de uma ferramenta. Se o usuário não especificar \
conta ou canal, combine os dados de todas as contas disponíveis; se \
especificar (ex: "na Shopee", "na conta X"), use os parâmetros conta_id/ \
canal das ferramentas para filtrar. Responda em português, de forma direta \
e objetiva, citando números quando fizer sentido. Se não conseguir \
responder com os dados disponíveis, diga isso claramente em vez de supor."""

_DIAS_DA_SEMANA = [
    "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
    "sexta-feira", "sábado", "domingo",
]


def _montar_system_prompt() -> str:
    """
    Monta o prompt de sistema com a data/hora atual embutida, pra que o
    modelo resolva sozinho expressões relativas ("ontem", "hoje", "essa
    semana") sem precisar perguntar de volta ao usuário o que cada uma
    significa. Recalculado a cada pergunta (não é uma constante fixa) -
    isso reduz um pouco o aproveitamento do cache do prompt (ver
    cache_control em responder_pergunta) só quando o dia muda, o que é
    uma perda pequena perto do ganho de não confundir o modelo com a data.
    """
    # Servidores na nuvem (GitHub Actions, Streamlit Cloud) rodam em UTC, não
    # em horário de Brasília - por isso converte explicitamente pro fuso
    # certo, em vez de usar datetime.now() puro (que dependeria do fuso do
    # sistema operacional onde o processo está rodando).
    agora = datetime.now(FUSO_BRASILIA)
    dia_semana = _DIAS_DA_SEMANA[agora.weekday()]
    return (
        f"{SYSTEM_PROMPT_BASE}\n\n"
        f"Data e hora atual: {agora.strftime('%d/%m/%Y')} ({dia_semana}), {agora.strftime('%H:%M')} "
        f"(horário de Brasília). Use essa referência pra resolver expressões relativas de tempo na "
        f"pergunta do usuário (\"ontem\", \"hoje\", \"essa semana\", \"último mês\" etc.) sem precisar "
        f"perguntar de volta o que a expressão significa - calcule a data exata você mesmo. Lembre que "
        f"os dados coletados costumam ir só até ontem (a coleta roda 1x por dia); se o usuário perguntar "
        f"sobre \"hoje\", explique que o dado mais recente disponível é de ontem."
    )


def _formatar_linhas(linhas: list[dict]) -> str:
    """Formata uma lista de dicionários como texto tabular compacto (resultado de ferramenta)."""
    if not linhas:
        return "Nenhum resultado encontrado."
    colunas = list(linhas[0].keys())
    corpo = [" | ".join(colunas)]
    for linha in linhas:
        corpo.append(" | ".join(str(linha[c]) for c in colunas))
    return "\n".join(corpo)


@beta_tool
def consultar_sku(
    sku_ou_titulo: str,
    data_inicio: str = "",
    data_fim: str = "",
    conta_id: str = "",
    canal: str = "",
) -> str:
    """Busca o desempenho (visitas, vendas e receita somados) de um anúncio
    específico por SKU ou parte do título. Pode retornar mais de um anúncio
    se o termo for genérico, ou se o mesmo produto existir em contas
    diferentes. Datas no formato AAAA-MM-DD; se omitidas, usa os últimos 30
    dias com dados disponíveis.

    Args:
        sku_ou_titulo: SKU exato ou parte do título do anúncio a buscar.
        data_inicio: Data inicial do período (AAAA-MM-DD), opcional.
        data_fim: Data final do período (AAAA-MM-DD), opcional.
        conta_id: Restringe a busca a uma conta específica (ex: "hc"), opcional - se omitido, busca em todas as contas.
        canal: Restringe a um canal inteiro (ex: "mercado_livre", "shopee", "amazon"), opcional.
    """
    resultado = buscar_por_sku_ou_titulo(
        sku_ou_titulo, data_inicio or None, data_fim or None, conta_id or None, canal or None
    )
    return _formatar_linhas(resultado)


@beta_tool
def variacao_recente(
    data_inicial: str = "", data_final: str = "", conta_id: str = "", canal: str = ""
) -> str:
    """Lista todos os anúncios com a variação percentual de visitas e vendas
    entre duas datas, classificados como Queda, Alta ou Estável. Se as datas
    não forem informadas, usa as duas datas mais recentes com dados no banco.

    Args:
        data_inicial: Data mais antiga da comparação (AAAA-MM-DD), opcional.
        data_final: Data mais recente da comparação (AAAA-MM-DD), opcional.
        conta_id: Restringe a comparação a uma conta específica (ex: "hc"), opcional - se omitido, combina todas as contas.
        canal: Restringe a um canal inteiro (ex: "mercado_livre", "shopee", "amazon"), opcional.
    """
    resultado = obter_variacao_anuncios(
        data_inicial or None, data_final or None, conta_id or None, canal or None
    )
    if resultado is None:
        return "Ainda não há snapshots suficientes para comparar (precisa de pelo menos 2 dias de histórico)."
    return _formatar_linhas(resultado)


@beta_tool
def ranking_periodo(
    metrica: str,
    data_inicio: str,
    data_fim: str,
    top_n: int = 10,
    conta_id: str = "",
    canal: str = "",
) -> str:
    """Retorna o ranking (top N) de anúncios por receita, visitas ou vendas,
    somados num intervalo de datas.

    Args:
        metrica: Uma de 'receita', 'visitas' ou 'vendas'.
        data_inicio: Data inicial do período (AAAA-MM-DD).
        data_fim: Data final do período (AAAA-MM-DD).
        top_n: Quantos anúncios retornar no ranking (padrão 10).
        conta_id: Restringe a uma conta específica (ex: "hc"), opcional.
        canal: Restringe a um canal inteiro (ex: "mercado_livre", "shopee", "amazon"), opcional - se omitido junto com conta_id, combina tudo.
    """
    try:
        resultado = obter_ranking(metrica, data_inicio, data_fim, top_n, conta_id or None, canal or None)
    except ValueError as erro:
        return str(erro)
    return _formatar_linhas(resultado)


@beta_tool
def ultima_analise(conta_id: str = "") -> str:
    """Retorna a análise narrativa mais recente já gerada sobre o
    desempenho dos anúncios (a "análise do dia").

    Args:
        conta_id: Restringe a uma conta específica (ex: "hc"), opcional - se omitido, retorna a análise mais recente entre todas as contas.
    """
    analise = obter_ultima_analise(conta_id or None)
    if analise is None:
        return "Ainda não há nenhuma análise gerada."
    return (
        f"Análise da conta '{analise['conta_id']}' em {analise['data']} "
        f"(gerada em {analise['gerado_em']}):\n\n{analise['texto']}"
    )


@beta_tool
def pedidos_do_dia(conta_id: str = "", canal: str = "") -> str:
    """Retorna quantos pedidos (vendas/transações, não unidades) entraram
    no dia mais recente coletado, e quantos estão em cada situação de
    envio: prontos pra despachar agora (imediato), aguardando preparo
    (postergado), já enviados, ou cancelados. O status é capturado no dia
    do pedido e não é atualizado depois - reflete a foto daquele momento.

    Args:
        conta_id: Restringe a uma conta específica (ex: "hc"), opcional.
        canal: Restringe a um canal inteiro (ex: "mercado_livre", "shopee", "amazon"), opcional.
    """
    data = obter_data_mais_recente_pedidos(conta_id or None, canal or None)
    if data is None:
        return "Ainda não há pedidos coletados para esse filtro."

    resumo = obter_resumo_pedidos(data, conta_id or None, canal or None)
    return (
        f"Pedidos de {data}: {resumo['total']} no total, sendo "
        f"{resumo['imediato']} prontos pra envio, {resumo['postergado']} aguardando preparo, "
        f"{resumo['enviado']} já enviados e {resumo['cancelado']} cancelados. "
        f"Valor total: R$ {resumo['valor_total']:.2f}."
    )


@beta_tool
def extrato_do_dia(conta_id: str = "", canal: str = "") -> str:
    """Retorna o extrato de margem do dia mais recente coletado: total
    vendido, comissão do Mercado Livre, frete pago pelo vendedor, imposto
    estimado (14% sobre o preço de venda), a margem líquida em reais (já
    descontando o custo do produto, vindo do Bling) e também em
    porcentagem (margem de contribuição). Itens cujo SKU não foi
    encontrado no Bling (ou tem custo zerado) ficam de fora do total de
    margem, pra não distorcer o número - o total de itens nessa situação
    é informado à parte.

    Args:
        conta_id: Restringe a uma conta específica (ex: "hc"), opcional.
        canal: Restringe a um canal inteiro (ex: "mercado_livre", "shopee", "amazon"), opcional.
    """
    data = obter_data_mais_recente_extrato(conta_id or None, canal or None)
    if data is None:
        return "Ainda não há extrato de vendas coletado para esse filtro."

    resumo = obter_resumo_extrato(data, conta_id or None, canal or None)
    aviso_custo = (
        f" {resumo['itens_sem_custo']} item(ns) sem custo encontrado no Bling, excluído(s) da margem."
        if resumo["itens_sem_custo"]
        else ""
    )
    aviso_cancelados = (
        f" {resumo['itens_cancelados']} pedido(s) cancelado(s) nesse dia (não contam em nenhum total)."
        if resumo["itens_cancelados"]
        else ""
    )
    margem_pct = f"{resumo['margem_percentual']:.1f}%" if resumo["margem_percentual"] is not None else "indisponível"
    return (
        f"Extrato de {data}: {resumo['total_itens']} item(ns) vendido(s), "
        f"R$ {resumo['total_vendido']:.2f} em vendas, R$ {resumo['total_comissao']:.2f} de comissão ML, "
        f"R$ {resumo['total_frete']:.2f} de frete, valor líquido sem imposto de R$ {resumo['total_liquido_sem_imposto']:.2f}, "
        f"R$ {resumo['total_imposto']:.2f} de imposto estimado, "
        f"margem líquida (já descontando o custo do produto) de R$ {resumo['total_margem']:.2f}, "
        f"equivalente a {margem_pct} de margem de contribuição sobre o valor vendido.{aviso_custo}{aviso_cancelados}"
    )


FERRAMENTAS = [
    consultar_sku, variacao_recente, ranking_periodo, ultima_analise, pedidos_do_dia, extrato_do_dia,
]


def responder_pergunta(
    pergunta: str, mensagens_api: list[dict], anthropic_api_key: str
) -> tuple[str, list[dict], dict]:
    """
    Responde uma pergunta do usuário usando o modelo com tool-calling, e
    devolve o texto da resposta, a lista de mensagens atualizada (pra manter
    histórico de conversa entre perguntas na mesma sessão) e um resumo do
    consumo de tokens do turno (somado entre todas as idas e vindas de
    ferramenta) - usado pra confirmar que o consumo é pequeno, não os ~318
    mil tokens/pergunta do design antigo que mandava o histórico inteiro.

    Só a resposta final em texto de cada turno é adicionada de volta em
    mensagens_api (não as chamadas de ferramenta intermediárias) - o Tool
    Runner não expõe esse histórico interno pra reconstrução, e os dados
    mudam todo dia, então não faz sentido re-enviar resultado de ferramenta
    antigo em perguntas futuras da mesma sessão; o modelo simplesmente chama
    a ferramenta de novo se precisar do mesmo dado, o que é barato porque os
    resultados das ferramentas são pequenos e específicos, não um dump geral.
    """
    client = anthropic.Anthropic(api_key=anthropic_api_key)

    historico = mensagens_api + [{"role": "user", "content": pergunta}]

    runner = client.beta.messages.tool_runner(
        model=MODELO,
        max_tokens=4096,
        system=_montar_system_prompt(),
        tools=FERRAMENTAS,
        messages=historico,
        # Cacheia o prompt de sistema + as definições das ferramentas (que
        # não mudam entre as idas e vindas do tool-calling de uma pergunta,
        # nem entre perguntas seguidas da mesma sessão) - evita recobrar o
        # preço cheio desses tokens toda vez.
        cache_control={"type": "ephemeral"},
    )

    ultima_mensagem = None
    total_entrada = 0
    total_saida = 0
    numero_de_idas = 0
    for mensagem in runner:
        ultima_mensagem = mensagem
        total_entrada += mensagem.usage.input_tokens
        total_saida += mensagem.usage.output_tokens
        numero_de_idas += 1

    texto = next((bloco.text for bloco in ultima_mensagem.content if bloco.type == "text"), "")
    if not texto:
        texto = f"(sem resposta em texto - motivo de parada: {ultima_mensagem.stop_reason})"

    novo_historico = historico + [{"role": "assistant", "content": texto}]
    uso = {"tokens_entrada": total_entrada, "tokens_saida": total_saida, "idas_ao_modelo": numero_de_idas}
    return texto, novo_historico, uso


if __name__ == "__main__":
    # Teste isolado, sem Streamlit: roda perguntas manuais cobrindo cada
    # ferramenta e mede o consumo de tokens de cada resposta - a prova de
    # que o novo design não repete o custo do dump completo antigo.
    from config.settings import carregar_configuracao_anthropic

    config = carregar_configuracao_anthropic()

    perguntas_teste = [
        "Como está o desempenho da bancada gourmet ilha 120cm no último mês?",
        "Quais anúncios mais caíram recentemente?",
        "Quais os 5 anúncios com mais receita nos últimos 30 dias?",
        "Qual foi a última análise gerada?",
    ]

    mensagens: list[dict] = []
    for pergunta in perguntas_teste:
        print(f"\n{'=' * 70}\nPERGUNTA: {pergunta}\n{'=' * 70}")
        texto, mensagens, uso = responder_pergunta(pergunta, mensagens, config.api_key)
        print(f"\nRESPOSTA:\n{texto}")
        print(
            f"\n[tokens entrada={uso['tokens_entrada']} saida={uso['tokens_saida']} "
            f"idas_ao_modelo={uso['idas_ao_modelo']}] (design antigo: ~318.000 tokens de entrada/pergunta)"
        )
