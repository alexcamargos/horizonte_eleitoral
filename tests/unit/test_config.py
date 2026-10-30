"""Testes da configuracao de borda, sem alterar variaveis do processo."""

from pathlib import Path

import pytest
import pytest_mock

from horizonte_eleitoral.config import (
    Environment,
    get_data_dir,
    get_final_data_dir,
    get_norm_data_dir,
    get_project_root,
    get_raw_data_dir,
    get_real_data_dir,
    load_settings,
)
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


def test_data_directory_hierarchy_helpers() -> None:
    """Valida a resolucao correta dos subdiretorios do sistema de dados (raw, norm, final).

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    root = get_project_root()
    data_dir = get_data_dir()
    assert data_dir == root / "data"
    assert get_raw_data_dir() == data_dir / "raw"
    assert get_norm_data_dir() == data_dir / "norm"
    assert get_final_data_dir() == data_dir / "final"


def test_get_real_data_dir_fallback(mocker: pytest_mock.MockerFixture, tmp_path: Path) -> None:
    """Valida prioridade de data/final e compatibilidade retroativa com data/real.

    Args:
        mocker: Fixture pytest-mock para substituicao deterministica.
        tmp_path: Diretorio temporario efemero.

    Returns:
        None.

    Raises:
        None.
    """
    data_dir = tmp_path / "data"
    final_dir = data_dir / "final"
    real_dir = data_dir / "real"
    mocker.patch("horizonte_eleitoral.config.get_project_root", return_value=tmp_path)
    mocker.patch("horizonte_eleitoral.config.get_data_dir", return_value=data_dir)
    mocker.patch("horizonte_eleitoral.config.get_final_data_dir", return_value=final_dir)

    # Caso 1: Nem final nem real existem -> retorna final como alvo padrao
    assert get_real_data_dir() == final_dir

    # Caso 2: Apenas real existe -> fallback para real
    real_dir.mkdir(parents=True)
    assert get_real_data_dir() == real_dir

    # Caso 3: Ambos existem -> prioridade para final
    final_dir.mkdir(parents=True)
    assert get_real_data_dir() == final_dir
