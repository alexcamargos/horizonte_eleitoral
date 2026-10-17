"""Schemas Pydantic estritos para os contratos de resposta da API somente leitura."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class GroupProjectionResponse(BaseModel):
    """Detalhe projetado para um grupo partidario individual."""

    code: str = Field(..., description="Codigo do grupo politico (e.g. PT, PL, OUTROS)")
    observed_share: float = Field(..., description="Participacao percentual apurada [0, 100]")
    projected_share: float = Field(..., description="Participacao percentual projetada [0, 100]")
    q05: float = Field(..., description="Limite inferior do IC 90% em percentual [0, 100]")
    q95: float = Field(..., description="Limite superior do IC 90% em percentual [0, 100]")


class ProjectionResponse(BaseModel):
    """Contrato publico de uma projecao eleitoral consolidada."""

    projection_id: str = Field(..., description="Identificador determinista da projecao")
    published_at: datetime = Field(..., description="Data e hora UTC da publicacao")
    data_observed_at: datetime = Field(
        ..., description="Data e hora UTC do corte de dados observados"
    )
    status: str = Field(..., description="Estado da publicacao (published)")
    totalized_electorate_pct: float = Field(
        ..., description="Percentual do eleitorado totalizado [0, 100]"
    )
    groups: list[GroupProjectionResponse] = Field(..., description="Lista de estimativas por grupo")
    second_round_probability: float = Field(
        ..., description="Probabilidade estimada de segundo turno [0, 1]"
    )
    data_quality: dict[str, int] = Field(
        ..., description="Metricas de qualidade dos dados de apuracao"
    )
    model_version: str = Field(..., description="Versao do modelo preditivo utilizado")
    snapshot_id: str = Field(..., description="Hash identificador do snapshot de origem")


class DataHealthResponse(BaseModel):
    """Diagnostico de integridade, qualidade e defasagem das fontes oficiais."""

    status: str = Field(
        ..., description="Estado geral de saude dos dados (healthy, stale, degraded)"
    )
    stale_seconds: int = Field(..., description="Idade dos dados mais recentes em segundos")
    last_observed_at: datetime | None = Field(
        None, description="Horario do dado mais recente recebido"
    )
    consistent_snapshots_count: int = Field(
        ..., description="Total de snapshots consistentes gerados"
    )
    divergent_snapshots_count: int = Field(
        ..., description="Total de snapshots divergentes retidos"
    )


class ModelCardResponse(BaseModel):
    """Transparencia metodologica e limitacoes conhecidas do sistema de previsao."""

    system_name: str = Field("Sistema de Projecao Eleitoral 2026", description="Nome do sistema")
    model_version: str = Field(..., description="Versao ativa do modelo estatistico")
    methodology: str = Field(..., description="Descricao sucinta do algoritmo e simulacao")
    target_error_margin: str = Field(
        "0.5 pp em 10% do eleitorado apurado", description="Meta de erro historica"
    )
    limitations: list[str] = Field(..., description="Limites conhecidos e condicoes de incerteza")
    disclaimer: str = Field(
        "A projecao estatistica nao substitui a apuracao oficial do Tribunal Superior Eleitoral.",
        description="Aviso legal e institucional",
    )
