"""Testes da configuracao de borda, sem alterar variaveis do processo."""

from pathlib import Path

import pytest

from horizonte_eleitoral.config import Environment, load_settings
from horizonte_eleitoral.domain.errors import ConfigurationError


def test_load_settings_uses_typed_values_and_resolves_data_directory(tmp_path: Path) -> None:
    """A configuracao converte ambiente e limites antes de ser injetada."""
    settings = load_settings(
        {
            "HORIZONTE_ENVIRONMENT": "test",
            "HORIZONTE_DATA_DIRECTORY": "runtime-data",
            "HORIZONTE_TSE_ALLOWED_HOSTS": "www.tse.jus.br, dadosabertos.tse.jus.br",
            "HORIZONTE_MAX_REQUESTS_PER_SECOND": "12",
            "HORIZONTE_MAX_CONCURRENCY": "3",
        },
        working_directory=tmp_path,
    )

    assert settings.environment is Environment.TEST
    assert settings.data_directory == (tmp_path / "runtime-data").resolve()
    assert settings.max_requests_per_second == 12
    assert settings.max_concurrency == 3


def test_load_settings_rejects_invalid_numeric_value() -> None:
    """Valores de ambiente invalidos falham antes de chegar ao dominio."""
    with pytest.raises(ConfigurationError, match="inteiro positivo"):
        load_settings({"HORIZONTE_MAX_CONCURRENCY": "zero"})
