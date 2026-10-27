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


def test_build_projection_chart_forward_projection_to_end() -> None:
    """Valida que o grafico do 1º turno projeta os votos ate o encerramento (100%)."""
    points = [
        {
            "t": "17:06",
            "x": 2.0,
            "apurado": {"PT": 35.77, "PL": 55.14, "OUTROS": 9.09},
            "projecao": {"PT": 45.25, "PL": 46.99, "OUTROS": 7.77},
            "faixa": {
                "PT": [44.66, 45.8],
                "PL": [46.41, 47.52],
                "OUTROS": [7.62, 7.94],
            },
        },
        {
            "t": "17:15",
            "x": 5.0,
            "apurado": {"PT": 35.62, "PL": 55.35, "OUTROS": 9.03},
            "projecao": {"PT": 45.32, "PL": 46.87, "OUTROS": 7.82},
            "faixa": {
                "PT": [44.75, 45.9],
                "PL": [46.3, 47.4],
                "OUTROS": [7.65, 8.0],
            },
        },
    ]

    chart = build_projection_chart(
        points=points,
        active_wave=5.0,
        extend_to_end=True,
        final_result={"PT": 45.16, "PL": 47.03, "OUTROS": 7.81},
    )
    assert isinstance(chart, alt.VConcatChart)
    chart_dict = chart.to_dict()
    assert len(chart_dict["vconcat"]) == 2

    # Verifica presenca de camadas no painel principal
    main_layers = chart_dict["vconcat"][0]["layer"]
    # Deve conter band, line_proj, points_proj, line_obs, points_obs, rule_50, text_50,
    # band_fwd, line_fwd, points_term, text_term, rule_final
    assert len(main_layers) >= 9

    # Verifica presenca de camadas no subpainel (OUTROS)
    sub_layers = chart_dict["vconcat"][1]["layer"]
    assert len(sub_layers) >= 6


def test_build_projection_chart_with_preliminary_data() -> None:
    """Valida que marcos preliminares (<2%) projetam corretamente ate 100%."""
    points = [
        {
            "t": "17:03",
            "x": 1.0,
            "apurado": {"PT": 36.16, "PL": 54.75, "OUTROS": 9.09},
            "projecao": None,
            "faixa": None,
            "preliminar": {"PT": 45.44, "PL": 46.77, "OUTROS": 7.79},
        }
    ]

    chart = build_projection_chart(points=points, active_wave=1.0, extend_to_end=True)
    assert isinstance(chart, alt.VConcatChart)
    chart_dict = chart.to_dict()
    assert len(chart_dict["vconcat"]) == 2
