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
from database.pedidos import salvar_pedidos_do_dia, obter_resumo as obter_resumo_pedidos
from database.custo_produtos import sincronizar as sincronizar_custo_produtos
from database.pedidos_bling import sincronizar as sincronizar_pedidos_bling
from database.extrato import salvar_itens_venda_do_dia
from database.ads import salvar_campanhas_do_dia, salvar_anuncios_do_dia, obter_resumo as obter_resumo_ads
from database.kpis import obter_totais_periodo, obter_data_mais_recente
from database.estoque import obter_divergencias, obter_anuncios_em_risco, salvar_divergencias, salvar_risco
from agents.analista_ia import analisar_e_salvar
from agents.analista_ads_ia import analisar_e_salvar_ads
from agents.analista_estoque_ia import analisar_e_salvar_estoque

# Quantos dias pra trás a rotina diária reprocessa o extrato de vendas (não
# só "ontem"). Necessário porque um pedido pode ficar "pendente" (aguardando
# confirmação de pagamento, ex: boleto) no dia em que é coletado e só virar
# "pago"/"cancelado" depois - reprocessar essa janela corrige a linha
# automaticamente assim que o status real mudar (ver
# coletar_extrato_do_dia). Pedido que demore mais que isso pra confirmar
# fica com o status desatualizado (limitação aceita, documentada, não
# escondida - raríssimo em pagamentos no Brasil).
DIAS_JANELA_RECONCILIACAO_EXTRATO = 5


def _resumo_kpis() -> str:
    """
    Monta um resumo compacto em texto dos KPIs mais recentes (vendas,
    publicidade, pedidos, estoque) - pensado pra ser consumido por
    ferramentas externas (ex: um agente pessoal agendado, tipo Hermes)
    via 'python main.py resumo_kpis', não só por gente lendo o console.
    Só leitura - não coleta nada novo, usa o que a rotina diária já
    salvou no banco.
    """
    contas = obter_contas_ativas()
    data_recente = obter_data_mais_recente()
    linhas = [f"=== Resumo — {datetime.now().strftime('%d/%m/%Y %H:%M')} ==="]

    if not contas:
        linhas.append("Nenhuma conta ativa cadastrada.")
        return "\n".join(linhas)

    if not data_recente:
        linhas.append("Ainda não há nenhum dado coletado.")
        return "\n".join(linhas)

    linhas.append(f"Última coleta: {data_recente}")
    atrasadas = [
        c["conta_id"] for c in contas
        if obter_data_mais_recente(conta_id=c["conta_id"]) != data_recente
    ]
    if atrasadas:
        linhas.append(f"⚠ Conta(s) atrasada(s) na coleta: {', '.join(atrasadas)}")

    totais = obter_totais_periodo(data_recente, data_recente)
    linhas.append(
        f"\nVendas de {data_recente}: {totais['vendas']} unidade(s), "
        f"R$ {totais['receita']:.2f} receita, {totais['visitas']} visita(s)"
    )
    for c in contas:
        t = obter_totais_periodo(data_recente, data_recente, conta_id=c["conta_id"])
        linhas.append(f"  [{c['conta_id']}] {t['vendas']} vendas · R$ {t['receita']:.2f} · {t['visitas']} visitas")

    ads = obter_resumo_ads(data_recente, data_recente)
    if ads["cost"]:
        linhas.append(
            f"\nPublicidade: R$ {ads['cost']:.2f} investido · ROAS {ads['roas']}x · "
            f"ACOS {ads['acos']}% · {ads['clicks']} clique(s)"
        )

    pedidos = obter_resumo_pedidos(data_recente)
    if pedidos["total"]:
        linhas.append(
            f"\nPedidos: {pedidos['total']} · pronto p/ envio {pedidos['imediato']} · "
            f"aguardando {pedidos['postergado']} · cancelado {pedidos['cancelado']} · "
            f"R$ {pedidos['valor_total']:.2f}"
        )

    divergencias = obter_divergencias()
    criticas = [d for d in divergencias if d["categoria"] == "risco_venda_sem_estoque"]
    if criticas:
        linhas.append(f"\n⚠ Estoque - {len(criticas)} SKU(s) com risco de venda sem estoque:")
        for d in criticas[:5]:
            linhas.append(f"  {d['sku']}: publicado {d['soma_ml']} vs Bling {d['saldo_bling']} (dif. +{d['diferenca']})")
    outras = [d for d in divergencias if d["categoria"] != "risco_venda_sem_estoque"]
    if outras:
        linhas.append(f"Estoque - {len(outras)} outra(s) divergência(s) sem risco imediato (ex: SKU sem controle no Bling).")
    if not divergencias:
        linhas.append("\nEstoque: nenhuma divergência.")

    em_risco = obter_anuncios_em_risco()
    if em_risco:
        linhas.append(f"\n⚠ {len(em_risco)} anúncio(s) ranqueado(s) perto de pausar por falta de estoque:")
        for r in em_risco[:5]:
            dias = f"{r['dias_restantes_estimados']:.1f}d" if r["dias_restantes_estimados"] is not None else "sem estimativa"
            linhas.append(f"  {r['anuncio']} ({r['conta_id']}): estoque {r['estoque_disponivel']} · {dias} restante(s)")

    return "\n".join(linhas)


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

    # O Bling não é por conta (credencial única, ver integrations/bling.py) -
    # sincroniza o custo de produto 1x por rodada, antes do loop por conta.
    try:
        produtos_bling = BlingClient().listar_produtos()
        sincronizar_custo_produtos(produtos_bling)
    except Exception as erro:
        print(f"Falha ao sincronizar produtos do Bling: {erro}")

    # Mesmo princípio, pro cruzamento de número de pedido (extrato mostra
    # o número da venda no ML e no Bling lado a lado) - janela igual à de
    # reconciliação do extrato, com 2 dias de folga (o pedido pode levar
    # um pouco pra chegar no Bling depois de confirmado no ML).
    try:
        janela_inicio = (datetime.now().date() - timedelta(days=DIAS_JANELA_RECONCILIACAO_EXTRATO + 2)).isoformat()
        janela_fim = datetime.now().date().isoformat()
        pedidos_bling = BlingClient().listar_pedidos_vendas(janela_inicio, janela_fim)
        sincronizar_pedidos_bling(pedidos_bling)
    except Exception as erro:
        print(f"Falha ao sincronizar pedidos do Bling: {erro}")

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

        try:
            adaptador_extrato = obter_adaptador(conta_id, canal)
            for offset in range(DIAS_JANELA_RECONCILIACAO_EXTRATO):
                dia_reconciliacao = dia - timedelta(days=offset)
                itens_venda = adaptador_extrato.coletar_extrato_do_dia(dia_reconciliacao)
                salvar_itens_venda_do_dia(conta_id, itens_venda, dia_reconciliacao)
        except NotImplementedError as erro:
            print(f"[conta: {conta_id}] {erro}")
        except Exception as erro:
            print(f"[conta: {conta_id}] Falha ao coletar extrato de vendas: {erro}")

        try:
            adaptador_ads = obter_adaptador(conta_id, canal)
            campanhas_ads = adaptador_ads.coletar_campanhas_ads_do_dia(dia)
            salvar_campanhas_do_dia(conta_id, campanhas_ads, dia)
            anuncios_ads = adaptador_ads.coletar_anuncios_ads_do_dia(dia)
            salvar_anuncios_do_dia(conta_id, anuncios_ads, dia)
            if campanhas_ads:
                analisar_e_salvar_ads(campanhas_ads, dia.isoformat(), conta_id=conta_id)
        except NotImplementedError as erro:
            print(f"[conta: {conta_id}] {erro}")
        except Exception as erro:
            print(f"[conta: {conta_id}] Falha ao coletar publicidade: {erro}")

        variacao = obter_variacao_anuncios(conta_id=conta_id)
        if variacao is None:
            print(f"[conta: {conta_id}] Ainda não há snapshots suficientes para comparar (precisa de pelo menos 2 dias de histórico).")
            continue

        # Cada conta publica na sua própria aba ("Dados - <conta_id>",
        # "Análise IA - <conta_id>") - várias contas ativas não sobrescrevem
        # a publicação umas das outras.
        publicar_resultado_no_sheets(variacao, conta_id)

        data_str = dia.isoformat()
        texto_analise = analisar_e_salvar(variacao, data_str, conta_id=conta_id)
        publicar_analise_no_sheets(texto_analise, data_str, conta_id)

    # Depois do loop por conta (só faz sentido comparar estoque com as 3
    # contas já atualizadas nesta rodada) - estoque é compartilhado pelas
    # contas, então é uma análise única "geral", não por conta.
    try:
        divergencias = obter_divergencias()
        em_risco = obter_anuncios_em_risco()
        # Sobrescreve o snapshot mesmo quando vazio - um SKU que deixou de
        # divergir não pode ficar preso na tabela com dado velho (ver
        # database/estoque.py::salvar_divergencias).
        salvar_divergencias(divergencias)
        salvar_risco(em_risco)
        if divergencias or em_risco:
            analisar_e_salvar_estoque(divergencias, em_risco, datetime.now().date().isoformat())
        else:
            print("Estoque: nenhuma divergência nem anúncio ranqueado em risco hoje.")
    except Exception as erro:
        print(f"Falha ao analisar estoque: {erro}")


if __name__ == "__main__":
    comando = sys.argv[1] if len(sys.argv) > 1 else None

    if comando == "config":
        _testar_configuracao()

    elif comando == "resumo_kpis":
        print(_resumo_kpis())

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

    elif comando == "ads_diagnostico":
        if len(sys.argv) < 3:
            print("Uso: python main.py ads_diagnostico <conta_id>")
        else:
            obter_adaptador(sys.argv[2], "mercado_livre").testar_chamada_advertising()

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
              "ads_diagnostico <conta_id>|"
              "bling_passo1|bling_passo2 <code>|bling_passo3|"
              "testar_sheets|coletar_snapshot <conta_id> <canal>|"
              "backfill <conta_id> <canal> <inicio> <fim>|"
              "analisar_variacao [conta_id]|rotina_diaria|resumo_kpis]")
