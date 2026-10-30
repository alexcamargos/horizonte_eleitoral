"""Testes do contrato e integridade do sistema de dados (raw, norm, final).

Garante que os dados do projeto estejam estruturados nas camadas medallion:
- data/raw: arquivos brutos imutaveis (ex.: ZIPs baixados do TSE).
- data/norm: arquivos normalizados intermediarios (ex.: CSVs de secoes e historicos).
- data/final: artefatos analiticos colunares e marcos pre-computados (Parquet/JSON).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_mock

from horizonte_eleitoral.config import (
    get_data_dir,
    get_final_data_dir,
    get_norm_data_dir,
    get_raw_data_dir,
    get_real_data_dir,
)
from horizonte_eleitoral.ingestion.real_data_loader import RealDataLoader


def test_data_folders_separation_and_file_extensions() -> None:
    """Verifica que as pastas raw, norm e final estao estritamente segregadas por extensao.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    data_dir = get_data_dir()
    raw_dir = get_raw_data_dir()
    norm_dir = get_norm_data_dir()
    final_dir = get_final_data_dir()

    assert data_dir.is_dir()

    if not raw_dir.exists() or not norm_dir.exists() or not final_dir.exists():
        pytest.skip("Ambiente sem diretorio de dados persistido.")

    # Camada Raw: apenas arquivos ZIP ou artefatos de cofre
    raw_files = [f for f in raw_dir.iterdir() if f.is_file()]
    for f in raw_files:
        assert f.suffix in (".zip", ".blob", ".json"), f"Arquivo inesperado em raw: {f.name}"

    # Camada Norm: apenas arquivos CSV estruturados
    norm_files = [f for f in norm_dir.iterdir() if f.is_file()]
    for f in norm_files:
        assert f.suffix in (".csv",), f"Arquivo inesperado em norm: {f.name}"

    # Camada Final: apenas artefatos Parquet e JSONs de resumo/checkpoints
    final_files = [f for f in final_dir.iterdir() if f.is_file()]
    for f in final_files:
        assert f.suffix in (".parquet", ".json"), f"Arquivo inesperado em final: {f.name}"


def test_final_catalog_parquet_loadable() -> None:
    """Verifica que o catalogo analitico em data/final e valido e carregavel.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    final_dir = get_final_data_dir()
    parquet_path = final_dir / "catalog_2026.parquet"
    if not parquet_path.exists():
        pytest.skip("catalog_2026.parquet nao disponivel em data/final.")

    loader = RealDataLoader()
    catalog = loader.load_catalog_parquet(parquet_path, limit_rows=10)
    assert len(catalog) == 10
    first = catalog[0]
    assert "section_id" in first
    assert "state" in first
    assert "valid_votes" in first


def test_data_dir_resolution_contract(tmp_path: Path, mocker: pytest_mock.MockerFixture) -> None:
    """Valida que get_data_dir e suas especializacoes respeitam a hierarquia e fallback.

    Args:
        tmp_path: Diretorio temporario de teste isolado.
        mocker: Fixture pytest-mock para substituicao deterministica.

    Returns:
        None.

    Raises:
        None.
    """
    mocker.patch("horizonte_eleitoral.config.get_project_root", return_value=tmp_path)
    base = tmp_path / "data"
    mocker.patch("horizonte_eleitoral.config.get_data_dir", return_value=base)

    raw = base / "raw"
    norm = base / "norm"
    final = base / "final"
    legacy_real = base / "real"

    assert get_raw_data_dir() == raw
    assert get_norm_data_dir() == norm
    assert get_final_data_dir() == final

    # Quando nenhum existe, get_real_data_dir aponta para final
    assert get_real_data_dir() == final

    # Quando apenas legacy_real existe, faz fallback gracioso
    legacy_real.mkdir(parents=True)
    assert get_real_data_dir() == legacy_real

    # Quando final existe, final tem precedencia absoluta
    final.mkdir(parents=True)
    assert get_real_data_dir() == final
