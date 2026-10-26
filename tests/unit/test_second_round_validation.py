"""Testes unitarios para consolidacao, validacao retroativa e UI do 2o Turno de 2026."""

from __future__ import annotations

import json
from typing import Any
from zoneinfo import ZoneInfo

import altair as alt
import numpy as np
from pytest_mock import MockerFixture

from horizonte_eleitoral.backtest.second_round_validation import (
    evaluate_second_round_wave,
    generate_second_round_state_validation,
    simulate_second_round_wave_projection,
    summarize_second_round_validation,
)
from horizonte_eleitoral.dashboard.charts import (
    build_second_round_chart,
    build_second_round_error_chart,
)
from horizonte_eleitoral.dashboard.components import (
    build_chart_guide_html,
    render_editorial_header,
    render_second_round_history_table,
    render_second_round_state_table,
    render_second_round_validation_panel,
)
from horizonte_eleitoral.dashboard.replay import (
    build_second_round_validation_point,
    generate_second_round_state_projections,
    generate_second_round_validation_timeline,
)
from horizonte_eleitoral.domain.enums import GeographicScope
from horizonte_eleitoral.ingestion.second_round_consolidator import (
    _parse_tse_time_minutes,
    allocate_integer_votes_by_swing,
    build_2026_second_round_catalog,
)
from horizonte_eleitoral.normalization.adapters import normalize_ea20
from horizonte_eleitoral.normalization.models import NormalizedTotalization


def _make_synthetic_1t_catalog() -> list[dict[str, Any]]:
    """Cria um catalogo sintetico deterministico do 1o turno com 100 secoes em 2 UFs.

    Args:
        None.

    Returns:
        Lista de 100 dicionarios de secoes com eleitorado e votos de 1o turno.

    Raises:
        None.
    """
    sections: list[dict[str, Any]] = []
    for idx in range(100):
        uf = "SP" if idx < 50 else "BA"
        muni = "71072" if uf == "SP" else "38490"
        zone = f"{(idx % 5) + 1:04d}"
        sec = f"{idx + 1:04d}"
        pt_1t = 120 if uf == "SP" else 220
        pl_1t = 180 if uf == "SP" else 80
        out_1t = 30
        sections.append(
            {
                "section_id": f"{uf}:{muni}:{zone}:{sec}",
                "state": uf,
                "municipality_code": muni,
                "zone": zone,
                "section": sec,
                "local_code": "0001",
                "electorate": 420,
                "valid_votes": pt_1t + pl_1t + out_1t,
                "group_votes": (("OUTROS", out_1t), ("PL", pl_1t), ("PT", pt_1t)),
                "historical_shares": (("OUTROS", 0.08), ("PL", 0.46), ("PT", 0.46)),
                "match_quality": "A_EXATA",
                "sequence_order": idx + 1,
            }
        )
    return sections


def test_normalize_ea20_supports_municipality_scope_preserving_leading_zeros() -> None:
    """Valida que normalize_ea20 reconhece tpabr='mu' e preserva zeros a esquerda em cdabr.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: Se o escopo ou codigo do municipio forem normalizados incorretamente.
    """
    payload = {
        "tpabr": "mu",
        "cdabr": "105",
        "dt": "25/10/2026",
        "ht": "18:42:10",
        "s": "50",
        "st": "50",
        "e": "15000",
        "ea": "15000",
        "vv": "12000",
        "vb": "200",
        "vn": "300",
        "cand": [
            {"n": "13", "vap": "6500"},
            {"n": "22", "vap": "5500"},
        ],
    }
    tot = normalize_ea20(json.dumps(payload).encode("utf-8"), round_num=2)
    assert tot.scope is GeographicScope.MUNICIPALITY
    assert tot.scope_code == "00105"
    assert dict(tot.candidate_group_votes) == {"PL": 5500, "PT": 6500}
    assert tot.generation_time == "25/10/2026 18:42:10"


def test_build_2026_second_round_catalog_conserves_exact_integer_votes() -> None:
    """Valida conservacao inteira exata, conversao de fuso TRE e regime real pos-19h do 2T.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: Se a soma de votos ou a janela de suspensao 17h-19h falharem.
    """
    assert _parse_tse_time_minutes("ZZ", "24/10/2026", "23:00:05") == 17.0 * 60.0 + 5.0
    assert (
        _parse_tse_time_minutes("AC", "25/10/2026", "17:34:00", apply_local_tz_offset=True)
        == 19.0 * 60.0 + 34.0
    )
    assert (
        _parse_tse_time_minutes("MT", "25/10/2026", "18:23:00", apply_local_tz_offset=True)
        == 19.0 * 60.0 + 23.0
    )

    elec = np.array([300, 400, 500], dtype=np.int64)
    priors = np.array([[0.60, 0.40], [0.50, 0.50], [0.35, 0.65]], dtype=np.float64)
    pl_a, pt_a, bl_a, nu_a = allocate_integer_votes_by_swing(
        electorates=elec,
        priors=priors,
        target_pl=487,
        target_pt=513,
        target_blank=19,
        target_null=31,
    )
    assert int(pl_a.sum()) == 487
    assert int(pt_a.sum()) == 513
    assert int(bl_a.sum()) == 19
    assert int(nu_a.sum()) == 31

    cat_1t = _make_synthetic_1t_catalog()
    sp_tot = NormalizedTotalization(
        scope=GeographicScope.STATE,
        scope_code="SP",
        total_electorate=21000,
        totalized_electorate=21000,
        pending_electorate=0,
        total_sections=50,
        totalized_sections=50,
        pending_sections=0,
        valid_votes=16000,
        blank_votes=300,
        null_votes=500,
        candidate_group_votes=(("PL", 9200), ("PT", 6800)),
        generation_time="25/10/2026 19:20:00",
    )
    ba_tot = NormalizedTotalization(
        scope=GeographicScope.STATE,
        scope_code="BA",
        total_electorate=21000,
        totalized_electorate=21000,
        pending_electorate=0,
        total_sections=50,
        totalized_sections=50,
        pending_sections=0,
        valid_votes=16000,
        blank_votes=250,
        null_votes=450,
        candidate_group_votes=(("PL", 4400), ("PT", 11600)),
        generation_time="25/10/2026 20:10:00",
    )
    muni_sp = NormalizedTotalization(
        scope=GeographicScope.MUNICIPALITY,
        scope_code="71072",
        total_electorate=21000,
        totalized_electorate=21000,
        pending_electorate=0,
        total_sections=50,
        totalized_sections=50,
        pending_sections=0,
        valid_votes=16000,
        blank_votes=300,
        null_votes=500,
        candidate_group_votes=(("PL", 9200), ("PT", 6800)),
        generation_time="25/10/2026 19:20:00",
    )

    cat_2t = build_2026_second_round_catalog(
        first_round_catalog=cat_1t,
        state_totalizations={"SP": sp_tot, "BA": ba_tot},
        muni_totalizations={("SP", "71072"): muni_sp},
        muni_completion_times={
            ("SP", "71072"): ("25/10/2026", "19:20:00"),
            ("BA", "38490"): ("25/10/2026", "20:10:00"),
        },
    )

    assert len(cat_2t) == 100
    sum_pl = sum(dict(s["group_votes"])["PL"] for s in cat_2t)
    sum_pt = sum(dict(s["group_votes"])["PT"] for s in cat_2t)
    assert sum_pl == 9200 + 4400
    assert sum_pt == 6800 + 11600
    assert [s["sequence_order"] for s in cat_2t] == list(range(1, 101))
    # Todas as secoes de SP (71072) e BA (38490) chegam estritamente apos as 19h00 BRT
    for s in cat_2t:
        ts_brt = s["totalized_timestamp"].astimezone(ZoneInfo("America/Sao_Paulo"))
        assert ts_brt.hour >= 19


def test_simulate_second_round_wave_projection_enforces_strict_zero_data_leakage() -> None:
    """Garante matematicamente que alterar votos futuros (> cutoff) nao afeta a projecao atual.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: Se houver qualquer vazamento de votos das secoes pendentes.
    """
    base_1t = _make_synthetic_1t_catalog()
    cat_a: list[dict[str, Any]] = []
    cat_b: list[dict[str, Any]] = []

    for idx, s in enumerate(base_1t):
        common = {
            **s,
            "historical_shares": (("OUTROS", 0.0), ("PL", 0.48), ("PT", 0.52)),
        }
        if idx < 50:
            votes = (("OUTROS", 0), ("PL", 160), ("PT", 180))
            cat_a.append({**common, "valid_votes": 340, "group_votes": votes})
            cat_b.append({**common, "valid_votes": 340, "group_votes": votes})
        else:
            # No futuro ainda nao apurado, cat_a tem 100% PT e cat_b tem 100% PL
            cat_a.append(
                {
                    **common,
                    "valid_votes": 400,
                    "group_votes": (("OUTROS", 0), ("PL", 0), ("PT", 400)),
                }
            )
            cat_b.append(
                {
                    **common,
                    "valid_votes": 400,
                    "group_votes": (("OUTROS", 0), ("PL", 400), ("PT", 0)),
                }
            )

    payload_a, _, cut_a = simulate_second_round_wave_projection(
        sections_catalog_2t=cat_a,
        wave=0.40,
        num_draws=120,
        seed=99,
    )
    payload_b, _, cut_b = simulate_second_round_wave_projection(
        sections_catalog_2t=cat_b,
        wave=0.40,
        num_draws=120,
        seed=99,
    )

    assert cut_a == cut_b == 40
    map_a = {g.code: g for g in payload_a.groups}
    map_b = {g.code: g for g in payload_b.groups}
    for code in ("PT", "PL"):
        assert map_a[code].observed_share == map_b[code].observed_share
        assert map_a[code].projected_share == map_b[code].projected_share
        assert map_a[code].q05 == map_b[code].q05
        assert map_a[code].q95 == map_b[code].q95
        assert map_a[code].win_probability == map_b[code].win_probability


def test_evaluate_second_round_wave_preliminary_gate_and_retroactive_metrics() -> None:
    """Valida limiar de 2,0%, convergencia em 100%, resumo global e projecao por UF.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: Se o limiar preliminar ou as metricas retroativas falharem.
    """
    cat_1t = _make_synthetic_1t_catalog()
    cat_2t = [
        {
            **s,
            "valid_votes": 340,
            "group_votes": (
                ("OUTROS", 0),
                ("PL", 190 if s["state"] == "SP" else 110),
                ("PT", 150 if s["state"] == "SP" else 230),
            ),
            "historical_shares": (
                ("OUTROS", 0.0),
                ("PL", 0.58 if s["state"] == "SP" else 0.30),
                ("PT", 0.42 if s["state"] == "SP" else 0.70),
            ),
        }
        for s in cat_1t
    ]

    p_1pct = evaluate_second_round_wave(
        sections_catalog_2t=cat_2t,
        wave=0.01,
        num_draws=80,
        seed=42,
    )
    assert p_1pct["x"] == 1.0
    assert p_1pct["projecao"] is None
    assert p_1pct["faixa"] is None
    assert p_1pct["win_probability"] is None
    assert p_1pct["preliminar"] is not None
    assert p_1pct["metrics"]["model_mae_pp"] is None
    assert p_1pct["metrics"]["raw_mae_pp"] is not None

    timeline = generate_second_round_validation_timeline(
        catalog_2t=cat_2t,
        current_wave=1.0,
        checkpoints=(0.01, 0.10, 0.50, 1.00),
    )
    assert len(timeline) == 4
    p_100 = timeline[-1]
    assert p_100["x"] == 100.0
    assert p_100["apurado"] == p_100["projecao"] == p_100["final_oficial"]
    assert p_100["metrics"]["model_mae_pp"] == 0.0
    assert p_100["metrics"]["raw_mae_pp"] == 0.0
    assert p_100["metrics"]["ci_90_covered"] is True

    summary = summarize_second_round_validation(timeline)
    assert summary["winner_code"] == "PT"
    assert summary["partial_waves_count"] == 2
    assert summary["mean_model_mae_pp"] is not None
    assert summary["ci_90_coverage_pct"] is not None

    states = generate_second_round_state_validation(sections_catalog_2t=cat_2t, wave=0.60)
    assert {r["uf"] for r in states} == {"BA", "SP"}
    sp_row = next(r for r in states if r["uf"] == "SP")
    assert "erro_modelo_pp" in sp_row
    assert "final_PT" in sp_row

    # Wrappers do modulo dashboard.replay
    pt_wrap = build_second_round_validation_point(catalog_2t=cat_2t, wave=0.30, num_draws=50)
    assert pt_wrap["projecao"] is not None
    st_wrap = generate_second_round_state_projections(catalog_2t=cat_2t, wave=0.30)
    assert len(st_wrap) == 2


def test_second_round_validation_charts_and_ui_components() -> None:
    """Valida renderizacao sem erros dos novos graficos e componentes de auditoria do 2o Turno.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: Se algum componente ou grafico Altair falhar na construcao.
    """
    chart_err_empty = build_second_round_error_chart([])
    assert isinstance(chart_err_empty, alt.Chart)

    sample_points = [
        {
            "t": "17:08",
            "x": 1.0,
            "apurado": {"PT": 50.80, "PL": 49.20},
            "projecao": None,
            "faixa": None,
            "win_probability": None,
            "final_oficial": {"PT": 51.78, "PL": 48.22},
            "metrics": {
                "raw_mae_pp": 0.98,
                "model_mae_pp": None,
                "mae_gain_pp": None,
                "ci_90_covered": None,
                "leader_correct": None,
            },
        },
        {
            "t": "18:30",
            "x": 40.0,
            "apurado": {"PT": 51.29, "PL": 48.71},
            "projecao": {"PT": 51.78, "PL": 48.22},
            "faixa": {"PT": [51.69, 51.86], "PL": [48.14, 48.31]},
            "win_probability": {"PT": 1.0, "PL": 0.0},
            "final_oficial": {"PT": 51.78, "PL": 48.22},
            "metrics": {
                "raw_mae_pp": 0.49,
                "model_mae_pp": 0.00,
                "mae_gain_pp": 0.49,
                "ci_90_covered": True,
                "leader_correct": True,
            },
        },
    ]

    chart_main = build_second_round_chart(
        points=sample_points,
        final_result={"PT": 51.78, "PL": 48.22},
    )
    assert isinstance(chart_main, (alt.Chart, alt.LayerChart))
    assert "Resultado oficial 100% TSE" in str(chart_main.to_dict()["title"]["subtitle"])

    chart_err = build_second_round_error_chart(sample_points)
    assert isinstance(chart_err, (alt.Chart, alt.LayerChart))

    guide_2t = build_chart_guide_html(round_num=2)
    assert "50% (Maioria Absoluta)" in guide_2t
    assert "Outros (soma)" not in guide_2t

    val_summary = summarize_second_round_validation(sample_points)
    render_editorial_header(
        electorate_pct=40.0,
        updated_str="18:30",
        environment="replay",
        round_num=2,
    )
    render_second_round_validation_panel(
        latest_point=sample_points[-1],
        validation_summary=val_summary,
    )
    render_second_round_history_table(points=sample_points)
    render_second_round_state_table(
        states_data=[
            {
                "uf": "SP",
                "x": 45.0,
                "apurado_PT": 42.10,
                "PT": 43.20,
                "PL": 56.80,
                "final_PT": 43.25,
                "final_PL": 56.75,
                "prior_1t_PT": 41.80,
                "swing_2t_pp": 1.45,
                "erro_modelo_pp": 0.05,
            }
        ]
    )


def test_load_second_round_validation_catalog_offline_fallback(
    mocker: MockerFixture,
) -> None:
    """Valida fallback offline deterministico quando catalog_2026_2t.parquet nao existe.

    Args:
        mocker: Fixture nativa do pytest-mock.

    Returns:
        None.

    Raises:
        AssertionError: Se o fallback offline falhar na derivacao bilateral.
    """
    import horizonte_eleitoral.dashboard.replay as replay_mod

    mocker.patch.dict(replay_mod._CATALOG_2T_CACHE, {}, clear=True)
    mocker.patch.object(
        replay_mod,
        "load_replay_catalog",
        return_value=_make_synthetic_1t_catalog()[:10],
    )
    orig_exists = replay_mod.Path.exists
    mocker.patch.object(
        replay_mod.Path,
        "exists",
        autospec=True,
        side_effect=lambda self: (
            False if self.name == "catalog_2026_2t.parquet" else orig_exists(self)
        ),
    )

    fallback_cat = replay_mod.load_second_round_validation_catalog(limit_sections=10)
    assert len(fallback_cat) == 10
    assert dict(fallback_cat[0]["group_votes"])["OUTROS"] == 0


def test_cli_build_2026_2t_history_flag(
    mocker: MockerFixture,
    tmp_path: Any,
) -> None:
    """Valida flag CLI --build-2026-2t-history via mocker sem I/O de rede externo.

    Args:
        mocker: Fixture nativa do pytest-mock.
        tmp_path: Diretorio temporario isolado do pytest.

    Returns:
        None.

    Raises:
        AssertionError: Se a orquestracao da CLI nao invocar o pre-calculo de marcos.
    """
    from horizonte_eleitoral import cli
    from horizonte_eleitoral.ingestion.real_data_loader import RealDataLoader

    loader = RealDataLoader()
    cat_tmp = [
        {
            **s,
            "valid_votes": 300,
            "group_votes": (("OUTROS", 0), ("PL", 140), ("PT", 160)),
            "historical_shares": (("OUTROS", 0.0), ("PL", 0.48), ("PT", 0.52)),
        }
        for s in _make_synthetic_1t_catalog()[:20]
    ]
    loader.save_catalog_parquet(cat_tmp, tmp_path / "catalog_2026_2t.parquet")

    mocker.patch(
        "horizonte_eleitoral.ingestion.second_round_consolidator.consolidate_and_save_2026_second_round",
        return_value={
            "catalog_rows_saved": 20,
            "municipalities_downloaded": 2,
            "states_downloaded": 2,
            "sections_pct_tse": 100.0,
            "official_shares": {"PT": 53.33, "PL": 46.67},
        },
    )
    mock_precompute = mocker.patch(
        "horizonte_eleitoral.dashboard.replay.precompute_second_round_checkpoints",
        return_value={"0.100": {}, "1.000": {}},
    )
    cli.main(["--build-2026-2t-history", "--data-dir", str(tmp_path), "--draws", "30"])
    mock_precompute.assert_called_once()
