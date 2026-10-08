"""
.github/scripts/parse_resposta_publicador.py

Usado só pelo workflow .github/workflows/alertas.yml - interpreta a resposta
JSON da rota do publicador (Lovable, src/routes/api/public/ml-alertas-publicador.ts)
de forma tolerante ao formato exato dos campos, exceto o único campo cujo
nome está confirmado em todas as versões vistas até agora: "processadas".

Saída (stdout), sempre 2 linhas, lidas pelo workflow via `grep`/`cut`:
    PROCESSADAS:<numero>
    RESUMO:<texto pra log>

Sai com código != 0 (sem nenhuma das 2 linhas) se o arquivo não for um JSON
válido ou não tiver o campo "processadas" - o workflow trata isso como falha
de verdade, nunca como "fila vazia".
"""

import json
import sys

CAMINHO_ARQUIVO = sys.argv[1]

# Campos informativos - nomes ainda não confirmados contra o código real no
# momento em que este script foi escrito (ver docs/progresso.md e o commit
# que introduziu este arquivo) - por isso são só informativos, com "n/d"
# como fallback, nunca motivo de falha do workflow.
CAMPOS_INFORMATIVOS = [
    "publicadasAgora",
    "mantidasPendentesPorFalhaPush",
    "semDestinatarios",
    "jaPublicadasPorConcorrencia",
    "falhasBroadcast",
    "falhasPush",
]


def main() -> None:
    try:
        with open(CAMINHO_ARQUIVO, encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
    except Exception as erro:
        print(f"ERRO_PARSE: resposta não é um JSON válido ({erro})", file=sys.stderr)
        sys.exit(1)

    if not isinstance(dados, dict) or "processadas" not in dados:
        print("ERRO_CAMPO: resposta sem o campo obrigatório 'processadas'", file=sys.stderr)
        sys.exit(1)

    partes = [f"processadas={dados['processadas']}"]
    for campo in CAMPOS_INFORMATIVOS:
        partes.append(f"{campo}={dados.get(campo, 'n/d')}")

    print(f"PROCESSADAS:{dados['processadas']}")
    print("RESUMO:" + " ".join(partes), file=sys.stderr)


if __name__ == "__main__":
    main()
