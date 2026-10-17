"""Modulo de logs estruturados em formato JSON com propagacao de contexto."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class StructuredJsonFormatter(logging.Formatter):
    """Formatador de logs em JSON compativel com coletores de observabilidade."""

    def format(self, record: logging.LogRecord) -> str:
        """Formata o registro de log como string JSON canonica.

        Args:
            record: Objeto LogRecord emitido pela aplicacao.

        Returns:
            String JSON estruturada com campos contextuais.
        """
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Extrai atributos adicionais passados via 'extra'
        for key in (
            "correlation_id",
            "snapshot_id",
            "projection_id",
            "artifact_id",
            "model_version",
        ):
            val = getattr(record, key, None)
            if val is not None:
                payload[key] = val

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def setup_structured_logging(level: int = logging.INFO) -> logging.Logger:
    """Configura e retorna o logger raiz estruturado para a aplicacao.

    Args:
        level: Nivel de severidade do logging (default INFO).

    Returns:
        Instancia de logging.Logger configurada.
    """
    logger = logging.getLogger("horizonte_eleitoral")
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(StructuredJsonFormatter())
        logger.addHandler(handler)

    return logger
