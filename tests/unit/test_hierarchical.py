"""Testes unitarios para o modelo hierarquico composicional e softmax estavel."""

import numpy as np

from horizonte_eleitoral.models.base import PendingSection, SectionObservation
from horizonte_eleitoral.models.hierarchical import (
    HierarchicalBayesianModel,
    stable_softmax,
)


def test_stable_softmax_sums_to_one() -> None:
    """Valida que a softmax numericamente estavel retorna probabilidades somando 1.0."""
    logits = np.array([1000.0, 1002.0, 998.0])  # Valores muito altos que causariam overflow simples
    base_shares = np.array([0.4, 0.4, 0.2])

    p = stable_softmax(logits, base_shares)
    assert np.all(p >= 0.0)
    assert np.all(p <= 1.0)
    assert abs(np.sum(p) - 1.0) < 1e-6


def test_hierarchical_bayesian_model_prediction() -> None:
    """Valida previsao pontual do modelo hierarquico com encolhimento multinivel."""
    obs = [
        SectionObservation(
            section_id="SP:71072:1:1",
            state="SP",
            municipality_code="71072",
            valid_votes=400,
            group_votes=(("PT", 220), ("PL", 140), ("OUTROS", 40)),
            historical_shares=(("PT", 0.45), ("PL", 0.45), ("OUTROS", 0.10)),
        ),
        SectionObservation(
            section_id="MG:41238:1:1",
            state="MG",
            municipality_code="41238",
            valid_votes=300,
            group_votes=(("PT", 150), ("PL", 120), ("OUTROS", 30)),
            historical_shares=(("PT", 0.45), ("PL", 0.45), ("OUTROS", 0.10)),
        ),
    ]

    pending = [
        PendingSection(
            section_id="SP:71072:1:2",
            state="SP",
            municipality_code="71072",
            electorate=500,
            historical_shares=(("PT", 0.45), ("PL", 0.45), ("OUTROS", 0.10)),
        )
    ]

    model = HierarchicalBayesianModel()
    result = model.predict(observations=obs, pending=pending)

    shares = dict(result.projected_shares)
    assert abs(sum(shares.values()) - 1.0) < 1e-4
    assert result.model_name == "hierarchical_bayesian_composite"
    assert result.total_projected_valid > 700
