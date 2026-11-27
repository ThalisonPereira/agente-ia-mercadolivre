"""
scripts/recuperar_vendas_bling_local.py

Salva o que for legível de um dados_locais/vendas_bling.db corrompido ("database disk image is malformed") num arquivo NOVO.
O arquivo é só um cache dos pedidos do Bling: o que não for recuperado é coletado de novo pela rotina. Não altera o original.

Uso: python scripts/recuperar_vendas_bling_local.py ORIGEM.db DESTINO.db
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import vendas_bling_local as loja  # noqa: E402


def copiar_tabela(origem, destino, tabela, colunas):
    """Copia linha a linha (por rowid, em blocos que se dividem ao achar página ruim). Devolve (copiadas, perdidas)."""
    lista = ", ".join(colunas)
    marcas = ", ".join("?" for _ in colunas)
    copiadas, perdidas = 0, 0
    try:
        maximo = origem.execute(f"select max(rowid) from {tabela}").fetchone()[0] or 0
    except sqlite3.DatabaseError:
        maximo = 10_000_000
    pilha = [(1, maximo)]
    while pilha:
        a, b = pilha.pop()
        try:
            linhas = origem.execute(f"select {lista} from {tabela} where rowid between ? and ?", (a, b)).fetchall()
        except sqlite3.DatabaseError:
            if a == b:
                perdidas += 1
            else:
                meio = (a + b) // 2
                pilha.extend([(meio + 1, b), (a, meio)])
            continue
        if linhas:
            destino.executemany(f"insert or replace into {tabela} ({lista}) values ({marcas})", [tuple(l) for l in linhas])
            copiadas += len(linhas)
    destino.commit()
    return copiadas, perdidas


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return
    origem_p, destino_p = Path(sys.argv[1]), Path(sys.argv[2])
    if destino_p.exists():
        raise SystemExit(f"{destino_p} já existe: apague ou escolha outro nome.")
    origem = sqlite3.connect(f"file:{origem_p}?mode=ro", uri=True)
    destino = loja.abrir(destino_p)
    for tabela in ("pedidos", "itens"):
        colunas = [r[1] for r in destino.execute(f"pragma table_info({tabela})")]
        colunas_origem = {r[1] for r in origem.execute(f"pragma table_info({tabela})")}
        usar = [c for c in colunas if c in colunas_origem]
        copiadas, perdidas = copiar_tabela(origem, destino, tabela, usar)
        print(f"{tabela}: {copiadas} linhas copiadas, {perdidas} ilegíveis")
    print("integrity_check do novo arquivo:", destino.execute("pragma integrity_check").fetchone()[0])
    sem_itens = destino.execute(
        "select count(*) from pedidos p where p.detalhe_ok = 1 and p.conta_venda = 1 and not exists (select 1 from itens i where i.pedido_id = p.pedido_id)").fetchone()[0]
    print(f"pedidos que contam venda e ficaram sem itens (precisam ser recoletados): {sem_itens}")


if __name__ == "__main__":
    main()
