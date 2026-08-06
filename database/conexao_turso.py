"""
database/conexao_turso.py

Conexão com o banco de dados hospedado (Turso/libSQL) - substitui o SQLite
local (database/conexao.py) como fonte de verdade dos dados, acessível tanto
pela coleta local (main.py, roda no computador do usuário) quanto pelo chat
hospedado no Streamlit Cloud (chat_app.py).

Usa o pacote `libsql_client` (HTTP/websocket puro Python) em vez de `libsql`
(que embute o motor libSQL via extensão nativa em Rust) porque este último
não tem wheel pré-compilada para todas as plataformas e falhou ao compilar
localmente nesta máquina (faltando toolchain de compilação). `libsql_client`
fala o mesmo protocolo Hrana usado pelo Turso, sem precisar compilar nada.

Fornece uma interface parecida com sqlite3.Connection (execute/commit/close,
linhas acessíveis por nome de coluna como sqlite3.Row) para que o resto de
database/*.py não precise mudar - só o import de conexao.obter_conexao
para conexao_turso.obter_conexao.
"""

from __future__ import annotations

import time

import libsql_client

from config.settings import carregar_configuracao_turso

MAX_TENTATIVAS = 3


def _com_retry(func, *args, **kwargs):
    """
    Tenta de novo (com pequena espera) em caso de erro transitório de rede
    (ex: timeout numa chamada HTTP isolada, como já aconteceu na prática) -
    mesmo espírito do retry já usado nas chamadas à API do Mercado Livre
    (integrations/ml_client.py::_get_com_retry).
    """
    ultimo_erro = None
    for tentativa in range(MAX_TENTATIVAS):
        try:
            return func(*args, **kwargs)
        except Exception as erro:  # noqa: BLE001 - qualquer falha de rede/HTTP conta como transitória aqui
            ultimo_erro = erro
            if tentativa < MAX_TENTATIVAS - 1:
                espera = 2 ** tentativa
                print(f"Erro temporário ao falar com o Turso ({erro}). Tentando de novo em {espera}s...")
                time.sleep(espera)
    raise ultimo_erro


class _LinhaTurso:
    """Envolve uma linha (tupla) + nomes de coluna, pra acesso por nome como sqlite3.Row."""

    __slots__ = ("_valores", "_indices")

    def __init__(self, valores: tuple, indices: dict[str, int]):
        self._valores = valores
        self._indices = indices

    def __getitem__(self, chave):
        if isinstance(chave, str):
            return self._valores[self._indices[chave]]
        return self._valores[chave]

    def keys(self):
        return self._indices.keys()

    def __repr__(self):
        return f"_LinhaTurso({dict(zip(self._indices.keys(), self._valores))})"


class _ResultadoTurso:
    """Envolve o ResultSet do libsql_client, expondo fetchall()/fetchone() com linhas por nome."""

    def __init__(self, resultado):
        indices = {nome: i for i, nome in enumerate(resultado.columns)}
        self._linhas = [_LinhaTurso(linha, indices) for linha in resultado.rows]

    def fetchall(self) -> list[_LinhaTurso]:
        return self._linhas

    def fetchone(self) -> _LinhaTurso | None:
        return self._linhas[0] if self._linhas else None


class ConexaoTurso:
    """
    Envolve o cliente HTTP do libsql_client com interface parecida com
    sqlite3.Connection.

    O cliente HTTP do libsql_client não suporta transações interativas (só
    WebSocket suporta, e o handshake por WebSocket falhou nesse banco - ver
    obter_conexao() abaixo) - por isso cada execute() aqui já persiste
    imediatamente no servidor (uma requisição HTTP por chamada), e commit()
    é um no-op mantido só pra não quebrar o padrão "execute(); ...;
    commit(); close()" usado em todo o resto de database/*.py. Isso significa
    que, se um loop de várias escritas falhar no meio, as escritas já feitas
    ficam salvas (não há rollback automático) - aceitável aqui porque todas
    as escritas do projeto são upserts idempotentes (rodar de novo sobrescreve
    com o mesmo resultado, não duplica).
    """

    def __init__(self, cliente: "libsql_client.ClientSync"):
        self._cliente = cliente

    def execute(self, sql: str, params: dict | tuple | None = None) -> _ResultadoTurso:
        resultado = _com_retry(self._cliente.execute, sql, params if params is not None else {})
        return _ResultadoTurso(resultado)

    def executar_em_lote(self, instrucoes: list[tuple[str, dict]], tamanho_lote: int = 500) -> None:
        """
        Executa várias instruções (sql, params) em poucas requisições HTTP
        (lotes de até `tamanho_lote`) em vez de uma requisição por instrução.

        Usado por operações que escrevem muitas linhas de uma vez (ex:
        capturar_snapshot_diario, que grava ~190 anúncios x 2 upserts por
        dia) - várias requisições sequenciais têm mais chance de esbarrar
        num timeout de rede isolado (visto na prática), então agrupar reduz
        tanto o tempo total quanto a superfície de falha.
        """
        for inicio in range(0, len(instrucoes), tamanho_lote):
            lote = [
                libsql_client.Statement(sql, params)
                for sql, params in instrucoes[inicio:inicio + tamanho_lote]
            ]
            _com_retry(self._cliente.batch, lote)

    def commit(self) -> None:
        pass  # cada execute()/executar_em_lote() já foi persistido imediatamente - nada a fazer aqui.

    def close(self) -> None:
        self._cliente.close()


def obter_conexao() -> ConexaoTurso:
    """
    Abre uma conexão com o banco de dados Turso e retorna um objeto com
    execute()/commit()/close() compatível com o restante do database/*.py -
    mesmo padrão de uso do database/conexao.py local:

        conexao = obter_conexao()
        try:
            conexao.execute(SQL, {...})
            conexao.commit()
        finally:
            conexao.close()
    """
    config = carregar_configuracao_turso()
    # O esquema libsql:// mapeia pra WebSocket (wss://) no libsql_client, e o
    # handshake por WebSocket falhou nesse banco (erro 400) - HTTP funciona
    # normalmente, então convertemos aqui em vez de pedir pro usuário mudar
    # a URL que o painel do Turso forneceu.
    url = config.database_url.replace("libsql://", "https://", 1)
    cliente = libsql_client.create_client_sync(url, auth_token=config.auth_token)
    return ConexaoTurso(cliente)
