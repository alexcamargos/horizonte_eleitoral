"""Publicador atomico com troca segura e preservacao da ultima boa versao."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock

from horizonte_eleitoral.domain.enums import SnapshotStatus
from horizonte_eleitoral.domain.errors import ReconciliationError
from horizonte_eleitoral.domain.identity import deterministic_id
from horizonte_eleitoral.domain.models import CountSnapshot
from horizonte_eleitoral.publishing.models import (
    GroupProjectionDetail,
    PublishedProjectionPayload,
)
from horizonte_eleitoral.simulation.monte_carlo import SimulationSummary


class AtomicPublisher:
    """Garante publicacao transacional imutavel; falhas preservam a versao previa."""

    def __init__(self) -> None:
        """Inicializa o publicador com armazenamento em memoria protegido por lock."""
        self._lock = Lock()
        self._latest: PublishedProjectionPayload | None = None
        self._by_id: dict[str, PublishedProjectionPayload] = {}
        self._by_geography: dict[tuple[str, str], PublishedProjectionPayload] = {}

    def publish(
        self,
        *,
        snapshot: CountSnapshot,
        simulation: SimulationSummary,
        model_version: str = "2026.2",
        geography: str = "BR",
    ) -> PublishedProjectionPayload:
        """Valida e publica atomicamente uma nova projecao.

        Args:
            snapshot: Snapshot reconciliado de entrada.
            simulation: Sumario estatistico gerado pelas simulacoes preditivas.
            model_version: Versao do modelo preditivo empregado.
            geography: Escopo geografico (e.g. 'BR' ou 'UF:SP').

        Returns:
            PublishedProjectionPayload publicado com sucesso.

        Raises:
            ReconciliationError: Se o snapshot for divergente (bloqueando publicacao).
            InvariantViolationError: Se as invariantes de escala ou soma forem violadas.
        """
        # Regra de Ouro: snapshot divergente NUNCA pode ser publicado
        if snapshot.status is not SnapshotStatus.CONSISTENT:
            raise ReconciliationError(
                f"Snapshot {snapshot.snapshot_id} possui status DIVERGENTE "
                "e nao pode ser publicado."
            )

        published_at = datetime.now(UTC)

        # Converte as participacoes da escala estatistica [0, 1] para a escala externa [0, 100]
        mean_shares_dict = dict(simulation.projected_mean_shares)
        q05_dict = dict(simulation.q05_shares)
        q95_dict = dict(simulation.q95_shares)
        obs_shares_dict = dict(simulation.observed_shares)
        win_probs_dict = dict(simulation.candidate_win_probabilities)

        groups_detail: list[GroupProjectionDetail] = []
        for code in mean_shares_dict:
            groups_detail.append(
                GroupProjectionDetail(
                    code=code,
                    observed_share=round(obs_shares_dict.get(code, 0.0) * 100.0, 2),
                    projected_share=round(mean_shares_dict[code] * 100.0, 2),
                    q05=round(q05_dict.get(code, 0.0) * 100.0, 2),
                    q95=round(q95_dict.get(code, 0.0) * 100.0, 2),
                    win_probability=round(win_probs_dict.get(code, 0.0), 4),
                )
            )

        # Percentual de eleitorado apurado [0, 100]
        total_electorate = snapshot.total_electorate
        totalized = snapshot.totalized_electorate
        totalized_pct = (totalized / total_electorate * 100.0) if total_electorate > 0 else 0.0

        # Metadados de qualidade dos dados
        data_quality = {
            "total_electorate": total_electorate,
            "totalized_electorate": totalized,
            "pending_electorate": snapshot.pending_electorate,
        }

        # Gera ID determinista com namespace 'projection'
        projection_payload_meta = {
            "snapshot_id": snapshot.snapshot_id,
            "model_version": model_version,
            "geography": geography,
            "seed": simulation.seed,
        }
        projection_id = deterministic_id("projection", projection_payload_meta)

        payload = PublishedProjectionPayload(
            projection_id=projection_id,
            published_at=published_at,
            data_observed_at=snapshot.observed_at,
            status="published",
            totalized_electorate_pct=round(totalized_pct, 2),
            groups=tuple(sorted(groups_detail, key=lambda g: g.code)),
            second_round_probability=round(simulation.second_round_probability, 4),
            data_quality=data_quality,
            model_version=model_version,
            snapshot_id=snapshot.snapshot_id,
        )

        # Troca atomica protegida por Lock
        with self._lock:
            self._by_id[projection_id] = payload
            self._by_geography[(geography, projection_id)] = payload
            if geography == "BR":
                self._latest = payload

        return payload

    def get_latest(self, geography: str = "BR") -> PublishedProjectionPayload | None:
        """Retorna a ultima boa publicacao disponivel para a geografia solicitada.

        Args:
            geography: Escopo geografico desejado (default 'BR').

        Returns:
            PublishedProjectionPayload se disponivel, senao None.
        """
        with self._lock:
            if geography == "BR":
                return self._latest
            # Retorna a mais recente para a geografia
            matching = [p for (geo, _), p in self._by_geography.items() if geo == geography]
            return matching[-1] if matching else None

    def get_by_id(self, projection_id: str) -> PublishedProjectionPayload | None:
        """Busca uma projecao historica especifica pelo seu ID determinista.

        Args:
            projection_id: Identificador unico da projecao.

        Returns:
            PublishedProjectionPayload se encontrada, senao None.
        """
        with self._lock:
            return self._by_id.get(projection_id)

    def get_history(self, geography: str = "BR") -> list[PublishedProjectionPayload]:
        """Retorna a sequencia historica ordenada de projecoes para a geografia informada.

        Args:
            geography: Escopo territorial desejado (default 'BR').

        Returns:
            Lista de projecoes publicadas ordenadas por totalizacao e data de publicacao.

        Raises:
            None.
        """
        with self._lock:
            matching = [p for (geo, _), p in self._by_geography.items() if geo == geography]
            return sorted(
                matching,
                key=lambda x: (x.totalized_electorate_pct, x.published_at),
            )
