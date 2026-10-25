"""Testes unitarios dos estimadores de swing composicional em log-ratio."""

from __future__ import annotations

import math

import pytest

from horizonte_eleitoral.domain.errors import InvariantViolationError, ValidationError
from horizonte_eleitoral.models.swing import (
    SwingEstimator,
    aggregate_logratio_swing,
    calibrated_logratio_swing,
    estimate_logratio_swing,
)

# Secoes heterogeneas: uma fortemente PT, outra fortemente PL (ordem PT, PL, OUTROS).
HETERO_VALID = [1000.0, 1000.0]
HETERO_HIST = [[0.70, 0.20, 0.10], [0.20, 0.70, 0.10]]
HETERO_TOTALS = [850.0, 950.0, 200.0]


def _apply(delta: tuple[float, ...], hist: list[list[float]], valid: list[float]) -> list[float]:
    """Aplica o swing secao a secao via softmax e devolve os totais reconstruidos.

    Args:
        delta: Swing por grupo.
        hist: Shares historicos por secao.
        valid: Votos validos por secao.

    Returns:
        Totais reconstruidos por grupo.
    """
    totals = [0.0 for _ in delta]
    for v, row in zip(valid, hist, strict=True):
        unnorm = [h * math.exp(d) for h, d in zip(row, delta, strict=True)]
        denom = sum(unnorm)
        for k, u in enumerate(unnorm):
            totals[k] += v * u / denom
    return totals


def test_calibrated_reproduces_observed_totals_without_pseudo_count() -> None:
    """Com pseudo_count=0, o swing calibrado reconstroi exatamente os totais observados."""
    delta = calibrated_logratio_swing(
        HETERO_VALID, HETERO_HIST, HETERO_TOTALS, reference_index=2, pseudo_count=0.0
    )
    rebuilt = _apply(delta, HETERO_HIST, HETERO_VALID)
    for got, expected in zip(rebuilt, HETERO_TOTALS, strict=True):
        assert got == pytest.approx(expected, abs=1e-6)


def test_aggregate_estimator_is_biased_with_heterogeneous_history() -> None:
    """O estimador agregado legado nao reconstroi os totais quando as bases divergem."""
    delta = aggregate_logratio_swing(
        HETERO_VALID, HETERO_HIST, HETERO_TOTALS, reference_index=2, pseudo_count=0.0
    )
    rebuilt = _apply(delta, HETERO_HIST, HETERO_VALID)
    max_error = max(abs(g - e) for g, e in zip(rebuilt, HETERO_TOTALS, strict=True))
    assert max_error > 1.0


def test_estimators_coincide_with_homogeneous_history() -> None:
    """Com bases historicas identicas, a softmax e linear no agregado e os estimadores coincidem."""
    hist = [[0.5, 0.4, 0.1], [0.5, 0.4, 0.1], [0.5, 0.4, 0.1]]
    valid = [300.0, 500.0, 200.0]
    totals = [550.0, 380.0, 70.0]
    calibrated = calibrated_logratio_swing(valid, hist, totals, reference_index=2, pseudo_count=0.0)
    aggregate = aggregate_logratio_swing(valid, hist, totals, reference_index=2, pseudo_count=0.0)
    assert calibrated == pytest.approx(aggregate, abs=1e-9)


def test_reference_group_delta_is_zero() -> None:
    """O grupo de referencia sempre recebe delta zero."""
    delta = calibrated_logratio_swing(
        HETERO_VALID, HETERO_HIST, HETERO_TOTALS, reference_index=2, pseudo_count=10.0
    )
    assert delta[2] == 0.0


def test_pseudo_count_keeps_zero_vote_group_finite() -> None:
    """Grupo sem votos observados produz swing finito quando ha pseudo-contagem."""
    delta = calibrated_logratio_swing(
        [100.0], [[0.5, 0.4, 0.1]], [60.0, 40.0, 0.0], reference_index=0, pseudo_count=10.0
    )
    assert all(math.isfinite(d) for d in delta)
    assert delta[2] < 0.0


def test_zero_vote_group_without_pseudo_count_raises() -> None:
    """Sem regularizacao, um grupo sem votos leva o swing ao infinito e a calibracao falha."""
    with pytest.raises(InvariantViolationError):
        calibrated_logratio_swing(
            [100.0], [[0.5, 0.4, 0.1]], [60.0, 40.0, 0.0], reference_index=0, pseudo_count=0.0
        )


def test_empty_observations_return_zero_swing() -> None:
    """Sem secoes observadas, o swing calibrado e nulo."""
    delta = calibrated_logratio_swing([], [], [0.0, 0.0, 0.0], reference_index=2, pseudo_count=0.0)
    assert delta == (0.0, 0.0, 0.0)


@pytest.mark.parametrize(
    ("valid", "hist", "totals", "ref"),
    [
        ([100.0, 50.0], [[0.5, 0.5]], [80.0, 70.0], 1),
        ([100.0], [[0.5, 0.5]], [80.0, 20.0], 2),
        ([-1.0], [[0.5, 0.5]], [80.0, 20.0], 1),
        ([100.0], [[0.5, 0.5]], [100.0], 0),
    ],
)
def test_invalid_inputs_raise_validation_error(
    valid: list[float], hist: list[list[float]], totals: list[float], ref: int
) -> None:
    """Entradas com dimensoes, sinais ou indice de referencia invalidos sao rejeitadas.

    Args:
        valid: Votos validos por secao.
        hist: Shares historicos por secao.
        totals: Totais observados por grupo.
        ref: Indice do grupo de referencia.
    """
    with pytest.raises(ValidationError):
        calibrated_logratio_swing(valid, hist, totals, reference_index=ref, pseudo_count=0.0)


def test_vote_conservation_mismatch_raises_validation_error() -> None:
    """Soma de votos validos divergente da soma de votos por grupo lanca ValidationError."""
    with pytest.raises(ValidationError, match="diverge da soma dos totais"):
        calibrated_logratio_swing(
            [100.0, 100.0],
            [[0.5, 0.5], [0.5, 0.5]],
            [120.0, 90.0],
            reference_index=1,
            pseudo_count=0.0,
        )


def test_non_convergence_raises_invariant_violation_error() -> None:
    """Se o Newton-Raphson nao convergir no maximo de iteracoes, lanca InvariantViolationError."""
    with pytest.raises(InvariantViolationError, match="nao convergiu apos"):
        calibrated_logratio_swing(
            HETERO_VALID,
            HETERO_HIST,
            HETERO_TOTALS,
            reference_index=2,
            pseudo_count=0.0,
            max_iter=0,
            tol=1e-15,
        )


def test_dispatcher_selects_estimator() -> None:
    """O despachante respeita a estrategia escolhida."""
    args = (HETERO_VALID, HETERO_HIST, HETERO_TOTALS)
    assert estimate_logratio_swing(
        SwingEstimator.AGGREGATE, *args, reference_index=2
    ) == aggregate_logratio_swing(*args, reference_index=2)
    assert estimate_logratio_swing(
        SwingEstimator.CALIBRATED, *args, reference_index=2
    ) == calibrated_logratio_swing(*args, reference_index=2)
