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
    build_second_round_replay_point,
    generate_second_round_timeline,
    load_replay_catalog,
)


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
    }

    # Executa renderizacao dos cards
    render_second_round_candidate_cards(latest_point=sample_point)

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
