"""
Agente de IA para E-commerce (multi-conta/multi-canal) - Ponto de entrada principal.
"""

import sys
from datetime import date, datetime, timedelta

from config.settings import (
    carregar_configuracao_sheets,
    carregar_configuracao_anthropic,
    ConfiguracaoInvalidaError,
)
from integrations.canais import obter_adaptador
from integrations.bling import BlingClient
from integrations.google_sheets import (
    publicar_resultado_no_sheets,
    publicar_analise_no_sheets,
    testar_conexao_sheets,
)
from database.contas import cadastrar_conta, obter_contas_ativas
from database.capturar_snapshot import capturar_snapshot_diario
from database.analisar_variacao import obter_variacao_anuncios
from database.historico_completo import obter_datas_existentes
from database.pedidos import salvar_pedidos_do_dia
from agents.analista_ia import analisar_e_salvar


def _testar_configuracao() -> None:
    try:
        carregar_configuracao_sheets()
        print("Configuração do Google Sheets carregada com sucesso.")
    except ConfiguracaoInvalidaError as erro:
        print(f"Erro de configuração (Sheets): {erro}")

    try:
        carregar_configuracao_anthropic()
        print("Configuração da Anthropic carregada com sucesso.")
    except ConfiguracaoInvalidaError as erro:
        print(f"Erro de configuração (Anthropic): {erro}")

    contas = obter_contas_ativas()
    if not contas:
        print("Nenhuma conta cadastrada ainda (rode 'python main.py cadastrar_conta <id> <canal> <nome>').")
    else:
        resumo = ", ".join(f"{c['conta_id']} ({c['canal']})" for c in contas)
        print(f"{len(contas)} conta(s) ativa(s): {resumo}")


def _coletar_dados_do_dia(conta_id: str, canal: str) -> tuple[list[dict], date]:
    """
    Busca no canal os anúncios ativos, visitas e vendas de ontem (dia
    calendário completo), pra uma conta específica.

    Retorna os dados junto com a data de ontem, para que o snapshot seja
    salvo rotulado com o dia real dos dados - e não com o dia em que o
    script foi executado (as duas coisas só coincidem se a rotina rodar
    uma vez por dia, mas rotular pelo dia real evita duplicidade caso o
    comando seja rodado mais de uma vez no mesmo dia, como aconteceu em
    testes).
    """
    adaptador = obter_adaptador(conta_id, canal)
    ontem = datetime.now().date() - timedelta(days=1)
    dados = adaptador.coletar_dados_do_dia(ontem)
    return dados, ontem


def _backfill_periodo(conta_id: str, canal: str, data_inicio: date, data_fim: date) -> None:
    """
    Coleta e grava snapshots de cada dia entre data_inicio e data_fim
    (inclusive), pra uma conta específica.

    Pula dias que já têm snapshot registrado no banco, para que o comando
    possa ser executado de novo com segurança após uma falha (ex: rate limit
    da API) sem refazer trabalho já concluído.
    """
    datas_existentes = obter_datas_existentes(conta_id)
    adaptador = obter_adaptador(conta_id, canal)

    dia_atual = data_inicio
    while dia_atual <= data_fim:
        if dia_atual.isoformat() in datas_existentes:
            print(f"[conta: {conta_id}] Pulando {dia_atual.isoformat()} (já coletado).")
        else:
            print(f"[conta: {conta_id}] Coletando dados de {dia_atual.isoformat()}...")
            dados = adaptador.coletar_dados_do_dia(dia_atual)
            capturar_snapshot_diario(conta_id, dados, dia_atual)
        dia_atual += timedelta(days=1)


def _rotina_diaria() -> None:
    """
    Executa o pipeline completo pra todas as contas ativas cadastradas:
    coleta -> snapshot -> comparação -> Sheets -> análise de IA.

    Cada conta é processada de forma independente - se uma falhar (ex:
    canal ainda não implementado, token expirado), as demais continuam.
    """
    contas = obter_contas_ativas()
    if not contas:
        print("Nenhuma conta ativa cadastrada. Rode 'python main.py cadastrar_conta <id> <canal> <nome>' primeiro.")
        return

    for conta in contas:
        conta_id, canal = conta["conta_id"], conta["canal"]
        print(f"\n=== Conta: {conta_id} ({canal}) ===")

        try:
            dados, dia = _coletar_dados_do_dia(conta_id, canal)
        except NotImplementedError as erro:
            print(f"[conta: {conta_id}] {erro}")
            continue
        except Exception as erro:
            print(f"[conta: {conta_id}] Falha ao coletar dados: {erro}")
            continue

        capturar_snapshot_diario(conta_id, dados, dia)

        try:
            pedidos = obter_adaptador(conta_id, canal).coletar_pedidos_do_dia(dia)
            salvar_pedidos_do_dia(conta_id, pedidos, dia)
        except NotImplementedError as erro:
            print(f"[conta: {conta_id}] {erro}")
        except Exception as erro:
            print(f"[conta: {conta_id}] Falha ao coletar pedidos: {erro}")

        variacao = obter_variacao_anuncios(conta_id=conta_id)
        if variacao is None:
            print(f"[conta: {conta_id}] Ainda não há snapshots suficientes para comparar (precisa de pelo menos 2 dias de histórico).")
            continue

        # A aba do Sheets ainda é única (não por conta) - com só 1 conta
        # ativa isso não é problema; quando existir uma 2ª conta de verdade,
        # essa publicação passa a sobrescrever a anterior (limitação
        # conhecida, o Sheets é uma visão secundária, não a fonte principal).
        publicar_resultado_no_sheets(variacao)

        data_str = dia.isoformat()
        texto_analise = analisar_e_salvar(variacao, data_str, conta_id=conta_id)
        publicar_analise_no_sheets(texto_analise, data_str)


if __name__ == "__main__":
    comando = sys.argv[1] if len(sys.argv) > 1 else None

    if comando == "config":
        _testar_configuracao()

    elif comando == "cadastrar_conta":
        if len(sys.argv) < 5:
            print("Uso: python main.py cadastrar_conta <conta_id> <canal> <nome>")
        else:
            cadastrar_conta(sys.argv[2], sys.argv[3], sys.argv[4])
            print(f"Conta '{sys.argv[2]}' ({sys.argv[3]}) cadastrada.")

    elif comando == "passo1":
        if len(sys.argv) < 3:
            print("Uso: python main.py passo1 <conta_id>")
        else:
            obter_adaptador(sys.argv[2], "mercado_livre").gerar_link_autorizacao()
    elif comando == "passo2":
        if len(sys.argv) < 4:
            print("Uso: python main.py passo2 <conta_id> SEU_AUTHORIZATION_CODE")
        else:
            obter_adaptador(sys.argv[2], "mercado_livre").trocar_code_por_token(sys.argv[3])
    elif comando == "passo3":
        if len(sys.argv) < 3:
            print("Uso: python main.py passo3 <conta_id>")
        else:
            obter_adaptador(sys.argv[2], "mercado_livre").testar_chamada_real()

    elif comando == "bling_passo1":
        BlingClient().gerar_link_autorizacao()
    elif comando == "bling_passo2":
        if len(sys.argv) < 3:
            print("Uso: python main.py bling_passo2 SEU_AUTHORIZATION_CODE")
        else:
            BlingClient().trocar_code_por_token(sys.argv[2])
    elif comando == "bling_passo3":
        BlingClient().testar_chamada_real()

    elif comando == "testar_sheets":
        testar_conexao_sheets()

    elif comando == "coletar_snapshot":
        if len(sys.argv) < 4:
            print("Uso: python main.py coletar_snapshot <conta_id> <canal>")
        else:
            dados, dia = _coletar_dados_do_dia(sys.argv[2], sys.argv[3])
            capturar_snapshot_diario(sys.argv[2], dados, dia)

    elif comando == "backfill":
        if len(sys.argv) < 6:
            print("Uso: python main.py backfill <conta_id> <canal> AAAA-MM-DD AAAA-MM-DD")
        else:
            _backfill_periodo(
                sys.argv[2], sys.argv[3],
                date.fromisoformat(sys.argv[4]), date.fromisoformat(sys.argv[5]),
            )

    elif comando == "analisar_variacao":
        conta_id_filtro = sys.argv[2] if len(sys.argv) > 2 else None
        resultado = obter_variacao_anuncios(conta_id=conta_id_filtro)
        if resultado is None:
            print("Ainda não há snapshots suficientes para comparar.")
        else:
            for linha in resultado:
                print(f" - [{linha['conta_id']}] {linha['anuncio']}: visitas {linha['visitas']} ({linha['variacao_visitas']}%), "
                      f"vendas {linha['vendas']} ({linha['variacao_vendas']}%) - {linha['status']}")

    elif comando == "rotina_diaria":
        _rotina_diaria()

    else:
        print("Uso: python main.py [config|cadastrar_conta <id> <canal> <nome>|"
              "passo1 <conta_id>|passo2 <conta_id> <code>|passo3 <conta_id>|"
              "bling_passo1|bling_passo2 <code>|bling_passo3|"
              "testar_sheets|coletar_snapshot <conta_id> <canal>|"
              "backfill <conta_id> <canal> <inicio> <fim>|"
              "analisar_variacao [conta_id]|rotina_diaria]")
