"""Motor de reproducao e geracao de series temporais de apuracao para o dashboard."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from horizonte_eleitoral.ingestion.real_data_loader import RealDataLoader
from horizonte_eleitoral.models.base import SectionObservation
from horizonte_eleitoral.models.hierarchical import REGIONS_BY_UF
from horizonte_eleitoral.models.hierarchical_v2 import HierarchicalBayesianModelV2
from horizonte_eleitoral.simulation.election_night_runner import (
    calculate_wave_cutoff,
    simulate_2026_real_checkpoint,
)

# Lista de marcos padronizados de apuracao para a curva de evolucao
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

_CHECKPOINTS_FILE = Path("data/real/checkpoints_2026.json")
_PRECOMPUTED_CHECKPOINTS: dict[str, dict[str, Any]] | None = None
_CATALOG_CACHE: dict[int | None, list[dict[str, Any]]] = {}


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
    if _CHECKPOINTS_FILE.exists():
        try:
            with open(_CHECKPOINTS_FILE, encoding="utf-8") as f:
                _PRECOMPUTED_CHECKPOINTS = json.load(f)
                return _PRECOMPUTED_CHECKPOINTS
        except Exception:
            pass
    _PRECOMPUTED_CHECKPOINTS = {}
    return _PRECOMPUTED_CHECKPOINTS


def load_replay_catalog(limit_sections: int | None = None) -> list[dict[str, Any]]:
    """Carrega o catalogo de secoes reais para a reproducao da apuracao.

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
    parquet_path = Path("data/real/catalog_2026.parquet")
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

    raise FileNotFoundError("Nenhum arquivo de catalogo encontrado em data/real ou fixtures.")


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
        points.append(point)

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
