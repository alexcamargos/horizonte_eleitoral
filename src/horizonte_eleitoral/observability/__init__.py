"""Modulo de observabilidade, metricas e telemetria estruturada."""

from __future__ import annotations

from horizonte_eleitoral.observability.logging import (
    StructuredJsonFormatter,
    setup_structured_logging,
)

__all__ = ["StructuredJsonFormatter", "setup_structured_logging"]
