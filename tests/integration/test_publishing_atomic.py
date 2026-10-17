"""Testes de integracao da publicacao atomica e protecao contra snapshots divergentes."""

from datetime import UTC, datetime

import pytest

from horizonte_eleitoral.domain.enums import SnapshotStatus
from horizonte_eleitoral.domain.errors import ReconciliationError
from horizonte_eleitoral.domain.models import CountSnapshot
from horizonte_eleitoral.publishing.publisher import AtomicPublisher
from horizonte_eleitoral.simulation.monte_carlo import SimulationSummary


def test_atomic_publisher_rejects_divergent_snapshot_and_preserves_last_good() -> None:
    """Snapshot divergente e rejeitado e a ultima publicacao valida permanece intocada."""
    publisher = AtomicPublisher()

    # 1. Primeira publicacao CONSISTENTE
    good_snapshot = CountSnapshot.create(
        observed_at=datetime(2026, 10, 4, 19, 0, tzinfo=UTC),
        status=SnapshotStatus.CONSISTENT,
        total_electorate=1000,
        totalized_electorate=300,
        pending_electorate=700,
        artifact_hashes=("a" * 64,),
        normalizer_version="2026.1",
        reconciliation_rule_version="2026.1",
    )
    sim1 = SimulationSummary(
        projected_mean_shares=(("OUTROS", 0.1), ("PL", 0.4), ("PT", 0.5)),
        q05_shares=(("OUTROS", 0.08), ("PL", 0.38), ("PT", 0.48)),
        q50_shares=(("OUTROS", 0.1), ("PL", 0.4), ("PT", 0.5)),
        q95_shares=(("OUTROS", 0.12), ("PL", 0.42), ("PT", 0.52)),
        projected_mean_votes=(("OUTROS", 80), ("PL", 320), ("PT", 400)),
        observed_shares=(("OUTROS", 0.05), ("PL", 0.45), ("PT", 0.50)),
        second_round_probability=0.45,
        total_projected_valid_mean=800,
        num_draws=500,
        seed=1,
    )
    pub1 = publisher.publish(snapshot=good_snapshot, simulation=sim1)
    assert publisher.get_latest("BR") == pub1

    # 2. Tentativa de publicacao com snapshot DIVERGENTE (deve falhar!)
    bad_snapshot = CountSnapshot.create(
        observed_at=datetime(2026, 10, 4, 19, 10, tzinfo=UTC),
        status=SnapshotStatus.DIVERGENT,
        total_electorate=1000,
        totalized_electorate=400,
        pending_electorate=600,
        artifact_hashes=("b" * 64,),
        normalizer_version="2026.1",
        reconciliation_rule_version="2026.1",
    )

    with pytest.raises(ReconciliationError, match="DIVERGENTE"):
        publisher.publish(snapshot=bad_snapshot, simulation=sim1)

    # 3. Garante que o estado anterior continua intacto
    latest_after_failure = publisher.get_latest("BR")
    assert latest_after_failure is not None
    assert latest_after_failure.projection_id == pub1.projection_id
    assert latest_after_failure.totalized_electorate_pct == 30.0
