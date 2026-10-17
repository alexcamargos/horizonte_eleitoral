"""Modulo de API publica somente leitura do Horizonte Eleitoral."""

from __future__ import annotations

from horizonte_eleitoral.api.app import app, create_app

__all__ = ["app", "create_app"]
