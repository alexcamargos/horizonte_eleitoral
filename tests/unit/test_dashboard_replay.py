"""Testes unitarios para o motor de replay historico e projecoes estaduais."""

from __future__ import annotations

from horizonte_eleitoral.dashboard.replay import (
    build_replay_point,
    generate_replay_timeline,
    generate_state_projections,
    load_replay_catalog,
)


def test_load_replay_catalog_and_sample_structure() -> None:
    """Valida o carregamento do catalogo analitico real com limite para replay."""
    catalog = load_replay_catalog(limit_sections=50)
    assert len(catalog) <= 50
    assert len(catalog) > 0

    first = catalog[0]
    assert "section_id" in first
    assert "state" in first
    assert "electorate" in first
    assert "valid_votes" in first


def test_build_replay_point_invariants() -> None:
    """Valida geracao de um ponto de apuracao e consistencia de chaves."""
    catalog = load_replay_catalog(limit_sections=40)
    point = build_replay_point(catalog=catalog, wave=0.20, num_draws=30, seed=123)

    assert "t" in point
    assert "x" in point
    assert "apurado" in point
    assert "PT" in point["apurado"]
    assert "PL" in point["apurado"]
    assert "OUTROS" in point["apurado"]

    # Para wave 0.20 (20%), ja deve haver projecao e faixa calculadas
    assert point["projecao"] is not None
    assert point["faixa"] is not None
    assert point["p_2turno"] is not None


def test_generate_replay_timeline_chronological_order() -> None:
    """Valida que a linha do tempo e gerada em ordem percentual crescente."""
    catalog = load_replay_catalog(limit_sections=40)
    timeline = generate_replay_timeline(
        catalog=catalog,
        current_wave=0.30,
        checkpoints=(0.05, 0.10, 0.20, 0.30),
    )

    assert len(timeline) == 4
    for idx in range(len(timeline) - 1):
        assert timeline[idx]["x"] <= timeline[idx + 1]["x"]


def test_generate_state_projections_coverage() -> None:
    """Valida o calculo de apuracao e diferenca com pesquisas por UF."""
    catalog = load_replay_catalog(limit_sections=50)
    states = generate_state_projections(catalog=catalog, wave=0.50)

    assert len(states) > 0
    first_state = states[0]
    assert "uf" in first_state
    assert "x" in first_state
    assert "PT" in first_state
    assert "PL" in first_state
    assert "diff_PT" in first_state
    assert "diff_PL" in first_state


def test_precomputed_checkpoints_match_reality() -> None:
    """Valida que os marcos precomputados correspondem a realidade eleitoral de 2026."""
    from horizonte_eleitoral.dashboard.replay import _load_precomputed_checkpoints

    checkpoints = _load_precomputed_checkpoints()
    if not checkpoints:
        return

    # No marco de 70% apurado
    pt_70 = checkpoints.get("0.700")
    assert pt_70 is not None
    assert pt_70["apurado"]["PL"] == 50.50
    assert pt_70["apurado"]["PT"] == 41.16

    proj = pt_70["projecao"]
    assert proj is not None
    assert abs(proj["PL"] - 46.95) <= 0.2
    assert abs(proj["PT"] - 45.21) <= 0.2

    faixa = pt_70["faixa"]
    assert faixa is not None
    # Realidade final do 1T 2026: PT 45.16%, PL 47.03%
    assert faixa["PT"][0] <= 45.16 <= faixa["PT"][1]
    assert faixa["PL"][0] <= 47.03 <= faixa["PL"][1]
    assert pt_70["p_2turno"] == 1.0


def test_generate_replay_timeline_includes_custom_current_wave() -> None:
    """Valida que um marco intermediario arbitrario do slider e incorporado na linha do tempo."""
    catalog = load_replay_catalog(limit_sections=40)
    timeline = generate_replay_timeline(
        catalog=catalog,
        current_wave=0.25,
        checkpoints=(0.10, 0.20, 0.30),
    )

    waves = [p["x"] for p in timeline]
    # Espera 10%, 20% e o marco corrente de 25%
    assert len(waves) == 3
    assert waves == sorted(waves)
    assert any(abs(w - 25.0) < 0.2 for w in waves)
