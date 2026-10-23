"""Implementacao dos 4 modelos de referencia (baselines) para projecao eleitoral."""

from __future__ import annotations

import math
from collections import defaultdict

from horizonte_eleitoral.models.base import (
    ForecastModel,
    ForecastResult,
    PendingSection,
    SectionObservation,
)
from horizonte_eleitoral.models.swing import SwingEstimator, estimate_logratio_swing


def _compute_observed_totals(
    observations: list[SectionObservation],
    groups: tuple[str, ...],
) -> tuple[dict[str, int], dict[str, float], int]:
    """Calcula os totais e percentuais observados ate o momento.

    Args:
        observations: Lista de secoes observadas.
        groups: Grupos eleitorais avaliados.

    Returns:
        Tupla com (votos por grupo, shares por grupo, total de votos validos).
    """
    votes: dict[str, int] = {g: 0 for g in groups}
    total_valid = 0
    for obs in observations:
        total_valid += obs.valid_votes
        obs_dict = dict(obs.group_votes)
        for g in groups:
            votes[g] += obs_dict.get(g, 0)

    if total_valid == 0:
        uniform_share = 1.0 / len(groups)
        shares = {g: uniform_share for g in groups}
    else:
        shares = {g: votes[g] / total_valid for g in groups}

    return votes, shares, total_valid


def _estimate_swing(
    observations: list[SectionObservation],
    groups: tuple[str, ...],
    reference_group: str,
    pseudo_count: float,
    estimator: SwingEstimator,
) -> dict[str, float]:
    """Estima o swing em log-ratio de um conjunto de secoes observadas.

    Args:
        observations: Secoes observadas do recorte (nacional ou UF).
        groups: Grupos eleitorais avaliados.
        reference_group: Grupo de referencia (delta fixado em zero).
        pseudo_count: Pseudo-contagem de regularizacao.
        estimator: Estrategia de estimacao do swing.

    Returns:
        Dicionario grupo -> delta; zeros se nao houver observacoes ou referencia.

    Raises:
        InvariantViolationError: Se a calibracao nao convergir.
    """
    if not observations or reference_group not in groups:
        return {g: 0.0 for g in groups}
    default_share = 1.0 / len(groups)
    valid: list[float] = []
    hist_rows: list[list[float]] = []
    totals = [0.0 for _ in groups]
    for obs in observations:
        valid.append(float(obs.valid_votes))
        h_dict = dict(obs.historical_shares)
        hist_rows.append([float(h_dict.get(g, default_share)) for g in groups])
        o_dict = dict(obs.group_votes)
        for idx, g in enumerate(groups):
            totals[idx] += float(o_dict.get(g, 0))
    delta = estimate_logratio_swing(
        estimator,
        valid,
        hist_rows,
        totals,
        reference_index=groups.index(reference_group),
        pseudo_count=pseudo_count,
    )
    return dict(zip(groups, delta, strict=True))


class RawCountBaseline(ForecastModel):
    """Baseline 1: Apurado Bruto.

    Representa a participacao observada ate o momento das secoes apuradas.
    Nao projeta votos para as secoes pendentes.
    """

    def predict(
        self,
        *,
        observations: list[SectionObservation],
        pending: list[PendingSection],
        groups: tuple[str, ...] = ("PT", "PL", "OUTROS"),
    ) -> ForecastResult:
        """Retorna o apurado bruto como previsao pontual.

        Args:
            observations: Secoes observadas.
            pending: Secoes pendentes (ignoradas por este baseline).
            groups: Grupos avaliados.

        Returns:
            ForecastResult contendo o percentual apurado.
        """
        obs_votes, obs_shares, total_valid = _compute_observed_totals(observations, groups)

        shares_tuple = tuple(
            sorted(((g, round(obs_shares[g], 6)) for g in groups), key=lambda x: x[0])
        )
        votes_tuple = tuple(sorted(((g, obs_votes[g]) for g in groups), key=lambda x: x[0]))

        return ForecastResult(
            model_name="baseline_1_raw_count",
            projected_shares=shares_tuple,
            projected_votes=votes_tuple,
            observed_shares=shares_tuple,
            total_projected_valid=total_valid,
        )


class HistoricalNoSwingBaseline(ForecastModel):
    """Baseline 2: Base Historica sem Swing.

    Aplica as participações historicas de 2022 diretamente as secoes pendentes,
    mantendo intactos os votos ja observados.
    """

    def predict(
        self,
        *,
        observations: list[SectionObservation],
        pending: list[PendingSection],
        groups: tuple[str, ...] = ("PT", "PL", "OUTROS"),
    ) -> ForecastResult:
        """Projeta secoes pendentes usando seu share historico puro de 2022.

        Args:
            observations: Secoes observadas.
            pending: Secoes pendentes a projetar.
            groups: Grupos avaliados.

        Returns:
            ForecastResult com consolidado projetado.
        """
        obs_votes, obs_shares, _ = _compute_observed_totals(observations, groups)
        proj_votes: dict[str, float] = {g: float(obs_votes[g]) for g in groups}

        for sec in pending:
            valid_expected = sec.electorate * sec.expected_turnout_rate * sec.expected_valid_rate
            hist_dict = dict(sec.historical_shares)
            for g in groups:
                proj_votes[g] += valid_expected * hist_dict.get(g, 1.0 / len(groups))

        total_proj = sum(proj_votes.values())
        if total_proj > 0:
            proj_shares = {g: proj_votes[g] / total_proj for g in groups}
        else:
            proj_shares = {g: 1.0 / len(groups) for g in groups}

        return ForecastResult(
            model_name="baseline_2_historical_no_swing",
            projected_shares=tuple(
                sorted(((g, round(proj_shares[g], 6)) for g in groups), key=lambda x: x[0])
            ),
            projected_votes=tuple(
                sorted(((g, int(round(proj_votes[g]))) for g in groups), key=lambda x: x[0])
            ),
            observed_shares=tuple(
                sorted(((g, round(obs_shares[g], 6)) for g in groups), key=lambda x: x[0])
            ),
            total_projected_valid=int(round(total_proj)),
        )


class NationalSwingBaseline(ForecastModel):
    """Baseline 3: Swing Nacional Composicional.

    Estima o deslocamento médio nacional em log-ratios sobre as seções apuradas
    em relação ao seu perfil historico correspondente, aplicando-o as secoes pendentes.
    Por padrao usa o estimador calibrado, que reproduz os totais observados quando
    aplicado secao a secao (ver ``horizonte_eleitoral.models.swing``).
    """

    def __init__(
        self,
        pseudo_count: float = 10.0,
        reference_group: str = "OUTROS",
        swing_estimator: SwingEstimator = SwingEstimator.CALIBRATED,
    ) -> None:
        """Inicializa o modelo com pseudo-contagens e grupo base.

        Args:
            pseudo_count: Regularizacao para evitar log de zero.
            reference_group: Grupo usado como denominador nas razoes logaritmicas.
            swing_estimator: Estimador do swing (calibrado por padrao; agregado e legado).
        """
        self._pseudo_count = pseudo_count
        self._ref_group = reference_group
        self._swing_estimator = swing_estimator

    def predict(
        self,
        *,
        observations: list[SectionObservation],
        pending: list[PendingSection],
        groups: tuple[str, ...] = ("PT", "PL", "OUTROS"),
    ) -> ForecastResult:
        """Calcula o swing nacional e projeta as secoes pendentes via softmax.

        Args:
            observations: Secoes observadas.
            pending: Secoes pendentes.
            groups: Grupos avaliados.

        Returns:
            ForecastResult com projecao ajustada por swing nacional.

        Raises:
            InvariantViolationError: Se a calibracao do swing nao convergir.
        """
        obs_votes, obs_shares, _ = _compute_observed_totals(observations, groups)

        # Swing nacional em log-space estimado sobre as MESMAS secoes observadas
        delta = _estimate_swing(
            observations, groups, self._ref_group, self._pseudo_count, self._swing_estimator
        )

        proj_votes: dict[str, float] = {g: float(obs_votes[g]) for g in groups}

        max_delta_nat = max(delta.values(), default=0.0)

        # Aplica swing as secoes pendentes
        for sec in pending:
            valid_expected = sec.electorate * sec.expected_turnout_rate * sec.expected_valid_rate
            hist_dict = dict(sec.historical_shares)

            # Softmax estabilizada numericamente: p[k] = b[k] * exp(delta[k] - c) / sum(...)
            unnorm_p: dict[str, float] = {}
            for g in groups:
                b_k = hist_dict.get(g, 1.0 / len(groups))
                unnorm_p[g] = b_k * math.exp(delta[g] - max_delta_nat)

            denom = sum(unnorm_p.values())
            for g in groups:
                p_k = (unnorm_p[g] / denom) if denom > 0.0 else (1.0 / len(groups))
                proj_votes[g] += valid_expected * p_k

        total_proj = sum(proj_votes.values())
        proj_shares = (
            {g: proj_votes[g] / total_proj for g in groups}
            if total_proj > 0
            else {g: 1.0 / len(groups) for g in groups}
        )

        return ForecastResult(
            model_name="baseline_3_national_swing",
            projected_shares=tuple(
                sorted(((g, round(proj_shares[g], 6)) for g in groups), key=lambda x: x[0])
            ),
            projected_votes=tuple(
                sorted(((g, int(round(proj_votes[g]))) for g in groups), key=lambda x: x[0])
            ),
            observed_shares=tuple(
                sorted(((g, round(obs_shares[g], 6)) for g in groups), key=lambda x: x[0])
            ),
            total_projected_valid=int(round(total_proj)),
        )


class UFSwingWithShrinkageBaseline(ForecastModel):
    """Baseline 4: Swing por UF com Encolhimento (Shrinkage) por Credibilidade.

    Combina a evidencia local da UF com o swing nacional por meio do fator de
    credibilidade ``lambda_u = N_u / (N_u + K)``, em que ``N_u`` e o numero de
    secoes observadas na UF e ``K`` e uma pseudo-contagem fixa. Equivale a media
    a posteriori de um modelo normal-normal com razao de variancias
    ``sigma^2 / tau^2 = K`` fixada a priori. Nao e um estimador de James-Stein
    nem Empirical Bayes, pois ``K`` nao e estimado da dispersao entre UFs.
    Os swings nacional e estaduais usam por padrao o estimador calibrado
    (ver ``horizonte_eleitoral.models.swing``).
    """

    def __init__(
        self,
        pseudo_count: float = 10.0,
        shrinkage_k: float = 30.0,
        reference_group: str = "OUTROS",
        swing_estimator: SwingEstimator = SwingEstimator.CALIBRATED,
    ) -> None:
        """Inicializa o modelo com parametros de suavizacao.

        Args:
            pseudo_count: Regularizacao para log-odds.
            shrinkage_k: Pseudo-contagem fixa K (em secoes) que define a forca de
                atracao ao swing nacional; nao e estimada dos dados.
            reference_group: Grupo de referencia para log-odds.
            swing_estimator: Estimador do swing (calibrado por padrao; agregado e legado).
        """
        self._pseudo_count = pseudo_count
        self._shrinkage_k = shrinkage_k
        self._ref_group = reference_group
        self._swing_estimator = swing_estimator

    def predict(
        self,
        *,
        observations: list[SectionObservation],
        pending: list[PendingSection],
        groups: tuple[str, ...] = ("PT", "PL", "OUTROS"),
    ) -> ForecastResult:
        """Calcula swings estaduais encolhidos em direcao ao nacional e projeta secoes pendentes.

        Args:
            observations: Secoes observadas.
            pending: Secoes pendentes.
            groups: Grupos avaliados.

        Returns:
            ForecastResult com projecao balanceada por estado.

        Raises:
            InvariantViolationError: Se a calibracao do swing nao convergir.
        """
        obs_votes, obs_shares, _ = _compute_observed_totals(observations, groups)

        # 1. Swing Nacional
        delta_nat = _estimate_swing(
            observations, groups, self._ref_group, self._pseudo_count, self._swing_estimator
        )

        # 2. Swings por UF
        obs_by_uf: dict[str, list[SectionObservation]] = defaultdict(list)
        for obs in observations:
            obs_by_uf[obs.state].append(obs)

        uf_delta: dict[str, dict[str, float]] = {}
        for uf, uf_obs in obs_by_uf.items():
            count = len(uf_obs)
            lambda_uf = count / (count + self._shrinkage_k)
            raw_delta_uf = _estimate_swing(
                uf_obs, groups, self._ref_group, self._pseudo_count, self._swing_estimator
            )
            # Encolhimento: lambda * local + (1 - lambda) * nacional
            uf_delta[uf] = {
                g: lambda_uf * raw_delta_uf[g] + (1.0 - lambda_uf) * delta_nat[g] for g in groups
            }

        # 3. Projecao das secoes pendentes
        proj_votes: dict[str, float] = {g: float(obs_votes[g]) for g in groups}

        for sec in pending:
            valid_expected = sec.electorate * sec.expected_turnout_rate * sec.expected_valid_rate
            hist_dict = dict(sec.historical_shares)
            chosen_delta = uf_delta.get(sec.state, delta_nat)
            max_delta_uf = max((chosen_delta.get(g, 0.0) for g in groups), default=0.0)

            unnorm_p: dict[str, float] = {}
            for g in groups:
                b_k = hist_dict.get(g, 1.0 / len(groups))
                unnorm_p[g] = b_k * math.exp(chosen_delta.get(g, 0.0) - max_delta_uf)

            denom = sum(unnorm_p.values())
            for g in groups:
                p_k = (unnorm_p[g] / denom) if denom > 0.0 else (1.0 / len(groups))
                proj_votes[g] += valid_expected * p_k

        total_proj = sum(proj_votes.values())
        proj_shares = (
            {g: proj_votes[g] / total_proj for g in groups}
            if total_proj > 0
            else {g: 1.0 / len(groups) for g in groups}
        )

        return ForecastResult(
            model_name="baseline_4_uf_swing_shrinkage",
            projected_shares=tuple(
                sorted(((g, round(proj_shares[g], 6)) for g in groups), key=lambda x: x[0])
            ),
            projected_votes=tuple(
                sorted(((g, int(round(proj_votes[g]))) for g in groups), key=lambda x: x[0])
            ),
            observed_shares=tuple(
                sorted(((g, round(obs_shares[g], 6)) for g in groups), key=lambda x: x[0])
            ),
            total_projected_valid=int(round(total_proj)),
        )
