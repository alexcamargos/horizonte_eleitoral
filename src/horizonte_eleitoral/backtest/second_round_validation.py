"""Motor puro de replay historico e validacao retroativa de qualidade para o 2o Turno de 2026.

Avalia onda a onda (de 1% a 100% do eleitorado apurado) o desempenho preditivo do
``HierarchicalBayesianModelV2`` frente ao resultado oficial consolidado pelo TSE no 2o turno,
respeitando estritamente o contrato de Zero Vazamento Temporal (secoes pendentes apos o corte
expoem apenas eleitorado e prior bilateral do 1o turno) e o limiar minimo de 2,0% apurado.

Modulo puro: zero operacoes de I/O de rede, disco ou leitura de variaveis de ambiente.
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt

from horizonte_eleitoral.backtest.metrics import compute_metrics
from horizonte_eleitoral.domain.enums import GeographicScope, MatchQuality
from horizonte_eleitoral.historical.elasticity import MunicipalElasticityIndex
from horizonte_eleitoral.models.base import PendingSection, SectionObservation
from horizonte_eleitoral.models.hierarchical import REGIONS_BY_UF
from horizonte_eleitoral.models.hierarchical_v2 import HierarchicalBayesianModelV2
from horizonte_eleitoral.normalization.models import NormalizedTotalization
from horizonte_eleitoral.publishing.models import PublishedProjectionPayload
from horizonte_eleitoral.publishing.publisher import AtomicPublisher
from horizonte_eleitoral.reconciliation.reconciler import ReconciliationEngine
from horizonte_eleitoral.simulation.monte_carlo import MonteCarloSimulator

BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")

Int64Array = npt.NDArray[np.int64]
Int32Array = npt.NDArray[np.int32]
Float64Array = npt.NDArray[np.float64]

PRIOR_TURNOUT_RATE: float = 0.80
PRIOR_VALID_RATE: float = 0.96
PRIOR_EFFECTIVE_VALID_RATE: float = PRIOR_TURNOUT_RATE * PRIOR_VALID_RATE


@dataclass(frozen=True, slots=True)
class ValidationCatalogIndex:
    """Indice colunar vetorizado do catalogo cronologico do 2o Turno para replay sem vazamento.

    Attributes:
        num_sections: Quantidade total de secoes no catalogo ordenado.
        electorates: Eleitorado apto por secao.
        cum_electorates: Soma acumulada do eleitorado na ordem de chegada.
        votes_pl: Votos oficiais do 2o turno para PL por secao (acessados apenas ate ``cutoff``).
        votes_pt: Votos oficiais do 2o turno para PT por secao (acessados apenas ate ``cutoff``).
        cum_pl: Soma acumulada de votos PL para leitura O(1) em ``cutoff``.
        cum_pt: Soma acumulada de votos PT para leitura O(1) em ``cutoff``.
        mz_codes: Indice inteiro [0, M) do estrato Muni-Zona ('UF:municipio:zona') da secao.
        mz_meta: Metadados imutaveis (stratum_id, uf, municipality_code, match_quality, uf_idx).
        uf_codes: Indice inteiro [0, U) da Unidade Federativa de cada secao.
        uf_names: Siglas ordenadas das UFs presentes no catalogo.
        elec_prior_pl: Produto ``electorate * prior_pl_1t`` (derivado exclusivamente do historico).
        elec_prior_pt: Produto ``electorate * prior_pt_1t`` (derivado exclusivamente do historico).
        timestamps_brt: Horario formatado 'HH:MM' (BRT) de cada secao na ordem cronologica.
        final_pl_votes: Total consolidado oficial de votos PL em 100% do catalogo.
        final_pt_votes: Total consolidado oficial de votos PT em 100% do catalogo.
        final_shares: Participacoes percentuais oficiais finais {'PT': ..., 'PL': ...}.
    """

    num_sections: int
    electorates: Int64Array
    cum_electorates: Int64Array
    votes_pl: Int64Array
    votes_pt: Int64Array
    cum_pl: Int64Array
    cum_pt: Int64Array
    mz_codes: Int32Array
    mz_meta: tuple[tuple[str, str, str, MatchQuality, int], ...]
    uf_codes: Int32Array
    uf_names: tuple[str, ...]
    elec_prior_pl: Float64Array
    elec_prior_pt: Float64Array
    timestamps_brt: tuple[str, ...]
    final_pl_votes: int
    final_pt_votes: int
    final_shares: Mapping[str, float]


_VALIDATION_INDEX_CACHE: dict[tuple[int, int, str], ValidationCatalogIndex] = {}


def _parse_quality(raw_mq: Any) -> MatchQuality:
    """Converte valor de qualidade do catalogo em MatchQuality tipado.

    Args:
        raw_mq: Representacao bruta da qualidade de pareamento.

    Returns:
        Membro correspondente de MatchQuality (padrao: MatchQuality.EXACT).

    Raises:
        None.
    """
    if isinstance(raw_mq, MatchQuality):
        return raw_mq
    if raw_mq:
        s_val = str(raw_mq)
        try:
            return MatchQuality(s_val)
        except ValueError:
            if s_val in MatchQuality.__members__:
                return MatchQuality[s_val]
    return MatchQuality.EXACT


def _extract_strict_historical_prior(sec: Mapping[str, Any]) -> tuple[float, float]:
    """Extrai o prior bilateral (PL, PT) exclusivamente de ``historical_shares`` (sem vazamento).

    Jamais inspeciona ``group_votes`` da secao, assegurando que secoes pendentes nao vazem
    informacao dos votos realizados no 2o turno.

    Args:
        sec: Dicionario de secao eleitoral.

    Returns:
        Tupla (prior_pl, prior_pt) normalizada para somar 1.0.

    Raises:
        None.
    """
    hd = dict(sec.get("historical_shares", ()))
    pl_h = float(hd.get("PL", 0.0) or 0.0)
    pt_h = float(hd.get("PT", 0.0) or 0.0)
    total_h = pl_h + pt_h
    if total_h > 0.0:
        return (pl_h / total_h, pt_h / total_h)
    return (0.5, 0.5)


def get_or_build_validation_index(
    sections_catalog_2t: Sequence[Mapping[str, Any]],
) -> ValidationCatalogIndex:
    """Constroi ou recupera em cache o indice colunar de validacao do 2o Turno.

    Args:
        sections_catalog_2t: Sequencia cronologica de secoes do 2o turno.

    Returns:
        Instancia imutavel de ValidationCatalogIndex.

    Raises:
        ValueError: Se ``sections_catalog_2t`` estiver vazio.
    """
    n = len(sections_catalog_2t)
    if n == 0:
        raise ValueError("sections_catalog_2t nao pode ser vazio.")

    first_sec = sections_catalog_2t[0]
    last_sec = sections_catalog_2t[-1]
    sig = f"{first_sec.get('section_id', '')}|{last_sec.get('section_id', '')}"
    cache_key = (id(sections_catalog_2t), n, sig)
    cached = _VALIDATION_INDEX_CACHE.get(cache_key)
    if cached is not None:
        return cached

    ufs_sorted = sorted({str(s.get("state", "BR")).strip().upper() for s in sections_catalog_2t})
    uf_to_idx = {uf: idx for idx, uf in enumerate(ufs_sorted)}

    elec = np.empty(n, dtype=np.int64)
    v_pl = np.empty(n, dtype=np.int64)
    v_pt = np.empty(n, dtype=np.int64)
    mz_codes = np.empty(n, dtype=np.int32)
    uf_codes = np.empty(n, dtype=np.int32)
    w_pl = np.empty(n, dtype=np.float64)
    w_pt = np.empty(n, dtype=np.float64)
    ts_list: list[str] = []

    mz_map: dict[tuple[str, str, str], int] = {}
    mz_meta_list: list[tuple[str, str, str, MatchQuality, int]] = []

    for i, sec in enumerate(sections_catalog_2t):
        uf = str(sec.get("state", "BR")).strip().upper()
        muni = str(sec.get("municipality_code", "00000")).strip().zfill(5)
        zone = str(sec.get("zone", "0001")).strip().zfill(4)
        u_idx = uf_to_idx[uf]

        e_val = max(1, int(sec.get("electorate", 0) or 0))
        gv = dict(sec.get("group_votes", ()))
        pl_votes = max(0, int(gv.get("PL", 0) or 0))
        pt_votes = max(0, int(gv.get("PT", 0) or 0))
        p_pl, p_pt = _extract_strict_historical_prior(sec)

        ckey = (uf, muni, zone)
        cid = mz_map.get(ckey)
        if cid is None:
            cid = len(mz_meta_list)
            mz_map[ckey] = cid
            mq = _parse_quality(sec.get("match_quality"))
            mz_meta_list.append((f"{uf}:{muni}:{zone}", uf, muni, mq, u_idx))

        elec[i] = e_val
        v_pl[i] = pl_votes
        v_pt[i] = pt_votes
        mz_codes[i] = cid
        uf_codes[i] = u_idx
        w_pl[i] = e_val * p_pl
        w_pt[i] = e_val * p_pt

        raw_ts = sec.get("totalized_timestamp")
        if isinstance(raw_ts, datetime):
            brt_dt = (
                raw_ts.astimezone(BRASILIA_TZ)
                if raw_ts.tzinfo is not None
                else raw_ts.replace(tzinfo=UTC).astimezone(BRASILIA_TZ)
            )
            ts_list.append(brt_dt.strftime("%H:%M"))
        else:
            frac = (i + 1) / float(n)
            mins = 17 * 60 + 4 + int(round(frac * 265))
            ts_list.append(f"{(mins // 60) % 24:02d}:{mins % 60:02d}")

    cum_elec = np.cumsum(elec, dtype=np.int64)
    cum_pl = np.cumsum(v_pl, dtype=np.int64)
    cum_pt = np.cumsum(v_pt, dtype=np.int64)

    final_pl = int(cum_pl[-1])
    final_pt = int(cum_pt[-1])
    final_valid = final_pl + final_pt
    if final_valid > 0:
        final_shares = {
            "PT": (final_pt / float(final_valid)) * 100.0,
            "PL": (final_pl / float(final_valid)) * 100.0,
        }
    else:
        final_shares = {"PT": 50.0, "PL": 50.0}

    built = ValidationCatalogIndex(
        num_sections=n,
        electorates=elec,
        cum_electorates=cum_elec,
        votes_pl=v_pl,
        votes_pt=v_pt,
        cum_pl=cum_pl,
        cum_pt=cum_pt,
        mz_codes=mz_codes,
        mz_meta=tuple(mz_meta_list),
        uf_codes=uf_codes,
        uf_names=tuple(ufs_sorted),
        elec_prior_pl=w_pl,
        elec_prior_pt=w_pt,
        timestamps_brt=tuple(ts_list),
        final_pl_votes=final_pl,
        final_pt_votes=final_pt,
        final_shares=final_shares,
    )
    if len(_VALIDATION_INDEX_CACHE) >= 8:
        _VALIDATION_INDEX_CACHE.clear()
    _VALIDATION_INDEX_CACHE[cache_key] = built
    return built


def _compute_cutoff_index(index: ValidationCatalogIndex, wave: float) -> int:
    """Determina o indice de corte estrito ``cutoff`` em [1, num_sections] por eleitorado.

    Args:
        index: Indice colunar de validacao.
        wave: Fracao alvo do eleitorado no intervalo (0.0, 1.0].

    Returns:
        Quantidade inteira de secoes observadas no marco ``wave``.

    Raises:
        ValueError: Se ``wave`` estiver fora do intervalo (0.0, 1.0].
    """
    if not 0.0 < wave <= 1.0:
        raise ValueError("wave deve estar no intervalo (0.0, 1.0].")
    n = index.num_sections
    if wave >= 1.0 - 1e-9 or n == 1:
        return n
    target_elec = wave * float(index.cum_electorates[-1])
    raw_cut = int(np.searchsorted(index.cum_electorates, target_elec, side="left")) + 1
    return max(1, min(n - 1, raw_cut))


def simulate_second_round_wave_projection(
    *,
    sections_catalog_2t: Sequence[Mapping[str, Any]],
    wave: float,
    num_draws: int = 250,
    seed: int = 42,
    elasticity_index: MunicipalElasticityIndex | None = None,
    observed_at: datetime | None = None,
) -> tuple[PublishedProjectionPayload, str, int]:
    """Simula a projecao em tempo real em um marco percentual sem qualquer vazamento futuro.

    Particiona estritamente em ``cutoff``:
    - ``[:cutoff]`` expoe os votos observados ate aquele instante e os priors historicos;
    - ``[cutoff:]`` expoe exclusivamente eleitorado e priors historicos do 1o turno.

    Args:
        sections_catalog_2t: Catalogo cronologico do 2o turno.
        wave: Fracao do eleitorado apurado em (0.0, 1.0].
        num_draws: Quantidade de sorteios estocasticos no MonteCarloSimulator.
        seed: Semente deterministica pseudoaleatoria.
        elasticity_index: Indice opcional de elasticidade municipal 2018-2022.
        observed_at: Timestamp UTC opcional da rodada.

    Returns:
        Tupla (PublishedProjectionPayload, time_str_brt, cutoff_sections).

    Raises:
        ValueError: Se ``sections_catalog_2t`` estiver vazio ou ``wave`` for invalido.
    """
    index = get_or_build_validation_index(sections_catalog_2t)
    cutoff = _compute_cutoff_index(index, wave)
    n = index.num_sections
    m = len(index.mz_meta)
    u_count = len(index.uf_names)

    obs_codes = index.mz_codes[:cutoff]
    obs_pl_mz = np.bincount(obs_codes, weights=index.votes_pl[:cutoff], minlength=m)
    obs_pt_mz = np.bincount(obs_codes, weights=index.votes_pt[:cutoff], minlength=m)
    obs_w_pl = np.bincount(obs_codes, weights=index.elec_prior_pl[:cutoff], minlength=m)
    obs_w_pt = np.bincount(obs_codes, weights=index.elec_prior_pt[:cutoff], minlength=m)

    observations: list[SectionObservation] = []
    for cid in np.flatnonzero((obs_pl_mz + obs_pt_mz) > 0):
        c = int(cid)
        cid_str, uf, muni_code, _, _ = index.mz_meta[c]
        y_pl = int(round(float(obs_pl_mz[c])))
        y_pt = int(round(float(obs_pt_mz[c])))
        v_tot = y_pl + y_pt
        if v_tot <= 0:
            continue
        sum_w = float(obs_w_pl[c] + obs_w_pt[c])
        p_pl = float(obs_w_pl[c] / sum_w) if sum_w > 0.0 else 0.5
        p_pt = float(obs_w_pt[c] / sum_w) if sum_w > 0.0 else 0.5
        observations.append(
            SectionObservation(
                section_id=cid_str,
                state=uf,
                municipality_code=muni_code,
                valid_votes=v_tot,
                group_votes=(("PL", y_pl), ("PT", y_pt)),
                historical_shares=(("PL", p_pl), ("PT", p_pt)),
            )
        )

    obs_pl_tot = int(index.cum_pl[cutoff - 1])
    obs_pt_tot = int(index.cum_pt[cutoff - 1])
    obs_valid_tot = obs_pl_tot + obs_pt_tot
    obs_elec_tot = int(index.cum_electorates[cutoff - 1])
    tot_elec_all = int(index.cum_electorates[-1])

    pending: list[PendingSection] = []
    qual_map: dict[str, MatchQuality] = {}

    if cutoff < n:
        # Taxa efetiva observada ate cutoff por UF (zero leitura apos cutoff)
        obs_uf_codes = index.uf_codes[:cutoff]
        obs_uf_elec = np.bincount(
            obs_uf_codes, weights=index.electorates[:cutoff], minlength=u_count
        )
        obs_uf_valid = np.bincount(
            obs_uf_codes,
            weights=(index.votes_pl[:cutoff] + index.votes_pt[:cutoff]),
            minlength=u_count,
        )
        nat_obs_rate = (
            obs_valid_tot / float(obs_elec_tot) if obs_elec_tot > 0 else PRIOR_EFFECTIVE_VALID_RATE
        )
        cred_nat = obs_elec_tot / (obs_elec_tot + 50_000.0)
        shrunk_nat_rate = cred_nat * nat_obs_rate + (1.0 - cred_nat) * PRIOR_EFFECTIVE_VALID_RATE

        uf_eff_rates = np.empty(u_count, dtype=np.float64)
        for u_idx in range(u_count):
            ue = float(obs_uf_elec[u_idx])
            if ue > 0.0:
                u_rate = float(obs_uf_valid[u_idx]) / ue
                cred_u = ue / (ue + 20_000.0)
                eff_u = cred_u * u_rate + (1.0 - cred_u) * shrunk_nat_rate
            else:
                eff_u = shrunk_nat_rate
            uf_eff_rates[u_idx] = max(0.20, min(0.98, eff_u))

        pend_codes = index.mz_codes[cutoff:n]
        pend_elec_mz = np.bincount(pend_codes, weights=index.electorates[cutoff:n], minlength=m)
        pend_w_pl = np.bincount(pend_codes, weights=index.elec_prior_pl[cutoff:n], minlength=m)
        pend_w_pt = np.bincount(pend_codes, weights=index.elec_prior_pt[cutoff:n], minlength=m)

        for cid in np.flatnonzero(pend_elec_mz > 0):
            c = int(cid)
            cid_str, uf, muni_code, mq, u_idx = index.mz_meta[c]
            p_elec = max(1, int(round(float(pend_elec_mz[c]))))
            sum_w = float(pend_w_pl[c] + pend_w_pt[c])
            p_pl = float(pend_w_pl[c] / sum_w) if sum_w > 0.0 else 0.5
            p_pt = float(pend_w_pt[c] / sum_w) if sum_w > 0.0 else 0.5
            turnout_u = min(1.0, float(uf_eff_rates[u_idx]) / PRIOR_VALID_RATE)
            sec_id = f"pend:{cid_str}"
            pending.append(
                PendingSection(
                    section_id=sec_id,
                    state=uf,
                    municipality_code=muni_code,
                    electorate=p_elec,
                    expected_turnout_rate=turnout_u,
                    expected_valid_rate=PRIOR_VALID_RATE,
                    historical_shares=(("PL", p_pl), ("PT", p_pt)),
                )
            )
            qual_map[sec_id] = mq

    totalization = NormalizedTotalization(
        scope=GeographicScope.BRAZIL,
        scope_code="BR",
        total_electorate=tot_elec_all,
        totalized_electorate=obs_elec_tot,
        pending_electorate=max(0, tot_elec_all - obs_elec_tot),
        total_sections=n,
        totalized_sections=cutoff,
        pending_sections=max(0, n - cutoff),
        valid_votes=obs_valid_tot,
        blank_votes=0,
        null_votes=0,
        candidate_group_votes=(("PL", obs_pl_tot), ("PT", obs_pt_tot)),
    )

    now = observed_at if observed_at is not None else datetime.now(UTC)
    reconciler = ReconciliationEngine()
    publisher = AtomicPublisher()
    model = HierarchicalBayesianModelV2(
        elasticity_index=elasticity_index,
        reference_group="PL",
    )
    simulator = MonteCarloSimulator(num_draws=num_draws, seed=seed)

    artifact_hash = hashlib.sha256(
        f"2T-VAL:{cutoff}:{obs_elec_tot}:{obs_pl_tot}:{obs_pt_tot}".encode()
    ).hexdigest()

    snapshot, report = reconciler.reconcile(
        observed_at=now,
        sections=(),
        totalization=totalization,
        artifact_hashes=(artifact_hash,),
    )
    if not report.is_consistent:
        raise RuntimeError("Falha de reconciliacao na rodada de validacao do 2o turno.")

    summary = simulator.simulate(
        observations=observations,
        pending=pending,
        model=model,
        groups=("PL", "PT"),
        match_qualities=qual_map if qual_map else None,
    )
    payload = publisher.publish(snapshot=snapshot, simulation=summary)
    time_str = index.timestamps_brt[cutoff - 1]
    return payload, time_str, cutoff


def evaluate_second_round_wave(
    *,
    sections_catalog_2t: Sequence[Mapping[str, Any]],
    wave: float,
    num_draws: int = 250,
    seed: int = 42,
    elasticity_index: MunicipalElasticityIndex | None = None,
    official_final_shares: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Executa a projecao em ``wave`` e audita retroativamente sua qualidade contra o final TSE.

    Args:
        sections_catalog_2t: Catalogo cronologico do 2o turno.
        wave: Fracao do eleitorado apurado em (0.0, 1.0].
        num_draws: Quantidade de sorteios estocasticos Monte Carlo.
        seed: Semente deterministica pseudoaleatoria.
        elasticity_index: Indice opcional de elasticidade municipal 2018-2022.
        official_final_shares: Resultado oficial 100% opcional {'PT': ..., 'PL': ...}.
            Se None, utiliza a consolidacao de 100% do proprio ``sections_catalog_2t``.

    Returns:
        Dicionario completo do marco com ``apurado``, ``projecao``, ``faixa``,
        ``win_probability``, ``final_oficial`` e ``metrics`` de auditoria retroativa.

    Raises:
        ValueError: Se ``sections_catalog_2t`` estiver vazio ou ``wave`` for invalido.
    """
    index = get_or_build_validation_index(sections_catalog_2t)
    payload, time_str, cutoff = simulate_second_round_wave_projection(
        sections_catalog_2t=sections_catalog_2t,
        wave=wave,
        num_draws=num_draws,
        seed=seed,
        elasticity_index=elasticity_index,
    )

    final_exact = dict(official_final_shares or index.final_shares)
    final_rounded = {
        "PT": round(float(final_exact["PT"]), 2),
        "PL": round(float(final_exact["PL"]), 2),
    }

    group_map = {g.code: g for g in payload.groups}
    obs_exact: dict[str, float] = {
        str(code): float(group_map[code].observed_share)
        for code in ("PT", "PL")
        if code in group_map
    }
    apurado = {code: round(val, 2) for code, val in obs_exact.items()}

    x_elec = round(payload.totalized_electorate_pct, 2)
    x_sec = round((cutoff / float(index.num_sections)) * 100.0, 2)
    tem_projecao = x_elec >= 2.0
    if x_elec <= 0.35 and "17:00" <= time_str < "19:00":
        time_str = "17:07–19:00"

    raw_mae, raw_bias, raw_lead_err = compute_metrics(
        projected_shares=obs_exact,
        final_shares=final_exact,
        groups=("PT", "PL"),
    )

    projecao: dict[str, float] | None = None
    faixa: dict[str, list[float]] | None = None
    win_prob: dict[str, float] | None = None
    preliminar: dict[str, float] | None = None

    model_mae: float | None = None
    model_bias: float | None = None
    model_lead_err: float | None = None
    mae_gain: float | None = None
    ci_width: float | None = None
    ci_covered: bool | None = None
    leader_correct: bool | None = None

    if tem_projecao:
        proj_exact: dict[str, float] = {
            str(code): float(group_map[code].projected_share)
            for code in ("PT", "PL")
            if code in group_map
        }
        projecao = {code: round(val, 2) for code, val in proj_exact.items()}
        faixa = {
            code: [round(float(group_map[code].q05), 2), round(float(group_map[code].q95), 2)]
            for code in ("PT", "PL")
            if code in group_map
        }
        win_prob = {
            code: round(float(group_map[code].win_probability), 4)
            for code in ("PT", "PL")
            if code in group_map
        }

        m_mae, m_bias, m_lead = compute_metrics(
            projected_shares=proj_exact,
            final_shares=final_exact,
            groups=("PT", "PL"),
        )
        model_mae = round(m_mae, 2)
        model_bias = round(m_bias, 2)
        model_lead_err = round(m_lead, 2)
        mae_gain = round(raw_mae - m_mae, 2)

        q05_pt = float(group_map["PT"].q05)
        q95_pt = float(group_map["PT"].q95)
        ci_width = round(max(0.0, q95_pt - q05_pt), 2)
        # Tolerancia de 0.01 pp evita falsos negativos por arredondamento na convergencia 100%
        ci_covered = (q05_pt - 0.01) <= float(final_exact["PT"]) <= (q95_pt + 0.01)

        winner_final = "PT" if float(final_exact["PT"]) >= float(final_exact["PL"]) else "PL"
        winner_proj = "PT" if proj_exact["PT"] >= proj_exact["PL"] else "PL"
        leader_correct = winner_proj == winner_final
    else:
        preliminar = {
            code: round(float(group_map[code].projected_share), 2)
            for code in ("PT", "PL")
            if code in group_map
        }

    return {
        "t": time_str,
        "x": x_elec,
        "x_sections": x_sec,
        "apurado": apurado,
        "projecao": projecao,
        "faixa": faixa,
        "win_probability": win_prob,
        "preliminar": preliminar,
        "final_oficial": final_rounded,
        "metrics": {
            "raw_mae_pp": round(raw_mae, 2),
            "raw_bias_leader_pp": round(raw_bias, 2),
            "raw_lead_error_pp": round(raw_lead_err, 2),
            "model_mae_pp": model_mae,
            "model_bias_leader_pp": model_bias,
            "model_lead_error_pp": model_lead_err,
            "mae_gain_pp": mae_gain,
            "ci_width_pp": ci_width,
            "ci_90_covered": ci_covered,
            "leader_correct": leader_correct,
        },
        "round": 2,
    }


def summarize_second_round_validation(
    points: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Consolida os indicadores globais de qualidade retroativa do modelo ao longo das ondas.

    Args:
        points: Sequencia cronologica de pontos avaliados por ``evaluate_second_round_wave``.

    Returns:
        Dicionario com erro medio (MAE) do modelo vs urna bruta nas ondas parciais,
        cobertura empirica do IC 90% e os marcos de lideranca correta e cravada estatistica.

    Raises:
        None.
    """
    if not points:
        return {
            "final_oficial": {"PT": 50.0, "PL": 50.0},
            "winner_code": "PT",
            "partial_waves_count": 0,
            "mean_model_mae_pp": None,
            "max_model_mae_pp": None,
            "mean_raw_mae_pp": None,
            "ci_90_coverage_pct": None,
            "earliest_correct_leader_pct": None,
            "earliest_correct_leader_time": None,
            "statistical_call_pct": None,
            "statistical_call_time": None,
        }

    ordered = sorted(points, key=lambda p: float(p.get("x", 0.0)))
    final_oficial = dict(ordered[-1].get("final_oficial") or {"PT": 51.77, "PL": 48.23})
    winner = "PT" if float(final_oficial.get("PT", 50.0)) >= 50.0 else "PL"

    valid_pts = [p for p in ordered if p.get("projecao") is not None]
    partial_pts = [p for p in valid_pts if float(p.get("x", 0.0)) < 99.95]

    eval_pool = partial_pts if partial_pts else valid_pts
    model_maes = [
        float(p["metrics"]["model_mae_pp"])
        for p in eval_pool
        if p.get("metrics") and p["metrics"].get("model_mae_pp") is not None
    ]
    raw_maes = [
        float(p["metrics"]["raw_mae_pp"])
        for p in eval_pool
        if p.get("metrics") and p["metrics"].get("raw_mae_pp") is not None
    ]
    covered_flags = [
        bool(p["metrics"]["ci_90_covered"])
        for p in valid_pts
        if p.get("metrics") and p["metrics"].get("ci_90_covered") is not None
    ]

    # Marco estavel de lideranca correta: primeiro ponto a partir do qual nunca mais errou o lider
    earliest_leader_pct: float | None = None
    earliest_leader_time: str | None = None
    for idx in range(len(valid_pts)):
        if all(
            bool((valid_pts[k].get("metrics") or {}).get("leader_correct"))
            for k in range(idx, len(valid_pts))
        ):
            earliest_leader_pct = float(valid_pts[idx]["x"])
            earliest_leader_time = str(valid_pts[idx].get("t", ""))
            break

    # Cravada estatistica: primeiro ponto a partir do qual P(vitoria do vencedor real) >= 95%
    stat_call_pct: float | None = None
    stat_call_time: str | None = None
    for idx in range(len(valid_pts)):
        if all(
            float((valid_pts[k].get("win_probability") or {}).get(winner, 0.0)) >= 0.95
            for k in range(idx, len(valid_pts))
        ):
            stat_call_pct = float(valid_pts[idx]["x"])
            stat_call_time = str(valid_pts[idx].get("t", ""))
            break

    return {
        "final_oficial": final_oficial,
        "winner_code": winner,
        "partial_waves_count": len(partial_pts),
        "mean_model_mae_pp": (round(sum(model_maes) / len(model_maes), 2) if model_maes else None),
        "max_model_mae_pp": round(max(model_maes), 2) if model_maes else None,
        "mean_raw_mae_pp": round(sum(raw_maes) / len(raw_maes), 2) if raw_maes else None,
        "ci_90_coverage_pct": (
            round((sum(1 for c in covered_flags if c) / len(covered_flags)) * 100.0, 1)
            if covered_flags
            else None
        ),
        "earliest_correct_leader_pct": earliest_leader_pct,
        "earliest_correct_leader_time": earliest_leader_time,
        "statistical_call_pct": stat_call_pct,
        "statistical_call_time": stat_call_time,
    }


def generate_second_round_state_validation(
    *,
    sections_catalog_2t: Sequence[Mapping[str, Any]],
    wave: float,
    elasticity_index: MunicipalElasticityIndex | None = None,
) -> list[dict[str, Any]]:
    """Calcula a projecao estadual sem vazamento em ``wave`` e audita contra o final de cada UF.

    Args:
        sections_catalog_2t: Catalogo cronologico de secoes do 2o turno.
        wave: Fracao do eleitorado nacional apurado em (0.0, 1.0].
        elasticity_index: Indice opcional de elasticidade municipal 2018-2022.

    Returns:
        Lista de dicionarios por UF com % apurado, urna parcial 2T, projecao V2 2T,
        resultado final oficial TSE 2T, prior bilateral do 1T e erro absoluto em pp.

    Raises:
        ValueError: Se ``sections_catalog_2t`` estiver vazio ou ``wave`` for invalido.
    """
    index = get_or_build_validation_index(sections_catalog_2t)
    cutoff = _compute_cutoff_index(index, wave)
    n = index.num_sections
    m = len(index.mz_meta)
    u_count = len(index.uf_names)

    obs_codes = index.mz_codes[:cutoff]
    obs_pl_mz = np.bincount(obs_codes, weights=index.votes_pl[:cutoff], minlength=m)
    obs_pt_mz = np.bincount(obs_codes, weights=index.votes_pt[:cutoff], minlength=m)
    obs_w_pl = np.bincount(obs_codes, weights=index.elec_prior_pl[:cutoff], minlength=m)
    obs_w_pt = np.bincount(obs_codes, weights=index.elec_prior_pt[:cutoff], minlength=m)

    obs_objs: list[SectionObservation] = []
    for cid in np.flatnonzero((obs_pl_mz + obs_pt_mz) > 0):
        c = int(cid)
        cid_str, uf, muni_code, _, _ = index.mz_meta[c]
        y_pl = int(round(float(obs_pl_mz[c])))
        y_pt = int(round(float(obs_pt_mz[c])))
        v_tot = y_pl + y_pt
        if v_tot <= 0:
            continue
        sum_w = float(obs_w_pl[c] + obs_w_pt[c])
        p_pl = float(obs_w_pl[c] / sum_w) if sum_w > 0.0 else 0.5
        p_pt = float(obs_w_pt[c] / sum_w) if sum_w > 0.0 else 0.5
        obs_objs.append(
            SectionObservation(
                section_id=cid_str,
                state=uf,
                municipality_code=muni_code,
                valid_votes=v_tot,
                group_votes=(("PL", y_pl), ("PT", y_pt)),
                historical_shares=(("PL", p_pl), ("PT", p_pt)),
            )
        )

    model = HierarchicalBayesianModelV2(
        elasticity_index=elasticity_index,
        reference_group="PL",
    )
    delta_nat, delta_reg, delta_uf, _ = model.estimate_effects(obs_objs, ("PL", "PT"))

    # Totais estaduais (100% final para auditoria + parciais ate cutoff)
    tot_uf_elec = np.bincount(index.uf_codes, weights=index.electorates, minlength=u_count)
    tot_uf_pl = np.bincount(index.uf_codes, weights=index.votes_pl, minlength=u_count)
    tot_uf_pt = np.bincount(index.uf_codes, weights=index.votes_pt, minlength=u_count)
    tot_uf_w_pl = np.bincount(index.uf_codes, weights=index.elec_prior_pl, minlength=u_count)
    tot_uf_w_pt = np.bincount(index.uf_codes, weights=index.elec_prior_pt, minlength=u_count)

    obs_uf_elec = np.bincount(
        index.uf_codes[:cutoff], weights=index.electorates[:cutoff], minlength=u_count
    )
    obs_uf_pl = np.bincount(
        index.uf_codes[:cutoff], weights=index.votes_pl[:cutoff], minlength=u_count
    )
    obs_uf_pt = np.bincount(
        index.uf_codes[:cutoff], weights=index.votes_pt[:cutoff], minlength=u_count
    )

    pend_mz_elec = (
        np.bincount(index.mz_codes[cutoff:n], weights=index.electorates[cutoff:n], minlength=m)
        if cutoff < n
        else np.zeros(m, dtype=np.float64)
    )
    pend_mz_w_pl = (
        np.bincount(index.mz_codes[cutoff:n], weights=index.elec_prior_pl[cutoff:n], minlength=m)
        if cutoff < n
        else np.zeros(m, dtype=np.float64)
    )
    pend_mz_w_pt = (
        np.bincount(index.mz_codes[cutoff:n], weights=index.elec_prior_pt[cutoff:n], minlength=m)
        if cutoff < n
        else np.zeros(m, dtype=np.float64)
    )

    pend_by_uf: dict[int, list[int]] = defaultdict(list)
    for cid in np.flatnonzero(pend_mz_elec > 0):
        c = int(cid)
        u_idx = index.mz_meta[c][4]
        pend_by_uf[u_idx].append(c)

    obs_valid_all = float(obs_uf_pl.sum() + obs_uf_pt.sum())
    obs_elec_all = float(obs_uf_elec.sum())
    nat_rate = obs_valid_all / obs_elec_all if obs_elec_all > 0.0 else PRIOR_EFFECTIVE_VALID_RATE

    rows: list[dict[str, Any]] = []
    for u_idx, uf in enumerate(index.uf_names):
        t_elec = float(tot_uf_elec[u_idx])
        o_elec = float(obs_uf_elec[u_idx])
        pct_apu = round((o_elec / t_elec * 100.0) if t_elec > 0.0 else 0.0, 1)

        o_pl = float(obs_uf_pl[u_idx])
        o_pt = float(obs_uf_pt[u_idx])
        o_valid = o_pl + o_pt
        obs_pt_share = round(o_pt / o_valid * 100.0, 2) if o_valid > 0.0 else None

        f_pl = float(tot_uf_pl[u_idx])
        f_pt = float(tot_uf_pt[u_idx])
        f_valid = f_pl + f_pt
        final_pt_share = round(f_pt / f_valid * 100.0, 2) if f_valid > 0.0 else 50.0
        final_pl_share = round(100.0 - final_pt_share, 2)

        w_sum_1t = float(tot_uf_w_pl[u_idx] + tot_uf_w_pt[u_idx])
        prior_1t_pt = (
            round(float(tot_uf_w_pt[u_idx]) / w_sum_1t * 100.0, 2) if w_sum_1t > 0 else 50.0
        )

        reg = REGIONS_BY_UF.get(uf, "OUTRA")
        d_state = delta_uf.get(uf) or delta_reg.get(reg) or delta_nat
        max_d = max(d_state.values(), default=0.0)

        u_eff_rate = (
            (o_valid / o_elec) * (o_elec / (o_elec + 20_000.0))
            + nat_rate * (1.0 - o_elec / (o_elec + 20_000.0))
            if o_elec > 0.0
            else nat_rate
        )

        pend_pl_proj = 0.0
        pend_pt_proj = 0.0
        for c in pend_by_uf.get(u_idx, []):
            pe = float(pend_mz_elec[c])
            v_exp = pe * u_eff_rate
            sw = float(pend_mz_w_pl[c] + pend_mz_w_pt[c])
            p_pl_c = float(pend_mz_w_pl[c] / sw) if sw > 0.0 else 0.5
            p_pt_c = float(pend_mz_w_pt[c] / sw) if sw > 0.0 else 0.5
            wt_pl = max(p_pl_c, 1e-5) * math.exp(d_state.get("PL", 0.0) - max_d)
            wt_pt = max(p_pt_c, 1e-5) * math.exp(d_state.get("PT", 0.0) - max_d)
            wt_tot = wt_pl + wt_pt
            if wt_tot > 0.0:
                pend_pl_proj += v_exp * (wt_pl / wt_tot)
                pend_pt_proj += v_exp * (wt_pt / wt_tot)

        tot_proj_valid = o_valid + pend_pl_proj + pend_pt_proj
        if tot_proj_valid > 0.0:
            proj_pt_share = round(((o_pt + pend_pt_proj) / tot_proj_valid) * 100.0, 2)
        else:
            proj_pt_share = prior_1t_pt
        proj_pl_share = round(100.0 - proj_pt_share, 2)

        rows.append(
            {
                "uf": uf,
                "x": pct_apu,
                "apurado_PT": obs_pt_share,
                "PT": proj_pt_share,
                "PL": proj_pl_share,
                "final_PT": final_pt_share,
                "final_PL": final_pl_share,
                "prior_1t_PT": prior_1t_pt,
                "swing_2t_pp": round(final_pt_share - prior_1t_pt, 2),
                "erro_modelo_pp": round(abs(proj_pt_share - final_pt_share), 2),
            }
        )

    return rows


__all__ = [
    "ValidationCatalogIndex",
    "evaluate_second_round_wave",
    "generate_second_round_state_validation",
    "get_or_build_validation_index",
    "simulate_second_round_wave_projection",
    "summarize_second_round_validation",
]
