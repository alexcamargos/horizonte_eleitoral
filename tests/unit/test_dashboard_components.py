"""Testes unitarios para os componentes visuais do dashboard Streamlit."""

from __future__ import annotations

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
