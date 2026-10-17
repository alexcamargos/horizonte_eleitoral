"""Testes unitarios para o comparador temporal e analitico entre Modelo v1 e Modelo v2."""

from __future__ import annotations

import pytest

from horizonte_eleitoral.backtest.compare import (
    format_comparison_table,
    run_v1_v2_comparison,
)
from horizonte_eleitoral.historical.elasticity import (
    MunicipalElasticityIndex,
    MunicipalElasticityProfile,
)


def _make_dummy_catalog() -> list[dict[str, object]]:
    """Gera um catalogo minimo de secoes para teste do comparador."""
    catalog: list[dict[str, object]] = []
    for i in range(10):
        uf = "SP" if i < 5 else "BA"
        muni = "71072" if uf == "SP" else "38490"
        catalog.append(
            {
                "section_id": f"{uf}:{muni}:0001:{i:04d}",
                "state": uf,
                "municipality_code": muni,
                "zone": "0001",
                "section": f"{i:04d}",
                "electorate": 300,
                "valid_votes": 240,
                "group_votes": (("OUTROS", 20), ("PL", 110), ("PT", 110)),
                "historical_shares": (("OUTROS", 0.10), ("PL", 0.45), ("PT", 0.45)),
            }
        )
    return catalog


def test_run_v1_v2_comparison_basic() -> None:
    """Verifica que a comparacao roda nos checkpoints e retorna metricas validas."""
    catalog = _make_dummy_catalog()
    prof = MunicipalElasticityProfile(
        municipality_key="SP:71072",
        state="SP",
        municipality_code="71072",
        valid_votes_2018=1000,
        valid_votes_2022=1200,
        pt_share_2018=0.30,
        pt_share_2022=0.45,
        pl_share_2018=0.60,
        pl_share_2022=0.45,
        pt_swing=0.15,
        pl_swing=-0.15,
        volatility=0.15,
    )
    idx = MunicipalElasticityIndex(profiles={"SP:71072": prof})

    results = run_v1_v2_comparison(
        sections_catalog=catalog,
        elasticity_index=idx,
        checkpoints=(20.0, 50.0, 100.0),
    )

    assert len(results) == 3
    assert results[0].checkpoint_pct == 20.0
    assert results[2].checkpoint_pct == 100.0

    # No final (100%), o erro deve ser zero
    assert results[2].v1_mae == pytest.approx(0.0, abs=1e-5)
    assert results[2].v2_mae == pytest.approx(0.0, abs=1e-5)

    table = format_comparison_table(results)
    assert "MARCO" in table
    assert "V1 MAE" in table
    assert "V2 MAE" in table
    assert "DELTA MAE" in table


def test_run_v1_v2_comparison_empty_catalog() -> None:
    """Verifica que catalogo vazio lanca ValueError."""
    with pytest.raises(ValueError, match="sections_catalog nao pode ser vazio"):
        run_v1_v2_comparison(sections_catalog=[])
