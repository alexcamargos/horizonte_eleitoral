"""Script utilitario para consolidar arquivos brutos de secoes eleitorais do TSE."""

from __future__ import annotations

import sys
from pathlib import Path

from horizonte_eleitoral.config import get_final_data_dir, get_norm_data_dir, get_raw_data_dir
from horizonte_eleitoral.ingestion.consolidator import (
    consolidate_2018_sections,
    consolidate_2022_sections,
    consolidate_2026_sections,
    consolidate_real_catalog,
)


def _resolve_input(filename: str) -> Path:
    candidates = [
        get_raw_data_dir() / filename,
        Path("data/raw") / filename,
        Path("data/real") / filename,
        Path("data") / filename,
    ]
    for c in candidates:
        if c.exists():
            return c
    return get_raw_data_dir() / filename


def _resolve_norm(filename: str) -> Path:
    candidates = [
        get_norm_data_dir() / filename,
        Path("data/norm") / filename,
        Path("data/real") / filename,
        Path("data") / filename,
    ]
    for c in candidates:
        if c.exists():
            return c
    return get_norm_data_dir() / filename


def main() -> None:
    """Executa a consolidacao dos dados do TSE no sistema de raw, norm e final."""
    raw_dir = get_raw_data_dir()
    norm_dir = get_norm_data_dir()
    final_dir = get_final_data_dir()
    raw_dir.mkdir(parents=True, exist_ok=True)
    norm_dir.mkdir(parents=True, exist_ok=True)
    final_dir.mkdir(parents=True, exist_ok=True)

    zip_2026 = _resolve_input("votacao_secao_2026_BR.zip")
    out_2026 = norm_dir / "sections_2026.csv"
    if zip_2026.exists() and not out_2026.exists():
        consolidate_2026_sections(zip_2026, out_2026)

    zip_2022 = _resolve_input("votacao_secao_2022_BR.zip")
    out_2022 = norm_dir / "historical_2022.csv"
    if zip_2022.exists() and not out_2022.exists():
        consolidate_2022_sections(zip_2022, out_2022)

    zip_2018 = _resolve_input("votacao_secao_2018_BR.zip")
    out_2018 = norm_dir / "historical_2018.csv"
    if zip_2018.exists() and not out_2018.exists():
        consolidate_2018_sections(zip_2018, out_2018, round_num=1)

    force_rebuild = "--rebuild" in sys.argv or "--force" in sys.argv
    out_parquet = final_dir / "catalog_2026.parquet"
    in_2022 = _resolve_norm("historical_2022.csv")
    in_2026 = _resolve_norm("sections_2026.csv")
    if in_2022.exists() and in_2026.exists() and (not out_parquet.exists() or force_rebuild):
        consolidate_real_catalog(in_2022, in_2026, out_parquet)


if __name__ == "__main__":
    main()
