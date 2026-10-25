"""Testes unitarios para os graficos e componentes da aba de 2º Turno do dashboard."""

from __future__ import annotations

import altair as alt

from horizonte_eleitoral.dashboard.charts import build_second_round_chart
from horizonte_eleitoral.dashboard.components import (
    render_polling_log_table,
    render_polling_status_box,
    render_second_round_candidate_cards,
)
from horizonte_eleitoral.dashboard.replay import (
    build_second_round_live_point,
    build_second_round_replay_point,
    generate_second_round_timeline,
    load_replay_catalog,
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

    chart_pop = build_second_round_chart(points=sample_points)
    assert chart_pop is not None


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

    # Executa caixa de status
    render_polling_status_box(
        last_check_str="18:05:00 UTC",
        current_pct=50.0,
        is_auto_active=True,
        is_window_open=True,
        status_message="Operação normal.",
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
    assert point["x"] == 0.43
    assert point["x_sections"] == 0.25
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
