"""
scripts/migrar_para_multi_conta.py

Script de uso único (Fase 0): migra o banco Turso do schema antigo (uma
conta implícita, sem conta_id) para o schema multi-conta/multi-canal
(database/esquema.py).

O que faz, em ordem:
1. Renomeia as tabelas antigas (anuncios, historico_anuncios_diario,
   analises_diarias) com sufixo "_antigo", como backup - CREATE TABLE IF
   NOT EXISTS não altera tabelas já existentes, então não dá pra só rodar
   criar_tabelas() em cima delas.
2. Cria as tabelas novas (schema multi-conta) via criar_tabelas().
3. Cadastra a conta "hc" (Mercado Livre - HOME CASA) na tabela `contas`.
4. Copia os dados das tabelas antigas para as novas, preenchendo
   conta_id='hc' em cada linha.
5. Migra o token OAuth salvo localmente (config/.ml_tokens.json) para a
   tabela `tokens_oauth`, também sob conta_id='hc'.
6. Confere as contagens de linhas (antigo vs. novo) antes de considerar
   concluído.

As tabelas "_antigo" NÃO são apagadas automaticamente - ficam como backup
até a Fase 0 ser validada ponta a ponta; podem ser removidas manualmente
depois (DROP TABLE anuncios_antigo; etc.).

Roda uma vez: python -m scripts.migrar_para_multi_conta
"""

import json
from pathlib import Path

from database.conexao_turso import obter_conexao
from database.esquema import criar_tabelas
from database.contas import cadastrar_conta
from database.tokens_oauth import salvar_token

CONTA_ID = "hc"
CANAL = "mercado_livre"
NOME_CONTA = "HOME CASA"

CAMINHO_TOKEN_LOCAL = Path(__file__).resolve().parent.parent / "config" / ".ml_tokens.json"

TABELAS_ANTIGAS = ["anuncios", "historico_anuncios_diario", "analises_diarias"]


def _renomear_tabelas_antigas(conexao) -> None:
    print("Renomeando tabelas antigas (backup com sufixo '_antigo')...")
    for tabela in TABELAS_ANTIGAS:
        conexao.execute(f"ALTER TABLE {tabela} RENAME TO {tabela}_antigo")
    conexao.commit()


def _copiar_anuncios(conexao) -> int:
    linhas = conexao.execute("SELECT item_id, titulo, sku, atualizado_em FROM anuncios_antigo").fetchall()
    instrucoes = [
        (
            """
            INSERT INTO anuncios (conta_id, item_id, titulo, sku, atualizado_em)
            VALUES (:conta_id, :item_id, :titulo, :sku, :atualizado_em)
            ON CONFLICT(conta_id, item_id) DO UPDATE SET
                titulo = excluded.titulo,
                sku = excluded.sku,
                atualizado_em = excluded.atualizado_em;
            """,
            {
                "conta_id": CONTA_ID,
                "item_id": linha["item_id"],
                "titulo": linha["titulo"],
                "sku": linha["sku"],
                "atualizado_em": linha["atualizado_em"],
            },
        )
        for linha in linhas
    ]
    conexao.executar_em_lote(instrucoes)
    return len(linhas)


def _copiar_historico(conexao) -> int:
    linhas = conexao.execute(
        "SELECT item_id, data_snapshot, visitas, vendas_quantidade, receita, capturado_em "
        "FROM historico_anuncios_diario_antigo"
    ).fetchall()
    instrucoes = [
        (
            """
            INSERT INTO historico_anuncios_diario
                (conta_id, item_id, data_snapshot, visitas, vendas_quantidade, receita, capturado_em)
            VALUES
                (:conta_id, :item_id, :data_snapshot, :visitas, :vendas_quantidade, :receita, :capturado_em)
            ON CONFLICT(conta_id, item_id, data_snapshot) DO UPDATE SET
                visitas = excluded.visitas,
                vendas_quantidade = excluded.vendas_quantidade,
                receita = excluded.receita,
                capturado_em = excluded.capturado_em;
            """,
            {
                "conta_id": CONTA_ID,
                "item_id": linha["item_id"],
                "data_snapshot": linha["data_snapshot"],
                "visitas": linha["visitas"],
                "vendas_quantidade": linha["vendas_quantidade"],
                "receita": linha["receita"],
                "capturado_em": linha["capturado_em"],
            },
        )
        for linha in linhas
    ]
    conexao.executar_em_lote(instrucoes)
    return len(linhas)


def _copiar_analises(conexao) -> int:
    linhas = conexao.execute("SELECT data, texto, gerado_em FROM analises_diarias_antigo").fetchall()
    instrucoes = [
        (
            """
            INSERT INTO analises_diarias (conta_id, data, texto, gerado_em)
            VALUES (:conta_id, :data, :texto, :gerado_em)
            ON CONFLICT(conta_id, data) DO UPDATE SET
                texto = excluded.texto,
                gerado_em = excluded.gerado_em;
            """,
            {
                "conta_id": CONTA_ID,
                "data": linha["data"],
                "texto": linha["texto"],
                "gerado_em": linha["gerado_em"],
            },
        )
        for linha in linhas
    ]
    conexao.executar_em_lote(instrucoes)
    return len(linhas)


def _migrar_token_local() -> bool:
    if not CAMINHO_TOKEN_LOCAL.exists():
        print(f"Nenhum token local encontrado em {CAMINHO_TOKEN_LOCAL} - pulando.")
        return False
    dados = json.loads(CAMINHO_TOKEN_LOCAL.read_text(encoding="utf-8"))
    salvar_token(CONTA_ID, dados)
    print(f"Token OAuth migrado de {CAMINHO_TOKEN_LOCAL} para a tabela tokens_oauth (conta '{CONTA_ID}').")
    return True


def migrar() -> None:
    conexao = obter_conexao()
    try:
        tabelas_existentes = {
            linha["name"]
            for linha in conexao.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "anuncios_antigo" in tabelas_existentes:
            print("Tabelas antigas já foram renomeadas antes - pulando renomeação (script já rodou?).")
        elif "anuncios" in tabelas_existentes:
            _renomear_tabelas_antigas(conexao)
        else:
            print("Nenhuma tabela antiga encontrada (banco já vazio ou já migrado) - nada a renomear.")

        print("Criando tabelas novas (schema multi-conta)...")
        criar_tabelas()

        print(f"Cadastrando conta '{CONTA_ID}' ({CANAL})...")
        cadastrar_conta(CONTA_ID, CANAL, NOME_CONTA)

        total_anuncios = 0
        total_historico = 0
        total_analises = 0
        if "anuncios_antigo" in tabelas_existentes or "anuncios" in tabelas_existentes:
            print("Copiando anúncios...")
            total_anuncios = _copiar_anuncios(conexao)
            print("Copiando histórico diário...")
            total_historico = _copiar_historico(conexao)
            print("Copiando análises diárias...")
            total_analises = _copiar_analises(conexao)

        _migrar_token_local()
    finally:
        conexao.close()

    print("\nConferindo contagens...")
    conexao = obter_conexao()
    try:
        novo_anuncios = conexao.execute(
            "SELECT COUNT(*) AS total FROM anuncios WHERE conta_id = :c", {"c": CONTA_ID}
        ).fetchone()["total"]
        novo_historico = conexao.execute(
            "SELECT COUNT(*) AS total FROM historico_anuncios_diario WHERE conta_id = :c", {"c": CONTA_ID}
        ).fetchone()["total"]
        novo_analises = conexao.execute(
            "SELECT COUNT(*) AS total FROM analises_diarias WHERE conta_id = :c", {"c": CONTA_ID}
        ).fetchone()["total"]
    finally:
        conexao.close()

    print(f"anuncios: antigo={total_anuncios} novo(conta={CONTA_ID})={novo_anuncios}")
    print(f"historico_anuncios_diario: antigo={total_historico} novo(conta={CONTA_ID})={novo_historico}")
    print(f"analises_diarias: antigo={total_analises} novo(conta={CONTA_ID})={novo_analises}")

    if total_anuncios == novo_anuncios and total_historico == novo_historico and total_analises == novo_analises:
        print("\nMIGRAÇÃO CONFIRMADA COM SUCESSO.")
        print("As tabelas antigas (*_antigo) ficaram como backup - pode apagá-las manualmente depois de validar tudo.")
    else:
        print("\nATENÇÃO: as contagens não batem - revisar antes de considerar a migração concluída.")


if __name__ == "__main__":
    migrar()
