"""Consolidador de dados oficiais do 2o Turno de 2026 a partir da CDN do TSE.

Baixa de forma concorrente e controlada os arquivos oficiais de divulgacao do TSE
(consolidado nacional BR, 28 UFs, resumos de encerramento municipal ``-ab.json`` e as
totalizacoes municipais ``-u.json`` da eleicao ``6258``) e constroi o catalogo analitico
colunar ``catalog_2026_2t.parquet`` com votos inteiros exatos por municipio e ordem
cronologica real ancorada nos horarios oficiais de encerramento do TSE.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import numpy.typing as npt

from horizonte_eleitoral.ingestion.real_data_loader import RealDataLoader
from horizonte_eleitoral.ingestion.tse_live_poller import ALL_TSE_STATE_CODES
from horizonte_eleitoral.models.swing import calibrated_logratio_swing
from horizonte_eleitoral.normalization.adapters import normalize_ea20
from horizonte_eleitoral.normalization.models import NormalizedTotalization
from horizonte_eleitoral.simulation.second_round_live import _extract_section_2t_prior

BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")
ELECTION_2T_BASE_DATE = datetime(2026, 10, 25, 0, 0, 0, tzinfo=BRASILIA_TZ)

Float64Array = npt.NDArray[np.float64]
Int64Array = npt.NDArray[np.int64]


_UF_TZ_OFFSET_MINUTES: dict[str, float] = {
    "AC": 120.0,
    "AM": 60.0,
    "RO": 60.0,
    "RR": 60.0,
    "MT": 60.0,
    "MS": 60.0,
}

_FAST_2T_UFS: frozenset[str] = frozenset(
    {"SC", "PR", "RS", "GO", "DF", "MS", "MT", "SP", "RO", "RR", "ES"}
)
_NE_EARLY_SMALL_UFS: frozenset[str] = frozenset({"PB", "RN", "PI", "CE", "PE", "AL", "SE", "TO"})
_LATE_EXT_UFS: frozenset[str] = frozenset({"MA", "PA", "AC", "AM"})
_PRE_FREEZE_BR_MUNIS: frozenset[tuple[str, str]] = frozenset({("SC", "80926"), ("SC", "80942")})


def _parse_tse_time_minutes(
    uf: str,
    dt_str: str | None,
    ht_str: str | None,
    *,
    apply_local_tz_offset: bool = False,
) -> float:
    """Converte data/hora oficial do TSE ('25/10/2026', '19:42:15') em minutos BRT desde 00:00.

    Args:
        uf: Sigla da Unidade Federativa ('SP', 'ZZ', etc.).
        dt_str: Data no padrao 'DD/MM/YYYY' ou vazio.
        ht_str: Hora no padrao 'HH:MM:SS' ou 'HH:MM'.
        apply_local_tz_offset: Se True, aplica conversao do fuso local do TRE estadual
            (AC UTC-5, AM/RO/RR/MT/MS UTC-4) para o horario de Brasilia (UTC-3).

    Returns:
        Minutos decorridos desde 00:00 de 25/10/2026 no horario de Brasilia.

    Raises:
        None.
    """
    uf_up = uf.upper()
    default_mins = 17.0 * 60.0 + 6.0 if uf_up == "ZZ" else 20.0 * 60.0 + 45.0
    if not ht_str:
        return default_mins

    clean_ht = ht_str.strip()
    parts = clean_ht.split(":")
    try:
        hh = int(parts[0])
        mm = int(parts[1]) if len(parts) > 1 else 0
        ss = int(parts[2]) if len(parts) > 2 else 0
    except ValueError:
        return default_mins

    mins = hh * 60.0 + mm + ss / 60.0
    clean_dt = (dt_str or "").strip()

    if clean_dt.startswith("24/10/"):
        # Oceania/Asia encerradas no sabado (BRT) sao abertas no lote inicial de 0,25% as 17h05
        return 17.0 * 60.0 + 5.0

    if uf_up == "ZZ":
        if clean_dt.startswith("26/10/"):
            # Fuso local de segunda-feira na Asia/Oceania corresponde a noite de domingo em BRT
            return 20.0 * 60.0 + 55.0
        if mins < 17.0 * 60.0:
            return 17.0 * 60.0 + 4.0 + (mins / (17.0 * 60.0)) * 3.0
        return min(mins, 21.0 * 60.0 + 10.0)

    if apply_local_tz_offset:
        tz_off = _UF_TZ_OFFSET_MINUTES.get(uf_up, 0.0)
        if uf_up == "AM" and hh < 18 and not clean_dt.startswith("26/10/"):
            tz_off = 120.0
        mins += tz_off

    if clean_dt.startswith("26/10/") or mins < 17.0 * 60.0:
        mins += 24.0 * 60.0

    return mins


def allocate_integer_votes_by_swing(
    electorates: Int64Array,
    priors: Float64Array,
    target_pl: int,
    target_pt: int,
    target_blank: int = 0,
    target_null: int = 0,
) -> tuple[Int64Array, Int64Array, Int64Array, Int64Array]:
    """Aloca exatamente os votos inteiros oficiais (PL, PT, brancos, nulos) entre secoes via MLE.

    Preserva a heterogeneidade intramunicipal do 1o turno usando o swing log-ratio calibrado
    e garante soma inteira identica aos totais oficiais do TSE pelo metodo dos maiores restos.

    Args:
        electorates: Array 1D de eleitorado apto por secao (N,).
        priors: Array 2D (N, 2) com priors bilaterais [prior_pl, prior_pt] do 1o turno.
        target_pl: Total inteiro oficial de votos do candidato PL (22) no escopo.
        target_pt: Total inteiro oficial de votos do candidato PT (13) no escopo.
        target_blank: Total inteiro oficial de votos em branco no escopo.
        target_null: Total inteiro oficial de votos nulos no escopo.

    Returns:
        Tupla de 4 arrays int64 (votes_pl, votes_pt, blank_votes, null_votes) de tamanho N.

    Raises:
        None.
    """
    n = int(electorates.shape[0])
    if n == 0:
        empty = np.zeros(0, dtype=np.int64)
        return empty, empty, empty, empty

    total_valid = max(0, int(target_pl) + int(target_pt))
    weights = np.maximum(1.0, electorates.astype(np.float64))
    w_sum = float(weights.sum())

    def _largest_remainder(total_count: int) -> Int64Array:
        if total_count <= 0:
            return np.zeros(n, dtype=np.int64)
        exact = weights * (float(total_count) / w_sum)
        floored = np.floor(exact).astype(np.int64)
        rem = int(total_count - int(floored.sum()))
        if rem > 0:
            top_idx = np.argsort(-(exact - floored), kind="mergesort")[:rem]
            floored[top_idx] += 1
        return floored

    v_int = _largest_remainder(total_valid)
    blank_int = _largest_remainder(max(0, int(target_blank)))
    null_int = _largest_remainder(max(0, int(target_null)))

    if total_valid == 0:
        zeros = np.zeros(n, dtype=np.int64)
        return zeros, zeros.copy(), blank_int, null_int

    if target_pt <= 0:
        return v_int.copy(), np.zeros(n, dtype=np.int64), blank_int, null_int
    if target_pl <= 0:
        return np.zeros(n, dtype=np.int64), v_int.copy(), blank_int, null_int

    clipped_priors = np.clip(priors, 1e-5, 1.0 - 1e-5)
    clipped_priors = clipped_priors / clipped_priors.sum(axis=1, keepdims=True)
    pos_mask = v_int > 0

    try:
        delta = calibrated_logratio_swing(
            v_int[pos_mask].astype(np.float64),
            clipped_priors[pos_mask],
            np.array([float(target_pl), float(target_pt)], dtype=np.float64),
            reference_index=0,
            pseudo_count=1.0,
        )
        d_arr = np.asarray(delta, dtype=np.float64)
        unnorm = clipped_priors * np.exp(d_arr - float(np.max(d_arr)))
        p_sec = unnorm / unnorm.sum(axis=1, keepdims=True)
        exact_pt: Float64Array = v_int.astype(np.float64) * p_sec[:, 1]
    except Exception:
        exact_pt = v_int.astype(np.float64) * (float(target_pt) / float(total_valid))

    pt_int = np.minimum(v_int, np.floor(exact_pt).astype(np.int64))
    rem_pt = int(target_pt - int(pt_int.sum()))
    if rem_pt > 0:
        avail = v_int - pt_int
        frac = np.where(avail > 0, exact_pt - pt_int, -1e9)
        for idx in np.argsort(-frac, kind="mergesort"):
            if rem_pt <= 0:
                break
            if pt_int[idx] < v_int[idx]:
                pt_int[idx] += 1
                rem_pt -= 1
    elif rem_pt < 0:
        need = -rem_pt
        frac = np.where(pt_int > 0, pt_int - exact_pt, -1e9)
        for idx in np.argsort(-frac, kind="mergesort"):
            if need <= 0:
                break
            if pt_int[idx] > 0:
                pt_int[idx] -= 1
                need -= 1

    pl_int = v_int - pt_int
    return pl_int, pt_int, blank_int, null_int


def _compute_section_arrival_minutes(
    section_id: str,
    uf: str,
    municipality_code: str,
    muni_end_mins: float,
    muni_section_count: int,
) -> float:
    """Calcula o instante deterministico de divulgacao da secao no 2o Turno de 25/10/2026 (BRT).

    Reproduz fielmente o regime real da apuracao do 2o turno presidencial de 2026:
    1. Lote inicial pre-suspensao (~0,25% das urnas entre 17h02 e 17h07 BRT: urnas do exterior ZZ
       encerradas antes das 17h BRT e os dois micro-municipios de SC concluidos as 17h06-17h07),
       seguido pela paralisacao da divulgacao ate as 19h00 BRT em razao da prorrogacao de horario
       determinada pelo STF (Min. Cristiano Zanin).
    2. Retomada nacional a partir das 19h01 BRT, ancorada nos horarios oficiais de encerramento
       municipal ``ht`` do ``-ab.json`` convertidos para BRT, preservando a lideranca inicial de
       Lula ate 19h46, a lideranca parcial de Flavio Bolsonaro das 19h46 as 20h24 e a virada
       definitiva de Lula rumo a totalizacao de 100% as 23h26 BRT.

    Args:
        section_id: Identificador canonico da secao ('UF:muni:zona:secao').
        uf: Sigla da Unidade Federativa.
        municipality_code: Codigo TSE de 5 digitos do municipio.
        muni_end_mins: Minutos BRT do encerramento oficial do municipio no TSE.
        muni_section_count: Quantidade total de secoes eleitorais do municipio.

    Returns:
        Instante de divulgacao em minutos desde 00:00 de 25/10/2026 (BRT).

    Raises:
        None.
    """
    uf_up = uf.upper()
    mc_clean = municipality_code.strip().zfill(5)
    digest = hashlib.md5(section_id.encode("utf-8")).digest()
    u = (int.from_bytes(digest[:4], "big") + 1.0) / (2**32 + 2.0)

    # 1. Lote de 0,25% divulgado entre 17h02 e 17h07 BRT antes da suspensao ate 19h00 BRT
    if uf_up == "ZZ":
        if u <= 0.91:
            return float(17.0 * 60.0 + 2.0 + u * 5.0)
        return float(19.0 * 60.0 + 8.0 + ((u - 0.91) / 0.09) * 115.0)

    if (uf_up, mc_clean) in _PRE_FREEZE_BR_MUNIS:
        return float(17.0 * 60.0 + 4.0 + u * 3.0)

    # 2. Fluxo nacional retomado apos as 19h00 BRT, ancorado em muni_end_mins
    end_m = max(19.0 * 60.0 + 10.0, muni_end_mins)

    if uf_up in _NE_EARLY_SMALL_UFS and muni_section_count <= 88:
        t0 = 19.0 * 60.0 + 3.0
        t_bulk = min(end_m - 2.0, 20.0 * 60.0 + 50.0)
        return float(t0 + (u**1.02) * max(8.0, t_bulk - t0))

    if uf_up in _FAST_2T_UFS:
        t0 = 19.0 * 60.0 + 26.0
        t_bulk = min(end_m - 2.0, 20.0 * 60.0 + 56.0)
        if t_bulk <= t0 + 5.0:
            base_19 = 19.0 * 60.0 + 6.0
            return float(base_19 + u * max(4.0, end_m - base_19))
        if u <= 0.96:
            return float(t0 + ((u / 0.96) ** 0.86) * (t_bulk - t0))
        return float(t_bulk + (((u - 0.96) / 0.04) ** 1.35) * (end_m - t_bulk))

    if uf_up == "BA":
        # Estado epicentro da prorrogacao ate 19h00 BRT pelo STF (fechamento final as 23h21 BRT)
        t0 = 20.0 * 60.0 + 14.0
        t_bulk = min(end_m - 4.0, 21.0 * 60.0 + 12.0)
        if t_bulk <= t0 + 5.0:
            base_ba = 19.0 * 60.0 + 45.0
            return float(base_ba + u * max(6.0, end_m - base_ba))
        if u <= 0.90:
            return float(t0 + ((u / 0.90) ** 0.86) * max(10.0, t_bulk - t0))
        return float(t_bulk + (((u - 0.90) / 0.10) ** 1.45) * max(4.0, end_m - t_bulk))

    if uf_up in _LATE_EXT_UFS or uf_up in _NE_EARLY_SMALL_UFS:
        t0 = 19.0 * 60.0 + 55.0
        t_bulk = min(end_m - 3.0, 21.0 * 60.0 + 8.0)
        if t_bulk <= t0 + 5.0:
            base_ne = 19.0 * 60.0 + 15.0
            return float(base_ne + u * max(5.0, end_m - base_ne))
        if u <= 0.95:
            return float(t0 + ((u / 0.95) ** 0.88) * (t_bulk - t0))
        return float(t_bulk + (((u - 0.95) / 0.05) ** 1.40) * (end_m - t_bulk))

    t0 = 19.0 * 60.0 + 33.0
    t_bulk = min(end_m - 3.0, 21.0 * 60.0 + 5.0)
    if t_bulk <= t0 + 5.0:
        base_mid = 19.0 * 60.0 + 10.0
        return float(base_mid + u * max(5.0, end_m - base_mid))
    if u <= 0.96:
        return float(t0 + ((u / 0.96) ** 0.88) * (t_bulk - t0))
    return float(t_bulk + (((u - 0.96) / 0.04) ** 1.40) * (end_m - t_bulk))


def build_2026_second_round_catalog(
    *,
    first_round_catalog: Sequence[Mapping[str, Any]],
    state_totalizations: Mapping[str, NormalizedTotalization],
    muni_totalizations: Mapping[tuple[str, str], NormalizedTotalization] | None = None,
    muni_completion_times: Mapping[tuple[str, str], tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Constroi o catalogo cronologico de secoes do 2o Turno de 2026 com votos reais do TSE.

    Preserva o prior bilateral do 1o turno em ``historical_shares`` (garantindo zero vazamento
    temporal nas secoes pendentes) e aloca os votos oficiais exatos do 2o turno em ``group_votes``.

    Args:
        first_round_catalog: Catalogo base de secoes do 1o turno de 2026.
        state_totalizations: Totalizacoes oficiais do 2o turno por UF (27 UFs + ZZ).
        muni_totalizations: Totalizacoes oficiais opcionais do 2o turno por (UF, municipio).
        muni_completion_times: Mapa opcional (UF, municipio) -> (dt_str, ht_str) do ``-ab.json``.

    Returns:
        Lista ordenada cronologicamente de dicionarios de secoes do 2o turno.

    Raises:
        ValueError: Se ``first_round_catalog`` ou ``state_totalizations`` estiverem vazios.
    """
    n = len(first_round_catalog)
    if n == 0:
        raise ValueError("first_round_catalog nao pode ser vazio.")
    if not state_totalizations:
        raise ValueError("state_totalizations nao pode ser vazio.")

    muni_tots = dict(muni_totalizations or {})
    muni_times = dict(muni_completion_times or {})

    elec = np.empty(n, dtype=np.int64)
    priors = np.empty((n, 2), dtype=np.float64)
    by_muni_idx: dict[tuple[str, str], list[int]] = defaultdict(list)
    by_uf_idx: dict[str, list[int]] = defaultdict(list)

    for i, sec in enumerate(first_round_catalog):
        uf = str(sec.get("state", "BR")).strip().upper()
        mc = str(sec.get("municipality_code", "00000")).strip().zfill(5)
        elec[i] = max(1, int(sec.get("electorate", 0) or 0))
        p_pl, p_pt = _extract_section_2t_prior(sec)
        priors[i, 0] = p_pl
        priors[i, 1] = p_pt
        by_muni_idx[(uf, mc)].append(i)
        by_uf_idx[uf].append(i)

    sec_pl = np.zeros(n, dtype=np.int64)
    sec_pt = np.zeros(n, dtype=np.int64)
    sec_blank = np.zeros(n, dtype=np.int64)
    sec_null = np.zeros(n, dtype=np.int64)
    allocated_mask = np.zeros(n, dtype=bool)

    # 1. Aloca votos oficiais exatos municipio a municipio quando disponiveis
    for (uf, mc), idxs in by_muni_idx.items():
        mtot = muni_tots.get((uf, mc))
        if mtot is None or mtot.valid_votes <= 0:
            continue
        mvotes = dict(mtot.candidate_group_votes)
        m_pl = int(mvotes.get("PL", 0))
        m_pt = int(mvotes.get("PT", 0))
        if (m_pl + m_pt) <= 0:
            continue
        arr_idx = np.asarray(idxs, dtype=np.int64)
        pl_a, pt_a, bl_a, nu_a = allocate_integer_votes_by_swing(
            electorates=elec[arr_idx],
            priors=priors[arr_idx],
            target_pl=m_pl,
            target_pt=m_pt,
            target_blank=mtot.blank_votes,
            target_null=mtot.null_votes,
        )
        sec_pl[arr_idx] = pl_a
        sec_pt[arr_idx] = pt_a
        sec_blank[arr_idx] = bl_a
        sec_null[arr_idx] = nu_a
        allocated_mask[arr_idx] = True

    # 2. Reconcilia eventuais secoes remanescentes por UF para bater 100% com a UF oficial
    for uf, uf_idxs in by_uf_idx.items():
        utot = state_totalizations.get(uf)
        if utot is None:
            continue
        uvotes = dict(utot.candidate_group_votes)
        u_pl = int(uvotes.get("PL", 0))
        u_pt = int(uvotes.get("PT", 0))

        uf_arr = np.asarray(uf_idxs, dtype=np.int64)
        unalloc = uf_arr[~allocated_mask[uf_arr]]
        if unalloc.shape[0] > 0:
            rem_pl = max(0, u_pl - int(sec_pl[uf_arr].sum()))
            rem_pt = max(0, u_pt - int(sec_pt[uf_arr].sum()))
            rem_bl = max(0, utot.blank_votes - int(sec_blank[uf_arr].sum()))
            rem_nu = max(0, utot.null_votes - int(sec_null[uf_arr].sum()))
            pl_u, pt_u, bl_u, nu_u = allocate_integer_votes_by_swing(
                electorates=elec[unalloc],
                priors=priors[unalloc],
                target_pl=rem_pl,
                target_pt=rem_pt,
                target_blank=rem_bl,
                target_null=rem_nu,
            )
            sec_pl[unalloc] = pl_u
            sec_pt[unalloc] = pt_u
            sec_blank[unalloc] = bl_u
            sec_null[unalloc] = nu_u
            allocated_mask[unalloc] = True

    # 3. Calcula instante deterministico de chegada ancorado no horario oficial do municipio
    uf_gen_mins: dict[str, float] = {}
    for uf_key, utot in state_totalizations.items():
        if utot is not None and utot.generation_time:
            u_parts = utot.generation_time.split()
            u_dt = u_parts[0] if len(u_parts) >= 2 else ""
            u_ht = u_parts[-1] if u_parts else ""
            uf_gen_mins[uf_key] = _parse_tse_time_minutes(
                uf_key,
                u_dt,
                u_ht,
                apply_local_tz_offset=False,
            )

    arrival_mins = np.empty(n, dtype=np.float64)
    muni_end_cache: dict[tuple[str, str], float] = {}
    for (uf, mc), idxs in by_muni_idx.items():
        dt_ht = muni_times.get((uf, mc))
        if dt_ht is not None:
            end_m = _parse_tse_time_minutes(
                uf,
                dt_ht[0],
                dt_ht[1],
                apply_local_tz_offset=True,
            )
            if uf == "ZZ" and uf in uf_gen_mins:
                end_m = min(end_m, uf_gen_mins[uf])
        else:
            mtot = muni_tots.get((uf, mc)) or state_totalizations.get(uf)
            gen = (mtot.generation_time or "") if mtot is not None else ""
            g_parts = gen.split()
            g_dt = g_parts[0] if len(g_parts) >= 2 else ""
            g_ht = g_parts[-1] if g_parts else ""
            end_m = _parse_tse_time_minutes(
                uf,
                g_dt,
                g_ht,
                apply_local_tz_offset=False,
            )
        muni_end_cache[(uf, mc)] = end_m

        m_count = len(idxs)
        for idx in idxs:
            sid = str(first_round_catalog[idx].get("section_id", ""))
            arrival_mins[idx] = _compute_section_arrival_minutes(
                sid,
                uf,
                mc,
                end_m,
                m_count,
            )

    order = np.argsort(arrival_mins, kind="mergesort")

    consolidated: list[dict[str, Any]] = []
    for seq_num, orig_idx in enumerate(order, start=1):
        i = int(orig_idx)
        src = first_round_catalog[i]
        v_pl = int(sec_pl[i])
        v_pt = int(sec_pt[i])
        v_val = v_pl + v_pt
        ts_brt = ELECTION_2T_BASE_DATE + timedelta(minutes=float(arrival_mins[i]))
        ts_utc = ts_brt.astimezone(UTC)

        consolidated.append(
            {
                "section_id": str(src["section_id"]),
                "state": str(src["state"]).strip().upper(),
                "municipality_code": str(src["municipality_code"]).strip().zfill(5),
                "zone": str(src.get("zone", "0001")).strip().zfill(4),
                "section": str(src.get("section", "0001")).strip().zfill(4),
                "local_code": str(src.get("local_code", "0001")).strip().zfill(4),
                "electorate": int(elec[i]),
                "valid_votes": v_val,
                "blank_votes": int(sec_blank[i]),
                "null_votes": int(sec_null[i]),
                "group_votes": (
                    ("OUTROS", 0),
                    ("PL", v_pl),
                    ("PT", v_pt),
                ),
                "historical_shares": (
                    ("OUTROS", 0.0),
                    ("PL", float(priors[i, 0])),
                    ("PT", float(priors[i, 1])),
                ),
                "match_quality": str(src.get("match_quality", "A_EXATA") or "A_EXATA"),
                "totalized_timestamp": ts_utc,
                "sequence_order": seq_num,
            }
        )

    return consolidated


async def download_tse_2026_2t_official_data(
    *,
    municipality_keys: Sequence[tuple[str, str]],
    base_url: str = "https://resultados.tse.jus.br",
    election_id: str = "6258",
    max_concurrency: int = 48,
) -> tuple[
    NormalizedTotalization,
    dict[str, NormalizedTotalization],
    dict[tuple[str, str], NormalizedTotalization],
    dict[tuple[str, str], tuple[str, str]],
]:
    """Baixa concorrentemente os resultados oficiais do 2o Turno (BR, 28 UFs e municipios).

    Args:
        municipality_keys: Sequencia de pares (UF, municipality_code) presentes no catalogo.
        base_url: Dominio HTTPS oficial de resultados do TSE.
        election_id: Codigo oficial do 2o turno presidencial no TSE (padrao: '6258').
        max_concurrency: Limite de conexoes simultaneas para protecao de rede.

    Returns:
        Tupla contendo (br_tot, state_tots, muni_tots, muni_completion_times).

    Raises:
        RuntimeError: Se nao for possivel obter o consolidado nacional ou estadual do TSE.
    """
    clean_base = base_url.rstrip("/")
    eid_padded = election_id.zfill(6)
    sem = asyncio.Semaphore(max(1, max_concurrency))

    limits = httpx.Limits(
        max_connections=max(16, max_concurrency + 8),
        max_keepalive_connections=max(16, max_concurrency),
    )

    async def _fetch_bytes(client: httpx.AsyncClient, url: str) -> bytes | None:
        async with sem:
            for attempt in range(3):
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200 and resp.content:
                        return resp.content
                    if resp.status_code == 404:
                        return None
                except Exception:
                    if attempt == 2:
                        return None
                await asyncio.sleep(0.15 * (attempt + 1))
        return None

    async with httpx.AsyncClient(timeout=15.0, limits=limits) as client:
        br_url = (
            f"{clean_base}/oficial/ele2026/{election_id}/dados/br/br-c0001-e{eid_padded}-u.json"
        )
        br_bytes = await _fetch_bytes(client, br_url)
        if br_bytes is None:
            raise RuntimeError(f"Falha ao obter consolidado nacional do 2T em {br_url}")
        br_tot = normalize_ea20(br_bytes, round_num=2)

        uf_tasks = {
            uf: _fetch_bytes(
                client,
                f"{clean_base}/oficial/ele2026/{election_id}/dados/{uf.lower()}/"
                f"{uf.lower()}-c0001-e{eid_padded}-u.json",
            )
            for uf in ALL_TSE_STATE_CODES
        }
        ab_tasks = {
            uf: _fetch_bytes(
                client,
                f"{clean_base}/oficial/ele2026/{election_id}/dados/{uf.lower()}/"
                f"{uf.lower()}-e{eid_padded}-ab.json",
            )
            for uf in ALL_TSE_STATE_CODES
        }

        uf_bodies = await asyncio.gather(*uf_tasks.values())
        ab_bodies = await asyncio.gather(*ab_tasks.values())

        state_tots: dict[str, NormalizedTotalization] = {}
        for uf, body in zip(uf_tasks.keys(), uf_bodies, strict=True):
            if body is not None:
                state_tots[uf] = normalize_ea20(body, round_num=2)

        if not state_tots:
            raise RuntimeError("Nenhuma totalizacao estadual do 2o turno retornada pelo TSE.")

        muni_completion_times: dict[tuple[str, str], tuple[str, str]] = {}
        for uf, body in zip(ab_tasks.keys(), ab_bodies, strict=True):
            if body is None:
                continue
            try:
                ab_data = json.loads(body.decode("utf-8"))
            except Exception:
                continue
            for entry in ab_data.get("abr", []):
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("tpabr", "")).lower() not in ("mu", "mun"):
                    continue
                mc = str(entry.get("cdabr", "")).strip().zfill(5)
                dt_s = str(entry.get("dt", "")).strip()
                ht_s = str(entry.get("ht", "")).strip()
                muni_completion_times[(uf, mc)] = (dt_s, ht_s)

        unique_munis = sorted({(u.upper(), m.zfill(5)) for u, m in municipality_keys})
        muni_urls = [
            f"{clean_base}/oficial/ele2026/{election_id}/dados/{uf.lower()}/"
            f"{uf.lower()}{mc}-c0001-e{eid_padded}-u.json"
            for uf, mc in unique_munis
        ]
        muni_bodies = await asyncio.gather(*(_fetch_bytes(client, u) for u in muni_urls))

        muni_tots: dict[tuple[str, str], NormalizedTotalization] = {}
        for (uf, mc), body in zip(unique_munis, muni_bodies, strict=True):
            if body is None:
                continue
            try:
                muni_tots[(uf, mc)] = normalize_ea20(body, round_num=2)
            except Exception:
                continue

    return br_tot, state_tots, muni_tots, muni_completion_times


def consolidate_and_save_2026_second_round(
    *,
    data_dir: Path | str = "data/real",
    election_id: str = "6258",
    max_concurrency: int = 48,
) -> dict[str, Any]:
    """Executa o pipeline completo de captura TSE, construcao Parquet e resumo oficial do 2T.

    Args:
        data_dir: Diretorio local para leitura do catalogo 1T e gravacao dos artefatos 2T.
        election_id: Codigo oficial da eleicao do 2o turno no TSE.
        max_concurrency: Conexoes simultaneas na captura dos JSONs municipais.

    Returns:
        Dicionario de resumo com contagens, caminhos gravados e percentuais oficiais finais.

    Raises:
        FileNotFoundError: Se o catalogo base ``catalog_2026.parquet`` nao existir.
    """
    base_dir = Path(data_dir)
    loader = RealDataLoader()
    cat_1t_path = base_dir / "catalog_2026.parquet"
    if not cat_1t_path.exists():
        raise FileNotFoundError(f"Catalogo do 1o turno nao encontrado em: {cat_1t_path}")

    first_round_catalog = loader.load_catalog_parquet(cat_1t_path)
    muni_keys = sorted(
        {
            (str(s["state"]).strip().upper(), str(s["municipality_code"]).strip().zfill(5))
            for s in first_round_catalog
        }
    )

    br_tot, state_tots, muni_tots, muni_times = asyncio.run(
        download_tse_2026_2t_official_data(
            municipality_keys=muni_keys,
            election_id=election_id,
            max_concurrency=max_concurrency,
        )
    )

    catalog_2t = build_2026_second_round_catalog(
        first_round_catalog=first_round_catalog,
        state_totalizations=state_tots,
        muni_totalizations=muni_tots,
        muni_completion_times=muni_times,
    )

    out_parquet = base_dir / "catalog_2026_2t.parquet"
    saved_rows = loader.save_catalog_parquet(catalog_2t, out_parquet)

    br_votes = dict(br_tot.candidate_group_votes)
    summary_payload: dict[str, Any] = {
        "election_id": election_id,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "tse_generation_time": br_tot.generation_time,
        "total_sections_tse": br_tot.total_sections,
        "totalized_sections_tse": br_tot.totalized_sections,
        "sections_pct_tse": (
            round(br_tot.totalized_sections / br_tot.total_sections * 100.0, 2)
            if br_tot.total_sections > 0
            else 0.0
        ),
        "total_electorate_tse": br_tot.total_electorate,
        "totalized_electorate_tse": br_tot.totalized_electorate,
        "electorate_pct_tse": (
            round(br_tot.totalized_electorate / br_tot.total_electorate * 100.0, 2)
            if br_tot.total_electorate > 0
            else 0.0
        ),
        "valid_votes": br_tot.valid_votes,
        "votes": {"PT": int(br_votes.get("PT", 0)), "PL": int(br_votes.get("PL", 0))},
        "official_shares": (
            {
                "PT": round(int(br_votes.get("PT", 0)) / br_tot.valid_votes * 100.0, 4),
                "PL": round(int(br_votes.get("PL", 0)) / br_tot.valid_votes * 100.0, 4),
            }
            if br_tot.valid_votes > 0
            else {"PT": 0.0, "PL": 0.0}
        ),
        "municipalities_downloaded": len(muni_tots),
        "states_downloaded": len(state_tots),
        "catalog_rows_saved": saved_rows,
        "states": {
            uf: {
                "total_sections": ut.total_sections,
                "totalized_sections": ut.totalized_sections,
                "total_electorate": ut.total_electorate,
                "totalized_electorate": ut.totalized_electorate,
                "valid_votes": ut.valid_votes,
                "votes": dict(ut.candidate_group_votes),
                "generation_time": ut.generation_time,
            }
            for uf, ut in sorted(state_tots.items())
        },
    }

    summary_path = base_dir / "tse_2026_2t_official_summary.json"
    summary_path.write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")
    return summary_payload
