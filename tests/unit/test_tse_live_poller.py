"""Testes unitarios para o servico de polling oficial do TSE e controle de janela horaria."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from horizonte_eleitoral.config import Environment, Settings
from horizonte_eleitoral.domain.enums import ArtifactType
from horizonte_eleitoral.domain.models import RawArtifactRequest
from horizonte_eleitoral.ingestion.client import TSEAsyncClient
from horizonte_eleitoral.ingestion.discovery import TSEPathResolver
from horizonte_eleitoral.ingestion.tse_live_poller import (
    TSELivePoller,
    is_election_night_window,
)


@pytest.fixture
def mock_settings() -> Settings:
    """Configuracao de teste isolada para o poller."""
    return Settings(
        environment=Environment.TEST,
        data_directory=Path("test_data"),
        database_dsn=None,
        allowed_tse_hosts=("dadosabertos.tse.jus.br", "resultados.tse.jus.br"),
        max_requests_per_second=50,
        max_concurrency=5,
    )


def test_is_election_night_window_schedule_gate() -> None:
    """Valida a regra de restricao temporal: domingos a partir das 17h no horario de Brasilia."""
    # Domingo 17:00 em Brasilia (UTC-3 -> 20:00 UTC)
    domingo_17h = datetime(2026, 10, 4, 20, 0, tzinfo=UTC)
    assert is_election_night_window(domingo_17h, ignore_gate=False) is True

    # Domingo 16:59 em Brasilia (UTC-3 -> 19:59 UTC)
    domingo_16h59 = datetime(2026, 10, 4, 19, 59, tzinfo=UTC)
    assert is_election_night_window(domingo_16h59, ignore_gate=False) is False

    # Sabado 18:00 em Brasilia (dia incorreto)
    sabado_18h = datetime(2026, 10, 3, 21, 0, tzinfo=UTC)
    assert is_election_night_window(sabado_18h, ignore_gate=False) is False

    # Sabado com ignore_gate=True deve liberar para testes
    assert is_election_night_window(sabado_18h, ignore_gate=True) is True


@pytest.mark.asyncio
async def test_poller_blocks_when_outside_schedule_window(
    mock_settings: Settings,
) -> None:
    """Valida que o poller nao faz requisicao HTTP se estiver fora da janela das 17h."""
    client = TSEAsyncClient(mock_settings)
    resolver = TSEPathResolver("https://resultados.tse.jus.br", "002026")
    poller = TSELivePoller(client, resolver, ignore_schedule_gate=False)

    sabado = datetime(2026, 10, 3, 15, 0, tzinfo=UTC)
    has_new, tot, msg = await poller.check_for_updates(now=sabado)

    assert has_new is False
    assert tot is None
    assert "Aguardando início da apuração oficial" in msg
    assert len(poller.history_log) == 1
    assert poller.history_log[0].http_status == 0


@pytest.mark.asyncio
async def test_poller_handles_http_304_and_404(
    mock_settings: Settings,
    mocker: MockerFixture,
) -> None:
    """Valida o tratamento gracioso de HTTP 304 (sem mudancas) e 404 (arquivo ausente)."""
    client = TSEAsyncClient(mock_settings)
    resolver = TSEPathResolver("https://resultados.tse.jus.br", "002026")
    poller = TSELivePoller(client, resolver, ignore_schedule_gate=True)

    # 1. Simula HTTP 304
    mock_resp_304 = RawArtifactRequest(
        election_id="002026",
        artifact_type=ArtifactType.EA20,
        source_url=resolver.url_for_totalization(),
        collected_at=datetime.now(UTC),
        http_status=304,
        body=b"",
        headers=(("etag", '"tag-1"'),),
    )
    mocker.patch.object(client, "fetch", return_value=mock_resp_304)

    has_new, tot, msg = await poller.check_for_updates()
    assert has_new is False
    assert tot is None
    assert "HTTP 304" in msg

    # 2. Simula HTTP 404
    mock_resp_404 = RawArtifactRequest(
        election_id="002026",
        artifact_type=ArtifactType.EA20,
        source_url=resolver.url_for_totalization(),
        collected_at=datetime.now(UTC),
        http_status=404,
        body=b"",
        headers=(),
    )
    mocker.patch.object(client, "fetch", return_value=mock_resp_404)

    has_new, tot, msg = await poller.check_for_updates()
    assert has_new is False
    assert tot is None
    assert "HTTP 404" in msg


@pytest.mark.asyncio
async def test_poller_detects_new_data_and_updates_state(
    mock_settings: Settings,
    mocker: MockerFixture,
) -> None:
    """Valida a deteccao de avanco no percentual apurado e atualizacao do estado do poller."""
    client = TSEAsyncClient(mock_settings)
    resolver = TSEPathResolver("https://resultados.tse.jus.br", "002026")
    poller = TSELivePoller(client, resolver, round_num=2, ignore_schedule_gate=True)

    # Primeira onda: 20% do eleitorado
    body_wave_1 = (
        b'{"abrangencia":"BR","e":100000,"ea":20000,"vv":15000,'
        b'"cand":[{"n":"13","vap":7800},{"n":"22","vap":7200}]}'
    )
    mock_resp_w1 = RawArtifactRequest(
        election_id="002026",
        artifact_type=ArtifactType.EA20,
        source_url=resolver.url_for_totalization(),
        collected_at=datetime.now(UTC),
        http_status=200,
        body=body_wave_1,
        headers=(("etag", '"etag-w1"'),),
    )
    mocker.patch.object(client, "fetch", return_value=mock_resp_w1)

    has_new, tot1, msg1 = await poller.check_for_updates()
    assert has_new is True
    assert tot1 is not None
    assert poller.last_totalized_pct == 20.0
    assert "20.00%" in msg1
    assert poller._last_etag == '"etag-w1"'

    # Segunda onda idêntica: nao deve sinalizar novos dados
    has_new_repeat, tot_rep, msg_rep = await poller.check_for_updates()
    assert has_new_repeat is False
    assert "inalterados" in msg_rep

    # Terceira onda: 45% do eleitorado
    body_wave_2 = (
        b'{"abrangencia":"BR","e":100000,"ea":45000,"vv":35000,'
        b'"cand":[{"n":"13","vap":18000},{"n":"22","vap":17000}]}'
    )
    mock_resp_w2 = RawArtifactRequest(
        election_id="002026",
        artifact_type=ArtifactType.EA20,
        source_url=resolver.url_for_totalization(),
        collected_at=datetime.now(UTC),
        http_status=200,
        body=body_wave_2,
        headers=(("etag", '"etag-w2"'),),
    )
    mocker.patch.object(client, "fetch", return_value=mock_resp_w2)

    has_new_w2, tot2, msg2 = await poller.check_for_updates()
    assert has_new_w2 is True
    assert tot2 is not None
    assert poller.last_totalized_pct == 45.0
    assert "45.00%" in msg2


@pytest.mark.asyncio
async def test_poller_run_cycle_computes_projection_on_new_data(
    mock_settings: Settings,
    mocker: MockerFixture,
) -> None:
    """Valida que o run_poller_cycle dispara o modelo preditivo de 2º turno quando ha novidade."""
    client = TSEAsyncClient(mock_settings)
    resolver = TSEPathResolver("https://resultados.tse.jus.br", "002026")
    poller = TSELivePoller(client, resolver, round_num=2, ignore_schedule_gate=True)

    body = (
        b'{"abrangencia":"BR","e":100000,"ea":30000,"vv":24000,'
        b'"cand":[{"n":"13","vap":12500},{"n":"22","vap":11500}]}'
    )
    mock_resp = RawArtifactRequest(
        election_id="002026",
        artifact_type=ArtifactType.EA20,
        source_url=resolver.url_for_totalization(),
        collected_at=datetime.now(UTC),
        http_status=200,
        body=body,
        headers=(("etag", '"tag-cycle"'),),
    )
    mocker.patch.object(client, "fetch", return_value=mock_resp)

    cycle_result = await poller.run_poller_cycle(num_draws=50, seed=42)

    assert cycle_result["has_new_data"] is True
    assert cycle_result["projection"] is not None

    proj = cycle_result["projection"]
    group_codes = {g.code for g in proj.groups}
    assert group_codes == {"PL", "PT"}
    assert poller.last_published_payload == proj
