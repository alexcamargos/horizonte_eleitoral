"""Adaptadores de parsing que convertem JSONs externos do TSE em entidades canonicas."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime

from horizonte_eleitoral.domain.enums import GeographicScope
from horizonte_eleitoral.domain.errors import ValidationError
from horizonte_eleitoral.normalization.models import (
    NormalizedSectionState,
    NormalizedTotalization,
)

DEFAULT_CANDIDATE_TAXONOMY: dict[str, str] = {
    "13": "PT",
    "22": "PL",
}


def _safe_json_loads(body: bytes, source_name: str) -> dict[str, object]:
    """Decodifica com seguranca o JSON do corpo bruto ou lanca ValidationError para quarentena.

    Args:
        body: Bytes brutos da resposta oficial.
        source_name: Rotulo identificador do arquivo para mensagens de erro.

    Returns:
        Dicionario do JSON decodificado.

    Raises:
        ValidationError: Se o JSON for malformado ou nao for um objeto raiz.
    """
    try:
        data = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValidationError(f"Arquivo {source_name} possui codificacao JSON invalida.") from error
    if not isinstance(data, dict):
        raise ValidationError(f"Arquivo {source_name} deve conter um objeto JSON raiz.")
    return data


def _to_int(val: object, default: int = 0) -> int:
    """Converte um valor generico para inteiro de forma segura.

    Args:
        val: Valor a ser convertido.
        default: Valor padrao se a conversao falhar ou valor for None.

    Returns:
        Inteiro convertido ou default.

    Raises:
        None.
    """
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, (str, bytes)):
        try:
            return int(val)
        except ValueError:
            return default
    return default


def normalize_ea14(body: bytes) -> dict[str, str]:
    """Normaliza o resumo nacional de UFs alteradas (EA14).

    Args:
        body: Bytes do arquivo EA14.

    Returns:
        Mapeamento de sigla da UF para versao ou hash de atualizacao.

    Raises:
        ValidationError: Se o formato nao contiver a lista esperada de UFs.
    """
    data = _safe_json_loads(body, "EA14")
    ufs = data.get("ufs")
    if not isinstance(ufs, list):
        raise ValidationError("EA14 deve conter uma lista no campo 'ufs'.")

    result: dict[str, str] = {}
    for entry in ufs:
        if isinstance(entry, dict) and "uf" in entry:
            uf = str(entry["uf"]).upper()
            version = str(entry.get("ver", entry.get("dh", "")))
            result[uf] = version
    return result


def normalize_ea15(body: bytes) -> dict[str, str]:
    """Normaliza o resumo estadual de municipios alterados (EA15).

    Args:
        body: Bytes do arquivo EA15.

    Returns:
        Mapeamento de codigo do municipio para versao ou hash de atualizacao.

    Raises:
        ValidationError: Se o formato nao contiver a lista esperada de municipios.
    """
    data = _safe_json_loads(body, "EA15")
    munis = data.get("mun")
    if not isinstance(munis, list):
        raise ValidationError("EA15 deve conter uma lista no campo 'mun'.")

    result: dict[str, str] = {}
    for entry in munis:
        if isinstance(entry, dict) and "cd" in entry:
            code = str(entry["cd"])
            version = str(entry.get("ver", entry.get("dh", "")))
            result[code] = version
    return result


def normalize_ea16(
    body: bytes,
    state: str,
    municipality_code: str,
) -> list[NormalizedSectionState]:
    """Normaliza a lista de secoes e estados de urna de um municipio (EA16).

    Args:
        body: Bytes do arquivo EA16.
        state: UF do municipio.
        municipality_code: Codigo do municipio.

    Returns:
        Lista de NormalizedSectionState para cada secao encontrada.

    Raises:
        ValidationError: Se o arquivo nao contiver a estrutura correta de secoes.
    """
    data = _safe_json_loads(body, "EA16")
    sections_raw = data.get("sec")
    if not isinstance(sections_raw, list):
        raise ValidationError("EA16 deve conter uma lista no campo 'sec'.")

    sections: list[NormalizedSectionState] = []
    for item in sections_raw:
        if not isinstance(item, dict):
            continue
        zone = str(item.get("z", "")).zfill(4)
        sec = str(item.get("s", "")).zfill(4)
        gen_hash = str(item.get("ha", item.get("hash", "")))
        st_flag = str(item.get("st", "")).upper()
        is_totalized = st_flag in ("T", "TOTALIZADA", "1")

        dh_str = item.get("da") or item.get("dh")
        dh_parsed = None
        if isinstance(dh_str, str):
            try:
                dh_parsed = datetime.fromisoformat(dh_str)
            except ValueError:
                dh_parsed = None

        sections.append(
            NormalizedSectionState(
                state=state.upper(),
                municipality_code=municipality_code,
                zone=zone,
                section=sec,
                generation_timestamp=dh_parsed,
                generation_hash=gen_hash,
                is_totalized=is_totalized,
            )
        )
    return sections


def normalize_ea20(
    body: bytes,
    taxonomy: Mapping[str, str] | None = None,
    round_num: int = 1,
) -> NormalizedTotalization:
    """Normaliza o arquivo de totalizacao oficial de votos (EA20 ou JSON de divulgacao do TSE).

    Args:
        body: Bytes do arquivo EA20 ou u.json da CDN do TSE.
        taxonomy: Mapeamento de numero do candidato para grupo ('PT', 'PL', 'OUTROS').
        round_num: Turno da eleicao (1 ou 2). No 2º turno, grupos restringem-se aos finalistas.

    Returns:
        NormalizedTotalization com eleitorado e votos consolidados por grupo.

    Raises:
        ValidationError: Se os campos obrigatorios estiverem ausentes ou JSON invalido.
    """
    data = _safe_json_loads(body, "EA20")
    candidate_tax = dict(taxonomy or DEFAULT_CANDIDATE_TAXONOMY)

    scope_str = str(data.get("abrangencia", data.get("st", "BR"))).upper()
    try:
        scope = GeographicScope(scope_str)
    except ValueError:
        scope = GeographicScope.BRAZIL

    scope_code = str(data.get("cd", data.get("cdAbr", scope.value)))

    total_electorate = _to_int(data.get("e", data.get("eleitorado", 0)))
    totalized_electorate = _to_int(
        data.get("ea", data.get("e_tot", data.get("eleitorado_apurado", 0)))
    )
    pending_electorate = max(0, total_electorate - totalized_electorate)

    total_sections = _to_int(data.get("sec_tot", data.get("secoes_total", data.get("te", 0))))
    totalized_sections = _to_int(
        data.get("sec_apu", data.get("secoes_apuradas", data.get("ea_sec", 0)))
    )
    pending_sections = max(0, total_sections - totalized_sections)

    valid_votes = _to_int(data.get("vv", data.get("votos_validos", data.get("v", 0))))
    blank_votes = _to_int(data.get("vb", data.get("votos_brancos", 0)))
    null_votes = _to_int(data.get("vn", data.get("votos_nulos", 0)))

    # Agrupamento das candidaturas
    cand_votes_raw = data.get("cand", data.get("cands", []))
    if round_num == 2:
        group_votes_counter: dict[str, int] = {"PT": 0, "PL": 0}
    else:
        group_votes_counter = {"PT": 0, "PL": 0, "OUTROS": 0}

    if isinstance(cand_votes_raw, list):
        for cand in cand_votes_raw:
            if not isinstance(cand, dict):
                continue
            cand_num = str(cand.get("n", cand.get("numero", "")))
            v_cand = _to_int(cand.get("vap", cand.get("v", cand.get("votos", 0))))
            default_fallback = (
                "PL"
                if round_num == 2 and cand_num == "22"
                else ("PT" if round_num == 2 and cand_num == "13" else "OUTROS")
            )
            assigned_group = candidate_tax.get(cand_num, default_fallback)
            if assigned_group in group_votes_counter:
                group_votes_counter[assigned_group] += v_cand
            elif round_num == 1:
                group_votes_counter["OUTROS"] += v_cand

    # Garante que a soma bate com valid_votes se houve votos
    candidate_group_votes = tuple(
        sorted(((grp, votes) for grp, votes in group_votes_counter.items()), key=lambda x: x[0])
    )

    return NormalizedTotalization(
        scope=scope,
        scope_code=scope_code,
        total_electorate=total_electorate,
        totalized_electorate=totalized_electorate,
        pending_electorate=pending_electorate,
        total_sections=total_sections,
        totalized_sections=totalized_sections,
        pending_sections=pending_sections,
        valid_votes=valid_votes,
        blank_votes=blank_votes,
        null_votes=null_votes,
        candidate_group_votes=candidate_group_votes,
    )
