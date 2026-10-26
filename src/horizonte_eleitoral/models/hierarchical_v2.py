"""Modelo hierarquico multinivel Versao 2 (HORIZON-MRP) - MODELO PADRAO DO PROJETO.

HORIZON-MRP (Hierarchical Optimal Regression & Inferred Zonal Outcomes Network).
Incorpora o indice de elasticidade historica municipal (eleicoes 2018-2022)
para modular o encolhimento bayesiano (shrinkage) municipal em relacao ao estadual.
Consolidado como modelo preditivo ativo padrao apos validacao em 100% da base de 2026.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from horizonte_eleitoral.historical.elasticity import MunicipalElasticityIndex
from horizonte_eleitoral.models.base import (
    ForecastModel,
    ForecastResult,
    PendingSection,
    SectionObservation,
)
from horizonte_eleitoral.models.hierarchical import (
    REGIONAL_ELECTORATE_WEIGHTS,
    REGIONS_BY_UF,
)
from horizonte_eleitoral.models.swing import (
    SwingEstimator,
    aggregate_logratio_swing,
    calibrated_logratio_swing,
)

_DEFAULT_ELASTICITY_INDEX: MunicipalElasticityIndex | None = None


def get_default_elasticity_index() -> MunicipalElasticityIndex | None:
    """Carrega ou retorna a instancia em cache do indice de elasticidade 2018-2022.

    Returns:
        Instancia de MunicipalElasticityIndex carregada ou None se indisponivel.
    """
    global _DEFAULT_ELASTICITY_INDEX
    if _DEFAULT_ELASTICITY_INDEX is not None:
        return _DEFAULT_ELASTICITY_INDEX

    default_path = Path("data/real/elasticity_2018_2022.parquet")
    if default_path.exists():
        try:
            _DEFAULT_ELASTICITY_INDEX = MunicipalElasticityIndex.load_parquet(default_path)
            return _DEFAULT_ELASTICITY_INDEX
        except Exception:
            return None
    return None


class HierarchicalBayesianModelV2(ForecastModel):
    """Modelo hierarquico multinivel Versao 2 (v2) - MODELO PADRAO DO PROJETO.

    Estima efeitos eleitorais com swing log-ratio calibrado via Newton-Raphson
    e encolhimento bayesiano multinivel (MRP Nacional -> Regional -> Estadual),
    eliminando o vies de agregacao nao-linear de Jensen e garantindo reconstrucao
    exata dos votos observados sem distorcoes aditivas no simplex.
    """

    def __init__(
        self,
        elasticity_index: MunicipalElasticityIndex | None = None,
        pseudo_count: float = 1.0,
        shrinkage_region: float = 30.0,
        shrinkage_uf: float = 20.0,
        shrinkage_muni: float | None = None,
        elasticity_sensitivity: float = 2.0,
        reference_group: str = "OUTROS",
        auto_load_default: bool = True,
        estimator: SwingEstimator = SwingEstimator.CALIBRATED,
    ) -> None:
        """Inicializa o modelo hierarquico v2 com swing log-ratio calibrado e encolhimento MRP.

        Args:
            elasticity_index: Indice opcional de elasticidade historica 2018-2022.
            pseudo_count: Constante de regularizacao numerica para celulas vazias.
            shrinkage_region: Constante K de encolhimento regional para o nacional MRP.
            shrinkage_uf: Constante K de encolhimento estadual para o regional.
            shrinkage_muni: Constante K de encolhimento municipal (None desativa nivel municipal).
            elasticity_sensitivity: Sensibilidade de ajuste do encolhimento a volatilidade.
            reference_group: Grupo de referencia para log-odds/swings.
            auto_load_default: Se True e elasticity_index for None, tenta carregar indice padrao.
            estimator: Estimador de swing (CALIBRATED via Newton-Raphson ou AGGREGATE legado).

        Returns:
            None.

        Raises:
            None.
        """
        if (
            elasticity_index is None
            and auto_load_default
            and shrinkage_muni is not None
            and shrinkage_muni > 0
        ):
            self._elasticity_index = get_default_elasticity_index()
        else:
            self._elasticity_index = elasticity_index
        self._pseudo_count = pseudo_count
        self._k_reg = shrinkage_region
        self._k_uf = shrinkage_uf
        self._k_muni = shrinkage_muni
        self._sensitivity = elasticity_sensitivity
        self._ref_group = reference_group
        self._estimator = estimator

    def estimate_effects(
        self,
        observations: Sequence[SectionObservation],
        groups: tuple[str, ...],
    ) -> tuple[
        dict[str, float],
        dict[str, dict[str, float]],
        dict[str, dict[str, float]],
        dict[str, dict[str, float]],
    ]:
        """Estima swings log-ratio multinivel com ponderacao regional MRP e shrinkage bayesiano.

        Args:
            observations: Sequencia de secoes eleitorais ja totalizadas e observadas.
            groups: Tupla contendo codigos canonicos dos grupos politicos avaliados.

        Returns:
            Tupla contendo:
                - delta_nacional: Dicionario mapeando cada grupo ao shift log-ratio nacional.
                - deltas_regionais: Dicionario mapeando regiao a shifts partidarios.
                - deltas_uf: Dicionario mapeando UF a shifts partidarios.
                - deltas_municipais: Dicionario mapeando 'UF:codigo_municipio' a shifts.

        Raises:
            None.
        """
        if not observations:
            empty_g = {g: 0.0 for g in groups}
            return empty_g, {}, {}, {}

        num_groups = len(groups)
        ref_idx = groups.index(self._ref_group) if self._ref_group in groups else num_groups - 1

        # 1. Agrupamento de secoes observadas por regiao, UF e municipio
        reg_valid: dict[str, list[float]] = defaultdict(list)
        reg_hist: dict[str, list[list[float]]] = defaultdict(list)
        reg_obs_votes: dict[str, np.ndarray] = defaultdict(
            lambda: np.zeros(num_groups, dtype=np.float64)
        )
        reg_count: dict[str, int] = defaultdict(int)

        uf_valid: dict[str, list[float]] = defaultdict(list)
        uf_hist: dict[str, list[list[float]]] = defaultdict(list)
        uf_obs_votes: dict[str, np.ndarray] = defaultdict(
            lambda: np.zeros(num_groups, dtype=np.float64)
        )
        uf_count: dict[str, int] = defaultdict(int)

        muni_valid: dict[str, list[float]] = defaultdict(list)
        muni_hist: dict[str, list[list[float]]] = defaultdict(list)
        muni_obs_votes: dict[str, np.ndarray] = defaultdict(
            lambda: np.zeros(num_groups, dtype=np.float64)
        )
        muni_count: dict[str, int] = defaultdict(int)

        all_valid: list[float] = []
        all_hist: list[list[float]] = []
        all_votes = np.zeros(num_groups, dtype=np.float64)

        for obs in observations:
            uf = obs.state
            reg = REGIONS_BY_UF.get(uf, "OUTRA")
            muni = f"{uf}:{obs.municipality_code}"

            reg_count[reg] += 1
            uf_count[uf] += 1
            if self._k_muni is not None and self._k_muni > 0:
                muni_count[muni] += 1

            v = float(obs.valid_votes)
            all_valid.append(v)
            reg_valid[reg].append(v)
            uf_valid[uf].append(v)
            if self._k_muni is not None and self._k_muni > 0:
                muni_valid[muni].append(v)

            obs_d = dict(obs.group_votes)
            h_d = dict(obs.historical_shares)

            h_row = [float(h_d.get(g, 1.0 / num_groups)) for g in groups]
            y_row = np.array([float(obs_d.get(g, 0)) for g in groups], dtype=np.float64)

            all_hist.append(h_row)
            all_votes += y_row

            reg_hist[reg].append(h_row)
            reg_obs_votes[reg] += y_row

            uf_hist[uf].append(h_row)
            uf_obs_votes[uf] += y_row

            if self._k_muni is not None and self._k_muni > 0:
                muni_hist[muni].append(h_row)
                muni_obs_votes[muni] += y_row

        # Funcao auxiliar para estimar log-ratio swing em um subconjunto
        def _calc_swing(
            v_list: list[float],
            h_list: list[list[float]],
            y_sum: np.ndarray,
        ) -> np.ndarray:
            if not v_list or np.sum(y_sum) <= 0.0:
                return np.zeros(num_groups, dtype=np.float64)
            v_arr = np.asarray(v_list, dtype=np.float64)
            h_arr = np.asarray(h_list, dtype=np.float64)
            if self._estimator == SwingEstimator.CALIBRATED:
                raw_tuple = calibrated_logratio_swing(
                    v_arr,
                    h_arr,
                    y_sum,
                    reference_index=ref_idx,
                    pseudo_count=self._pseudo_count,
                )
            else:
                raw_tuple = aggregate_logratio_swing(
                    v_arr,
                    h_arr,
                    y_sum,
                    reference_index=ref_idx,
                    pseudo_count=self._pseudo_count,
                )
            return np.asarray(raw_tuple, dtype=np.float64)

        # 2. Efeitos Regionais Brutos
        raw_reg: dict[str, np.ndarray] = {
            r: _calc_swing(reg_valid[r], reg_hist[r], reg_obs_votes[r]) for r in reg_count
        }

        # 3. Efeito Nacional Ponderado pela composicao censitaria regional (MRP)
        # Cada regiao observada e encolhida por sua credibilidade amostral
        # lambda_r = N_r / (N_r + K_reg) e ponderada pelo seu peso oficial no eleitorado nacional.
        # As regioes pendentes permanecem ancoradas no prior historico nulo (delta = 0),
        # evitando que os primeiros boletins de uma unica regiao dominem o pais a 100%.
        delta_nat_arr = np.zeros(num_groups, dtype=np.float64)
        for r in reg_count:
            w = REGIONAL_ELECTORATE_WEIGHTS.get(r, 0.01)
            lambda_r = reg_count[r] / (reg_count[r] + self._k_reg)
            delta_nat_arr += w * lambda_r * raw_reg[r]

        delta_nat = {g: float(delta_nat_arr[idx]) for idx, g in enumerate(groups)}

        # 4. Efeitos Regionais com encolhimento bayesiano para o Nacional
        delta_reg: dict[str, dict[str, float]] = {}
        delta_reg_arr: dict[str, np.ndarray] = {}
        for reg, count in reg_count.items():
            lambda_r = count / (count + self._k_reg)
            shrunk_r = lambda_r * raw_reg[reg] + (1.0 - lambda_r) * delta_nat_arr
            delta_reg_arr[reg] = shrunk_r
            delta_reg[reg] = {g: float(shrunk_r[idx]) for idx, g in enumerate(groups)}

        # 5. Efeitos Estaduais com encolhimento para o Regional
        delta_uf: dict[str, dict[str, float]] = {}
        delta_uf_arr: dict[str, np.ndarray] = {}
        for uf, count in uf_count.items():
            reg = REGIONS_BY_UF.get(uf, "OUTRA")
            parent_arr = delta_reg_arr.get(reg, delta_nat_arr)
            raw_u = _calc_swing(uf_valid[uf], uf_hist[uf], uf_obs_votes[uf])
            lambda_u = count / (count + self._k_uf)
            shrunk_u = lambda_u * raw_u + (1.0 - lambda_u) * parent_arr
            delta_uf_arr[uf] = shrunk_u
            delta_uf[uf] = {g: float(shrunk_u[idx]) for idx, g in enumerate(groups)}

        # 6. Efeitos Municipais (opcional se shrinkage_muni for configurado)
        delta_muni: dict[str, dict[str, float]] = {}
        if self._k_muni is not None and self._k_muni > 0:
            for muni, count in muni_count.items():
                uf = muni.split(":")[0]
                parent_arr = delta_uf_arr.get(uf, delta_nat_arr)
                raw_m = _calc_swing(muni_valid[muni], muni_hist[muni], muni_obs_votes[muni])

                vol = 0.05
                if self._elasticity_index is not None:
                    vol = self._elasticity_index.get_volatility(muni, state=uf)

                effective_k_muni = self._k_muni * (1.0 + self._sensitivity * vol)
                lambda_m = count / (count + effective_k_muni)
                shrunk_m = lambda_m * raw_m + (1.0 - lambda_m) * parent_arr
                delta_muni[muni] = {g: float(shrunk_m[idx]) for idx, g in enumerate(groups)}

        return delta_nat, delta_reg, delta_uf, delta_muni

    def predict(
        self,
        *,
        observations: list[SectionObservation],
        pending: list[PendingSection],
        groups: tuple[str, ...] = ("PT", "PL", "OUTROS"),
    ) -> ForecastResult:
        """Gera previsao pontual esperada do modelo hierarquico v2 sobre secoes pendentes.

        Aplica os swings log-ratio estimados as bases historicas das secoes pendentes
        via formulacao multinomial logit (softmax), sem qualquer acesso aos resultados reais.

        Args:
            observations: Secoes observadas ja totalizadas.
            pending: Secoes pendentes de apuracao.
            groups: Grupos partidarios avaliados no escopo.

        Returns:
            ForecastResult com shares projetados, contagens esperadas e participacao observada.

        Raises:
            None.
        """
        delta_nat, delta_reg, delta_uf, delta_muni = self.estimate_effects(observations, groups)

        obs_votes: dict[str, int] = {g: 0 for g in groups}
        total_valid_obs = 0
        for obs in observations:
            total_valid_obs += obs.valid_votes
            d = dict(obs.group_votes)
            for g in groups:
                obs_votes[g] += d.get(g, 0)

        obs_shares = {
            g: (obs_votes[g] / total_valid_obs if total_valid_obs > 0 else 1.0 / len(groups))
            for g in groups
        }
        proj_votes: dict[str, float] = {g: float(obs_votes[g]) for g in groups}

        # Cache de exp(delta) por nivel para evitar recomputacao repetida
        delta_cache: dict[str, np.ndarray] = {}

        def _get_exp_delta(muni_key: str, uf_code: str, reg_code: str) -> np.ndarray:
            if muni_key in delta_cache:
                return delta_cache[muni_key]
            d_dict = (
                delta_muni.get(muni_key)
                or delta_uf.get(uf_code)
                or delta_reg.get(reg_code)
                or delta_nat
            )
            raw_d = np.array([d_dict.get(g, 0.0) for g in groups], dtype=np.float64)
            arr = np.exp(raw_d - np.max(raw_d))
            delta_cache[muni_key] = arr
            return arr

        for sec in pending:
            valid_expected = sec.electorate * sec.expected_turnout_rate * sec.expected_valid_rate
            uf = sec.state
            reg = REGIONS_BY_UF.get(uf, "OUTRA")
            muni = f"{uf}:{sec.municipality_code}"

            exp_d = _get_exp_delta(muni, uf, reg)
            hist_d = dict(sec.historical_shares)
            raw_h = [hist_d.get(g, 1.0 / len(groups)) for g in groups]
            h_vec = np.maximum(np.array(raw_h, dtype=np.float64), 1e-5)

            w = h_vec * exp_d
            sum_w = np.sum(w)
            norm_shares = w / sum_w if sum_w > 0.0 else np.full(len(groups), 1.0 / len(groups))

            for idx, g in enumerate(groups):
                proj_votes[g] += valid_expected * float(norm_shares[idx])

        total_proj = sum(proj_votes.values())
        proj_shares = (
            {g: proj_votes[g] / total_proj for g in groups}
            if total_proj > 0
            else {g: 1.0 / len(groups) for g in groups}
        )

        return ForecastResult(
            model_name="hierarchical_bayesian_composite_v2",
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


# A Versao 2 (HORIZON-MRP) e o modelo padrao ativo do sistema
HierarchicalBayesianModel = HierarchicalBayesianModelV2
HorizonMRP = HierarchicalBayesianModelV2
HorizonMRPModel = HierarchicalBayesianModelV2

__all__ = [
    "HierarchicalBayesianModel",
    "HierarchicalBayesianModelV2",
    "HorizonMRP",
    "HorizonMRPModel",
    "get_default_elasticity_index",
]
