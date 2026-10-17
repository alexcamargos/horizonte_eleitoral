"""Contratos canonicos e estruturas de dados comuns para modelos de projecao."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from horizonte_eleitoral.domain.errors import InvariantViolationError


@dataclass(frozen=True, slots=True)
class SectionObservation:
    """Dados observados de uma secao eleitoral ja totalizada.

    Attributes:
        section_id: Identificador unico da secao (e.g. 'SP:71072:0001:0007').
        state: Sigla da Unidade Federativa.
        municipality_code: Codigo do municipio.
        valid_votes: Total de votos validos computados.
        group_votes: Votos validos computados por grupo partidario.
        historical_shares: Participacoes historicas de 2022 desta mesma secao.
    """

    section_id: str
    state: str
    municipality_code: str
    valid_votes: int
    group_votes: tuple[tuple[str, int], ...]
    historical_shares: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        """Valida se as contagens de votos sao nao negativas.

        Raises:
            InvariantViolationError: Se valid_votes for negativo.
        """
        if self.valid_votes < 0:
            raise InvariantViolationError("valid_votes nao pode ser negativo.")


@dataclass(frozen=True, slots=True)
class PendingSection:
    """Informacoes de uma secao eleitoral ainda pendente de apuracao.

    Attributes:
        section_id: Identificador unico da secao.
        state: Sigla da Unidade Federativa.
        municipality_code: Codigo do municipio.
        electorate: Total de eleitores aptos a votar na secao.
        historical_shares: Distribuicao de participacao historica base de 2022.
        expected_turnout_rate: Taxa esperada de comparecimento (default 0.80).
        expected_valid_rate: Proporcao esperada de votos validos no comparecimento (default 0.95).
    """

    section_id: str
    state: str
    municipality_code: str
    electorate: int
    historical_shares: tuple[tuple[str, float], ...]
    expected_turnout_rate: float = 0.80
    expected_valid_rate: float = 0.95

    def __post_init__(self) -> None:
        """Valida que eleitorado e taxas sao coerentes.

        Raises:
            InvariantViolationError: Se eleitorado for negativo ou taxas fora de [0, 1].
        """
        if self.electorate < 0:
            raise InvariantViolationError("electorate nao pode ser negativo.")
        if not 0.0 <= self.expected_turnout_rate <= 1.0:
            raise InvariantViolationError("expected_turnout_rate deve estar entre 0.0 e 1.0.")
        if not 0.0 <= self.expected_valid_rate <= 1.0:
            raise InvariantViolationError("expected_valid_rate deve estar entre 0.0 e 1.0.")


@dataclass(frozen=True, slots=True)
class ForecastResult:
    """Resultado imutavel de uma rodada de projecao eleitoral.

    Attributes:
        model_name: Nome do algoritmo que gerou a previsao.
        projected_shares: Projecao final consolidada da participacao de cada grupo (somando 1.0).
        projected_votes: Total absoluto projetado de votos para cada grupo.
        observed_shares: Participacao observada ate o momento (apurado bruto).
        total_projected_valid: Soma total estimada de votos validos no pais.
    """

    model_name: str
    projected_shares: tuple[tuple[str, float], ...]
    projected_votes: tuple[tuple[str, int], ...]
    observed_shares: tuple[tuple[str, float], ...]
    total_projected_valid: int

    def __post_init__(self) -> None:
        """Valida que os shares projetados somam aproximadamente 1.0.

        Raises:
            InvariantViolationError: Se a soma dos shares divergir de 1.0.
        """
        total = sum(s for _, s in self.projected_shares)
        if abs(total - 1.0) > 1e-4:
            raise InvariantViolationError(
                f"Shares projetados devem somar 1.0 (soma encontrada: {total:.4f})."
            )


class ForecastModel(Protocol):
    """Contrato que qualquer algoritmo de projecao deve satisfazer."""

    def predict(
        self,
        *,
        observations: list[SectionObservation],
        pending: list[PendingSection],
        groups: tuple[str, ...] = ("PT", "PL", "OUTROS"),
    ) -> ForecastResult:
        """Gera uma projecao eleitoral a partir das secoes observadas e pendentes.

        Args:
            observations: Lista de secoes ja apuradas com votos e base historica.
            pending: Lista de secoes ainda pendentes de apuracao.
            groups: Codigos dos grupos eleitorais avaliados.

        Returns:
            ForecastResult com shares projetados somando 1.0.
        """
