"""Consolidacao e agregacao de arquivos brutos de secoes eleitorais do TSE."""

from __future__ import annotations

import csv
import io
import time
import zipfile
from pathlib import Path
from typing import Any

from horizonte_eleitoral.ingestion.real_data_loader import RealDataLoader


def consolidate_2026_sections(
    zip_path: Path,
    out_csv: Path,
    max_sections: int | None = None,
) -> int:
    """Consolida os votos por candidato da eleicao presidencial de 2026 em secoes eleitorais.

    Args:
        zip_path: Caminho para votacao_secao_2026_BR.zip.
        out_csv: Caminho de saida para sections_2026.csv.
        max_sections: Limite maximo de secoes a extrair (None para todas).

    Returns:
        Total de secoes eleitorais consolidadas gravadas.

    Raises:
        FileNotFoundError: Se o arquivo zip de entrada nao existir.
    """
    if not zip_path.exists():
        raise FileNotFoundError(f"Arquivo zip nao encontrado: {zip_path}")

    t0 = time.time()
    sections: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    with zipfile.ZipFile(zip_path) as z:
        csv_names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            raise FileNotFoundError("Nenhum CSV encontrado no ZIP de 2026.")
        with z.open(csv_names[0]) as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";")
            for row in reader:
                sec_key = (
                    row["SG_UF"].strip().upper(),
                    row["CD_MUNICIPIO"].strip().zfill(5),
                    row["NR_ZONA"].strip().zfill(4),
                    row["NR_SECAO"].strip().zfill(4),
                )
                if sec_key not in sections:
                    if max_sections is not None and len(sections) >= max_sections:
                        break
                    sections[sec_key] = {
                        "local_code": row.get("NR_LOCAL_VOTACAO", "0001").strip().zfill(4),
                        "valid_votes": 0,
                        "votes_pt": 0,
                        "votes_pl": 0,
                        "votes_outros": 0,
                        "blank_votes": 0,
                        "null_votes": 0,
                        "turnout": 0,
                        "dt": row.get("DT_GERACAO", ""),
                        "hh": row.get("HH_GERACAO", ""),
                    }

                v = int(row.get("QT_VOTOS", 0) or 0)
                sec_data = sections[sec_key]
                sec_data["turnout"] = int(sec_data["turnout"]) + v
                cand = row.get("NR_VOTAVEL", "").strip()

                if cand in ("95", "BRANCO"):
                    sec_data["blank_votes"] = int(sec_data["blank_votes"]) + v
                elif cand in ("96", "NULO"):
                    sec_data["null_votes"] = int(sec_data["null_votes"]) + v
                else:
                    sec_data["valid_votes"] = int(sec_data["valid_votes"]) + v
                    if cand == "13":
                        sec_data["votes_pt"] = int(sec_data["votes_pt"]) + v
                    elif cand == "22":
                        sec_data["votes_pl"] = int(sec_data["votes_pl"]) + v
                    else:
                        sec_data["votes_outros"] = int(sec_data["votes_outros"]) + v

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", encoding="utf-8", newline="") as out_f:
        writer = csv.writer(out_f)
        writer.writerow(
            [
                "state",
                "municipality_code",
                "zone",
                "section",
                "local_code",
                "electorate",
                "valid_votes",
                "votes_pt",
                "votes_pl",
                "votes_outros",
                "blank_votes",
                "null_votes",
                "timestamp",
            ]
        )
        for (uf, muni, zone, sec), d in sections.items():
            tot = int(d["turnout"])
            elec = int(round(tot / 0.80)) if tot > 0 else 0
            ts = f"{d['dt']} {d['hh']}".strip()
            writer.writerow(
                [
                    uf,
                    muni,
                    zone,
                    sec,
                    d["local_code"],
                    elec,
                    d["valid_votes"],
                    d["votes_pt"],
                    d["votes_pl"],
                    d["votes_outros"],
                    d["blank_votes"],
                    d["null_votes"],
                    ts,
                ]
            )

    elapsed = time.time() - t0
    print(f"2026: {len(sections)} secoes gravadas em {out_csv} ({elapsed:.2f}s)")
    return len(sections)


def consolidate_2022_sections(
    zip_path: Path,
    out_csv: Path,
    max_sections: int | None = None,
) -> int:
    """Consolida os votos presidenciais de 2022 em secoes e locais historicos.

    Args:
        zip_path: Caminho para votacao_secao_2022_BR.zip.
        out_csv: Caminho de saida para historical_2022.csv.
        max_sections: Limite maximo de secoes a extrair (None para todas).

    Returns:
        Total de secoes eleitorais historicas consolidadas.

    Raises:
        FileNotFoundError: Se o arquivo zip de entrada nao existir.
    """
    if not zip_path.exists():
        raise FileNotFoundError(f"Arquivo zip nao encontrado: {zip_path}")

    t0 = time.time()
    sections: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    with zipfile.ZipFile(zip_path) as z:
        csv_names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            raise FileNotFoundError("Nenhum CSV encontrado no ZIP de 2022.")
        with z.open(csv_names[0]) as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";")
            for row in reader:
                sec_key = (
                    row["SG_UF"].strip().upper(),
                    row["CD_MUNICIPIO"].strip().zfill(5),
                    row["NR_ZONA"].strip().zfill(4),
                    row["NR_SECAO"].strip().zfill(4),
                )
                if sec_key not in sections:
                    if max_sections is not None and len(sections) >= max_sections:
                        break
                    sections[sec_key] = {
                        "local_code": row.get("NR_LOCAL_VOTACAO", "0001").strip().zfill(4),
                        "valid_votes": 0,
                        "votes_pt": 0,
                        "votes_pl": 0,
                        "votes_outros": 0,
                        "turnout": 0,
                    }

                v = int(row.get("QT_VOTOS", 0) or 0)
                sec_data = sections[sec_key]
                sec_data["turnout"] = int(sec_data["turnout"]) + v
                cand = row.get("NR_VOTAVEL", "").strip()

                if cand not in ("95", "96", "BRANCO", "NULO"):
                    sec_data["valid_votes"] = int(sec_data["valid_votes"]) + v
                    if cand == "13":
                        sec_data["votes_pt"] = int(sec_data["votes_pt"]) + v
                    elif cand == "22":
                        sec_data["votes_pl"] = int(sec_data["votes_pl"]) + v
                    else:
                        sec_data["votes_outros"] = int(sec_data["votes_outros"]) + v

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", encoding="utf-8", newline="") as out_f:
        writer = csv.writer(out_f)
        writer.writerow(
            [
                "state",
                "municipality_code",
                "zone",
                "section",
                "local_code",
                "electorate",
                "valid_votes",
                "votes_pt",
                "votes_pl",
                "votes_outros",
            ]
        )
        for (uf, muni, zone, sec), d in sections.items():
            tot = int(d["turnout"])
            elec = int(round(tot / 0.80)) if tot > 0 else 0
            writer.writerow(
                [
                    uf,
                    muni,
                    zone,
                    sec,
                    d["local_code"],
                    elec,
                    d["valid_votes"],
                    d["votes_pt"],
                    d["votes_pl"],
                    d["votes_outros"],
                ]
            )

    elapsed = time.time() - t0
    print(f"2022: {len(sections)} secoes historicas gravadas em {out_csv} ({elapsed:.2f}s)")
    return len(sections)


def consolidate_2018_sections(
    zip_path: Path,
    out_csv: Path,
    round_num: int = 1,
    max_sections: int | None = None,
) -> int:
    """Consolida os votos presidenciais de 2018 em secoes e locais historicos.

    Args:
        zip_path: Caminho para votacao_secao_2018_BR.zip.
        out_csv: Caminho de saida para historical_2018.csv.
        round_num: Turno da eleicao a extrair (1 para 1T, 2 para 2T).
        max_sections: Limite maximo de secoes a extrair (None para todas).

    Returns:
        Total de secoes eleitorais historicas consolidadas.

    Raises:
        FileNotFoundError: Se o arquivo zip de entrada nao existir.
    """
    if not zip_path.exists():
        raise FileNotFoundError(f"Arquivo zip nao encontrado: {zip_path}")

    t0 = time.time()
    sections: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    target_round = str(round_num)

    with zipfile.ZipFile(zip_path) as z:
        csv_names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            raise FileNotFoundError("Nenhum CSV encontrado em votacao_secao_2018_BR.zip")
        csv_name = csv_names[0]
        with z.open(csv_name) as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";")
            for row in reader:
                if row.get("NR_TURNO", "1").strip() != target_round:
                    continue
                cargo = row.get("CD_CARGO", "1").strip()
                ds_cargo = str(row.get("DS_CARGO", "")).upper()
                if cargo not in ("1", "PRESIDENTE") and "PRESIDENTE" not in ds_cargo:
                    continue

                sec_key = (
                    row["SG_UF"].strip().upper(),
                    row["CD_MUNICIPIO"].strip().zfill(5),
                    row["NR_ZONA"].strip().zfill(4),
                    row["NR_SECAO"].strip().zfill(4),
                )
                if sec_key not in sections:
                    if max_sections is not None and len(sections) >= max_sections:
                        break
                    sections[sec_key] = {
                        "local_code": row.get("NR_LOCAL_VOTACAO", "0001").strip().zfill(4),
                        "valid_votes": 0,
                        "votes_pt": 0,
                        "votes_pl": 0,
                        "votes_outros": 0,
                        "turnout": 0,
                    }

                v = int(row.get("QT_VOTOS", 0) or 0)
                sec_data = sections[sec_key]
                sec_data["turnout"] = int(sec_data["turnout"]) + v
                cand = row.get("NR_VOTAVEL", "").strip()

                if cand not in ("95", "96", "BRANCO", "NULO"):
                    sec_data["valid_votes"] = int(sec_data["valid_votes"]) + v
                    if cand == "13":
                        sec_data["votes_pt"] = int(sec_data["votes_pt"]) + v
                    elif cand in ("17", "22"):
                        sec_data["votes_pl"] = int(sec_data["votes_pl"]) + v
                    else:
                        sec_data["votes_outros"] = int(sec_data["votes_outros"]) + v

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", encoding="utf-8", newline="") as out_f:
        writer = csv.writer(out_f)
        writer.writerow(
            [
                "state",
                "municipality_code",
                "zone",
                "section",
                "local_code",
                "electorate",
                "valid_votes",
                "votes_pt",
                "votes_pl",
                "votes_outros",
            ]
        )
        for (uf, muni, zone, sec), d in sections.items():
            tot = int(d["turnout"])
            elec = int(round(tot / 0.80)) if tot > 0 else 0
            writer.writerow(
                [
                    uf,
                    muni,
                    zone,
                    sec,
                    d["local_code"],
                    elec,
                    d["valid_votes"],
                    d["votes_pt"],
                    d["votes_pl"],
                    d["votes_outros"],
                ]
            )

    elapsed = time.time() - t0
    msg = f"2018 (Turno {round_num}): {len(sections)} secoes historicas gravadas em {out_csv}"
    print(f"{msg} ({elapsed:.2f}s)")
    return len(sections)


def consolidate_real_catalog(
    historical_path: Path,
    results_path: Path,
    out_catalog: Path,
) -> int:
    """Pareia e consolida as secoes de 2026 com o historico de 2022 em catalogo analitico.

    Args:
        historical_path: Caminho para o arquivo CSV de historico de 2022.
        results_path: Caminho para o arquivo CSV de apuracao de 2026.
        out_catalog: Caminho de saida para gravacao de catalog_2026.parquet.

    Returns:
        Total de secoes eleitorais catalogadas e gravadas no arquivo Parquet.

    Raises:
        FileNotFoundError: Se algum dos arquivos de entrada nao existir.
    """
    if not historical_path.exists():
        raise FileNotFoundError(f"Arquivo de historico nao encontrado: {historical_path}")
    if not results_path.exists():
        raise FileNotFoundError(f"Arquivo de resultados nao encontrado: {results_path}")

    t0 = time.time()
    loader = RealDataLoader()
    locations, votes = loader.load_2022_historical_data(historical_path)
    results = loader.load_2026_results_data(results_path)
    catalog = loader.build_real_election_catalog(locations, votes, results)
    parquet_path = out_catalog.with_suffix(".parquet")
    total_saved = loader.save_catalog_parquet(catalog, parquet_path)
    elapsed = time.time() - t0
    print(f"Catalogo Parquet: {total_saved} secoes gravadas em {parquet_path} ({elapsed:.2f}s)")
    return total_saved
