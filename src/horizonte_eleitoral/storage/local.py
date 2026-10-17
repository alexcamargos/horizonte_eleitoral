"""Persistencia local append-only para artefatos, lineage e snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from horizonte_eleitoral.domain.errors import (
    ArtifactNotFoundError,
    ArtifactStorageError,
    ImmutableWriteError,
    SnapshotConflictError,
)
from horizonte_eleitoral.domain.identity import canonical_json_bytes, require_sha256, sha256_hex
from horizonte_eleitoral.domain.models import (
    CountSnapshot,
    LineageRecord,
    RawArtifact,
    RawArtifactRequest,
)
from horizonte_eleitoral.storage.serialization import (
    lineage_from_dict,
    raw_artifact_from_dict,
    snapshot_from_dict,
)


class LocalArtifactStore:
    """Cofre de arquivos local que deduplica corpos por hash e nunca os sobrescreve."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def store(self, request: RawArtifactRequest) -> RawArtifact:
        """Armazena corpo e manifesto de uma resposta sem realizar I/O de rede."""
        body_path = self._body_path(request.content_sha256)
        self._write_immutable(body_path, request.body, ImmutableWriteError)
        artifact = RawArtifact.from_request(
            request,
            storage_path=body_path.relative_to(self._root).as_posix(),
        )
        manifest_path = self._manifest_path(artifact.artifact_id)
        self._write_immutable(
            manifest_path, canonical_json_bytes(artifact.to_dict()), ImmutableWriteError
        )
        return artifact

    def get(self, artifact_id: str) -> RawArtifact:
        """Reabre um manifesto e valida a entidade ao desserializa-la."""
        value = self._read_json(self._manifest_path(artifact_id), artifact_id)
        return raw_artifact_from_dict(value)

    def read_body(self, artifact: RawArtifact) -> bytes:
        """Le o corpo do artefato e confirma que seu hash permanece inalterado."""
        body_path = self._safe_path(artifact.storage_path)
        try:
            body = body_path.read_bytes()
        except FileNotFoundError as error:
            raise ArtifactNotFoundError(
                f"Corpo do artefato {artifact.artifact_id} nao foi encontrado."
            ) from error
        except OSError as error:
            raise ArtifactStorageError(
                f"Falha ao ler corpo do artefato {artifact.artifact_id}."
            ) from error
        if sha256_hex(body) != artifact.content_sha256:
            raise ImmutableWriteError(
                f"O corpo do artefato {artifact.artifact_id} falhou na verificacao SHA-256."
            )
        return body

    def _body_path(self, content_sha256: str) -> Path:
        require_sha256(content_sha256, "content_sha256")
        return self._root / "raw" / "sha256" / content_sha256[:2] / f"{content_sha256}.blob"

    def _manifest_path(self, artifact_id: str) -> Path:
        return (
            self._root / "raw" / "manifests" / f"{_identifier_digest(artifact_id, 'artifact')}.json"
        )

    def _safe_path(self, relative_path: str) -> Path:
        candidate = (self._root / relative_path).resolve()
        if not candidate.is_relative_to(self._root):
            raise ArtifactStorageError(
                "O caminho persistido do artefato escapa do cofre configurado."
            )
        return candidate

    def _read_json(self, path: Path, identifier: str) -> dict[str, object]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise ArtifactNotFoundError(f"Registro {identifier} nao foi encontrado.") from error
        except (OSError, json.JSONDecodeError) as error:
            raise ArtifactStorageError(f"Registro {identifier} nao pode ser lido.") from error
        if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
            raise ArtifactStorageError(f"Registro {identifier} possui formato JSON invalido.")
        return cast(dict[str, object], value)

    @staticmethod
    def _write_immutable(
        path: Path,
        content: bytes,
        error_type: type[ImmutableWriteError],
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as destination:
                destination.write(content)
        except FileExistsError:
            try:
                existing = path.read_bytes()
            except OSError as error:
                raise ArtifactStorageError(
                    f"Falha ao verificar arquivo imutavel {path}."
                ) from error
            if existing != content:
                raise error_type(f"Tentativa de substituir conteudo imutavel em {path}.") from None
        except OSError as error:
            raise ArtifactStorageError(f"Falha ao persistir arquivo imutavel {path}.") from error


class FileLineageRepository:
    """Repositorio local append-only de registros de lineage."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def save(self, lineage: LineageRecord) -> LineageRecord:
        """Persiste lineage sem permitir alterar um ID ja existente."""
        path = self._path(lineage.lineage_id)
        LocalArtifactStore._write_immutable(
            path, canonical_json_bytes(lineage.to_dict()), ImmutableWriteError
        )
        return lineage

    def get(self, lineage_id: str) -> LineageRecord:
        """Reabre lineage persistido e valida sua forma canonica."""
        value = _read_record(self._path(lineage_id), lineage_id)
        return lineage_from_dict(value)

    def _path(self, lineage_id: str) -> Path:
        return self._root / "lineage" / f"{_identifier_digest(lineage_id, 'lineage')}.json"


class FileSnapshotRepository:
    """Repositorio local de snapshots cujo ID resulta dos hashes e versoes de entrada."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def save(self, snapshot: CountSnapshot) -> CountSnapshot:
        """Persiste ou reusa um snapshot identico; rejeita colisao de mesmo ID."""
        path = self._path(snapshot.snapshot_id)
        try:
            LocalArtifactStore._write_immutable(
                path,
                canonical_json_bytes(snapshot.to_dict()),
                _SnapshotImmutableWriteError,
            )
        except _SnapshotImmutableWriteError as error:
            raise SnapshotConflictError(
                f"O snapshot {snapshot.snapshot_id} ja existe com outro conteudo."
            ) from error
        return snapshot

    def get(self, snapshot_id: str) -> CountSnapshot:
        """Reabre snapshot persistido e valida suas invariantes."""
        value = _read_record(self._path(snapshot_id), snapshot_id)
        return snapshot_from_dict(value)

    def _path(self, snapshot_id: str) -> Path:
        return self._root / "snapshots" / f"{_identifier_digest(snapshot_id, 'snapshot')}.json"


class _SnapshotImmutableWriteError(ImmutableWriteError):
    """Sinal interno para converter conflito de escrita em erro de snapshot."""


def _identifier_digest(identifier: str, namespace: str) -> str:
    prefix = f"{namespace}:"
    if not identifier.startswith(prefix):
        raise ArtifactStorageError(f"Identificador deve iniciar com {prefix}.")
    return require_sha256(identifier.removeprefix(prefix), "identifier digest")


def _read_record(path: Path, identifier: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ArtifactNotFoundError(f"Registro {identifier} nao foi encontrado.") from error
    except (OSError, json.JSONDecodeError) as error:
        raise ArtifactStorageError(f"Registro {identifier} nao pode ser lido.") from error
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ArtifactStorageError(f"Registro {identifier} possui formato JSON invalido.")
    return cast(dict[str, object], value)
