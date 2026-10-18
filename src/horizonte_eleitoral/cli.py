"""Pontos de entrada da aplicacao, mantidos fora do dominio."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from horizonte_eleitoral.backtest.compare import format_comparison_table, run_v1_v2_comparison
from horizonte_eleitoral.config import load_settings
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
    fallback_dir = (
        Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "real_replay"
    )
    loader = RealDataLoader()

    # 1. Verifica se ja existe catalog_2026.parquet analitico (formato colunar de alta performance)
    parquet_path = data_dir / "catalog_2026.parquet"
    if not historical_file_str and not results_file_str and parquet_path.exists():
        print(f"Carregando catalogo analitico de 2026 de: {parquet_path.name}...")
        catalog = loader.load_catalog_parquet(
            parquet_path, limit_rows=limit_sections, filter_ufs=filter_ufs
        )
        print(f"Catalogo real analitico carregado com sucesso ({len(catalog)} secoes ordenadas).")
        return catalog

    # 1.1 Fallback para catalog_2026.csv se o parquet ainda nao tiver sido gerado
    csv_path = data_dir / "catalog_2026.csv"
    if not historical_file_str and not results_file_str and csv_path.exists():
        print(f"Carregando catalogo consolidado de 2026 de: {csv_path.name}...")
        catalog = loader.load_catalog_csv(
            csv_path, limit_rows=limit_sections, filter_ufs=filter_ufs
        )
        print(f"Catalogo real carregado com sucesso ({len(catalog)} secoes ordenadas).")
        if data_dir == Path("data/real") and limit_sections is None and filter_ufs is None:
            try:
                loader.save_catalog_parquet(catalog, parquet_path)
                print(f"Catalogo analitico Parquet gerado para reuso: {parquet_path.name}")
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
            data_dir / "votacao_secao_2022_BR.zip",
            data_dir / "Historico_Totalizacao_Presidente_BR_1T_2022.zip",
            data_dir / "detalhe_votacao_munzona_2022.zip",
            fallback_dir / "sample_historical_2022.csv",
        ]
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
            data_dir / "votacao_secao_2026_BR.zip",
            fallback_dir / "sample_results_2026.csv",
        ]
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
        and data_dir == Path("data/real")
    ):
        try:
            loader.save_catalog_parquet(catalog, parquet_path)
            print(f"Catalogo analitico Parquet gravado para reuso: {parquet_path.name}")
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
        default="data/real",
        help="Diretorio contendo os arquivos de dados reais (padrao: data/real).",
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
        help="Consolida os votos de 2018 em data/real/historical_2018.csv.",
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
        "--ignore-time-gate",
        action="store_true",
        help="Ignora a janela de domingo apos as 17h para testes e simulacoes.",
    )

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    settings = load_settings()
    print(f"Horizonte Eleitoral configurado para o ambiente {settings.environment.value}.")

    data_dir = Path(args.data_dir)

    if args.simulate_2026_2t_pct is not None:
        pct = args.simulate_2026_2t_pct
        norm_pct = pct / 100.0 if pct > 1.0 else pct
        print(f"Iniciando ensaio do 2º turno de 2026 com {norm_pct * 100:.1f}% da apuracao...")
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

    if args.poll_tse_live:
        import asyncio

        from horizonte_eleitoral.ingestion.client import TSEAsyncClient
        from horizonte_eleitoral.ingestion.discovery import TSEPathResolver
        from horizonte_eleitoral.ingestion.tse_live_poller import TSELivePoller

        print("Iniciando consulta à API oficial do TSE...")
        tse_client = TSEAsyncClient(settings)
        resolver = TSEPathResolver(
            base_url="https://resultados.tse.jus.br",
            election_id="002026",
        )
        poller = TSELivePoller(
            client=tse_client,
            resolver=resolver,
            round_num=2,
            ignore_schedule_gate=args.ignore_time_gate,
        )
        try:
            has_new, tot, msg = asyncio.run(poller.check_for_updates())
            print(f"Resultado da checagem: {msg}")
        except Exception as e:
            print(f"Erro ao consultar TSE: {e}")
        return

    if args.download_2018:
        from scripts.download_tse_2018 import download_tse_2018_file

        zip_target = data_dir / "votacao_secao_2018_BR.zip"
        download_tse_2018_file(zip_target)
        return

    if args.consolidate_2018:
        from horizonte_eleitoral.ingestion.consolidator import consolidate_2018_sections

        zip_18 = data_dir / "votacao_secao_2018_BR.zip"
        out_18 = data_dir / "historical_2018.csv"
        consolidate_2018_sections(zip_18, out_18, round_num=1)
        return

    if args.build_elasticity:
        p18 = data_dir / "historical_2018.csv"
        p22 = data_dir / "historical_2022.csv"
        out_elast = data_dir / "elasticity_2018_2022.parquet"
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
        elast_path = data_dir / "elasticity_2018_2022.parquet"
        elast_idx: MunicipalElasticityIndex | None = None
        if elast_path.exists():
            print(f"Carregando indice de elasticidade de: {elast_path.name}...")
            elast_idx = MunicipalElasticityIndex.load_parquet(elast_path)
        else:
            p18 = data_dir / "historical_2018.csv"
            p22 = data_dir / "historical_2022.csv"
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
        parquet_path = data_dir / "catalog_2026.parquet"
        if not parquet_path.exists():
            _resolve_and_load_real_catalog(
                data_dir_str=args.data_dir,
                historical_file_str=args.historical_file,
                results_file_str=args.results_file,
                limit_sections=args.limit_sections,
                filter_ufs=args.ufs,
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
