"""Modelo hierarquico multinivel Versao 2 (v2) - MODELO PADRAO DO PROJETO.

Incorpora o indice de elasticidade historica municipal (eleicoes 2018-2022)
para modular o encolhimento bayesiano (shrinkage) municipal em relacao ao estadual.
Consolidado como modelo preditivo ativo padrao apos validacao em 100% da base de 2026.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

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

    Estima efeitos eleitorais parciais com encolhimento bayesiano multinivel (MRP)
    onde o encolhimento municipal e modulado pela volatilidade historica do municipio:
    municipios com alta volatilidade historica (swing alto) aceleram a absorcao da evidencia
    de 2026, enquanto municipios estaveis retem a ancoragem conservadora na base de 2022.
    """

    def __init__(
        self,
        elasticity_index: MunicipalElasticityIndex | None = None,
        pseudo_count: float = 10.0,
        shrinkage_region: float = 30.0,
        shrinkage_uf: float = 20.0,
        shrinkage_muni: float = 10.0,
        elasticity_sensitivity: float = 2.0,
        reference_group: str = "OUTROS",
        auto_load_default: bool = True,
    ) -> None:
        """Inicializa o modelo hierarquico v2 com indice de elasticidade e hiperparametros.

        Args:
            elasticity_index: Indice opcional de elasticidade historica 2018-2022.
            pseudo_count: Constante de regularizacao.
            shrinkage_region: Constante K de encolhimento regional para o nacional.
            shrinkage_uf: Constante K de encolhimento estadual para o regional.
            shrinkage_muni: Constante K base de encolhimento municipal para o estadual.
            elasticity_sensitivity: Sensibilidade de ajuste do encolhimento a volatilidade.
            reference_group: Grupo de referencia para log-odds/swings.
            auto_load_default: Se True e elasticity_index for None, tenta carregar o indice padrao.

        Returns:
            None.

        Raises:
            None.
        """
        if elasticity_index is None and auto_load_default:
            self._elasticity_index = get_default_elasticity_index()
        else:
            self._elasticity_index = elasticity_index
        self._pseudo_count = pseudo_count
        self._k_reg = shrinkage_region
        self._k_uf = shrinkage_uf
        self._k_muni = shrinkage_muni
        self._sensitivity = elasticity_sensitivity
        self._ref_group = reference_group

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
        """Estima swings aditivos com ponderacao regional e shrinkage modulado por elasticidade.

        Args:
            observations: Sequencia de secoes eleitorais ja totalizadas e observadas.
            groups: Tupla contendo codigos canonicos dos grupos politicos avaliados.

        Returns:
            Tupla contendo:
                - delta_nacional: Dicionario mapeando cada grupo ao shift nacional ponderado.
                - deltas_regionais: Dicionario mapeando regiao a shifts partidarios.
                - deltas_uf: Dicionario mapeando UF a shifts partidarios.
                - deltas_municipais: Dicionario mapeando 'UF:codigo_municipio' a shifts.

        Raises:
            None.
        """
        if not observations:
            empty_g = {g: 0.0 for g in groups}
            return empty_g, {}, {}, {}

        # 1. Agregacoes em todos os niveis a partir dos dados observados
        nat_obs: dict[str, float] = {g: 0.0 for g in groups}
        nat_hist: dict[str, float] = {g: 0.0 for g in groups}

        reg_obs: dict[str, dict[str, float]] = defaultdict(lambda: {g: 0.0 for g in groups})
        reg_hist: dict[str, dict[str, float]] = defaultdict(lambda: {g: 0.0 for g in groups})
        reg_count: dict[str, int] = defaultdict(int)

        uf_obs: dict[str, dict[str, float]] = defaultdict(lambda: {g: 0.0 for g in groups})
        uf_hist: dict[str, dict[str, float]] = defaultdict(lambda: {g: 0.0 for g in groups})
        uf_count: dict[str, int] = defaultdict(int)

        muni_obs: dict[str, dict[str, float]] = defaultdict(lambda: {g: 0.0 for g in groups})
        muni_hist: dict[str, dict[str, float]] = defaultdict(lambda: {g: 0.0 for g in groups})
        muni_count: dict[str, int] = defaultdict(int)

        for obs in observations:
            uf = obs.state
            reg = REGIONS_BY_UF.get(uf, "OUTRA")
            muni = f"{uf}:{obs.municipality_code}"

            reg_count[reg] += 1
            uf_count[uf] += 1
            muni_count[muni] += 1

            obs_d = dict(obs.group_votes)
            h_d = dict(obs.historical_shares)
            v = float(obs.valid_votes)

            for g in groups:
                y = float(obs_d.get(g, 0))
                b = v * float(h_d.get(g, 1.0 / len(groups)))

                nat_obs[g] += y
                nat_hist[g] += b
                reg_obs[reg][g] += y
                reg_hist[reg][g] += b
                uf_obs[uf][g] += y
                uf_hist[uf][g] += b
                muni_obs[muni][g] += y
                muni_hist[muni][g] += b

        # Funcao auxiliar para calcular o shift aditivo linearizado
        def _calc_shift(obs_map: dict[str, float], hist_map: dict[str, float]) -> dict[str, float]:
            tot_o = sum(obs_map.values())
            tot_h = sum(hist_map.values())
            if tot_o <= 0.0 or tot_h <= 0.0:
                return {g: 0.0 for g in groups}
            return {g: (obs_map[g] / tot_o) - (hist_map[g] / tot_h) for g in groups}

        # 2. Efeitos Regionais Brutos
        delta_reg_raw: dict[str, dict[str, float]] = {
            reg: _calc_shift(reg_obs[reg], reg_hist[reg]) for reg in reg_count
        }

        # 3. Efeito Nacional Ponderado pela composicao do eleitorado (MRP)
        delta_nat: dict[str, float] = {g: 0.0 for g in groups}
        weight_sum = sum(REGIONAL_ELECTORATE_WEIGHTS.get(r, 0.01) for r in reg_count)
        if weight_sum > 0.0:
            for r in reg_count:
                w = REGIONAL_ELECTORATE_WEIGHTS.get(r, 0.01) / weight_sum
                for g in groups:
                    delta_nat[g] += w * delta_reg_raw[r][g]
        else:
            delta_nat = _calc_shift(nat_obs, nat_hist)

        # 4. Efeitos Regionais com encolhimento para o Nacional
        delta_reg: dict[str, dict[str, float]] = {}
        for reg, count in reg_count.items():
            lambda_r = count / (count + self._k_reg)
            delta_reg[reg] = {
                g: lambda_r * delta_reg_raw[reg][g] + (1.0 - lambda_r) * delta_nat[g]
                for g in groups
            }

        # 5. Efeitos Estaduais com encolhimento para o Regional
        delta_uf: dict[str, dict[str, float]] = {}
        for uf, count in uf_count.items():
            reg = REGIONS_BY_UF.get(uf, "OUTRA")
            parent_delta = delta_reg.get(reg, delta_nat)
            raw_u = _calc_shift(uf_obs[uf], uf_hist[uf])
            lambda_u = count / (count + self._k_uf)
            delta_uf[uf] = {
                g: lambda_u * raw_u[g] + (1.0 - lambda_u) * parent_delta.get(g, 0.0) for g in groups
            }

        # 6. Efeitos Municipais com encolhimento modulado pela Elasticidade Historica
        delta_muni: dict[str, dict[str, float]] = {}
        for muni, count in muni_count.items():
            uf = muni.split(":")[0]
            parent_delta = delta_uf.get(uf, delta_nat)
            raw_m = _calc_shift(muni_obs[muni], muni_hist[muni])

            # Consulta volatilidade historica 2018-2022
            vol = 0.05
            if self._elasticity_index is not None:
                vol = self._elasticity_index.get_volatility(muni, state=uf)

            # Modula K_muni: maior volatilidade -> menor K efetivo -> maior lambda_m
            effective_k_muni = self._k_muni / (1.0 + self._sensitivity * vol)
            lambda_m = count / (count + effective_k_muni)

            delta_muni[muni] = {
                g: lambda_m * raw_m[g] + (1.0 - lambda_m) * parent_delta.get(g, 0.0) for g in groups
            }

        return delta_nat, delta_reg, delta_uf, delta_muni

    def predict(
        self,
        *,
        observations: list[SectionObservation],
        pending: list[PendingSection],
        groups: tuple[str, ...] = ("PT", "PL", "OUTROS"),
    ) -> ForecastResult:
        """Gera previsao pontual esperada do modelo hierarquico v2 sobre secoes pendentes.

        Aplica os shifts estimados com modulacao de elasticidade as bases historicas
        das secoes pendentes, sem qualquer acesso aos resultados reais das urnas nao abertas.

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

        for sec in pending:
            valid_expected = sec.electorate * sec.expected_turnout_rate * sec.expected_valid_rate
            uf = sec.state
            reg = REGIONS_BY_UF.get(uf, "OUTRA")
            muni = f"{uf}:{sec.municipality_code}"

            chosen_delta = (
                delta_muni.get(muni) or delta_uf.get(uf) or delta_reg.get(reg) or delta_nat
            )
            hist_d = dict(sec.historical_shares)

            raw_shares = [
                max(0.0, hist_d.get(g, 1.0 / len(groups)) + chosen_delta.get(g, 0.0))
                for g in groups
            ]
            sum_raw = sum(raw_shares)
            norm_shares = (
                [x / sum_raw for x in raw_shares]
                if sum_raw > 0.0
                else [1.0 / len(groups) for _ in groups]
            )

            for idx, g in enumerate(groups):
                proj_votes[g] += valid_expected * norm_shares[idx]

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


# A Versao 2 e o modelo padrao ativo do sistema
HierarchicalBayesianModel = HierarchicalBayesianModelV2

__all__ = [
    "HierarchicalBayesianModel",
    "HierarchicalBayesianModelV2",
    "get_default_elasticity_index",
]
