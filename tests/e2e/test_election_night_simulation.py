"""Teste e2e de ensaio operacional simulando a noite eleitoral ponta a ponta."""

from __future__ import annotations

import pytest

from horizonte_eleitoral.simulation.election_night_runner import (
    run_election_night_simulation,
    simulate_2026_first_round_checkpoint,
)


def test_election_night_e2e_rehearsal_meets_latency_gate() -> None:
    """Valida ensaio operacional completo e confirma latencia p95 < 10 segundos.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    metrics = run_election_night_simulation(
        num_sections=40,
        waves=(0.10, 0.30, 0.60, 1.00),
        num_draws=400,
        seed=123,
    )

    # Gate operacional: p95 menor que 10 segundos
    assert metrics["p95_seconds"] < 10.0
    assert metrics["mean_seconds"] < 5.0
    assert metrics["max_seconds"] < 10.0


@pytest.mark.parametrize("pct", [10, 20, 30, 40, 50, 60, 70, 80, 90, 100])
def test_first_round_2026_at_10pct_steps(pct: int) -> None:
    """Testa a projecao e publicacao de 10% a 100% (em passos de 10 pontos) do 1o turno de 2026.

    Args:
        pct: Marco percentual de apuracao (10, 20, ..., 100).

    Returns:
        None.

    Raises:
        None.
    """
    payload = simulate_2026_first_round_checkpoint(
        progress_pct=pct / 100.0,
        num_sections=50,
        num_draws=200,
        seed=42,
    )

    # 1. Validacao do progresso de apuracao em torno do percentual esperado
    assert (pct - 3.0) <= payload.totalized_electorate_pct <= min(100.0, pct + 3.0)
    assert payload.status == "published"
    assert payload.model_version == "2026.2"

    # 2. Validacao da probabilidade de 2o turno
    assert 0.0 <= payload.second_round_probability <= 1.0

    # 3. Validacao dos grupos politicos e intervalos de credibilidade 90%
    groups = {g.code: g for g in payload.groups}
    assert set(groups.keys()) == {"OUTROS", "PL", "PT"}

    total_projected_share = sum(g.projected_share for g in payload.groups)
    assert 99.9 <= total_projected_share <= 100.1

    for g in payload.groups:
        assert g.q05 <= g.projected_share <= g.q95
        assert 0.0 <= g.observed_share <= 100.0

    # 4. Validacao dos metadados de qualidade dos dados
    assert payload.data_quality["total_electorate"] > 0
    assert payload.data_quality["totalized_electorate"] > 0
    if pct < 100:
        assert payload.data_quality["pending_electorate"] > 0
    else:
        assert payload.data_quality["pending_electorate"] == 0
