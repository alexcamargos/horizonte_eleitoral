"""Testes unitarios para os componentes visuais do dashboard Streamlit."""

from __future__ import annotations

from pytest_mock import MockerFixture

from horizonte_eleitoral.dashboard.components import (
    build_chart_guide_html,
    format_staleness_badge,
    parse_group_card_metrics,
)


def test_build_chart_guide_html_contains_orientation_and_legends() -> None:
    """Valida se o HTML gerado para o guia dos graficos contem orientacao e legendas completas."""
    html = build_chart_guide_html()

    # Verifica classes CSS estruturais
    assert "grafico-guia-container" in html
    assert "grafico-descricao" in html
    assert "grafico-legenda-grid" in html

    # Verifica texto orientativo
    assert "Como interpretar" in html
    assert "votos apurados" in html
    assert "projeção final" in html

    # Verifica itens da legenda de series/tracos
    assert "amostra-linha-solida" in html
    assert "Apurado (TSE)" in html
    assert "amostra-linha-tracejada" in html
    assert "Projeção Final" in html
    assert "amostra-faixa-ic" in html
    assert "Faixa de 90% (IC)" in html
    assert "amostra-linha-50" in html
    assert "50% (1º Turno)" in html

    # Verifica itens da legenda de candidaturas/cores
    assert "chave-PT" in html
    assert "Lula (PT)" in html
    assert "chave-PL" in html
    assert "Flávio Bolsonaro (PL)" in html
    assert "chave-OUTROS" in html
    assert "Outros (soma)" in html


def test_parse_group_card_metrics() -> None:
    """Valida a formatacao correta das metricas dos cartoes de grupo."""
    group_data = {
        "code": "PT",
        "observed_share": 43.5,
        "projected_share": 48.2,
        "q05": 47.1,
        "q95": 49.3,
    }
    metrics = parse_group_card_metrics(group_data)
    assert metrics["title"] == "Candidatura PT"
    assert metrics["projected_display"] == "48.2%"
    assert metrics["ci_display"] == "IC 90%: [47.1% - 49.3%]"
    assert metrics["observed_display"] == "43.5% apurado"


def test_format_staleness_badge() -> None:
    """Valida o rotulo e niveis de alerta para staleness."""
    text, level = format_staleness_badge(30)
    assert "30s" in text
    assert level == "normal"

    text, level = format_staleness_badge(700)
    assert "11 min" in text
    assert level == "warning"

    text, level = format_staleness_badge(2000)
    assert level == "error"


def test_build_chart_guide_html_round_2() -> None:
    """Valida legendas especificas de 2o turno com maioria absoluta e gabarito final."""
    html_2t = build_chart_guide_html(round_num=2)
    assert "50% (Maioria Absoluta)" in html_2t
    assert "Resultado Final TSE (100%)" in html_2t
    assert "amostra-linha-gabarito" in html_2t
    assert "Outros (soma)" not in html_2t


def test_get_custom_css_contains_design_tokens() -> None:
    """Valida presenca dos tokens de tema claro/escuro e classes estruturais no CSS."""
    from horizonte_eleitoral.dashboard.styles import get_custom_css

    css = get_custom_css()
    assert "--fundo-card" in css
    assert "--borda-card" in css
    assert "--badge-bg-pt" in css
    assert "--badge-bg-pl" in css
    assert "sidebar-model-badge" in css
    assert "chance-vitoria-box" in css
    assert "status-box-container" in css


def test_render_general_model_documentation(mocker: MockerFixture) -> None:
    """Valida renderizacao do expander de documentacao geral do modelo sem erros."""
    import streamlit as st

    from horizonte_eleitoral.dashboard.components import render_general_model_documentation

    mock_expander = mocker.patch.object(st, "expander")
    mock_markdown = mocker.patch.object(st, "markdown")
    mock_columns = mocker.patch.object(
        st, "columns", return_value=[mocker.MagicMock(), mocker.MagicMock()]
    )

    render_general_model_documentation()

    assert mock_expander.called
    assert mock_markdown.called
    assert mock_columns.called


def test_build_candidate_card_html_contains_standardized_tokens() -> None:
    """Valida presenca dos elementos padronizados do cartao de candidato em ambos os turnos."""
    from horizonte_eleitoral.dashboard.components import _build_candidate_card_html

    card_html = _build_candidate_card_html(
        bloco="PT",
        nome="Lula",
        partido_legenda="PT · 13",
        proj_val=51.70,
        obs_val=49.15,
        q05_val=51.58,
        q95_val=51.82,
        is_lider=True,
        status_box_text="🏆 Chance de Vitória: 99.9% (Liderança)",
        status_box_cls="chance-lider",
    )

    # Identidade visual e borda
    assert "cartao-candidato cartao-candidato-pt cartao-lider" in card_html
    assert "cartao-cabecalho" in card_html
    assert "Lula" in card_html
    assert "badge-partido-pt" in card_html
    assert "PT · 13" in card_html
    assert "cartao-badge-lider" in card_html
    assert "Líder projetado" in card_html

    # Projecao e rotulo explícito
    assert "cartao-valor-destaque cartao-projecao-pt" in card_html
    assert "51,70" in card_html
    assert "cartao-sinal-pct" in card_html
    assert "Projeção do resultado final" in card_html

    # Intervalo de 90%
    assert "Intervalo de 90%: 51,58% – 51,82%" in card_html

    # Urna e explicacao de vies
    assert "Oficial apurado no TSE:" in card_html
    assert "49,15%" in card_html
    assert "cartao-vies-nota" in card_html
    assert "Diferença de +2,6 pp decorre da ordem de apuração regional das urnas." in card_html

    # Rodape de status
    assert "chance-vitoria-box chance-lider" in card_html
    assert "Chance de Vitória: 99.9%" in card_html


def test_render_candidate_cards_1t_executes_cleanly() -> None:
    """Valida renderizacao dos 3 cartoes padronizados no 1º Turno sem erros."""
    from horizonte_eleitoral.dashboard.components import render_candidate_cards

    sample_point = {
        "t": "18:30",
        "x": 30.0,
        "apurado": {"PT": 36.87, "PL": 54.30, "OUTROS": 8.83},
        "projecao": {"PT": 45.19, "PL": 46.98, "OUTROS": 7.83},
        "faixa": {
            "PT": [44.91, 45.45],
            "PL": [46.71, 47.23],
            "OUTROS": [7.75, 7.92],
        },
    }
    render_candidate_cards(latest_point=sample_point)


def test_render_validation_panels_both_rounds_execute_cleanly() -> None:
    """Valida execucao do painel de 4 KPIs de validacao historica para 1º e 2º turno."""
    from horizonte_eleitoral.dashboard.components import (
        render_first_round_validation_panel,
        render_second_round_validation_panel,
    )

    pt_1t = {
        "metrics": {
            "model_mae_pp": 0.03,
            "raw_mae_pp": 5.53,
            "mae_gain_pp": 5.50,
            "ci_90_covered": True,
        }
    }
    summary_1t = {
        "final_oficial": {"PT": 45.16, "PL": 47.03, "OUTROS": 7.81},
        "ci_90_coverage_pct": 100.0,
        "statistical_call_pct": 2.0,
        "statistical_call_time": "17:06",
        "mean_model_mae_pp": 0.04,
    }
    render_first_round_validation_panel(latest_point=pt_1t, validation_summary=summary_1t)

    pt_2t = {
        "metrics": {
            "model_mae_pp": 0.09,
            "raw_mae_pp": 2.64,
            "mae_gain_pp": 2.55,
            "ci_90_covered": True,
        }
    }
    summary_2t = {
        "final_oficial": {"PT": 51.79, "PL": 48.21},
        "ci_90_coverage_pct": 92.3,
        "statistical_call_pct": 2.0,
        "statistical_call_time": "19:20",
        "mean_model_mae_pp": 0.12,
    }
    render_second_round_validation_panel(latest_point=pt_2t, validation_summary=summary_2t)


def test_summarize_first_round_validation_logic() -> None:
    """Valida geracao de metricas consolidadas do 1º Turno a partir de pontos simulados."""
    from horizonte_eleitoral.dashboard.replay import summarize_first_round_validation

    sample_points = [
        {
            "t": "17:03",
            "x": 1.0,
            "apurado": {"PT": 36.16, "PL": 54.75, "OUTROS": 9.09},
            "projecao": None,
            "faixa": None,
            "metrics": {},
        },
        {
            "t": "17:06",
            "x": 2.0,
            "apurado": {"PT": 35.77, "PL": 55.14, "OUTROS": 9.09},
            "projecao": {"PT": 45.25, "PL": 46.99, "OUTROS": 7.77},
            "faixa": {
                "PT": [44.66, 45.80],
                "PL": [46.41, 47.52],
                "OUTROS": [7.63, 7.91],
            },
            "metrics": {
                "model_mae_pp": 0.06,
                "raw_mae_pp": 6.26,
                "mae_gain_pp": 6.20,
                "ci_90_covered": True,
            },
        },
    ]

    summary = summarize_first_round_validation(sample_points)
    assert summary["winner_code"] == "PL"
    assert summary["partial_waves_count"] == 1
    assert summary["mean_model_mae_pp"] == 0.06
    assert summary["ci_90_coverage_pct"] == 100.0
    assert summary["statistical_call_pct"] == 2.0
