"""Adaptadores locais de persistencia imutavel usados pela fundacao."""

from horizonte_eleitoral.storage.local import (
    FileLineageRepository,
    FileSnapshotRepository,
    LocalArtifactStore,
)

__all__ = ["FileLineageRepository", "FileSnapshotRepository", "LocalArtifactStore"]
