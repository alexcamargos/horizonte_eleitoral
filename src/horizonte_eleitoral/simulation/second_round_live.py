"""Motor puro de projecao em tempo real para o 2o Turno condicionado aos votos oficiais do TSE.

Integra os totais oficiais apurados em tempo real (consolidado nacional BR e, quando disponiveis,
as totalizacoes oficiais por Unidade Federativa) ao catalogo analitico pareado de secoes,
estimando os deslocamentos (swings) composicionais em log-ratio do 2o turno via
``HierarchicalBayesianModelV2`` e propagando incertezas via ``MonteCarloSimulator``.

Modulo puro: zero operacoes de I/O de rede, disco ou leitura de variaveis de ambiente.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import numpy.typing as npt

from horizonte_eleitoral.domain.enums import GeographicScope, MatchQuality
from horizonte_eleitoral.models.base import PendingSection, SectionObservation
from horizonte_eleitoral.models.hierarchical_v2 import HierarchicalBayesianModelV2
from horizonte_eleitoral.models.swing import calibrated_logratio_swing
from horizonte_eleitoral.normalization.models import NormalizedTotalization
from horizonte_eleitoral.publishing.models import PublishedProjectionPayload
from horizonte_eleitoral.publishing.publisher import AtomicPublisher
from horizonte_eleitoral.reconciliation.reconciler import ReconciliationEngine
from horizonte_eleitoral.simulation.monte_carlo import MonteCarloSimulator

Int64Array = npt.NDArray[np.int64]
Int32Array = npt.NDArray[np.int32]
Float64Array = npt.NDArray[np.float64]

PRIOR_TURNOUT_RATE: float = 0.80
PRIOR_VALID_RATE: float = 0.96
PRIOR_EFFECTIVE_VALID_RATE: float = PRIOR_TURNOUT_RATE * PRIOR_VALID_RATE


@dataclass(frozen=True, slots=True)
class UFColumnarSlice:
    """Indice colunar vetorizado das secoes de uma Unidade Federativa na ordem de chegada.

    Attributes:
        state: Sigla da UF com 2 letras maiusculas.
        electorates: Eleitorado apto por secao na ordem cronologica de chegada.
        cum_electorates: Soma acumulada do eleitorado para busca binaria instantanea de corte.
        mz_codes: Codigo inteiro [0, num_clusters) da Zona Eleitoral (municipio + zona) da secao.
        mz_meta: Metadados imutaveis (cluster_id_str, municipality_code, match_quality) por cluster.
        elec_prior_pl: Produto electorate * prior_pl de cada secao para agregacao via bincount.
        elec_prior_pt: Produto electorate * prior_pt de cada secao para agregacao via bincount.
    """

    state: str
    electorates: Int64Array
    cum_electorates: Int64Array
    mz_codes: Int32Array
    mz_meta: tuple[tuple[str, str, MatchQuality], ...]
    elec_prior_pl: Float64Array
    elec_prior_pt: Float64Array


@dataclass(frozen=True, slots=True)
class SecondRoundCatalogIndex:
    """Indice colunar global e por UF para agregacao instantanea por Zona Eleitoral (Muni-Zona).

    Attributes:
        num_sections: Quantidade total de secoes indexadas no catalogo.
        global_electorates: Eleitorado por secao na ordem global do catalogo.
        global_cum_electorates: Eleitorado acumulado global para corte nacional rapido.
        global_mz_codes: Codigo inteiro [0, num_global_clusters) da Muni-Zona de cada secao.
        global_mz_meta: Metadados (cluster_id_str, state, municipality_code, match_quality).
        global_elec_prior_pl: Produto electorate * prior_pl na ordem global.
        global_elec_prior_pt: Produto electorate * prior_pt na ordem global.
        by_uf: Mapeamento de sigla da UF para sua fatia colunar UFColumnarSlice.
    """

    num_sections: int
    global_electorates: Int64Array
    global_cum_electorates: Int64Array
    global_mz_codes: Int32Array
    global_mz_meta: tuple[tuple[str, str, str, MatchQuality], ...]
    global_elec_prior_pl: Float64Array
    global_elec_prior_pt: Float64Array
    by_uf: Mapping[str, UFColumnarSlice]


@dataclass(frozen=True, slots=True)
class AggregatedStratum:
    """Estrato territorial homogeneo (Muni-Zona) agregado de secoes observadas ou pendentes.

    Attributes:
        stratum_id: Identificador deterministico do estrato ('UF:municipio:zona').
        state: Sigla da Unidade Federativa.
        municipality_code: Codigo TSE do municipio preservando zeros a esquerda.
        electorate: Soma do eleitorado das secoes contidas no estrato.
        prior_pl: Proporcao base (prior) do grupo PL no estrato em (0, 1).
        prior_pt: Proporcao base (prior) do grupo PT no estrato em (0, 1).
        match_quality: Qualidade de pareamento representativa do estrato.
    """

    stratum_id: str
    state: str
    municipality_code: str
    electorate: int
    prior_pl: float
    prior_pt: float
    match_quality: MatchQuality


_INDEX_CACHE: dict[tuple[int, int, str], SecondRoundCatalogIndex] = {}


def _parse_match_quality(raw_mq: Any) -> MatchQuality:
    """Converte representacao bruta de qualidade de pareamento em enum MatchQuality seguro.

    Args:
        raw_mq: Valor bruto oriundo do dicionario do catalogo.

    Returns:
        Instancia valida de MatchQuality (fallback para MatchQuality.EXACT).

    Raises:
        None.
    """
    if isinstance(raw_mq, MatchQuality):
        return raw_mq
    if raw_mq:
        raw_str = str(raw_mq)
        try:
            return MatchQuality(raw_str)
        except ValueError:
            if raw_str in MatchQuality.__members__:
                return MatchQuality[raw_str]
    return MatchQuality.EXACT


def _extract_section_2t_prior(sec: Mapping[str, Any]) -> tuple[float, float]:
    """Extrai o prior bilateral (PL, PT) de uma secao usando o 1o Turno de 2026 com fallback 2022.

    No 2o turno presidencial, a votacao homologada da propria secao no 1o turno (realizado tres
    semanas antes com os mesmos finalistas) constitui a covariavel territorial de maxima resolucao,
    recorrendo automaticamente ao perfil historico de 2022 caso a secao nao possua votos no 1T.

    Args:
        sec: Registro de secao eleitoral do catalogo analitico.

    Returns:
        Tupla (prior_pl, prior_pt) somando exatamente 1.0.

    Raises:
        None.
    """
    gv = dict(sec.get("group_votes", ()))
    pt_1t = float(gv.get("PT", 0) or 0)
    pl_1t = float(gv.get("PL", 0) or 0)
    sum_1t = pt_1t + pl_1t
    if sum_1t > 0.0:
        return (pl_1t / sum_1t, pt_1t / sum_1t)

    hd = dict(sec.get("historical_shares", ()))
    pt_h = float(hd.get("PT", 0.5) or 0.0)
    pl_h = float(hd.get("PL", 0.5) or 0.0)
    sum_h = pt_h + pl_h
    if sum_h > 0.0:
        return (pl_h / sum_h, pt_h / sum_h)

    return (0.5, 0.5)


def get_or_build_catalog_index(
    sections_catalog: Sequence[Mapping[str, Any]],
) -> SecondRoundCatalogIndex:
    """Retorna ou constroi em cache o indice colunar vetorizado do catalogo de secoes.

    Args:
        sections_catalog: Sequencia ordenada de secoes eleitorais.

    Returns:
        Instancia imutavel de SecondRoundCatalogIndex pronta para cortes em O(log N).

    Raises:
        ValueError: Se sections_catalog estiver vazio.
    """
    n = len(sections_catalog)
    if n == 0:
        raise ValueError("sections_catalog nao pode ser vazio.")

    first_id = str(sections_catalog[0].get("section_id", ""))
    last_id = str(sections_catalog[-1].get("section_id", ""))
    cache_key = (id(sections_catalog), n, f"{first_id}|{last_id}")
    cached = _INDEX_CACHE.get(cache_key)
    if cached is not None:
        return cached

    g_elec = np.empty(n, dtype=np.int64)
    g_mz = np.empty(n, dtype=np.int32)
    g_w_pl = np.empty(n, dtype=np.float64)
    g_w_pt = np.empty(n, dtype=np.float64)

    g_cluster_map: dict[tuple[str, str, str], int] = {}
    g_meta_list: list[tuple[str, str, str, MatchQuality]] = []

    uf_indices: dict[str, list[int]] = defaultdict(list)

    for i, sec in enumerate(sections_catalog):
        uf = str(sec.get("state", "BR")).strip().upper()
        muni = str(sec.get("municipality_code", "00000")).strip()
        zone = str(sec.get("zone", "0001")).strip()
        elec = max(1, int(sec.get("electorate", 0) or 0))
        p_pl, p_pt = _extract_section_2t_prior(sec)

        ckey = (uf, muni, zone)
        cid = g_cluster_map.get(ckey)
        if cid is None:
            cid = len(g_meta_list)
            g_cluster_map[ckey] = cid
            mq = _parse_match_quality(sec.get("match_quality"))
            g_meta_list.append((f"{uf}:{muni}:{zone}", uf, muni, mq))

        g_elec[i] = elec
        g_mz[i] = cid
        g_w_pl[i] = elec * p_pl
        g_w_pt[i] = elec * p_pt
        uf_indices[uf].append(i)

    g_cum_elec = np.cumsum(g_elec, dtype=np.int64)

    by_uf: dict[str, UFColumnarSlice] = {}
    for uf, idxs in uf_indices.items():
        idx_arr = np.asarray(idxs, dtype=np.int64)
        u_elec = g_elec[idx_arr]
        u_cum = np.cumsum(u_elec, dtype=np.int64)
        u_w_pl = g_w_pl[idx_arr]
        u_w_pt = g_w_pt[idx_arr]

        u_global_mz = g_mz[idx_arr]
        u_mz = np.empty(len(idxs), dtype=np.int32)
        local_map: dict[int, int] = {}
        u_meta_list: list[tuple[str, str, MatchQuality]] = []
        for pos, g_cid in enumerate(u_global_mz):
            gid = int(g_cid)
            lid = local_map.get(gid)
            if lid is None:
                lid = len(u_meta_list)
                local_map[gid] = lid
                cid_str, _, muni_code, mq_val = g_meta_list[gid]
                u_meta_list.append((cid_str, muni_code, mq_val))
            u_mz[pos] = lid

        by_uf[uf] = UFColumnarSlice(
            state=uf,
            electorates=u_elec,
            cum_electorates=u_cum,
            mz_codes=u_mz,
            mz_meta=tuple(u_meta_list),
            elec_prior_pl=u_w_pl,
            elec_prior_pt=u_w_pt,
        )

    built = SecondRoundCatalogIndex(
        num_sections=n,
        global_electorates=g_elec,
        global_cum_electorates=g_cum_elec,
        global_mz_codes=g_mz,
        global_mz_meta=tuple(g_meta_list),
        global_elec_prior_pl=g_w_pl,
        global_elec_prior_pt=g_w_pt,
        by_uf=by_uf,
    )
    if len(_INDEX_CACHE) >= 8:
        _INDEX_CACHE.clear()
    _INDEX_CACHE[cache_key] = built
    return built


def _aggregate_uf_slice(
    uf_slice: UFColumnarSlice,
    start: int,
    end: int,
) -> list[AggregatedStratum]:
    """Agrega vetorizadamente o intervalo [start, end) de uma UF por Zona Eleitoral via bincount.

    Args:
        uf_slice: Fatia colunar da UF.
        start: Indice inicial inclusivo.
        end: Indice final exclusivo.

    Returns:
        Lista de AggregatedStratum com eleitorado positivo no intervalo solicitado.

    Raises:
        None.
    """
    if end <= start:
        return []
    m = len(uf_slice.mz_meta)
    codes = uf_slice.mz_codes[start:end]
    sum_e = np.bincount(codes, weights=uf_slice.electorates[start:end], minlength=m)
    sum_pl = np.bincount(codes, weights=uf_slice.elec_prior_pl[start:end], minlength=m)
    sum_pt = np.bincount(codes, weights=uf_slice.elec_prior_pt[start:end], minlength=m)

    active = np.flatnonzero(sum_e > 0.0)
    strata: list[AggregatedStratum] = []
    for cid in active:
        i = int(cid)
        cid_str, muni_code, mq = uf_slice.mz_meta[i]
        tot_w = float(sum_pl[i] + sum_pt[i])
        p_pl = float(sum_pl[i] / tot_w) if tot_w > 0.0 else 0.5
        p_pt = float(sum_pt[i] / tot_w) if tot_w > 0.0 else 0.5
        strata.append(
            AggregatedStratum(
                stratum_id=cid_str,
                state=uf_slice.state,
                municipality_code=muni_code,
                electorate=max(1, int(round(float(sum_e[i])))),
                prior_pl=p_pl,
                prior_pt=p_pt,
                match_quality=mq,
            )
        )
    return strata


def _aggregate_global_slice(
    index: SecondRoundCatalogIndex,
    start: int,
    end: int,
    override_quality: MatchQuality | None = None,
) -> list[AggregatedStratum]:
    """Agrega vetorizadamente o intervalo global [start, end) por Zona Eleitoral via bincount.

    Args:
        index: Indice colunar global do catalogo.
        start: Indice inicial inclusivo.
        end: Indice final exclusivo.
        override_quality: Qualidade de pareamento opcional para refletir incerteza agregada.

    Returns:
        Lista de AggregatedStratum com eleitorado positivo no intervalo global.

    Raises:
        None.
    """
    if end <= start:
        return []
    m = len(index.global_mz_meta)
    codes = index.global_mz_codes[start:end]
    sum_e = np.bincount(codes, weights=index.global_electorates[start:end], minlength=m)
    sum_pl = np.bincount(codes, weights=index.global_elec_prior_pl[start:end], minlength=m)
    sum_pt = np.bincount(codes, weights=index.global_elec_prior_pt[start:end], minlength=m)

    active = np.flatnonzero(sum_e > 0.0)
    strata: list[AggregatedStratum] = []
    for cid in active:
        i = int(cid)
        cid_str, uf, muni_code, mq = index.global_mz_meta[i]
        tot_w = float(sum_pl[i] + sum_pt[i])
        p_pl = float(sum_pl[i] / tot_w) if tot_w > 0.0 else 0.5
        p_pt = float(sum_pt[i] / tot_w) if tot_w > 0.0 else 0.5
        strata.append(
            AggregatedStratum(
                stratum_id=cid_str,
                state=uf,
                municipality_code=muni_code,
                electorate=max(1, int(round(float(sum_e[i])))),
                prior_pl=p_pl,
                prior_pt=p_pt,
                match_quality=override_quality if override_quality is not None else mq,
            )
        )
    return strata


def allocate_stratum_observations(
    strata: Sequence[AggregatedStratum],
    target_pl: int,
    target_pt: int,
) -> list[SectionObservation]:
    """Distribui os votos oficiais exatos (target_pl, target_pt) sobre estratos observados via MLE.

    Garante reconstrucao inteira exata dos votos oficiais do TSE (sem jamais alterar totais
    observados) e preserva o swing log-ratio calibrado do estrato territorial.

    Args:
        strata: Estratos territoriais observados ate o corte atual.
        target_pl: Total oficial exato de votos validos do grupo PL no escopo.
        target_pt: Total oficial exato de votos validos do grupo PT no escopo.

    Returns:
        Lista de SectionObservation cujos votos somam exatamente (target_pl, target_pt).

    Raises:
        None.
    """
    total_valid = target_pl + target_pt
    if not strata or total_valid <= 0:
        return []

    raw_w = np.array([max(1.0, float(st.electorate)) for st in strata], dtype=np.float64)
    exact_v = raw_w * (float(total_valid) / float(raw_w.sum()))
    v_int = np.floor(exact_v).astype(np.int64)
    rem_v = int(total_valid - int(v_int.sum()))
    if rem_v > 0:
        top_idx = np.argsort(-(exact_v - v_int))[:rem_v]
        v_int[top_idx] += 1

    priors = np.array([[st.prior_pl, st.prior_pt] for st in strata], dtype=np.float64)
    priors = np.clip(priors, 1e-5, 1.0 - 1e-5)
    priors = priors / priors.sum(axis=1, keepdims=True)

    pos_mask = v_int > 0
    if not np.any(pos_mask):
        return []

    if target_pt == 0:
        pt_int = np.zeros_like(v_int)
    elif target_pl == 0:
        pt_int = v_int.copy()
    else:
        try:
            delta = calibrated_logratio_swing(
                v_int[pos_mask].astype(np.float64),
                priors[pos_mask],
                np.array([float(target_pl), float(target_pt)], dtype=np.float64),
                reference_index=0,
                pseudo_count=1.0,
            )
            d_arr = np.asarray(delta, dtype=np.float64)
            unnorm = priors * np.exp(d_arr - float(np.max(d_arr)))
            p_sec = unnorm / unnorm.sum(axis=1, keepdims=True)
            exact_pt: Float64Array = v_int.astype(np.float64) * p_sec[:, 1]
        except Exception:
            exact_pt = v_int.astype(np.float64) * (float(target_pt) / float(total_valid))

        pt_int = np.minimum(v_int, np.floor(exact_pt).astype(np.int64))
        rem_pt = int(target_pt - int(pt_int.sum()))
        if rem_pt > 0:
            avail = v_int - pt_int
            frac = np.where(avail > 0, exact_pt - pt_int, -1e9)
            for idx in np.argsort(-frac):
                if rem_pt <= 0:
                    break
                if pt_int[idx] < v_int[idx]:
                    pt_int[idx] += 1
                    rem_pt -= 1
        elif rem_pt < 0:
            need = -rem_pt
            frac = np.where(pt_int > 0, pt_int - exact_pt, -1e9)
            for idx in np.argsort(-frac):
                if need <= 0:
                    break
                if pt_int[idx] > 0:
                    pt_int[idx] -= 1
                    need -= 1

    pl_int = v_int - pt_int

    observations: list[SectionObservation] = []
    for i, st in enumerate(strata):
        vi = int(v_int[i])
        if vi <= 0:
            continue
        observations.append(
            SectionObservation(
                section_id=st.stratum_id,
                state=st.state,
                municipality_code=st.municipality_code,
                valid_votes=vi,
                group_votes=(("PL", int(pl_int[i])), ("PT", int(pt_int[i]))),
                historical_shares=(("PL", float(priors[i, 0])), ("PT", float(priors[i, 1]))),
            )
        )
    return observations


def _build_pending_sections(
    strata: Sequence[AggregatedStratum],
    target_pending_electorate: int,
    effective_valid_rate: float,
    qualities_out: dict[str, MatchQuality],
) -> list[PendingSection]:
    """Constroi PendingSection escalando eleitorado e taxa efetiva de votos validos do escopo.

    Args:
        strata: Estratos pendentes agregados por Zona Eleitoral.
        target_pending_electorate: Eleitorado pendente oficial reportado pelo TSE no escopo.
        effective_valid_rate: Taxa efetiva esperada (votos validos / eleitorado apto) em (0, 1].
        qualities_out: Dicionario mutavel preenchido com MatchQuality por section_id pendente.

    Returns:
        Lista de PendingSection prontas para simulacao Monte Carlo.

    Raises:
        None.
    """
    if not strata or target_pending_electorate <= 0:
        return []

    cat_pend_elec = sum(max(1, st.electorate) for st in strata)
    elec_scale = float(target_pending_electorate) / float(max(1, cat_pend_elec))
    clamped_eff = max(0.20, min(0.98, effective_valid_rate))
    turnout_rate = min(1.0, clamped_eff / PRIOR_VALID_RATE)

    pending_list: list[PendingSection] = []
    for st in strata:
        sec_id = f"pend:{st.stratum_id}"
        scaled_elec = max(1, int(round(max(1, st.electorate) * elec_scale)))
        pending_list.append(
            PendingSection(
                section_id=sec_id,
                state=st.state,
                municipality_code=st.municipality_code,
                electorate=scaled_elec,
                expected_turnout_rate=turnout_rate,
                expected_valid_rate=PRIOR_VALID_RATE,
                historical_shares=(("PL", st.prior_pl), ("PT", st.prior_pt)),
            )
        )
        qualities_out[sec_id] = st.match_quality
    return pending_list


def _has_usable_state_breakdown(
    totalization: NormalizedTotalization,
    state_totalizations: Mapping[str, NormalizedTotalization] | None,
    catalog_ufs: set[str],
) -> bool:
    """Verifica se o mapa de totalizacoes por UF e consistente e cobre o escopo nacional.

    Args:
        totalization: Totalizacao nacional consolidada (BR).
        state_totalizations: Mapeamento opcional UF -> NormalizedTotalization.
        catalog_ufs: Conjunto de UFs presentes no catalogo analitico.

    Returns:
        True se as totalizacoes estaduais forem validas e cobrirem >= 95% do eleitorado nacional.

    Raises:
        None.
    """
    if not state_totalizations:
        return False

    matched_ufs = 0
    sum_uf_total_elec = 0
    sum_uf_valid = 0
    for uf_key, utot in state_totalizations.items():
        uf_norm = uf_key.strip().upper()
        if utot.scope is not GeographicScope.STATE or utot.scope_code.upper() != uf_norm:
            return False
        if uf_norm in catalog_ufs:
            matched_ufs += 1
        sum_uf_total_elec += utot.total_electorate
        sum_uf_valid += utot.valid_votes

    if matched_ufs == 0 or sum_uf_valid <= 0:
        return False

    if totalization.total_electorate > 0:
        coverage = sum_uf_total_elec / float(totalization.total_electorate)
        if not 0.90 <= coverage <= 1.10:
            return False

    return True


def project_second_round_live(
    *,
    totalization: NormalizedTotalization,
    sections_catalog: Sequence[Mapping[str, Any]],
    state_totalizations: Mapping[str, NormalizedTotalization] | None = None,
    num_draws: int = 500,
    seed: int = 42,
    observed_at: datetime | None = None,
) -> PublishedProjectionPayload:
    """Executa projecao bayesiana em tempo real do 2o Turno condicionada aos votos reais do TSE.

    Reconcilia a totalizacao oficial, estima os swings em log-ratio calibrados sobre os votos
    reais do 2o turno (por UF quando ``state_totalizations`` esta disponivel, ou nacionalmente
    com correcao de chegada regional) e publica atomicamente o ``PublishedProjectionPayload``.

    Args:
        totalization: Totalizacao nacional consolidada oficial do TSE (BR).
        sections_catalog: Catalogo analitico de secoes ordenado cronologicamente.
        state_totalizations: Totalizacoes oficiais opcionais por UF (27 UFs + ZZ).
        num_draws: Quantidade de sorteios estocasticos no MonteCarloSimulator.
        seed: Semente deterministica para total reprodutibilidade.
        observed_at: Timestamp UTC da observacao (padrao: datetime.now(UTC)).

    Returns:
        PublishedProjectionPayload reconciliado e publicado com estimativas para PL e PT.

    Raises:
        ValueError: Se sections_catalog estiver vazio.
        RuntimeError: Se o relatorio de reconciliacao apontar inconsistencia.
    """
    now = observed_at if observed_at is not None else datetime.now(UTC)
    index = get_or_build_catalog_index(sections_catalog)

    br_votes = dict(totalization.candidate_group_votes)
    br_pl = int(br_votes.get("PL", 0))
    br_pt = int(br_votes.get("PT", 0))

    obs_all: list[SectionObservation] = []
    pend_all: list[PendingSection] = []
    qual_map: dict[str, MatchQuality] = {}

    is_complete = (totalization.total_sections > 0 and totalization.pending_sections == 0) or (
        totalization.total_electorate > 0
        and (
            totalization.pending_electorate == 0
            or totalization.totalized_electorate >= totalization.total_electorate
        )
    )

    if is_complete:
        all_strata = _aggregate_global_slice(index, 0, index.num_sections)
        obs_all = allocate_stratum_observations(all_strata, br_pl, br_pt)
    elif _has_usable_state_breakdown(totalization, state_totalizations, set(index.by_uf.keys())):
        assert state_totalizations is not None
        for uf, uf_slice in sorted(index.by_uf.items()):
            utot = state_totalizations.get(uf)
            if utot is None:
                continue
            u_votes = dict(utot.candidate_group_votes)
            y_pl = int(u_votes.get("PL", 0))
            y_pt = int(u_votes.get("PT", 0))
            n_uf = int(uf_slice.electorates.shape[0])

            uf_complete = (utot.total_sections > 0 and utot.pending_sections == 0) or (
                utot.total_electorate > 0
                and (
                    utot.pending_electorate == 0
                    or utot.totalized_electorate >= utot.total_electorate
                )
            )
            if uf_complete:
                obs_strata = _aggregate_uf_slice(uf_slice, 0, n_uf)
                obs_all.extend(allocate_stratum_observations(obs_strata, y_pl, y_pt))
                continue

            if (utot.total_sections > 0 and utot.totalized_sections <= 0) or (y_pl + y_pt) <= 0:
                pend_strata = _aggregate_uf_slice(uf_slice, 0, n_uf)
                pend_all.extend(
                    _build_pending_sections(
                        pend_strata,
                        utot.pending_electorate,
                        PRIOR_EFFECTIVE_VALID_RATE,
                        qual_map,
                    )
                )
                continue

            w_uf = utot.totalized_electorate / float(max(1, utot.total_electorate))
            tot_cat_elec = int(uf_slice.cum_electorates[-1])
            target_elec = w_uf * float(tot_cat_elec)
            raw_cut = int(np.searchsorted(uf_slice.cum_electorates, target_elec, side="left")) + 1
            cutoff = max(1, min(n_uf - 1, raw_cut)) if n_uf > 1 else 1

            obs_strata = _aggregate_uf_slice(uf_slice, 0, cutoff)
            obs_all.extend(allocate_stratum_observations(obs_strata, y_pl, y_pt))

            if cutoff < n_uf:
                pend_strata = _aggregate_uf_slice(uf_slice, cutoff, n_uf)
                obs_rate = (
                    utot.valid_votes / float(utot.totalized_electorate)
                    if utot.totalized_electorate > 0
                    else PRIOR_EFFECTIVE_VALID_RATE
                )
                cred = len(obs_strata) / (len(obs_strata) + 5.0)
                eff_rate = cred * obs_rate + (1.0 - cred) * PRIOR_EFFECTIVE_VALID_RATE
                pend_all.extend(
                    _build_pending_sections(
                        pend_strata,
                        utot.pending_electorate,
                        eff_rate,
                        qual_map,
                    )
                )
    else:
        w_br = (
            totalization.totalized_electorate / float(totalization.total_electorate)
            if totalization.total_electorate > 0
            else 0.0
        )
        tot_cat_elec = int(index.global_cum_electorates[-1])
        target_elec = max(0.0, min(1.0, w_br)) * float(tot_cat_elec)
        raw_cut = int(np.searchsorted(index.global_cum_electorates, target_elec, side="left")) + 1
        cutoff = max(1, min(index.num_sections - 1, raw_cut)) if index.num_sections > 1 else 1

        obs_strata = _aggregate_global_slice(index, 0, cutoff)
        obs_all = allocate_stratum_observations(obs_strata, br_pl, br_pt)

        if cutoff < index.num_sections and totalization.pending_electorate > 0:
            # Em modo apenas-BR (sem abertura por UF), aplica SAME_MUNICIPALITY (2.5x)
            # para refletir honestamente a incerteza adicional sobre os swings estaduais.
            pend_strata = _aggregate_global_slice(
                index,
                cutoff,
                index.num_sections,
                override_quality=MatchQuality.SAME_MUNICIPALITY,
            )
            obs_rate = (
                totalization.valid_votes / float(totalization.totalized_electorate)
                if totalization.totalized_electorate > 0
                else PRIOR_EFFECTIVE_VALID_RATE
            )
            cred = len(obs_strata) / (len(obs_strata) + 10.0)
            eff_rate = cred * obs_rate + (1.0 - cred) * PRIOR_EFFECTIVE_VALID_RATE
            pend_all = _build_pending_sections(
                pend_strata,
                totalization.pending_electorate,
                eff_rate,
                qual_map,
            )

    reconciler = ReconciliationEngine()
    publisher = AtomicPublisher()
    model = HierarchicalBayesianModelV2(reference_group="PL")
    simulator = MonteCarloSimulator(num_draws=num_draws, seed=seed)

    hash_src = (
        f"2T:{totalization.scope_code}:{totalization.totalized_sections}:"
        f"{totalization.totalized_electorate}:{br_pl}:{br_pt}"
    )
    artifact_hash = hashlib.sha256(hash_src.encode("utf-8")).hexdigest()

    snapshot, report = reconciler.reconcile(
        observed_at=now,
        sections=(),
        totalization=totalization,
        artifact_hashes=(artifact_hash,),
    )
    if not report.is_consistent:
        raise RuntimeError("Relatorio de reconciliacao apontou inconsistencia nos dados do 2T.")

    summary = simulator.simulate(
        observations=obs_all,
        pending=pend_all,
        model=model,
        groups=("PL", "PT"),
        match_qualities=qual_map if qual_map else None,
    )

    return publisher.publish(snapshot=snapshot, simulation=summary)


__all__ = [
    "AggregatedStratum",
    "SecondRoundCatalogIndex",
    "UFColumnarSlice",
    "allocate_stratum_observations",
    "get_or_build_catalog_index",
    "project_second_round_live",
]
