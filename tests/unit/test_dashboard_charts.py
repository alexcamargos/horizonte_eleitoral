"""Testes unitarios para criacao dos graficos interativos de projecao em Altair."""

from __future__ import annotations

import altair as alt

from horizonte_eleitoral.dashboard.charts import (
    build_projection_chart,
    prepare_chart_dataframe,
)


def test_prepare_chart_dataframe_structure() -> None:
    """Valida a conversao da lista de pontos para DataFrame tabular do Altair."""
    points = [
        {
            "t": "17:30",
            "x": 15.0,
            "apurado": {"PT": 42.0, "PL": 48.0, "OUTROS": 10.0},
            "projecao": {"PT": 45.0, "PL": 47.0, "OUTROS": 8.0},
            "faixa": {
                "PT": [44.0, 46.0],
                "PL": [46.0, 48.0],
                "OUTROS": [7.0, 9.0],
            },
        }
    ]

    df = prepare_chart_dataframe(points)
    assert len(df) == 3  # PT, PL, OUTROS
    assert set(df["bloco"]) == {"PT", "PL", "OUTROS"}
    assert df[df["bloco"] == "PT"]["q05"].iloc[0] == 44.0
    assert df[df["bloco"] == "PT"]["q95"].iloc[0] == 46.0
    assert df[df["bloco"] == "PL"]["projecao"].iloc[0] == 47.0


def test_build_projection_chart_with_empty_points() -> None:
    """Valida que lista vazia de pontos gera grafico de espera sem excecao e com subtitulo."""
    chart = build_projection_chart([])
    assert isinstance(chart, alt.Chart)
    chart_dict = chart.to_dict()
    assert isinstance(chart_dict["title"], dict)
    assert chart_dict["title"]["text"] == "Aguardando dados de apuração..."
    assert "subtitle" in chart_dict["title"]


def test_build_projection_chart_with_data() -> None:
    """Valida a concatenacao vertical dos dois paineis com subtitulos informativos."""
    points = [
        {
            "t": "17:15",
            "x": 1.5,
            "apurado": {"PT": 38.0, "PL": 52.0, "OUTROS": 10.0},
            "projecao": None,
            "faixa": None,
        },
        {
            "t": "17:30",
            "x": 10.0,
            "apurado": {"PT": 42.0, "PL": 48.0, "OUTROS": 10.0},
            "projecao": {"PT": 45.2, "PL": 46.8, "OUTROS": 8.0},
            "faixa": {
                "PT": [44.5, 45.9],
                "PL": [46.1, 47.5],
                "OUTROS": [7.5, 8.5],
            },
        },
    ]

    chart = build_projection_chart(points)
    assert isinstance(chart, alt.VConcatChart)
    chart_dict = chart.to_dict()
    assert "vconcat" in chart_dict
    assert len(chart_dict["vconcat"]) == 2

    # Verifica titulos e subtitulos dos paineis
    main_title = chart_dict["vconcat"][0]["title"]
    sub_title = chart_dict["vconcat"][1]["title"]
    assert isinstance(main_title, dict)
    assert "subtitle" in main_title
    assert "Apurado oficial (TSE)" in main_title["subtitle"]
    assert "Projeção final" in main_title["subtitle"]

    assert isinstance(sub_title, dict)
    assert "subtitle" in sub_title
    assert "Apurado oficial (TSE)" in sub_title["subtitle"]
