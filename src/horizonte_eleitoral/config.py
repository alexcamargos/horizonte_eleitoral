"""Configuracao tipada carregada exclusivamente nas bordas da aplicacao."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from horizonte_eleitoral.domain.errors import ConfigurationError


class Environment(StrEnum):
    """Ambientes de execucao permitidos."""

    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


DEFAULT_ALLOWED_TSE_HOSTS = (
    "www.tse.jus.br",
    "dadosabertos.tse.jus.br",
    "resultados.tse.jus.br",
)
DEFAULT_MAX_REQUESTS_PER_SECOND = 20
DEFAULT_MAX_CONCURRENCY = 10
DEFAULT_TSE_POLL_INTERVAL_SECONDS = 60
DEFAULT_TSE_ELECTION_ID_2T = "6258"
DEFAULT_TSE_ENDPOINT_TYPE = "divulgacao"


@dataclass(frozen=True, slots=True)
class Settings:
    """Parametros validados que podem ser injetados nos adaptadores de aplicacao."""

    environment: Environment
    data_directory: Path
    database_dsn: str | None
    allowed_tse_hosts: tuple[str, ...]
    max_requests_per_second: int
    max_concurrency: int
    tse_poll_interval_seconds: int = DEFAULT_TSE_POLL_INTERVAL_SECONDS
    tse_election_id_2t: str = DEFAULT_TSE_ELECTION_ID_2T
    ignore_schedule_gate: bool = False
    tse_target_url: str | None = None
    tse_endpoint_type: str = DEFAULT_TSE_ENDPOINT_TYPE

    def __post_init__(self) -> None:
        if not self.allowed_tse_hosts or any(
            not host or "/" in host for host in self.allowed_tse_hosts
        ):
            raise ConfigurationError(
                "HORIZONTE_TSE_ALLOWED_HOSTS deve conter nomes de host validos."
            )
        if self.max_requests_per_second <= 0:
            raise ConfigurationError("HORIZONTE_MAX_REQUESTS_PER_SECOND deve ser maior que zero.")
        if self.max_concurrency <= 0:
            raise ConfigurationError("HORIZONTE_MAX_CONCURRENCY deve ser maior que zero.")
        if self.tse_poll_interval_seconds <= 0:
            raise ConfigurationError("HORIZONTE_TSE_POLL_INTERVAL_SECONDS deve ser maior que zero.")


def load_settings(
    environ: Mapping[str, str] | None = None,
    *,
    working_directory: Path | None = None,
) -> Settings:
    """Constroi configuracao validada a partir do ambiente, sem vazar env para o dominio."""
    values = os.environ if environ is None else environ
    root = Path.cwd() if working_directory is None else working_directory
    environment = _parse_environment(values.get("HORIZONTE_ENVIRONMENT", Environment.LOCAL.value))
    data_directory = _resolve_data_directory(values.get("HORIZONTE_DATA_DIRECTORY", "data"), root)
    database_dsn = values.get("HORIZONTE_DATABASE_DSN") or None
    allowed_tse_hosts = _parse_hosts(values.get("HORIZONTE_TSE_ALLOWED_HOSTS"))
    tse_poll_interval_seconds = _parse_positive_int(
        values.get("HORIZONTE_TSE_POLL_INTERVAL_SECONDS"),
        "HORIZONTE_TSE_POLL_INTERVAL_SECONDS",
        DEFAULT_TSE_POLL_INTERVAL_SECONDS,
    )
    tse_election_id_2t = values.get("HORIZONTE_TSE_ELECTION_ID_2T", DEFAULT_TSE_ELECTION_ID_2T)
    tse_target_url = values.get("HORIZONTE_TSE_TARGET_URL") or None
    tse_endpoint_type = values.get("HORIZONTE_TSE_ENDPOINT_TYPE", DEFAULT_TSE_ENDPOINT_TYPE)
    ignore_gate_val = values.get("HORIZONTE_IGNORE_SCHEDULE_GATE", "").lower() in (
        "true",
        "1",
        "yes",
    )

    return Settings(
        environment=environment,
        data_directory=data_directory,
        database_dsn=database_dsn,
        allowed_tse_hosts=allowed_tse_hosts,
        max_requests_per_second=_parse_positive_int(
            values.get("HORIZONTE_MAX_REQUESTS_PER_SECOND"),
            "HORIZONTE_MAX_REQUESTS_PER_SECOND",
            DEFAULT_MAX_REQUESTS_PER_SECOND,
        ),
        max_concurrency=_parse_positive_int(
            values.get("HORIZONTE_MAX_CONCURRENCY"),
            "HORIZONTE_MAX_CONCURRENCY",
            DEFAULT_MAX_CONCURRENCY,
        ),
        tse_poll_interval_seconds=tse_poll_interval_seconds,
        tse_election_id_2t=tse_election_id_2t,
        ignore_schedule_gate=ignore_gate_val,
        tse_target_url=tse_target_url,
        tse_endpoint_type=tse_endpoint_type,
    )


def _parse_environment(value: str) -> Environment:
    try:
        return Environment(value.lower())
    except ValueError as error:
        choices = ", ".join(member.value for member in Environment)
        raise ConfigurationError(f"HORIZONTE_ENVIRONMENT deve ser um de: {choices}.") from error


def _resolve_data_directory(value: str, root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (root / path).resolve()


def _parse_hosts(value: str | None) -> tuple[str, ...]:
    if value is None:
        return DEFAULT_ALLOWED_TSE_HOSTS
    hosts = tuple(host.strip().lower() for host in value.split(",") if host.strip())
    if not hosts:
        raise ConfigurationError("HORIZONTE_TSE_ALLOWED_HOSTS nao pode ser vazio.")
    return hosts


def _parse_positive_int(value: str | None, name: str, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as error:
        raise ConfigurationError(f"{name} deve ser um inteiro positivo.") from error
    if parsed <= 0:
        raise ConfigurationError(f"{name} deve ser maior que zero.")
    return parsed


def get_project_root() -> Path:
    """Retorna o caminho absoluto do diretorio raiz do projeto Horizonte Eleitoral.

    Busca dinamicamente pelo arquivo marcador 'pyproject.toml' subindo a partir da
    localizacao deste modulo. Se nao encontrar, utiliza o diretorio de trabalho atual.

    Args:
        None.

    Returns:
        Path absoluto para a raiz do repositorio.

    Raises:
        None.
    """
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


def get_real_data_dir() -> Path:
    """Retorna o caminho absoluto do diretorio de dados reais (data/real).

    Args:
        None.

    Returns:
        Path absoluto para o diretorio data/real do repositorio.

    Raises:
        None.
    """
    return get_project_root() / "data" / "real"
