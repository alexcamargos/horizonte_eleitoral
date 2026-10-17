"""Calculo determinista de metricas de erro e calibracao para avaliacao estatistica."""

from __future__ import annotations

from collections.abc import Mapping


def compute_metrics(
    projected_shares: Mapping[str, float],
    final_shares: Mapping[str, float],
    groups: tuple[str, ...] = ("PT", "PL", "OUTROS"),
) -> tuple[float, float, float]:
    """Calcula MAE, vies medio e erro no saldo entre os dois principais candidatos.

    Args:
        projected_shares: Dicionario de participacoes estimadas pelo modelo.
        final_shares: Dicionario de participacoes reais no resultado final oficial.
        groups: Lista dos grupos eleitorais avaliados.

    Returns:
        Tupla com (mae, bias, lead_error).

    Raises:
        ValueError: Se algum grupo configurado nao estiver presente nos dicionarios.
    """
    for g in groups:
        if g not in projected_shares or g not in final_shares:
            raise ValueError(f"Grupo {g} ausente na comparacao de resultados.")

    errors = [projected_shares[g] - final_shares[g] for g in groups]
    mae = sum(abs(e) for e in errors) / len(groups)
    bias = sum(errors) / len(groups)

    # Identifica os dois principais no resultado real
    sorted_final = sorted(groups, key=lambda g: final_shares[g], reverse=True)
    g1, g2 = sorted_final[0], sorted_final[1]

    real_lead = final_shares[g1] - final_shares[g2]
    projected_lead = projected_shares[g1] - projected_shares[g2]
    lead_error = abs(projected_lead - real_lead)

    return round(mae, 6), round(bias, 6), round(lead_error, 6)
