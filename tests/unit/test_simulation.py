"""Testes unitarios para simulacao de Monte Carlo, comparecimento e intervalos preditivos."""

import numpy as np

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
