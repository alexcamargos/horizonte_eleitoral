"""Testes unitarios para a maquina de reconciliacao de estado da apuracao."""

from datetime import UTC, datetime, timedelta

from horizonte_eleitoral.domain.enums import GeographicScope, SnapshotStatus
from horizonte_eleitoral.normalization.models import (
    NormalizedSectionState,
    NormalizedTotalization,
)
from horizonte_eleitoral.reconciliation.reconciler import ReconciliationEngine


def test_reconciliation_produces_consistent_snapshot_when_counts_align() -> None:
    """Quando o numero de secoes totalizadas bate entre EA16 e EA20, o status e CONSISTENTE."""
    now = datetime(2026, 10, 4, 19, 0, tzinfo=UTC)

    sections = [
        NormalizedSectionState("SP", "71072", "0001", "0001", now, "h1", is_totalized=True),
        NormalizedSectionState("SP", "71072", "0001", "0002", now, "h2", is_totalized=True),
        NormalizedSectionState("SP", "71072", "0001", "0003", now, "h3", is_totalized=False),
    ]

    totalization = NormalizedTotalization(
        scope=GeographicScope.MUNICIPALITY,
        scope_code="71072",
        total_electorate=1000,
        totalized_electorate=650,
        pending_electorate=350,
        total_sections=3,
        totalized_sections=2,
        pending_sections=1,
        valid_votes=500,
        blank_votes=50,
        null_votes=50,
        candidate_group_votes=(("OUTROS", 50), ("PL", 200), ("PT", 250)),
    )

    engine = ReconciliationEngine()
    snapshot, report = engine.reconcile(
        observed_at=now,
        sections=sections,
        totalization=totalization,
        artifact_hashes=("a" * 64,),
    )

    assert report.is_consistent is True
    assert report.status == SnapshotStatus.CONSISTENT
    assert snapshot.status == SnapshotStatus.CONSISTENT
    assert report.divergent_sections == 0


def test_reconciliation_produces_divergent_snapshot_when_counts_differ() -> None:
    """Discrepancia entre secoes totalizadas gera snapshot DIVERGENTE e diagnostico explicito."""
    now = datetime(2026, 10, 4, 19, 0, tzinfo=UTC)

    # 1 secao apurada no EA16, mas EA20 diz 2 secoes apuradas
    sections = [
        NormalizedSectionState("SP", "71072", "0001", "0001", now, "h1", is_totalized=True),
        NormalizedSectionState("SP", "71072", "0001", "0002", now, "h2", is_totalized=False),
    ]

    totalization = NormalizedTotalization(
        scope=GeographicScope.MUNICIPALITY,
        scope_code="71072",
        total_electorate=1000,
        totalized_electorate=600,
        pending_electorate=400,
        total_sections=2,
        totalized_sections=2,  # Conflito!
        pending_sections=0,
        valid_votes=500,
        blank_votes=50,
        null_votes=50,
        candidate_group_votes=(("OUTROS", 50), ("PL", 200), ("PT", 250)),
    )

    engine = ReconciliationEngine()
    snapshot, report = engine.reconcile(
        observed_at=now,
        sections=sections,
        totalization=totalization,
        artifact_hashes=("b" * 64,),
    )

    assert report.is_consistent is False
    assert report.status == SnapshotStatus.DIVERGENT
    assert snapshot.status == SnapshotStatus.DIVERGENT
    assert report.divergent_sections == 1
    assert any("mismatch" in key for key, _ in report.diagnostics)


def test_reconciliation_detects_stale_data() -> None:
    """Defasagem temporal maior que o limite configurado gera aviso de staleness."""
    now = datetime(2026, 10, 4, 20, 0, tzinfo=UTC)
    old_time = now - timedelta(hours=1)  # 3600 segundos atras

    sections = [
        NormalizedSectionState("SP", "71072", "0001", "0001", old_time, "h1", is_totalized=True),
    ]

    totalization = NormalizedTotalization(
        scope=GeographicScope.MUNICIPALITY,
        scope_code="71072",
        total_electorate=500,
        totalized_electorate=500,
        pending_electorate=0,
        total_sections=1,
        totalized_sections=1,
        pending_sections=0,
        valid_votes=400,
        blank_votes=50,
        null_votes=50,
        candidate_group_votes=(("OUTROS", 40), ("PL", 160), ("PT", 200)),
    )

    engine = ReconciliationEngine(max_stale_seconds=1800)
    _, report = engine.reconcile(
        observed_at=now,
        sections=sections,
        totalization=totalization,
        artifact_hashes=("c" * 64,),
    )

    assert report.stale_seconds >= 3600
    assert any("stale" in key for key, _ in report.diagnostics)
