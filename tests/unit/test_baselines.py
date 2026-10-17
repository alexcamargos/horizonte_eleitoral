"""Testes unitarios para os quatro modelos de referencia (baselines)."""

from horizonte_eleitoral.models.base import PendingSection, SectionObservation
from horizonte_eleitoral.models.baselines import (
    HistoricalNoSwingBaseline,
    NationalSwingBaseline,
    RawCountBaseline,
    UFSwingWithShrinkageBaseline,
)


def test_raw_count_baseline() -> None:
    """Valida que o RawCountBaseline retorna as participacoes observadas."""
    obs = [
        SectionObservation(
            section_id="SP:1:1",
            state="SP",
            municipality_code="71072",
            valid_votes=100,
            group_votes=(("PT", 60), ("PL", 30), ("OUTROS", 10)),
            historical_shares=(("PT", 0.5), ("PL", 0.4), ("OUTROS", 0.1)),
        )
    ]
    baseline = RawCountBaseline()
    result = baseline.predict(observations=obs, pending=[])

    shares = dict(result.projected_shares)
    assert shares["PT"] == 0.60
    assert shares["PL"] == 0.30
    assert shares["OUTROS"] == 0.10
    assert abs(sum(shares.values()) - 1.0) < 1e-4


def test_historical_no_swing_baseline() -> None:
    """Valida que o HistoricalNoSwing projeta secoes pendentes pela base pura."""
    obs = [
        SectionObservation(
            section_id="SP:1:1",
            state="SP",
            municipality_code="71072",
            valid_votes=100,
            group_votes=(("PT", 60), ("PL", 40), ("OUTROS", 0)),
            historical_shares=(("PT", 0.5), ("PL", 0.5), ("OUTROS", 0.0)),
        )
    ]
    # Secao pendente com eleitorado 200 -> ~152 validos esperados (200 * 0.8 * 0.95 = 152)
    # Historico dela: 80% PL, 20% PT
    pending = [
        PendingSection(
            section_id="SP:1:2",
            state="SP",
            municipality_code="71072",
            electorate=200,
            historical_shares=(("PT", 0.2), ("PL", 0.8), ("OUTROS", 0.0)),
        )
    ]

    baseline = HistoricalNoSwingBaseline()
    result = baseline.predict(observations=obs, pending=pending)

    shares = dict(result.projected_shares)
    assert abs(sum(shares.values()) - 1.0) < 1e-4
    # Como a secao pendente e fortemente PL (80%), o share projetado de PL deve subir
    assert shares["PL"] > 0.40


def test_national_swing_baseline() -> None:
    """Valida estimativa de swing nacional e ajuste das secoes pendentes."""
    obs = [
        SectionObservation(
            section_id="SP:1:1",
            state="SP",
            municipality_code="71072",
            valid_votes=1000,
            # Crescimento do PT em relacao ao historico (era 40%, agora 60%)
            group_votes=(("PT", 600), ("PL", 300), ("OUTROS", 100)),
            historical_shares=(("PT", 0.4), ("PL", 0.5), ("OUTROS", 0.1)),
        )
    ]
    # Secao pendente que no historico tinha PT=0.30, PL=0.60, OUTROS=0.10
    pending = [
        PendingSection(
            section_id="MG:1:1",
            state="MG",
            municipality_code="41238",
            electorate=1000,
            historical_shares=(("PT", 0.3), ("PL", 0.6), ("OUTROS", 0.1)),
        )
    ]

    baseline = NationalSwingBaseline()
    result = baseline.predict(observations=obs, pending=pending)

    shares = dict(result.projected_shares)
    assert abs(sum(shares.values()) - 1.0) < 1e-4
    # O swing nacional positivo para o PT eleva a projecao acima do historico puro (30%)
    assert shares["PT"] > 0.35


def test_uf_swing_with_shrinkage() -> None:
    """Valida calculo de swing estadual com encolhimento para o nacional."""
    obs = [
        SectionObservation(
            section_id="SP:1:1",
            state="SP",
            municipality_code="71072",
            valid_votes=500,
            group_votes=(("PT", 300), ("PL", 150), ("OUTROS", 50)),
            historical_shares=(("PT", 0.5), ("PL", 0.4), ("OUTROS", 0.1)),
        ),
        SectionObservation(
            section_id="RJ:1:1",
            state="RJ",
            municipality_code="60011",
            valid_votes=500,
            group_votes=(("PT", 150), ("PL", 300), ("OUTROS", 50)),
            historical_shares=(("PT", 0.4), ("PL", 0.5), ("OUTROS", 0.1)),
        ),
    ]
    pending = [
        PendingSection(
            section_id="SP:1:2",
            state="SP",
            municipality_code="71072",
            electorate=500,
            historical_shares=(("PT", 0.5), ("PL", 0.4), ("OUTROS", 0.1)),
        )
    ]

    baseline = UFSwingWithShrinkageBaseline(shrinkage_k=10.0)
    result = baseline.predict(observations=obs, pending=pending)

    shares = dict(result.projected_shares)
    assert abs(sum(shares.values()) - 1.0) < 1e-4
