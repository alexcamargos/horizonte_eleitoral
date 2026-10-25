"""Estimadores de swing composicional em log-ratio para projecao de secoes pendentes.

O swing em log-ratio desloca a base historica de cada secao por um vetor comum
``delta`` aplicado via softmax: ``p_ik = h_ik * exp(delta_k) / sum_m h_im * exp(delta_m)``.

Dois estimadores de ``delta`` sao oferecidos:

* ``aggregate_logratio_swing`` (legado): forma fechada sobre os **totais** agregados.
  Como a softmax e nao linear, aplicar esse ``delta`` secao a secao nao reconstroi os
  totais observados quando as bases historicas sao heterogeneas (vies de Jensen).
* ``calibrated_logratio_swing`` (padrao): resolve as equacoes de calibracao
  ``sum_i v_i * p_ik(delta) = Y_k`` por Newton-Raphson. Equivale a estimativa de maxima
  verossimilhanca dos interceptos de um logit multinomial com offsets ``log h_ik`` e,
  por construcao, reproduz os totais observados quando aplicado as proprias secoes.

Modulo puro: sem I/O, sem aleatoriedade e sem leitura de ambiente.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

import numpy as np
import numpy.typing as npt

from horizonte_eleitoral.domain.errors import InvariantViolationError, ValidationError

FloatArray = npt.NDArray[np.float64]


class SwingEstimator(StrEnum):
    """Estrategia de estimacao do swing composicional em log-ratio."""

    CALIBRATED = "calibrado"
    AGGREGATE = "agregado"


def _prepare_inputs(
    valid_votes: Sequence[float] | FloatArray,
    historical_shares: Sequence[Sequence[float]] | FloatArray,
    observed_totals: Sequence[float] | FloatArray,
    reference_index: int,
    pseudo_count: float,
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Valida e converte as entradas para arrays numpy.

    Linhas historicas sem massa positiva sao substituidas pela distribuicao uniforme.

    Args:
        valid_votes: Votos validos por secao (n,).
        historical_shares: Shares historicos por secao (n, k).
        observed_totals: Votos observados agregados por grupo (k,).
        reference_index: Indice do grupo de referencia.
        pseudo_count: Pseudo-contagem de regularizacao por grupo.

    Returns:
        Tupla (votos validos, shares historicos, totais observados).

    Raises:
        ValidationError: Se dimensoes, valores ou o indice de referencia forem invalidos.
    """
    v = np.asarray(valid_votes, dtype=np.float64)
    y = np.asarray(observed_totals, dtype=np.float64)
    n_groups = y.shape[0] if y.ndim == 1 else 0
    if n_groups < 2:
        raise ValidationError("observed_totals deve ser um vetor com pelo menos 2 grupos.")
    h = np.asarray(historical_shares, dtype=np.float64).reshape(-1, n_groups)
    if v.ndim != 1 or h.shape[0] != v.shape[0]:
        raise ValidationError("valid_votes e historical_shares devem ter o mesmo numero de secoes.")
    if not 0 <= reference_index < n_groups:
        raise ValidationError("reference_index fora do intervalo de grupos.")
    if pseudo_count < 0.0:
        raise ValidationError("pseudo_count nao pode ser negativo.")
    if (v < 0.0).any() or (h < 0.0).any() or (y < 0.0).any():
        raise ValidationError("Votos e shares historicos nao podem ser negativos.")
    v_tot = float(v.sum())
    y_tot = float(y.sum())
    if abs(v_tot - y_tot) > max(1e-4, 1e-5 * v_tot):
        raise ValidationError(
            f"Soma dos votos validos por secao ({v_tot:.2f}) diverge "
            f"da soma dos totais observados por grupo ({y_tot:.2f})."
        )
    row_mass = h.sum(axis=1)
    h = np.where(row_mass[:, None] > 0.0, h, 1.0 / n_groups)
    return v, h, y


def aggregate_logratio_swing(
    valid_votes: Sequence[float] | FloatArray,
    historical_shares: Sequence[Sequence[float]] | FloatArray,
    observed_totals: Sequence[float] | FloatArray,
    *,
    reference_index: int,
    pseudo_count: float = 10.0,
) -> tuple[float, ...]:
    """Estimador legado em forma fechada sobre os totais agregados.

    ``delta_k = ln((Y_k + e) / (Y_ref + e)) - ln((B_k + e) / (B_ref + e))``, com
    ``B_k = sum_i v_i * h_ik``. Mantido para auditoria e comparacao historica.

    Args:
        valid_votes: Votos validos por secao observada.
        historical_shares: Shares historicos por secao observada (n, k).
        observed_totals: Votos observados agregados por grupo (k,).
        reference_index: Indice do grupo de referencia (delta fixado em zero).
        pseudo_count: Pseudo-contagem ``e`` somada a cada total.

    Returns:
        Tupla com ``delta_k`` por grupo; o grupo de referencia vale 0.0.

    Raises:
        ValidationError: Se as entradas forem inconsistentes.
    """
    v, h, y = _prepare_inputs(
        valid_votes, historical_shares, observed_totals, reference_index, pseudo_count
    )
    b = v @ h
    ye, be = y + pseudo_count, b + pseudo_count
    if ye[reference_index] <= 0.0 or be[reference_index] <= 0.0 or (ye <= 0.0).any():
        return tuple(0.0 for _ in range(y.shape[0]))
    with np.errstate(divide="ignore"):
        delta = np.log(ye / ye[reference_index]) - np.log(be / be[reference_index])
    if not np.isfinite(delta).all():
        return tuple(0.0 for _ in range(y.shape[0]))
    return tuple(float(d) for d in delta)


def calibrated_logratio_swing(
    valid_votes: Sequence[float] | FloatArray,
    historical_shares: Sequence[Sequence[float]] | FloatArray,
    observed_totals: Sequence[float] | FloatArray,
    *,
    reference_index: int,
    pseudo_count: float = 10.0,
    max_iter: int = 100,
    tol: float = 1e-10,
) -> tuple[float, ...]:
    """Estima ``delta`` que reproduz os totais observados quando aplicado secao a secao.

    Resolve ``sum_i v_i * p_ik(delta) + K*e*q_k(delta) = Y_k + e`` para todo grupo ``k``,
    onde ``q = softmax(delta)`` corresponde a uma pseudo-secao de ``K*e`` votos com base
    uniforme. A pseudo-secao torna o problema estritamente convexo (solucao unica e
    finita mesmo com grupos sem votos). O metodo e Newton-Raphson amortecido com busca
    linear de Armijo sobre a funcao objetivo convexa
    ``f(delta) = sum_i v_i * lse_i(delta) + K*e*lse_0(delta) - sum_k (Y_k + e) * delta_k``.

    Args:
        valid_votes: Votos validos por secao observada (n,).
        historical_shares: Shares historicos por secao observada (n, k).
        observed_totals: Votos observados agregados por grupo (k,).
        reference_index: Indice do grupo de referencia (delta fixado em zero).
        pseudo_count: Pseudo-contagem ``e`` por grupo; ``0.0`` desativa a regularizacao.
        max_iter: Numero maximo de iteracoes de Newton.
        tol: Tolerancia relativa do gradiente (fracao do total de votos).

    Returns:
        Tupla com ``delta_k`` por grupo; o grupo de referencia vale 0.0.

    Raises:
        ValidationError: Se as entradas forem inconsistentes.
        InvariantViolationError: Se o metodo nao convergir (ex.: grupo sem votos e
            ``pseudo_count == 0``).
    """
    v, h, y = _prepare_inputs(
        valid_votes, historical_shares, observed_totals, reference_index, pseudo_count
    )
    n_groups = int(y.shape[0])
    mask = v > 0.0
    v, h = v[mask], h[mask]
    pseudo_weight = float(n_groups) * pseudo_count
    total = float(v.sum()) + pseudo_weight
    if total <= 0.0 or v.shape[0] == 0:
        return tuple(0.0 for _ in range(n_groups))

    if pseudo_count <= 0.0 and (y <= 0.0).any():
        raise InvariantViolationError(
            "Grupo com zero votos observados requer pseudo_count > 0 para calibracao finita."
        )

    target = y + pseudo_count
    free = np.array([k for k in range(n_groups) if k != reference_index])
    uniform = np.full(n_groups, 1.0 / n_groups)

    def objective(delta: FloatArray) -> float:
        shift = float(delta.max())
        lse = np.log((h * np.exp(delta - shift)).sum(axis=1)) + shift
        lse0 = float(np.log((uniform * np.exp(delta - shift)).sum()) + shift)
        lse_term = float(np.asarray(v @ lse).item())
        target_term = float(np.asarray(target @ delta).item())
        val: float = lse_term + pseudo_weight * lse0 - target_term
        return val

    def gradient_hessian(delta: FloatArray) -> tuple[FloatArray, FloatArray]:
        unnorm = h * np.exp(delta - delta.max())
        p = unnorm / unnorm.sum(axis=1, keepdims=True)
        q = uniform * np.exp(delta - delta.max())
        q = q / q.sum()
        fitted = v @ p + pseudo_weight * q
        weighted = p * v[:, None]
        hess = np.diag(fitted) - weighted.T @ p - pseudo_weight * np.outer(q, q)
        return fitted - target, hess

    init = aggregate_logratio_swing(
        v, h, y, reference_index=reference_index, pseudo_count=max(pseudo_count, 1e-9)
    )
    delta = np.asarray(init, dtype=np.float64)
    for _ in range(max_iter):
        grad, hess = gradient_hessian(delta)
        g_free = grad[free]
        if float(np.abs(g_free).max()) <= tol * total:
            return tuple(float(d) for d in delta)
        h_free = hess[np.ix_(free, free)]
        try:
            step_free = np.linalg.solve(h_free, -g_free)
        except np.linalg.LinAlgError:
            try:
                step_free = np.linalg.lstsq(h_free, -g_free, rcond=None)[0]
            except np.linalg.LinAlgError as err:
                raise InvariantViolationError(
                    "Calibracao do swing log-ratio falhou por singularidade matricial."
                ) from err
        step = np.zeros(n_groups)
        step[free] = step_free
        f0 = objective(delta)
        slope = float(g_free @ step_free)
        alpha = 1.0
        while alpha > 1e-12 and objective(delta + alpha * step) > f0 + 1e-4 * alpha * slope:
            alpha *= 0.5
        delta = delta + alpha * step
    grad, _ = gradient_hessian(delta)
    max_g = float(np.abs(grad[free]).max())
    if max_g <= tol * total * 1e3:
        return tuple(float(d) for d in delta)
    raise InvariantViolationError(
        f"Calibracao do swing log-ratio nao convergiu apos {max_iter} iteracoes "
        f"(gradiente maximo: {max_g:.2e}, tolerancia: {tol * total * 1e3:.2e})."
    )


def estimate_logratio_swing(
    estimator: SwingEstimator,
    valid_votes: Sequence[float] | FloatArray,
    historical_shares: Sequence[Sequence[float]] | FloatArray,
    observed_totals: Sequence[float] | FloatArray,
    *,
    reference_index: int,
    pseudo_count: float = 10.0,
) -> tuple[float, ...]:
    """Despacha para o estimador de swing selecionado.

    Args:
        estimator: Estrategia de estimacao.
        valid_votes: Votos validos por secao observada.
        historical_shares: Shares historicos por secao observada (n, k).
        observed_totals: Votos observados agregados por grupo (k,).
        reference_index: Indice do grupo de referencia.
        pseudo_count: Pseudo-contagem de regularizacao.

    Returns:
        Tupla com ``delta_k`` por grupo.

    Raises:
        ValidationError: Se as entradas forem inconsistentes.
        InvariantViolationError: Se a calibracao nao convergir.
    """
    if estimator is SwingEstimator.AGGREGATE:
        return aggregate_logratio_swing(
            valid_votes,
            historical_shares,
            observed_totals,
            reference_index=reference_index,
            pseudo_count=pseudo_count,
        )
    return calibrated_logratio_swing(
        valid_votes,
        historical_shares,
        observed_totals,
        reference_index=reference_index,
        pseudo_count=pseudo_count,
    )


__all__ = [
    "SwingEstimator",
    "aggregate_logratio_swing",
    "calibrated_logratio_swing",
    "estimate_logratio_swing",
]
