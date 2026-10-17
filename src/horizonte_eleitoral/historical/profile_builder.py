"""Construtor determinista de perfis historicos de secao eleitoral a partir de participacoes."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from decimal import Decimal

from horizonte_eleitoral.domain.enums import MatchQuality
from horizonte_eleitoral.domain.errors import InvariantViolationError, ReconciliationError
from horizonte_eleitoral.domain.models import SectionKey
from horizonte_eleitoral.historical.models import (
    HistoricalVoteProfile,
    MatchCandidate,
    SectionHistoricalProfile,
)

BASE_QUALITY_SCORES: dict[MatchQuality, float] = {
    MatchQuality.EXACT: 1.0,
    MatchQuality.SAME_COMPLEX: 0.90,
    MatchQuality.NEIGHBORING: 0.75,
    MatchQuality.SAME_ZONE: 0.50,
    MatchQuality.SAME_MUNICIPALITY: 0.30,
    MatchQuality.UNMATCHED: 0.05,
}


class HistoricalProfileBuilder:
    """Constroi perfis de secao ponderando participacoes de votos sem duplicar totais absolutos."""

    def __init__(
        self,
        historical_votes: Mapping[str, HistoricalVoteProfile],
        configured_groups: tuple[str, ...] = ("PT", "PL", "OUTROS"),
    ) -> None:
        """Inicializa o construtor com os resultados historicos conhecidos.

        Args:
            historical_votes: Mapeamento de location_id para perfil de votacao historica.
            configured_groups: Lista ordenada de codigos de grupo estatisticos esperados.

        Returns:
            None.

        Raises:
            InvariantViolationError: Se configured_groups estiver vazio.
        """
        if not configured_groups:
            raise InvariantViolationError("E necessario configurar ao menos um grupo.")
        self._historical_votes = historical_votes
        self._configured_groups = configured_groups

    def build_profile(
        self,
        section: SectionKey,
        candidates: Sequence[MatchCandidate],
    ) -> SectionHistoricalProfile:
        """Deriva o perfil historico em participacoes percentuais para a secao de 2026.

        Args:
            section: Chave completa da secao eleitoral de 2026.
            candidates: Candidatas de pareamento com pesos normalizados.

        Returns:
            SectionHistoricalProfile com shares somando rigorosamente 1.0.

        Raises:
            ReconciliationError: Se nenhuma candidata possuir perfil historico correspondente.
            InvariantViolationError: Se os pesos das candidatas nao somarem 1.0.
        """
        if not candidates:
            raise ReconciliationError(
                f"Secao {section.section} na zona {section.zone} "
                "nao possui candidatas de pareamento."
            )

        total_weight = sum(cand.weight for cand in candidates)
        if abs(total_weight - 1.0) > 1e-4:
            raise InvariantViolationError(
                f"Pesos das candidatas devem somar 1.0 (soma encontrada: {total_weight:.4f})."
            )

        # Calculo da entropia normalizada de pareamento: H = - sum w * log2(w) / log2(k)
        num_candidates = len(candidates)
        if num_candidates <= 1:
            match_entropy = 0.0
        else:
            raw_entropy = -sum(
                cand.weight * math.log2(cand.weight) for cand in candidates if cand.weight > 0.0
            )
            max_entropy = math.log2(num_candidates)
            match_entropy = min(1.0, max(0.0, raw_entropy / max_entropy))

        primary_method = candidates[0].method
        base_score = BASE_QUALITY_SCORES.get(primary_method, 0.1)
        quality_score = max(0.01, min(1.0, base_score * (1.0 - 0.2 * match_entropy)))

        # Ponderacao de participacoes (shares) por grupo
        group_shares_sum: dict[str, float] = {group: 0.0 for group in self._configured_groups}
        matched_any = False

        for cand in candidates:
            vote_profile = self._historical_votes.get(cand.candidate_location_id)
            if vote_profile is None or vote_profile.valid_votes == 0:
                continue

            matched_any = True
            loc_votes = dict(vote_profile.group_votes)
            valid = float(vote_profile.valid_votes)

            # Acumula participacao ponderada: share = votos_grupo / valid_votes
            for group in self._configured_groups:
                share = loc_votes.get(group, 0) / valid
                group_shares_sum[group] += cand.weight * share

        # Se nenhum local tinha votos validos, atribui distribuicao uniforme
        if not matched_any:
            uniform_share = 1.0 / len(self._configured_groups)
            for group in self._configured_groups:
                group_shares_sum[group] = uniform_share

        # Converte para Decimal normalizado garantindo soma exata 1.0
        total_float = sum(group_shares_sum.values())
        raw_decimals: dict[str, Decimal] = {}
        for group in self._configured_groups:
            normalized_float = group_shares_sum[group] / total_float
            raw_decimals[group] = Decimal(f"{normalized_float:.6f}")

        diff = Decimal("1.000000") - sum(raw_decimals.values())
        first_group = self._configured_groups[0]
        raw_decimals[first_group] += diff

        shares_tuple = tuple(
            sorted(((grp, share) for grp, share in raw_decimals.items()), key=lambda x: x[0])
        )

        return SectionHistoricalProfile(
            section=section,
            shares=shares_tuple,
            match_entropy=round(match_entropy, 4),
            quality_score=round(quality_score, 4),
            primary_method=primary_method,
            candidates=tuple(candidates),
        )
