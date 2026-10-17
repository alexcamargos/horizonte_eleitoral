"""Modulo de visualizacao e dashboard operacional em Streamlit."""

from __future__ import annotations

from horizonte_eleitoral.dashboard.client import DashboardApiClient
from horizonte_eleitoral.dashboard.components import (
    format_staleness_badge,
    parse_group_card_metrics,
)

__all__ = [
    "DashboardApiClient",
    "format_staleness_badge",
    "parse_group_card_metrics",
]
