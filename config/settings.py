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
    if not valor or not valor.strip():
        raise ConfiguracaoInvalidaError(
            f"A variável de ambiente '{nome}' não foi encontrada. "
            f"Verifique se o arquivo .env existe na raiz do projeto e contém essa chave."
        )
    # .strip() remove espaços/quebras de linha acidentais (ex: secret do
    # GitHub Actions colado com um "Enter" sobrando no final, que quebra
    # bibliotecas HTTP como aiohttp - "Forbidden control character in headers").
    return valor.strip()


@dataclass(frozen=True)
class MercadoLivreConfig:
    """Credenciais e parâmetros da integração OAuth2 com o Mercado Livre."""

    client_id: str
    client_secret: str
    redirect_uri: str


def carregar_configuracao_ml(conta_id: str | None = None) -> MercadoLivreConfig:
    """
    Lê e valida as variáveis de ambiente do Mercado Livre pra uma conta
    específica, retornando um objeto imutável.

    Convenção pra múltiplas contas: ML_{CONTA_ID}_CLIENT_ID/_CLIENT_SECRET/
    _REDIRECT_URI (ex: ML_HC_CLIENT_ID pra conta_id="hc"). Se a variável
    prefixada não existir, cai pra ML_CLIENT_ID/_CLIENT_SECRET/_REDIRECT_URI
    sem prefixo - compatibilidade com a configuração de conta única já
    existente, sem exigir renomear o .env imediatamente.
    """
    def obter(sufixo: str) -> str:
        if conta_id:
            valor = os.getenv(f"ML_{conta_id.upper()}_{sufixo}")
            if valor and valor.strip():
                return valor.strip()
        return _obter_variavel_obrigatoria(f"ML_{sufixo}")

    return MercadoLivreConfig(
        client_id=obter("CLIENT_ID"),
        client_secret=obter("CLIENT_SECRET"),
        redirect_uri=obter("REDIRECT_URI"),
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
class BlingConfig:
    """Credenciais da integração OAuth2 com o Bling (ERP - fonte do custo de produto pra cálculo de margem)."""

    client_id: str
    client_secret: str
    redirect_uri: str


def carregar_configuracao_bling() -> BlingConfig:
    """Lê e valida as variáveis de ambiente do Bling. Credencial única, compartilhada
    por toda a operação (não é por conta de venda, diferente do Mercado Livre)."""
    return BlingConfig(
        client_id=_obter_variavel_obrigatoria("BLING_CLIENT_ID"),
        client_secret=_obter_variavel_obrigatoria("BLING_CLIENT_SECRET"),
        redirect_uri=_obter_variavel_obrigatoria("BLING_REDIRECT_URI"),
    )


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


@dataclass(frozen=True)
class SupabaseConfig:
    """Connection string direta do Postgres do Supabase - novo banco de dados
    (substitui o Turso), pra permitir uma interface nova (Lovable) consumir
    os mesmos dados que o Python já coleta/calcula."""

    database_url: str


def carregar_configuracao_supabase() -> SupabaseConfig:
    """Lê e valida a connection string do Supabase."""
    return SupabaseConfig(
        database_url=_obter_variavel_obrigatoria("SUPABASE_DB_URL"),
    )
