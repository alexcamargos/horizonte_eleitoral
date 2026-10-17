"""Testes unitarios para carregamento e consolidacao de dados historicos de 2018."""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

from horizonte_eleitoral.ingestion.consolidator import consolidate_2018_sections
from horizonte_eleitoral.ingestion.real_data_loader import RealDataLoader


def test_load_2018_historical_data_csv(tmp_path: Path) -> None:
    """Verifica que o carregador le arquivos CSV de 2018 e mapeia legendas corretamente."""
    csv_file = tmp_path / "test_2018.csv"
    with open(csv_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
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
        writer.writerow(["SP", "71072", "0001", "0001", "1001", "400", "300", "90", "180", "30"])

    loader = RealDataLoader()
    locations, votes = loader.load_2018_historical_data(csv_file)

    assert len(locations) == 1
    assert locations[0].state == "SP"
    assert locations[0].municipality_code == "71072"

    loc_id = locations[0].location_id
    assert loc_id in votes
    v_profile = votes[loc_id]
    assert v_profile.valid_votes == 300
    group_dict = dict(v_profile.group_votes)
    assert group_dict["PT"] == 90
    assert group_dict["PL"] == 180
    assert group_dict["OUTROS"] == 30


def test_consolidate_2018_sections_from_synthetic_zip(tmp_path: Path) -> None:
    """Valida a extracao de secoes presidenciais de 2018 a partir de arquivo zip simulado."""
    zip_path = tmp_path / "votacao_secao_2018_BR.zip"
    out_csv = tmp_path / "historical_2018.csv"

    # Cria ZIP simulado no formato do TSE
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as z:
        csv_content = io.StringIO()
        writer = csv.writer(csv_content, delimiter=";")
        writer.writerow(
            [
                "SG_UF",
                "CD_MUNICIPIO",
                "NR_ZONA",
                "NR_SECAO",
                "NR_LOCAL_VOTACAO",
                "NR_TURNO",
                "CD_CARGO",
                "DS_CARGO",
                "NR_VOTAVEL",
                "QT_VOTOS",
            ]
        )
        # Turno 1 - Haddad (13)
        writer.writerow(["SP", "71072", "1", "1", "1001", "1", "1", "Presidente", "13", "100"])
        # Turno 1 - Bolsonaro (17)
        writer.writerow(["SP", "71072", "1", "1", "1001", "1", "1", "Presidente", "17", "150"])
        # Turno 1 - Ciro Gomes (12 - Outros)
        writer.writerow(["SP", "71072", "1", "1", "1001", "1", "1", "Presidente", "12", "50"])
        # Turno 1 - Voto em branco
        writer.writerow(["SP", "71072", "1", "1", "1001", "1", "1", "Presidente", "95", "10"])
        # Turno 2 - Deve ser ignorado quando round_num=1
        writer.writerow(["SP", "71072", "1", "1", "1001", "2", "1", "Presidente", "13", "120"])
        # Cargo de Governador (3) - Deve ser ignorado
        writer.writerow(["SP", "71072", "1", "1", "1001", "1", "3", "Governador", "45", "110"])

        z.writestr("votacao_secao_2018_BR.csv", csv_content.getvalue().encode("latin1"))

    with open(zip_path, "wb") as f:
        f.write(zip_buffer.getvalue())

    total = consolidate_2018_sections(zip_path, out_csv, round_num=1)
    assert total == 1
    assert out_csv.exists()

    with open(out_csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        assert len(rows) == 1
        r = rows[0]
        assert r["state"] == "SP"
        assert r["municipality_code"] == "71072"
        assert r["valid_votes"] == "300"  # 100 + 150 + 50
        assert r["votes_pt"] == "100"
        assert r["votes_pl"] == "150"
        assert r["votes_outros"] == "50"
