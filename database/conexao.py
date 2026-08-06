"""
database/conexao.py

Responsável apenas por abrir uma conexão com o arquivo SQLite local.
Não sabe nada sobre tabelas ou dados - só entrega uma conexão pronta pra uso.
"""

import sqlite3
from pathlib import Path

CAMINHO_BANCO = Path(__file__).resolve().parent / "monitoramento.db"


def obter_conexao() -> sqlite3.Connection:
    """
    Abre (ou cria, se não existir) o arquivo do banco SQLite e retorna
    uma conexão configurada para devolver linhas como dicionários
    (em vez de tuplas posicionais, o que deixa o código mais legível).
    """
    conexao = sqlite3.connect(CAMINHO_BANCO)
    conexao.row_factory = sqlite3.Row
    return conexao
