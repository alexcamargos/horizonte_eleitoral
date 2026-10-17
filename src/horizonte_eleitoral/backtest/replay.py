"""Motor de replay temporal para execucao de backtests sem vazamento de informacao futura."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any

from horizonte_eleitoral.backtest.metrics import compute_metrics
from horizonte_eleitoral.backtest.models import BacktestReport, CheckpointMetric
from horizonte_eleitoral.models.base import (
    ForecastModel,
    PendingSection,
    SectionObservation,
)


class TimelineReplayer:
    """Simulador de apuracao que alimenta os modelos estritamente ate o marco de cada checkpoint."""

    def __init__(
        self, checkpoints_pct: Sequence[float] = (5.0, 10.0, 20.0, 50.0, 80.0, 95.0)
    ) -> None:
        """Inicializa o replayer com os marcos percentuais desejados.

        Args:
            checkpoints_pct: Lista ordenada de percentuais de totalizacao do eleitorado.

        Returns:
            None.

        Raises:
            None.
        """
        self._checkpoints = tuple(sorted(checkpoints_pct))

    def replay(
        self,
        *,
        election_id: str,
        models: Sequence[ForecastModel],
        all_sections: Sequence[Mapping[str, Any]],
        groups: tuple[str, ...] = ("PT", "PL", "OUTROS"),
    ) -> BacktestReport:
        """Executa a simulacao cronologica comparando todos os modelos nos mesmos checkpoints.

        Args:
            election_id: Identificador da eleicao avaliada.
            models: Modelos a serem testados em paralelo nos mesmos dados.
            all_sections: Dicionarios com 'section_id', 'state', 'muni', 'electorate',
                          'valid_votes', 'group_votes', 'historical_shares'.
            groups: Grupos partidarios avaliados.

        Returns:
            BacktestReport completo com metricas comparaveis por checkpoint.

        Raises:
            ValueError: Se a lista de secoes estiver vazia.
        """
        if not all_sections:
            raise ValueError("all_sections nao pode ser vazia para o replay.")

        total_electorate = sum(int(s.get("electorate", 0)) for s in all_sections)
        if total_electorate == 0:
            raise ValueError("O eleitorado total da simulacao deve ser maior que zero.")

        # Calcula o resultado real final consolidado (gabarito)
        final_votes: dict[str, int] = {g: 0 for g in groups}
        total_final_valid = 0
        for s in all_sections:
            valid = int(s.get("valid_votes", 0))
            total_final_valid += valid
            g_votes: dict[str, int] = dict(s.get("group_votes", ()))
            for g in groups:
                final_votes[g] += int(g_votes.get(g, 0))

        if total_final_valid == 0:
            final_shares = {g: 1.0 / len(groups) for g in groups}
        else:
            final_shares = {g: final_votes[g] / total_final_valid for g in groups}

        metrics_list: list[CheckpointMetric] = []

        # Execucao em cada checkpoint
        for cp in self._checkpoints:
            target_electorate = (cp / 100.0) * total_electorate

            accumulated_electorate = 0
            observed_sections: list[SectionObservation] = []
            pending_sections: list[PendingSection] = []

            for s in all_sections:
                sec_id = str(s["section_id"])
                st = str(s["state"])
                muni = str(s["municipality_code"])
                electorate = int(s["electorate"])
                hist_shares: tuple[tuple[str, float], ...] = tuple(s["historical_shares"])

                # Se ainda estamos antes do limite do checkpoint, secao e OBSERVADA
                if (
                    accumulated_electorate + electorate <= target_electorate
                    or not observed_sections
                ):
                    accumulated_electorate += electorate
                    observed_sections.append(
                        SectionObservation(
                            section_id=sec_id,
                            state=st,
                            municipality_code=muni,
                            valid_votes=int(s["valid_votes"]),
                            group_votes=tuple(s["group_votes"]),
                            historical_shares=hist_shares,
                        )
                    )
                else:
                    # Secao PENDENTE (Nenhum voto real visivel!)
                    pending_sections.append(
                        PendingSection(
                            section_id=sec_id,
                            state=st,
                            municipality_code=muni,
                            electorate=electorate,
                            historical_shares=hist_shares,
                        )
                    )

            # Roda cada modelo no mesmo checkpoint
            for model in models:
                t0 = time.perf_counter()
                result = model.predict(
                    observations=observed_sections,
                    pending=pending_sections,
                    groups=groups,
                )
                elapsed = time.perf_counter() - t0

                proj_dict = dict(result.projected_shares)
                mae, bias, lead_error = compute_metrics(proj_dict, final_shares, groups)

                metrics_list.append(
                    CheckpointMetric(
                        model_name=result.model_name,
                        checkpoint_pct=cp,
                        mae=mae,
                        bias=bias,
                        lead_error=lead_error,
                        runtime_seconds=round(elapsed, 6),
                    )
                )

        return BacktestReport(
            election_id=election_id,
            checkpoints=self._checkpoints,
            metrics=tuple(metrics_list),
        )
