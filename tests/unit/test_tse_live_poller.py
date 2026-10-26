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


@pytest.mark.asyncio
async def test_poller_uses_divulgacao_and_custom_target_url(
    mock_settings: Settings,
    mocker: MockerFixture,
) -> None:
    """Valida selecao de url de divulgacao e de target_url customizado."""
    client = TSEAsyncClient(mock_settings)
    resolver = TSEPathResolver("https://resultados.tse.jus.br", "6258")

    # Poller com endpoint_type='divulgacao'
    poller_div = TSELivePoller(
        client,
        resolver,
        election_id="6258",
        endpoint_type="divulgacao",
        ignore_schedule_gate=True,
    )
    assert poller_div.get_target_url() == (
        "https://resultados.tse.jus.br/oficial/ele2026/6258/dados/br/br-c0001-e006258-u.json"
    )

    # Poller com target_url explicitamente customizado
    custom_url = "https://resultados.tse.jus.br/custom/rota/teste.json"
    poller_custom = TSELivePoller(
        client,
        resolver,
        election_id="6258",
        target_url=custom_url,
        ignore_schedule_gate=True,
    )
    assert poller_custom.get_target_url() == custom_url


@pytest.mark.asyncio
async def test_poller_handles_zero_votes_as_waiting_status(
    mock_settings: Settings,
    mocker: MockerFixture,
) -> None:
    """Valida que resposta 200 com 0% e 0 votos mantem status de prontidao sem recalcular."""
    client = TSEAsyncClient(mock_settings)
    resolver = TSEPathResolver("https://resultados.tse.jus.br", "6258")
    poller = TSELivePoller(
        client,
        resolver,
        election_id="6258",
        endpoint_type="divulgacao",
        ignore_schedule_gate=True,
    )

    body_zero = (
        b'{"ele":"6258","t":"2","tpabr":"br","cdabr":"br",'
        b'"s":{"ts":"499248","st":"0"},"e":{"te":"158745502","est":"0"},'
        b'"v":{"vv":"0","vb":"0","vn":"0"},"carg":[{"agr":[{"par":[{"cand":'
        b'[{"n":"13","vap":"0"},{"n":"22","vap":"0"}]}]}]}]}'
    )
    mock_resp = RawArtifactRequest(
        election_id="6258",
        artifact_type=ArtifactType.EA20,
        source_url=poller.get_target_url(),
        collected_at=datetime.now(UTC),
        http_status=200,
        body=body_zero,
        headers=(),
    )
    mocker.patch.object(client, "fetch", return_value=mock_resp)

    has_new, tot, msg = await poller.check_for_updates()
    assert has_new is False
    assert tot is not None
    assert tot.total_sections == 499248
    assert "Aguardando início da contagem" in msg
    assert poller.history_log[-1].totalized_electorate_pct == 0.0


@pytest.mark.asyncio
async def test_poller_fetches_state_totalizations_with_etag_cache_and_404_resilience(
    mock_settings: Settings,
    mocker: MockerFixture,
) -> None:
    """Valida coleta concorrente por UF com suporte a cache ETag 304 e resiliencia a 404.

    Args:
        mock_settings: Configuracao de teste isolada.
        mocker: Fixture pytest-mock para interceptar o cliente HTTP.

    Returns:
        None.

    Raises:
        AssertionError: Se UFs validas nao forem parseadas ou o cache 304 falhar.
    """
    client = TSEAsyncClient(mock_settings)
    resolver = TSEPathResolver("https://resultados.tse.jus.br", "6258")
    poller = TSELivePoller(
        client,
        resolver,
        election_id="6258",
        endpoint_type="divulgacao",
        ignore_schedule_gate=True,
    )

    sp_body = (
        b'{"ele":"6258","t":"2","tpabr":"uf","cdabr":"sp",'
        b'"s":{"ts":"105000","st":"90000"},"e":{"te":"34000000","est":"29000000"},'
        b'"v":{"vv":"23000000","vb":"500000","vn":"800000"},"carg":[{"agr":[{"par":[{"cand":'
        b'[{"n":"13","vap":"10350000"},{"n":"22","vap":"12650000"}]}]}]}]}'
    )
    ba_body = (
        b'{"ele":"6258","t":"2","tpabr":"uf","cdabr":"ba",'
        b'"s":{"ts":"35000","st":"25000"},"e":{"te":"11200000","est":"8000000"},'
        b'"v":{"vv":"6400000","vb":"100000","vn":"200000"},"carg":[{"agr":[{"par":[{"cand":'
        b'[{"n":"13","vap":"4480000"},{"n":"22","vap":"1920000"}]}]}]}]}'
    )

    observed_etags: dict[str, str | None] = {}

    async def _fake_fetch(
        *,
        election_id: str,
        artifact_type: ArtifactType,
        url: str,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> RawArtifactRequest:
        observed_etags[url] = etag
        if "/sp/" in url:
            if etag == '"etag-sp-1"':
                return RawArtifactRequest(
                    election_id=election_id,
                    artifact_type=artifact_type,
                    source_url=url,
                    collected_at=datetime.now(UTC),
                    http_status=304,
                    body=b"",
                    headers=(("etag", '"etag-sp-1"'),),
                )
            return RawArtifactRequest(
                election_id=election_id,
                artifact_type=artifact_type,
                source_url=url,
                collected_at=datetime.now(UTC),
                http_status=200,
                body=sp_body,
                headers=(("etag", '"etag-sp-1"'),),
            )
        if "/ba/" in url:
            return RawArtifactRequest(
                election_id=election_id,
                artifact_type=artifact_type,
                source_url=url,
                collected_at=datetime.now(UTC),
                http_status=200,
                body=ba_body,
                headers=(("etag", '"etag-ba-1"'),),
            )
        return RawArtifactRequest(
            election_id=election_id,
            artifact_type=artifact_type,
            source_url=url,
            collected_at=datetime.now(UTC),
            http_status=404,
            body=b"",
            headers=(),
        )

    mocker.patch.object(client, "fetch", side_effect=_fake_fetch)

    res1 = await poller.fetch_state_totalizations(states=("SP", "BA", "ZZ"))
    assert set(res1.keys()) == {"SP", "BA"}
    assert res1["SP"].scope_code == "SP"
    assert dict(res1["BA"].candidate_group_votes)["PT"] == 4480000

    res2 = await poller.fetch_state_totalizations(states=("SP", "BA", "ZZ"))
    assert set(res2.keys()) == {"SP", "BA"}
    sp_url = poller.get_state_target_url("SP")
    assert observed_etags[sp_url] == '"etag-sp-1"'


@pytest.mark.asyncio
async def test_poller_run_cycle_conditions_projection_on_live_2t_votes(
    mock_settings: Settings,
    mocker: MockerFixture,
) -> None:
    """Valida que run_poller_cycle altera a projecao conforme os votos reais do 2T mudam.

    Args:
        mock_settings: Configuracao de teste isolada.
        mocker: Fixture pytest-mock para interceptar o cliente HTTP.

    Returns:
        None.

    Raises:
        AssertionError: Se a projecao ignorar a mudanca nos votos reais retornados pelo TSE.
    """
    client = TSEAsyncClient(mock_settings)
    resolver = TSEPathResolver("https://resultados.tse.jus.br", "6258")
    poller = TSELivePoller(
        client,
        resolver,
        election_id="6258",
        round_num=2,
        ignore_schedule_gate=True,
    )

    # Cenario A: 75% apurado com PL liderando folgado (55% vs 45%)
    body_pl_lead = (
        b'{"abrangencia":"BR","sec_tot":100,"sec_apu":75,"e":100000,"ea":75000,"vv":60000,'
        b'"cand":[{"n":"13","vap":27000},{"n":"22","vap":33000}]}'
    )
    resp_a = RawArtifactRequest(
        election_id="6258",
        artifact_type=ArtifactType.EA20,
        source_url=poller.get_target_url(),
        collected_at=datetime.now(UTC),
        http_status=200,
        body=body_pl_lead,
        headers=(("etag", '"tag-a"'),),
    )
    mocker.patch.object(client, "fetch", return_value=resp_a)
    res_a = await poller.run_poller_cycle(num_draws=100, seed=42)
    groups_a = {g.code: g for g in res_a["projection"].groups}
    assert groups_a["PL"].projected_share > groups_a["PT"].projected_share

    # Cenario B: 82% apurado com PT virando e abrindo 52,5% vs 47,5%
    body_pt_lead = (
        b'{"abrangencia":"BR","sec_tot":100,"sec_apu":82,"e":100000,"ea":82000,"vv":66000,'
        b'"cand":[{"n":"13","vap":34650},{"n":"22","vap":31350}]}'
    )
    resp_b = RawArtifactRequest(
        election_id="6258",
        artifact_type=ArtifactType.EA20,
        source_url=poller.get_target_url(),
        collected_at=datetime.now(UTC),
        http_status=200,
        body=body_pt_lead,
        headers=(("etag", '"tag-b"'),),
    )
    mocker.patch.object(client, "fetch", return_value=resp_b)
    res_b = await poller.run_poller_cycle(num_draws=100, seed=42)
    groups_b = {g.code: g for g in res_b["projection"].groups}
    assert groups_b["PT"].projected_share > 51.5
    assert groups_b["PT"].projected_share > groups_b["PL"].projected_share
    assert groups_b["PT"].win_probability > 0.90
