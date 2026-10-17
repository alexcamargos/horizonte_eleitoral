"""Enumeracoes independentes de formatos externos e adaptadores."""

from enum import StrEnum


class ArtifactType(StrEnum):
    """Familia de arquivos oficiais suportada pelo contrato de ingestao."""

    EA11 = "EA11"
    EA12 = "EA12"
    EA14 = "EA14"
    EA15 = "EA15"
    EA16 = "EA16"
    EA18 = "EA18"
    EA20 = "EA20"


class GeographicScope(StrEnum):
    """Escopos geograficos que nao podem ser agregados sem regra explicita."""

    BRAZIL = "BR"
    STATE = "UF"
    MUNICIPALITY = "MUNICIPIO"
    ZONE = "ZONA"
    SECTION = "SECAO"


class ProcessingState(StrEnum):
    """Estados possiveis de um artefato ou secao durante a apuracao."""

    DISCOVERED = "DESCOBERTA"
    DOWNLOADED = "BAIXADA"
    VERIFIED = "VERIFICADA"
    NORMALIZED = "NORMALIZADA"
    QUARANTINED = "QUARENTENA"
    ELIGIBLE_FOR_RECONCILIATION = "ELEGIVEL_PARA_RECONCILIACAO"
    CONSISTENT = "CONSISTENTE"
    DIVERGENT = "DIVERGENTE"
    PUBLISHABLE = "PUBLICAVEL"
    SUPERSEDED = "SUBSTITUIDA"


class MatchQuality(StrEnum):
    """Qualidade do pareamento historico de uma secao."""

    EXACT = "A_EXATA"
    SAME_COMPLEX = "B_MESMO_COMPLEXO"
    NEIGHBORING = "C_VIZINHA"
    SAME_ZONE = "D_MESMA_ZONA"
    SAME_MUNICIPALITY = "E_MESMO_MUNICIPIO"
    UNMATCHED = "F_SEM_PAREAMENTO"


class SnapshotStatus(StrEnum):
    """Resultado da reconciliacao de um snapshot operacional."""

    CONSISTENT = "CONSISTENTE"
    DIVERGENT = "DIVERGENTE"
