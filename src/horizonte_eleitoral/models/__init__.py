"""Modulo de modelos estatisticos e baselines de projecao."""

from __future__ import annotations

from horizonte_eleitoral.models.base import (
    ForecastModel,
    ForecastResult,
    PendingSection,
    SectionObservation,
)
from horizonte_eleitoral.models.baselines import (
    HistoricalNoSwingBaseline,
    NationalSwingBaseline,
    RawCountBaseline,
    UFSwingWithShrinkageBaseline,
)
from horizonte_eleitoral.models.hierarchical import (
    HierarchicalBayesianModelV1,
)
from horizonte_eleitoral.models.hierarchical_v2 import (
    HierarchicalBayesianModelV2,
    HorizonMRP,
    HorizonMRPModel,
)
from horizonte_eleitoral.models.swing import SwingEstimator

# HORIZON-MRP (Versao 2 com elasticidade 2018-2022) e o modelo preditivo padrao do sistema
HierarchicalBayesianModel = HierarchicalBayesianModelV2

__all__ = [
    "ForecastModel",
    "ForecastResult",
    "HierarchicalBayesianModel",
    "HierarchicalBayesianModelV1",
    "HierarchicalBayesianModelV2",
    "HistoricalNoSwingBaseline",
    "HorizonMRP",
    "HorizonMRPModel",
    "NationalSwingBaseline",
    "PendingSection",
    "RawCountBaseline",
    "SectionObservation",
    "SwingEstimator",
    "UFSwingWithShrinkageBaseline",
]
