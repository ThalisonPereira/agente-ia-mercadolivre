"""
database/conexao_supabase.py

Conexão com o banco de dados hospedado (Supabase/Postgres) - substitui o
Turso/libSQL como fonte de verdade dos dados, pra permitir que uma
interface nova (Lovable) consuma os mesmos dados que o Python já coleta e
calcula. Interface idêntica a ConexaoTurso (database/conexao_turso.py:
execute/executar_em_lote/commit/close, linhas acessíveis por nome de
coluna) pra que o resto de database/*.py não precise mudar a lógica - só
o import (conexao_turso.obter_conexao -> conexao_supabase.obter_conexao)
e a sintaxe de parâmetro nomeado em cada SQL (:param -> %(param)s).

Diferente do Turso (cliente HTTP sem transação interativa, cada execute()
já persiste na hora, commit() é no-op), aqui commit()/close() usam
transação real do Postgres via psycopg2 - mais seguro que o modelo
anterior (um lote com falha no meio agora pode ser revertido de verdade).
"""

from __future__ import annotations

import time
from collections import OrderedDict

import psycopg2
import psycopg2.extras

from config.settings import carregar_configuracao_supabase

MAX_TENTATIVAS = 3


def _com_retry(func, *args, **kwargs):
    """Mesmo princípio de conexao_turso.py::_com_retry - erro transitório de rede tenta de novo."""
    ultimo_erro = None
    for tentativa in range(MAX_TENTATIVAS):
        try:
            return func(*args, **kwargs)
        except Exception as erro:  # noqa: BLE001 - qualquer falha de rede/HTTP conta como transitória aqui
            ultimo_erro = erro
            if tentativa < MAX_TENTATIVAS - 1:
                espera = 2 ** tentativa
                print(f"Erro temporário ao falar com o Supabase ({erro}). Tentando de novo em {espera}s...")
                time.sleep(espera)
    raise ultimo_erro


class _ResultadoSupabase:
    """Já vem materializado (lista de dicts) do cursor - mesma interface de _ResultadoTurso."""

    def __init__(self, linhas: list[dict]):
        self._linhas = linhas

    def fetchall(self) -> list[dict]:
        return self._linhas

    def fetchone(self) -> dict | None:
        return self._linhas[0] if self._linhas else None


class ConexaoSupabase:
    """Envolve a conexão psycopg2 com interface idêntica a ConexaoTurso."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql: str, params: dict | None = None) -> _ResultadoSupabase:
        def _executar():
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Importante: passar None (não {}) quando não há parâmetros -
                # psycopg2 só tenta interpretar '%' como início de placeholder
                # quando `vars` não é None; um SQL com '%' literal (ex: LIKE
                # 'algo%') sem nenhum parâmetro nomeado quebraria com "dict is
                # not a sequence" se mandássemos {} aqui.
                cur.execute(sql, params if params else None)
                if cur.description is None:  # instrução sem resultado (INSERT/UPDATE/CREATE/...)
                    return []
                return [dict(linha) for linha in cur.fetchall()]

        return _ResultadoSupabase(_com_retry(_executar))

    def executar_em_lote(self, instrucoes: list[tuple[str, dict]], tamanho_lote: int = 500) -> None:
        """
        Agrupa por SQL idêntico e usa execute_batch por grupo, dentro da
        mesma transação da conexão - só persiste de verdade no commit()
        explícito. O agrupamento NÃO assume que instruções do mesmo SQL
        vêm consecutivas (capturar_snapshot.py intercala UPSERT_ANUNCIO/
        UPSERT_SNAPSHOT item a item) - por isso agrupa por conteúdo, não
        por sequência (um `itertools.groupby` simples quebraria esse caso
        em lotes de 1, funcionando mas perdendo o ganho do batch).
        """
        grupos: OrderedDict[str, list[dict]] = OrderedDict()
        for sql, params in instrucoes:
            grupos.setdefault(sql, []).append(params)

        for sql, params_lista in grupos.items():
            with self._conn.cursor() as cur:
                _com_retry(psycopg2.extras.execute_batch, cur, sql, params_lista, page_size=tamanho_lote)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def obter_conexao() -> ConexaoSupabase:
    """
    Abre uma conexão com o banco de dados Supabase e retorna um objeto com
    execute()/commit()/close() compatível com o restante do database/*.py -
    mesmo padrão de uso já usado com o Turso:

        conexao = obter_conexao()
        try:
            conexao.execute(SQL, {...})
            conexao.commit()
        finally:
            conexao.close()
    """
    config = carregar_configuracao_supabase()
    conn = psycopg2.connect(config.database_url)
    return ConexaoSupabase(conn)
