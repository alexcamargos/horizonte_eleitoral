"""Contratos de fixtures e migracao que rodam sem recursos externos."""

import json
from datetime import datetime
from pathlib import Path

from horizonte_eleitoral.domain.enums import ArtifactType
from horizonte_eleitoral.domain.models import RawArtifactRequest


def test_raw_artifact_fixture_conforms_to_the_typed_boundary() -> None:
    """O fixture de contrato representa uma resposta valida sem chamar o TSE."""
    fixture_directory = Path(__file__).parents[1] / "fixtures" / "foundation"
    metadata = json.loads(
        (fixture_directory / "raw-artifact-request.json").read_text(encoding="utf-8")
    )

    artifact = RawArtifactRequest(
        election_id=metadata["election_id"],
        artifact_type=ArtifactType(metadata["artifact_type"]),
        source_url=metadata["source_url"],
        collected_at=datetime.fromisoformat(metadata["collected_at"]),
        http_status=metadata["http_status"],
        body=(fixture_directory / "ea20-sample.json").read_bytes(),
        headers=tuple((name, value) for name, value in metadata["headers"]),
    )

    assert artifact.artifact_type is ArtifactType.EA20
    assert artifact.content_sha256


def test_initial_migration_contains_the_auditability_contract() -> None:
    """A migracao inicial preserva as entidades exigidas pela fase de fundacao."""
    repository_root = Path(__file__).parents[2]
    migration = (repository_root / "migrations" / "001_foundation.sql").read_text(encoding="utf-8")

    for table_name in (
        "raw_artifact",
        "ingestion_attempt",
        "parser_run",
        "data_lineage",
        "count_snapshot",
    ):
        assert f"CREATE TABLE {table_name}" in migration
    assert "content_sha256 CHAR(64)" in migration
    assert "totalized_electorate + pending_electorate = total_electorate" in migration
