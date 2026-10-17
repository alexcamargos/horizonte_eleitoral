"""Testes unitarios para o logger estruturado em formato JSON."""

import json
import logging

from horizonte_eleitoral.observability.logging import (
    StructuredJsonFormatter,
    setup_structured_logging,
)


def test_structured_json_formatter() -> None:
    """Valida formatacao de record com campos contextuais e conversao JSON."""
    formatter = StructuredJsonFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="Teste de mensagem estruturada",
        args=(),
        exc_info=None,
    )
    record.correlation_id = "corr_123"  # type: ignore[attr-defined]
    record.snapshot_id = "snap_456"  # type: ignore[attr-defined]
    record.projection_id = "proj_789"  # type: ignore[attr-defined]

    formatted_str = formatter.format(record)
    parsed = json.loads(formatted_str)

    assert parsed["level"] == "INFO"
    assert parsed["message"] == "Teste de mensagem estruturada"
    assert parsed["correlation_id"] == "corr_123"
    assert parsed["snapshot_id"] == "snap_456"
    assert parsed["projection_id"] == "proj_789"
    assert "timestamp" in parsed


def test_setup_structured_logging() -> None:
    """Valida criacao e reuso do logger raiz estruturado."""
    logger = setup_structured_logging(logging.DEBUG)
    assert logger.name == "horizonte_eleitoral"
    assert logger.level == logging.DEBUG
    assert len(logger.handlers) >= 1
