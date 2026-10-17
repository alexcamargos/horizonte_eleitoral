"""Tipos puros, invariantes e contratos de dominio."""

from horizonte_eleitoral.domain.enums import (
    ArtifactType,
    GeographicScope,
    MatchQuality,
    ProcessingState,
    SnapshotStatus,
)
from horizonte_eleitoral.domain.models import (
    CandidateGroup,
    CountSnapshot,
    ElectionKey,
    LineageRecord,
    MunicipalityKey,
    RawArtifact,
    RawArtifactRequest,
    SectionKey,
)

__all__ = [
    "ArtifactType",
    "CandidateGroup",
    "CountSnapshot",
    "ElectionKey",
    "GeographicScope",
    "LineageRecord",
    "MatchQuality",
    "MunicipalityKey",
    "ProcessingState",
    "RawArtifact",
    "RawArtifactRequest",
    "SectionKey",
    "SnapshotStatus",
]
