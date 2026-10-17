"""Testes unitarios para funcoes de transformacao de dados do dashboard."""

from pytest_mock import MockerFixture

from horizonte_eleitoral.dashboard.components import (
    format_staleness_badge,
    parse_group_card_metrics,
)


def test_format_staleness_badge() -> None:
    """Valida niveis de alerta para staleness de dados."""
    text_normal, level_normal = format_staleness_badge(30)
    assert "30s" in text_normal
    assert level_normal == "normal"

    text_warn, level_warn = format_staleness_badge(800)  # ~13 min
    assert "13 min" in text_warn
    assert level_warn == "warning"

    text_err, level_err = format_staleness_badge(2400)  # 40 min
    assert "40 min" in text_err
    assert level_err == "error"


def test_parse_group_card_metrics() -> None:
    """Valida formatacao clara de cards comparando Apurado vs Projecao."""
    group_data = {
        "code": "PT",
        "observed_share": 44.12,
        "projected_share": 45.04,
        "q05": 43.80,
        "q95": 46.25,
    }
    card = parse_group_card_metrics(group_data)

    assert card["title"] == "Candidatura PT"
    assert card["projected_display"] == "45.0%"
    assert card["ci_display"] == "IC 90%: [43.8% - 46.2%]"
    assert card["observed_display"] == "44.1% apurado"


def test_dashboard_api_client_calls_endpoints(mocker: MockerFixture) -> None:
    """Valida que o DashboardApiClient consulta os endpoints e trata respostas corretamente."""
    from horizonte_eleitoral.dashboard.client import DashboardApiClient

    client = DashboardApiClient(base_url="http://testserver")

    mock_resp_latest = mocker.MagicMock()
    mock_resp_latest.status_code = 200
    mock_resp_latest.json.return_value = {"projection_id": "proj_123"}

    mock_resp_health = mocker.MagicMock()
    mock_resp_health.status_code = 200
    mock_resp_health.json.return_value = {"status": "healthy"}

    mock_resp_card = mocker.MagicMock()
    mock_resp_card.status_code = 200
    mock_resp_card.json.return_value = {"model_version": "2026.1"}

    mock_resp_history = mocker.MagicMock()
    mock_resp_history.status_code = 200
    mock_resp_history.json.return_value = [{"projection_id": "proj_123"}]

    mock_http_client = mocker.MagicMock()
    mock_http_client.__enter__.return_value = mock_http_client
    mock_http_client.get.side_effect = [
        mock_resp_latest,
        mock_resp_health,
        mock_resp_card,
        mock_resp_history,
    ]

    mocker.patch("httpx.Client", return_value=mock_http_client)

    latest = client.get_latest_projection("BR")
    assert latest == {"projection_id": "proj_123"}

    health = client.get_data_health()
    assert health == {"status": "healthy"}

    card = client.get_model_card()
    assert card == {"model_version": "2026.1"}

    history = client.get_projection_history("BR")
    assert history == [{"projection_id": "proj_123"}]


def test_fmt_pct_formatting() -> None:
    """Valida formatacao de porcentagem no padrao brasileiro com virgula."""
    from horizonte_eleitoral.dashboard.components import fmt_pct

    assert fmt_pct(45.24, decimals=1) == "45,2%"
    assert fmt_pct(45.24, decimals=2) == "45,24%"
    assert fmt_pct(None) == "–"
