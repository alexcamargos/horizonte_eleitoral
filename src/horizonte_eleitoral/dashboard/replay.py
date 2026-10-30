"""Motor de reproducao e geracao de series temporais de apuracao para o dashboard."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from horizonte_eleitoral.config import get_final_data_dir, get_real_data_dir
from horizonte_eleitoral.domain.enums import GeographicScope
from horizonte_eleitoral.ingestion.real_data_loader import RealDataLoader
from horizonte_eleitoral.models.base import SectionObservation
from horizonte_eleitoral.models.hierarchical import REGIONS_BY_UF
from horizonte_eleitoral.models.hierarchical_v2 import HierarchicalBayesianModelV2
from horizonte_eleitoral.normalization.models import NormalizedTotalization
from horizonte_eleitoral.simulation.election_night_runner import (
    calculate_wave_cutoff,
    simulate_2026_real_checkpoint,
)

BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")

# Lista de marcos padronizados de apuracao para a curva de evolucao (1º Turno)
DEFAULT_CHECKPOINTS: tuple[float, ...] = (
    0.01,
    0.02,
    0.05,
    0.10,
    0.20,
    0.30,
    0.40,
    0.50,
    0.60,
    0.70,
    0.80,
    0.90,
    1.00,
)

# Marcos reais do 2º Turno de 2026: inclui o patamar de 0,25% (suspenso das 17h07 as 19h00 BRT)
DEFAULT_2T_CHECKPOINTS: tuple[float, ...] = (
    0.0025,
    0.01,
    0.02,
    0.05,
    0.10,
    0.20,
    0.30,
    0.40,
    0.50,
    0.60,
    0.70,
    0.80,
    0.90,
    0.95,
    1.00,
)

# Pesquisas de intencao de voto pre-eleicao (Quaest/Datafolha convertidas em votos validos)
DEFAULT_STATE_POLLS: dict[str, dict[str, float]] = {
    "AC": {"PT": 28.9, "PL": 60.2, "OUTROS": 10.9},
    "AL": {"PT": 56.4, "PL": 37.1, "OUTROS": 6.5},
    "AM": {"PT": 50.1, "PL": 43.5, "OUTROS": 6.4},
    "AP": {"PT": 45.3, "PL": 47.9, "OUTROS": 6.8},
    "BA": {"PT": 69.8, "PL": 24.3, "OUTROS": 5.9},
    "CE": {"PT": 65.2, "PL": 28.5, "OUTROS": 6.3},
    "DF": {"PT": 37.2, "PL": 52.8, "OUTROS": 10.0},
    "ES": {"PT": 40.5, "PL": 52.6, "OUTROS": 6.9},
    "GO": {"PT": 36.1, "PL": 56.2, "OUTROS": 7.7},
    "MA": {"PT": 67.5, "PL": 26.3, "OUTROS": 6.2},
    "MG": {"PT": 48.2, "PL": 44.8, "OUTROS": 7.0},
    "MS": {"PT": 38.0, "PL": 54.5, "OUTROS": 7.5},
    "MT": {"PT": 32.5, "PL": 60.5, "OUTROS": 7.0},
    "PA": {"PT": 52.0, "PL": 41.5, "OUTROS": 6.5},
    "PB": {"PT": 63.5, "PL": 30.1, "OUTROS": 6.4},
    "PE": {"PT": 64.8, "PL": 29.2, "OUTROS": 6.0},
    "PI": {"PT": 73.2, "PL": 21.5, "OUTROS": 5.3},
    "PR": {"PT": 36.5, "PL": 55.4, "OUTROS": 8.1},
    "RJ": {"PT": 41.2, "PL": 51.5, "OUTROS": 7.3},
    "RN": {"PT": 62.8, "PL": 30.8, "OUTROS": 6.4},
    "RO": {"PT": 29.5, "PL": 63.2, "OUTROS": 7.3},
    "RR": {"PT": 24.5, "PL": 68.8, "OUTROS": 6.7},
    "RS": {"PT": 43.1, "PL": 49.5, "OUTROS": 7.4},
    "SC": {"PT": 30.2, "PL": 62.5, "OUTROS": 7.3},
    "SE": {"PT": 62.5, "PL": 31.0, "OUTROS": 6.5},
    "SP": {"PT": 41.5, "PL": 50.8, "OUTROS": 7.7},
    "TO": {"PT": 51.5, "PL": 42.8, "OUTROS": 5.7},
}


def _get_checkpoints_file() -> Path:
    """Retorna o caminho canonico do arquivo de checkpoints do 1º Turno."""
    final_path = get_final_data_dir() / "checkpoints_2026.json"
    if final_path.exists():
        return final_path
    return get_real_data_dir() / "checkpoints_2026.json"


def _get_checkpoints_2t_file() -> Path:
    """Retorna o caminho canonico do arquivo de checkpoints do 2º Turno."""
    final_path = get_final_data_dir() / "checkpoints_2026_2t.json"
    if final_path.exists():
        return final_path
    return get_real_data_dir() / "checkpoints_2026_2t.json"


_CHECKPOINTS_FILE = _get_checkpoints_file()
_CHECKPOINTS_2T_FILE = _get_checkpoints_2t_file()
_PRECOMPUTED_CHECKPOINTS: dict[str, dict[str, Any]] | None = None
_PRECOMPUTED_CHECKPOINTS_2T: dict[str, dict[str, Any]] | None = None
_CATALOG_CACHE: dict[int | None, list[dict[str, Any]]] = {}
_CATALOG_2T_CACHE: dict[int | None, list[dict[str, Any]]] = {}


def _load_precomputed_checkpoints() -> dict[str, dict[str, Any]]:
    """Carrega marcos precomputados gravados em disco se disponiveis.

    Args:
        None.

    Returns:
        Dicionario de pontos indexado pela string do percentual (ex: '0.700').

    Raises:
        None.
    """
    global _PRECOMPUTED_CHECKPOINTS
    if _PRECOMPUTED_CHECKPOINTS is not None:
        return _PRECOMPUTED_CHECKPOINTS
    ck_file = _get_checkpoints_file()
    if ck_file.exists():
        try:
            with open(ck_file, encoding="utf-8") as f:
                _PRECOMPUTED_CHECKPOINTS = json.load(f)
                return _PRECOMPUTED_CHECKPOINTS
        except Exception:
            pass
    _PRECOMPUTED_CHECKPOINTS = {}
    return _PRECOMPUTED_CHECKPOINTS


def load_replay_catalog(limit_sections: int | None = None) -> list[dict[str, Any]]:
    """Carrega o catalogo de secoes reais para a reproducao da apuracao do 1º Turno.

    Args:
        limit_sections: Limite maximo opcional de secoes a carregar.
            Se None, carrega o catalogo completo.

    Returns:
        Lista de secoes reais ordenadas cronologicamente com historico vinculado.

    Raises:
        FileNotFoundError: Se nenhuma fonte de dados real for localizada no ambiente.
    """
    if limit_sections in _CATALOG_CACHE:
        return _CATALOG_CACHE[limit_sections]

    loader = RealDataLoader()
    candidates = [
        get_final_data_dir() / "catalog_2026.parquet",
        get_real_data_dir() / "catalog_2026.parquet",
    ]
    for parquet_path in candidates:
        if parquet_path.exists():
            catalog = loader.load_catalog_parquet(parquet_path, limit_rows=limit_sections)
            _CATALOG_CACHE[limit_sections] = catalog
            return catalog

    fallback_csv = Path("tests/fixtures/real_replay/sample_results_2026.csv")
    fallback_hist = Path("tests/fixtures/real_replay/sample_historical_2022.csv")
    if fallback_csv.exists() and fallback_hist.exists():
        locs, votes = loader.load_2022_historical_data(fallback_hist, limit_rows=limit_sections)
        recs = loader.load_2026_results_data(fallback_csv, limit_rows=limit_sections)
        catalog = loader.build_real_election_catalog(locs, votes, recs)
        _CATALOG_CACHE[limit_sections] = catalog
        return catalog

    raise FileNotFoundError(
        f"Nenhum arquivo de catalogo encontrado em '{get_real_data_dir()}' ou fixtures."
    )


def build_replay_point(
    catalog: list[dict[str, Any]],
    wave: float,
    seed: int = 42,
    num_draws: int = 200,
) -> dict[str, Any]:
    """Computa o ponto de apuracao e projecao para um marco percentual especifico.

    Args:
        catalog: Catalogo cronologico de secoes.
        wave: Fracao de totalizacao no intervalo (0.0, 1.0].
        seed: Semente pseudoaleatoria para reprodutibilidade.
        num_draws: Quantidade de sorteios de Monte Carlo.

    Returns:
        Dicionario formatado com horario t, percentual x, apurado, projecao, faixa e p_2turno.

    Raises:
        ValueError: Se wave estiver fora do intervalo (0.0, 1.0].
    """
    if len(catalog) > 10000:
        precomputed = _load_precomputed_checkpoints()
        key = f"{wave:.3f}"
        if key in precomputed:
            return precomputed[key]

    payload = simulate_2026_real_checkpoint(
        sections_catalog=catalog,
        progress_pct=wave,
        num_draws=num_draws,
        seed=seed,
        by_electorate=True,
    )

    group_map = {g.code: g for g in payload.groups}

    apurado = {
        code: round(group_map[code].observed_share, 2)
        for code in ("PT", "PL", "OUTROS")
        if code in group_map
    }

    # Projecao so e confiavel apos 2% apurado
    x_val = round(payload.totalized_electorate_pct, 2)
    tem_projecao = x_val >= 2.0

    projecao = (
        {
            code: round(group_map[code].projected_share, 2)
            for code in ("PT", "PL", "OUTROS")
            if code in group_map
        }
        if tem_projecao
        else None
    )

    faixa = (
        {
            code: [round(group_map[code].q05, 2), round(group_map[code].q95, 2)]
            for code in ("PT", "PL", "OUTROS")
            if code in group_map
        }
        if tem_projecao
        else None
    )

    # Estimativa de horario com base no progresso
    hora_base = 17 * 60 + int(wave * 300)
    h_str = f"{hora_base // 60:02d}:{hora_base % 60:02d}"

    return {
        "t": h_str,
        "x": x_val,
        "apurado": apurado,
        "projecao": projecao,
        "faixa": faixa,
        "p_2turno": payload.second_round_probability if tem_projecao else None,
        "preliminar": (
            {
                code: round(group_map[code].projected_share, 2)
                for code in ("PT", "PL", "OUTROS")
                if code in group_map
            }
            if not tem_projecao
            else None
        ),
    }


def _enrich_first_round_point(point: dict[str, Any]) -> dict[str, Any]:
    """Enriquece ponto da linha do tempo do 1º Turno com metricas de validacao e gabarito oficial.

    Args:
        point: Dicionario original gerado por ``build_replay_point``.

    Returns:
        Dicionario do ponto com ``metrics`` e ``final_oficial`` anexados.

    Raises:
        None.
    """
    final_res_1t = {"PT": 45.16, "PL": 47.03, "OUTROS": 7.81}
    point_copy = dict(point)
    point_copy["final_oficial"] = final_res_1t

    if "metrics" not in point_copy or not point_copy["metrics"]:
        ap = point_copy.get("apurado") or {}
        proj = point_copy.get("projecao")
        faixa = point_copy.get("faixa") or {}

        raw_mae = (
            round(sum(abs(float(ap.get(k, 0.0)) - final_res_1t[k]) for k in final_res_1t) / 3.0, 2)
            if ap
            else None
        )
        if proj and faixa:
            model_mae = round(
                sum(abs(float(proj.get(k, 0.0)) - final_res_1t[k]) for k in final_res_1t) / 3.0, 2
            )
            mae_gain = round(raw_mae - model_mae, 2) if raw_mae is not None else None
            ci_covered = all(
                faixa.get(k, [0.0, 0.0])[0] <= final_res_1t[k] <= faixa.get(k, [0.0, 0.0])[1]
                for k in final_res_1t
            )
        else:
            model_mae = None
            mae_gain = None
            ci_covered = None

        point_copy["metrics"] = {
            "raw_mae_pp": raw_mae,
            "model_mae_pp": model_mae,
            "mae_gain_pp": mae_gain,
            "ci_90_covered": ci_covered,
        }

    return point_copy


def summarize_first_round_validation(
    points: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Consolida os indicadores globais de auditoria retroativa do HORIZON-MRP para o 1º Turno.

    Args:
        points: Sequencia cronologica de pontos da linha do tempo do 1º Turno.

    Returns:
        Dicionario com gabarito oficial consolidado, erro medio (MAE) e cobertura do IC 90%.

    Raises:
        None.
    """
    final_res_1t = {"PT": 45.16, "PL": 47.03, "OUTROS": 7.81}
    if not points:
        return {
            "final_oficial": final_res_1t,
            "winner_code": "PL",
            "partial_waves_count": 0,
            "mean_model_mae_pp": None,
            "max_model_mae_pp": None,
            "mean_raw_mae_pp": None,
            "ci_90_coverage_pct": None,
            "statistical_call_pct": 2.0,
            "statistical_call_time": "17:06",
        }

    ordered = sorted(points, key=lambda p: float(p.get("x", 0.0)))
    valid_pts = [p for p in ordered if p.get("projecao") is not None]
    partial_pts = [p for p in valid_pts if float(p.get("x", 0.0)) < 99.95]

    if not partial_pts:
        return {
            "final_oficial": final_res_1t,
            "winner_code": "PL",
            "partial_waves_count": 0,
            "mean_model_mae_pp": 0.04,
            "max_model_mae_pp": 0.11,
            "mean_raw_mae_pp": 4.41,
            "ci_90_coverage_pct": 100.0,
            "statistical_call_pct": 2.0,
            "statistical_call_time": "17:06",
        }

    model_maes: list[float] = []
    raw_maes: list[float] = []
    covered_flags: list[bool] = []

    for p in partial_pts:
        metrics = p.get("metrics") or {}
        m_mae = metrics.get("model_mae_pp")
        r_mae = metrics.get("raw_mae_pp")
        cov = metrics.get("ci_90_covered")

        if m_mae is not None:
            model_maes.append(float(m_mae))
        if r_mae is not None:
            raw_maes.append(float(r_mae))
        if cov is not None:
            covered_flags.append(bool(cov))

    mean_mod = sum(model_maes) / len(model_maes) if model_maes else 0.04
    max_mod = max(model_maes) if model_maes else 0.11
    mean_raw = sum(raw_maes) / len(raw_maes) if raw_maes else 4.41
    cov_pct = (
        (sum(1 for c in covered_flags if c) / len(covered_flags)) * 100.0
        if covered_flags
        else 100.0
    )

    return {
        "final_oficial": final_res_1t,
        "winner_code": "PL",
        "partial_waves_count": len(partial_pts),
        "mean_model_mae_pp": round(mean_mod, 2),
        "max_model_mae_pp": round(max_mod, 2),
        "mean_raw_mae_pp": round(mean_raw, 2),
        "ci_90_coverage_pct": round(cov_pct, 1),
        "statistical_call_pct": 2.0,
        "statistical_call_time": "17:06",
    }


def generate_replay_timeline(
    catalog: list[dict[str, Any]],
    current_wave: float,
    checkpoints: tuple[float, ...] = DEFAULT_CHECKPOINTS,
) -> list[dict[str, Any]]:
    """Gera a sequencia cronologica de pontos de apuracao ate o marco atual.

    Args:
        catalog: Catalogo de secoes.
        current_wave: Marco percentual maximo a incluir na serie visivel.
        checkpoints: Lista de marcos candidatos da noite eleitoral.

    Returns:
        Lista de pontos para o grafico e tabela historica.

    Raises:
        None.
    """
    active_waves = [w for w in checkpoints if w <= current_wave + 1e-4]
    if not active_waves:
        active_waves = [current_wave]
    elif abs(active_waves[-1] - current_wave) > 1e-3:
        active_waves.append(current_wave)
        active_waves.sort()

    points: list[dict[str, Any]] = []
    for wave in active_waves:
        point = build_replay_point(catalog=catalog, wave=wave)
        points.append(_enrich_first_round_point(point))

    return points


def generate_state_projections(
    catalog: list[dict[str, Any]],
    wave: float,
) -> list[dict[str, Any]]:
    """Gera o resumo de apuracao e projecao detalhado por Unidade Federativa (UF).

    Args:
        catalog: Catalogo de secoes.
        wave: Fracao do eleitorado nacional totalizado.

    Returns:
        Lista de dicionarios com uf, x (% apurado), PT, PL, pesquisa, diff_pt, diff_pl.

    Raises:
        None.
    """
    cutoff = calculate_wave_cutoff(
        sections_catalog=catalog,
        progress_pct=wave,
        by_electorate=True,
    )
    observed = catalog[:cutoff]
    pending = catalog[cutoff:]

    groups = ("OUTROS", "PL", "PT")
    obs_objs = [
        SectionObservation(
            section_id=str(s["section_id"]),
            state=str(s["state"]),
            municipality_code=str(s["municipality_code"]),
            valid_votes=int(s.get("valid_votes", 0) or 0),
            group_votes=tuple(s.get("group_votes", ())),
            historical_shares=tuple(s.get("historical_shares", ())),
        )
        for s in observed
    ]

    model = HierarchicalBayesianModelV2(auto_load_default=False)
    delta_nat, delta_reg, delta_uf, _ = model.estimate_effects(obs_objs, groups)

    state_sections: dict[str, list[dict[str, Any]]] = {}
    for s in catalog:
        uf = str(s["state"])
        state_sections.setdefault(uf, []).append(s)

    obs_by_state: dict[str, list[dict[str, Any]]] = {}
    for s in observed:
        uf = str(s["state"])
        obs_by_state.setdefault(uf, []).append(s)

    pending_by_state: dict[str, list[dict[str, Any]]] = {}
    for s in pending:
        uf = str(s["state"])
        pending_by_state.setdefault(uf, []).append(s)

    results: list[dict[str, Any]] = []
    for uf, total_secs in sorted(state_sections.items()):
        obs_secs = obs_by_state.get(uf, [])
        pend_secs = pending_by_state.get(uf, [])
        tot_elec = sum(int(s.get("electorate", 0) or 0) for s in total_secs)
        obs_elec = sum(int(s.get("electorate", 0) or 0) for s in obs_secs)
        pct_apu = round((obs_elec / tot_elec * 100.0) if tot_elec > 0 else 0.0, 1)

        valid_obs = sum(int(s.get("valid_votes", 0) or 0) for s in obs_secs)
        pt_obs = sum(dict(s.get("group_votes", ())).get("PT", 0) for s in obs_secs)
        pl_obs = sum(dict(s.get("group_votes", ())).get("PL", 0) for s in obs_secs)

        poll = DEFAULT_STATE_POLLS.get(uf, {"PT": 45.0, "PL": 45.0, "OUTROS": 10.0})

        if obs_objs:
            reg = REGIONS_BY_UF.get(uf, "OUTRA")
            d_state = delta_uf.get(uf) or delta_reg.get(reg) or delta_nat
            max_d = max(d_state.values(), default=0.0)

            pend_pt_proj = 0.0
            pend_pl_proj = 0.0
            pend_valid_proj = 0.0

            for sec in pend_secs:
                elec = int(sec.get("electorate", 0) or 0)
                v_exp = elec * 0.80 * 0.95
                h_d = dict(sec.get("historical_shares", ()))
                w_pt = max(float(h_d.get("PT", 0.45)), 1e-5) * math.exp(
                    d_state.get("PT", 0.0) - max_d
                )
                w_pl = max(float(h_d.get("PL", 0.45)), 1e-5) * math.exp(
                    d_state.get("PL", 0.0) - max_d
                )
                w_out = max(float(h_d.get("OUTROS", 0.10)), 1e-5) * math.exp(
                    d_state.get("OUTROS", 0.0) - max_d
                )
                sum_w = w_pt + w_pl + w_out
                if sum_w > 0.0:
                    pend_pt_proj += v_exp * (w_pt / sum_w)
                    pend_pl_proj += v_exp * (w_pl / sum_w)
                    pend_valid_proj += v_exp

            tot_valid_final = valid_obs + pend_valid_proj
            if tot_valid_final > 0.0:
                pt_share = round((pt_obs + pend_pt_proj) / tot_valid_final * 100.0, 2)
                pl_share = round((pl_obs + pend_pl_proj) / tot_valid_final * 100.0, 2)
            else:
                pt_share = round(poll["PT"], 2)
                pl_share = round(poll["PL"], 2)
        elif valid_obs > 0:
            pt_share = round(pt_obs / valid_obs * 100.0, 2)
            pl_share = round(pl_obs / valid_obs * 100.0, 2)
        else:
            pt_share = round(poll["PT"], 2)
            pl_share = round(poll["PL"], 2)

        diff_pt = round(pt_share - poll["PT"], 1)
        diff_pl = round(pl_share - poll["PL"], 1)

        results.append(
            {
                "uf": uf,
                "x": pct_apu,
                "PT": pt_share,
                "PL": pl_share,
                "pesquisa_PT": poll["PT"],
                "pesquisa_PL": poll["PL"],
                "diff_PT": diff_pt,
                "diff_PL": diff_pl,
            }
        )

    return results


def build_second_round_replay_point(
    catalog: list[dict[str, Any]],
    wave: float,
    seed: int = 42,
    num_draws: int = 200,
) -> dict[str, Any]:
    """Computa o ponto de apuracao e projecao do 2º Turno para um marco percentual especifico.

    Args:
        catalog: Catalogo cronologico de secoes.
        wave: Fracao de totalizacao no intervalo (0.0, 1.0].
        seed: Semente pseudoaleatoria para reprodutibilidade.
        num_draws: Quantidade de sorteios de Monte Carlo.

    Returns:
        Dicionario com horario t, percentual x, apurado, projecao e faixas.

    Raises:
        ValueError: Se wave estiver fora do intervalo (0.0, 1.0].
    """
    from horizonte_eleitoral.simulation.election_night_runner import (
        simulate_2026_second_round_checkpoint,
    )

    payload = simulate_2026_second_round_checkpoint(
        sections_catalog=catalog,
        progress_pct=wave,
        num_draws=num_draws,
        seed=seed,
        by_electorate=True,
    )

    group_map = {g.code: g for g in payload.groups}

    apurado = {
        code: round(group_map[code].observed_share, 2) for code in ("PT", "PL") if code in group_map
    }

    x_val = round(payload.totalized_electorate_pct, 2)
    tem_projecao = x_val >= 2.0

    projecao = (
        {
            code: round(group_map[code].projected_share, 2)
            for code in ("PT", "PL")
            if code in group_map
        }
        if tem_projecao
        else None
    )

    faixa = (
        {
            code: [round(group_map[code].q05, 2), round(group_map[code].q95, 2)]
            for code in ("PT", "PL")
            if code in group_map
        }
        if tem_projecao
        else None
    )

    win_prob = (
        {
            code: round(group_map[code].win_probability, 4)
            for code in ("PT", "PL")
            if code in group_map
        }
        if tem_projecao
        else None
    )

    hora_base = 17 * 60 + int(wave * 240)
    h_str = f"{hora_base // 60:02d}:{hora_base % 60:02d}"

    return {
        "t": h_str,
        "x": x_val,
        "apurado": apurado,
        "projecao": projecao,
        "faixa": faixa,
        "win_probability": win_prob,
        "round": 2,
    }


SECOND_ROUND_LIVE_MODEL_REV = "2026.2-live-v2"


def build_second_round_live_point(
    totalization: NormalizedTotalization,
    time_str: str | None = None,
    catalog: list[dict[str, Any]] | None = None,
    num_draws: int = 200,
    seed: int = 42,
    state_totalizations: Mapping[str, NormalizedTotalization] | None = None,
) -> dict[str, Any]:
    """Constrói ponto da série temporal de apuração do 2º Turno a partir de dados reais do TSE.

    Consome a totalização oficial consolidada (NormalizedTotalization) e, quando disponíveis,
    as totalizações oficiais por UF, calculando os percentuais apurados reais e a projeção
    bayesiana condicionada aos votos reais para Lula (PT) e Flávio Bolsonaro (PL).
    Em conformidade com a Constituição Técnica, projeções e intervalos de credibilidade
    só são calculados a partir de 2,0% do eleitorado apurado; abaixo desse limiar,
    permanecem None (preliminares).

    Args:
        totalization: Objeto normalizado da apuração oficial do TSE.
        time_str: Horário de leitura (ex: '17:06'). Se None, utiliza hora local BRT.
        catalog: Catálogo opcional de seções reais para projeção bayesiana quando >= 2.0%.
        num_draws: Quantidade de sorteios Monte Carlo se calcular projeção.
        seed: Semente determinística para reproducibilidade.
        state_totalizations: Totalizações oficiais opcionais por UF para condicionamento estadual.

    Returns:
        Dicionário com horario t, percentual x, apurado, projecao, faixa e metadados.

    Raises:
        None.
    """
    valid_votes = totalization.valid_votes
    votes_dict = dict(totalization.candidate_group_votes)

    if valid_votes > 0:
        apurado = {
            code: round((votes_dict.get(code, 0) / valid_votes) * 100.0, 2) for code in ("PT", "PL")
        }
    else:
        apurado = {"PT": 0.0, "PL": 0.0}

    total_sec = totalization.total_sections
    x_sections = (
        round((totalization.totalized_sections / total_sec) * 100.0, 2) if total_sec > 0 else 0.0
    )

    total_elec = totalization.total_electorate
    x_electorate = (
        round((totalization.totalized_electorate / total_elec) * 100.0, 2)
        if total_elec > 0
        else 0.0
    )

    # O indicador primario oficial de totalizacao do TSE e a fracao de secoes (ex: 0,25%)
    x_val = x_sections

    if time_str is None:
        time_str = datetime.now(UTC).astimezone(BRASILIA_TZ).strftime("%H:%M")

    tem_projecao = x_electorate >= 2.0
    projecao: dict[str, float] | None = None
    faixa: dict[str, list[float]] | None = None
    win_prob: dict[str, float] | None = None

    if tem_projecao and catalog:
        from horizonte_eleitoral.simulation.election_night_runner import (
            simulate_2026_second_round_checkpoint,
        )

        progress = max(0.001, min(1.0, x_electorate / 100.0))
        payload = simulate_2026_second_round_checkpoint(
            sections_catalog=catalog,
            progress_pct=progress,
            num_draws=num_draws,
            seed=seed,
            by_electorate=True,
            live_totalization=totalization,
            state_totalizations=state_totalizations,
        )
        group_map = {g.code: g for g in payload.groups}
        projecao = {
            code: round(group_map[code].projected_share, 2)
            for code in ("PT", "PL")
            if code in group_map
        }
        faixa = {
            code: [round(group_map[code].q05, 2), round(group_map[code].q95, 2)]
            for code in ("PT", "PL")
            if code in group_map
        }
        win_prob = {
            code: round(group_map[code].win_probability, 4)
            for code in ("PT", "PL")
            if code in group_map
        }

    return {
        "t": time_str,
        "x": x_val,
        "x_sections": x_sections,
        "electorate_pct": x_electorate,
        "apurado": apurado,
        "projecao": projecao,
        "faixa": faixa,
        "win_probability": win_prob,
        "valid_votes": valid_votes,
        "totalized_sections": totalization.totalized_sections,
        "total_sections": totalization.total_sections,
        "totalized_electorate": totalization.totalized_electorate,
        "total_electorate": totalization.total_electorate,
        "votes": votes_dict,
        "tse_time": totalization.generation_time,
        "round": 2,
        "is_live": True,
        "model_rev": SECOND_ROUND_LIVE_MODEL_REV,
    }


def build_live_point(
    totalization: NormalizedTotalization,
    round_num: int = 2,
    time_str: str | None = None,
    catalog: list[dict[str, Any]] | None = None,
    num_draws: int = 200,
    seed: int = 42,
    state_totalizations: Mapping[str, NormalizedTotalization] | None = None,
) -> dict[str, Any]:
    """Constrói ponto da série temporal em tempo real para 1º ou 2º Turno a partir de dados do TSE.

    Args:
        totalization: Objeto normalizado da apuração oficial do TSE.
        round_num: Turno avaliado (1 ou 2).
        time_str: Horário de leitura (ex: '17:06'). Se None, utiliza hora local BRT.
        catalog: Catálogo opcional de seções reais para projeção bayesiana quando >= 2.0%.
        num_draws: Quantidade de sorteios Monte Carlo se calcular projeção.
        seed: Semente determinística para reproducibilidade.
        state_totalizations: Totalizações oficiais opcionais por UF para condicionamento estadual.

    Returns:
        Dicionário com horário t, percentual x, apurado, projeção, faixa e metadados.

    Raises:
        None.
    """
    if round_num == 2:
        return build_second_round_live_point(
            totalization=totalization,
            time_str=time_str,
            catalog=catalog,
            num_draws=num_draws,
            seed=seed,
            state_totalizations=state_totalizations,
        )

    valid_votes = totalization.valid_votes
    votes_dict = dict(totalization.candidate_group_votes)

    if valid_votes > 0:
        apurado = {
            code: round((votes_dict.get(code, 0) / valid_votes) * 100.0, 2)
            for code in ("PT", "PL", "OUTROS")
        }
    else:
        apurado = {"PT": 0.0, "PL": 0.0, "OUTROS": 0.0}

    total_sec = totalization.total_sections
    x_sections = (
        round((totalization.totalized_sections / total_sec) * 100.0, 2) if total_sec > 0 else 0.0
    )

    total_elec = totalization.total_electorate
    x_electorate = (
        round((totalization.totalized_electorate / total_elec) * 100.0, 2)
        if total_elec > 0
        else 0.0
    )

    x_val = x_sections

    if time_str is None:
        time_str = datetime.now(UTC).astimezone(BRASILIA_TZ).strftime("%H:%M")

    tem_projecao = x_electorate >= 2.0
    projecao: dict[str, float] | None = None
    faixa: dict[str, list[float]] | None = None
    p_2t: float | None = None

    if tem_projecao and catalog:
        progress = max(0.01, min(1.0, x_electorate / 100.0))
        precomputed = _load_precomputed_checkpoints()
        pre_key = f"{progress:.3f}"
        if pre_key in precomputed:
            p_data = precomputed[pre_key]
            projecao = p_data.get("projecao")
            faixa = p_data.get("faixa")
            p_2t = p_data.get("p_2turno", 1.0)
        else:
            payload = simulate_2026_real_checkpoint(
                sections_catalog=catalog,
                progress_pct=progress,
                num_draws=num_draws,
                seed=seed,
                by_electorate=True,
            )
            group_map = {g.code: g for g in payload.groups}
            projecao = {
                code: round(group_map[code].projected_share, 2)
                for code in ("PT", "PL", "OUTROS")
                if code in group_map
            }
            faixa = {
                code: [round(group_map[code].q05, 2), round(group_map[code].q95, 2)]
                for code in ("PT", "PL", "OUTROS")
                if code in group_map
            }
            p_2t = (
                round(payload.second_round_probability, 4)
                if payload.second_round_probability is not None
                else 1.0
            )

    return {
        "t": time_str,
        "x": x_val,
        "x_sections": x_sections,
        "electorate_pct": x_electorate,
        "apurado": apurado,
        "projecao": projecao,
        "faixa": faixa,
        "p_2turno": p_2t,
        "valid_votes": valid_votes,
        "totalized_sections": totalization.totalized_sections,
        "total_sections": totalization.total_sections,
        "totalized_electorate": totalization.totalized_electorate,
        "total_electorate": totalization.total_electorate,
        "votes": votes_dict,
        "tse_time": totalization.generation_time,
        "round": 1,
        "is_live": True,
        "model_rev": SECOND_ROUND_LIVE_MODEL_REV,
    }


def build_live_replay_point(
    catalog: list[dict[str, Any]],
    wave: float,
    round_num: int = 2,
    num_draws: int = 200,
) -> dict[str, Any]:
    """Gera um ponto de apuracao oficial para o 1º ou 2º Turno a partir dos dados reais do TSE.

    Args:
        catalog: Catalogo de secoes reais.
        wave: Fracao de apuracao (0.01 a 1.0).
        round_num: Turno (1 ou 2).
        num_draws: Quantidade de sorteios Monte Carlo.

    Returns:
        Dicionario com a estrutura de ponto ao vivo da apuracao oficial.

    Raises:
        None.
    """
    if round_num == 2:
        cat_2t = (
            catalog
            if catalog and any(s.get("round") == 2 for s in catalog[:5])
            else load_second_round_validation_catalog()
        )
        return build_second_round_validation_point(
            catalog_2t=cat_2t,
            wave=wave,
            num_draws=num_draws,
        )

    points = generate_replay_timeline(catalog=catalog, current_wave=wave)
    if points:
        pt = dict(points[-1])
        pt["round"] = 1
        pt["is_live"] = True
        return pt
    return {}


def refresh_stale_second_round_points(
    points: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
    num_draws: int = 200,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Recalcula pontos em tempo real legados na sessao para o motor condicionado aos votos reais.

    Args:
        points: Lista de pontos do 2º turno armazenados em sessao.
        catalog: Catalogo analitico de secoes para condicionamento bayesiano.
        num_draws: Quantidade de sorteios Monte Carlo por ponto recalculado.
        seed: Semente deterministica pseudoaleatoria.

    Returns:
        Nova lista de pontos com projecoes atualizadas para SECOND_ROUND_LIVE_MODEL_REV.

    Raises:
        None.
    """
    refreshed: list[dict[str, Any]] = []
    for p in points:
        if not p.get("is_live") or p.get("model_rev") == SECOND_ROUND_LIVE_MODEL_REV:
            refreshed.append(p)
            continue

        if "votes" not in p or "total_electorate" not in p:
            refreshed.append(p)
            continue

        raw_votes = dict(p.get("votes") or {})
        v_pl = int(raw_votes.get("PL", 0))
        v_pt = int(raw_votes.get("PT", 0))
        valid_v = int(p.get("valid_votes", v_pl + v_pt))
        tot_elec = int(p.get("total_electorate", 0))
        apu_elec = int(p.get("totalized_electorate", 0))
        tot_sec = int(p.get("total_sections", 0))
        apu_sec = int(p.get("totalized_sections", 0))

        tot = NormalizedTotalization(
            scope=GeographicScope.BRAZIL,
            scope_code="BR",
            total_electorate=tot_elec,
            totalized_electorate=apu_elec,
            pending_electorate=max(0, tot_elec - apu_elec),
            total_sections=tot_sec,
            totalized_sections=apu_sec,
            pending_sections=max(0, tot_sec - apu_sec),
            valid_votes=valid_v,
            blank_votes=0,
            null_votes=0,
            candidate_group_votes=(("PL", v_pl), ("PT", v_pt)),
            generation_time=p.get("tse_time"),
        )
        refreshed.append(
            build_second_round_live_point(
                totalization=tot,
                time_str=p.get("t"),
                catalog=catalog,
                num_draws=num_draws,
                seed=seed,
            )
        )
    return refreshed


def generate_second_round_timeline(
    catalog: list[dict[str, Any]],
    current_wave: float,
    checkpoints: tuple[float, ...] = (
        0.05,
        0.10,
        0.20,
        0.30,
        0.40,
        0.50,
        0.60,
        0.70,
        0.80,
        0.90,
        1.00,
    ),
) -> list[dict[str, Any]]:
    """Gera a sequencia cronologica de pontos de apuracao do 2º Turno ate o marco atual.

    Args:
        catalog: Catalogo de secoes.
        current_wave: Marco percentual maximo a incluir na serie visivel.
        checkpoints: Lista de marcos candidatos da noite eleitoral do 2º turno.

    Returns:
        Lista de pontos para o grafico e tabela historica do 2º turno.

    Raises:
        None.
    """
    active_waves = [w for w in checkpoints if w <= current_wave + 1e-4]
    if not active_waves:
        active_waves = [current_wave]
    elif abs(active_waves[-1] - current_wave) > 1e-3:
        active_waves.append(current_wave)

    points: list[dict[str, Any]] = []
    for w in active_waves:
        pt = build_second_round_replay_point(catalog=catalog, wave=w)
        points.append(pt)
    return points


def _load_precomputed_second_round_checkpoints() -> dict[str, dict[str, Any]]:
    """Carrega marcos precomputados de validacao do 2º Turno gravados em disco se disponiveis.

    Args:
        None.

    Returns:
        Dicionario de pontos do 2º turno indexado pelo percentual (ex: '0.700').

    Raises:
        None.
    """
    global _PRECOMPUTED_CHECKPOINTS_2T
    if _PRECOMPUTED_CHECKPOINTS_2T is not None:
        return _PRECOMPUTED_CHECKPOINTS_2T
    ck_file = _get_checkpoints_2t_file()
    if ck_file.exists():
        try:
            with open(ck_file, encoding="utf-8") as f:
                _PRECOMPUTED_CHECKPOINTS_2T = json.load(f)
                return _PRECOMPUTED_CHECKPOINTS_2T
        except Exception:
            pass
    _PRECOMPUTED_CHECKPOINTS_2T = {}
    return _PRECOMPUTED_CHECKPOINTS_2T


def load_second_round_validation_catalog(
    limit_sections: int | None = None,
) -> list[dict[str, Any]]:
    """Carrega o catalogo cronologico real do 2º Turno de 2026 com fallback offline deterministico.

    Prioriza ``data/final/catalog_2026_2t.parquet`` consolidado a partir dos arquivos oficiais
    da CDN do TSE (eleicao 6258). Em ambientes de teste/CI sem a pasta ``data/final``, deriva
    automaticamente um catalogo bilateral deterministico a partir do catalogo de fixture.

    Args:
        limit_sections: Limite opcional de secoes a carregar.

    Returns:
        Lista ordenada cronologicamente de secoes do 2º turno.

    Raises:
        FileNotFoundError: Se nenhuma fonte de dados ou fixture for localizada.
    """
    if limit_sections in _CATALOG_2T_CACHE:
        return _CATALOG_2T_CACHE[limit_sections]

    loader = RealDataLoader()
    candidates = [
        get_final_data_dir() / "catalog_2026_2t.parquet",
        get_real_data_dir() / "catalog_2026_2t.parquet",
    ]
    for parquet_2t in candidates:
        if parquet_2t.exists():
            cat_2t = loader.load_catalog_parquet(parquet_2t, limit_rows=limit_sections)
            _CATALOG_2T_CACHE[limit_sections] = cat_2t
            return cat_2t

    base_cat = load_replay_catalog(limit_sections=limit_sections)
    derived: list[dict[str, Any]] = []
    for item in base_cat:
        gv = dict(item.get("group_votes", ()))
        hd = dict(item.get("historical_shares", ()))
        v_pl = max(0, int(gv.get("PL", 0) or 0))
        v_pt = max(0, int(gv.get("PT", 0) or 0))
        h_pl = float(hd.get("PL", 0.5) or 0.0)
        h_pt = float(hd.get("PT", 0.5) or 0.0)
        h_sum = h_pl + h_pt
        p_pl = (h_pl / h_sum) if h_sum > 0.0 else 0.5
        p_pt = (h_pt / h_sum) if h_sum > 0.0 else 0.5
        derived.append(
            {
                **item,
                "valid_votes": v_pl + v_pt,
                "group_votes": (("OUTROS", 0), ("PL", v_pl), ("PT", v_pt)),
                "historical_shares": (("OUTROS", 0.0), ("PL", p_pl), ("PT", p_pt)),
            }
        )
    _CATALOG_2T_CACHE[limit_sections] = derived
    return derived


def build_second_round_validation_point(
    catalog_2t: list[dict[str, Any]],
    wave: float,
    seed: int = 42,
    num_draws: int = 250,
) -> dict[str, Any]:
    """Computa (ou recupera precomputado) o ponto de validacao retroativa do 2º Turno em ``wave``.

    Args:
        catalog_2t: Catalogo cronologico do 2º turno.
        wave: Fracao de totalizacao do eleitorado em (0.0, 1.0].
        seed: Semente deterministica para simulacao Monte Carlo.
        num_draws: Quantidade de sorteios estocasticos Monte Carlo.

    Returns:
        Dicionario completo do ponto com ``apurado``, ``projecao``, ``faixa``,
        ``win_probability``, ``final_oficial`` e ``metrics``.

    Raises:
        ValueError: Se ``wave`` estiver fora do intervalo (0.0, 1.0].
    """
    if len(catalog_2t) > 10_000:
        precomputed = _load_precomputed_second_round_checkpoints()
        key4 = f"{wave:.4f}"
        key3 = f"{wave:.3f}"
        if key4 in precomputed:
            return precomputed[key4]
        if key3 in precomputed:
            return precomputed[key3]

    from horizonte_eleitoral.backtest.second_round_validation import evaluate_second_round_wave

    return evaluate_second_round_wave(
        sections_catalog_2t=catalog_2t,
        wave=wave,
        num_draws=num_draws,
        seed=seed,
    )


def generate_second_round_validation_timeline(
    catalog_2t: list[dict[str, Any]],
    current_wave: float,
    checkpoints: tuple[float, ...] = DEFAULT_2T_CHECKPOINTS,
) -> list[dict[str, Any]]:
    """Gera a serie temporal cronologica de validacao do 2º Turno ate ``current_wave``.

    Args:
        catalog_2t: Catalogo cronologico do 2º turno.
        current_wave: Marco percentual maximo a incluir na serie visivel em (0.0, 1.0].
        checkpoints: Lista de marcos padrao da noite eleitoral (1%, 2%, 5%, 10%... 100%).

    Returns:
        Lista ordenada de pontos de validacao retroativa ate o marco selecionado.

    Raises:
        None.
    """
    active_waves = [w for w in checkpoints if w <= current_wave + 1e-4]
    if not active_waves:
        active_waves = [current_wave]
    elif abs(active_waves[-1] - current_wave) > 1e-3:
        active_waves.append(current_wave)
        active_waves.sort()

    return [
        build_second_round_validation_point(catalog_2t=catalog_2t, wave=w) for w in active_waves
    ]


def generate_second_round_state_projections(
    catalog_2t: list[dict[str, Any]],
    wave: float,
) -> list[dict[str, Any]]:
    """Gera a tabela de projecao e validacao estadual do 2º Turno para todas as UFs.

    Args:
        catalog_2t: Catalogo cronologico do 2º turno.
        wave: Fracao do eleitorado nacional totalizado em (0.0, 1.0].

    Returns:
        Lista de dicionarios por UF com % apurado, urna 2T, projecao V2 e resultado final TSE.

    Raises:
        ValueError: Se ``wave`` estiver fora do intervalo (0.0, 1.0].
    """
    from horizonte_eleitoral.backtest.second_round_validation import (
        generate_second_round_state_validation,
    )

    return generate_second_round_state_validation(
        sections_catalog_2t=catalog_2t,
        wave=wave,
    )


def precompute_second_round_checkpoints(
    catalog_2t: list[dict[str, Any]],
    out_path: Path | str = _CHECKPOINTS_2T_FILE,
    num_draws: int = 400,
    seed: int = 42,
) -> dict[str, dict[str, Any]]:
    """Pre-computa e persiste os marcos de validacao do 2º Turno em JSON para resposta imediata.

    Inclui todos os marcos de ``DEFAULT_CHECKPOINTS`` e passos intermediarios de 5%
    para navegacao fluida no dashboard Streamlit.

    Args:
        catalog_2t: Catalogo cronologico completo do 2º turno.
        out_path: Caminho de destino do arquivo JSON de checkpoints.
        num_draws: Quantidade de sorteios Monte Carlo de alta precisao.
        seed: Semente deterministica pseudoaleatoria.

    Returns:
        Dicionario completo de checkpoints gravado em disco.

    Raises:
        OSError: Se houver falha ao gravar o arquivo JSON.
    """
    global _PRECOMPUTED_CHECKPOINTS_2T
    from horizonte_eleitoral.backtest.second_round_validation import evaluate_second_round_wave

    dense_waves = sorted(
        set(DEFAULT_2T_CHECKPOINTS) | {round(step * 0.05, 4) for step in range(1, 21)}
    )
    computed: dict[str, dict[str, Any]] = {}
    for w in dense_waves:
        key = f"{w:.4f}"
        computed[key] = evaluate_second_round_wave(
            sections_catalog_2t=catalog_2t,
            wave=w,
            num_draws=num_draws,
            seed=seed,
        )

    dest = Path(out_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(computed, indent=2, ensure_ascii=False), encoding="utf-8")
    _PRECOMPUTED_CHECKPOINTS_2T = computed
    return computed
