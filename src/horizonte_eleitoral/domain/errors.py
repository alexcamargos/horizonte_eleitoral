"""Hierarquia explicita de excecoes do sistema."""


class HorizonteEleitoralError(Exception):
    """Classe-base para erros previstos pelo sistema."""


class ValidationError(HorizonteEleitoralError):
    """Indica que um valor de fronteira viola o contrato de dominio."""


class ConfigurationError(ValidationError):
    """Indica configuracao de aplicacao ausente ou invalida."""


class InvariantViolationError(ValidationError):
    """Indica que uma entidade nao respeita uma invariante essencial."""


class ReconciliationError(HorizonteEleitoralError):
    """Indica que os dados nao permitem formar um snapshot consistente."""


class SourceUnavailableError(HorizonteEleitoralError):
    """Indica falha temporaria ou ausencia de uma fonte oficial."""


class ArtifactNotFoundError(HorizonteEleitoralError):
    """Indica que um artefato ou seu corpo nao foi encontrado no cofre."""


class ArtifactStorageError(HorizonteEleitoralError):
    """Indica uma falha de infraestrutura no cofre de artefatos."""


class ImmutableWriteError(ArtifactStorageError):
    """Indica tentativa de substituir um registro ou corpo imutavel."""


class SnapshotConflictError(HorizonteEleitoralError):
    """Indica conflito entre conteudos para o mesmo identificador de snapshot."""
