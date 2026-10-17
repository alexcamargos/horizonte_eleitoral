"""Serializacao explicita dos contratos persistidos pela fundacao."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from horizonte_eleitoral.domain.enums import ArtifactType, SnapshotStatus
from horizonte_eleitoral.domain.errors import ValidationError
from horizonte_eleitoral.domain.models import CountSnapshot, LineageRecord, RawArtifact


def raw_artifact_from_dict(value: dict[str, object]) -> RawArtifact:
    """Reconstrui um manifesto de artefato e reaplica suas invariantes."""
    return RawArtifact(
        artifact_id=_string(value, "artifact_id"),
        election_id=_string(value, "election_id"),
        artifact_type=ArtifactType(_string(value, "artifact_type")),
        source_url=_string(value, "source_url"),
        collected_at=_datetime(value, "collected_at"),
        http_status=_integer(value, "http_status"),
        content_sha256=_string(value, "content_sha256"),
        size_bytes=_integer(value, "size_bytes"),
        headers=_string_pairs(value, "headers"),
        storage_path=_string(value, "storage_path"),
    )


def lineage_from_dict(value: dict[str, object]) -> LineageRecord:
    """Reconstrui lineage persistido e valida hashes/ordem."""
    return LineageRecord(
        lineage_id=_string(value, "lineage_id"),
        output_type=_string(value, "output_type"),
        output_id=_string(value, "output_id"),
        input_hashes=_strings(value, "input_hashes"),
        code_version=_string(value, "code_version"),
        configuration_hash=_string(value, "configuration_hash"),
    )


def snapshot_from_dict(value: dict[str, object]) -> CountSnapshot:
    """Reconstrui snapshot persistido e valida todos os invariantes."""
    return CountSnapshot(
        snapshot_id=_string(value, "snapshot_id"),
        observed_at=_datetime(value, "observed_at"),
        status=SnapshotStatus(_string(value, "status")),
        total_electorate=_integer(value, "total_electorate"),
        totalized_electorate=_integer(value, "totalized_electorate"),
        pending_electorate=_integer(value, "pending_electorate"),
        artifact_hashes=_strings(value, "artifact_hashes"),
        normalizer_version=_string(value, "normalizer_version"),
        reconciliation_rule_version=_string(value, "reconciliation_rule_version"),
        diagnostics=_string_pairs(value, "diagnostics"),
    )


def _string(value: dict[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise ValidationError(f"{key} deve ser texto no registro persistido.")
    return item


def _integer(value: dict[str, object], key: str) -> int:
    item = value.get(key)
    if type(item) is not int:
        raise ValidationError(f"{key} deve ser inteiro no registro persistido.")
    return item


def _datetime(value: dict[str, object], key: str) -> datetime:
    item = _string(value, key)
    try:
        return datetime.fromisoformat(item)
    except ValueError as error:
        raise ValidationError(f"{key} deve ser data ISO-8601 no registro persistido.") from error


def _strings(value: dict[str, object], key: str) -> tuple[str, ...]:
    item = value.get(key)
    if not isinstance(item, list) or not all(isinstance(element, str) for element in item):
        raise ValidationError(f"{key} deve ser lista de textos no registro persistido.")
    return tuple(cast(list[str], item))


def _string_pairs(value: dict[str, object], key: str) -> tuple[tuple[str, str], ...]:
    item = value.get(key)
    if not isinstance(item, list):
        raise ValidationError(f"{key} deve ser lista de pares no registro persistido.")
    pairs: list[tuple[str, str]] = []
    for pair in item:
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or not isinstance(pair[0], str)
            or not isinstance(pair[1], str)
        ):
            raise ValidationError(f"{key} deve conter pares de textos no registro persistido.")
        pairs.append((pair[0], pair[1]))
    return tuple(pairs)
