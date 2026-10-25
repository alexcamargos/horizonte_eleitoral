"""Testes unitarios para os quatro modelos de referencia (baselines)."""

from collections.abc import Callable

import pytest

from horizonte_eleitoral.models.base import ForecastModel, PendingSection, SectionObservation
from horizonte_eleitoral.models.baselines import (
    HistoricalNoSwingBaseline,
    NationalSwingBaseline,
    RawCountBaseline,
    UFSwingWithShrinkageBaseline,
)
from horizonte_eleitoral.models.swing import SwingEstimator


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


def test_national_swing_baseline_large_delta_no_overflow() -> None:
    """Garante que swings extremos nao provoquem OverflowError em exponenciais."""
    obs = [
        SectionObservation(
            section_id="SP:1:1",
            state="SP",
            municipality_code="71072",
            valid_votes=1000,
            group_votes=(("PT", 999), ("PL", 1), ("OUTROS", 0)),
            historical_shares=(("PT", 0.01), ("PL", 0.98), ("OUTROS", 0.01)),
        )
    ]
    pending = [
        PendingSection(
            section_id="SP:1:2",
            state="SP",
            municipality_code="71072",
            electorate=500,
            historical_shares=(("PT", 0.1), ("PL", 0.8), ("OUTROS", 0.1)),
        )
    ]
    baseline = NationalSwingBaseline()
    result = baseline.predict(observations=obs, pending=pending)
    res_shares = dict(result.projected_shares)
    assert abs(sum(res_shares.values()) - 1.0) < 1e-4
    assert res_shares["PT"] > 0.80


def _self_projection_inputs() -> tuple[list[SectionObservation], list[PendingSection]]:
    """Monta secoes heterogeneas e as mesmas secoes como pendentes com peso exato.

    Returns:
        Tupla (observacoes, pendentes) em que cada pendente espera exatamente os
        votos validos observados da secao correspondente.
    """
    specs = [
        ("SP:1:1", "SP", 1000, ((("PT", 600), ("PL", 300), ("OUTROS", 100))), (0.7, 0.2, 0.1)),
        ("SP:1:2", "SP", 1000, ((("PT", 250), ("PL", 650), ("OUTROS", 100))), (0.2, 0.7, 0.1)),
        ("BA:1:1", "BA", 800, ((("PT", 560), ("PL", 180), ("OUTROS", 60))), (0.6, 0.3, 0.1)),
        ("BA:1:2", "BA", 800, ((("PT", 300), ("PL", 420), ("OUTROS", 80))), (0.3, 0.6, 0.1)),
    ]
    obs: list[SectionObservation] = []
    pending: list[PendingSection] = []
    for sec_id, uf, valid, votes, (h_pt, h_pl, h_out) in specs:
        hist = (("PT", h_pt), ("PL", h_pl), ("OUTROS", h_out))
        obs.append(
            SectionObservation(
                section_id=sec_id,
                state=uf,
                municipality_code="00001",
                valid_votes=valid,
                group_votes=votes,
                historical_shares=hist,
            )
        )
        pending.append(
            PendingSection(
                section_id=f"{sec_id}:espelho",
                state=uf,
                municipality_code="00001",
                electorate=valid,
                historical_shares=hist,
                expected_turnout_rate=1.0,
                expected_valid_rate=1.0,
            )
        )
    return obs, pending


@pytest.mark.parametrize(
    "model_factory",
    [
        lambda est: NationalSwingBaseline(pseudo_count=0.0, swing_estimator=est),
        lambda est: UFSwingWithShrinkageBaseline(
            pseudo_count=0.0, shrinkage_k=0.0, swing_estimator=est
        ),
    ],
    ids=["baseline_3", "baseline_4"],
)
def test_calibrated_swing_reproduces_observed_in_self_projection(
    model_factory: Callable[[SwingEstimator], ForecastModel],
) -> None:
    """Projetar as proprias secoes apuradas deve reproduzir o apurado (sem vies de Jensen).

    Args:
        model_factory: Fabrica do baseline parametrizada pelo estimador de swing.
    """
    obs, pending = _self_projection_inputs()

    calibrated = model_factory(SwingEstimator.CALIBRATED).predict(observations=obs, pending=pending)
    observed = dict(calibrated.observed_shares)
    projected = dict(calibrated.projected_shares)
    for group in ("PT", "PL", "OUTROS"):
        assert projected[group] == pytest.approx(observed[group], abs=2e-6)

    legacy = model_factory(SwingEstimator.AGGREGATE).predict(observations=obs, pending=pending)
    legacy_projected = dict(legacy.projected_shares)
    assert max(abs(legacy_projected[g] - observed[g]) for g in observed) > 1e-4


@pytest.mark.parametrize(
    "model",
    [
        NationalSwingBaseline(),
        UFSwingWithShrinkageBaseline(),
    ],
    ids=["baseline_3", "baseline_4"],
)
def test_zero_historical_share_not_locked_out(model: ForecastModel) -> None:
    """Valida que grupo com share historico zero na secao pendente nao sofre zero-lockout."""
    obs = [
        SectionObservation(
            section_id="SP:1:1",
            state="SP",
            municipality_code="71072",
            valid_votes=1000,
            group_votes=(("PT", 500), ("PL", 400), ("OUTROS", 100)),
            historical_shares=(("PT", 0.45), ("PL", 0.45), ("OUTROS", 0.10)),
        )
    ]
    pending = [
        PendingSection(
            section_id="SP:1:2",
            state="SP",
            municipality_code="71072",
            electorate=200_000,
            historical_shares=(("PT", 0.5), ("PL", 0.5), ("OUTROS", 0.0)),
        )
    ]
    result = model.predict(observations=obs, pending=pending)
    proj_votes = dict(result.projected_votes)
    # OUTROS observou 100 votos; com o piso 1e-5 na secao pendente, projeta votos > 100
    assert proj_votes["OUTROS"] > 100
    proj_shares = dict(result.projected_shares)
    assert proj_shares["OUTROS"] > 0.0
