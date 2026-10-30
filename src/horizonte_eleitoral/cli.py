"""Pontos de entrada da aplicacao, mantidos fora do dominio."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from horizonte_eleitoral.backtest.compare import format_comparison_table, run_v1_v2_comparison
from horizonte_eleitoral.config import (
    Settings,
    get_final_data_dir,
    get_norm_data_dir,
    get_raw_data_dir,
    get_real_data_dir,
    load_settings,
)
from horizonte_eleitoral.historical.elasticity import MunicipalElasticityIndex
from horizonte_eleitoral.ingestion.real_data_loader import RealDataLoader
from horizonte_eleitoral.simulation.election_night_runner import (
    simulate_2026_first_round_checkpoint,
)

SIMULATION_CHECKPOINTS_PCT: tuple[int, ...] = (10, 20, 30, 40, 50, 60, 70, 80, 90, 100)


def _resolve_and_load_real_catalog(
    data_dir_str: str,
    historical_file_str: str | None,
    results_file_str: str | None,
    limit_sections: int | None = None,
    filter_ufs: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Localiza e carrega arquivos de dados reais, montando o catalogo pareado da eleicao.

    Args:
        data_dir_str: Diretorio base contendo os arquivos de dados reais.
        historical_file_str: Caminho especifico opcional para a base de 2022.
        results_file_str: Caminho especifico opcional para os resultados de 2026.
        limit_sections: Limite maximo opcional de secoes a carregar.
        filter_ufs: Lista opcional de siglas de UFs permitidas.

    Returns:
        Lista ordenada de secoes com proporcoes historicas e apuracao real vinculadas.

    Raises:
        FileNotFoundError: Se os arquivos nao forem localizados.
    """
    data_dir = Path(data_dir_str)
    is_default_data_dir = data_dir in (Path("data"), Path("data/final"), Path("data/real"))
    if is_default_data_dir and not data_dir.exists():
        data_dir = get_final_data_dir()
    fallback_dir = (
        Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "real_replay"
    )
    loader = RealDataLoader()

    # 1. Verifica se ja existe catalog_2026.parquet analitico (formato colunar de alta performance)
    parquet_candidates = [
        data_dir / "catalog_2026.parquet",
        data_dir / "final" / "catalog_2026.parquet",
    ]
    if is_default_data_dir:
        parquet_candidates.extend(
            [
                get_final_data_dir() / "catalog_2026.parquet",
                get_real_data_dir() / "catalog_2026.parquet",
            ]
        )
    parquet_path: Path | None = None
    for candidate in parquet_candidates:
        if candidate.exists():
            parquet_path = candidate
            break

    if not historical_file_str and not results_file_str and parquet_path is not None:
        print(f"Carregando catalogo analitico de 2026 de: {parquet_path.name}...")
        catalog = loader.load_catalog_parquet(
            parquet_path, limit_rows=limit_sections, filter_ufs=filter_ufs
        )
        print(f"Catalogo real analitico carregado com sucesso ({len(catalog)} secoes ordenadas).")
        return catalog

    # 1.1 Fallback para catalog_2026.csv se o parquet ainda nao tiver sido gerado
    csv_candidates = [
        data_dir / "catalog_2026.csv",
        data_dir / "norm" / "catalog_2026.csv",
    ]
    if is_default_data_dir:
        csv_candidates.append(get_norm_data_dir() / "catalog_2026.csv")
    csv_path: Path | None = None
    for candidate in csv_candidates:
        if candidate.exists():
            csv_path = candidate
            break

    if not historical_file_str and not results_file_str and csv_path is not None:
        print(f"Carregando catalogo consolidado de 2026 de: {csv_path.name}...")
        catalog = loader.load_catalog_csv(
            csv_path, limit_rows=limit_sections, filter_ufs=filter_ufs
        )
        print(f"Catalogo real carregado com sucesso ({len(catalog)} secoes ordenadas).")
        if is_default_data_dir and limit_sections is None and filter_ufs is None:
            try:
                target_parquet = get_final_data_dir() / "catalog_2026.parquet"
                loader.save_catalog_parquet(catalog, target_parquet)
                print(f"Catalogo analitico Parquet gerado para reuso: {target_parquet.name}")
            except Exception:
                pass
        return catalog

    # 2. Resolucao do arquivo historico de 2022
    hist_path: Path | None = None
    if historical_file_str:
        hist_path = Path(historical_file_str)
    else:
        candidates_2022 = [
            data_dir / "historical_2022.csv",
            data_dir / "norm" / "historical_2022.csv",
            data_dir / "votacao_secao_2022_BR.zip",
            data_dir / "raw" / "votacao_secao_2022_BR.zip",
            data_dir / "Historico_Totalizacao_Presidente_BR_1T_2022.zip",
            data_dir / "raw" / "Historico_Totalizacao_Presidente_BR_1T_2022.zip",
            data_dir / "detalhe_votacao_munzona_2022.zip",
            data_dir / "raw" / "detalhe_votacao_munzona_2022.zip",
        ]
        if is_default_data_dir:
            candidates_2022.extend(
                [
                    get_norm_data_dir() / "historical_2022.csv",
                    get_raw_data_dir() / "votacao_secao_2022_BR.zip",
                    get_raw_data_dir() / "Historico_Totalizacao_Presidente_BR_1T_2022.zip",
                    get_raw_data_dir() / "detalhe_votacao_munzona_2022.zip",
                ]
            )
        candidates_2022.append(fallback_dir / "sample_historical_2022.csv")
        for c in candidates_2022:
            if c.exists():
                hist_path = c
                break

    if hist_path is None or not hist_path.exists():
        raise FileNotFoundError(
            f"Nenhum arquivo de 2022 encontrado em '{data_dir}' nem em '{fallback_dir}'."
        )

    # 3. Resolucao do arquivo de resultados de 2026
    results_path: Path | None = None
    if results_file_str:
        results_path = Path(results_file_str)
    else:
        candidates_2026 = [
            data_dir / "sections_2026.csv",
            data_dir / "norm" / "sections_2026.csv",
            data_dir / "votacao_secao_2026_BR.zip",
            data_dir / "raw" / "votacao_secao_2026_BR.zip",
        ]
        if is_default_data_dir:
            candidates_2026.extend(
                [
                    get_norm_data_dir() / "sections_2026.csv",
                    get_raw_data_dir() / "votacao_secao_2026_BR.zip",
                ]
            )
        candidates_2026.append(fallback_dir / "sample_results_2026.csv")
        for c in candidates_2026:
            if c.exists():
                results_path = c
                break

    if results_path is None or not results_path.exists():
        raise FileNotFoundError(
            f"Nenhum arquivo de 2026 encontrado em '{data_dir}' nem em '{fallback_dir}'."
        )

    print(f"Carregando base historica de 2022 de: {hist_path.name}...")
    locations, votes = loader.load_2022_historical_data(
        hist_path, limit_rows=limit_sections, filter_ufs=filter_ufs
    )
    print(f"  -> {len(locations)} locais de votacao carregados.")

    print(f"Carregando resultados reais de 2026 de: {results_path.name}...")
    results = loader.load_2026_results_data(
        results_path, limit_rows=limit_sections, filter_ufs=filter_ufs
    )
    print(f"  -> {len(results)} secoes eleitorais apuradas carregadas.")

    print("Pareando secoes de 2026 com base historica de 2022...")
    catalog = loader.build_real_election_catalog(locations, votes, results)
    print(f"Catalogo real montado com sucesso ({len(catalog)} secoes ordenadas).")

    if (
        not historical_file_str
        and not results_file_str
        and limit_sections is None
        and filter_ufs is None
        and is_default_data_dir
    ):
        try:
            target_parquet = get_final_data_dir() / "catalog_2026.parquet"
            loader.save_catalog_parquet(catalog, target_parquet)
            print(f"Catalogo analitico Parquet gravado para reuso: {target_parquet.name}")
        except Exception:
            pass

    return catalog


def _run_and_print_checkpoint(
    *,
    wave: float,
    sections: int,
    draws: int,
    seed: int,
    sections_catalog: list[dict[str, Any]] | None = None,
    by_electorate: bool = True,
) -> None:
    """Executa um marco percentual do ensaio de 2026 e exibe o sumario no stdout.

    Args:
        wave: Fracao de apuracao no intervalo (0.0, 1.0].
        sections: Quantidade de secoes eleitorais sinteticas se catalogo for None.
        draws: Quantidade de sorteios Monte Carlo.
        seed: Semente aleatoria determinista.
        sections_catalog: Catalogo opcional de secoes reais prontas.
        by_electorate: Se True, corte baseado em eleitorado; se False, em secoes.

    Returns:
        None.

    Raises:
        ValueError: Se wave estiver fora do intervalo (0.0, 1.0].
    """
    mode_label = "dados reais" if sections_catalog is not None else "dados sinteticos"
    wave_pct_str = f"{wave * 100:.1f}%"
    print(f"Iniciando ensaio do 1º turno de 2026 com {wave_pct_str} da apuracao ({mode_label})...")
    payload = simulate_2026_first_round_checkpoint(
        progress_pct=wave,
        num_sections=sections,
        num_draws=draws,
        seed=seed,
        sections_catalog=sections_catalog,
        by_electorate=by_electorate,
    )
    print("Ensaio concluido com sucesso!")
    print(f"Projection ID: {payload.projection_id}")
    print(f"Totalizado: {payload.totalized_electorate_pct:.2f}% do eleitorado")
    print(f"Probabilidade de 2º Turno: {payload.second_round_probability * 100:.2f}%")
    print("Estimativas dos Grupos Politicos:")
    for group in payload.groups:
        print(
            f"  - {group.code:6s} | Observado: {group.observed_share:5.2f}% | "
            f"Projetado: {group.projected_share:5.2f}% | "
            f"IC 90%: [{group.q05:5.2f}%, {group.q95:5.2f}%]"
        )


def _handle_tse_polling(
    settings: Settings,
    args: argparse.Namespace,
    data_dir: Path,
) -> None:
    """Executa a rotina de consulta pontual ou monitoramento continuo na API do TSE.

    Args:
        settings: Objeto Settings contendo parametros validados da aplicacao.
        args: Argumentos parseados da linha de comando CLI.
        data_dir: Diretorio base para catalogo analitico e persistencia.

    Returns:
        None.

    Raises:
        None.
    """
    import httpx

    from horizonte_eleitoral.ingestion.client import TSEAsyncClient
    from horizonte_eleitoral.ingestion.discovery import TSEPathResolver
    from horizonte_eleitoral.ingestion.tse_live_poller import TSELivePoller

    election_id = args.election_id or settings.tse_election_id_2t
    endpoint_type = args.endpoint_type or settings.tse_endpoint_type
    target_url = args.tse_url or settings.tse_target_url
    ignore_gate = args.ignore_time_gate or settings.ignore_schedule_gate
    interval = args.poll_interval or settings.tse_poll_interval_seconds
    is_continuous = args.poll_continuous or (
        args.poll_interval is not None and args.max_cycles != 1
    )

    resolver = TSEPathResolver(
        base_url="https://resultados.tse.jus.br",
        election_id=election_id,
    )

    sections_catalog: list[dict[str, Any]] | None = None
    if not args.synthetic:
        try:
            sections_catalog = _resolve_and_load_real_catalog(
                data_dir_str=str(data_dir),
                historical_file_str=args.historical_file,
                results_file_str=args.results_file,
                limit_sections=args.limit_sections,
                filter_ufs=args.ufs,
            )
        except Exception as e:
            print(
                f"Aviso: Não foi possível carregar catálogo real ({e}). "
                "Utilizando seções sintéticas."
            )

    async def _async_polling_loop() -> None:
        async with httpx.AsyncClient(timeout=10.0) as hc:
            tse_client = TSEAsyncClient(settings, http_client=hc)
            poller = TSELivePoller(
                client=tse_client,
                resolver=resolver,
                election_id=election_id,
                round_num=2,
                ignore_schedule_gate=ignore_gate,
                target_url=target_url,
                endpoint_type=endpoint_type,
            )
            resolved_url = poller.get_target_url()

            print("=" * 80)
            print("HORIZONTE ELEITORAL · SISTEMA DE PROJEÇÃO EM TEMPO REAL (2º TURNO 2026)")
            print(f"URL Alvo TSE: {resolved_url}")
            print(f"Eleição TSE: {election_id} | Tipo de Endpoint: {endpoint_type}")
            print(
                f"Intervalo de Pull: {interval}s | Modo: "
                f"{'Contínuo' if is_continuous else 'Consulta Pontual'}"
            )
            print(
                f"Janela Oficial: "
                f"{'Ignorada (Modo Ensaio)' if ignore_gate else 'Domingo após as 17:00 BRT'}"
            )
            print("=" * 80)

            cycle = 0
            while True:
                cycle += 1
                now = datetime.now(UTC)
                now_br = now.astimezone(ZoneInfo("America/Sao_Paulo"))
                now_str = now_br.strftime("%H:%M:%S")

                print(f"\n[{now_str} BRT] Ciclo #{cycle}: Consultando API oficial do TSE...")
                try:
                    cycle_result = await poller.run_poller_cycle(
                        sections_catalog=sections_catalog,
                        num_draws=args.draws,
                        seed=args.seed,
                        now=now,
                    )
                    msg = cycle_result["message"]
                    has_new = cycle_result["has_new_data"]
                    payload = cycle_result["projection"]
                    print(f"  -> Resultado: {msg}")

                    if has_new and payload is not None:
                        print(f"  -> PROJEÇÃO ATUALIZADA (Projection ID: {payload.projection_id})")
                        print(f"  -> Eleitorado Apurado: {payload.totalized_electorate_pct:.2f}%")
                        print("  -> Estimativas dos Grupos:")
                        for group in payload.groups:
                            print(
                                f"     * {group.code:4s}: Observado {group.observed_share:5.2f}% | "
                                f"Projetado {group.projected_share:5.2f}% | "
                                f"IC 90%: [{group.q05:5.2f}%, {group.q95:5.2f}%] | "
                                f"Prob. Vitória: {group.win_probability * 100:5.1f}%"
                            )
                        try:
                            out_file = data_dir / "latest_projection_2t.json"
                            out_dict = {
                                "projection_id": payload.projection_id,
                                "published_at": payload.published_at.isoformat(),
                                "data_observed_at": payload.data_observed_at.isoformat(),
                                "status": payload.status,
                                "totalized_electorate_pct": payload.totalized_electorate_pct,
                                "groups": [
                                    {
                                        "code": g.code,
                                        "observed_share": g.observed_share,
                                        "projected_share": g.projected_share,
                                        "q05": g.q05,
                                        "q95": g.q95,
                                        "win_probability": g.win_probability,
                                    }
                                    for g in payload.groups
                                ],
                                "data_quality": payload.data_quality,
                                "model_version": payload.model_version,
                                "snapshot_id": payload.snapshot_id,
                            }
                            out_file.write_text(json.dumps(out_dict, indent=2), encoding="utf-8")
                            print(f"  -> Projeção consolidada salva em: {out_file.name}")
                        except Exception as err:
                            print(f"  -> Aviso ao salvar projeção em disco: {err}")

                except Exception as err:
                    print(f"  -> Alerta: Falha temporária ao consultar TSE: {err}")

                if not is_continuous or (args.max_cycles and cycle >= args.max_cycles):
                    break

                print(
                    f"  -> Próxima checagem em {interval} segundos "
                    "(Pressione Ctrl+C para encerrar)..."
                )
                await asyncio.sleep(interval)

    try:
        asyncio.run(_async_polling_loop())
    except KeyboardInterrupt:
        print("\nMonitoramento encerrado pelo usuário. Dados e projeções preservados.")


def main(argv: Sequence[str] | None = None) -> None:
    """Carrega a configuracao na borda da aplicacao e executa simulacoes ou testes solicitados.

    Args:
        argv: Argumentos opcionais da linha de comando. Se None, utiliza sys.argv[1:].

    Returns:
        None.

    Raises:
        None.
    """
    parser = argparse.ArgumentParser(
        prog="horizonte-eleitoral",
        description="Horizonte Eleitoral - Sistema de Projecao Eleitoral de 2026.",
    )
    for pct in SIMULATION_CHECKPOINTS_PCT:
        parser.add_argument(
            f"--simulate-2026-{pct}pct",
            action="append_const",
            const=pct / 100.0,
            dest="checkpoint_waves",
            help=f"Executa ensaio com {pct}%% da apuracao do primeiro turno de 2026.",
        )
    parser.add_argument(
        "--simulate-2026-all-10pct",
        action="store_true",
        help="Executa ensaios sequenciais de 10%% a 100%% (passo de 10 pontos).",
    )
    parser.add_argument(
        "--wave",
        type=float,
        default=None,
        help="Marco percentual de apuracao (ex: 0.10 ou 10 para 10%%).",
    )
    parser.add_argument(
        "--sections",
        type=int,
        default=100,
        help="Quantidade de secoes eleitorais sinteticas (padrao: 100).",
    )
    parser.add_argument(
        "--draws",
        type=int,
        default=200,
        help="Quantidade de sorteios Monte Carlo (padrao: 200).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Semente aleatoria determinista (padrao: 42).",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Executa o ensaio utilizando dados sinteticos gerados aleatoriamente.",
    )
    parser.add_argument(
        "--real-data",
        action="store_true",
        default=True,
        help="Executa o ensaio utilizando dados reais do TSE (padrao da aplicacao).",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data/final",
        help="Diretorio contendo os arquivos de dados (padrao: data/final).",
    )
    parser.add_argument(
        "--historical-file",
        type=str,
        default=None,
        help="Caminho especifico para o arquivo historico de 2022.",
    )
    parser.add_argument(
        "--results-file",
        type=str,
        default=None,
        help="Caminho especifico para o arquivo de resultados de 2026.",
    )
    parser.add_argument(
        "--replay-by",
        choices=["electorate", "sections"],
        default="electorate",
        help="Criterio de corte das ondas: por eleitorado acumulado ou por contagem de secoes.",
    )
    parser.add_argument(
        "--limit-sections",
        type=int,
        default=None,
        help="Limite maximo opcional de secoes reais a processar.",
    )
    parser.add_argument(
        "--uf",
        action="append",
        dest="ufs",
        help="Filtra UFs especificas (ex: --uf SP --uf RJ).",
    )
    parser.add_argument(
        "--query-sql",
        type=str,
        default=None,
        help="Executa uma consulta analitica SQL direta via DuckDB sobre o catalogo Parquet.",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Inicia a interface visual web interativa do Streamlit.",
    )
    parser.add_argument(
        "--compare-v1-v2",
        action="store_true",
        help="Executa analise comparativa de desempenho entre v1 e v2 nos checkpoints.",
    )
    parser.add_argument(
        "--download-2018",
        action="store_true",
        help="Baixa arquivo zip oficial de secoes eleitorais de 2018 do TSE.",
    )
    parser.add_argument(
        "--consolidate-2018",
        action="store_true",
        help="Consolida os votos de 2018 em data/norm/historical_2018.csv.",
    )
    parser.add_argument(
        "--build-elasticity",
        action="store_true",
        help="Gera o arquivo Parquet de elasticidade municipal 2018-2022.",
    )
    parser.add_argument(
        "--simulate-2026-2t-pct",
        type=float,
        default=None,
        help="Executa ensaio de marco do 2º turno majoritario de 2026 (ex: 50 para 50%%).",
    )
    parser.add_argument(
        "--poll-tse-live",
        action="store_true",
        help="Executa uma checagem de dados na API oficial do TSE com o modelo de 2º turno.",
    )
    parser.add_argument(
        "--poll-continuous",
        action="store_true",
        help="Executa monitoramento continuo em loop com pull periodico a cada X segundos.",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=None,
        help="Intervalo em segundos entre consultas ao TSE (padrao: 60s).",
    )
    parser.add_argument(
        "--election-id",
        type=str,
        default=None,
        help="Identificador oficial da eleicao no TSE (padrao: 6258 para o 2º Turno de 2026).",
    )
    parser.add_argument(
        "--tse-url",
        type=str,
        default=None,
        help="URL completa customizada para consultar resultados no TSE.",
    )
    parser.add_argument(
        "--endpoint-type",
        choices=["divulgacao", "simplificada", "totalization", "auto"],
        default=None,
        help="Tipo de endpoint oficial do TSE (padrao: divulgacao).",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="Numero maximo de ciclos de polling antes de encerrar (util para testes).",
    )
    parser.add_argument(
        "--ignore-time-gate",
        action="store_true",
        help="Ignora a janela de domingo apos as 17h para testes e simulacoes.",
    )
    parser.add_argument(
        "--build-2026-2t-history",
        action="store_true",
        help=(
            "Consolida os dados oficiais do 2º turno de 2026 da CDN do TSE em "
            "catalog_2026_2t.parquet e pre-computa checkpoints_2026_2t.json."
        ),
    )

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    settings = load_settings()
    print(f"Horizonte Eleitoral configurado para o ambiente {settings.environment.value}.")

    data_dir = Path(args.data_dir)

    if args.build_2026_2t_history:
        from horizonte_eleitoral.dashboard.replay import precompute_second_round_checkpoints
        from horizonte_eleitoral.ingestion.second_round_consolidator import (
            consolidate_and_save_2026_second_round,
        )

        eid_2t = args.election_id or settings.tse_election_id_2t
        print(
            f"Baixando e consolidando dados oficiais do 2º Turno "
            f"(Eleição {eid_2t}) na CDN do TSE..."
        )
        summary_2t = consolidate_and_save_2026_second_round(
            data_dir=data_dir,
            election_id=eid_2t,
        )
        print(
            f"Catalogo Parquet do 2º Turno gravado: {summary_2t['catalog_rows_saved']} secoes "
            f"({summary_2t['municipalities_downloaded']} municipios e "
            f"{summary_2t['states_downloaded']} UFs oficiais)."
        )
        print(
            f"Resultado Oficial TSE ({summary_2t['sections_pct_tse']:.2f}% secoes): "
            f"Lula (PT) {summary_2t['official_shares']['PT']:.2f}% vs "
            f"Flávio Bolsonaro (PL) {summary_2t['official_shares']['PL']:.2f}%"
        )
        loader_2t = RealDataLoader()
        cat_2t_candidates = [
            data_dir / "catalog_2026_2t.parquet",
            data_dir / "final" / "catalog_2026_2t.parquet",
            get_final_data_dir() / "catalog_2026_2t.parquet",
        ]
        cat_2t_path = next(
            (c for c in cat_2t_candidates if c.exists()),
            data_dir / "catalog_2026_2t.parquet",
        )
        cat_2t = loader_2t.load_catalog_parquet(cat_2t_path)
        ck_out_dir = (
            data_dir / "final"
            if (data_dir / "final").exists()
            else (
                get_final_data_dir() if data_dir in (Path("data"), Path("data/real")) else data_dir
            )
        )
        ck_path = ck_out_dir / "checkpoints_2026_2t.json"
        print(f"Pre-computando marcos de validacao retroativa do 2º Turno em {ck_path.name}...")
        computed_cks = precompute_second_round_checkpoints(
            catalog_2t=cat_2t,
            out_path=ck_path,
            num_draws=max(300, args.draws),
            seed=args.seed,
        )
        print(f"Concluido! {len(computed_cks)} marcos de validacao salvos em {ck_path}.")
        return

    if args.simulate_2026_2t_pct is not None:
        pct = args.simulate_2026_2t_pct
        norm_pct = pct / 100.0 if pct > 1.0 else pct
        print(f"Iniciando ensaio do 2º turno de 2026 com {norm_pct * 100:.1f}% da apuracao...")
        loader_2t = RealDataLoader()
        parquet_candidates_2t = [
            data_dir / "catalog_2026_2t.parquet",
            data_dir / "final" / "catalog_2026_2t.parquet",
            get_final_data_dir() / "catalog_2026_2t.parquet",
            get_real_data_dir() / "catalog_2026_2t.parquet",
        ]
        parquet_2t = next((c for c in parquet_candidates_2t if c.exists()), None)

        if parquet_2t is not None and not args.historical_file and not args.results_file:
            print(f"Carregando catalogo real do 2º Turno de: {parquet_2t.name}...")
            sections_catalog = loader_2t.load_catalog_parquet(
                parquet_2t, limit_rows=args.limit_sections, filter_ufs=args.ufs
            )
        else:
            sections_catalog = _resolve_and_load_real_catalog(
                data_dir_str=args.data_dir,
                historical_file_str=args.historical_file,
                results_file_str=args.results_file,
                limit_sections=args.limit_sections,
                filter_ufs=args.ufs,
            )
        from horizonte_eleitoral.simulation.election_night_runner import (
            simulate_2026_second_round_checkpoint,
        )

        payload = simulate_2026_second_round_checkpoint(
            progress_pct=norm_pct,
            sections_catalog=sections_catalog,
            num_draws=args.draws,
            seed=args.seed,
            by_electorate=(args.replay_by == "electorate"),
        )
        print("Ensaio do 2º Turno concluido com sucesso!")
        print(f"Projection ID: {payload.projection_id}")
        print(f"Totalizado: {payload.totalized_electorate_pct:.2f}% do eleitorado")
        print("Estimativas das Candidaturas Majoritarias:")
        for group in payload.groups:
            print(
                f"  - {group.code:6s} | Observado: {group.observed_share:5.2f}% | "
                f"Projetado: {group.projected_share:5.2f}% | "
                f"IC 90%: [{group.q05:5.2f}%, {group.q95:5.2f}%]"
            )
        return

    if args.poll_tse_live or args.poll_continuous:
        _handle_tse_polling(settings, args, data_dir)
        return

    if args.download_2018:
        from scripts.download_tse_2018 import download_tse_2018_file

        raw_dir = (
            data_dir / "raw"
            if (data_dir / "raw").exists()
            else (
                get_raw_data_dir()
                if data_dir in (Path("data"), Path("data/final"), Path("data/real"))
                else data_dir
            )
        )
        raw_dir.mkdir(parents=True, exist_ok=True)
        zip_target = raw_dir / "votacao_secao_2018_BR.zip"
        download_tse_2018_file(zip_target)
        return

    if args.consolidate_2018:
        from horizonte_eleitoral.ingestion.consolidator import consolidate_2018_sections

        zip_candidates = [
            data_dir / "votacao_secao_2018_BR.zip",
            data_dir / "raw" / "votacao_secao_2018_BR.zip",
            get_raw_data_dir() / "votacao_secao_2018_BR.zip",
        ]
        zip_18 = next(
            (c for c in zip_candidates if c.exists()), data_dir / "votacao_secao_2018_BR.zip"
        )
        norm_dir = (
            data_dir / "norm"
            if (data_dir / "norm").exists()
            else (
                get_norm_data_dir()
                if data_dir in (Path("data"), Path("data/final"), Path("data/real"))
                else data_dir
            )
        )
        norm_dir.mkdir(parents=True, exist_ok=True)
        out_18 = norm_dir / "historical_2018.csv"
        consolidate_2018_sections(zip_18, out_18, round_num=1)
        return

    if args.build_elasticity:
        p18_candidates = [
            data_dir / "historical_2018.csv",
            data_dir / "norm" / "historical_2018.csv",
            get_norm_data_dir() / "historical_2018.csv",
        ]
        p18 = next((c for c in p18_candidates if c.exists()), data_dir / "historical_2018.csv")
        p22_candidates = [
            data_dir / "historical_2022.csv",
            data_dir / "norm" / "historical_2022.csv",
            get_norm_data_dir() / "historical_2022.csv",
        ]
        p22 = next((c for c in p22_candidates if c.exists()), data_dir / "historical_2022.csv")
        final_dir = (
            data_dir / "final"
            if (data_dir / "final").exists()
            else (
                get_final_data_dir()
                if data_dir in (Path("data"), Path("data/norm"), Path("data/real"))
                else data_dir
            )
        )
        final_dir.mkdir(parents=True, exist_ok=True)
        out_elast = final_dir / "elasticity_2018_2022.parquet"
        idx = MunicipalElasticityIndex.build_from_csvs(p18, p22)
        saved = idx.save_parquet(out_elast)
        print(f"Indice de elasticidade gerado: {saved} municipios salvos em {out_elast.name}.")
        return

    if args.compare_v1_v2:
        print("Iniciando comparativo head-to-head entre Modelo v1 e Modelo v2...")
        sections_catalog = _resolve_and_load_real_catalog(
            data_dir_str=args.data_dir,
            historical_file_str=args.historical_file,
            results_file_str=args.results_file,
            limit_sections=args.limit_sections,
            filter_ufs=args.ufs,
        )
        elast_candidates = [
            data_dir / "elasticity_2018_2022.parquet",
            data_dir / "final" / "elasticity_2018_2022.parquet",
            get_final_data_dir() / "elasticity_2018_2022.parquet",
        ]
        elast_path = next((c for c in elast_candidates if c.exists()), None)
        elast_idx: MunicipalElasticityIndex | None = None
        if elast_path is not None:
            print(f"Carregando indice de elasticidade de: {elast_path.name}...")
            elast_idx = MunicipalElasticityIndex.load_parquet(elast_path)
        else:
            p18_candidates = [
                data_dir / "historical_2018.csv",
                data_dir / "norm" / "historical_2018.csv",
                get_norm_data_dir() / "historical_2018.csv",
            ]
            p18 = next((c for c in p18_candidates if c.exists()), data_dir / "historical_2018.csv")
            p22_candidates = [
                data_dir / "historical_2022.csv",
                data_dir / "norm" / "historical_2022.csv",
                get_norm_data_dir() / "historical_2022.csv",
            ]
            p22 = next((c for c in p22_candidates if c.exists()), data_dir / "historical_2022.csv")
            if p18.exists() and p22.exists():
                print("Calculando indice de elasticidade a partir dos CSVs...")
                elast_idx = MunicipalElasticityIndex.build_from_csvs(p18, p22)

        comparison_results = run_v1_v2_comparison(
            sections_catalog=sections_catalog,
            elasticity_index=elast_idx,
            checkpoints=(10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0),
        )
        print(format_comparison_table(comparison_results))
        return

    if args.dashboard:
        import subprocess

        dashboard_app = Path(__file__).resolve().parent / "dashboard" / "app.py"
        print(f"Iniciando painel Streamlit em {dashboard_app}...")
        subprocess.run(
            [sys.executable, "-m", "streamlit", "run", str(dashboard_app)],
            check=True,
        )
        return

    if args.query_sql:
        parquet_candidates = [
            data_dir / "catalog_2026.parquet",
            data_dir / "final" / "catalog_2026.parquet",
            get_final_data_dir() / "catalog_2026.parquet",
            get_real_data_dir() / "catalog_2026.parquet",
        ]
        parquet_path = next((c for c in parquet_candidates if c.exists()), None)
        if parquet_path is None:
            _resolve_and_load_real_catalog(
                data_dir_str=args.data_dir,
                historical_file_str=args.historical_file,
                results_file_str=args.results_file,
                limit_sections=args.limit_sections,
                filter_ufs=args.ufs,
            )
            parquet_path = next(
                (c for c in parquet_candidates if c.exists()), data_dir / "catalog_2026.parquet"
            )
        loader = RealDataLoader()
        rel = loader.query_catalog_sql(parquet_path, args.query_sql)
        print(rel.df().to_string(index=False))
        return

    waves_to_run: list[float] = []
    if args.simulate_2026_all_10pct:
        waves_to_run.extend(pct / 100.0 for pct in SIMULATION_CHECKPOINTS_PCT)
    elif args.checkpoint_waves:
        waves_to_run.extend(args.checkpoint_waves)
    elif args.wave is not None:
        normalized_wave = args.wave / 100.0 if 1.0 < args.wave <= 100.0 else args.wave
        waves_to_run.append(normalized_wave)

    sections_catalog_run: list[dict[str, Any]] | None = None
    if not args.synthetic and (
        args.checkpoint_waves or args.simulate_2026_all_10pct or args.wave is not None
    ):
        sections_catalog_run = _resolve_and_load_real_catalog(
            data_dir_str=args.data_dir,
            historical_file_str=args.historical_file,
            results_file_str=args.results_file,
            limit_sections=args.limit_sections,
            filter_ufs=args.ufs,
        )

    by_electorate = args.replay_by == "electorate"

    for wave in waves_to_run:
        _run_and_print_checkpoint(
            wave=wave,
            sections=args.sections,
            draws=args.draws,
            seed=args.seed,
            sections_catalog=sections_catalog_run,
            by_electorate=by_electorate,
        )


if __name__ == "__main__":
    main()
