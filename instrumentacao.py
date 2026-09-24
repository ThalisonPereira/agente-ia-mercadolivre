"""
instrumentacao.py

Instrumentação TEMPORÁRIA de medição (Fase 1 do plano de otimização
multi-conta, ver auditoria de concorrência desta sessão) - mede tempo por
conta/bloco e conta chamadas HTTP feitas ao Mercado Livre, por endpoint,
sem mudar nenhum comportamento funcional da rotina diária.

Não escreve em nenhum banco - vive só em memória durante a execução e
termina num relatório de texto (Metricas.relatorio()), impresso no
console. Não registra token, credencial nem payload de resposta - só o
"rótulo" do endpoint (uma string curta escolhida no código, ex:
"orders_search"), a conta_id e a contagem/duração.

Pensada pra ser removida (ou só deixada de fora do uso, sem excluir)
depois que a Fase 1 tiver os números reais precisados pra decidir a Fase
1.5 (concorrência entre contas).
"""

import threading
import time
from collections import defaultdict
from contextlib import contextmanager


class Metricas:
    """Acumula tempos por conta/bloco e contagem de chamadas HTTP por conta/rótulo."""

    def __init__(self):
        self.tempo_total_rotina: float | None = None
        self.tempo_por_conta: dict[str, float] = {}
        # conta_id -> {nome_do_bloco: segundos acumulados}. Acumula (soma)
        # em vez de sobrescrever, porque alguns blocos são medidos mais de
        # uma vez na mesma conta (ex: extrato roda 1x por dia da janela de
        # reconciliação) - queremos o total do bloco, não só a última medição.
        self.tempo_por_bloco: dict[str, dict[str, float]] = defaultdict(dict)
        # Etapas que não são por conta (sync do Bling antes do loop,
        # divergência de estoque depois do loop - compartilhados entre as 3 contas).
        self.tempo_geral: dict[str, float] = {}
        # conta_id -> {rotulo_endpoint: quantidade de requisições reais enviadas}
        self.chamadas_por_conta: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        # conta_id -> quantas instâncias de MercadoLivreCanal foram criadas
        # durante esta execução (ver seção 6 da auditoria - hoje esperado
        # ~4 por conta, uma por bloco que chama obter_adaptador de novo).
        self.instancias_canal_por_conta: dict[str, int] = defaultdict(int)

        # Fase 3 (concorrência dentro da conta, coleta de visitas) - novos
        # campos, mesmo padrão de lock dos demais.
        # conta_id -> {bloco: nº de workers usados na última chamada}
        self.workers_por_bloco: dict[str, dict[str, int]] = defaultdict(dict)
        # conta_id -> {rotulo: nº de retries (429/5xx) decididos em _get_com_retry}
        self.retries_por_conta: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        # conta_id -> {rotulo: nº de itens que falharam de forma isolada (não geral)}
        self.falhas_por_conta: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

        self._inicio_rotina: float | None = None
        # Fase 2 (concorrência entre contas) - as contas rodam em threads
        # separadas e podem chamar medir_conta/medir_bloco/registrar_* ao
        # mesmo tempo (cada uma só escreve na própria chave de conta_id,
        # nunca colidindo, mas protege mesmo assim contra qualquer
        # comportamento não garantido de dict do Python sob concorrência).
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Medição de tempo
    # ------------------------------------------------------------------

    @contextmanager
    def medir_rotina(self):
        self._inicio_rotina = time.perf_counter()
        try:
            yield
        finally:
            self.tempo_total_rotina = time.perf_counter() - self._inicio_rotina

    @contextmanager
    def medir_conta(self, conta_id: str):
        inicio = time.perf_counter()
        try:
            yield
        finally:
            duracao = time.perf_counter() - inicio
            with self._lock:
                self.tempo_por_conta[conta_id] = duracao

    @contextmanager
    def medir_bloco(self, conta_id: str, bloco: str):
        """Mede um bloco nomeado dentro de uma conta - soma se o mesmo bloco for medido mais de uma vez."""
        inicio = time.perf_counter()
        try:
            yield
        finally:
            duracao = time.perf_counter() - inicio
            with self._lock:
                blocos_da_conta = self.tempo_por_bloco[conta_id]
                blocos_da_conta[bloco] = blocos_da_conta.get(bloco, 0.0) + duracao

    @contextmanager
    def medir_etapa_geral(self, nome: str):
        """Mede uma etapa que não é por conta (sync do Bling, estoque compartilhado)."""
        inicio = time.perf_counter()
        try:
            yield
        finally:
            duracao = time.perf_counter() - inicio
            with self._lock:
                self.tempo_geral[nome] = self.tempo_geral.get(nome, 0.0) + duracao

    # ------------------------------------------------------------------
    # Contagem de chamadas / instâncias
    # ------------------------------------------------------------------

    def registrar_chamada(self, conta_id: str, rotulo: str) -> None:
        """Incrementa o contador da conta/rótulo informado. Não recebe (nem grava) nenhum dado de payload/credencial."""
        with self._lock:
            self.chamadas_por_conta[conta_id][rotulo] += 1

    def registrar_instancia_canal(self, conta_id: str) -> None:
        with self._lock:
            self.instancias_canal_por_conta[conta_id] += 1

    def registrar_workers(self, conta_id: str, bloco: str, workers: int) -> None:
        with self._lock:
            self.workers_por_bloco[conta_id][bloco] = workers

    def registrar_retry(self, conta_id: str, rotulo: str) -> None:
        with self._lock:
            self.retries_por_conta[conta_id][rotulo] += 1

    def registrar_falha_item(self, conta_id: str, rotulo: str) -> None:
        with self._lock:
            self.falhas_por_conta[conta_id][rotulo] += 1

    # ------------------------------------------------------------------
    # Relatório
    # ------------------------------------------------------------------

    def relatorio(self) -> str:
        linhas = [
            "=" * 78,
            "RELATÓRIO DE INSTRUMENTAÇÃO - FASE 1 (medição, sem efeito no comportamento funcional)",
            "=" * 78,
        ]

        if self.tempo_total_rotina is not None:
            linhas.append(f"Tempo total da rotina: {self.tempo_total_rotina:.1f}s")

        if self.tempo_geral:
            linhas.append("\n--- Etapas gerais (não são por conta) ---")
            for nome, duracao in sorted(self.tempo_geral.items(), key=lambda x: -x[1]):
                linhas.append(f"  {nome:32s} {duracao:8.2f}s")

        for conta_id in self.tempo_por_conta:
            segundos_conta = self.tempo_por_conta[conta_id]
            linhas.append(f"\n--- Conta: {conta_id} (total: {segundos_conta:.1f}s) ---")

            blocos = self.tempo_por_bloco.get(conta_id, {})
            for bloco, duracao in sorted(blocos.items(), key=lambda x: -x[1]):
                pct = (duracao / segundos_conta * 100) if segundos_conta else 0.0
                linhas.append(f"  {bloco:32s} {duracao:8.2f}s ({pct:5.1f}%)")

            chamadas = self.chamadas_por_conta.get(conta_id, {})
            total_chamadas = sum(chamadas.values())
            linhas.append(f"  Chamadas HTTP ao Mercado Livre: {total_chamadas}")
            for rotulo, n in sorted(chamadas.items(), key=lambda x: -x[1]):
                linhas.append(f"    {rotulo:30s} {n:5d}")

            instancias = self.instancias_canal_por_conta.get(conta_id, 0)
            linhas.append(f"  Instâncias de MercadoLivreCanal criadas: {instancias}")

            workers = self.workers_por_bloco.get(conta_id, {})
            for bloco, n in sorted(workers.items()):
                linhas.append(f"  Workers usados ({bloco}): {n}")

            retries = self.retries_por_conta.get(conta_id, {})
            if retries:
                linhas.append(f"  Retries (429/5xx): {sum(retries.values())}")
                for rotulo, n in sorted(retries.items(), key=lambda x: -x[1]):
                    linhas.append(f"    {rotulo:30s} {n:5d}")

            falhas = self.falhas_por_conta.get(conta_id, {})
            if falhas:
                linhas.append(f"  Falhas individuais de item: {sum(falhas.values())}")
                for rotulo, n in sorted(falhas.items(), key=lambda x: -x[1]):
                    linhas.append(f"    {rotulo:30s} {n:5d}")

        linhas.append("=" * 78)
        return "\n".join(linhas)
