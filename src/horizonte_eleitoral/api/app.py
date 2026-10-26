"""Aplicacao FastAPI somente leitura para consulta publica de projecoes eleitorais."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, status

from horizonte_eleitoral.api.schemas import (
    DataHealthResponse,
    GroupProjectionResponse,
    ModelCardResponse,
    ProjectionResponse,
)
from horizonte_eleitoral.publishing.models import PublishedProjectionPayload
from horizonte_eleitoral.publishing.publisher import AtomicPublisher

_DEFAULT_PUBLISHER = AtomicPublisher()


def get_publisher() -> AtomicPublisher:
    """Provedor de dependencia injetavel do publicador atomico.

    Returns:
        Instancia de AtomicPublisher ativa.
    """
    return _DEFAULT_PUBLISHER


PublisherDep = Annotated[AtomicPublisher, Depends(get_publisher)]


def create_app(publisher: AtomicPublisher | None = None) -> FastAPI:
    """Fabrica de criacao da aplicacao FastAPI configurada.

    Args:
        publisher: Instancia especifica de AtomicPublisher para testes.

    Returns:
        Aplicacao FastAPI pronta para execucao.
    """
    global _DEFAULT_PUBLISHER
    if publisher is not None:
        _DEFAULT_PUBLISHER = publisher

    application = FastAPI(
        title="Horizonte Eleitoral - API de Projecoes 2026",
        version="0.1.0",
        description="API somente leitura para consumo de estimativas e diagnosticos da apuracao.",
        docs_url="/docs",
        redoc_url=None,
    )

    def _payload_to_response(payload: PublishedProjectionPayload) -> ProjectionResponse:
        return ProjectionResponse(
            projection_id=payload.projection_id,
            published_at=payload.published_at,
            data_observed_at=payload.data_observed_at,
            status=payload.status,
            totalized_electorate_pct=payload.totalized_electorate_pct,
            groups=[
                GroupProjectionResponse(
                    code=g.code,
                    observed_share=g.observed_share,
                    projected_share=g.projected_share,
                    q05=g.q05,
                    q95=g.q95,
                )
                for g in payload.groups
            ],
            second_round_probability=payload.second_round_probability,
            data_quality=payload.data_quality,
            model_version=payload.model_version,
            snapshot_id=payload.snapshot_id,
        )

    @application.get(
        "/v1/projections/latest",
        response_model=ProjectionResponse,
        summary="Consulta a ultima projecao valida publicada",
    )
    async def get_latest_projection(
        geography: Annotated[str, Query(description="Escopo geografico (e.g. BR ou UF:SP)")] = "BR",
        pub: PublisherDep = None,  # type: ignore[assignment]
    ) -> ProjectionResponse:
        """Retorna a estimativa nacional mais recente disponivel."""
        payload = pub.get_latest(geography=geography)
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Nenhuma projecao publicada encontrada para a geografia '{geography}'.",
            )
        return _payload_to_response(payload)

    @application.get(
        "/v1/projections/history",
        response_model=list[ProjectionResponse],
        summary="Consulta o historico ordenado de projecoes publicadas",
    )
    async def get_projection_history(
        geography: Annotated[str, Query(description="Escopo geografico (e.g. BR ou UF:SP)")] = "BR",
        pub: PublisherDep = None,  # type: ignore[assignment]
    ) -> list[ProjectionResponse]:
        """Retorna todas as projecoes publicadas ordenadas cronologicamente."""
        payloads = pub.get_history(geography=geography)
        return [_payload_to_response(p) for p in payloads]

    @application.get(
        "/v1/projections/{projection_id}",
        response_model=ProjectionResponse,
        summary="Consulta uma projecao historica por seu identificador",
    )
    async def get_projection_by_id(
        projection_id: str,
        pub: PublisherDep = None,  # type: ignore[assignment]
    ) -> ProjectionResponse:
        """Permite auditoria e reproducao exata de uma versao previamente emitida."""
        payload = pub.get_by_id(projection_id)
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Projecao com ID '{projection_id}' nao foi encontrada.",
            )
        return _payload_to_response(payload)

    @application.get(
        "/v1/health/data",
        response_model=DataHealthResponse,
        summary="Diagnostico de integridade e defasagem das fontes",
    )
    async def get_data_health(
        pub: PublisherDep = None,  # type: ignore[assignment]
    ) -> DataHealthResponse:
        """Informa a idade dos dados e o status de consistencia operacional."""
        latest = pub.get_latest("BR")
        if latest is None:
            return DataHealthResponse(
                status="initializing",
                stale_seconds=0,
                last_observed_at=None,
                consistent_snapshots_count=0,
                divergent_snapshots_count=0,
            )

        now = datetime.now(UTC)
        obs_utc = (
            latest.data_observed_at.astimezone(UTC)
            if latest.data_observed_at.tzinfo
            else latest.data_observed_at.replace(tzinfo=UTC)
        )
        stale_sec = max(0, int((now - obs_utc).total_seconds()))
        health_status = (
            "healthy" if stale_sec < 600 else ("stale" if stale_sec < 1800 else "degraded")
        )

        return DataHealthResponse(
            status=health_status,
            stale_seconds=stale_sec,
            last_observed_at=obs_utc,
            consistent_snapshots_count=len(pub._by_id),
            divergent_snapshots_count=0,
        )

    @application.get(
        "/v1/model-card",
        response_model=ModelCardResponse,
        summary="Informacoes de transparencia metodologica e model card",
    )
    async def get_model_card() -> ModelCardResponse:
        """Exibe os metadados do modelo e seus limites estatisticos conhecidos."""
        return ModelCardResponse(
            system_name="Horizonte Eleitoral 2026 · HORIZON-MRP",
            model_version="HORIZON-MRP v2026.2",
            methodology=(
                "HORIZON-MRP (Hierarchical Optimal Regression & Inferred Zonal Outcomes Network): "
                "Modelo multinivel hierarquico bayesiano composicional em log-odds Versao 2 (v2) "
                "com modulacao adaptativa por elasticidade municipal 2018-2022, amostragem "
                "preditiva vetorizada de Monte Carlo (2000 draws) e calibracao exata "
                "via Newton-Raphson. Versao 1 arquivada como base de modelo legado."
            ),
            target_error_margin=(
                "Erro absoluto medio menor que 0.5 pp quando 10% do eleitorado estiver apurado."
            ),
            limitations=[
                "Estimativas em municipios sem secoes apuradas utilizam fallback regional.",
                "Discrepancias e atrasos nos boletins de urna bloqueiam novas projecoes.",
                "Nao substitui os numeros consolidados oficiais do Tribunal Superior Eleitoral.",
            ],
            disclaimer=(
                "A projecao estatistica nao substitui a apuracao oficial do "
                "Tribunal Superior Eleitoral."
            ),
        )

    return application


app = create_app()
