"""Portas tipadas entre o nucleo de dominio e adaptadores de infraestrutura."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from horizonte_eleitoral.domain.models import (
    CountSnapshot,
    OfficialResult,
    ProjectionRun,
    RawArtifact,
    RawArtifactRequest,
)


class ArtifactStore(Protocol):
    """Contrato para cofre de corpos brutos e seus manifestos imutaveis."""

    def store(self, request: RawArtifactRequest) -> RawArtifact:
        """Persiste resposta sem sobrescrever um corpo ou manifesto existente."""

    def get(self, artifact_id: str) -> RawArtifact:
        """Reabre metadados previamente persistidos."""

    def read_body(self, artifact: RawArtifact) -> bytes:
        """Retorna o corpo e valida sua integridade antes de entrega-lo."""


class ResultRepository(Protocol):
    """Contrato para resultados normalizados, desacoplado do banco escolhido."""

    def append(self, result: OfficialResult) -> None:
        """Acrescenta uma observacao normalizada sem misturar escopos."""


class SnapshotRepository(Protocol):
    """Contrato para snapshots reconciliados de identidade determinista."""

    def save(self, snapshot: CountSnapshot) -> CountSnapshot:
        """Persiste ou retorna um snapshot identico; rejeita colisao de conteudo."""

    def get(self, snapshot_id: str) -> CountSnapshot:
        """Reabre um snapshot pelo identificador determinista."""


class ProjectionRepository(Protocol):
    """Contrato para metadados de execucoes de projecao."""

    def save(self, projection: ProjectionRun) -> ProjectionRun:
        """Persiste uma execucao de projecao versionada."""

    def get(self, projection_id: str) -> ProjectionRun:
        """Reabre uma execucao de projecao por seu identificador."""


class Clock(Protocol):
    """Fonte de tempo injetavel para tornar operacoes testaveis."""

    def now(self) -> datetime:
        """Retorna instante atual com fuso horario."""


class TSEClient(Protocol):
    """Porta assincrona para uma fonte oficial, sem dependencia de HTTPX no dominio."""

    async def fetch(self, request: RawArtifactRequest) -> RawArtifactRequest:
        """Retorna uma resposta validada para posterior persistencia."""
