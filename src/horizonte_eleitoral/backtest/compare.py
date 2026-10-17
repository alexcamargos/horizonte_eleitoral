"""Comparador analitico, temporal e de performance entre Modelos Versao 1 e Versao 2."""

from __future__ import annotations

import bisect
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from horizonte_eleitoral.backtest.metrics import compute_metrics
from horizonte_eleitoral.historical.elasticity import MunicipalElasticityIndex
from horizonte_eleitoral.models.base import PendingSection, SectionObservation
from horizonte_eleitoral.models.hierarchical import HierarchicalBayesianModelV1
from horizonte_eleitoral.models.hierarchical_v2 import HierarchicalBayesianModelV2


@dataclass(frozen=True, slots=True)
class CheckpointComparison:
    """Metricas comparadas de acuracia e performance entre Modelo v1 e Modelo v2.

    Attributes:
        checkpoint_pct: Percentual de apuracao do eleitorado (e.g. 10.0, 50.0).
        v1_mae: Erro medio absoluto do Modelo v1.
        v1_lead_error: Erro no saldo do Modelo v1.
        v1_bias: Vies medio do Modelo v1.
        v2_mae: Erro medio absoluto do Modelo v2.
        v2_lead_error: Erro no saldo do Modelo v2.
        v2_bias: Vies medio do Modelo v2.
        mae_delta: Diferenca v2_mae - v1_mae (negativo indica melhora em v2).
        lead_error_delta: Diferenca v2_lead - v1_lead (negativo indica melhora em v2).
        observed_shares: Participacoes observadas no momento.
        v1_shares: Participacoes projetadas pelo Modelo v1.
        v2_shares: Participacoes projetadas pelo Modelo v2.
        final_shares: Participacoes oficiais consolidadas de gabarito.
        num_observed: Quantidade exata de secoes apuradas no marco.
        num_pending: Quantidade de secoes pendentes projetadas.
        v1_time_ms: Tempo de execucao do Modelo v1 em milissegundos.
        v2_time_ms: Tempo de execucao do Modelo v2 em milissegundos.
    """

    checkpoint_pct: float
    v1_mae: float
    v1_lead_error: float
    v1_bias: float
    v2_mae: float
    v2_lead_error: float
    v2_bias: float
    mae_delta: float
    lead_error_delta: float
    observed_shares: dict[str, float]
    v1_shares: dict[str, float]
    v2_shares: dict[str, float]
    final_shares: dict[str, float]
    num_observed: int = 0
    num_pending: int = 0
    v1_time_ms: float = 0.0
    v2_time_ms: float = 0.0


def run_v1_v2_comparison(
    sections_catalog: Sequence[Mapping[str, Any]],
    elasticity_index: MunicipalElasticityIndex | None = None,
    checkpoints: Sequence[float] = (10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0),
    groups: tuple[str, ...] = ("PT", "PL", "OUTROS"),
) -> list[CheckpointComparison]:
    """Executa a comparacao simultanea de previsao e performance entre v1 e v2 nos checkpoints.

    Otimizado para escala nacional completa (470k+ secoes) atraves de indexacao cumulativa
    e particionamento determinista em tempo linear O(N).

    Args:
        sections_catalog: Catalogo de secoes ordenadas cronologicamente com resultados reais.
        elasticity_index: Indice de elasticidade historica municipal para alimentar o Modelo v2.
        checkpoints: Lista de percentuais de totalizacao do eleitorado a avaliar.
        groups: Codigos dos grupos politicos avaliados.

    Returns:
        Lista de CheckpointComparison ordenada cronologicamente com métricas e tempos.

    Raises:
        ValueError: Se o catalogo de secoes estiver vazio ou o eleitorado for zero.
    """
    if not sections_catalog:
        raise ValueError("sections_catalog nao pode ser vazio para o comparativo.")

    total_elec = sum(int(s.get("electorate", 0)) for s in sections_catalog)
    if total_elec <= 0:
        raise ValueError("Eleitorado total deve ser maior que zero.")

    # 1. Gabarito final oficial consolidado
    final_votes: dict[str, int] = {g: 0 for g in groups}
    tot_valid = 0
    all_obs: list[SectionObservation] = []
    all_pending: list[PendingSection] = []
    cum_elec: list[int] = []
    current_elec = 0

    for s in sections_catalog:
        v = int(s.get("valid_votes", 0))
        tot_valid += v
        g_votes = dict(s.get("group_votes", ()))
        for g in groups:
            final_votes[g] += int(g_votes.get(g, 0))

        sec_id = str(s["section_id"])
        st = str(s["state"])
        muni = str(s["municipality_code"])
        elec = int(s["electorate"])
        h_shares = tuple(s["historical_shares"])

        current_elec += elec
        cum_elec.append(current_elec)

        all_obs.append(
            SectionObservation(
                section_id=sec_id,
                state=st,
                municipality_code=muni,
                valid_votes=v,
                group_votes=tuple(s["group_votes"]),
                historical_shares=h_shares,
            )
        )
        all_pending.append(
            PendingSection(
                section_id=sec_id,
                state=st,
                municipality_code=muni,
                electorate=elec,
                historical_shares=h_shares,
            )
        )

    if tot_valid > 0:
        final_shares = {g: final_votes[g] / tot_valid for g in groups}
    else:
        final_shares = {g: 1.0 / len(groups) for g in groups}

    model_v1 = HierarchicalBayesianModelV1()
    model_v2 = HierarchicalBayesianModelV2(elasticity_index=elasticity_index)

    results: list[CheckpointComparison] = []
    n_sections = len(all_obs)

    for cp in sorted(checkpoints):
        target_elec = (cp / 100.0) * total_elec
        cutoff = bisect.bisect_left(cum_elec, int(target_elec))
        cutoff = min(cutoff, n_sections)

        observed = all_obs[:cutoff]
        pending = all_pending[cutoff:]

        # Mede latencia de processamento do Modelo v1
        t0 = time.perf_counter()
        pred_v1 = model_v1.predict(observations=observed, pending=pending, groups=groups)
        t_v1_ms = (time.perf_counter() - t0) * 1000.0

        # Mede latencia de processamento do Modelo v2
        t1 = time.perf_counter()
        pred_v2 = model_v2.predict(observations=observed, pending=pending, groups=groups)
        t_v2_ms = (time.perf_counter() - t1) * 1000.0

        v1_dict = dict(pred_v1.projected_shares)
        v2_dict = dict(pred_v2.projected_shares)
        obs_dict = dict(pred_v1.observed_shares)

        mae_1, bias_1, lead_1 = compute_metrics(v1_dict, final_shares, groups)
        mae_2, bias_2, lead_2 = compute_metrics(v2_dict, final_shares, groups)

        results.append(
            CheckpointComparison(
                checkpoint_pct=round(cp, 1),
                v1_mae=mae_1,
                v1_lead_error=lead_1,
                v1_bias=bias_1,
                v2_mae=mae_2,
                v2_lead_error=lead_2,
                v2_bias=bias_2,
                mae_delta=round(mae_2 - mae_1, 6),
                lead_error_delta=round(lead_2 - lead_1, 6),
                observed_shares=obs_dict,
                v1_shares=v1_dict,
                v2_shares=v2_dict,
                final_shares=final_shares,
                num_observed=len(observed),
                num_pending=len(pending),
                v1_time_ms=round(t_v1_ms, 2),
                v2_time_ms=round(t_v2_ms, 2),
            )
        )

    return results


def format_comparison_table(results: Sequence[CheckpointComparison]) -> str:
    """Formata a comparacao entre v1 e v2 com acuracia e metricas de performance.

    Args:
        results: Sequencia de CheckpointComparison.

    Returns:
        String formatada em formato tabular.

    Raises:
        None.
    """
    lines = [
        "=" * 108,
        (
            f"{'MARCO':^7} | {'SEÇÕES APURADAS':^15} | {'V1 MAE':^9} | {'V2 MAE':^9} | "
            f"{'DELTA MAE':^10} | {'V1 LEAD':^9} | {'V2 LEAD':^9} | {'DELTA LEAD':^11} | "
            f"{'TEMPO V1':^9} | {'TEMPO V2':^9}"
        ),
        "-" * 108,
    ]
    for r in results:
        delta_m_sign = f"{r.mae_delta * 100:+.3f}%"
        delta_l_sign = f"{r.lead_error_delta * 100:+.3f}%"
        sec_str = f"{r.num_observed:,} / {r.num_observed + r.num_pending:,}".replace(",", ".")
        lines.append(
            f"{r.checkpoint_pct:>5.1f}%  | "
            f"{sec_str:^15} | "
            f"{r.v1_mae * 100:>7.3f}% | "
            f"{r.v2_mae * 100:>7.3f}% | "
            f"{delta_m_sign:>9} | "
            f"{r.v1_lead_error * 100:>7.3f}% | "
            f"{r.v2_lead_error * 100:>7.3f}% | "
            f"{delta_l_sign:>10} | "
            f"{r.v1_time_ms:>6.1f}ms | "
            f"{r.v2_time_ms:>6.1f}ms"
        )
    lines.append("=" * 108)
    return "\n".join(lines)
