"""Modulo de backtesting e replay cronologico sem vazamento temporal."""

from __future__ import annotations

from horizonte_eleitoral.backtest.metrics import compute_metrics
from horizonte_eleitoral.backtest.models import BacktestReport, CheckpointMetric
from horizonte_eleitoral.backtest.replay import TimelineReplayer

__all__ = [
    "BacktestReport",
    "CheckpointMetric",
    "TimelineReplayer",
    "compute_metrics",
]
