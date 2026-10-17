"""Script utilitario para consolidar arquivos brutos de secoes eleitorais do TSE."""

from __future__ import annotations

import sys
from pathlib import Path

from horizonte_eleitoral.ingestion.consolidator import (
    consolidate_2018_sections,
    consolidate_2022_sections,
    consolidate_2026_sections,
    consolidate_real_catalog,
)


def main() -> None:
    """Executa a consolidacao dos dados reais do TSE para a pasta data/real/."""
    data_dir = Path("data/real")
    zip_2026 = data_dir / "votacao_secao_2026_BR.zip"
    out_2026 = data_dir / "sections_2026.csv"
    if zip_2026.exists() and not out_2026.exists():
        consolidate_2026_sections(zip_2026, out_2026)

    zip_2022 = data_dir / "votacao_secao_2022_BR.zip"
    out_2022 = data_dir / "historical_2022.csv"
    if zip_2022.exists() and not out_2022.exists():
        consolidate_2022_sections(zip_2022, out_2022)

    zip_2018 = data_dir / "votacao_secao_2018_BR.zip"
    out_2018 = data_dir / "historical_2018.csv"
    if zip_2018.exists() and not out_2018.exists():
        consolidate_2018_sections(zip_2018, out_2018, round_num=1)

    force_rebuild = "--rebuild" in sys.argv or "--force" in sys.argv
    out_parquet = data_dir / "catalog_2026.parquet"
    if out_2022.exists() and out_2026.exists() and (not out_parquet.exists() or force_rebuild):
        consolidate_real_catalog(out_2022, out_2026, out_parquet)


if __name__ == "__main__":
    main()
