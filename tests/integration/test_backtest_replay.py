"""Testes de integracao do motor de replay temporal de backtesting."""

from horizonte_eleitoral.backtest.replay import TimelineReplayer
from horizonte_eleitoral.models.baselines import (
    HistoricalNoSwingBaseline,
    NationalSwingBaseline,
    RawCountBaseline,
    UFSwingWithShrinkageBaseline,
)


def test_timeline_replay_executes_checkpoints_without_future_leak() -> None:
    """Valida execucao de replay temporal ponta a ponta comparando os 4 baselines."""
    # Conjunto sintetico de 10 secoes com eleitorado 100 cada (total 1000)
    sections_dataset: list[dict[str, object]] = []
    for i in range(10):
        sections_dataset.append(
            {
                "section_id": f"SP:1:{i}",
                "state": "SP" if i < 6 else "MG",
                "municipality_code": "71072" if i < 6 else "41238",
                "electorate": 100,
                "valid_votes": 80,
                "group_votes": (("PT", 40 + i), ("PL", 35 - i), ("OUTROS", 5)),
                "historical_shares": (("PT", 0.45), ("PL", 0.45), ("OUTROS", 0.10)),
            }
        )

    models = [
        RawCountBaseline(),
        HistoricalNoSwingBaseline(),
        NationalSwingBaseline(),
        UFSwingWithShrinkageBaseline(),
    ]

    replayer = TimelineReplayer(checkpoints_pct=(20.0, 50.0, 80.0))
    report = replayer.replay(
        election_id="002026",
        models=models,
        all_sections=sections_dataset,
        groups=("PT", "PL", "OUTROS"),
    )

    assert report.election_id == "002026"
    assert report.checkpoints == (20.0, 50.0, 80.0)

    # 4 modelos x 3 checkpoints = 12 metricas geradas
    assert len(report.metrics) == 12

    for m in report.metrics:
        assert m.mae >= 0.0
        assert m.lead_error >= 0.0
        assert m.runtime_seconds >= 0.0
        assert m.checkpoint_pct in (20.0, 50.0, 80.0)

    # Valida que o erro medio absoluto (MAE) diminui a medida que a apuracao avanca
    # para o baseline de apurado bruto
    raw_metrics = [m for m in report.metrics if m.model_name == "baseline_1_raw_count"]
    assert raw_metrics[2].checkpoint_pct == 80.0
    # No marco de 80%, o apurado bruto esta muito proximo do resultado final
    assert raw_metrics[2].mae < 0.05
