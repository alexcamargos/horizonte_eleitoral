"""Simulador vetorizado de Monte Carlo para projecao eleitoral e intervalos de incerteza."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from horizonte_eleitoral.domain.enums import MatchQuality
from horizonte_eleitoral.models import HierarchicalBayesianModel
from horizonte_eleitoral.models.base import PendingSection, SectionObservation
from horizonte_eleitoral.models.hierarchical import (
    QUALITY_VARIANCE_MULTIPLIER,
    REGIONS_BY_UF,
)


@dataclass(frozen=True, slots=True)
class SimulationSummary:
    """Sumario estatistico com intervalos preditivos de 90% e probabilidade de 2o turno.

    Attributes:
        projected_mean_shares: Media dos shares projetados por grupo [0, 1].
        q05_shares: Limite inferior do intervalo preditivo de 90% (quantil 5%).
        q50_shares: Mediana dos shares projetados (quantil 50%).
        q95_shares: Limite superior do intervalo preditivo de 90% (quantil 95%).
        projected_mean_votes: Total medio absoluto de votos projetados por grupo.
        observed_shares: Participacao observada ate o instante atual.
        second_round_probability: Fracao dos sorteios onde nenhum grupo supera 50% dos votos.
        total_projected_valid_mean: Total medio de votos validos projetados no pais.
        num_draws: Numero de sorteios Monte Carlo realizados.
        seed: Semente pseudo-aleatoria empregada para reproducibilidade.
    """

    projected_mean_shares: tuple[tuple[str, float], ...]
    q05_shares: tuple[tuple[str, float], ...]
    q50_shares: tuple[tuple[str, float], ...]
    q95_shares: tuple[tuple[str, float], ...]
    projected_mean_votes: tuple[tuple[str, int], ...]
    observed_shares: tuple[tuple[str, float], ...]
    second_round_probability: float
    total_projected_valid_mean: int
    num_draws: int
    seed: int


class MonteCarloSimulator:
    """Motor de simulacao preditiva com propagacao de incerteza hierarquica macro."""

    def __init__(self, num_draws: int = 2000, seed: int = 42) -> None:
        """Inicializa o simulador com quantidade de draws e semente deterministica.

        Args:
            num_draws: Numero de repeticoes Monte Carlo (padrao: 2000).
            seed: Semente inteira para garantir reproducibilidade deterministica.

        Returns:
            None.

        Raises:
            None.
        """
        self._num_draws = num_draws
        self._seed = seed

    def simulate(
        self,
        *,
        observations: list[SectionObservation],
        pending: list[PendingSection],
        model: HierarchicalBayesianModel,
        groups: tuple[str, ...] = ("PT", "PL", "OUTROS"),
        match_qualities: dict[str, MatchQuality] | None = None,
    ) -> SimulationSummary:
        """Executa a simulacao completa vetorizada sem vazamento temporal de dados.

        A incerteza preditiva e propagada nos niveis macro (nacional e estadual)
        com base na fracao de eleitorado ainda pendente e na quantidade de secoes
        ja apuradas, preservando intervalos de confianca estatisticamente validos.

        Args:
            observations: Secoes observadas ate o marco atual.
            pending: Secoes eleitorais ainda pendentes de totalizacao.
            model: Instancia do modelo hierarquico para extracao de efeitos.
            groups: Grupos partidarios avaliados no pleito.
            match_qualities: Mapeamento opcional de qualidade de pareamento historico.

        Returns:
            SimulationSummary contendo estimativas centrais e intervalos preditivos de 90%.

        Raises:
            None.
        """
        rng = np.random.default_rng(self._seed)
        qualities_map = match_qualities or {}

        # 1. Totalizacao exata dos votos ja observados
        obs_votes_dict: dict[str, int] = {g: 0 for g in groups}
        total_obs_valid = 0
        obs_count_by_uf: dict[str, int] = {}

        for obs in observations:
            total_obs_valid += obs.valid_votes
            d = dict(obs.group_votes)
            for g in groups:
                obs_votes_dict[g] += d.get(g, 0)
            obs_count_by_uf[obs.state] = obs_count_by_uf.get(obs.state, 0) + 1

        obs_shares_dict = {
            g: (obs_votes_dict[g] / total_obs_valid if total_obs_valid > 0 else 1.0 / len(groups))
            for g in groups
        }

        # Se nao ha secoes pendentes, o resultado e deterministico (ja 100% totalizado)
        if not pending:
            obs_tuple = tuple(
                sorted(((g, round(obs_shares_dict[g], 6)) for g in groups), key=lambda x: x[0])
            )
            votes_tuple = tuple(
                sorted(((g, obs_votes_dict[g]) for g in groups), key=lambda x: x[0])
            )
            has_majority = max(obs_shares_dict.values()) > 0.50
            return SimulationSummary(
                projected_mean_shares=obs_tuple,
                q05_shares=obs_tuple,
                q50_shares=obs_tuple,
                q95_shares=obs_tuple,
                projected_mean_votes=votes_tuple,
                observed_shares=obs_tuple,
                second_round_probability=0.0 if has_majority else 1.0,
                total_projected_valid_mean=total_obs_valid,
                num_draws=self._num_draws,
                seed=self._seed,
            )

        # 2. Extracao de efeitos hierarquicos baseados estritamente nas secoes observadas
        delta_nat, delta_reg, delta_uf, delta_muni = model.estimate_effects(observations, groups)
        num_groups = len(groups)

        # 3. Agrupamento das secoes pendentes por estado para aplicacao de incerteza macro
        state_base_pend_votes: dict[str, np.ndarray] = {}
        state_valid_expected: dict[str, float] = {}
        state_quality_sum: dict[str, float] = {}
        state_pend_count: dict[str, int] = {}

        for sec in pending:
            uf = sec.state
            muni = f"{uf}:{sec.municipality_code}"
            reg = REGIONS_BY_UF.get(uf, "OUTRA")
            chosen_delta = (
                delta_muni.get(muni) or delta_uf.get(uf) or delta_reg.get(reg) or delta_nat
            )

            hist_d = dict(sec.historical_shares)
            raw_shares = [
                max(0.0, hist_d.get(g, 1.0 / num_groups) + chosen_delta.get(g, 0.0)) for g in groups
            ]
            sum_raw = sum(raw_shares)
            norm_shares = (
                [x / sum_raw for x in raw_shares]
                if sum_raw > 0.0
                else [1.0 / num_groups for _ in groups]
            )

            valid_exp = sec.electorate * sec.expected_turnout_rate * sec.expected_valid_rate
            mq = qualities_map.get(sec.section_id, MatchQuality.EXACT)
            q_scale = QUALITY_VARIANCE_MULTIPLIER.get(mq, 1.0)

            if uf not in state_base_pend_votes:
                state_base_pend_votes[uf] = np.zeros(num_groups, dtype=np.float64)
                state_valid_expected[uf] = 0.0
                state_quality_sum[uf] = 0.0
                state_pend_count[uf] = 0

            for j in range(num_groups):
                state_base_pend_votes[uf][j] += valid_exp * norm_shares[j]
            state_valid_expected[uf] += valid_exp
            state_quality_sum[uf] += q_scale
            state_pend_count[uf] += 1

        unique_states = sorted(state_base_pend_votes.keys())
        num_states = len(unique_states)

        # Fracao de apuracao pendente no nivel nacional
        tot_obs_count = len(observations)
        tot_pend_count = len(pending)
        p_nat_pend = tot_pend_count / max(tot_pend_count + tot_obs_count, 1)

        # Incerteza do swing macro nacional: escala com a fracao nao apurada
        sigma_nat = 0.012 * p_nat_pend
        nat_noise_raw = rng.normal(0.0, max(sigma_nat, 1e-6), size=(self._num_draws, num_groups))
        nat_noise = nat_noise_raw - np.mean(nat_noise_raw, axis=1, keepdims=True)

        state_sd = np.zeros(num_states, dtype=np.float64)
        state_base_mat = np.zeros((num_states, num_groups), dtype=np.float64)
        state_vexp_vec = np.zeros(num_states, dtype=np.float64)

        for i, uf in enumerate(unique_states):
            n_obs = obs_count_by_uf.get(uf, 0)
            cnt_p = state_pend_count[uf]
            q_avg = state_quality_sum[uf] / max(cnt_p, 1)
            p_u_pend = cnt_p / max(cnt_p + n_obs, 1)

            # Incerteza posterior do estado baseada na amostra observada e no eleitorado pendente
            state_sd[i] = (0.025 / np.sqrt(n_obs / 20.0 + 1.0)) * p_u_pend * q_avg
            state_base_mat[i] = state_base_pend_votes[uf]
            state_vexp_vec[i] = state_valid_expected[uf]

        # Sorteio de perturbacao por estado centrado (soma zero entre grupos)
        st_noise_raw = (
            rng.normal(0.0, 1.0, size=(self._num_draws, num_states, num_groups))
            * state_sd[None, :, None]
        )
        st_noise = st_noise_raw - np.mean(st_noise_raw, axis=2, keepdims=True)

        # Fusao da incerteza nacional com a incerteza especifica do estado
        total_shift = nat_noise[:, None, :] + st_noise

        # Votos simulados para o conjunto de secoes pendentes de cada estado
        sim_pend_by_state = np.maximum(
            0.0,
            state_base_mat[None, :, :] + state_vexp_vec[None, :, None] * total_shift,
        )
        s_state = np.sum(sim_pend_by_state, axis=2, keepdims=True)
        sim_pend_by_state = np.where(
            s_state > 0.0,
            sim_pend_by_state * (state_vexp_vec[None, :, None] / s_state),
            state_base_mat[None, :, :],
        )
        pending_votes_by_group = np.sum(sim_pend_by_state, axis=1)

        # 4. Soma com os votos observados (estritamente imutaveis em todos os draws)
        obs_votes_arr = np.array([obs_votes_dict[g] for g in groups], dtype=np.float64)
        total_votes_sampled = pending_votes_by_group + obs_votes_arr[None, :]

        total_valid_per_draw = np.sum(total_votes_sampled, axis=-1, keepdims=True)
        final_shares_sampled = total_votes_sampled / np.maximum(total_valid_per_draw, 1.0)

        # 5. Consolidacao estatistica dos quantis e medias
        mean_shares = np.mean(final_shares_sampled, axis=0)
        q05 = np.percentile(final_shares_sampled, 5, axis=0)
        q50 = np.percentile(final_shares_sampled, 50, axis=0)
        q95 = np.percentile(final_shares_sampled, 95, axis=0)
        mean_votes = np.mean(total_votes_sampled, axis=0)
        mean_total_valid = int(round(float(np.mean(total_valid_per_draw))))

        # Segundo turno: proporcao de cenarios onde nenhum candidato supera 50% dos votos validos
        max_shares_per_draw = np.max(final_shares_sampled, axis=1)
        second_round_prob = float(np.mean(max_shares_per_draw <= 0.50))

        return SimulationSummary(
            projected_mean_shares=tuple(
                sorted(
                    ((groups[j], round(float(mean_shares[j]), 6)) for j in range(num_groups)),
                    key=lambda x: x[0],
                )
            ),
            q05_shares=tuple(
                sorted(
                    ((groups[j], round(float(q05[j]), 6)) for j in range(num_groups)),
                    key=lambda x: x[0],
                )
            ),
            q50_shares=tuple(
                sorted(
                    ((groups[j], round(float(q50[j]), 6)) for j in range(num_groups)),
                    key=lambda x: x[0],
                )
            ),
            q95_shares=tuple(
                sorted(
                    ((groups[j], round(float(q95[j]), 6)) for j in range(num_groups)),
                    key=lambda x: x[0],
                )
            ),
            projected_mean_votes=tuple(
                sorted(
                    ((groups[j], int(round(float(mean_votes[j])))) for j in range(num_groups)),
                    key=lambda x: x[0],
                )
            ),
            observed_shares=tuple(
                sorted(((g, round(obs_shares_dict[g], 6)) for g in groups), key=lambda x: x[0])
            ),
            second_round_probability=round(second_round_prob, 4),
            total_projected_valid_mean=mean_total_valid,
            num_draws=self._num_draws,
            seed=self._seed,
        )
