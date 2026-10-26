"""Ponto de entrada oficial para deploy e execucao no Streamlit Community Cloud.

Configura o sys.path para reconhecer o pacote em src/ e executa o renderizador
principal do painel Horizonte Eleitoral.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Adiciona o diretorio src ao caminho de busca de modulos
_ROOT_DIR = Path(__file__).resolve().parent
_SRC_DIR = _ROOT_DIR / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from horizonte_eleitoral.dashboard.app import render_dashboard  # noqa: E402

if __name__ == "__main__":
    render_dashboard()
