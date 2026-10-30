"""Testes unitarios para os graficos e componentes da aba de 2º Turno do dashboard."""

from __future__ import annotations

import altair as alt

from horizonte_eleitoral.dashboard.charts import (
    build_second_round_chart,
    build_second_round_error_chart,
)
from horizonte_eleitoral.dashboard.components import (
    render_polling_log_table,
    render_polling_status_box,
    render_second_round_candidate_cards,
)
from horizonte_eleitoral.dashboard.replay import (
    SECOND_ROUND_LIVE_MODEL_REV,
    build_second_round_live_point,
    build_second_round_replay_point,
    generate_second_round_timeline,
    load_replay_catalog,
    refresh_stale_second_round_points,
)
from horizonte_eleitoral.domain.enums import GeographicScope
from horizonte_eleitoral.normalization.models import NormalizedTotalization


def test_build_second_round_chart_empty_and_populated() -> None:
    """Valida geracao do grafico Altair para 2º turno vazio e com pontos reais."""
    chart_empty = build_second_round_chart(points=[])
    assert chart_empty is not None
    assert isinstance(chart_empty, alt.Chart)

    sample_points = [
        {
            "t": "17:30",
            "x": 20.0,
            "apurado": {"PT": 48.5, "PL": 51.5},
            "projecao": {"PT": 51.2, "PL": 48.8},
            "faixa": {"PT": [50.1, 52.3], "PL": [47.7, 49.9]},
        },
        {
            "t": "18:00",
            "x": 40.0,
            "apurado": {"PT": 49.8, "PL": 50.2},
            "projecao": {"PT": 51.0, "PL": 49.0},
            "faixa": {"PT": [50.3, 51.7], "PL": [48.3, 49.7]},
        },
    ]

    # Validacao com projecao estendida (padrao)
    chart_pop = build_second_round_chart(
        points=sample_points,
        active_wave=20.0,
        extend_to_end=True,
    )
    assert chart_pop is not None
    assert isinstance(chart_pop, (alt.Chart, alt.LayerChart))

    # Validacao sem projecao estendida (serie completa)
    chart_full = build_second_round_chart(
        points=sample_points,
        active_wave=20.0,
        extend_to_end=False,
    )
    assert chart_full is not None
    assert isinstance(chart_full, (alt.Chart, alt.LayerChart))


def test_build_second_round_error_chart_empty_and_populated() -> None:
    """Valida geracao do grafico Altair de erro absoluto vazio, com foco e onda ativa.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: Caso o grafico retornado nao seja uma instancia valida de alt.Chart.
    """
    chart_empty = build_second_round_error_chart(points=[])
    assert chart_empty is not None
    assert isinstance(chart_empty, alt.Chart)

    sample_metrics_points = [
        {
            "t": "17:04",
            "x": 2.0,
            "metrics": {
                "raw_mae_pp": 17.21,
                "model_mae_pp": 0.85,
                "ci_90_covered": False,
            },
        },
        {
            "t": "17:15",
            "x": 5.0,
            "metrics": {
                "raw_mae_pp": 7.13,
                "model_mae_pp": 0.09,
                "ci_90_covered": True,
            },
        },
        {
            "t": "17:34",
            "x": 10.0,
            "metrics": {
                "raw_mae_pp": 0.88,
                "model_mae_pp": 0.06,
                "ci_90_covered": True,
            },
        },
    ]

    # Teste com foco de precisao (y_max=4.0) e marcador de onda ativa (10.0%)
    chart_focused = build_second_round_error_chart(
        points=sample_metrics_points,
        height=320,
        y_max=4.0,
        active_wave=10.0,
    )
    assert chart_focused is not None
    assert isinstance(chart_focused, (alt.Chart, alt.LayerChart))

    # Teste com escala ampla automatica
    chart_wide = build_second_round_error_chart(
        points=sample_metrics_points,
        y_max=20.0,
    )
    assert chart_wide is not None
    assert isinstance(chart_wide, (alt.Chart, alt.LayerChart))


def test_build_second_round_replay_point_and_timeline() -> None:
    """Valida geracao de pontos e series temporais de 2º turno pelo modulo replay."""
    catalog = load_replay_catalog(limit_sections=40)
    point = build_second_round_replay_point(catalog=catalog, wave=0.30, num_draws=30)

    assert "t" in point
    assert "x" in point
    assert "apurado" in point
    assert "PT" in point["apurado"]
    assert "PL" in point["apurado"]
    assert "OUTROS" not in point["apurado"]

    assert point["projecao"] is not None
    assert "PT" in point["projecao"]
    assert "PL" in point["projecao"]

    # Gera linha do tempo com 2 marcos
    timeline = generate_second_round_timeline(
        catalog=catalog,
        current_wave=0.20,
        checkpoints=(0.10, 0.20),
    )
    assert len(timeline) == 2
    assert timeline[0]["x"] <= timeline[1]["x"]


def test_render_second_round_components_execute_cleanly() -> None:
    """Valida que componentes visuais executam sem erros de sintaxe ou tipo."""
    sample_point = {
        "t": "18:00",
        "x": 50.0,
        "apurado": {"PT": 51.0, "PL": 49.0},
        "projecao": {"PT": 51.5, "PL": 48.5},
        "faixa": {"PT": [50.5, 52.5], "PL": [47.5, 49.5]},
        "win_probability": {"PT": 0.85, "PL": 0.15},
    }

    # Executa renderizacao dos cards com latest_point
    render_second_round_candidate_cards(latest_point=sample_point)

    # Executa renderizacao dos cards com groups_payload da API
    api_groups = [
        {
            "code": "PT",
            "observed_share": 51.0,
            "projected_share": 51.5,
            "q05": 50.5,
            "q95": 52.5,
            "win_probability": 0.85,
        },
        {
            "code": "PL",
            "observed_share": 49.0,
            "projected_share": 48.5,
            "q05": 47.5,
            "q95": 49.5,
            "win_probability": 0.15,
        },
    ]
    render_second_round_candidate_cards(groups_payload=api_groups)

    # Executa caixa de status com e sem parametros estendidos
    render_polling_status_box(
        last_check_str="18:05:00 UTC",
        current_pct=50.0,
        is_auto_active=True,
        is_window_open=True,
        status_message="Operação normal.",
    )
    render_polling_status_box(
        last_check_str="17:06:31 UTC",
        current_pct=0.25,
        is_auto_active=True,
        is_window_open=True,
        status_message="Operação normal.",
        totalized_sections=1225,
        total_sections=499248,
        sections_pct=0.25,
        totalized_electorate=682901,
        total_electorate=158745502,
        electorate_pct=0.43,
        tse_timestamp_str="25/10/2026 17:06:27",
    )

    # Executa tabela de log vazia e preenchida
    render_polling_log_table([])
    render_polling_log_table(
        [
            {
                "Horário": "18:00:00",
                "Status": 200,
                "Apurado (%)": "50.00%",
                "Dados Novos": "Sim",
                "Mensagem": "OK",
                "URL": "https://resultados.tse.jus.br",
            }
        ]
    )


def test_build_second_round_live_point_with_real_tse_numbers() -> None:
    """Valida construcao de ponto real do TSE com 0.25% secoes e 0.43% eleitorado.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: Se os percentuais calculados divergirem da contagem do TSE.
    """
    totalization = NormalizedTotalization(
        scope=GeographicScope.BRAZIL,
        scope_code="BR",
        total_electorate=158745502,
        totalized_electorate=682901,
        pending_electorate=158745502 - 682901,
        total_sections=499248,
        totalized_sections=1225,
        pending_sections=499248 - 1225,
        valid_votes=335743,
        blank_votes=4158,
        null_votes=5153,
        candidate_group_votes=(("PL", 142169), ("PT", 193574)),
    )

    point = build_second_round_live_point(
        totalization=totalization,
        time_str="17:06",
    )

    assert point["t"] == "17:06"
    assert point["x"] == 0.25
    assert point["x_sections"] == 0.25
    assert point["electorate_pct"] == 0.43
    assert point["apurado"]["PT"] == 57.66
    assert point["apurado"]["PL"] == 42.34
    assert point["valid_votes"] == 335743
    assert point["totalized_sections"] == 1225
    assert point["is_live"] is True

    # Como x < 2.0%, projecao consolidada e IC permanecem None (Regra 4)
    assert point["projecao"] is None
    assert point["faixa"] is None
    assert point["win_probability"] is None

    # Renderiza o cartao sem erros
    render_second_round_candidate_cards(latest_point=point)


def test_build_second_round_live_point_above_threshold() -> None:
    """Valida que ponto do TSE >= 2.0% calcula projecao quando catalogo e fornecido.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: Se a projecao nao for calculada para x >= 2.0%.
    """
    totalization = NormalizedTotalization(
        scope=GeographicScope.BRAZIL,
        scope_code="BR",
        total_electorate=100000,
        totalized_electorate=5000,
        pending_electorate=95000,
        total_sections=400,
        totalized_sections=20,
        pending_sections=380,
        valid_votes=4000,
        blank_votes=200,
        null_votes=250,
        candidate_group_votes=(("PL", 1900), ("PT", 2100)),
    )

    catalog = load_replay_catalog(limit_sections=30)
    point = build_second_round_live_point(
        totalization=totalization,
        time_str="17:20",
        catalog=catalog,
        num_draws=20,
    )

    assert point["x"] == 5.00
    assert point["apurado"]["PT"] == 52.50
    assert point["apurado"]["PL"] == 47.50
    assert point["projecao"] is not None
    assert "PT" in point["projecao"]
    assert "PL" in point["projecao"]
    assert point["faixa"] is not None
    assert point["win_probability"] is not None

    render_second_round_candidate_cards(latest_point=point)


def test_build_second_round_live_point_responds_to_real_votes_at_81_pct() -> None:
    """Valida cenario real de 81,18% apurado com Lula em 51,32% projetando vitoria de Lula.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: Se a projecao ignorar os votos reais do TSE ou inverter o vencedor.
    """
    totalization = NormalizedTotalization(
        scope=GeographicScope.BRAZIL,
        scope_code="BR",
        total_electorate=158745502,
        totalized_electorate=127917125,
        pending_electorate=158745502 - 127917125,
        total_sections=499248,
        totalized_sections=405290,
        pending_sections=499248 - 405290,
        valid_votes=98500000,
        blank_votes=1800000,
        null_votes=2900000,
        candidate_group_votes=(("PL", 47949800), ("PT", 50550200)),
        generation_time="25/10/2026 20:55:00",
    )

    catalog = load_replay_catalog(limit_sections=120)
    point = build_second_round_live_point(
        totalization=totalization,
        time_str="20:55",
        catalog=catalog,
        num_draws=200,
        seed=42,
    )

    assert point["x"] == 81.18
    assert point["electorate_pct"] == 80.58
    assert point["apurado"]["PT"] == 51.32
    assert point["apurado"]["PL"] == 48.68
    assert point["model_rev"] == SECOND_ROUND_LIVE_MODEL_REV
    assert point["projecao"] is not None
    assert point["projecao"]["PT"] > 50.5
    assert point["projecao"]["PT"] > point["projecao"]["PL"]
    assert point["win_probability"]["PT"] > 0.90


def test_refresh_stale_second_round_points_heals_legacy_session_state() -> None:
    """Valida migracao automatica de pontos legados em st.session_state sem model_rev atualizado.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: Se o ponto legado congelado em 49,07% nao for recalculado corretamente.
    """
    catalog = load_replay_catalog(limit_sections=100)
    legacy_broken_point = {
        "t": "20:50",
        "x": 81.18,
        "x_sections": 81.18,
        "electorate_pct": 80.58,
        "apurado": {"PT": 51.32, "PL": 48.68},
        "projecao": {"PT": 49.07, "PL": 50.93},
        "faixa": {"PT": [49.06, 49.09], "PL": [50.91, 50.94]},
        "win_probability": {"PT": 0.001, "PL": 0.999},
        "valid_votes": 98500000,
        "totalized_sections": 405290,
        "total_sections": 499248,
        "totalized_electorate": 127917125,
        "total_electorate": 158745502,
        "votes": {"PL": 47949800, "PT": 50550200},
        "tse_time": "25/10/2026 20:50:00",
        "round": 2,
        "is_live": True,
    }

    healed = refresh_stale_second_round_points(
        points=[legacy_broken_point],
        catalog=catalog,
        num_draws=200,
        seed=42,
    )
    assert len(healed) == 1
    pt = healed[0]
    assert pt["t"] == "20:50"
    assert pt["model_rev"] == SECOND_ROUND_LIVE_MODEL_REV
    assert pt["projecao"]["PT"] > 50.5
    assert pt["win_probability"]["PT"] > 0.90


def test_slider_quick_jump_step_and_bounds() -> None:
    """Valida que saltos rapidos do controle deslizante obedecem aos limites de 0,25% a 100%."""
    curr = 5.0
    val_minus = max(0.25, min(100.0, round((curr - 10.0) * 4.0) / 4.0))
    assert val_minus == 0.25

    curr = 95.0
    val_plus = max(0.25, min(100.0, round((curr + 10.0) * 4.0) / 4.0))
    assert val_plus == 100.0

    target_start = max(0.25, min(100.0, 0.25))
    assert target_start == 0.25

    default_2t_val = 10.0
    assert max(0.25, min(100.0, default_2t_val)) == 10.0


def test_build_live_point_round_1_and_round_2() -> None:
    """Valida geracao de pontos em tempo real unificada para 1º e 2º turnos."""
    from horizonte_eleitoral.dashboard.replay import (
        build_live_point,
        build_live_replay_point,
    )

    tot_1t = NormalizedTotalization(
        scope=GeographicScope.BRAZIL,
        scope_code="BR",
        total_electorate=100_000_000,
        totalized_electorate=1_000_000,
        pending_electorate=99_000_000,
        total_sections=100_000,
        totalized_sections=1_000,
        pending_sections=99_000,
        valid_votes=800_000,
        blank_votes=20_000,
        null_votes=30_000,
        candidate_group_votes=(("OUTROS", 80_000), ("PL", 320_000), ("PT", 400_000)),
        generation_time="04/10/2026 17:15:00",
    )

    pt_1t = build_live_point(tot_1t, round_num=1, time_str="17:15")
    assert pt_1t["round"] == 1
    assert pt_1t["apurado"]["PT"] == 50.0
    assert pt_1t["apurado"]["PL"] == 40.0
    assert pt_1t["apurado"]["OUTROS"] == 10.0
    assert pt_1t["x_sections"] == 1.0
    assert pt_1t["electorate_pct"] == 1.0
    # < 2% nao emite projecao definitiva
    assert pt_1t["projecao"] is None

    tot_2t = NormalizedTotalization(
        scope=GeographicScope.BRAZIL,
        scope_code="BR",
        total_electorate=100_000_000,
        totalized_electorate=1_000_000,
        pending_electorate=99_000_000,
        total_sections=100_000,
        totalized_sections=1_000,
        pending_sections=99_000,
        valid_votes=800_000,
        blank_votes=20_000,
        null_votes=30_000,
        candidate_group_votes=(("PL", 380_000), ("PT", 420_000)),
        generation_time="25/10/2026 17:15:00",
    )

    pt_2t = build_live_point(tot_2t, round_num=2, time_str="17:15")
    assert pt_2t["round"] == 2
    assert pt_2t["apurado"]["PT"] == 52.5
    assert pt_2t["apurado"]["PL"] == 47.5
    assert pt_2t["x_sections"] == 1.0

    # Valida simulacao rapida via build_live_replay_point
    sample_catalog = [
        {
            "section_id": "SP:0001:0001",
            "state": "SP",
            "municipality_code": "00001",
            "zone": "0001",
            "section": "0001",
            "electorate": 300,
            "valid_votes": 250,
            "group_votes": (("OUTROS", 25), ("PL", 100), ("PT", 125)),
            "historical_shares": (("OUTROS", 0.10), ("PL", 0.40), ("PT", 0.50)),
            "match_quality": "EXACT",
        }
    ]
    sim_pt_2t = build_live_replay_point(sample_catalog, wave=0.10, round_num=2)
    assert sim_pt_2t["round"] == 2
    assert "apurado" in sim_pt_2t
