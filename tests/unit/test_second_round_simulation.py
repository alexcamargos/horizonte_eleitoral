"""Testes unitarios para a simulacao e projecao do 2º Turno majoritario (PT vs PL)."""

from __future__ import annotations

from typing import Any

import pytest

from horizonte_eleitoral.dashboard.replay import load_replay_catalog
from horizonte_eleitoral.domain.enums import GeographicScope
from horizonte_eleitoral.normalization.models import NormalizedTotalization
from horizonte_eleitoral.simulation.election_night_runner import (
    simulate_2026_second_round_checkpoint,
)
from horizonte_eleitoral.simulation.second_round_live import (
    AggregatedStratum,
    allocate_stratum_observations,
    project_second_round_live,
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


def _build_two_region_catalog() -> list[dict[str, Any]]:
    """Constroi catalogo controlado em que o 1º turno teve vantagem do PL (51% vs 49% bilateral).

    Returns:
        Lista ordenada de secoes (SP apurando antes de BA) com dados do 1º turno.

    Raises:
        None.
    """
    catalog: list[dict[str, Any]] = []
    # Primeiras 60 secoes: SP (forte PL no 1T: 60% PL, 40% PT)
    for i in range(60):
        catalog.append(
            {
                "section_id": f"SP:71072:{(i % 6) + 1:04d}:{i:04d}",
                "state": "SP",
                "municipality_code": "71072",
                "zone": f"{(i % 6) + 1:04d}",
                "section": f"{i:04d}",
                "electorate": 400,
                "valid_votes": 320,
                "group_votes": (("OUTROS", 20), ("PL", 180), ("PT", 120)),
                "historical_shares": (("OUTROS", 0.08), ("PL", 0.55), ("PT", 0.37)),
            }
        )
    # Ultimas 40 secoes: BA (forte PT no 1T: 36% PL, 64% PT) -> media 1T = 50.4% PL vs 49.6% PT
    for j in range(40):
        idx = 60 + j
        catalog.append(
            {
                "section_id": f"BA:38490:{(j % 4) + 1:04d}:{idx:04d}",
                "state": "BA",
                "municipality_code": "38490",
                "zone": f"{(j % 4) + 1:04d}",
                "section": f"{idx:04d}",
                "electorate": 400,
                "valid_votes": 320,
                "group_votes": (("OUTROS", 20), ("PL", 108), ("PT", 192)),
                "historical_shares": (("OUTROS", 0.06), ("PL", 0.34), ("PT", 0.60)),
            }
        )
    return catalog


def test_project_second_round_live_tracks_lula_lead_at_70_and_81_pct() -> None:
    """Valida que a projecao em tempo real responde aos votos reais do 2T em 70% e 81%.

    Mesmo quando o catalogo do 1º turno aponta vantagem bilateral do PL, se na apuracao real
    do 2º turno Lula (PT) lidera com 50,9% em 70% e avanca para 51,32% em 81%, o modelo
    deve projetar vitoria de Lula e refletir o aumento monotono da vantagem.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: Se o modelo permanecer preso aos votos do 1º turno.
    """
    catalog = _build_two_region_catalog()

    tot_70 = NormalizedTotalization(
        scope=GeographicScope.BRAZIL,
        scope_code="BR",
        total_electorate=40000,
        totalized_electorate=28000,
        pending_electorate=12000,
        total_sections=100,
        totalized_sections=70,
        pending_sections=30,
        valid_votes=22400,
        blank_votes=400,
        null_votes=600,
        candidate_group_votes=(("PL", 10998), ("PT", 11402)),  # PT 50.90% ja em 70%
    )
    tot_81 = NormalizedTotalization(
        scope=GeographicScope.BRAZIL,
        scope_code="BR",
        total_electorate=40000,
        totalized_electorate=32400,
        pending_electorate=7600,
        total_sections=100,
        totalized_sections=81,
        pending_sections=19,
        valid_votes=25920,
        blank_votes=450,
        null_votes=700,
        candidate_group_votes=(("PL", 12618), ("PT", 13302)),  # PT 51.32% vs PL 48.68%
    )

    p70 = simulate_2026_second_round_checkpoint(
        progress_pct=0.70,
        sections_catalog=catalog,
        num_draws=300,
        seed=42,
        live_totalization=tot_70,
    )
    p81 = simulate_2026_second_round_checkpoint(
        progress_pct=0.81,
        sections_catalog=catalog,
        num_draws=300,
        seed=42,
        live_totalization=tot_81,
    )

    g70 = {g.code: g for g in p70.groups}
    g81 = {g.code: g for g in p81.groups}

    assert g70["PT"].projected_share > 51.0
    assert g70["PT"].projected_share > g70["PL"].projected_share
    assert g70["PT"].win_probability > 0.90

    assert g81["PT"].projected_share > 51.3
    assert g81["PT"].win_probability > 0.95
    assert g81["PT"].observed_share == pytest.approx(51.32, abs=0.05)


def test_project_second_round_live_with_state_totalizations_accounts_for_late_ufs() -> None:
    """Valida condicionamento estadual por UF preservando soma inteira exata dos votos do TSE.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: Se os votos observados forem alterados ou se a composicao pendente falhar.
    """
    from horizonte_eleitoral.domain.enums import MatchQuality

    strata = [
        AggregatedStratum("SP:71072:0001", "SP", "71072", 5000, 0.60, 0.40, MatchQuality.EXACT),
        AggregatedStratum("SP:71072:0002", "SP", "71072", 5000, 0.55, 0.45, MatchQuality.EXACT),
    ]
    obs = allocate_stratum_observations(strata, target_pl=4321, target_pt=3679)
    assert sum(dict(o.group_votes)["PL"] for o in obs) == 4321
    assert sum(dict(o.group_votes)["PT"] for o in obs) == 3679

    catalog = _build_two_region_catalog()
    # SP com 90% apurado (21.600 de 24.000) e BA com apenas 50% apurado (8.000 de 16.000)
    sp_tot = NormalizedTotalization(
        scope=GeographicScope.STATE,
        scope_code="SP",
        total_electorate=24000,
        totalized_electorate=21600,
        pending_electorate=2400,
        total_sections=60,
        totalized_sections=54,
        pending_sections=6,
        valid_votes=17280,
        blank_votes=300,
        null_votes=400,
        candidate_group_votes=(("PL", 9677), ("PT", 7603)),  # PT 44% em SP (acima dos 40% do 1T!)
    )
    ba_tot = NormalizedTotalization(
        scope=GeographicScope.STATE,
        scope_code="BA",
        total_electorate=16000,
        totalized_electorate=8000,
        pending_electorate=8000,
        total_sections=40,
        totalized_sections=20,
        pending_sections=20,
        valid_votes=6400,
        blank_votes=100,
        null_votes=150,
        candidate_group_votes=(("PL", 1920), ("PT", 4480)),  # PT 70% na BA
    )
    br_tot = NormalizedTotalization(
        scope=GeographicScope.BRAZIL,
        scope_code="BR",
        total_electorate=40000,
        totalized_electorate=29600,
        pending_electorate=10400,
        total_sections=100,
        totalized_sections=74,
        pending_sections=26,
        valid_votes=23680,
        blank_votes=400,
        null_votes=550,
        candidate_group_votes=(("PL", 11597), ("PT", 12083)),  # Apurado BR: PT 51.03%
    )

    payload = project_second_round_live(
        totalization=br_tot,
        sections_catalog=catalog,
        state_totalizations={"SP": sp_tot, "BA": ba_tot},
        num_draws=400,
        seed=42,
    )
    groups = {g.code: g for g in payload.groups}
    # Como BA (70% PT) ainda tem 8.000 eleitores pendentes contra apenas 2.400 de SP,
    # a projecao final de PT deve superar o apurado atual de 51,03% (~53-54%)!
    assert groups["PT"].observed_share == pytest.approx(51.03, abs=0.05)
    assert groups["PT"].projected_share > groups["PT"].observed_share + 1.5
    assert groups["PT"].win_probability > 0.99


def test_project_second_round_live_at_100_pct_converges_with_zero_uncertainty() -> None:
    """Valida convergencia deterministica exata e intervalo zero quando 100% esta apurado.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: Se houver divergencia ou incerteza residual em 100% da apuracao.
    """
    catalog = _build_two_region_catalog()
    br_100 = NormalizedTotalization(
        scope=GeographicScope.BRAZIL,
        scope_code="BR",
        total_electorate=40000,
        totalized_electorate=40000,
        pending_electorate=0,
        total_sections=100,
        totalized_sections=100,
        pending_sections=0,
        valid_votes=32000,
        blank_votes=500,
        null_votes=700,
        candidate_group_votes=(("PL", 15360), ("PT", 16640)),  # Exatos 52.00% PT vs 48.00% PL
    )
    payload = project_second_round_live(
        totalization=br_100,
        sections_catalog=catalog,
        num_draws=200,
        seed=42,
    )
    groups = {g.code: g for g in payload.groups}
    assert groups["PT"].observed_share == 52.0
    assert groups["PT"].projected_share == 52.0
    assert groups["PT"].q05 == 52.0
    assert groups["PT"].q95 == 52.0
    assert groups["PT"].win_probability == 1.0
    assert groups["PL"].win_probability == 0.0
