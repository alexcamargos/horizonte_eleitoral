"""Testes unitarios para os adaptadores de normalizacao e quarentena de dados brutos."""

import pytest

from horizonte_eleitoral.domain.enums import GeographicScope
from horizonte_eleitoral.domain.errors import ValidationError
from horizonte_eleitoral.normalization.adapters import (
    normalize_ea14,
    normalize_ea15,
    normalize_ea16,
    normalize_ea20,
)


def test_normalize_ea14_parses_ufs() -> None:
    """Valida conversao do resumo EA14 para dicionario de versoes por UF."""
    payload = b'{"ufs": [{"uf": "sp", "ver": "v1"}, {"uf": "rj", "dh": "2026-10-04T18:00:00Z"}]}'
    result = normalize_ea14(payload)
    assert result["SP"] == "v1"
    assert result["RJ"] == "2026-10-04T18:00:00Z"


def test_normalize_ea15_parses_municipalities() -> None:
    """Valida conversao do resumo EA15 para dicionario de versoes por municipio."""
    payload = (
        b'{"mun": [{"cd": "71072", "ver": "v2"}, {"cd": "60011", "dh": "2026-10-04T18:05:00Z"}]}'
    )
    result = normalize_ea15(payload)
    assert result["71072"] == "v2"
    assert result["60011"] == "2026-10-04T18:05:00Z"


def test_normalize_ea16_parses_sections() -> None:
    """Valida conversao da lista de secoes EA16 para NormalizedSectionState."""
    payload = (
        b'{"sec": ['
        b'  {"z": "1", "s": "7", "ha": "hash_a", "st": "T", "da": "2026-10-04T18:00:00Z"},'
        b'  {"z": "1", "s": "8", "ha": "hash_b", "st": "P"}'
        b"]}"
    )
    sections = normalize_ea16(payload, state="SP", municipality_code="71072")
    assert len(sections) == 2
    assert sections[0].zone == "0001"
    assert sections[0].section == "0007"
    assert sections[0].is_totalized is True
    assert sections[1].zone == "0001"
    assert sections[1].section == "0008"
    assert sections[1].is_totalized is False


def test_normalize_ea20_parses_totalization_and_aggregates_groups() -> None:
    """Valida conversao do EA20 agregando votos por grupos configurados."""
    payload = (
        b'{"abrangencia": "BR", "e": 1000, "e_tot": 400, "sec_tot": 10, "sec_apu": 4,'
        b' "vv": 350, "vb": 25, "vn": 25,'
        b' "cand": [{"n": "13", "v": 175}, {"n": "22", "v": 140}, {"n": "15", "v": 35}]}'
    )
    totalization = normalize_ea20(payload)
    assert totalization.scope == GeographicScope.BRAZIL
    assert totalization.total_electorate == 1000
    assert totalization.totalized_electorate == 400
    assert totalization.pending_electorate == 600
    assert totalization.valid_votes == 350

    votes_dict = dict(totalization.candidate_group_votes)
    assert votes_dict["PT"] == 175
    assert votes_dict["PL"] == 140
    assert votes_dict["OUTROS"] == 35  # Candidato 15 vai para OUTROS


def test_normalization_quarantines_malformed_json() -> None:
    """JSON truncado ou invalido lanca ValidationError para desvio em quarentena."""
    with pytest.raises(ValidationError, match="invalida"):
        normalize_ea14(b'{"ufs": [invalido')

    with pytest.raises(ValidationError, match="raiz"):
        normalize_ea20(b'["nao_objeto"]')


def test_normalize_ea20_parses_real_tse_nested_format() -> None:
    """Valida conversao do formato oficial aninhado da CDN do TSE (u.json com carg, s, e, v)."""
    payload = b"""
    {
        "ele": "6258",
        "t": "2",
        "tpabr": "br",
        "cdabr": "br",
        "s": {"ts": "499.248", "st": "150.000"},
        "e": {"te": "158.745.502", "est": "45.000.000"},
        "v": {"vv": "38.000.000", "vb": "1.000.000", "vn": "1.500.000"},
        "carg": [
            {
                "cd": "1",
                "agr": [
                    {
                        "par": [
                            {
                                "cand": [
                                    {"n": "13", "nmu": "LULA", "vap": "20.000.000"}
                                ]
                            }
                        ]
                    },
                    {
                        "par": [
                            {
                                "cand": [
                                    {"n": "22", "nmu": "FLAVIO BOLSONARO", "vap": "18.000.000"}
                                ]
                            }
                        ]
                    }
                ]
            }
        ]
    }
    """
    totalization = normalize_ea20(payload, round_num=2)
    assert totalization.total_electorate == 158745502
    assert totalization.totalized_electorate == 45000000
    assert totalization.total_sections == 499248
    assert totalization.totalized_sections == 150000
    assert totalization.valid_votes == 38000000
    assert totalization.blank_votes == 1000000
    assert totalization.null_votes == 1500000

    votes_dict = dict(totalization.candidate_group_votes)
    assert votes_dict["PT"] == 20000000
    assert votes_dict["PL"] == 18000000
    assert totalization.scope == GeographicScope.BRAZIL
    assert totalization.scope_code == "BR"


def test_normalize_ea20_parses_uf_scope_from_tpabr_and_cdabr() -> None:
    """Valida extracao de GeographicScope.STATE e sigla UF a partir de tpabr/cdabr do TSE.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: Se o escopo estadual nao for reconhecido corretamente.
    """
    payload_uf = b"""
    {
        "ele": "6258",
        "t": "2",
        "tpabr": "uf",
        "cdabr": "ba",
        "s": {"ts": "35000", "st": "28000"},
        "e": {"te": "11200000", "est": "8960000"},
        "v": {"vv": "7000000", "vb": "100000", "vn": "200000"},
        "carg": [
            {
                "cd": "1",
                "agr": [
                    {"par": [{"cand": [{"n": "13", "vap": "5040000"}]}]},
                    {"par": [{"cand": [{"n": "22", "vap": "1960000"}]}]}
                ]
            }
        ]
    }
    """
    tot_ba = normalize_ea20(payload_uf, round_num=2)
    assert tot_ba.scope == GeographicScope.STATE
    assert tot_ba.scope_code == "BA"
    assert dict(tot_ba.candidate_group_votes) == {"PL": 1960000, "PT": 5040000}
