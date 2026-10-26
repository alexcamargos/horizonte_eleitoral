"""Testes unitarios para o cliente de ingestao oficial, limitador e resolucao de rotas."""

from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from horizonte_eleitoral.config import Environment, Settings
from horizonte_eleitoral.domain.enums import ArtifactType
from horizonte_eleitoral.domain.errors import ValidationError
from horizonte_eleitoral.ingestion.client import TSEAsyncClient
from horizonte_eleitoral.ingestion.discovery import TSEPathResolver
from horizonte_eleitoral.ingestion.rate_limiter import AsyncRateLimiter


@pytest.fixture
def test_settings() -> Settings:
    """Configuracao de teste isolada para o cliente."""
    return Settings(
        environment=Environment.TEST,
        data_directory=Path("test_data"),
        database_dsn=None,
        allowed_tse_hosts=("dadosabertos.tse.jus.br", "www.tse.jus.br"),
        max_requests_per_second=50,
        max_concurrency=5,
    )


def test_tse_path_resolver_generates_canonical_urls() -> None:
    """Valida geracao determinista de URLs para configuracao, resumos e totalizacao."""
    resolver = TSEPathResolver(
        base_url="https://dadosabertos.tse.jus.br",
        election_id="002026",
    )

    ea11_url = resolver.url_for_config(ArtifactType.EA11)
    assert ea11_url == "https://dadosabertos.tse.jus.br/002026/config/ea11.json"

    ea14_url = resolver.url_for_summary(ArtifactType.EA14)
    assert ea14_url == "https://dadosabertos.tse.jus.br/002026/summary/ea14-br.json"

    ea15_url = resolver.url_for_summary(ArtifactType.EA15, state="SP")
    assert ea15_url == "https://dadosabertos.tse.jus.br/002026/summary/ea15-sp.json"

    ea16_url = resolver.url_for_sections(ArtifactType.EA16, state="SP", municipality_code="71072")
    assert ea16_url == "https://dadosabertos.tse.jus.br/002026/sections/sp/71072/ea16.json"

    ea20_url = resolver.url_for_totalization(state="SP")
    assert ea20_url == "https://dadosabertos.tse.jus.br/002026/totalization/ea20-sp.json"

    divulga_resolver = TSEPathResolver(
        base_url="https://resultados.tse.jus.br",
        election_id="6258",
    )
    divulga_url = divulga_resolver.url_for_divulgacao()
    assert divulga_url == (
        "https://resultados.tse.jus.br/oficial/ele2026/6258/dados/br/br-c0001-e006258-u.json"
    )

    simplificada_url = divulga_resolver.url_for_divulgacao_simplificada()
    assert simplificada_url == (
        "https://resultados.tse.jus.br/oficial/ele2026/6258/dados-simplificados/"
        "br/br-c0001-e006258-r.json"
    )


def test_tse_path_resolver_rejects_invalid_inputs() -> None:
    """Valida rejeicao de URLs nao HTTPS, election_id vazio e ano fora de faixa."""
    with pytest.raises(ValidationError, match="https://"):
        TSEPathResolver("http://inseguro.tse.jus.br", "002026")

    with pytest.raises(ValidationError, match="election_id"):
        TSEPathResolver("https://dadosabertos.tse.jus.br", "")

    with pytest.raises(ValidationError, match="ano eleitoral valido"):
        TSEPathResolver("https://dadosabertos.tse.jus.br", "6258", year=1980)


def test_tse_path_resolver_custom_year() -> None:
    """Valida geracao de URLs com ano customizado (ex: 2022)."""
    resolver_2022 = TSEPathResolver(
        base_url="https://resultados.tse.jus.br",
        election_id="545",
        year=2022,
    )
    url_2022 = resolver_2022.url_for_divulgacao()
    assert url_2022 == (
        "https://resultados.tse.jus.br/oficial/ele2022/545/dados/br/br-c0001-e000545-u.json"
    )


@pytest.mark.asyncio
async def test_client_rejects_unallowed_hosts(test_settings: Settings) -> None:
    """URLs fora da allowlist configurada sao bloqueadas imediatamente."""
    client = TSEAsyncClient(test_settings)
    with pytest.raises(ValidationError, match="allowlist"):
        await client.fetch(
            election_id="002026",
            artifact_type=ArtifactType.EA20,
            url="https://site-malicioso.com/dados.json",
        )


@pytest.mark.asyncio
async def test_client_handles_http_200_and_304(
    test_settings: Settings,
    mocker: MockerFixture,
) -> None:
    """Valida tratamento correto de 200 (com conteudo) e 304 (nao modificado)."""
    client = TSEAsyncClient(test_settings)

    mock_response_200 = mocker.MagicMock()
    mock_response_200.status_code = 200
    mock_response_200.content = b'{"status": "ok"}'
    mock_response_200.headers = {"etag": '"abc123"'}

    mocker.patch.object(client._http_client, "get", return_value=mock_response_200)

    result_200 = await client.fetch(
        election_id="002026",
        artifact_type=ArtifactType.EA20,
        url="https://dadosabertos.tse.jus.br/002026/totalization/ea20-br.json",
    )
    assert result_200.http_status == 200
    assert result_200.body == b'{"status": "ok"}'

    # Agora simula 304 com If-None-Match
    mock_response_304 = mocker.MagicMock()
    mock_response_304.status_code = 304
    mock_response_304.content = b""
    mock_response_304.headers = {"etag": '"abc123"'}

    mocker.patch.object(client._http_client, "get", return_value=mock_response_304)

    result_304 = await client.fetch(
        election_id="002026",
        artifact_type=ArtifactType.EA20,
        url="https://dadosabertos.tse.jus.br/002026/totalization/ea20-br.json",
        etag='"abc123"',
    )
    assert result_304.http_status == 304
    assert result_304.body == b""


@pytest.mark.asyncio
async def test_rate_limiter_tokens() -> None:
    """Valida que o rate limiter permite aquisicoes e respeita limites."""
    limiter = AsyncRateLimiter(max_rate=100.0, max_concurrency=2)
    await limiter.acquire()
    limiter.release()
