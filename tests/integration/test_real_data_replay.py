"""Testes de integracao para o replay completo de ondas de 10% a 100% sobre dados reais."""

from __future__ import annotations

from pathlib import Path

from horizonte_eleitoral.ingestion.real_data_loader import RealDataLoader
from horizonte_eleitoral.simulation.election_night_runner import simulate_2026_real_checkpoint

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "real_replay"


def test_full_wave_replay_on_real_data() -> None:
    """Valida o replay completo de apuracao de 10% a 100% com dados reais.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    loader = RealDataLoader()
    locations, votes = loader.load_2022_historical_data(FIXTURES_DIR / "sample_historical_2022.csv")
    records = loader.load_2026_results_data(FIXTURES_DIR / "sample_results_2026.csv")

    catalog = loader.build_real_election_catalog(locations, votes, records)
    assert len(catalog) == 20

    waves = (0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00)
    previous_totalized = -1.0

    for wave in waves:
        payload = simulate_2026_real_checkpoint(
            sections_catalog=catalog,
            progress_pct=wave,
            num_draws=40,
            seed=42,
            by_electorate=True,
        )

        assert payload.status == "published"
        assert payload.totalized_electorate_pct >= previous_totalized
        previous_totalized = payload.totalized_electorate_pct

        group_map = {g.code: g for g in payload.groups}
        assert "PT" in group_map
        assert "PL" in group_map
        assert "OUTROS" in group_map

        # A soma dos shares projetados deve ser aproximadamente 100%
        sum_shares = sum(g.projected_share for g in payload.groups)
        assert abs(sum_shares - 100.0) < 1.0

        # Para cada grupo, o intervalo de confianca [q05, q95] deve ser consistente
        for g in payload.groups:
            assert g.q05 <= g.projected_share <= g.q95
            assert 0.0 <= g.observed_share <= 100.0

    # No final (100%), o totalizado deve ser 100%
    assert previous_totalized == 100.0
