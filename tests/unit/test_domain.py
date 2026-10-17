"""Testes unitarios de tipos e invariantes sem I/O ou ambiente externo."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from horizonte_eleitoral.domain.enums import SnapshotStatus
from horizonte_eleitoral.domain.errors import InvariantViolationError
from horizonte_eleitoral.domain.models import (
    CountSnapshot,
    ElectionKey,
    MunicipalityKey,
    SectionKey,
    VoteDistribution,
)

HASH_A = "a" * 64
HASH_B = "b" * 64


def test_section_key_preserves_external_leading_zeroes() -> None:
    """Codigos eleitorais sao texto e nao podem perder zeros a esquerda."""
    section = SectionKey(
        election=ElectionKey("0002026", "01", "PRESIDENTE"),
        municipality=MunicipalityKey("sp", "003558"),
        zone="0012",
        section="0007",
    )

    assert section.to_dict()["zone"] == "0012"
    assert section.to_dict()["section"] == "0007"
    assert section.municipality.municipality_code == "003558"


def test_vote_distribution_rejects_shares_that_do_not_sum_to_one() -> None:
    """Shares sao derivados consistentes e nao aceitam distribuicao incompleta."""
    with pytest.raises(InvariantViolationError, match="somar um"):
        VoteDistribution((("PT", Decimal("0.51")), ("PL", Decimal("0.40"))))


def test_snapshot_identifier_is_independent_of_artifact_input_order() -> None:
    """A identidade do snapshot usa hashes ordenados conforme o contrato tecnico."""
    common = {
        "observed_at": datetime(2026, 10, 4, 20, 0, tzinfo=UTC),
        "status": SnapshotStatus.CONSISTENT,
        "total_electorate": 100,
        "totalized_electorate": 40,
        "pending_electorate": 60,
        "normalizer_version": "2026.1",
        "reconciliation_rule_version": "2026.1",
    }

    first = CountSnapshot.create(artifact_hashes=(HASH_B, HASH_A), **common)
    second = CountSnapshot.create(artifact_hashes=(HASH_A, HASH_B), **common)

    assert first.snapshot_id == second.snapshot_id
    assert first.artifact_hashes == (HASH_A, HASH_B)
