"""Estruturas de dados para execucao de replay temporal e avaliacao de backtest."""

from __future__ import annotations

from dataclasses import dataclass

from horizonte_eleitoral.domain.errors import InvariantViolationError


@dataclass(frozen=True, slots=True)
class CheckpointMetric:
    """Metricas de desempenho de um modelo em um determinado checkpoint de apuracao.

    Attributes:
        model_name: Nome do modelo avaliado.
        checkpoint_pct: Percentual do eleitorado totalizado no checkpoint (e.g. 10.0 para 10%).
        mae: Mean Absolute Error (Erro Medio Absoluto) ponderado entre os grupos.
        bias: Vies medio das estimativas em relacao ao resultado final.
        lead_error: Erro absoluto na diferenca (saldo) entre o 1o e o 2o colocados.
        runtime_seconds: Tempo decorrido na execucao da inferencia em segundos.
    """

    model_name: str
    checkpoint_pct: float
    mae: float
    bias: float
    lead_error: float
    runtime_seconds: float

    def __post_init__(self) -> None:
        """Valida que percentual e tempos sao nao negativos.

        Raises:
            InvariantViolationError: Se valores violarem os limites esperados.
        """
        if not 0.0 <= self.checkpoint_pct <= 100.0:
            raise InvariantViolationError("checkpoint_pct deve estar entre 0.0 e 100.0.")
        if self.mae < 0.0:
            raise InvariantViolationError("mae nao pode ser negativo.")
        if self.runtime_seconds < 0.0:
            raise InvariantViolationError("runtime_seconds nao pode ser negativo.")


@dataclass(frozen=True, slots=True)
class BacktestReport:
    """Relatorio consolidado de backtest comparando multiplos modelos ao longo do tempo.

    Attributes:
        election_id: Identificador da eleicao simulada.
        checkpoints: Lista de percentuais avaliados (e.g. [5.0, 10.0, 50.0, 95.0]).
        metrics: Tupla com todas as metricas calculadas por modelo e checkpoint.
    """

    election_id: str
    checkpoints: tuple[float, ...]
    metrics: tuple[CheckpointMetric, ...]
