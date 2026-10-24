"""Testes unitarios para a interface de linha de comando (CLI)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from horizonte_eleitoral.cli import main

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "real_replay"


def test_cli_default_invocation(capsys: pytest.CaptureFixture[str]) -> None:
    """Valida execucao da CLI sem argumentos exibindo configuracao padrao.

    Args:
        capsys: Fixture nativa do pytest para captura de stdout e stderr.

    Returns:
        None.

    Raises:
        None.
    """
    main([])
    captured = capsys.readouterr()
    assert "Horizonte Eleitoral configurado para o ambiente" in captured.out


@pytest.mark.parametrize("pct", [10, 20, 30, 40, 50, 60, 70, 80, 90, 100])
def test_cli_simulate_2026_10pct_step_flags(
    pct: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Valida ensaio da noite eleitoral de 10% a 100% (passo de 10 pontos) via flags dedicadas.

    Args:
        pct: Marco percentual de apuracao (10 a 100).
        capsys: Fixture nativa do pytest para captura de stdout e stderr.

    Returns:
        None.

    Raises:
        None.
    """
    main(
        [
            f"--simulate-2026-{pct}pct",
            "--synthetic",
            "--sections",
            "20",
            "--draws",
            "50",
            "--seed",
            "123",
        ]
    )
    captured = capsys.readouterr()
    assert f"1º turno de 2026 com {pct:.1f}% da apuracao" in captured.out
    assert "Ensaio concluido com sucesso!" in captured.out
    assert "Projection ID: projection:" in captured.out
    assert "Totalizado:" in captured.out
    assert "Probabilidade de 2º Turno:" in captured.out
    assert "PT" in captured.out
    assert "PL" in captured.out
    assert "OUTROS" in captured.out


def test_cli_simulate_2026_all_10pct_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """Valida execucao sequencial de todos os marcos de 10 em 10 pontos (10% a 100%).

    Args:
        capsys: Fixture nativa do pytest para captura de stdout e stderr.

    Returns:
        None.

    Raises:
        None.
    """
    main(
        [
            "--simulate-2026-all-10pct",
            "--synthetic",
            "--sections",
            "20",
            "--draws",
            "40",
            "--seed",
            "123",
        ]
    )
    captured = capsys.readouterr()
    for pct in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100):
        assert f"1º turno de 2026 com {pct:.1f}% da apuracao" in captured.out
    assert captured.out.count("Ensaio concluido com sucesso!") == 10


def test_cli_wave_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """Valida ensaio com percentual arbitrario via flag --wave.

    Args:
        capsys: Fixture nativa do pytest para captura de stdout e stderr.

    Returns:
        None.

    Raises:
        None.
    """
    main(
        [
            "--wave",
            "0.10",
            "--synthetic",
            "--sections",
            "30",
            "--draws",
            "100",
            "--seed",
            "123",
        ]
    )
    captured = capsys.readouterr()
    assert "1º turno de 2026 com 10.0% da apuracao" in captured.out
    assert "Ensaio concluido com sucesso!" in captured.out


def test_cli_defaults_to_real_data_when_simulating(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Valida que o comportamento padrao sem --synthetic consome dados reais da pasta configurada.

    Args:
        capsys: Fixture nativa do pytest para captura de stdout e stderr.

    Returns:
        None.

    Raises:
        None.
    """
    main(
        [
            "--simulate-2026-10pct",
            "--data-dir",
            str(FIXTURES_DIR),
            "--draws",
            "30",
            "--seed",
            "42",
        ]
    )
    captured = capsys.readouterr()
    assert "1º turno de 2026 com 10.0% da apuracao (dados reais)" in captured.out
    assert "Ensaio concluido com sucesso!" in captured.out


def test_cli_simulate_2026_real_data_single_wave(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Valida execucao da CLI com flag --real-data consumindo fixtures locais.

    Args:
        capsys: Fixture nativa do pytest para captura de stdout e stderr.

    Returns:
        None.

    Raises:
        None.
    """
    main(
        [
            "--simulate-2026-10pct",
            "--real-data",
            "--data-dir",
            str(FIXTURES_DIR),
            "--draws",
            "50",
            "--seed",
            "42",
        ]
    )
    captured = capsys.readouterr()
    assert "Carregando base historica de 2022" in captured.out
    assert "Carregando resultados reais de 2026" in captured.out
    assert "Pareando secoes de 2026 com base historica de 2022" in captured.out
    assert "1º turno de 2026 com 10.0% da apuracao (dados reais)" in captured.out
    assert "Ensaio concluido com sucesso!" in captured.out
    assert "Projection ID: projection:" in captured.out


def test_cli_simulate_2026_real_data_all_10pct(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Valida execucao sequencial de 10% a 100% sobre dados reais na CLI.

    Args:
        capsys: Fixture nativa do pytest para captura de stdout e stderr.

    Returns:
        None.

    Raises:
        None.
    """
    main(
        [
            "--simulate-2026-all-10pct",
            "--real-data",
            "--data-dir",
            str(FIXTURES_DIR),
            "--draws",
            "30",
            "--seed",
            "42",
        ]
    )
    captured = capsys.readouterr()
    assert "Catalogo real montado com sucesso" in captured.out
    for pct in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100):
        assert f"1º turno de 2026 com {pct:.1f}% da apuracao (dados reais)" in captured.out
    assert captured.out.count("Ensaio concluido com sucesso!") == 10


def test_cli_loads_parquet_catalog(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Valida que a CLI prioriza o catalogo analitico Apache Parquet quando disponivel.

    Args:
        tmp_path: Fixture nativa do pytest com diretorio temporario efemero.
        capsys: Fixture nativa do pytest para captura de stdout e stderr.

    Returns:
        None.

    Raises:
        None.
    """
    from horizonte_eleitoral.ingestion.real_data_loader import RealDataLoader

    loader = RealDataLoader()
    locs, votes = loader.load_2022_historical_data(FIXTURES_DIR / "sample_historical_2022.csv")
    records = loader.load_2026_results_data(FIXTURES_DIR / "sample_results_2026.csv")
    cat = loader.build_real_election_catalog(locs, votes, records)

    parquet_file = tmp_path / "catalog_2026.parquet"
    loader.save_catalog_parquet(cat, parquet_file)

    main(
        [
            "--simulate-2026-10pct",
            "--data-dir",
            str(tmp_path),
            "--draws",
            "20",
            "--seed",
            "42",
        ]
    )
    captured = capsys.readouterr()
    assert "Carregando catalogo analitico de 2026 de: catalog_2026.parquet" in captured.out
    assert "Catalogo real analitico carregado com sucesso" in captured.out
    assert "1º turno de 2026 com 10.0% da apuracao (dados reais)" in captured.out


def test_cli_query_sql_duckdb(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Valida flag --query-sql executando consultas analiticas DuckDB na CLI.

    Args:
        tmp_path: Fixture nativa do pytest com diretorio temporario efemero.
        capsys: Fixture nativa do pytest para captura de stdout e stderr.

    Returns:
        None.

    Raises:
        None.
    """
    from horizonte_eleitoral.ingestion.real_data_loader import RealDataLoader

    loader = RealDataLoader()
    locs, votes = loader.load_2022_historical_data(FIXTURES_DIR / "sample_historical_2022.csv")
    records = loader.load_2026_results_data(FIXTURES_DIR / "sample_results_2026.csv")
    cat = loader.build_real_election_catalog(locs, votes, records)

    parquet_file = tmp_path / "catalog_2026.parquet"
    loader.save_catalog_parquet(cat, parquet_file)

    main(
        [
            "--query-sql",
            (
                "SELECT state, count(*) as cnt, sum(valid_votes) as tot "
                "FROM catalog GROUP BY state ORDER BY state"
            ),
            "--data-dir",
            str(tmp_path),
        ]
    )
    captured = capsys.readouterr()
    assert "state" in captured.out
    assert "cnt" in captured.out
    assert "tot" in captured.out
    assert "SP" in captured.out
    assert "RJ" in captured.out


def test_cli_simulate_second_round(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Valida execucao de marco percentual do 2º turno majoritario via CLI.

    Args:
        tmp_path: Fixture nativa do pytest com diretorio temporario efemero.
        capsys: Fixture nativa do pytest para captura de stdout e stderr.

    Returns:
        None.

    Raises:
        None.
    """
    from horizonte_eleitoral.ingestion.real_data_loader import RealDataLoader

    loader = RealDataLoader()
    locs, votes = loader.load_2022_historical_data(FIXTURES_DIR / "sample_historical_2022.csv")
    records = loader.load_2026_results_data(FIXTURES_DIR / "sample_results_2026.csv")
    cat = loader.build_real_election_catalog(locs, votes, records)

    parquet_file = tmp_path / "catalog_2026.parquet"
    loader.save_catalog_parquet(cat, parquet_file)

    main(
        [
            "--simulate-2026-2t-pct",
            "40",
            "--data-dir",
            str(tmp_path),
            "--draws",
            "50",
            "--seed",
            "42",
        ]
    )
    captured = capsys.readouterr()
    assert "Ensaio do 2º Turno concluido com sucesso!" in captured.out
    assert "PL" in captured.out
    assert "PT" in captured.out


def test_cli_help_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """Valida que a flag --help exibe o texto de ajuda e encerra com codigo 0.

    Args:
        capsys: Fixture nativa do pytest para captura de stdout e stderr.

    Returns:
        None.

    Raises:
        None.
    """
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "Horizonte Eleitoral - Sistema de Projecao Eleitoral de 2026." in captured.out
    assert "--simulate-2026-2t-pct" in captured.out
    assert "--poll-continuous" in captured.out


def test_cli_poll_tse_live_single_cycle(
    capsys: pytest.CaptureFixture[str],
    mocker: MockerFixture,
) -> None:
    """Valida execucao de consulta pontual a API do TSE via CLI."""
    from datetime import UTC, datetime

    from horizonte_eleitoral.domain.enums import ArtifactType
    from horizonte_eleitoral.domain.models import RawArtifactRequest

    mock_resp = RawArtifactRequest(
        election_id="6258",
        artifact_type=ArtifactType.EA20,
        source_url="https://resultados.tse.jus.br/oficial/ele2026/6258/dados/br/br-c0001-e006258-u.json",
        collected_at=datetime.now(UTC),
        http_status=200,
        body=(
            b'{"ele":"6258","t":"2","tpabr":"br","cdabr":"br",'
            b'"s":{"ts":"499248","st":"0"},"e":{"te":"158745502","est":"0"},'
            b'"v":{"vv":"0","vb":"0","vn":"0"},"carg":[]}'
        ),
        headers=(),
    )

    from horizonte_eleitoral.ingestion.client import TSEAsyncClient

    mocker.patch.object(TSEAsyncClient, "fetch", return_value=mock_resp)

    main(["--poll-tse-live", "--synthetic", "--ignore-time-gate", "--max-cycles", "1"])
    captured = capsys.readouterr()
    assert "HORIZONTE ELEITORAL" in captured.out
    assert "Ciclo #1" in captured.out
    assert "Conectado" in captured.out


def test_cli_poll_continuous_cycles(
    capsys: pytest.CaptureFixture[str],
    mocker: MockerFixture,
) -> None:
    """Valida execucao do modo continuo com multiplos ciclos via CLI."""
    from datetime import UTC, datetime

    from horizonte_eleitoral.domain.enums import ArtifactType
    from horizonte_eleitoral.domain.models import RawArtifactRequest

    mock_resp = RawArtifactRequest(
        election_id="6258",
        artifact_type=ArtifactType.EA20,
        source_url="https://resultados.tse.jus.br/oficial/ele2026/6258/dados/br/br-c0001-e006258-u.json",
        collected_at=datetime.now(UTC),
        http_status=200,
        body=(
            b'{"ele":"6258","t":"2","tpabr":"br","cdabr":"br",'
            b'"s":{"ts":"499248","st":"0"},"e":{"te":"158745502","est":"0"},'
            b'"v":{"vv":"0","vb":"0","vn":"0"},"carg":[]}'
        ),
        headers=(),
    )

    from horizonte_eleitoral.ingestion.client import TSEAsyncClient

    mocker.patch.object(TSEAsyncClient, "fetch", return_value=mock_resp)

    main(
        [
            "--poll-continuous",
            "--poll-interval",
            "1",
            "--max-cycles",
            "2",
            "--synthetic",
            "--ignore-time-gate",
        ]
    )
    captured = capsys.readouterr()
    assert "Ciclo #1" in captured.out
    assert "Ciclo #2" in captured.out
