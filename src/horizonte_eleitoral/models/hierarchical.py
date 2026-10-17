"""Modelo hierarquico multinivel Versao 1 (v1) - MODELO LEGADO ARQUIVADO.

Este modulo implementa a primeira versao do modelo multinivel bayesiano (MRP)
do projeto Horizonte Eleitoral, fundamentada exclusivamente nas bases de 2022 e 2026.

Status:
    ARQUIVADO / BASELINE LEGADO.
    Substituido pelo HierarchicalBayesianModelV2 como modelo ativo padrao do sistema,
    que incorpora o indice de elasticidade municipal 2018-2022 e modula dinamicamente
    o encolhimento bayesiano (shrinkage), reduzindo o erro absoluto medio (MAE) e o
    erro de diferenca entre os lideres (Lead Error) no conjunto nacional de 499.206 secoes.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import cast

import numpy as np

from horizonte_eleitoral.domain.enums import MatchQuality
from horizonte_eleitoral.models.base import (
    ForecastModel,
    ForecastResult,
    PendingSection,
    SectionObservation,
)

QUALITY_VARIANCE_MULTIPLIER: dict[MatchQuality, float] = {
    MatchQuality.EXACT: 1.0,
    MatchQuality.SAME_COMPLEX: 1.2,
    MatchQuality.NEIGHBORING: 1.5,
    MatchQuality.SAME_ZONE: 2.0,
    MatchQuality.SAME_MUNICIPALITY: 2.5,
    MatchQuality.UNMATCHED: 4.0,
}

REGIONS_BY_UF: dict[str, str] = {
    "AC": "NORTE",
    "AP": "NORTE",
    "AM": "NORTE",
    "PA": "NORTE",
    "RO": "NORTE",
    "RR": "NORTE",
    "TO": "NORTE",
    "AL": "NORDESTE",
    "BA": "NORDESTE",
    "CE": "NORDESTE",
    "MA": "NORDESTE",
    "PB": "NORDESTE",
    "PE": "NORDESTE",
    "PI": "NORDESTE",
    "RN": "NORDESTE",
    "SE": "NORDESTE",
    "DF": "CENTRO-OESTE",
    "GO": "CENTRO-OESTE",
    "MT": "CENTRO-OESTE",
    "MS": "CENTRO-OESTE",
    "ES": "SUDESTE",
    "MG": "SUDESTE",
    "RJ": "SUDESTE",
    "SP": "SUDESTE",
    "PR": "SUL",
    "RS": "SUL",
    "SC": "SUL",
}

# Pesos eleitorais oficiais das macro-regioes conhecidos a priori (censo eleitoral do TSE)
REGIONAL_ELECTORATE_WEIGHTS: dict[str, float] = {
    "SUDESTE": 0.428,
    "NORDESTE": 0.271,
    "SUL": 0.148,
    "NORTE": 0.080,
    "CENTRO-OESTE": 0.070,
    "OUTRA": 0.003,
}


def stable_softmax(logits: np.ndarray, base_shares: np.ndarray) -> np.ndarray:
    """Calcula a softmax numericamente estavel sobre composicoes logaritmicas.

    p[k] = base_share[k] * exp(logits[k]) / sum(...)
         = exp(log(base_share[k]) + logits[k] - c) / sum(...)

    Args:
        logits: Array de deltas [..., num_groups].
        base_shares: Array de shares historicos base [..., num_groups].

    Returns:
        Array de probabilidades com soma 1.0 no ultimo eixo.

    Raises:
        None.
    """
    clipped_shares = np.clip(base_shares, 1e-6, 1.0)
    log_base = np.log(clipped_shares)
    combined = log_base + logits
    max_val = np.max(combined, axis=-1, keepdims=True)
    exp_shifted = np.exp(combined - max_val)
    sum_exp = np.sum(exp_shifted, axis=-1, keepdims=True)
    return cast(np.ndarray, exp_shifted / sum_exp)


class HierarchicalBayesianModelV1(ForecastModel):
    """Modelo hierarquico multinivel Versao 1 (v1) - BASE DE MODELO LEGADO.

    Implementa a formulacao original do modelo bayesiano multinivel (MRP) com
    encolhimento multinivel estatico (Nacional -> Regional -> Estadual -> Municipal)
    utilizando apenas as bases de 2022 e 2026.

    Status:
        ARQUIVADO / LEGADO. Preservado para auditoria e ensaios comparativos de baseline.
        O modelo ativo padrao de producao e o HierarchicalBayesianModelV2.

    Args:
        pseudo_count: Constante historica de compatibilidade de interface.
        shrinkage_region: Constante K de encolhimento regional em direcao ao nacional.
        shrinkage_uf: Constante K de encolhimento estadual em direcao ao regional.
        shrinkage_muni: Constante K de encolhimento municipal em direcao ao estadual.
        reference_group: Grupo de referencia mantido para compatibilidade de assinatura.
    """

    def __init__(
        self,
        pseudo_count: float = 10.0,
        shrinkage_region: float = 30.0,
        shrinkage_uf: float = 20.0,
        shrinkage_muni: float = 10.0,
        reference_group: str = "OUTROS",
    ) -> None:
        """Inicializa o modelo hierarquico v1 legado com parametros de regularizacao e encolhimento.

        Args:
            pseudo_count: Constante historica de compatibilidade de interface.
            shrinkage_region: Constante K de encolhimento regional em direcao ao nacional.
            shrinkage_uf: Constante K de encolhimento estadual em direcao ao regional.
            shrinkage_muni: Constante K de encolhimento municipal em direcao ao estadual.
            reference_group: Grupo de referencia mantido para compatibilidade de assinatura.

        Returns:
            None.

        Raises:
            None.
        """
        self._pseudo_count = pseudo_count
        self._k_reg = shrinkage_region
        self._k_uf = shrinkage_uf
        self._k_muni = shrinkage_muni
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
        """Estima swings aditivos com ponderacao regional e shrinkage multinivel estrito.

        Calcula os desvios entre votos observados e votos esperados pelo historico
        utilizando exclusivamente as secoes observadas, garantindo ausencia de
        vazamento temporal de dados.

        Args:
            observations: Sequencia de secoes eleitorais ja totalizadas e observadas.
            groups: Tupla contendo codigos canonicos dos grupos politicos avaliados.

        Returns:
            Tupla de quatro elementos contendo:
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
        # Evita distorcao por velocidade assimetrica de apuracao entre regioes
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

        # 6. Efeitos Municipais com encolhimento para o Estadual
        delta_muni: dict[str, dict[str, float]] = {}
        for muni, count in muni_count.items():
            uf = muni.split(":")[0]
            parent_delta = delta_uf.get(uf, delta_nat)
            raw_m = _calc_shift(muni_obs[muni], muni_hist[muni])
            lambda_m = count / (count + self._k_muni)
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
        """Gera previsao pontual esperada do modelo hierarquico sobre secoes pendentes.

        Aplica os shifts estimados exclusivamente sobre dados observados as bases historicas
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
            model_name="hierarchical_bayesian_composite",
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


# Alias de retrocompatibilidade para importacoes diretas do modulo legado
HierarchicalBayesianModel = HierarchicalBayesianModelV1

__all__ = [
    "HierarchicalBayesianModel",
    "HierarchicalBayesianModelV1",
    "QUALITY_VARIANCE_MULTIPLIER",
    "REGIONS_BY_UF",
    "REGIONAL_ELECTORATE_WEIGHTS",
    "stable_softmax",
]
