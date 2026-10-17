"""Entidades imutaveis e validacoes centrais do dominio eleitoral."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import urlsplit

from horizonte_eleitoral.domain.enums import ArtifactType, GeographicScope, SnapshotStatus
from horizonte_eleitoral.domain.errors import InvariantViolationError, ValidationError
from horizonte_eleitoral.domain.identity import deterministic_id, require_sha256, sha256_hex

SHARE_TOLERANCE = Decimal("0.000001")


def _external_identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValidationError(f"{field_name} deve ser texto nao vazio, sem espacos externos.")
    return value


def _utc_timestamp(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError(f"{field_name} deve conter fuso horario.")
    return value.astimezone(UTC)


def _non_negative(value: int, field_name: str) -> int:
    if value < 0:
        raise InvariantViolationError(f"{field_name} nao pode ser negativo.")
    return value


@dataclass(frozen=True, slots=True)
class ElectionKey:
    """Identificador natural da eleicao, turno e cargo sem conversao numerica."""

    election_id: str
    round_number: str
    office: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "election_id", _external_identifier(self.election_id, "election_id")
        )
        object.__setattr__(
            self, "round_number", _external_identifier(self.round_number, "round_number")
        )
        object.__setattr__(self, "office", _external_identifier(self.office, "office"))

    def to_dict(self) -> dict[str, str]:
        """Retorna representacao estavel para persistencia e identificadores."""
        return {
            "election_id": self.election_id,
            "round_number": self.round_number,
            "office": self.office,
        }


@dataclass(frozen=True, slots=True)
class MunicipalityKey:
    """Chave de municipio que conserva codigos externos como texto."""

    state: str
    municipality_code: str

    def __post_init__(self) -> None:
        state = _external_identifier(self.state, "state").upper()
        if len(state) != 2 or not state.isalpha():
            raise ValidationError("state deve ser uma UF de duas letras.")
        object.__setattr__(self, "state", state)
        object.__setattr__(
            self,
            "municipality_code",
            _external_identifier(self.municipality_code, "municipality_code"),
        )

    def to_dict(self) -> dict[str, str]:
        """Retorna representacao estavel para persistencia e identificadores."""
        return {"state": self.state, "municipality_code": self.municipality_code}


@dataclass(frozen=True, slots=True)
class SectionKey:
    """Chave completa de uma secao eleitoral, com zona e secao textuais."""

    election: ElectionKey
    municipality: MunicipalityKey
    zone: str
    section: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "zone", _external_identifier(self.zone, "zone"))
        object.__setattr__(self, "section", _external_identifier(self.section, "section"))

    def to_dict(self) -> dict[str, object]:
        """Retorna a chave completa, sem remover zeros a esquerda."""
        return {
            "election": self.election.to_dict(),
            "municipality": self.municipality.to_dict(),
            "zone": self.zone,
            "section": self.section,
        }


@dataclass(frozen=True, slots=True)
class CandidateGroup:
    """Grupo estatistico versionado de uma candidatura."""

    candidate_id: str
    group_code: str
    taxonomy_version: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "candidate_id", _external_identifier(self.candidate_id, "candidate_id")
        )
        object.__setattr__(self, "group_code", _external_identifier(self.group_code, "group_code"))
        object.__setattr__(
            self,
            "taxonomy_version",
            _external_identifier(self.taxonomy_version, "taxonomy_version"),
        )


@dataclass(frozen=True, slots=True)
class VoteDistribution:
    """Participacoes por grupo, com soma validada e sem contagens derivadas."""

    shares: tuple[tuple[str, Decimal], ...]

    def __post_init__(self) -> None:
        if not self.shares:
            raise InvariantViolationError("Uma distribuicao deve possuir ao menos um grupo.")
        codes = [code for code, _ in self.shares]
        if len(set(codes)) != len(codes):
            raise InvariantViolationError("Uma distribuicao nao pode repetir group_code.")
        total = Decimal()
        for code, share in self.shares:
            _external_identifier(code, "group_code")
            if not isinstance(share, Decimal) or share < 0 or share > 1:
                raise InvariantViolationError("Cada share deve ser Decimal entre zero e um.")
            total += share
        if abs(total - Decimal(1)) > SHARE_TOLERANCE:
            raise InvariantViolationError("Os shares devem somar um dentro da tolerancia definida.")
        object.__setattr__(self, "shares", tuple(sorted(self.shares, key=lambda item: item[0])))


@dataclass(frozen=True, slots=True)
class RawArtifactRequest:
    """Resposta recebida que ainda sera persistida em um cofre imutavel."""

    election_id: str
    artifact_type: ArtifactType
    source_url: str
    collected_at: datetime
    http_status: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()
    suffix: str = ".json"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "election_id", _external_identifier(self.election_id, "election_id")
        )
        parsed_url = urlsplit(self.source_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise ValidationError("source_url deve ser uma URL HTTPS absoluta.")
        object.__setattr__(self, "collected_at", _utc_timestamp(self.collected_at, "collected_at"))
        if not 100 <= self.http_status <= 599:
            raise ValidationError("http_status deve estar entre 100 e 599.")
        if not isinstance(self.body, bytes):
            raise ValidationError("body deve ser bytes.")
        if not self.suffix.startswith(".") or len(self.suffix) > 16 or "/" in self.suffix:
            raise ValidationError("suffix deve ser uma extensao de arquivo simples.")
        normalized_headers = tuple(sorted(self.headers, key=lambda item: item[0].lower()))
        for name, value in normalized_headers:
            _external_identifier(name, "header name")
            _external_identifier(value, "header value")
        object.__setattr__(self, "headers", normalized_headers)

    @property
    def content_sha256(self) -> str:
        """Calcula o hash do corpo exato recebido."""
        return sha256_hex(self.body)

    def identity_payload(self) -> dict[str, object]:
        """Retorna todos os metadados que distinguem respostas recebidas."""
        return {
            "election_id": self.election_id,
            "artifact_type": self.artifact_type.value,
            "source_url": self.source_url,
            "collected_at": self.collected_at,
            "http_status": self.http_status,
            "headers": self.headers,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True, slots=True)
class RawArtifact:
    """Metadados auditaveis de uma resposta, separados do corpo deduplicado."""

    artifact_id: str
    election_id: str
    artifact_type: ArtifactType
    source_url: str
    collected_at: datetime
    http_status: int
    content_sha256: str
    size_bytes: int
    headers: tuple[tuple[str, str], ...]
    storage_path: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _external_identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self, "election_id", _external_identifier(self.election_id, "election_id")
        )
        object.__setattr__(self, "collected_at", _utc_timestamp(self.collected_at, "collected_at"))
        require_sha256(self.content_sha256, "content_sha256")
        _non_negative(self.size_bytes, "size_bytes")
        _external_identifier(self.storage_path, "storage_path")

    @classmethod
    def from_request(cls, request: RawArtifactRequest, storage_path: str) -> RawArtifact:
        """Cria metadados com identificador estavel para a resposta recebida."""
        return cls(
            artifact_id=deterministic_id("artifact", request.identity_payload()),
            election_id=request.election_id,
            artifact_type=request.artifact_type,
            source_url=request.source_url,
            collected_at=request.collected_at,
            http_status=request.http_status,
            content_sha256=request.content_sha256,
            size_bytes=len(request.body),
            headers=request.headers,
            storage_path=storage_path,
        )

    def to_dict(self) -> dict[str, object]:
        """Retorna representacao imutavel para o manifesto do cofre."""
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type.value,
            "collected_at": self.collected_at,
            "content_sha256": self.content_sha256,
            "election_id": self.election_id,
            "headers": self.headers,
            "http_status": self.http_status,
            "size_bytes": self.size_bytes,
            "source_url": self.source_url,
            "storage_path": self.storage_path,
        }


@dataclass(frozen=True, slots=True)
class LineageRecord:
    """Relacao determinista entre uma saida e os hashes que a produziram."""

    lineage_id: str
    output_type: str
    output_id: str
    input_hashes: tuple[str, ...]
    code_version: str
    configuration_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "lineage_id", _external_identifier(self.lineage_id, "lineage_id"))
        object.__setattr__(
            self, "output_type", _external_identifier(self.output_type, "output_type")
        )
        object.__setattr__(self, "output_id", _external_identifier(self.output_id, "output_id"))
        object.__setattr__(
            self, "code_version", _external_identifier(self.code_version, "code_version")
        )
        require_sha256(self.configuration_hash, "configuration_hash")
        normalized_hashes = tuple(sorted(set(self.input_hashes)))
        if not normalized_hashes:
            raise InvariantViolationError("Lineage deve apontar para ao menos um hash de entrada.")
        for input_hash in normalized_hashes:
            require_sha256(input_hash, "input_hashes")
        object.__setattr__(self, "input_hashes", normalized_hashes)

    @classmethod
    def create(
        cls,
        *,
        output_type: str,
        output_id: str,
        input_hashes: Iterable[str],
        code_version: str,
        configuration_hash: str,
    ) -> LineageRecord:
        """Constroi um registro com o mesmo ID para os mesmos insumos logicos."""
        normalized_hashes = tuple(sorted(set(input_hashes)))
        payload = {
            "output_type": output_type,
            "output_id": output_id,
            "input_hashes": normalized_hashes,
            "code_version": code_version,
            "configuration_hash": configuration_hash,
        }
        return cls(
            lineage_id=deterministic_id("lineage", payload),
            output_type=output_type,
            output_id=output_id,
            input_hashes=normalized_hashes,
            code_version=code_version,
            configuration_hash=configuration_hash,
        )

    def to_dict(self) -> dict[str, object]:
        """Retorna representacao estavel para persistencia."""
        return {
            "code_version": self.code_version,
            "configuration_hash": self.configuration_hash,
            "input_hashes": self.input_hashes,
            "lineage_id": self.lineage_id,
            "output_id": self.output_id,
            "output_type": self.output_type,
        }


@dataclass(frozen=True, slots=True)
class CountSnapshot:
    """Snapshot reconciliado cuja identidade depende somente dos insumos definidos no plano."""

    snapshot_id: str
    observed_at: datetime
    status: SnapshotStatus
    total_electorate: int
    totalized_electorate: int
    pending_electorate: int
    artifact_hashes: tuple[str, ...]
    normalizer_version: str
    reconciliation_rule_version: str
    diagnostics: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "snapshot_id", _external_identifier(self.snapshot_id, "snapshot_id")
        )
        object.__setattr__(self, "observed_at", _utc_timestamp(self.observed_at, "observed_at"))
        _non_negative(self.total_electorate, "total_electorate")
        _non_negative(self.totalized_electorate, "totalized_electorate")
        _non_negative(self.pending_electorate, "pending_electorate")
        if self.totalized_electorate + self.pending_electorate != self.total_electorate:
            raise InvariantViolationError(
                "totalized_electorate e pending_electorate devem compor total_electorate."
            )
        object.__setattr__(
            self,
            "normalizer_version",
            _external_identifier(self.normalizer_version, "normalizer_version"),
        )
        object.__setattr__(
            self,
            "reconciliation_rule_version",
            _external_identifier(self.reconciliation_rule_version, "reconciliation_rule_version"),
        )
        normalized_hashes = tuple(sorted(set(self.artifact_hashes)))
        if not normalized_hashes:
            raise InvariantViolationError("Snapshot deve referenciar ao menos um hash de artefato.")
        for artifact_hash in normalized_hashes:
            require_sha256(artifact_hash, "artifact_hashes")
        object.__setattr__(self, "artifact_hashes", normalized_hashes)
        object.__setattr__(self, "diagnostics", tuple(sorted(self.diagnostics)))

    @classmethod
    def create(
        cls,
        *,
        observed_at: datetime,
        status: SnapshotStatus,
        total_electorate: int,
        totalized_electorate: int,
        pending_electorate: int,
        artifact_hashes: Iterable[str],
        normalizer_version: str,
        reconciliation_rule_version: str,
        diagnostics: tuple[tuple[str, str], ...] = (),
    ) -> CountSnapshot:
        """Constroi o ID a partir de hashes ordenados e versoes de normalizacao/reconciliacao."""
        normalized_hashes = tuple(sorted(set(artifact_hashes)))
        identity = {
            "artifact_hashes": normalized_hashes,
            "normalizer_version": normalizer_version,
            "reconciliation_rule_version": reconciliation_rule_version,
        }
        return cls(
            snapshot_id=deterministic_id("snapshot", identity),
            observed_at=observed_at,
            status=status,
            total_electorate=total_electorate,
            totalized_electorate=totalized_electorate,
            pending_electorate=pending_electorate,
            artifact_hashes=normalized_hashes,
            normalizer_version=normalizer_version,
            reconciliation_rule_version=reconciliation_rule_version,
            diagnostics=diagnostics,
        )

    def to_dict(self) -> dict[str, object]:
        """Retorna representacao estavel para persistencia."""
        return {
            "artifact_hashes": self.artifact_hashes,
            "diagnostics": self.diagnostics,
            "normalizer_version": self.normalizer_version,
            "observed_at": self.observed_at,
            "pending_electorate": self.pending_electorate,
            "reconciliation_rule_version": self.reconciliation_rule_version,
            "snapshot_id": self.snapshot_id,
            "status": self.status.value,
            "total_electorate": self.total_electorate,
            "totalized_electorate": self.totalized_electorate,
        }


@dataclass(frozen=True, slots=True)
class ProjectionRun:
    """Contrato de identificacao de uma execucao de projecao reproduzivel."""

    projection_id: str
    snapshot_id: str
    model_version: str
    feature_version: str
    taxonomy_version: str
    simulation_configuration_hash: str
    seed: int

    def __post_init__(self) -> None:
        for field_name in (
            "projection_id",
            "snapshot_id",
            "model_version",
            "feature_version",
            "taxonomy_version",
        ):
            _external_identifier(getattr(self, field_name), field_name)
        require_sha256(self.simulation_configuration_hash, "simulation_configuration_hash")
        _non_negative(self.seed, "seed")


@dataclass(frozen=True, slots=True)
class Publication:
    """Contrato minimo de uma versao publicada de forma atomica em fase posterior."""

    publication_id: str
    projection_id: str
    published_at: datetime
    payload_sha256: str

    def __post_init__(self) -> None:
        _external_identifier(self.publication_id, "publication_id")
        _external_identifier(self.projection_id, "projection_id")
        object.__setattr__(self, "published_at", _utc_timestamp(self.published_at, "published_at"))
        require_sha256(self.payload_sha256, "payload_sha256")


@dataclass(frozen=True, slots=True)
class OfficialResult:
    """Resultado canonico minimo para a porta de persistencia, sem campos EA externos."""

    scope: GeographicScope
    source_artifact_id: str
    valid_votes: int
    blank_votes: int
    null_votes: int

    def __post_init__(self) -> None:
        _external_identifier(self.source_artifact_id, "source_artifact_id")
        _non_negative(self.valid_votes, "valid_votes")
        _non_negative(self.blank_votes, "blank_votes")
        _non_negative(self.null_votes, "null_votes")
