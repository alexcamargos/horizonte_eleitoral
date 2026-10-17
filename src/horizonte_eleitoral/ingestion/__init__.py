"""Modulo de ingestao oficial do TSE com limitador e resolucao de caminhos."""

from __future__ import annotations

from horizonte_eleitoral.ingestion.client import TSEAsyncClient
from horizonte_eleitoral.ingestion.discovery import TSEPathResolver
from horizonte_eleitoral.ingestion.rate_limiter import AsyncRateLimiter
from horizonte_eleitoral.ingestion.real_data_loader import (
    DEFAULT_CANDIDATE_TAXONOMY,
    RealDataLoader,
    RealSectionRecord,
)

__all__ = [
    "DEFAULT_CANDIDATE_TAXONOMY",
    "AsyncRateLimiter",
    "RealDataLoader",
    "RealSectionRecord",
    "TSEAsyncClient",
    "TSEPathResolver",
]
