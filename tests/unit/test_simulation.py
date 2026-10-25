"""Testes unitarios para simulacao de Monte Carlo, comparecimento e intervalos preditivos."""

import numpy as np
import pytest

from horizonte_eleitoral.domain.enums import MatchQuality
from horizonte_eleitoral.models.base import PendingSection, SectionObservation
from horizonte_eleitoral.models.hierarchical import HierarchicalBayesianModel
from horizonte_eleitoral.simulation.monte_carlo import MonteCarloSimulator
from horizonte_eleitoral.simulation.turnout import sample_beta_binomial


def test_sample_beta_binomial() -> None:
    """Valida geracao de sorteios Beta-Binomial respeitando limites de tentativas."""
    n_trials = np.array([100, 200, 300])
    rng = np.random.default_rng(123)

    samples = sample_beta_binomial(
        n_trials=n_trials,
        mean_rate=0.80,
        dispersion=0.02,
        num_draws=500,
        rng=rng,
    )

    assert samples.shape == (500, 3)
    assert np.all(samples >= 0)
    assert np.all(samples[:, 0] <= 100)
    assert np.all(samples[:, 1] <= 200)
    assert np.all(samples[:, 2] <= 300)

    # Media empirica proxima de 80%
    empirical_mean = np.mean(samples[:, 0]) / 100.0
    assert 0.75 < empirical_mean < 0.85


def test_monte_carlo_simulator_invariants_and_quantiles() -> None:
    """Valida ordenacao de quantis, soma de shares 1.0 e probabilidade de 2o turno."""
    obs = [
        SectionObservation(
            section_id="SP:1:1",
            state="SP",
            municipality_code="71072",
            valid_votes=500,
            group_votes=(("PT", 250), ("PL", 200), ("OUTROS", 50)),
            historical_shares=(("PT", 0.5), ("PL", 0.4), ("OUTROS", 0.1)),
        )
    ]

    pending = [
        PendingSection(
            section_id="SP:1:2",
            state="SP",
            municipality_code="71072",
            electorate=600,
            historical_shares=(("PT", 0.5), ("PL", 0.4), ("OUTROS", 0.1)),
        )
    ]

    model = HierarchicalBayesianModel()
    simulator = MonteCarloSimulator(num_draws=500, seed=999)

    summary = simulator.simulate(
        observations=obs,
        pending=pending,
        model=model,
        match_qualities={"SP:1:2": MatchQuality.EXACT},
    )

    mean_dict = dict(summary.projected_mean_shares)
    q05_dict = dict(summary.q05_shares)
    q50_dict = dict(summary.q50_shares)
    q95_dict = dict(summary.q95_shares)

    # 1. Shares medios somam 1.0
    assert abs(sum(mean_dict.values()) - 1.0) < 1e-4

    # 2. Ordenacao estrita de quantis: q05 <= q50 <= q95
    for g in ("PT", "PL", "OUTROS"):
        assert q05_dict[g] <= q50_dict[g] <= q95_dict[g]

    # 3. Probabilidade de 2o turno entre 0 e 1
    assert 0.0 <= summary.second_round_probability <= 1.0

    # 4. Total de validos projetados maior que os observados
    assert summary.total_projected_valid_mean > 500


def test_monte_carlo_reproducibility() -> None:
    """Mesma semente deve gerar resultados bit a bit identicos."""
    obs = [
        SectionObservation(
            section_id="SP:1:1",
            state="SP",
            municipality_code="71072",
            valid_votes=200,
            group_votes=(("PT", 100), ("PL", 80), ("OUTROS", 20)),
            historical_shares=(("PT", 0.5), ("PL", 0.4), ("OUTROS", 0.1)),
        )
    ]
    pending = [
        PendingSection(
            section_id="SP:1:2",
            state="SP",
            municipality_code="71072",
            electorate=400,
            historical_shares=(("PT", 0.5), ("PL", 0.4), ("OUTROS", 0.1)),
        )
    ]
    model = HierarchicalBayesianModel()

    sim1 = MonteCarloSimulator(num_draws=300, seed=42)
    sim2 = MonteCarloSimulator(num_draws=300, seed=42)

    res1 = sim1.simulate(observations=obs, pending=pending, model=model)
    res2 = sim2.simulate(observations=obs, pending=pending, model=model)

    assert res1.projected_mean_shares == res2.projected_mean_shares
    assert res1.q05_shares == res2.q05_shares
    assert res1.q95_shares == res2.q95_shares
    assert res1.second_round_probability == res2.second_round_probability


def test_monte_carlo_finite_population_correction_uncertainty() -> None:
    """Valida reducao monotona do intervalo de credibilidade conforme apuracao avanca (FPC)."""
    model = HierarchicalBayesianModel()
    sim = MonteCarloSimulator(num_draws=400, seed=42)

    # Cria 10 secoes no total
    all_sections_obs = [
        SectionObservation(
            section_id=f"SP:1:{i}",
            state="SP",
            municipality_code="71072",
            valid_votes=400,
            group_votes=(("PT", 200), ("PL", 160), ("OUTROS", 40)),
            historical_shares=(("PT", 0.5), ("PL", 0.4), ("OUTROS", 0.1)),
        )
        for i in range(1, 11)
    ]
    all_sections_pend = [
        PendingSection(
            section_id=f"SP:1:{i}",
            state="SP",
            municipality_code="71072",
            electorate=500,
            historical_shares=(("PT", 0.5), ("PL", 0.4), ("OUTROS", 0.1)),
        )
        for i in range(1, 11)
    ]

    # Cenario A: Apenas 1 secao observada (90% pendente)
    res_sparse = sim.simulate(
        observations=all_sections_obs[:1],
        pending=all_sections_pend[1:],
        model=model,
    )
    q05_a = dict(res_sparse.q05_shares)
    q95_a = dict(res_sparse.q95_shares)
    width_a = q95_a["PT"] - q05_a["PT"]

    # Cenario B: 8 secoes observadas (20% pendente)
    res_dense = sim.simulate(
        observations=all_sections_obs[:8],
        pending=all_sections_pend[8:],
        model=model,
    )
    q05_b = dict(res_dense.q05_shares)
    q95_b = dict(res_dense.q95_shares)
    width_b = q95_b["PT"] - q05_b["PT"]

    # Cenario C: 10 secoes observadas (0% pendente - apuracao completa)
    res_complete = sim.simulate(
        observations=all_sections_obs,
        pending=[],
        model=model,
    )
    q05_c = dict(res_complete.q05_shares)
    q95_c = dict(res_complete.q95_shares)
    width_c = q95_c["PT"] - q05_c["PT"]

    # FPC garante que a incerteza com 90% pendente e maior que com 20% pendente,
    # e com 0% pendente a incerteza e estritamente nula.
    assert width_a > width_b > width_c
    assert width_c == 0.0


def test_monte_carlo_candidate_win_probabilities() -> None:
    """Valida calculo e consistencia das probabilidades de vitoria por candidato."""
    obs = [
        SectionObservation(
            section_id="SP:1:1",
            state="SP",
            municipality_code="71072",
            valid_votes=500,
            group_votes=(("PT", 300), ("PL", 150), ("OUTROS", 50)),
            historical_shares=(("PT", 0.5), ("PL", 0.4), ("OUTROS", 0.1)),
        )
    ]
    pending = [
        PendingSection(
            section_id="SP:1:2",
            state="SP",
            municipality_code="71072",
            electorate=600,
            historical_shares=(("PT", 0.5), ("PL", 0.4), ("OUTROS", 0.1)),
        )
    ]
    model = HierarchicalBayesianModel()
    simulator = MonteCarloSimulator(num_draws=300, seed=42)
    summary = simulator.simulate(observations=obs, pending=pending, model=model)

    win_probs = dict(summary.candidate_win_probabilities)
    assert len(win_probs) == 3
    assert sum(win_probs.values()) == pytest.approx(1.0, abs=1e-3)
    assert win_probs["PT"] > win_probs["PL"]
    assert win_probs["PT"] > win_probs["OUTROS"]
