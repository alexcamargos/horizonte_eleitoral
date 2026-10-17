"""Motor de reconciliacao entre inventario de secoes e totalizacao de votos."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from horizonte_eleitoral.domain.enums import SnapshotStatus
from horizonte_eleitoral.domain.models import CountSnapshot
from horizonte_eleitoral.normalization.models import (
    NormalizedSectionState,
    NormalizedTotalization,
)
from horizonte_eleitoral.reconciliation.models import ReconciliationReport


class ReconciliationEngine:
    """Valida a consistencia logica entre arquivos parciais de urna e totalizacao oficial."""

    def __init__(self, max_stale_seconds: int = 1800) -> None:
        """Inicializa o reconciliador com tolerancia maxima de defasagem temporal.

        Args:
            max_stale_seconds: Limite em segundos para alertar defasagem de dados.

        Returns:
            None.

        Raises:
            None.
        """
        self._max_stale_seconds = max_stale_seconds

    def reconcile(
        self,
        *,
        observed_at: datetime,
        sections: Sequence[NormalizedSectionState],
        totalization: NormalizedTotalization,
        artifact_hashes: Sequence[str],
        normalizer_version: str = "2026.1",
        reconciliation_rule_version: str = "2026.1",
        unmatched_sections: int = 0,
    ) -> tuple[CountSnapshot, ReconciliationReport]:
        """Compara o estado detalhado das secoes com a totalizacao de votos.

        Args:
            observed_at: Horario UTC de observacao da rodada.
            sections: Lista de estados individuais de secao normalizados (EA16/EA18).
            totalization: Totalizacao consolidada do escopo (EA20).
            artifact_hashes: Lista ordenada de SHA-256 de todos os artefatos de entrada.
            normalizer_version: Versao semantica do normalizador utilizado.
            reconciliation_rule_version: Versao da regra de reconciliacao.
            unmatched_sections: Quantidade de secoes sem pareamento historico.

        Returns:
            Tupla contendo o CountSnapshot determinista e o ReconciliationReport.

        Raises:
            None.
        """
        diagnostics: list[tuple[str, str]] = []
        divergent_count = 0

        # 1. Verificacao de contagem de secoes totalizadas
        if sections:
            totalized_in_sections = sum(1 for s in sections if s.is_totalized)
            # Se ha discrepancia relevante entre a totalizacao EA20 e as secoes EA16
            if (
                totalization.totalized_sections > 0
                and abs(totalized_in_sections - totalization.totalized_sections) > 0
            ):
                divergent_count += abs(totalized_in_sections - totalization.totalized_sections)
                diagnostics.append(
                    (
                        "section_count_mismatch",
                        f"EA20 indica {totalization.totalized_sections} secoes apuradas, "
                        f"mas EA16 possui {totalized_in_sections}.",
                    )
                )

        # 2. Verificacao de defasagem temporal (staleness)
        newest_timestamp: datetime | None = None
        for sec in sections:
            if sec.generation_timestamp is not None:
                if newest_timestamp is None or sec.generation_timestamp > newest_timestamp:
                    newest_timestamp = sec.generation_timestamp

        stale_seconds = 0
        if newest_timestamp is not None:
            tz_observed = (
                observed_at.astimezone(UTC)
                if observed_at.tzinfo
                else observed_at.replace(tzinfo=UTC)
            )
            tz_newest = (
                newest_timestamp.astimezone(UTC)
                if newest_timestamp.tzinfo
                else newest_timestamp.replace(tzinfo=UTC)
            )
            delta = (tz_observed - tz_newest).total_seconds()
            stale_seconds = max(0, int(delta))

        if stale_seconds > self._max_stale_seconds:
            diagnostics.append(
                (
                    "stale_data_warning",
                    f"Ultima atualizacao de secao ocorreu ha {stale_seconds} segundos "
                    f"(limite: {self._max_stale_seconds}s).",
                )
            )

        # 3. Decisao de status do Snapshot
        is_consistent = (divergent_count == 0) and (totalization.total_electorate >= 0)
        status = SnapshotStatus.CONSISTENT if is_consistent else SnapshotStatus.DIVERGENT

        report = ReconciliationReport(
            status=status,
            total_sections=totalization.total_sections,
            totalized_sections=totalization.totalized_sections,
            divergent_sections=divergent_count,
            unmatched_sections=unmatched_sections,
            stale_seconds=stale_seconds,
            diagnostics=tuple(sorted(diagnostics)),
        )

        snapshot = CountSnapshot.create(
            observed_at=observed_at,
            status=status,
            total_electorate=totalization.total_electorate,
            totalized_electorate=totalization.totalized_electorate,
            pending_electorate=totalization.pending_electorate,
            artifact_hashes=artifact_hashes,
            normalizer_version=normalizer_version,
            reconciliation_rule_version=reconciliation_rule_version,
            diagnostics=tuple(sorted(diagnostics)),
        )

        return snapshot, report
