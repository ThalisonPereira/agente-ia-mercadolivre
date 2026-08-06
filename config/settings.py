"""
config/settings.py

Carrega e valida as variáveis de ambiente do projeto a partir do
arquivo .env na raiz. Nenhum outro módulo deve ler variáveis de
ambiente diretamente - todos devem passar por este arquivo.

Por quê: se uma variável obrigatória estiver faltando, queremos
descobrir isso imediatamente ao iniciar o programa (fail fast),
não no meio de uma chamada à API do Mercado Livre.
"""
from pathlib import Path
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


class ConfiguracaoInvalidaError(Exception):
    """Lançada quando uma variável de ambiente obrigatória não foi definida."""


def _obter_variavel_obrigatoria(nome: str) -> str:
    valor = os.getenv(nome)
    if not valor:
        raise ConfiguracaoInvalidaError(
            f"A variável de ambiente '{nome}' não foi encontrada. "
            f"Verifique se o arquivo .env existe na raiz do projeto e contém essa chave."
        )
    return valor


@dataclass(frozen=True)
class MercadoLivreConfig:
    """Credenciais e parâmetros da integração OAuth2 com o Mercado Livre."""

    client_id: str
    client_secret: str
    redirect_uri: str


def carregar_configuracao_ml() -> MercadoLivreConfig:
    """Lê e valida as variáveis de ambiente do Mercado Livre, retornando um objeto imutável."""
    return MercadoLivreConfig(
        client_id=_obter_variavel_obrigatoria("ML_CLIENT_ID"),
        client_secret=_obter_variavel_obrigatoria("ML_CLIENT_SECRET"),
        redirect_uri=_obter_variavel_obrigatoria("ML_REDIRECT_URI"),
    )


CAMINHO_SERVICE_ACCOUNT = Path(__file__).resolve().parent / "google_service_account.json"


@dataclass(frozen=True)
class GoogleSheetsConfig:
    """Credenciais e parâmetros da integração com Google Sheets."""

    sheets_id: str
    service_account_path: Path


def carregar_configuracao_sheets() -> GoogleSheetsConfig:
    """Lê e valida a configuração do Google Sheets, incluindo o arquivo de credencial."""
    sheets_id = _obter_variavel_obrigatoria("GOOGLE_SHEETS_ID")

    if not CAMINHO_SERVICE_ACCOUNT.exists():
        raise ConfiguracaoInvalidaError(
            f"Arquivo de credencial não encontrado em '{CAMINHO_SERVICE_ACCOUNT}'. "
            "Verifique se google_service_account.json está dentro da pasta config/."
        )

    return GoogleSheetsConfig(sheets_id=sheets_id, service_account_path=CAMINHO_SERVICE_ACCOUNT)


@dataclass(frozen=True)
class AnthropicConfig:
    """Credenciais da API da Anthropic, usada pela análise de IA."""

    api_key: str


def carregar_configuracao_anthropic() -> AnthropicConfig:
    """Lê e valida a chave de API da Anthropic."""
    return AnthropicConfig(api_key=_obter_variavel_obrigatoria("ANTHROPIC_API_KEY"))


@dataclass(frozen=True)
class TursoConfig:
    """Credenciais do banco de dados hospedado (Turso/libSQL) - fonte de verdade
    dos dados, acessível tanto pela coleta local quanto pelo chat na nuvem."""

    database_url: str
    auth_token: str


def carregar_configuracao_turso() -> TursoConfig:
    """Lê e valida as credenciais do Turso."""
    return TursoConfig(
        database_url=_obter_variavel_obrigatoria("TURSO_DATABASE_URL"),
        auth_token=_obter_variavel_obrigatoria("TURSO_AUTH_TOKEN"),
    )
