"""Modelos imutaveis para representacao da base historica e pareamento eleitoral."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from horizonte_eleitoral.domain.enums import MatchQuality
from horizonte_eleitoral.domain.errors import InvariantViolationError, ValidationError
from horizonte_eleitoral.domain.models import SectionKey


def _check_not_empty(value: str, field_name: str) -> str:
    """Valida se uma string de identificador e nao vazia e sem espacos externos.

    Args:
        value: Valor de texto a ser validado.
        field_name: Nome do campo para inclusao na mensagem de erro.

    Returns:
        O texto validado.

    Raises:
        ValidationError: Se o texto for vazio ou contiver espacos nas pontas.
    """
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValidationError(f"{field_name} deve ser texto nao vazio, sem espacos externos.")
    return value


def _check_non_negative_int(value: int, field_name: str) -> int:
    """Valida se um inteiro e nao negativo.

    Args:
        value: Inteiro a ser checado.
        field_name: Nome do campo.

    Returns:
        O inteiro validado.

    Raises:
        InvariantViolationError: Se o inteiro for menor que zero.
    """
    if value < 0:
        raise InvariantViolationError(f"{field_name} nao pode ser negativo.")
    return value


@dataclass(frozen=True, slots=True)
class HistoricalLocation:
    """Local de votacao historico (e.g. 2022) com coordenadas e cadastro.

    Attributes:
        location_id: Identificador unico do local de votacao.
        state: Unidade da Federacao (UF) em 2 letras maiusculas.
        municipality_code: Codigo do municipio segundo o cadastro eleitoral.
        zone: Numero da zona eleitoral preservando zeros a esquerda.
        local_code: Codigo do local de votacao na zona eleitoral.
        latitude: Latitude geografica decimal, se disponivel.
        longitude: Longitude geografica decimal, se disponivel.
        electorate: Total de eleitores cadastrados neste local historico.
    """

    location_id: str
    state: str
    municipality_code: str
    zone: str
    local_code: str
    latitude: float | None = None
    longitude: float | None = None
    electorate: int = 0

    def __post_init__(self) -> None:
        """Valida as invariantes do local historico.

        Raises:
            ValidationError: Se algum identificador for invalido.
            InvariantViolationError: Se o eleitorado for negativo.
        """
        object.__setattr__(self, "location_id", _check_not_empty(self.location_id, "location_id"))
        state = _check_not_empty(self.state, "state").upper()
        if len(state) != 2 or not state.isalpha():
            raise ValidationError("state deve ser uma UF de duas letras.")
        object.__setattr__(self, "state", state)
        object.__setattr__(
            self, "municipality_code", _check_not_empty(self.municipality_code, "municipality_code")
        )
        object.__setattr__(self, "zone", _check_not_empty(self.zone, "zone"))
        object.__setattr__(self, "local_code", _check_not_empty(self.local_code, "local_code"))
        _check_non_negative_int(self.electorate, "electorate")


@dataclass(frozen=True, slots=True)
class HistoricalVoteProfile:
    """Perfil de votos apurados de um local historico por grupo partidario.

    Attributes:
        location_id: Identificador do local historico associado.
        valid_votes: Total de votos validos computados neste local.
        turnout: Total de eleitores que compareceram a votacao.
        group_votes: Dicionario mapeando cada group_code para a contagem de votos validos.
    """

    location_id: str
    valid_votes: int
    turnout: int
    group_votes: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        """Valida se as contagens sao consistentes e nao negativas.

        Raises:
            ValidationError: Se o location_id for invalido.
            InvariantViolationError: Se votos forem negativos ou a soma discrepar.
        """
        object.__setattr__(self, "location_id", _check_not_empty(self.location_id, "location_id"))
        _check_non_negative_int(self.valid_votes, "valid_votes")
        _check_non_negative_int(self.turnout, "turnout")
        if self.valid_votes > self.turnout:
            raise InvariantViolationError("valid_votes nao pode exceder turnout.")

        total_voted = 0
        for code, votes in self.group_votes:
            _check_not_empty(code, "group_code")
            _check_non_negative_int(votes, f"votos de {code}")
            total_voted += votes

        if self.valid_votes > 0 and total_voted != self.valid_votes:
            raise InvariantViolationError(
                f"Soma dos votos por grupo ({total_voted}) deve "
                f"igualar valid_votes ({self.valid_votes})."
            )


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    """Candidata de pareamento historico para uma secao eleitoral.

    Attributes:
        candidate_location_id: Identificador do local historico candidato.
        method: Classe de qualidade do pareamento alcançado.
        distance_meters: Distancia fisica em metros, ou None para correspondencia por regiao.
        weight: Peso normalizado atribuido a esta candidata na composicao.
        rank: Classificacao ordinal da candidata entre os pares encontrados.
    """

    candidate_location_id: str
    method: MatchQuality
    distance_meters: float | None
    weight: float
    rank: int

    def __post_init__(self) -> None:
        """Valida as propriedades da candidata de pareamento.

        Raises:
            ValidationError: Se o identificador for invalido.
            InvariantViolationError: Se o peso ou rank violarem limites permitidos.
        """
        object.__setattr__(
            self,
            "candidate_location_id",
            _check_not_empty(self.candidate_location_id, "candidate_location_id"),
        )
        if self.weight < 0.0 or self.weight > 1.0:
            raise InvariantViolationError("O peso deve estar entre 0.0 e 1.0.")
        if self.rank < 1:
            raise InvariantViolationError("O rank deve ser maior ou igual a 1.")


@dataclass(frozen=True, slots=True)
class SectionHistoricalProfile:
    """Perfil historico atribuido a uma secao eleitoral de 2026.

    Attributes:
        section: Chave completa da secao eleitoral.
        shares: Distribuicao de participacao de cada grupo partidario (somando 1.0).
        match_entropy: Entropia de Shannon normalizada do pareamento (medida de incerteza).
        quality_score: Escore numerico de qualidade (1.0 para exata, decrescendo ate 0.0).
        primary_method: Metodo principal de pareamento que gerou este perfil.
        candidates: Tupla com todas as candidatas que integraram a ponderacao.
    """

    section: SectionKey
    shares: tuple[tuple[str, Decimal], ...]
    match_entropy: float
    quality_score: float
    primary_method: MatchQuality
    candidates: tuple[MatchCandidate, ...]

    def __post_init__(self) -> None:
        """Valida a soma dos shares e limites dos scores de qualidade.

        Raises:
            InvariantViolationError: Se os shares nao somarem 1.0 ou scores forem invalidos.
        """
        if not self.shares:
            raise InvariantViolationError("Perfil de secao deve ter ao menos um grupo.")
        total_share = Decimal(0)
        for _, share in self.shares:
            if share < Decimal(0) or share > Decimal(1):
                raise InvariantViolationError("Cada share deve estar no intervalo [0, 1].")
            total_share += share
        if abs(total_share - Decimal(1)) > Decimal("0.000001"):
            raise InvariantViolationError(
                f"Shares do perfil de secao devem somar 1.0 (soma encontrada: {total_share})."
            )
        if not 0.0 <= self.match_entropy <= 1.0:
            raise InvariantViolationError("match_entropy deve estar entre 0.0 e 1.0.")
        if not 0.0 <= self.quality_score <= 1.0:
            raise InvariantViolationError("quality_score deve estar entre 0.0 e 1.0.")
