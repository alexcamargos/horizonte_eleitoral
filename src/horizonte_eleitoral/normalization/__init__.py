"""Modulo de normalizacao e adaptadores de formatos de dados do TSE."""

from __future__ import annotations

from horizonte_eleitoral.normalization.adapters import (
    normalize_ea14,
    normalize_ea15,
    normalize_ea16,
    normalize_ea20,
)
from horizonte_eleitoral.normalization.models import (
    NormalizedSectionState,
    NormalizedTotalization,
)

__all__ = [
    "NormalizedSectionState",
    "NormalizedTotalization",
    "normalize_ea14",
    "normalize_ea15",
    "normalize_ea16",
    "normalize_ea20",
]
