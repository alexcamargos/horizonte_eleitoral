"""Testes de integracao do servico de pareamento historico contra cenarios realistas."""

from decimal import Decimal

import pytest

from horizonte_eleitoral.domain.enums import MatchQuality
from horizonte_eleitoral.domain.errors import InvariantViolationError, ReconciliationError
from horizonte_eleitoral.domain.models import ElectionKey, MunicipalityKey, SectionKey
from horizonte_eleitoral.historical.matcher import GeographicMatcher
from horizonte_eleitoral.historical.models import (
    HistoricalLocation,
    HistoricalVoteProfile,
    MatchCandidate,
)
from horizonte_eleitoral.historical.profile_builder import HistoricalProfileBuilder


@pytest.fixture
def sample_historical_dataset() -> tuple[
    list[HistoricalLocation], dict[str, HistoricalVoteProfile]
]:
    """Fixture com conjunto diversificado de locais e votos de 2022."""
    locations = [
        HistoricalLocation(
            location_id="loc_sp_01",
            state="SP",
            municipality_code="71072",
            zone="0001",
            local_code="1001",
            latitude=-23.5505,
            longitude=-46.6333,
            electorate=4000,
        ),
        HistoricalLocation(
            location_id="loc_sp_02",
            state="SP",
            municipality_code="71072",
            zone="0001",
            local_code="1002",
            latitude=-23.5520,
            longitude=-46.6345,
            electorate=3500,
        ),
        HistoricalLocation(
            location_id="loc_mg_01",
            state="MG",
            municipality_code="41238",
            zone="0033",
            local_code="2001",
            latitude=-19.9200,
            longitude=-43.9400,
            electorate=2800,
        ),
    ]

    votes = {
        "loc_sp_01": HistoricalVoteProfile(
            location_id="loc_sp_01",
            valid_votes=3200,
            turnout=3600,
            group_votes=(("PT", 1600), ("PL", 1400), ("OUTROS", 200)),
        ),
        "loc_sp_02": HistoricalVoteProfile(
            location_id="loc_sp_02",
            valid_votes=2800,
            turnout=3100,
            group_votes=(("PT", 1200), ("PL", 1400), ("OUTROS", 200)),
        ),
        "loc_mg_01": HistoricalVoteProfile(
            location_id="loc_mg_01",
            valid_votes=2200,
            turnout=2500,
            group_votes=(("PT", 1100), ("PL", 1000), ("OUTROS", 100)),
        ),
    }

    return locations, votes


def test_batch_matching_across_multiple_sections(
    sample_historical_dataset: tuple[list[HistoricalLocation], dict[str, HistoricalVoteProfile]],
) -> None:
    """Testa o pareamento e construcao de perfis para multiplas secoes de UFs distintas."""
    locations, votes = sample_historical_dataset
    matcher = GeographicMatcher(locations)
    builder = HistoricalProfileBuilder(votes)

    election = ElectionKey("002026", "01", "PRESIDENTE")

    sections_to_test = [
        # Secao 1: Exata em SP
        (
            SectionKey(election, MunicipalityKey("SP", "71072"), "0001", "0001"),
            {"local_code": "1001"},
            MatchQuality.EXACT,
        ),
        # Secao 2: Vizinha em SP
        (
            SectionKey(election, MunicipalityKey("SP", "71072"), "0001", "0002"),
            {"latitude": -23.5510, "longitude": -46.6340},
            MatchQuality.SAME_COMPLEX,
        ),
        # Secao 3: Exata em MG
        (
            SectionKey(election, MunicipalityKey("MG", "41238"), "0033", "0001"),
            {"local_code": "2001"},
            MatchQuality.EXACT,
        ),
        # Secao 4: Sem pareamento (UF presente, municipio desconhecido)
        (
            SectionKey(election, MunicipalityKey("MG", "99999"), "0001", "0001"),
            {},
            MatchQuality.UNMATCHED,
        ),
    ]

    for section, kwargs, expected_quality in sections_to_test:
        candidates = matcher.match(section, **kwargs)
        assert len(candidates) > 0
        profile = builder.build_profile(section, candidates)

        assert profile.primary_method == expected_quality
        shares_dict = dict(profile.shares)
        total_share = sum(shares_dict.values())
        assert total_share == Decimal("1.000000")
        assert all(s >= Decimal(0) for s in shares_dict.values())


def test_profile_builder_raises_on_empty_candidates() -> None:
    """Valida que o builder rejeita lista vazia de candidatas com ReconciliationError."""
    builder = HistoricalProfileBuilder({})
    section = SectionKey(
        ElectionKey("002026", "01", "PRESIDENTE"),
        MunicipalityKey("SP", "71072"),
        "0001",
        "0001",
    )
    with pytest.raises(ReconciliationError, match="nao possui candidatas"):
        builder.build_profile(section, ())


def test_profile_builder_raises_on_invalid_candidate_weights() -> None:
    """Valida que o builder rejeita pesos que nao somam 1.0 com InvariantViolationError."""
    builder = HistoricalProfileBuilder({})
    section = SectionKey(
        ElectionKey("002026", "01", "PRESIDENTE"),
        MunicipalityKey("SP", "71072"),
        "0001",
        "0001",
    )
    invalid_candidate = MatchCandidate(
        candidate_location_id="loc_x",
        method=MatchQuality.EXACT,
        distance_meters=0.0,
        weight=0.5,  # Peso total 0.5 em vez de 1.0
        rank=1,
    )
    with pytest.raises(InvariantViolationError, match="somar 1.0"):
        builder.build_profile(section, (invalid_candidate,))
