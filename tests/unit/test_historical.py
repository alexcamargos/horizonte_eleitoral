"""Testes unitarios para pareamento geografico e construcao de perfis historicos."""

from decimal import Decimal

from horizonte_eleitoral.domain.enums import MatchQuality
from horizonte_eleitoral.domain.models import ElectionKey, MunicipalityKey, SectionKey
from horizonte_eleitoral.historical.matcher import GeographicMatcher, haversine_distance
from horizonte_eleitoral.historical.models import HistoricalLocation, HistoricalVoteProfile
from horizonte_eleitoral.historical.profile_builder import HistoricalProfileBuilder


def test_haversine_distance_known_points() -> None:
    """Valida calculo de distancia geocentrica entre pontos conhecidos em Sao Paulo."""
    # Praca da Se (-23.5505, -46.6333) e Av Paulista (-23.5615, -46.6559) ~ 2.6 km
    dist = haversine_distance(-23.5505, -46.6333, -23.5615, -46.6559)
    assert 2500 < dist < 2800


def test_matcher_exact_match() -> None:
    """Pareamento exato quando codigo do local, zona e municipio coincidem."""
    loc = HistoricalLocation(
        location_id="loc_1001",
        state="SP",
        municipality_code="71072",
        zone="0001",
        local_code="1001",
        latitude=-23.55,
        longitude=-46.63,
        electorate=1000,
    )
    matcher = GeographicMatcher([loc])

    section = SectionKey(
        election=ElectionKey("002026", "01", "PRESIDENTE"),
        municipality=MunicipalityKey("SP", "71072"),
        zone="0001",
        section="0010",
    )

    candidates = matcher.match(section, local_code="1001")
    assert len(candidates) == 1
    assert candidates[0].candidate_location_id == "loc_1001"
    assert candidates[0].method == MatchQuality.EXACT
    assert candidates[0].weight == 1.0


def test_matcher_same_complex_within_100m() -> None:
    """Pareamento no mesmo complexo quando a distancia e inferior a 100m."""
    loc = HistoricalLocation(
        location_id="loc_complex",
        state="SP",
        municipality_code="71072",
        zone="0001",
        local_code="1002",
        latitude=-23.5500,
        longitude=-46.6300,
    )
    matcher = GeographicMatcher([loc])

    section = SectionKey(
        election=ElectionKey("002026", "01", "PRESIDENTE"),
        municipality=MunicipalityKey("SP", "71072"),
        zone="0001",
        section="0011",
    )

    # Coordenada a ~50 metros
    candidates = matcher.match(
        section,
        local_code="9999",  # local_code diferente
        latitude=-23.5504,
        longitude=-46.6300,
    )
    assert len(candidates) == 1
    assert candidates[0].method == MatchQuality.SAME_COMPLEX
    assert candidates[0].distance_meters is not None
    assert candidates[0].distance_meters <= 100.0


def test_matcher_neighboring_within_municipality() -> None:
    """Pareamento por vizinhos proximos no mesmo municipio."""
    loc1 = HistoricalLocation(
        location_id="loc_n1",
        state="SP",
        municipality_code="71072",
        zone="0001",
        local_code="1001",
        latitude=-23.5500,
        longitude=-46.6300,
    )
    loc2 = HistoricalLocation(
        location_id="loc_n2",
        state="SP",
        municipality_code="71072",
        zone="0001",
        local_code="1002",
        latitude=-23.5550,
        longitude=-46.6350,
    )
    matcher = GeographicMatcher([loc1, loc2])

    section = SectionKey(
        election=ElectionKey("002026", "01", "PRESIDENTE"),
        municipality=MunicipalityKey("SP", "71072"),
        zone="0001",
        section="0012",
    )

    candidates = matcher.match(
        section,
        latitude=-23.5520,
        longitude=-46.6320,
    )
    assert len(candidates) == 2
    assert all(c.method == MatchQuality.NEIGHBORING for c in candidates)
    total_w = sum(c.weight for c in candidates)
    assert abs(total_w - 1.0) < 1e-5


def test_matcher_same_zone_fallback() -> None:
    """Fallback para mesma zona eleitoral quando nao ha coordenadas."""
    loc1 = HistoricalLocation(
        location_id="loc_z1",
        state="SP",
        municipality_code="71072",
        zone="0001",
        local_code="1001",
    )
    loc2 = HistoricalLocation(
        location_id="loc_z2",
        state="SP",
        municipality_code="71072",
        zone="0001",
        local_code="1002",
    )
    matcher = GeographicMatcher([loc1, loc2])

    section = SectionKey(
        election=ElectionKey("002026", "01", "PRESIDENTE"),
        municipality=MunicipalityKey("SP", "71072"),
        zone="0001",
        section="0013",
    )

    candidates = matcher.match(section)
    assert len(candidates) == 2
    assert all(c.method == MatchQuality.SAME_ZONE for c in candidates)


def test_matcher_unmatched_fallback() -> None:
    """Fallback estadual e classificacao UNMATCHED quando municipio nao tem dados."""
    loc_rj = HistoricalLocation(
        location_id="loc_rj",
        state="RJ",
        municipality_code="60011",
        zone="0001",
        local_code="1001",
    )
    matcher = GeographicMatcher([loc_rj])

    section = SectionKey(
        election=ElectionKey("002026", "01", "PRESIDENTE"),
        municipality=MunicipalityKey("RJ", "99999"),  # Municipio desconhecido
        zone="0001",
        section="0001",
    )

    candidates = matcher.match(section)
    assert len(candidates) == 1
    assert candidates[0].method == MatchQuality.UNMATCHED


def test_profile_builder_shares_sum_to_one_and_no_vote_duplication() -> None:
    """Shares somam 1.0 e multiplas secoes associadas ao mesmo local nao duplicam votos."""
    votes = {
        "loc_1": HistoricalVoteProfile(
            location_id="loc_1",
            valid_votes=500,
            turnout=600,
            group_votes=(("PT", 250), ("PL", 200), ("OUTROS", 50)),
        )
    }
    builder = HistoricalProfileBuilder(votes)

    section1 = SectionKey(
        election=ElectionKey("002026", "01", "PRESIDENTE"),
        municipality=MunicipalityKey("SP", "71072"),
        zone="0001",
        section="0001",
    )
    section2 = SectionKey(
        election=ElectionKey("002026", "01", "PRESIDENTE"),
        municipality=MunicipalityKey("SP", "71072"),
        zone="0001",
        section="0002",
    )

    # Duas secoes de 2026 pareadas ao mesmo local de 2022
    candidates = (matcher_candidate_helper("loc_1", MatchQuality.EXACT, 1.0),)

    profile1 = builder.build_profile(section1, candidates)
    profile2 = builder.build_profile(section2, candidates)

    # Ambos os perfis tem shares somando 1.0
    sum1 = sum(share for _, share in profile1.shares)
    sum2 = sum(share for _, share in profile2.shares)
    assert sum1 == Decimal("1.000000")
    assert sum2 == Decimal("1.000000")

    shares1_dict = dict(profile1.shares)
    assert shares1_dict["PT"] == Decimal("0.500000")
    assert shares1_dict["PL"] == Decimal("0.400000")
    assert shares1_dict["OUTROS"] == Decimal("0.100000")

    # A associacao e em proporcoes, nao votos absolutos
    assert profile1.quality_score == 1.0
    assert profile1.match_entropy == 0.0


def test_profile_builder_zero_share_first_group_negative_diff() -> None:
    """Valida que o primeiro grupo com share zero nao recebe residuo negativo.

    Evita que o arredondamento decimal gere shares negativos (-0.000001),
    violando a invariante de SectionHistoricalProfile.

    Returns:
        None.

    Raises:
        None.
    """
    votes = {
        "loc_1": HistoricalVoteProfile(
            location_id="loc_1",
            valid_votes=3,
            turnout=3,
            group_votes=(("OUTROS", 0), ("PL", 1), ("PT", 2)),
        )
    }
    builder = HistoricalProfileBuilder(votes, configured_groups=("OUTROS", "PL", "PT"))
    section = SectionKey(
        election=ElectionKey("002026", "01", "PRESIDENTE"),
        municipality=MunicipalityKey("SP", "71072"),
        zone="0001",
        section="0001",
    )
    candidates = (matcher_candidate_helper("loc_1", MatchQuality.EXACT, 1.0),)
    profile = builder.build_profile(section, candidates)  # type: ignore[arg-type]

    shares_dict = dict(profile.shares)
    assert shares_dict["OUTROS"] == Decimal("0.000000")
    assert shares_dict["PL"] >= Decimal("0.000000")
    assert shares_dict["PT"] >= Decimal("0.000000")
    assert sum(shares_dict.values()) == Decimal("1.000000")


def matcher_candidate_helper(loc_id: str, method: MatchQuality, weight: float) -> object:
    from horizonte_eleitoral.historical.models import MatchCandidate

    return MatchCandidate(
        candidate_location_id=loc_id,
        method=method,
        distance_meters=0.0,
        weight=weight,
        rank=1,
    )
