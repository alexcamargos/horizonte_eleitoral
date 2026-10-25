"""Testes unitarios para o carregador de dados reais de 2022 e 2026."""

from __future__ import annotations

from pathlib import Path

import pytest

from horizonte_eleitoral.domain.errors import ValidationError
from horizonte_eleitoral.ingestion.real_data_loader import (
    RealDataLoader,
    RealSectionRecord,
    compute_section_arrival_score,
)
from horizonte_eleitoral.simulation.election_night_runner import (
    calculate_wave_cutoff,
    simulate_2026_real_checkpoint,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "real_replay"


def test_load_2022_historical_data_csv() -> None:
    """Valida o carregamento da base historica de 2022 a partir de arquivo CSV.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    loader = RealDataLoader()
    csv_path = FIXTURES_DIR / "sample_historical_2022.csv"
    locations, votes = loader.load_2022_historical_data(csv_path)

    assert len(locations) == 20
    assert len(votes) == 20

    loc_sp = next(loc for loc in locations if loc.location_id == "SP:71072:0001:1001")
    assert loc_sp.state == "SP"
    assert loc_sp.municipality_code == "71072"
    assert loc_sp.zone == "0001"
    assert loc_sp.local_code == "1001"
    assert loc_sp.electorate == 400

    vote_sp = votes["SP:71072:0001:1001"]
    assert vote_sp.valid_votes == 320
    group_dict = dict(vote_sp.group_votes)
    assert group_dict["PT"] == 160
    assert group_dict["PL"] == 140
    assert group_dict["OUTROS"] == 20


def test_load_2026_results_data_csv() -> None:
    """Valida o carregamento dos resultados de 2026 por secao a partir de CSV.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    loader = RealDataLoader()
    csv_path = FIXTURES_DIR / "sample_results_2026.csv"
    records = loader.load_2026_results_data(csv_path)

    assert len(records) == 20
    first = records[0]
    assert isinstance(first, RealSectionRecord)
    assert first.section_id == "SP:71072:0001:0001"
    assert first.state == "SP"
    assert first.municipality_code == "71072"
    assert first.zone == "0001"
    assert first.section == "0001"
    assert first.electorate == 400
    assert first.valid_votes == 320

    g_dict = dict(first.group_votes)
    assert g_dict["PT"] == 165
    assert g_dict["PL"] == 135
    assert g_dict["OUTROS"] == 20
    assert first.blank_votes == 10
    assert first.null_votes == 12
    assert first.totalized_timestamp is not None


def test_load_2026_results_data_json() -> None:
    """Valida o carregamento de resultados de 2026 estruturados em formato JSON.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    loader = RealDataLoader()
    json_path = FIXTURES_DIR / "sample_results_2026.json"
    records = loader.load_2026_results_data(json_path)

    assert len(records) == 2
    assert records[0].state == "SP"
    assert records[1].state == "RJ"
    assert dict(records[0].group_votes)["PT"] == 165


def test_build_real_election_catalog() -> None:
    """Valida pareamento historico e ordenacao cronologica do catalogo da eleicao.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    loader = RealDataLoader()
    locations, votes = loader.load_2022_historical_data(FIXTURES_DIR / "sample_historical_2022.csv")
    records = loader.load_2026_results_data(FIXTURES_DIR / "sample_results_2026.csv")

    catalog = loader.build_real_election_catalog(locations, votes, records)

    assert len(catalog) == len(records)
    # Verifica que todos os itens tem shares historicos somando aproximadamente 1.0
    for item in catalog:
        hist_shares = dict(item["historical_shares"])
        assert "PT" in hist_shares
        assert "PL" in hist_shares
        assert "OUTROS" in hist_shares
        total_share = sum(hist_shares.values())
        assert abs(total_share - 1.0) < 1e-4

    # Verifica ordenacao temporal estrita
    timestamps = [item["totalized_timestamp"] for item in catalog]
    assert timestamps == sorted(timestamps)


def test_calculate_wave_cutoff() -> None:
    """Valida calculo de corte de onda por eleitorado acumulado e por contagem de secoes.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    loader = RealDataLoader()
    locations, votes = loader.load_2022_historical_data(FIXTURES_DIR / "sample_historical_2022.csv")
    records = loader.load_2026_results_data(FIXTURES_DIR / "sample_results_2026.csv")
    catalog = loader.build_real_election_catalog(locations, votes, records)

    # 20 secoes com ~400 de eleitorado cada (~7900 total)
    cutoff_10pct_elec = calculate_wave_cutoff(catalog, progress_pct=0.10, by_electorate=True)
    assert 1 <= cutoff_10pct_elec <= 3

    cutoff_50pct_elec = calculate_wave_cutoff(catalog, progress_pct=0.50, by_electorate=True)
    assert 8 <= cutoff_50pct_elec <= 12

    cutoff_100pct = calculate_wave_cutoff(catalog, progress_pct=1.00, by_electorate=True)
    assert cutoff_100pct == len(catalog)

    # Por contagem de secoes
    cutoff_20pct_sec = calculate_wave_cutoff(catalog, progress_pct=0.20, by_electorate=False)
    assert cutoff_20pct_sec == 4


def test_simulate_2026_real_checkpoint_execution() -> None:
    """Valida execucao de um marco percentual completo sobre o catalogo real.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    loader = RealDataLoader()
    locations, votes = loader.load_2022_historical_data(FIXTURES_DIR / "sample_historical_2022.csv")
    records = loader.load_2026_results_data(FIXTURES_DIR / "sample_results_2026.csv")
    catalog = loader.build_real_election_catalog(locations, votes, records)

    payload = simulate_2026_real_checkpoint(
        sections_catalog=catalog,
        progress_pct=0.20,
        num_draws=50,
        seed=123,
    )

    assert payload.status == "published"
    assert payload.totalized_electorate_pct > 0.0
    assert 0.0 <= payload.second_round_probability <= 1.0
    assert len(payload.groups) == 3

    group_codes = {g.code for g in payload.groups}
    assert group_codes == {"OUTROS", "PL", "PT"}


def test_error_handling_invalid_files(tmp_path: Path) -> None:
    """Valida que o carregador lanca excecoes apropriadas para entradas invalidas.

    Args:
        tmp_path: Fixture nativa do pytest com diretorio temporario efemero.

    Returns:
        None.

    Raises:
        None.
    """
    loader = RealDataLoader()

    with pytest.raises(FileNotFoundError):
        loader.load_2022_historical_data(tmp_path / "nao_existe.csv")

    empty_file = tmp_path / "empty.csv"
    empty_file.write_text("", encoding="utf-8")
    with pytest.raises(ValidationError, match="vazio"):
        loader.load_2022_historical_data(empty_file)

    corrupt_json = tmp_path / "corrupt.json"
    corrupt_json.write_text("{corrupt json", encoding="utf-8")
    with pytest.raises(ValidationError, match="malformado"):
        loader.load_2022_historical_data(corrupt_json)

    with pytest.raises(ValidationError, match="results_2026 nao pode ser vazio"):
        loader.build_real_election_catalog([], {}, [])


def test_parquet_catalog_roundtrip_and_filtering(tmp_path: Path) -> None:
    """Valida serializacao e desserializacao colunar em Apache Parquet com filtros.

    Args:
        tmp_path: Fixture nativa do pytest com diretorio temporario efemero.

    Returns:
        None.

    Raises:
        None.
    """
    loader = RealDataLoader()
    locations, votes = loader.load_2022_historical_data(FIXTURES_DIR / "sample_historical_2022.csv")
    records = loader.load_2026_results_data(FIXTURES_DIR / "sample_results_2026.csv")
    catalog = loader.build_real_election_catalog(locations, votes, records)

    parquet_file = tmp_path / "catalog_test.parquet"
    count = loader.save_catalog_parquet(catalog, parquet_file)
    assert count == len(catalog)
    assert parquet_file.exists()

    # Leitura completa
    loaded = loader.load_catalog_parquet(parquet_file)
    assert len(loaded) == len(catalog)
    assert loaded[0]["section_id"] == catalog[0]["section_id"]
    assert dict(loaded[0]["group_votes"]) == dict(catalog[0]["group_votes"])
    assert loaded[0]["match_quality"] == catalog[0]["match_quality"]

    # Leitura com predicate pushdown por UF
    sp_only = loader.load_catalog_parquet(parquet_file, filter_ufs=["SP"])
    assert len(sp_only) == 3
    assert all(s["state"] == "SP" for s in sp_only)

    # Leitura com limite de linhas
    limited = loader.load_catalog_parquet(parquet_file, limit_rows=2)
    assert len(limited) == 2


def test_query_catalog_sql_duckdb(tmp_path: Path) -> None:
    """Valida execucao de queries SQL diretamente no arquivo Parquet usando DuckDB.

    Args:
        tmp_path: Fixture nativa do pytest com diretorio temporario efemero.

    Returns:
        None.

    Raises:
        None.
    """
    loader = RealDataLoader()
    locations, votes = loader.load_2022_historical_data(FIXTURES_DIR / "sample_historical_2022.csv")
    records = loader.load_2026_results_data(FIXTURES_DIR / "sample_results_2026.csv")
    catalog = loader.build_real_election_catalog(locations, votes, records)

    parquet_file = tmp_path / "catalog_analytics.parquet"
    loader.save_catalog_parquet(catalog, parquet_file)

    # Consulta analitica agregada com SQL
    sql = (
        "SELECT state, count(*) as n_sections, sum(valid_votes) as tot_valid "
        "FROM catalog GROUP BY state ORDER BY state"
    )
    relation = loader.query_catalog_sql(parquet_file, sql)
    df = relation.df()

    assert not df.empty
    assert "state" in df.columns
    assert "n_sections" in df.columns
    assert "tot_valid" in df.columns
    assert len(df) == 10  # 10 UFs presentes nas fixtures


def test_compute_section_arrival_score_deterministic() -> None:
    """Valida determinismo e diferenciacao regional do calculo de score de chegada.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    # Mesma secao deve sempre produzir exatamente o mesmo score
    score1 = compute_section_arrival_score("SP:71072:0001:0001", "SP")
    score2 = compute_section_arrival_score("SP:71072:0001:0001", "SP")
    assert score1 == score2

    # Regioes de apuracao rapida (DF, PR, SC) devem ter media de score menor
    # que estados do Nordeste (BA, PI, MA)
    df_scores = [compute_section_arrival_score(f"DF:00001:0001:{i:04d}", "DF") for i in range(100)]
    ba_scores = [compute_section_arrival_score(f"BA:38490:0001:{i:04d}", "BA") for i in range(100)]
    avg_df = sum(df_scores) / len(df_scores)
    avg_ba = sum(ba_scores) / len(ba_scores)
    assert avg_df < avg_ba


def test_build_real_election_catalog_uniform_timestamps() -> None:
    """Valida ordenacao regional e geracao de timestamps quando a entrada tem timestamps uniformes.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    loader = RealDataLoader()
    locations, votes = loader.load_2022_historical_data(FIXTURES_DIR / "sample_historical_2022.csv")
    records = loader.load_2026_results_data(FIXTURES_DIR / "sample_results_2026.csv")

    # Forca registros com timestamp uniforme (simulando dump em lote do TSE como DT_GERACAO)
    static_ts = records[0].totalized_timestamp
    uniform_records = [
        RealSectionRecord(
            section_id=r.section_id,
            state=r.state,
            municipality_code=r.municipality_code,
            zone=r.zone,
            section=r.section,
            electorate=r.electorate,
            valid_votes=r.valid_votes,
            blank_votes=r.blank_votes,
            null_votes=r.null_votes,
            group_votes=r.group_votes,
            totalized_timestamp=static_ts,
            sequence_order=r.sequence_order,
            local_code=r.local_code,
        )
        for r in records
    ]

    catalog = loader.build_real_election_catalog(locations, votes, uniform_records)

    assert len(catalog) == len(uniform_records)
    # Verifica que timestamps foram distribuidos crescentemente ao longo da noite
    timestamps = [item["totalized_timestamp"] for item in catalog]
    assert timestamps[0] < timestamps[-1]
    assert timestamps == sorted(timestamps)
    # Verifica sequence_order estritamente sequencial 1..N
    assert [item["sequence_order"] for item in catalog] == list(range(1, len(catalog) + 1))
