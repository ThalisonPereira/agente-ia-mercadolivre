"""
Agente de IA para E-commerce (Mercado Livre) - Ponto de entrada principal.
"""

import sys
from datetime import date, datetime, timedelta

from config.settings import (
    carregar_configuracao_ml,
    carregar_configuracao_sheets,
    carregar_configuracao_anthropic,
    ConfiguracaoInvalidaError,
)
from integrations.ml_auth import passo1_gerar_link, passo2_trocar_code_por_token, passo3_testar_chamada_real, obter_seller_id
from integrations.ml_client import listar_itens_ativos, obter_detalhes_itens, obter_visitas_itens, obter_pedidos_periodo
from integrations.google_sheets import (
    publicar_resultado_no_sheets,
    publicar_analise_no_sheets,
    publicar_historico_completo_no_sheets,
    testar_conexao_sheets,
)
from database.capturar_snapshot import capturar_snapshot_diario
from database.analisar_variacao import obter_variacao_anuncios
from database.historico_completo import obter_historico_completo, obter_datas_existentes
from agents.analista_ia import analisar_e_salvar


def _testar_configuracao() -> None:
    try:
        config_ml = carregar_configuracao_ml()
        print("Configuração do Mercado Livre carregada com sucesso.")
        print(f"Redirect URI configurada: {config_ml.redirect_uri}")
    except ConfiguracaoInvalidaError as erro:
        print(f"Erro de configuração (Mercado Livre): {erro}")
        return

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


def _coletar_itens_ativos() -> tuple[str, list[str], list[dict]]:
    """Busca o vendedor, os ids de anúncios ativos e seus detalhes (título/SKU)."""
    seller_id = obter_seller_id()

    item_ids = listar_itens_ativos(seller_id)
    print(f"{len(item_ids)} anúncio(s) ativo(s) encontrado(s).")

    detalhes = obter_detalhes_itens(item_ids)
    return seller_id, item_ids, detalhes


def _coletar_dados_para_dia(
    seller_id: str, item_ids: list[str], detalhes: list[dict], dia: date
) -> list[dict]:
    """Busca visitas e vendas de um dia calendário específico para os itens informados."""
    # /items/{id}/visits só aceita data pura (YYYY-MM-DD) e date_to é exclusivo,
    # então "dia 00:00 até dia+1 00:00" cobre exatamente o dia inteiro.
    visitas_data_de = dia.isoformat()
    visitas_data_ate = (dia + timedelta(days=1)).isoformat()

    # /orders/search exige timestamp ISO 8601 completo, delimitando o mesmo dia.
    pedidos_data_de = f"{dia.isoformat()}T00:00:00.000-00:00"
    pedidos_data_ate = f"{dia.isoformat()}T23:59:59.000-00:00"

    visitas_por_item = obter_visitas_itens(item_ids, visitas_data_de, visitas_data_ate)
    pedidos = obter_pedidos_periodo(seller_id, pedidos_data_de, pedidos_data_ate)

    vendas_por_item: dict[str, dict] = {}
    for pedido in pedidos:
        for item in pedido.get("order_items", []):
            item_id = str(item.get("item", {}).get("id"))
            quantidade = item.get("quantity", 0)
            valor = item.get("unit_price", 0) * quantidade
            registro = vendas_por_item.setdefault(item_id, {"quantidade": 0, "receita": 0.0})
            registro["quantidade"] += quantidade
            registro["receita"] += valor

    dados_anuncios = []
    for item in detalhes:
        item_id = str(item["id"])
        vendas = vendas_por_item.get(item_id, {"quantidade": 0, "receita": 0.0})
        dados_anuncios.append({
            "item_id": item_id,
            "titulo": item.get("title", ""),
            "sku": item.get("seller_custom_field") or "",
            "visitas": visitas_por_item.get(item_id, 0),
            "vendas_quantidade": vendas["quantidade"],
            "receita": vendas["receita"],
        })

    return dados_anuncios


def _coletar_dados_do_dia() -> tuple[list[dict], date]:
    """
    Busca no Mercado Livre os anúncios ativos, visitas e vendas de ontem
    (dia calendário completo).

    Retorna os dados junto com a data de ontem, para que o snapshot seja
    salvo rotulado com o dia real dos dados - e não com o dia em que o
    script foi executado (as duas coisas só coincidem se a rotina rodar
    uma vez por dia, mas rotular pelo dia real evita duplicidade caso o
    comando seja rodado mais de uma vez no mesmo dia, como aconteceu em
    testes).
    """
    seller_id, item_ids, detalhes = _coletar_itens_ativos()
    ontem = (datetime.now().date() - timedelta(days=1))
    dados = _coletar_dados_para_dia(seller_id, item_ids, detalhes, ontem)
    return dados, ontem


def _backfill_periodo(data_inicio: date, data_fim: date) -> None:
    """
    Coleta e grava snapshots de cada dia entre data_inicio e data_fim (inclusive).

    Pula dias que já têm snapshot registrado no banco, para que o comando
    possa ser executado de novo com segurança após uma falha (ex: rate limit
    da API do Mercado Livre) sem refazer trabalho já concluído.
    """
    datas_existentes = obter_datas_existentes()
    seller_id, item_ids, detalhes = _coletar_itens_ativos()

    dia_atual = data_inicio
    while dia_atual <= data_fim:
        if dia_atual.isoformat() in datas_existentes:
            print(f"Pulando {dia_atual.isoformat()} (já coletado).")
        else:
            print(f"Coletando dados de {dia_atual.isoformat()}...")
            dados = _coletar_dados_para_dia(seller_id, item_ids, detalhes, dia_atual)
            capturar_snapshot_diario(dados, dia_atual)
        dia_atual += timedelta(days=1)


def _rotina_diaria() -> None:
    """Executa o pipeline completo: coleta -> snapshot -> comparação -> Sheets -> análise de IA."""
    dados, dia = _coletar_dados_do_dia()
    capturar_snapshot_diario(dados, dia)

    variacao = obter_variacao_anuncios()
    if variacao is None:
        print("Ainda não há snapshots suficientes para comparar (precisa de pelo menos 2 dias de histórico).")
        return

    publicar_resultado_no_sheets(variacao)

    data_str = dia.isoformat()
    texto_analise = analisar_e_salvar(variacao, data_str)
    publicar_analise_no_sheets(texto_analise, data_str)


if __name__ == "__main__":
    comando = sys.argv[1] if len(sys.argv) > 1 else None

    if comando == "config":
        _testar_configuracao()

    elif comando == "passo1":
        passo1_gerar_link()
    elif comando == "passo2":
        if len(sys.argv) < 3:
            print("Uso: python main.py passo2 SEU_AUTHORIZATION_CODE")
        else:
            passo2_trocar_code_por_token(sys.argv[2])
    elif comando == "passo3":
        passo3_testar_chamada_real()

    elif comando == "testar_sheets":
        testar_conexao_sheets()

    elif comando == "coletar_snapshot":
        dados, dia = _coletar_dados_do_dia()
        capturar_snapshot_diario(dados, dia)

    elif comando == "backfill":
        if len(sys.argv) < 4:
            print("Uso: python main.py backfill AAAA-MM-DD AAAA-MM-DD")
        else:
            _backfill_periodo(date.fromisoformat(sys.argv[2]), date.fromisoformat(sys.argv[3]))

    elif comando == "publicar_historico":
        historico = obter_historico_completo()
        publicar_historico_completo_no_sheets(historico)

    elif comando == "analisar_variacao":
        resultado = obter_variacao_anuncios()
        if resultado is None:
            print("Ainda não há snapshots suficientes para comparar.")
        else:
            for linha in resultado:
                print(f" - {linha['anuncio']}: visitas {linha['visitas']} ({linha['variacao_visitas']}%), "
                      f"vendas {linha['vendas']} ({linha['variacao_vendas']}%) - {linha['status']}")

    elif comando == "rotina_diaria":
        _rotina_diaria()

    else:
        print("Uso: python main.py [config|passo1|passo2 <code>|passo3|testar_sheets|"
              "coletar_snapshot|backfill <inicio> <fim>|publicar_historico|"
              "analisar_variacao|rotina_diaria]")
