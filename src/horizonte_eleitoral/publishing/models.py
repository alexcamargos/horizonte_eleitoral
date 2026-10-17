"""Modelos para representacao imutavel do payload publicado de projecao."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from horizonte_eleitoral.domain.errors import InvariantViolationError


@dataclass(frozen=True, slots=True)
class GroupProjectionDetail:
    """Estimativa de um grupo politico individual no payload publicado.

    Attributes:
        code: Codigo do grupo (e.g. 'PT', 'PL', 'OUTROS').
        observed_share: Participacao apurada observada em percentual [0, 100].
        projected_share: Participacao projetada central em percentual [0, 100].
        q05: Limite inferior do IC 90% em percentual [0, 100].
        q95: Limite superior do IC 90% em percentual [0, 100].
    """

    code: str
    observed_share: float
    projected_share: float
    q05: float
    q95: float

    def to_dict(self) -> dict[str, object]:
        """Converte para dicionario para serializacao externa."""
        return {
            "code": self.code,
            "observed_share": round(self.observed_share, 2),
            "projected_share": round(self.projected_share, 2),
            "q05": round(self.q05, 2),
            "q95": round(self.q95, 2),
        }


@dataclass(frozen=True, slots=True)
class PublishedProjectionPayload:
    """Contrato publicavel consolidado exposto pela API e consumido pelo dashboard.

    Attributes:
        projection_id: Identificador unico e determinista da projecao.
        published_at: Timestamp UTC da publicacao atomica.
        data_observed_at: Timestamp UTC da observacao dos dados brutos.
        status: Situacao da publicacao ('published').
        totalized_electorate_pct: Percentual do eleitorado ja apurado [0, 100].
        groups: Tupla com os detalhes projetados por grupo politico.
        second_round_probability: Probabilidade de segundo turno [0, 1].
        data_quality: Dicionario com secoes consistentes, divergentes e defasagem.
        model_version: Versao semantica do modelo preditivo empregado.
        snapshot_id: Identificador do snapshot de contagem utilizado.
    """

    projection_id: str
    published_at: datetime
    data_observed_at: datetime
    status: str
    totalized_electorate_pct: float
    groups: tuple[GroupProjectionDetail, ...]
    second_round_probability: float
    data_quality: dict[str, int]
    model_version: str
    snapshot_id: str

    def __post_init__(self) -> None:
        """Valida que percentuais estao na escala [0, 100].

        Raises:
            InvariantViolationError: Se os percentuais extrapolarem os limites.
        """
        if not 0.0 <= self.totalized_electorate_pct <= 100.0:
            raise InvariantViolationError("totalized_electorate_pct deve estar entre 0 e 100.")
        if not 0.0 <= self.second_round_probability <= 1.0:
            raise InvariantViolationError("second_round_probability deve estar entre 0 e 1.")

    def to_dict(self) -> dict[str, object]:
        """Serializacao em conformidade estrita com o exemplo da especificacao tecnica."""
        return {
            "projection_id": self.projection_id,
            "published_at": self.published_at.isoformat(),
            "data_observed_at": self.data_observed_at.isoformat(),
            "status": self.status,
            "totalized_electorate_pct": round(self.totalized_electorate_pct, 2),
            "groups": [g.to_dict() for g in self.groups],
            "second_round_probability": round(self.second_round_probability, 4),
            "data_quality": self.data_quality,
            "model_version": self.model_version,
            "snapshot_id": self.snapshot_id,
        }
