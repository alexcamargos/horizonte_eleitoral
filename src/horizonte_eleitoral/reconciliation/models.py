"""Modelos imutaveis para relatorios de reconciliacao de apuracao."""

from __future__ import annotations

from dataclasses import dataclass

from horizonte_eleitoral.domain.enums import SnapshotStatus
from horizonte_eleitoral.domain.errors import InvariantViolationError


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """Diagnostico detalhado da consistencia entre inventario de secoes e totalizacao de votos.

    Attributes:
        status: Status consolidado do snapshot (CONSISTENT ou DIVERGENT).
        total_sections: Total de secoes avaliadas.
        totalized_sections: Secoes que figuram como apuradas.
        divergent_sections: Secoes com estados conflitantes de versao ou contagem.
        unmatched_sections: Secoes sem pareamento historico aceitavel.
        stale_seconds: Defasagem em segundos entre a observacao e a geracao do artefato.
        diagnostics: Pares (chave, detalhe) explicando possiveis anomalias detectadas.
    """

    status: SnapshotStatus
    total_sections: int
    totalized_sections: int
    divergent_sections: int
    unmatched_sections: int
    stale_seconds: int
    diagnostics: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        """Valida que valores de contagem sao nao negativos.

        Raises:
            InvariantViolationError: Se alguma contagem for negativa.
        """
        for field_name in (
            "total_sections",
            "totalized_sections",
            "divergent_sections",
            "unmatched_sections",
            "stale_seconds",
        ):
            if getattr(self, field_name) < 0:
                raise InvariantViolationError(f"{field_name} nao pode ser negativo.")

    @property
    def is_consistent(self) -> bool:
        """Indica se a reconciliacao autoriza publicacao ou avanco para o modelo.

        Returns:
            True se o status for CONSISTENT e nao houver divergencias impeditivas.
        """
        return self.status is SnapshotStatus.CONSISTENT and self.divergent_sections == 0
