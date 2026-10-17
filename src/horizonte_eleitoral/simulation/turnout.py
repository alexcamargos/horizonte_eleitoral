"""Simulacao de comparecimento e votos validos via modelo hierarquico Beta-Binomial."""

from __future__ import annotations

from typing import cast

import numpy as np


def sample_beta_binomial(
    n_trials: np.ndarray,
    mean_rate: float,
    dispersion: float,
    num_draws: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Realiza sorteios vetorizados da distribuicao Beta-Binomial.

    Parametrizacao por media mu e dispersao gamma in (0, 1):
        M = (1 - gamma) / gamma
        alpha = mu * M
        beta = (1 - mu) * M
        p ~ Beta(alpha, beta)
        k ~ Binomial(n, p)

    Args:
        n_trials: Array 1D com o numero de tentativas (e.g. eleitorado) por secao [num_sections].
        mean_rate: Proporcao media esperada (e.g. 0.80 para comparecimento).
        dispersion: Parametro de dispersao gamma (e.g. 0.05).
        num_draws: Quantidade de sorteios Monte Carlo R.
        rng: Gerador de numeros aleatorios NumPy.

    Returns:
        Array 2D de contagens simuladas inteiras [num_draws, num_sections].

    Raises:
        ValueError: Se mean_rate ou dispersion estiverem fora de (0, 1).
    """
    if not 0.0 < mean_rate < 1.0:
        raise ValueError("mean_rate deve estar no intervalo aberto (0, 1).")
    if not 0.0 < dispersion < 1.0:
        raise ValueError("dispersion deve estar no intervalo aberto (0, 1).")

    m_conc = (1.0 - dispersion) / dispersion
    alpha = mean_rate * m_conc
    beta_param = (1.0 - mean_rate) * m_conc

    num_sections = len(n_trials)
    # Sorteia taxas de sucesso estocasticas p ~ Beta(alpha, beta) para cada draw e secao
    p_sampled = rng.beta(alpha, beta_param, size=(num_draws, num_sections))

    # Sorteia contagens k ~ Binomial(n, p)
    # n_trials e expandido para broadcasting com shape (num_draws, num_sections)
    return cast(np.ndarray, rng.binomial(n_trials, p_sampled))


def sample_valid_votes_for_pending(
    electorates: np.ndarray,
    turnout_mean: float = 0.80,
    turnout_dispersion: float = 0.02,
    valid_mean: float = 0.95,
    valid_dispersion: float = 0.01,
    num_draws: int = 2000,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """Sorteia votos validos para cada secao pendente em R cenarios preditivos.

    Args:
        electorates: Array 1D com eleitorado de cada secao pendente.
        turnout_mean: Taxa media de comparecimento.
        turnout_dispersion: Dispersao do comparecimento entre secoes.
        valid_mean: Proporcao media de votos validos entre os presentes.
        valid_dispersion: Dispersao de votos validos.
        num_draws: Quantidade de draws de Monte Carlo.
        rng: Gerador aleatorio opcional.

    Returns:
        Array 2D com contagem de votos validos [num_draws, num_sections].
    """
    generator = rng or np.random.default_rng()

    # 1. Sorteia comparecimento A_s ~ BetaBinomial(E_s)
    turnout = sample_beta_binomial(
        n_trials=electorates,
        mean_rate=turnout_mean,
        dispersion=turnout_dispersion,
        num_draws=num_draws,
        rng=generator,
    )

    # 2. Sorteia votos validos V_s dado A_s ~ BetaBinomial(A_s)
    m_conc = (1.0 - valid_dispersion) / valid_dispersion
    alpha = valid_mean * m_conc
    beta_param = (1.0 - valid_mean) * m_conc

    p_valid = generator.beta(alpha, beta_param, size=turnout.shape)
    return cast(np.ndarray, generator.binomial(turnout, p_valid))
