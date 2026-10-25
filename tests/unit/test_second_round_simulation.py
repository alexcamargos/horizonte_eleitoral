"""Testes unitarios para a simulacao e projecao do 2º Turno majoritario (PT vs PL)."""

from __future__ import annotations

import pytest

from horizonte_eleitoral.dashboard.replay import load_replay_catalog
from horizonte_eleitoral.simulation.election_night_runner import (
    simulate_2026_second_round_checkpoint,
)


def test_simulate_second_round_checkpoint_structure() -> None:
    """Valida que a simulacao de 2º turno produz estritamente os dois grupos finalistas."""
    payload = simulate_2026_second_round_checkpoint(
        progress_pct=0.30,
        num_sections=40,
        num_draws=100,
        seed=42,
    )

    assert payload.status == "published"
    assert payload.model_version == "2026.2"

    group_dict = {g.code: g for g in payload.groups}
    assert set(group_dict.keys()) == {"PL", "PT"}
    assert "OUTROS" not in group_dict

    # Soma dos shares projetados deve ser 100%
    total_proj = sum(g.projected_share for g in payload.groups)
    assert 99.9 <= total_proj <= 100.1

    # Soma dos shares observados deve ser 100%
    total_obs = sum(g.observed_share for g in payload.groups)
    assert 99.9 <= total_obs <= 100.1

    # Consistencia das faixas de credibilidade e probabilidade de vitoria
    assert payload.second_round_probability == 0.0
    total_win_prob = sum(g.win_probability for g in payload.groups)
    assert total_win_prob == pytest.approx(1.0, abs=1e-3)

    for g in payload.groups:
        assert g.q05 <= g.projected_share <= g.q95
        assert 0.0 <= g.q05 <= 100.0
        assert 0.0 <= g.q95 <= 100.0
        assert 0.0 <= g.win_probability <= 1.0


def test_simulate_second_round_with_real_catalog_sample() -> None:
    """Valida a execucao do 2º turno com amostra do catalogo analitico de secoes."""
    catalog = load_replay_catalog(limit_sections=50)
    payload = simulate_2026_second_round_checkpoint(
        progress_pct=0.50,
        sections_catalog=catalog,
        num_draws=100,
        seed=123,
    )

    assert payload.totalized_electorate_pct >= 40.0
    group_dict = {g.code: g for g in payload.groups}
    assert "PT" in group_dict
    assert "PL" in group_dict

    pt = group_dict["PT"]
    pl = group_dict["PL"]
    assert pt.projected_share + pl.projected_share == pytest.approx(100.0, abs=0.1)


def test_simulate_second_round_validates_progress_pct() -> None:
    """Valida que progress_pct fora de (0, 1] lanca ValueError."""
    with pytest.raises(ValueError, match="progress_pct"):
        simulate_2026_second_round_checkpoint(progress_pct=0.0)

    with pytest.raises(ValueError, match="progress_pct"):
        simulate_2026_second_round_checkpoint(progress_pct=1.05)
