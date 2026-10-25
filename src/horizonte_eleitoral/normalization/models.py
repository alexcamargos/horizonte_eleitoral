"""Modelos canonicos normalizados a partir dos artefatos oficiais do TSE."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from horizonte_eleitoral.domain.enums import GeographicScope
from horizonte_eleitoral.domain.errors import InvariantViolationError, ValidationError


@dataclass(frozen=True, slots=True)
class NormalizedSectionState:
    """Estado auditavel de uma secao eleitoral individual (derivado de EA16 ou EA18).

    Attributes:
        state: Unidade Federativa da secao.
        municipality_code: Codigo do municipio segundo o TSE.
        zone: Numero da zona eleitoral.
        section: Numero da secao eleitoral.
        generation_timestamp: Data e hora do arquivo de urna ou geracao do dado.
        generation_hash: Hash identificador da urna (`ha`) ou versao do pacote.
        is_totalized: Indica se a secao ja foi contabilizada na apuracao oficial.
    """

    state: str
    municipality_code: str
    zone: str
    section: str
    generation_timestamp: datetime | None
    generation_hash: str
    is_totalized: bool

    def __post_init__(self) -> None:
        """Valida que campos textuais nao sao vazios.

        Raises:
            ValidationError: Se algum identificador obrigatorio for invalido.
        """
        if not self.state or len(self.state) != 2:
            raise ValidationError("state deve ser uma sigla de UF valida.")
        if not self.municipality_code:
            raise ValidationError("municipality_code nao pode ser vazio.")
        if not self.zone:
            raise ValidationError("zone nao pode ser vazia.")
        if not self.section:
            raise ValidationError("section nao pode ser vazia.")


@dataclass(frozen=True, slots=True)
class NormalizedTotalization:
    """Resultado oficial normalizado de votos de uma abrangencia (EA20).

    Attributes:
        scope: Escopo geografico da totalizacao (BR, UF, MUNICIPIO).
        scope_code: Codigo do escopo (e.g. 'BR', 'SP', '71072').
        total_electorate: Eleitorado total apto no escopo.
        totalized_electorate: Eleitorado correspondente as secoes ja totalizadas.
        pending_electorate: Eleitorado de secoes ainda pendentes.
        total_sections: Total de secoes eleitorais do escopo.
        totalized_sections: Numero de secoes ja totalizadas.
        pending_sections: Numero de secoes pendentes de apuracao.
        valid_votes: Total de votos validos computados.
        blank_votes: Total de votos em branco computados.
        null_votes: Total de votos nulos computados.
        candidate_group_votes: Mapeamento de group_code (e.g. 'PT', 'PL', 'OUTROS') para votos.
    """

    scope: GeographicScope
    scope_code: str
    total_electorate: int
    totalized_electorate: int
    pending_electorate: int
    total_sections: int
    totalized_sections: int
    pending_sections: int
    valid_votes: int
    blank_votes: int
    null_votes: int
    candidate_group_votes: tuple[tuple[str, int], ...]
    generation_time: str | None = None

    def __post_init__(self) -> None:
        """Valida invariantes essenciais de totalizacao.

        Raises:
            InvariantViolationError: Se as contagens forem negativas ou inconsistentes.
        """
        for field_name in (
            "total_electorate",
            "totalized_electorate",
            "pending_electorate",
            "total_sections",
            "totalized_sections",
            "pending_sections",
            "valid_votes",
            "blank_votes",
            "null_votes",
        ):
            value = getattr(self, field_name)
            if value < 0:
                raise InvariantViolationError(f"{field_name} nao pode ser negativo.")

        if self.totalized_electorate + self.pending_electorate != self.total_electorate:
            raise InvariantViolationError(
                "totalized_electorate e pending_electorate devem somar total_electorate."
            )
        if self.totalized_sections + self.pending_sections != self.total_sections:
            raise InvariantViolationError(
                "totalized_sections e pending_sections devem somar total_sections."
            )

        sum_candidates = sum(v for _, v in self.candidate_group_votes)
        if self.valid_votes > 0 and sum_candidates != self.valid_votes:
            raise InvariantViolationError(
                f"Soma dos votos por grupo ({sum_candidates}) deve "
                f"igualar valid_votes ({self.valid_votes})."
            )
