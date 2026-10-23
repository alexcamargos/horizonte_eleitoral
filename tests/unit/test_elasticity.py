"""Testes unitarios para o motor de elasticidade e volatilidade eleitoral municipal."""

from __future__ import annotations

from pathlib import Path

import pytest

from horizonte_eleitoral.domain.errors import ValidationError
from horizonte_eleitoral.historical.elasticity import (
    MunicipalElasticityIndex,
    MunicipalElasticityProfile,
)


def test_municipal_elasticity_profile_valid() -> None:
    """Valida a instanciacao correta de um perfil de elasticidade municipal."""
    prof = MunicipalElasticityProfile(
        municipality_key="SP:71072",
        state="SP",
        municipality_code="71072",
        valid_votes_2018=1000,
        valid_votes_2022=1200,
        pt_share_2018=0.30,
        pt_share_2022=0.40,
        pl_share_2018=0.60,
        pl_share_2022=0.50,
        pt_swing=0.10,
        pl_swing=-0.10,
        volatility=0.10,
    )
    assert prof.municipality_key == "SP:71072"
    assert prof.state == "SP"
    assert prof.volatility == pytest.approx(0.10)


def test_municipal_elasticity_profile_invalid() -> None:
    """Verifica se validacoes rejeitam chaves e valores invalidos."""
    with pytest.raises(ValidationError, match="municipality_key"):
        MunicipalElasticityProfile(
            municipality_key="INVALID",
            state="SP",
            municipality_code="71072",
            valid_votes_2018=100,
            valid_votes_2022=100,
            pt_share_2018=0.5,
            pt_share_2022=0.5,
            pl_share_2018=0.5,
            pl_share_2022=0.5,
            pt_swing=0.0,
            pl_swing=0.0,
            volatility=0.0,
        )

    with pytest.raises(ValidationError, match="state"):
        MunicipalElasticityProfile(
            municipality_key="SP:71072",
            state="S",
            municipality_code="71072",
            valid_votes_2018=100,
            valid_votes_2022=100,
            pt_share_2018=0.5,
            pt_share_2022=0.5,
            pl_share_2018=0.5,
            pl_share_2022=0.5,
            pt_swing=0.0,
            pl_swing=0.0,
            volatility=0.0,
        )


def test_elasticity_index_lookup_and_fallback() -> None:
    """Verifica lookup O(1) de volatilidade e fallback para media estadual e nacional."""
    p1 = MunicipalElasticityProfile(
        municipality_key="SP:00001",
        state="SP",
        municipality_code="00001",
        valid_votes_2018=1000,
        valid_votes_2022=1000,
        pt_share_2018=0.20,
        pt_share_2022=0.30,
        pl_share_2018=0.70,
        pl_share_2022=0.60,
        pt_swing=0.10,
        pl_swing=-0.10,
        volatility=0.10,
    )
    p2 = MunicipalElasticityProfile(
        municipality_key="RJ:00002",
        state="RJ",
        municipality_code="00002",
        valid_votes_2018=500,
        valid_votes_2022=500,
        pt_share_2018=0.40,
        pt_share_2022=0.44,
        pl_share_2018=0.50,
        pl_share_2022=0.46,
        pt_swing=0.04,
        pl_swing=-0.04,
        volatility=0.04,
    )
    index = MunicipalElasticityIndex(profiles={"SP:00001": p1, "RJ:00002": p2})

    assert index.total_municipalities == 2
    assert index.national_average_volatility == pytest.approx(0.07)

    # Exato
    assert index.get_volatility("SP:00001") == pytest.approx(0.10)
    assert index.get_volatility("RJ:00002") == pytest.approx(0.04)

    # Fallback estadual
    assert index.get_volatility("SP:99999", state="SP") == pytest.approx(0.10)

    # Fallback nacional
    assert index.get_volatility("MG:88888", state="MG") == pytest.approx(0.07)


def test_elasticity_index_parquet_roundtrip(tmp_path: Path) -> None:
    """Valida persistencia e recarregamento seguro via formato Parquet."""
    p1 = MunicipalElasticityProfile(
        municipality_key="BA:12345",
        state="BA",
        municipality_code="12345",
        valid_votes_2018=2000,
        valid_votes_2022=2500,
        pt_share_2018=0.65,
        pt_share_2022=0.70,
        pl_share_2018=0.25,
        pl_share_2022=0.20,
        pt_swing=0.05,
        pl_swing=-0.05,
        volatility=0.05,
    )
    index = MunicipalElasticityIndex(profiles={"BA:12345": p1})
    parquet_file = tmp_path / "test_elasticity.parquet"

    saved = index.save_parquet(parquet_file)
    assert saved == 1
    assert parquet_file.exists()

    loaded = MunicipalElasticityIndex.load_parquet(parquet_file)
    assert loaded.total_municipalities == 1
    prof = loaded.get_profile("BA:12345")
    assert prof is not None
    assert prof.municipality_code == "12345"
    assert prof.volatility == pytest.approx(0.05)


def test_elasticity_build_from_csvs(tmp_path: Path) -> None:
    """Valida construcao do indice a partir de CSVs reais de 2018 e 2022.

    Args:
        tmp_path: Diretorio temporario gerenciado pelo pytest.

    Returns:
        None.

    Raises:
        None.
    """
    csv_18 = tmp_path / "hist_2018.csv"
    csv_22 = tmp_path / "hist_2022.csv"

    csv_18.write_text(
        "state,municipality_code,valid_votes,votes_pt,votes_pl\n"
        "SP,71072,1000,300,600\n"
        "BA,38490,2000,1400,500\n",
        encoding="utf-8",
    )
    csv_22.write_text(
        "state,municipality_code,valid_votes,votes_pt,votes_pl\n"
        "SP,71072,1200,480,600\n"
        "BA,38490,2200,1540,440\n",
        encoding="utf-8",
    )

    index = MunicipalElasticityIndex.build_from_csvs(csv_18, csv_22)
    assert index.total_municipalities == 2
    prof_sp = index.get_profile("SP:71072")
    assert prof_sp is not None
    assert prof_sp.pt_share_2018 == pytest.approx(0.30)
    assert prof_sp.pt_share_2022 == pytest.approx(0.40)
    assert prof_sp.pt_swing == pytest.approx(0.10)
