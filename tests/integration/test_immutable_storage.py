"""Testes locais do cofre, lineage e snapshots, sem banco nem rede."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from horizonte_eleitoral.domain.enums import ArtifactType, SnapshotStatus
from horizonte_eleitoral.domain.errors import ImmutableWriteError, SnapshotConflictError
from horizonte_eleitoral.domain.models import CountSnapshot, LineageRecord, RawArtifactRequest
from horizonte_eleitoral.storage.local import (
    FileLineageRepository,
    FileSnapshotRepository,
    LocalArtifactStore,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
CONFIGURATION_HASH = "c" * 64


def test_artifact_body_is_deduplicated_and_manifests_are_reopened(tmp_path: Path) -> None:
    """Mesmo corpo gera um blob; cada recebimento conserva seu proprio manifesto."""
    request = _fixture_request()
    store = LocalArtifactStore(tmp_path)

    first = store.store(request)
    second = store.store(replace(request, collected_at=request.collected_at + timedelta(minutes=1)))

    assert first.content_sha256 == second.content_sha256
    assert first.storage_path == second.storage_path
    assert first.artifact_id != second.artifact_id
    assert store.get(first.artifact_id) == first
    assert store.read_body(first) == request.body
    assert len(list((tmp_path / "raw" / "sha256").rglob("*.blob"))) == 1


def test_store_refuses_to_overwrite_a_corrupted_immutable_body(tmp_path: Path) -> None:
    """Uma colisao de caminho nunca substitui bytes ja presentes no cofre."""
    request = _fixture_request()
    store = LocalArtifactStore(tmp_path)
    artifact = store.store(request)
    body_path = tmp_path / Path(artifact.storage_path)
    body_path.write_bytes(b"conteudo adulterado")

    with pytest.raises(ImmutableWriteError, match="substituir"):
        store.store(request)

    assert body_path.read_bytes() == b"conteudo adulterado"


def test_lineage_is_deterministic_and_reopens_from_append_only_storage(tmp_path: Path) -> None:
    """A ordem de hashes nao muda o lineage nem o registro persistido."""
    first = LineageRecord.create(
        output_type="count_snapshot",
        output_id="snapshot:fixture",
        input_hashes=(HASH_B, HASH_A),
        code_version="git:fixture",
        configuration_hash=CONFIGURATION_HASH,
    )
    second = LineageRecord.create(
        output_type="count_snapshot",
        output_id="snapshot:fixture",
        input_hashes=(HASH_A, HASH_B),
        code_version="git:fixture",
        configuration_hash=CONFIGURATION_HASH,
    )
    repository = FileLineageRepository(tmp_path)

    assert first.lineage_id == second.lineage_id
    assert repository.save(first) == first
    assert repository.get(first.lineage_id) == first


def test_snapshot_is_deterministic_and_rejects_same_id_with_different_content(
    tmp_path: Path,
) -> None:
    """Somente um conteudo pode ocupar o ID definido pelos artefatos e versoes."""
    first = _snapshot(totalized_electorate=40, pending_electorate=60)
    conflicting = _snapshot(totalized_electorate=50, pending_electorate=50)
    repository = FileSnapshotRepository(tmp_path)

    assert repository.save(first) == first
    assert repository.get(first.snapshot_id) == first
    assert first.snapshot_id == conflicting.snapshot_id
    with pytest.raises(SnapshotConflictError, match="outro conteudo"):
        repository.save(conflicting)


def _fixture_request() -> RawArtifactRequest:
    fixture_directory = Path(__file__).parents[1] / "fixtures" / "foundation"
    metadata = json.loads(
        (fixture_directory / "raw-artifact-request.json").read_text(encoding="utf-8")
    )
    body = (fixture_directory / "ea20-sample.json").read_bytes()
    return RawArtifactRequest(
        election_id=metadata["election_id"],
        artifact_type=ArtifactType(metadata["artifact_type"]),
        source_url=metadata["source_url"],
        collected_at=datetime.fromisoformat(metadata["collected_at"]),
        http_status=metadata["http_status"],
        body=body,
        headers=tuple((name, value) for name, value in metadata["headers"]),
    )


def _snapshot(*, totalized_electorate: int, pending_electorate: int) -> CountSnapshot:
    return CountSnapshot.create(
        observed_at=datetime(2026, 10, 4, 20, 0, tzinfo=UTC),
        status=SnapshotStatus.CONSISTENT,
        total_electorate=100,
        totalized_electorate=totalized_electorate,
        pending_electorate=pending_electorate,
        artifact_hashes=(HASH_B, HASH_A),
        normalizer_version="2026.1",
        reconciliation_rule_version="2026.1",
    )
