"""Testes de contrato para a API FastAPI somente leitura."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from horizonte_eleitoral.api.app import create_app
from horizonte_eleitoral.domain.enums import SnapshotStatus
from horizonte_eleitoral.domain.models import CountSnapshot
from horizonte_eleitoral.publishing.publisher import AtomicPublisher
from horizonte_eleitoral.simulation.monte_carlo import SimulationSummary


@pytest.fixture
def populated_publisher() -> AtomicPublisher:
    """Provedor de um AtomicPublisher populado com projecao valida."""
    publisher = AtomicPublisher()
    snapshot = CountSnapshot.create(
        observed_at=datetime(2026, 10, 4, 20, 15, tzinfo=UTC),
        status=SnapshotStatus.CONSISTENT,
        total_electorate=1000,
        totalized_electorate=400,
        pending_electorate=600,
        artifact_hashes=("a" * 64,),
        normalizer_version="2026.1",
        reconciliation_rule_version="2026.1",
    )
    simulation = SimulationSummary(
        projected_mean_shares=(("OUTROS", 0.10), ("PL", 0.45), ("PT", 0.45)),
        q05_shares=(("OUTROS", 0.08), ("PL", 0.42), ("PT", 0.42)),
        q50_shares=(("OUTROS", 0.10), ("PL", 0.45), ("PT", 0.45)),
        q95_shares=(("OUTROS", 0.12), ("PL", 0.48), ("PT", 0.48)),
        projected_mean_votes=(("OUTROS", 80), ("PL", 360), ("PT", 360)),
        observed_shares=(("OUTROS", 0.05), ("PL", 0.45), ("PT", 0.50)),
        second_round_probability=0.73,
        total_projected_valid_mean=800,
        num_draws=1000,
        seed=42,
    )
    publisher.publish(snapshot=snapshot, simulation=simulation)
    return publisher


def test_get_latest_projection_contract(populated_publisher: AtomicPublisher) -> None:
    """Valida o payload JSON e a conversao para escala percentual (0 a 100)."""
    app = create_app(populated_publisher)
    client = TestClient(app)

    response = client.get("/v1/projections/latest")
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "published"
    assert data["totalized_electorate_pct"] == 40.0
    assert data["second_round_probability"] == 0.73

    # Checa grupos e conversao de escala (0.45 -> 45.0)
    groups = {g["code"]: g for g in data["groups"]}
    assert groups["PT"]["projected_share"] == 45.0
    assert groups["PT"]["q05"] == 42.0
    assert groups["PT"]["q95"] == 48.0
    assert groups["PT"]["observed_share"] == 50.0

    assert groups["PL"]["projected_share"] == 45.0
    assert groups["OUTROS"]["projected_share"] == 10.0


def test_get_projection_by_id(populated_publisher: AtomicPublisher) -> None:
    """Consulta por projection_id retorna a versao historica exata."""
    app = create_app(populated_publisher)
    client = TestClient(app)

    latest = client.get("/v1/projections/latest").json()
    proj_id = latest["projection_id"]

    response = client.get(f"/v1/projections/{proj_id}")
    assert response.status_code == 200
    assert response.json()["projection_id"] == proj_id


def test_get_data_health_and_model_card(populated_publisher: AtomicPublisher) -> None:
    """Valida endpoints de diagnostico e model card institucional."""
    app = create_app(populated_publisher)
    client = TestClient(app)

    health_res = client.get("/v1/health/data")
    assert health_res.status_code == 200
    health_data = health_res.json()
    assert health_data["status"] in ("healthy", "stale", "degraded")
    assert health_data["consistent_snapshots_count"] >= 1

    card_res = client.get("/v1/model-card")
    assert card_res.status_code == 200
    card_data = card_res.json()
    assert "2026" in card_data["system_name"]
    assert len(card_data["limitations"]) > 0


def test_get_projection_history_contract(populated_publisher: AtomicPublisher) -> None:
    """Valida o endpoint de historico ordenado de projecoes publicadas."""
    app = create_app(populated_publisher)
    client = TestClient(app)

    response = client.get("/v1/projections/history")
    assert response.status_code == 200
    history = response.json()
    assert isinstance(history, list)
    assert len(history) == 1
    assert history[0]["status"] == "published"
    assert history[0]["totalized_electorate_pct"] == 40.0
