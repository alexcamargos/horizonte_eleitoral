"""Ensaio operacional completo de simulacao de noite eleitoral ponta a ponta."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, TypedDict

import numpy as np
from fastapi.testclient import TestClient

from horizonte_eleitoral.api.app import create_app
from horizonte_eleitoral.domain.enums import GeographicScope, MatchQuality
from horizonte_eleitoral.models import HierarchicalBayesianModel
from horizonte_eleitoral.models.base import PendingSection, SectionObservation
from horizonte_eleitoral.normalization.models import (
    NormalizedSectionState,
    NormalizedTotalization,
)
from horizonte_eleitoral.publishing.models import PublishedProjectionPayload
from horizonte_eleitoral.publishing.publisher import AtomicPublisher
from horizonte_eleitoral.reconciliation.reconciler import ReconciliationEngine
from horizonte_eleitoral.simulation.monte_carlo import MonteCarloSimulator


class SyntheticSection(TypedDict):
    """Secao eleitoral sintetica para o ensaio operacional de noite de eleicao."""

    section_id: str
    state: str
    municipality_code: str
    zone: str
    section: str
    electorate: int
    valid_votes: int
    group_votes: tuple[tuple[str, int], ...]
    historical_shares: tuple[tuple[str, float], ...]


def _generate_synthetic_sections(
    num_sections: int, rng: np.random.Generator
) -> list[SyntheticSection]:
    """Gera catalogo de secoes sinteticas distribuidas pelo Brasil para o ensaio eleitoral.

    Args:
        num_sections: Quantidade de secoes eleitorais sinteticas a gerar.
        rng: Gerador de numeros pseudoaleatorios numpy.

    Returns:
        Lista de SyntheticSection com atributos realistas e historico.

    Raises:
        None.
    """
    ufs = ["SP", "RJ", "MG", "BA", "RS", "PR", "PE", "CE"]
    sections_catalog: list[SyntheticSection] = []

    for i in range(num_sections):
        uf = ufs[i % len(ufs)]
        electorate = int(rng.integers(250, 450))
        valid_votes = int(round(electorate * 0.78))
        pt_votes = int(round(valid_votes * rng.uniform(0.35, 0.55)))
        pl_votes = int(round((valid_votes - pt_votes) * rng.uniform(0.70, 0.90)))
        outros_votes = max(0, valid_votes - pt_votes - pl_votes)

        sections_catalog.append(
            {
                "section_id": f"{uf}:0001:{i:04d}",
                "state": uf,
                "municipality_code": f"00{i:03d}",
                "zone": "0001",
                "section": f"{i:04d}",
                "electorate": electorate,
                "valid_votes": valid_votes,
                "group_votes": (("OUTROS", outros_votes), ("PL", pl_votes), ("PT", pt_votes)),
                "historical_shares": (("OUTROS", 0.10), ("PL", 0.45), ("PT", 0.45)),
            }
        )
    return sections_catalog


def _run_wave_pipeline(
    *,
    sections_catalog: list[SyntheticSection],
    cutoff: int,
    reconciler: ReconciliationEngine,
    model: HierarchicalBayesianModel,
    simulator: MonteCarloSimulator,
    publisher: AtomicPublisher,
    api_client: TestClient,
    observed_at: datetime | None = None,
    groups: tuple[str, ...] = ("OUTROS", "PL", "PT"),
    round_num: int = 1,
) -> PublishedProjectionPayload:
    """Executa o pipeline completo de uma onda de apuracao.


    Args:
        sections_catalog: Catalogo com a totalidade das secoes do ensaio.
        cutoff: Quantidade de secoes ja totalizadas ate o marco atual.
        reconciler: Motor de reconciliacao de consistencia de contagem.
        model: Modelo Bayesiano hierarquico para projecoes parciais.
        simulator: Simulador preditivo estocastico de Monte Carlo.
        publisher: Publicador atomico imutavel de projecoes.
        api_client: Cliente de teste da API REST somente leitura.
        observed_at: Timestamp UTC de observacao da rodada eleitoral.
        groups: Tupla contendo codigos canonicos dos grupos partidarios.
        round_num: Turno da eleicao (1 ou 2).

    Returns:
        PublishedProjectionPayload publicado atomicamente e validado via API.

    Raises:
        RuntimeError: Se houver inconsistencia na reconciliacao ou erro na API.
    """
    now = observed_at if observed_at is not None else datetime.now(UTC)
    num_sections = len(sections_catalog)
    observed_raw = sections_catalog[:cutoff]
    pending_raw = sections_catalog[cutoff:]

    sec_states: list[NormalizedSectionState] = []
    for idx, s in enumerate(sections_catalog):
        is_apu = idx < cutoff
        sec_states.append(
            NormalizedSectionState(
                state=str(s["state"]),
                municipality_code=str(s["municipality_code"]),
                zone=str(s["zone"]),
                section=str(s["section"]),
                generation_timestamp=now,
                generation_hash="sha_" + str(s["section"]),
                is_totalized=is_apu,
            )
        )

    total_elec = sum(s["electorate"] for s in sections_catalog)
    tot_elec = sum(s["electorate"] for s in observed_raw)

    sum_pt = sum(dict(s["group_votes"]).get("PT", 0) for s in observed_raw)
    sum_pl = sum(dict(s["group_votes"]).get("PL", 0) for s in observed_raw)
    sum_outros = sum(dict(s["group_votes"]).get("OUTROS", 0) for s in observed_raw)

    cand_group_votes: tuple[tuple[str, int], ...]
    if round_num == 2:
        tot_valid = sum_pt + sum_pl
        cand_group_votes = (("PL", sum_pl), ("PT", sum_pt))
    else:
        tot_valid = sum(s["valid_votes"] for s in observed_raw)
        cand_group_votes = (("OUTROS", sum_outros), ("PL", sum_pl), ("PT", sum_pt))

    tot_blank = sum(int(str(s.get("blank_votes", 0))) for s in observed_raw)
    if tot_blank == 0 and tot_valid > 0:
        tot_blank = int(round(tot_valid * 0.03))
    tot_null = sum(int(str(s.get("null_votes", 0))) for s in observed_raw)
    if tot_null == 0 and tot_valid > 0:
        tot_null = int(round(tot_valid * 0.04))

    totalization = NormalizedTotalization(
        scope=GeographicScope.BRAZIL,
        scope_code="BR",
        total_electorate=total_elec,
        totalized_electorate=tot_elec,
        pending_electorate=total_elec - tot_elec,
        total_sections=num_sections,
        totalized_sections=cutoff,
        pending_sections=num_sections - cutoff,
        valid_votes=tot_valid,
        blank_votes=tot_blank,
        null_votes=tot_null,
        candidate_group_votes=cand_group_votes,
    )

    wave_hash = f"{cutoff:064x}"
    snapshot, report = reconciler.reconcile(
        observed_at=now,
        sections=sec_states,
        totalization=totalization,
        artifact_hashes=(wave_hash,),
    )

    if not report.is_consistent:
        raise RuntimeError("Relatorio de reconciliacao apontou inconsistencia.")

    obs_objs: list[SectionObservation] = []
    for s in observed_raw:
        if round_num == 2:
            v_d = dict(s["group_votes"])
            v_pt = v_d.get("PT", 0)
            v_pl = v_d.get("PL", 0)
            v_sec_valid = v_pt + v_pl
            g_votes: tuple[tuple[str, int], ...] = (("PL", v_pl), ("PT", v_pt))
            h_d = dict(s["historical_shares"])
            h_pt = h_d.get("PT", 0.5)
            h_pl = h_d.get("PL", 0.5)
            sum_h = h_pt + h_pl
            norm_h: tuple[tuple[str, float], ...] = (
                ("PL", h_pl / sum_h if sum_h > 0 else 0.5),
                ("PT", h_pt / sum_h if sum_h > 0 else 0.5),
            )
        else:
            v_sec_valid = s["valid_votes"]
            g_votes = s["group_votes"]
            norm_h = s["historical_shares"]

        obs_objs.append(
            SectionObservation(
                section_id=s["section_id"],
                state=s["state"],
                municipality_code=s["municipality_code"],
                valid_votes=v_sec_valid,
                group_votes=g_votes,
                historical_shares=norm_h,
            )
        )

    pending_objs: list[PendingSection] = []
    for s in pending_raw:
        if round_num == 2:
            h_d = dict(s["historical_shares"])
            h_pt = h_d.get("PT", 0.5)
            h_pl = h_d.get("PL", 0.5)
            sum_h = h_pt + h_pl
            norm_h = (
                ("PL", h_pl / sum_h if sum_h > 0 else 0.5),
                ("PT", h_pt / sum_h if sum_h > 0 else 0.5),
            )
        else:
            norm_h = s["historical_shares"]

        pending_objs.append(
            PendingSection(
                section_id=s["section_id"],
                state=s["state"],
                municipality_code=s["municipality_code"],
                electorate=s["electorate"],
                historical_shares=norm_h,
            )
        )

    qualities_map: dict[str, MatchQuality] = {}
    for s in pending_raw:
        raw_mq = s.get("match_quality")
        if raw_mq:
            try:
                qualities_map[s["section_id"]] = (
                    raw_mq if isinstance(raw_mq, MatchQuality) else MatchQuality(str(raw_mq))
                )
            except ValueError:
                qualities_map[s["section_id"]] = MatchQuality.EXACT

    summary = simulator.simulate(
        observations=obs_objs,
        pending=pending_objs,
        model=model,
        groups=groups,
        match_qualities=qualities_map if qualities_map else None,
    )

    published_payload = publisher.publish(snapshot=snapshot, simulation=summary)

    res = api_client.get("/v1/projections/latest")
    if res.status_code != 200 or res.json()["projection_id"] != published_payload.projection_id:
        raise RuntimeError("Falha ao validar integridade da projecao servida pela API.")

    return published_payload


def calculate_wave_cutoff(
    sections_catalog: Sequence[Mapping[str, Any]],
    progress_pct: float,
    by_electorate: bool = True,
) -> int:
    """Calcula o indice de corte de secoes para um determinado marco percentual.

    Args:
        sections_catalog: Catalogo de secoes ordenado cronologicamente.
        progress_pct: Fracao percentual de apuracao no intervalo (0.0, 1.0].
        by_electorate: Se True, acumula ate a fracao do eleitorado; se False, por contagem.

    Returns:
        Indice inteiro de corte (quantidade de secoes observadas, >= 1).

    Raises:
        ValueError: Se progress_pct estiver fora de (0.0, 1.0] ou catalogo vazio.
    """
    if not 0.0 < progress_pct <= 1.0:
        raise ValueError("progress_pct deve estar no intervalo (0, 1].")
    num_sections = len(sections_catalog)
    if num_sections == 0:
        raise ValueError("sections_catalog nao pode ser vazio.")

    if not by_electorate:
        return max(1, min(num_sections, int(round(num_sections * progress_pct))))

    total_electorate = sum(int(s.get("electorate", 0)) for s in sections_catalog)
    if total_electorate == 0:
        return max(1, min(num_sections, int(round(num_sections * progress_pct))))

    target_electorate = progress_pct * total_electorate
    accumulated = 0
    cutoff = 1
    for idx, s in enumerate(sections_catalog):
        accumulated += int(s.get("electorate", 0))
        cutoff = idx + 1
        if accumulated >= target_electorate:
            break
    return max(1, min(num_sections, cutoff))


def simulate_2026_real_checkpoint(
    sections_catalog: list[dict[str, Any]],
    progress_pct: float = 0.10,
    num_draws: int = 1000,
    seed: int = 42,
    by_electorate: bool = True,
    observed_at: datetime | None = None,
) -> PublishedProjectionPayload:
    """Executa a simulacao de apuracao do primeiro turno de 2026 sobre dados reais.

    Args:
        sections_catalog: Catalogo com secoes reais e shares historicos vinculados.
        progress_pct: Marco percentual de totalizacao (ex: 0.10 para 10%).
        num_draws: Quantidade de sorteios Monte Carlo na rodada.
        seed: Semente aleatoria determinista.
        by_electorate: Se True, corte baseado em eleitorado; se False, em contagem de secoes.
        observed_at: Timestamp UTC de observacao da rodada eleitoral.

    Returns:
        PublishedProjectionPayload contendo a projecao publicada atomicamente.

    Raises:
        ValueError: Se progress_pct estiver fora do intervalo (0, 1] ou catalogo vazio.
    """
    if not 0.0 < progress_pct <= 1.0:
        raise ValueError("progress_pct deve estar no intervalo (0, 1].")
    if not sections_catalog:
        raise ValueError("sections_catalog nao pode ser vazio.")

    publisher = AtomicPublisher()
    reconciler = ReconciliationEngine()
    model = HierarchicalBayesianModel()
    simulator = MonteCarloSimulator(num_draws=num_draws, seed=seed)
    app = create_app(publisher)
    api_client = TestClient(app)

    cutoff = calculate_wave_cutoff(
        sections_catalog=sections_catalog,
        progress_pct=progress_pct,
        by_electorate=by_electorate,
    )
    election_day = observed_at or datetime(2026, 10, 4, 18, 0, tzinfo=UTC)

    return _run_wave_pipeline(
        sections_catalog=sections_catalog,  # type: ignore[arg-type]
        cutoff=cutoff,
        reconciler=reconciler,
        model=model,
        simulator=simulator,
        publisher=publisher,
        api_client=api_client,
        observed_at=election_day,
    )


def simulate_2026_first_round_checkpoint(
    progress_pct: float = 0.10,
    num_sections: int = 100,
    num_draws: int = 1000,
    seed: int = 42,
    sections_catalog: list[SyntheticSection] | list[dict[str, Any]] | None = None,
    by_electorate: bool = False,
) -> PublishedProjectionPayload:
    """Executa a simulacao da apuracao do primeiro turno de 2026 em um marco percentual especifico.

    Args:
        progress_pct: Marco percentual de totalizacao (ex: 0.10 para 10%).
        num_sections: Quantidade de secoes eleitorais sinteticas a simular.
        num_draws: Quantidade de sorteios Monte Carlo na rodada.
        seed: Semente aleatoria determinista.
        sections_catalog: Catalogo opcional de secoes prontas para simular.
        by_electorate: Se True, corte baseado em eleitorado; se False, em contagem de secoes.

    Returns:
        PublishedProjectionPayload contendo a projecao publicada atomicamente.

    Raises:
        ValueError: Se progress_pct estiver fora do intervalo (0, 1].
    """
    if not 0.0 < progress_pct <= 1.0:
        raise ValueError("progress_pct deve estar no intervalo (0, 1].")

    if sections_catalog is not None:
        return simulate_2026_real_checkpoint(
            sections_catalog=sections_catalog,  # type: ignore[arg-type]
            progress_pct=progress_pct,
            num_draws=num_draws,
            seed=seed,
            by_electorate=by_electorate,
        )

    rng = np.random.default_rng(seed)
    synthetic_catalog = _generate_synthetic_sections(num_sections, rng)

    publisher = AtomicPublisher()
    reconciler = ReconciliationEngine()
    model = HierarchicalBayesianModel()
    simulator = MonteCarloSimulator(num_draws=num_draws, seed=seed)
    app = create_app(publisher)
    api_client = TestClient(app)

    cutoff = max(1, int(round(num_sections * progress_pct)))
    election_day = datetime(2026, 10, 4, 18, 0, tzinfo=UTC)

    return _run_wave_pipeline(
        sections_catalog=synthetic_catalog,
        cutoff=cutoff,
        reconciler=reconciler,
        model=model,
        simulator=simulator,
        publisher=publisher,
        api_client=api_client,
        observed_at=election_day,
    )


def simulate_2026_second_round_checkpoint(
    progress_pct: float = 0.10,
    num_sections: int = 100,
    num_draws: int = 1000,
    seed: int = 42,
    sections_catalog: list[SyntheticSection] | list[dict[str, Any]] | None = None,
    by_electorate: bool = True,
    observed_at: datetime | None = None,
) -> PublishedProjectionPayload:
    """Executa a simulacao da apuracao do segundo turno majoritario de 2026 (PT vs PL).

    Calcula a projecao com o modelo hierarquico bayesiano v2, faixas de credibilidade de 90%
    e probabilidade de vitoria majoritaria (superacao da maioria absoluta de 50%).

    Args:
        progress_pct: Marco percentual de totalizacao (ex: 0.10 para 10%).
        num_sections: Quantidade de secoes sinteticas caso o catalogo nao seja fornecido.
        num_draws: Quantidade de sorteios Monte Carlo na rodada.
        seed: Semente aleatoria determinista.
        sections_catalog: Catalogo opcional de secoes reais prontas para simular.
        by_electorate: Se True, corte baseado em eleitorado; se False, em contagem de secoes.
        observed_at: Timestamp UTC de observacao da rodada eleitoral.

    Returns:
        PublishedProjectionPayload contendo a projecao publicada do 2º turno.

    Raises:
        ValueError: Se progress_pct estiver fora do intervalo (0, 1].
    """
    if not 0.0 < progress_pct <= 1.0:
        raise ValueError("progress_pct deve estar no intervalo (0, 1].")

    resolved_catalog: list[Any]
    if sections_catalog is not None:
        resolved_catalog = list(sections_catalog)
    else:
        rng = np.random.default_rng(seed)
        resolved_catalog = _generate_synthetic_sections(num_sections, rng)

    publisher = AtomicPublisher()
    reconciler = ReconciliationEngine()
    model = HierarchicalBayesianModel()
    simulator = MonteCarloSimulator(num_draws=num_draws, seed=seed)
    app = create_app(publisher)
    api_client = TestClient(app)

    cutoff = calculate_wave_cutoff(
        sections_catalog=resolved_catalog,
        progress_pct=progress_pct,
        by_electorate=by_electorate,
    )
    election_day = observed_at or datetime(2026, 10, 25, 18, 0, tzinfo=UTC)

    return _run_wave_pipeline(
        sections_catalog=resolved_catalog,
        cutoff=cutoff,
        reconciler=reconciler,
        model=model,
        simulator=simulator,
        publisher=publisher,
        api_client=api_client,
        observed_at=election_day,
        groups=("PL", "PT"),
        round_num=2,
    )


def run_election_night_simulation(
    num_sections: int = 100,
    waves: tuple[float, ...] = (0.05, 0.15, 0.30, 0.50, 0.75, 0.90, 1.00),
    num_draws: int = 1000,
    seed: int = 42,
) -> dict[str, float]:
    """Executa ensaio de noite eleitoral ponta a ponta medindo latencia e integridade.

    Args:
        num_sections: Quantidade de secoes eleitorais sinteticas a simular.
        waves: Pontos de corte de progresso da apuracao.
        num_draws: Quantidade de sorteios Monte Carlo em cada onda.
        seed: Semente aleatoria determinista.

    Returns:
        Dicionario com metricas operacionais de latencia (media, p95, maximo).

    Raises:
        None.
    """
    rng = np.random.default_rng(seed)
    sections_catalog = _generate_synthetic_sections(num_sections, rng)

    publisher = AtomicPublisher()
    reconciler = ReconciliationEngine()
    model = HierarchicalBayesianModel()
    simulator = MonteCarloSimulator(num_draws=num_draws, seed=seed)
    app = create_app(publisher)
    api_client = TestClient(app)

    round_latencies: list[float] = []

    for wave_pct in waves:
        t_start = time.perf_counter()
        cutoff = max(1, int(round(num_sections * wave_pct)))

        _run_wave_pipeline(
            sections_catalog=sections_catalog,
            cutoff=cutoff,
            reconciler=reconciler,
            model=model,
            simulator=simulator,
            publisher=publisher,
            api_client=api_client,
        )

        elapsed = time.perf_counter() - t_start
        round_latencies.append(elapsed)

    p95 = float(np.percentile(round_latencies, 95))
    mean_lat = float(np.mean(round_latencies))
    max_lat = float(np.max(round_latencies))

    return {
        "p95_seconds": round(p95, 4),
        "mean_seconds": round(mean_lat, 4),
        "max_seconds": round(max_lat, 4),
    }


if __name__ == "__main__":
    print("Iniciando ensaio operacional da noite eleitoral...")
    metrics = run_election_night_simulation()
    print("Ensaio concluido com sucesso!")
    print(f"Latencia p95: {metrics['p95_seconds']} s (Meta: < 10.0 s)")
    print(f"Latencia media: {metrics['mean_seconds']} s")
    print(f"Latencia maxima: {metrics['max_seconds']} s")
