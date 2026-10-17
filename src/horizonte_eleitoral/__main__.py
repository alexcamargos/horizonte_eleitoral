"""Ponto de entrada do pacote horizonte_eleitoral ao executar via python -m."""

from __future__ import annotations

import sys

from horizonte_eleitoral.cli import main

if __name__ == "__main__":
    main(sys.argv[1:])
