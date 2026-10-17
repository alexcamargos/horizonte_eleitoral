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
    """

    def __init__(self, pseudo_count: float = 10.0, reference_group: str = "OUTROS") -> None:
        """Inicializa o modelo com pseudo-contagens e grupo base.

        Args:
            pseudo_count: Regularizacao para evitar log de zero.
            reference_group: Grupo usado como denominador nas razoes logaritmicas.
        """
        self._pseudo_count = pseudo_count
        self._ref_group = reference_group

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
        """
        obs_votes, obs_shares, _ = _compute_observed_totals(observations, groups)

        # Base historica agregada DAS MESMAS secoes observadas
        hist_in_obs: dict[str, float] = {g: 0.0 for g in groups}
        for obs in observations:
            h_dict = dict(obs.historical_shares)
            for g in groups:
                hist_in_obs[g] += obs.valid_votes * h_dict.get(g, 1.0 / len(groups))

        # Calcula swing nacional em log-space
        delta: dict[str, float] = {g: 0.0 for g in groups}
        ref_obs = obs_votes.get(self._ref_group, 0) + self._pseudo_count
        ref_hist = hist_in_obs.get(self._ref_group, 0.0) + self._pseudo_count

        if ref_obs > 0 and ref_hist > 0:
            for g in groups:
                y_g = obs_votes.get(g, 0) + self._pseudo_count
                b_g = hist_in_obs.get(g, 0.0) + self._pseudo_count
                delta[g] = math.log(y_g / ref_obs) - math.log(b_g / ref_hist)

        proj_votes: dict[str, float] = {g: float(obs_votes[g]) for g in groups}

        # Aplica swing as secoes pendentes
        for sec in pending:
            valid_expected = sec.electorate * sec.expected_turnout_rate * sec.expected_valid_rate
            hist_dict = dict(sec.historical_shares)

            # Softmax estabilizada numericamente: p[k] = b[k] * exp(delta[k]) / sum(...)
            unnorm_p: dict[str, float] = {}
            for g in groups:
                b_k = hist_dict.get(g, 1.0 / len(groups))
                unnorm_p[g] = b_k * math.exp(delta[g])

            denom = sum(unnorm_p.values())
            for g in groups:
                p_k = unnorm_p[g] / denom
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
    """Baseline 4: Swing por UF com Encolhimento (Shrinkage).

    Combina a evidencia local da UF com o swing nacional por meio de shrinkage.
    """

    def __init__(
        self,
        pseudo_count: float = 10.0,
        shrinkage_k: float = 30.0,
        reference_group: str = "OUTROS",
    ) -> None:
        """Inicializa o modelo com parametros de suavizacao.

        Args:
            pseudo_count: Regularizacao para log-odds.
            shrinkage_k: Constante K que define a forca de atracao ao nacional.
            reference_group: Grupo de referencia para log-odds.
        """
        self._pseudo_count = pseudo_count
        self._shrinkage_k = shrinkage_k
        self._ref_group = reference_group

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
        """
        obs_votes, obs_shares, _ = _compute_observed_totals(observations, groups)

        # 1. Swing Nacional
        hist_nat: dict[str, float] = {g: 0.0 for g in groups}
        for obs in observations:
            h_dict = dict(obs.historical_shares)
            for g in groups:
                hist_nat[g] += obs.valid_votes * h_dict.get(g, 1.0 / len(groups))

        delta_nat: dict[str, float] = {g: 0.0 for g in groups}
        ref_obs_nat = obs_votes.get(self._ref_group, 0) + self._pseudo_count
        ref_hist_nat = hist_nat.get(self._ref_group, 0.0) + self._pseudo_count
        if ref_obs_nat > 0 and ref_hist_nat > 0:
            for g in groups:
                y_g = obs_votes.get(g, 0) + self._pseudo_count
                b_g = hist_nat.get(g, 0.0) + self._pseudo_count
                delta_nat[g] = math.log(y_g / ref_obs_nat) - math.log(b_g / ref_hist_nat)

        # 2. Swings por UF
        uf_obs_votes: dict[str, dict[str, int]] = defaultdict(lambda: {g: 0 for g in groups})
        uf_hist_votes: dict[str, dict[str, float]] = defaultdict(lambda: {g: 0.0 for g in groups})
        uf_count: dict[str, int] = defaultdict(int)

        for obs in observations:
            uf = obs.state
            uf_count[uf] += 1
            obs_dict = dict(obs.group_votes)
            h_dict = dict(obs.historical_shares)
            for g in groups:
                uf_obs_votes[uf][g] += obs_dict.get(g, 0)
                uf_hist_votes[uf][g] += obs.valid_votes * h_dict.get(g, 1.0 / len(groups))

        uf_delta: dict[str, dict[str, float]] = {}
        for uf, count in uf_count.items():
            uf_delta[uf] = {}
            ref_obs_uf = uf_obs_votes[uf].get(self._ref_group, 0) + self._pseudo_count
            ref_hist_uf = uf_hist_votes[uf].get(self._ref_group, 0.0) + self._pseudo_count
            lambda_uf = count / (count + self._shrinkage_k)

            for g in groups:
                y_uf = uf_obs_votes[uf].get(g, 0) + self._pseudo_count
                b_uf = uf_hist_votes[uf].get(g, 0.0) + self._pseudo_count
                raw_delta_uf = math.log(y_uf / ref_obs_uf) - math.log(b_uf / ref_hist_uf)
                # Encolhimento: lambda * local + (1 - lambda) * nacional
                uf_delta[uf][g] = lambda_uf * raw_delta_uf + (1.0 - lambda_uf) * delta_nat[g]

        # 3. Projecao das secoes pendentes
        proj_votes: dict[str, float] = {g: float(obs_votes[g]) for g in groups}

        for sec in pending:
            valid_expected = sec.electorate * sec.expected_turnout_rate * sec.expected_valid_rate
            hist_dict = dict(sec.historical_shares)
            chosen_delta = uf_delta.get(sec.state, delta_nat)

            unnorm_p: dict[str, float] = {}
            for g in groups:
                b_k = hist_dict.get(g, 1.0 / len(groups))
                unnorm_p[g] = b_k * math.exp(chosen_delta.get(g, 0.0))

            denom = sum(unnorm_p.values())
            for g in groups:
                p_k = unnorm_p[g] / denom
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
