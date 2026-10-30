"""Aplicacao Streamlit de alta precisao para acompanhamento e projecao eleitoral 2026."""

from __future__ import annotations

import asyncio
import importlib
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import streamlit as st

from horizonte_eleitoral.backtest.second_round_validation import (
    summarize_second_round_validation,
)
from horizonte_eleitoral.config import load_settings
from horizonte_eleitoral.dashboard import charts as dashboard_charts
from horizonte_eleitoral.dashboard.charts import (
    build_model_error_chart,
    build_second_round_chart,
    build_second_round_error_chart,
)
from horizonte_eleitoral.dashboard.components import (
    render_candidate_cards,
    render_chart_guide,
    render_editorial_header,
    render_first_round_validation_panel,
    render_general_model_documentation,
    render_history_table,
    render_model_card_expander,
    render_p2t_banner,
    render_polling_log_table,
    render_polling_status_box,
    render_second_round_candidate_cards,
    render_second_round_history_table,
    render_second_round_state_table,
    render_second_round_validation_panel,
    render_state_diff_table,
)
from horizonte_eleitoral.dashboard.replay import (
    SECOND_ROUND_LIVE_MODEL_REV,
    build_live_point,
    build_second_round_replay_point,
    generate_replay_timeline,
    generate_second_round_state_projections,
    generate_second_round_validation_timeline,
    generate_state_projections,
    load_replay_catalog,
    load_second_round_validation_catalog,
    refresh_stale_second_round_points,
    summarize_first_round_validation,
)
from horizonte_eleitoral.dashboard.styles import get_custom_css
from horizonte_eleitoral.ingestion.client import TSEAsyncClient
from horizonte_eleitoral.ingestion.discovery import TSEPathResolver
from horizonte_eleitoral.ingestion.tse_live_poller import (
    TSELivePoller,
    is_election_night_window,
)
from horizonte_eleitoral.normalization.models import NormalizedTotalization

BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")


@st.cache_resource(show_spinner="Carregando catálogo analítico completo de 2026...")
def get_replay_catalog() -> list[dict[str, Any]]:
    """Carrega o catalogo analitico completo de 499.206 secoes de 2026 em cache do Streamlit.

    Args:
        None.

    Returns:
        Lista completa de secoes eleitorais pareadas para replay.

    Raises:
        FileNotFoundError: Se o arquivo de catalogo nao for encontrado.
    """
    return load_replay_catalog(limit_sections=None)


@st.cache_resource(show_spinner="Carregando catálogo oficial consolidado do 2º Turno 2026...")
def get_second_round_validation_catalog() -> list[dict[str, Any]]:
    """Carrega o catalogo cronologico oficial do 2º Turno de 2026 em cache do Streamlit.

    Args:
        None.

    Returns:
        Lista ordenada cronologicamente de secoes do 2º turno com priors do 1º turno.

    Raises:
        FileNotFoundError: Se nenhum catalogo ou fixture for localizado.
    """
    return load_second_round_validation_catalog(limit_sections=None)


def _render_first_round_tab() -> None:
    """Renderiza a aba de historico e validacao do 1º Turno de 2026 com o catalogo real."""
    st.markdown("### Histórico e Validação · 1º Turno Presidencial 2026")
    st.caption(
        "Acompanhe a convergência das projeções estatísticas "
        "com dados consolidados de 499.206 seções eleitorais de 2026."
    )

    if "slider_1t" not in st.session_state:
        st.session_state.slider_1t = 10.0

    def _set_wave_1t(target: float) -> None:
        """Define o percentual de apuracao do 1º turno."""
        st.session_state.slider_1t = max(1.0, min(100.0, target))

    def _step_wave_1t(delta: float) -> None:
        """Incrementa ou decrementa o percentual do 1º turno."""
        curr = float(st.session_state.get("slider_1t", 10.0))
        st.session_state.slider_1t = max(1.0, min(100.0, round(curr + delta)))

    col_btn1, col_btn2, col_btn3, col_btn4, col_btn5 = st.columns(5)
    col_btn1.button(
        "⏪ Início (1%)",
        use_container_width=True,
        key="btn_1t_1",
        on_click=_set_wave_1t,
        args=(1.0,),
    )
    col_btn2.button(
        "🎯 10% (Padrão)",
        use_container_width=True,
        key="btn_1t_10",
        on_click=_set_wave_1t,
        args=(10.0,),
    )
    col_btn3.button(
        "◀️ -10%",
        use_container_width=True,
        key="btn_1t_m10",
        on_click=_step_wave_1t,
        args=(-10.0,),
    )
    col_btn4.button(
        "▶️ +10%",
        use_container_width=True,
        key="btn_1t_p10",
        on_click=_step_wave_1t,
        args=(10.0,),
    )
    col_btn5.button(
        "⏩ Fim (100%)",
        use_container_width=True,
        key="btn_1t_100",
        on_click=_set_wave_1t,
        args=(100.0,),
    )

    current_wave_pct = st.slider(
        "Progresso do Eleitorado Apurado no 1º Turno (%):",
        min_value=1.0,
        max_value=100.0,
        step=1.0,
        format="%.1f%%",
        key="slider_1t",
    )
    st.session_state.replay_wave = current_wave_pct
    current_wave = current_wave_pct / 100.0

    with st.spinner("Computando projeção bayesiana da rodada com o catálogo de 2026..."):
        catalog = get_replay_catalog()
        points = generate_replay_timeline(catalog=catalog, current_wave=current_wave)
        full_series = generate_replay_timeline(catalog=catalog, current_wave=1.0)
        val_summary_1t = summarize_first_round_validation(full_series)
        states_data = generate_state_projections(catalog=catalog, wave=current_wave)

    latest_point = points[-1] if points else None
    electorate_pct = latest_point["x"] if latest_point else current_wave_pct
    updated_str = latest_point["t"] if latest_point else "17:00"
    prob_2t = latest_point.get("p_2turno") if latest_point else None

    # 1. Cabecalho Editorial do 1o Turno
    render_editorial_header(
        electorate_pct=electorate_pct,
        updated_str=updated_str,
        environment="replay",
        round_num=1,
    )

    # 2. Cartoes de Candidatos padronizados
    render_candidate_cards(latest_point=latest_point)

    # 3. Painel de Auditoria e Validacao Historica Padronizado (4 KPIs)
    render_first_round_validation_panel(
        latest_point=latest_point,
        validation_summary=val_summary_1t,
    )

    # 4. Probabilidade de 2o Turno
    render_p2t_banner(prob_2t=prob_2t)

    # Grafico Interativo Duplo em Altair
    st.markdown("#### Evolução da Apuração e Projeção Final")
    render_chart_guide()

    col_v1, _ = st.columns([2.2, 1.8])
    with col_v1:
        view_opt_1t = st.radio(
            "Extensão da visualização do 1º Turno:",
            options=[
                "Projeção estendida até o final (100%)",
                "Série Completa de Auditoria (1% a 100%)",
            ],
            index=0,
            horizontal=True,
            key="radio_1t_view_extent",
            help=(
                "Projeção estendida exibe a trajetória e o resultado final projetado (100%) "
                "a partir do marco atual. Série Completa exibe a convergência de todos os marcos."
            ),
        )

    is_full_1t = "Completa" in view_opt_1t
    chart_points_1t = full_series if is_full_1t else points
    final_res_1t = {"PT": 45.16, "PL": 47.03, "OUTROS": 7.81}

    chart = dashboard_charts.build_projection_chart(
        points=chart_points_1t,
        active_wave=current_wave_pct,
        final_result=final_res_1t,
        extend_to_end=not is_full_1t,
    )
    st.altair_chart(chart, use_container_width=True)

    # Grafico Comparativo de Erro Absoluto (HORIZON-MRP vs Urna Bruta)
    st.markdown('<div style="margin-top: 28px;"></div>', unsafe_allow_html=True)
    st.markdown("#### Qualidade do Modelo HORIZON-MRP: Erro Absoluto ao Longo da Apuração")
    st.caption(
        "Distância média absoluta em pontos percentuais (pp) para o resultado oficial "
        "definitivo do TSE (PT: 45,16%, PL: 47,03%, OUTROS: 7,81%). "
        "A linha vertical destaca o marco percentual avaliado no controle acima."
    )

    col_scale_1t, col_ext_1t = st.columns([1.8, 2.2])
    with col_scale_1t:
        scale_opt_1t = st.radio(
            "Escala vertical do erro:",
            options=["Foco de Precisão (0 a 4 pp)", "Escala Ampla (0 a 20 pp)"],
            index=0,
            horizontal=True,
            key="radio_1t_error_chart_scale",
            help="Foco de Precisão permite visualizar detalhes abaixo de 1 pp e a meta de 0,50 pp.",
        )
    with col_ext_1t:
        ext_opt_1t = st.radio(
            "Extensão da série avaliada:",
            options=["Série Completa (2% a 100%)", "Apenas até o marco selecionado"],
            index=0,
            horizontal=True,
            key="radio_1t_error_chart_extent",
            help="Série Completa exibe a convergência global com cursor no marco atual.",
        )

    y_ceiling_1t = 4.0 if "Foco" in scale_opt_1t else 20.0
    chart_err_points_1t = full_series if "Completa" in ext_opt_1t else points

    chart_err_1t = build_model_error_chart(
        points=chart_err_points_1t,
        height=320,
        y_max=y_ceiling_1t,
        active_wave=current_wave_pct,
    )
    st.altair_chart(chart_err_1t, use_container_width=True, theme="streamlit")

    # Tabela Historica Expansivel
    with st.expander("📊 Ver os dados em tabela histórica"):
        render_history_table(points=points)

    # Projecao por Estado Expansivel
    with st.expander("🗺️ Diferença entre a urna e a pesquisa em cada estado (UFs)"):
        render_state_diff_table(states_data=states_data)

    # Metodologia e Model Card - HORIZON-MRP (Versao 2)
    render_model_card_expander(
        {
            "model_version": (
                "HORIZON-MRP v2026.2 "
                "(Hierarchical Optimal Regression & Inferred Zonal Outcomes Network)"
            ),
            "target_error_margin": (
                "0.5 pp a partir de 2% do eleitorado apurado (validado em 100% da base)"
            ),
            "disclaimer": (
                "Interface conectada exclusivamente ao modelo preditivo HORIZON-MRP. "
                "A Versão 1 encontra-se arquivada como base legada de auditoria."
            ),
        }
    )


def _init_dashboard_session_state() -> None:
    """Inicializa as variaveis de sessao necessarias para o monitoramento e replay do dashboard."""
    if "second_round_points" not in st.session_state:
        st.session_state.second_round_points = []

    if "second_round_pct" not in st.session_state:
        st.session_state.second_round_pct = 0.0

    if "tse_log_entries" not in st.session_state:
        st.session_state.tse_log_entries = []

    if "last_check_str" not in st.session_state:
        st.session_state.last_check_str = datetime.now(UTC).strftime("%H:%M:%S UTC")

    if "last_status_msg" not in st.session_state:
        st.session_state.last_status_msg = (
            "Monitoramento conectado à API do TSE. Aguardando disparo manual ou automático."
        )


_init_second_round_state = _init_dashboard_session_state


def _execute_second_round_step(target_pct: float) -> dict[str, Any]:
    """Computa e adiciona um novo marco de apuracao do 2º Turno a serie temporal.

    Args:
        target_pct: Percentual de totalizacao do eleitorado (ex: 25.0 para 25%).

    Returns:
        Dicionario com o ponto recem-computado.

    Raises:
        None.
    """
    catalog = get_replay_catalog()
    wave = max(0.01, min(1.0, target_pct / 100.0))
    point = build_second_round_replay_point(catalog=catalog, wave=wave, num_draws=200)

    # Evita pontos duplicados no mesmo percentual
    existing = [p for p in st.session_state.second_round_points if abs(p["x"] - point["x"]) < 0.1]
    if not existing:
        st.session_state.second_round_points.append(point)
        st.session_state.second_round_points.sort(key=lambda p: float(p["x"]))

    st.session_state.second_round_pct = float(point["x"])
    return point


def _render_real_time_tab() -> None:
    """Renderiza a aba de Tempo Real e Projecao para a disputa eleitoral oficial do TSE.

    Permite selecionar o ano e o turno da eleicao acompanhada, filtrando e consultando
    a API oficial do TSE em tempo real com calculo estocastico HORIZON-MRP.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    _init_second_round_state()

    st.markdown("### ⚡ Tempo Real Oficial TSE · Acompanhamento e Projeção")
    st.caption(
        "Monitoramento contínuo da API oficial do TSE com checagens automáticas, "
        "filtros por ano/turno da eleição e projeção do modelo HORIZON-MRP em tempo real."
    )

    settings = load_settings()

    # 1. Filtros de Selecao da Eleicao em Tempo Real (Ano, Turno, Codigo e Endpoint)
    st.markdown("#### 🎯 Filtros da Eleição Acompanhada")
    col_ano, col_turno, col_cod, col_end = st.columns([1.1, 1.2, 1.3, 1.4])

    with col_ano:
        ano_sel = st.selectbox(
            "Ano da Eleição:",
            options=[2026, 2024, 2022],
            index=0,
            help="Ano do pleito eleitoral no TSE (padrão: 2026).",
            key="realtime_selected_year",
        )

    with col_turno:
        turno_sel = st.selectbox(
            "Turno da Eleição:",
            options=["2º Turno", "1º Turno"],
            index=0,
            help="Turno da eleição presidencial acompanhada.",
            key="realtime_selected_round",
        )

    round_num = 2 if "2º" in turno_sel else 1

    default_ids: dict[tuple[int, int], str] = {
        (2026, 2): settings.tse_election_id_2t,
        (2026, 1): "6257",
        (2024, 2): "619",
        (2024, 1): "618",
        (2022, 2): "545",
        (2022, 1): "544",
    }
    suggested_id = default_ids.get(
        (ano_sel, round_num),
        settings.tse_election_id_2t if round_num == 2 else "6257",
    )

    with col_cod:
        election_id = st.text_input(
            "Código da Eleição TSE:",
            value=suggested_id,
            help="Código oficial do pleito no TSE (ex: 6258 para 2T 2026, 6257 para 1T 2026).",
            key=f"realtime_eid_{ano_sel}_{round_num}",
        )

    with col_end:
        endpoint_type = st.selectbox(
            "Tipo de Endpoint TSE:",
            options=["divulgacao", "simplificada", "totalization"],
            index=0,
            help="divulgacao (u.json completo), simplificada (r.json) ou totalization (ea20).",
            key="realtime_endpoint_type",
        )

    # Estado isolado para a combinacao ano/turno/codigo selecionada
    state_key = f"live_pts_{ano_sel}_{round_num}_{election_id}"
    if state_key not in st.session_state:
        st.session_state[state_key] = list(
            st.session_state.second_round_points if round_num == 2 and ano_sel == 2026 else []
        )

    active_points: list[dict[str, Any]] = st.session_state[state_key]

    if round_num == 2 and ano_sel == 2026:
        st.session_state.second_round_points = active_points

    ignore_gate = st.sidebar.checkbox(
        "Ignorar janela das 17h (Modo Teste / Demonstração)",
        value=True,
        help=(
            "Permite executar checagens e simulações na API mesmo "
            "fora do horário de votação oficial."
        ),
    )

    is_window_active = is_election_night_window(ignore_gate=ignore_gate)

    status_janela_str = "🟢 Aberta / Teste" if is_window_active else "⏳ Bloqueada"
    st.markdown(
        f"""
        <div style="background: var(--bg-suave); border: 1px solid var(--borda-card); """
        f"""border-radius: 8px; padding: 9px 14px; margin: 4px 0 16px 0; """
        f"""font-size: 0.86rem; color: var(--texto-card);">
            📡 <strong>Conexão TSE Ativa:</strong> Eleição {ano_sel} · {turno_sel} &nbsp;|&nbsp;
            <strong>Código Oficial:</strong> <code>{election_id}</code> &nbsp;|&nbsp;
            <strong>Endpoint:</strong> <code>{endpoint_type}</code> &nbsp;|&nbsp;
            <strong>Status Janela 17h:</strong> {status_janela_str}
        </div>
        """,
        unsafe_allow_html=True,
    )

    if any(
        p.get("is_live") and p.get("model_rev") != SECOND_ROUND_LIVE_MODEL_REV
        for p in active_points
    ):
        with st.spinner("Recalculando histórico com votos reais do TSE..."):
            active_points = refresh_stale_second_round_points(
                points=active_points,
                catalog=get_replay_catalog(),
            )
            st.session_state[state_key] = active_points
            if round_num == 2 and ano_sel == 2026:
                st.session_state.second_round_points = active_points

    latest_pt = active_points[-1] if active_points else None
    current_pct = float(latest_pt.get("x", 0.0)) if latest_pt else 0.0
    if round_num == 2 and ano_sel == 2026:
        st.session_state.second_round_pct = current_pct

    # 2. Caixa informativa com o status do monitoramento automatico
    render_polling_status_box(
        last_check_str=st.session_state.last_check_str,
        current_pct=current_pct,
        is_auto_active=is_window_active,
        is_window_open=is_window_active,
        status_message=st.session_state.last_status_msg,
        totalized_sections=latest_pt.get("totalized_sections") if latest_pt else None,
        total_sections=latest_pt.get("total_sections") if latest_pt else None,
        sections_pct=latest_pt.get("x_sections") if latest_pt else None,
        totalized_electorate=latest_pt.get("totalized_electorate") if latest_pt else None,
        total_electorate=latest_pt.get("total_electorate") if latest_pt else None,
        electorate_pct=latest_pt.get("electorate_pct") if latest_pt else None,
        tse_timestamp_str=latest_pt.get("tse_time") if latest_pt else None,
    )

    # 3. Painel de Controles e Botoes de Disparo
    st.markdown("#### Controle de Captura do TSE")
    col_btn, col_auto, col_int = st.columns([2, 1.5, 1.5])

    with col_btn:
        btn_check = st.button(
            "🔄 Consultar TSE Agora",
            type="primary",
            use_container_width=True,
            help=(
                "Consulta a API do TSE imediatamente. Se houver novos dados, recalcula a projeção."
            ),
        )

    with col_auto:
        auto_poll = st.toggle(
            "⏱️ Auto-Pull Periódico",
            value=False,
            help="Executa consultas automáticas periódicas à API oficial do TSE.",
        )

    with col_int:
        poll_interval = st.selectbox(
            "Intervalo de Pull:",
            options=[15, 30, 60, 120, 300],
            index=1,
            format_func=lambda s: f"{s} segundos",
            help="Frequência de consulta à API do TSE.",
        )

    def _poll_and_update() -> tuple[bool, str]:
        _init_dashboard_session_state()
        now_dt = datetime.now(UTC)
        check_time_str = now_dt.strftime("%H:%M:%S UTC")
        local_time_str = now_dt.astimezone(BRASILIA_TZ).strftime("%H:%M")
        st.session_state.last_check_str = check_time_str

        resolver = TSEPathResolver(
            base_url="https://resultados.tse.jus.br",
            election_id=election_id,
            year=ano_sel,
        )

        async def _poll_tse() -> tuple[
            bool,
            NormalizedTotalization | None,
            str,
            dict[str, NormalizedTotalization],
            str,
        ]:
            async with httpx.AsyncClient(timeout=10.0) as hc:
                tse_client = TSEAsyncClient(settings, http_client=hc)
                poller = TSELivePoller(
                    client=tse_client,
                    resolver=resolver,
                    election_id=election_id,
                    round_num=round_num,
                    ignore_schedule_gate=ignore_gate,
                    endpoint_type=endpoint_type,
                )
                has_new_res, tot_res, msg_res = await poller.check_for_updates(now=now_dt)
                uf_tots_res: dict[str, NormalizedTotalization] = {}
                if (
                    tot_res is not None
                    and tot_res.valid_votes > 0
                    and (tot_res.totalized_electorate / max(1, tot_res.total_electorate)) >= 0.02
                    and round_num == 2
                ):
                    uf_tots_res = await poller.fetch_state_totalizations()
                return has_new_res, tot_res, msg_res, uf_tots_res, poller.get_target_url()

        target_url_logged = resolver.url_for_divulgacao(round_num=round_num)
        uf_tots: dict[str, NormalizedTotalization] = {}
        try:
            has_new, tot, status_msg, uf_tots, target_url_logged = asyncio.run(_poll_tse())
        except Exception as exc:
            has_new = False
            tot = None
            status_msg = f"Aviso de conexão com o TSE: {exc}"

        if tot is not None and (tot.valid_votes > 0 or tot.totalized_sections > 0):
            has_enough = (tot.totalized_electorate / max(1, tot.total_electorate)) >= 0.02
            catalog = (
                (get_second_round_validation_catalog() if round_num == 2 else get_replay_catalog())
                if has_enough
                else None
            )
            new_point = build_live_point(
                totalization=tot,
                round_num=round_num,
                time_str=local_time_str,
                catalog=catalog,
                state_totalizations=uf_tots or None,
            )
            matched_idx = next(
                (
                    idx
                    for idx, p in enumerate(active_points)
                    if abs(p["x"] - new_point["x"]) < 0.01
                    and p.get("apurado") == new_point["apurado"]
                ),
                None,
            )
            if matched_idx is None:
                active_points.append(new_point)
                active_points.sort(key=lambda p: float(p["x"]))
            else:
                active_points[matched_idx] = new_point
                has_new = False

            st.session_state[state_key] = active_points
            if round_num == 2 and ano_sel == 2026:
                st.session_state.second_round_points = active_points
                st.session_state.second_round_pct = float(new_point["x"])

            sec_pct_str = f"{new_point['x_sections']:.2f}%".replace(".", ",")
            elec_pct_str = f"{new_point['electorate_pct']:.2f}%".replace(".", ",")
            sec_tot_str = f"{tot.totalized_sections:,}".replace(",", ".")
            sec_all_str = f"{tot.total_sections:,}".replace(",", ".")
            elec_tot_str = f"{tot.totalized_electorate:,}".replace(",", ".")
            elec_all_str = f"{tot.total_electorate:,}".replace(",", ".")

            if has_new:
                st.session_state.last_status_msg = (
                    f"Novos dados processados com sucesso! "
                    f"Seções totalizadas no TSE: {sec_pct_str} ({sec_tot_str} de {sec_all_str}) "
                    f"· Eleitorado apurado: {elec_pct_str} ({elec_tot_str} de {elec_all_str})."
                )
                st.session_state.tse_log_entries.append(
                    {
                        "Horário": check_time_str,
                        "Status": 200,
                        "Apurado (%)": sec_pct_str,
                        "Dados Novos": "Sim",
                        "Mensagem": status_msg,
                        "URL": target_url_logged,
                    }
                )
                return True, st.session_state.last_status_msg
            else:
                st.session_state.last_status_msg = (
                    f"Dados oficiais inalterados no TSE: {sec_pct_str} das seções "
                    f"({sec_tot_str} de {sec_all_str}) · {elec_pct_str} do eleitorado."
                )
                status_code = 304 if "304" in status_msg or "inalterados" in status_msg else 200
                st.session_state.tse_log_entries.append(
                    {
                        "Horário": check_time_str,
                        "Status": status_code,
                        "Apurado (%)": sec_pct_str,
                        "Dados Novos": "Não",
                        "Mensagem": status_msg,
                        "URL": target_url_logged,
                    }
                )
                return False, status_msg
        else:
            st.session_state.last_status_msg = status_msg
            status_code = (
                304
                if "304" in status_msg or "inalterados" in status_msg
                else (503 if "Aviso" in status_msg else 200)
            )
            st.session_state.tse_log_entries.append(
                {
                    "Horário": check_time_str,
                    "Status": status_code,
                    "Apurado (%)": f"{current_pct:.2f}%",
                    "Dados Novos": "Não",
                    "Mensagem": status_msg,
                    "URL": target_url_logged,
                }
            )
            return False, status_msg

    # Sincronizacao automatica inicial ao abrir a aba
    initial_sync_key = f"tse_initial_sync_done_{ano_sel}_{round_num}_{election_id}"
    if not active_points and initial_sync_key not in st.session_state:
        st.session_state[initial_sync_key] = True
        _poll_and_update()

    # Execucao do disparo manual
    if btn_check:
        with st.spinner("Consultando API oficial do TSE e processando dados..."):
            has_new, msg = _poll_and_update()
            if has_new:
                st.success(f"✅ {msg}")
            else:
                st.info(f"ℹ️ {msg}")

    # 4. Fragmento de verificacao automatica periodica (Auto-Pull)
    @st.fragment(run_every=poll_interval if auto_poll else None)
    def _auto_polling_fragment() -> None:
        """Fragmento interno que executa polling em segundo plano no intervalo selecionado."""
        now_f = datetime.now(UTC)
        if auto_poll and is_election_night_window(now_f, ignore_gate=ignore_gate):
            has_new, msg = _poll_and_update()
            st.caption(
                f"⏱️ Auto-pull ativo (a cada {poll_interval}s) · "
                f"Última checagem: {st.session_state.last_check_str}"
            )
            if has_new:
                st.rerun()
        elif not auto_poll:
            st.caption(
                "⏱️ Auto-pull desativado · Disparo manual disponível acima ou ative o toggle."
            )
        else:
            st.caption("⏳ Aguardando abertura da janela oficial das 17h para auto-pull.")

    _auto_polling_fragment()

    # 5. Cartoes de Candidatos e Grafico de Projecao adaptados ao Turno
    st.markdown("---")
    latest_live_point = active_points[-1] if active_points else None

    if round_num == 2:
        render_second_round_candidate_cards(latest_point=latest_live_point)

        st.markdown("#### Evolução da Apuração e Projeção · 2º Turno")
        render_chart_guide(round_num=2)
        active_wave_live = float(latest_live_point["x"]) if latest_live_point else None
        chart_2t = build_second_round_chart(
            points=active_points,
            active_wave=active_wave_live,
            extend_to_end=True,
        )
        st.altair_chart(chart_2t, use_container_width=True, theme="streamlit")

        with st.expander("📊 Ver histórico de ondas da apuração do 2º Turno"):
            render_second_round_history_table(points=active_points)
    else:
        render_candidate_cards(latest_point=latest_live_point)

        prob_2t = latest_live_point.get("p_2turno") if latest_live_point else None
        render_p2t_banner(prob_2t=prob_2t)

        st.markdown("#### Evolução da Apuração e Projeção · 1º Turno")
        render_chart_guide(round_num=1)
        active_wave_live = float(latest_live_point["x"]) if latest_live_point else None
        chart_1t = dashboard_charts.build_projection_chart(
            points=active_points,
            active_wave=active_wave_live,
            extend_to_end=True,
        )
        st.altair_chart(chart_1t, use_container_width=True)

        with st.expander("📊 Ver histórico de ondas da apuração do 1º Turno"):
            render_history_table(points=active_points)

    # 6. Log de Requisicoes a API Oficial do TSE
    with st.expander("🌐 Log detalhado de requisições à API Oficial do TSE"):
        render_polling_log_table(st.session_state.tse_log_entries)

    # 7. Model Card
    render_model_card_expander(
        {
            "model_version": (
                "HORIZON-MRP v2026.2 "
                "(Hierarchical Optimal Regression & Inferred Zonal Outcomes Network)"
            ),
            "target_error_margin": (
                "≤ 0.50 pp a partir de 2,0% do eleitorado apurado (tempo real oficial)"
            ),
            "disclaimer": (
                f"Monitoramento ao vivo conectado à CDN do TSE para o pleito {ano_sel} · "
                f"{turno_sel} (código {election_id}). Projeções bayesianas condicionadas."
            ),
        }
    )


# Alias de retrocompatibilidade para suites de teste legadas
_render_second_round_tab = _render_real_time_tab


def _render_second_round_validation_tab() -> None:
    """Renderiza a aba de Historico e Validacao Retroativa do Modelo para o 2º Turno de 2026."""
    st.markdown("### Histórico e Validação · 2º Turno Presidencial 2026")
    st.caption(
        "Auditoria retroativa da projeção estatística onda a onda frente "
        "ao resultado oficial do TSE (5.716 municípios e 499.206 seções)."
    )

    if "slider_2t_val" not in st.session_state:
        st.session_state.slider_2t_val = 10.0

    def _set_wave_2t(target: float) -> None:
        """Define o percentual de apuracao do 2º turno de forma segura."""
        st.session_state.slider_2t_val = max(0.25, min(100.0, target))

    def _step_wave_2t(delta: float) -> None:
        """Incrementa ou decrementa o percentual do 2º turno em passos de 10%."""
        curr = float(st.session_state.get("slider_2t_val", 10.0))
        st.session_state.slider_2t_val = max(
            0.25,
            min(100.0, round((curr + delta) * 4.0) / 4.0),
        )

    col_b1, col_b2, col_b3, col_b4, col_b5 = st.columns(5)
    col_b1.button(
        "⏪ 0,25% (17h–19h)",
        use_container_width=True,
        key="btn_2t_val_1",
        on_click=_set_wave_2t,
        args=(0.25,),
    )
    col_b2.button(
        "🎯 10% (Padrão)",
        use_container_width=True,
        key="btn_2t_val_10",
        on_click=_set_wave_2t,
        args=(10.0,),
    )
    col_b3.button(
        "◀️ -10%",
        use_container_width=True,
        key="btn_2t_val_m10",
        on_click=_step_wave_2t,
        args=(-10.0,),
    )
    col_b4.button(
        "▶️ +10%",
        use_container_width=True,
        key="btn_2t_val_p10",
        on_click=_step_wave_2t,
        args=(10.0,),
    )
    col_b5.button(
        "⏩ Fim (100%)",
        use_container_width=True,
        key="btn_2t_val_100",
        on_click=_set_wave_2t,
        args=(100.0,),
    )

    current_wave_pct = st.slider(
        "Progresso do Eleitorado Apurado no 2º Turno (%):",
        min_value=0.25,
        max_value=100.0,
        step=0.25,
        format="%.2f%%",
        key="slider_2t_val",
    )
    st.session_state.replay_wave_2t = current_wave_pct
    current_wave = current_wave_pct / 100.0

    with st.spinner("Avaliando projeção retroativa do 2º Turno com dados reais do TSE..."):
        catalog_2t = get_second_round_validation_catalog()
        points_2t = generate_second_round_validation_timeline(
            catalog_2t=catalog_2t,
            current_wave=current_wave,
        )
        full_series_2t = generate_second_round_validation_timeline(
            catalog_2t=catalog_2t,
            current_wave=1.0,
        )
        val_summary = summarize_second_round_validation(full_series_2t)
        states_2t = generate_second_round_state_projections(
            catalog_2t=catalog_2t,
            wave=current_wave,
        )

    latest_point = points_2t[-1] if points_2t else None
    electorate_pct = float(latest_point["x"]) if latest_point else current_wave_pct
    updated_str = str(latest_point["t"]) if latest_point else "17:04"

    # 1. Cabecalho Editorial do 2o Turno
    render_editorial_header(
        electorate_pct=electorate_pct,
        updated_str=updated_str,
        environment="replay",
        round_num=2,
    )

    # 2. Cartoes de Candidatos (Lula vs Flavio Bolsonaro) no marco selecionado
    render_second_round_candidate_cards(latest_point=latest_point)

    # 3. Painel de Qualidade e Auditoria Retroativa do HORIZON-MRP contra o Resultado Oficial TSE
    render_second_round_validation_panel(
        latest_point=latest_point,
        validation_summary=val_summary,
    )

    # 4. Grafico Principal de Evolucao (Apurado TSE vs Projecao HORIZON-MRP vs Gabarito Final)
    st.markdown("#### Evolução da Apuração Oficial e Projeção Final · 2º Turno")
    render_chart_guide(round_num=2)

    col_v2t, _ = st.columns([2.2, 1.8])
    with col_v2t:
        view_opt_2t = st.radio(
            "Extensão da visualização do 2º Turno:",
            options=[
                "Projeção estendida até o final (100%)",
                "Série Completa de Auditoria (2% a 100%)",
            ],
            index=0,
            horizontal=True,
            key="radio_2t_view_extent",
            help=(
                "Projeção estendida exibe a trajetória e o resultado final projetado (100%) "
                "a partir do marco atual. Série Completa exibe a convergência de todos os marcos."
            ),
        )

    is_full_2t = "Completa" in view_opt_2t
    chart_points_2t = full_series_2t if is_full_2t else points_2t

    chart_main = build_second_round_chart(
        points=chart_points_2t,
        active_wave=current_wave_pct,
        final_result=val_summary.get("final_oficial"),
        extend_to_end=not is_full_2t,
    )
    st.altair_chart(chart_main, use_container_width=True, theme="streamlit")

    # 5. Grafico Comparativo de Erro Absoluto (HORIZON-MRP vs Urna Bruta)
    st.markdown('<div style="margin-top: 28px;"></div>', unsafe_allow_html=True)
    st.markdown("#### Qualidade do Modelo HORIZON-MRP: Erro Absoluto ao Longo da Apuração")
    st.caption(
        "Distância em pontos percentuais (pp) para o resultado oficial definitivo do TSE. "
        "A linha vertical destaca o marco percentual avaliado no controle acima."
    )

    col_scale, col_ext = st.columns([1.8, 2.2])
    with col_scale:
        scale_opt = st.radio(
            "Escala vertical do erro:",
            options=["Foco de Precisão (0 a 4 pp)", "Escala Ampla (0 a 20 pp)"],
            index=0,
            horizontal=True,
            key="radio_error_chart_scale",
            help="Foco de Precisão permite visualizar detalhes abaixo de 1 pp e a meta de 0,50 pp.",
        )
    with col_ext:
        ext_opt = st.radio(
            "Extensão da série avaliada:",
            options=["Série Completa (2% a 100%)", "Apenas até o marco selecionado"],
            index=0,
            horizontal=True,
            key="radio_error_chart_extent",
            help="Série Completa exibe a convergência global com cursor no marco atual.",
        )

    y_ceiling = 4.0 if "Foco" in scale_opt else 20.0
    chart_err_points = full_series_2t if "Completa" in ext_opt else points_2t

    chart_err = build_second_round_error_chart(
        points=chart_err_points,
        height=320,
        y_max=y_ceiling,
        active_wave=current_wave_pct,
    )
    st.altair_chart(chart_err, use_container_width=True, theme="streamlit")

    # 6. Tabela de Auditoria Onda a Onda
    with st.expander(
        "📊 Auditoria onda a onda: evolução das projeções, intervalos e erros (2º Turno)",
        expanded=True,
    ):
        render_second_round_history_table(points=points_2t)

    # 7. Validacao por Estado (27 UFs + Exterior ZZ)
    with st.expander("🗺️ Desempenho e validação do modelo por estado (27 UFs + Exterior ZZ)"):
        render_second_round_state_table(states_data=states_2t)

    # 8. Metodologia e Model Card
    render_model_card_expander(
        {
            "model_version": (
                "HORIZON-MRP v2026.2 "
                "(Hierarchical Optimal Regression & Inferred Zonal Outcomes Network)"
            ),
            "target_error_margin": (
                "≤ 0.50 pp a partir de 2,0% do eleitorado apurado (zero vazamento temporal)"
            ),
            "disclaimer": (
                "Auditoria retroativa executada com o modelo HORIZON-MRP sobre as "
                "totalizações municipais e estaduais oficiais divulgadas pelo TSE "
                "na eleição 6258 (2º Turno Presidencial 2026)."
            ),
        }
    )


def render_dashboard() -> None:
    """Renderiza a aplicacao visual completa com navegacao em abas de validacao e monitoramento."""
    st.set_page_config(
        page_title="Horizonte Eleitoral · Apuração e Projeção 2026",
        page_icon="🗳️",
        layout="wide",
    )

    # Injeta estilos CSS editoriais
    st.markdown(get_custom_css(), unsafe_allow_html=True)

    st.sidebar.title("🗳️ Horizonte Eleitoral")
    st.sidebar.markdown(
        """
        <div class="sidebar-model-badge">
            <div class="model-badge-header">PROJEÇÃO ESTATÍSTICA OFICIAL</div>
            <div class="model-badge-name">HORIZON-MRP</div>
            <div class="model-badge-meta">
                Hierarchical Optimal Regression & Inferred Zonal Outcomes Network
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(
        """
        ---
        **Sobre o Projeto:**
        O **Horizonte Eleitoral** prevê o resultado das eleições presidenciais
        corrigindo vieses geográficos de transmissão das urnas via Regressão
        Multinível, Pós-Estratificação (MRP) e swing calibrado por Newton-Raphson.

        Consulte o expander no topo da página para a **Documentação Geral** completa.
        """
    )

    # Forca reload do modulo de graficos para garantir atualizacao de assinaturas no Streamlit
    importlib.reload(dashboard_charts)

    # Inicializa todas as variaveis de sessao de forma preventiva
    _init_dashboard_session_state()

    # Documentacao Geral do Modelo em Destaque para Visitantes Atentos
    render_general_model_documentation()

    tab_live, tab_1t_val, tab_2t_val = st.tabs(
        [
            "⚡ Tempo Real (API Oficial do TSE)",
            "📊 Análise Histórica · 1º Turno (2026)",
            "🏆 Análise Histórica · 2º Turno (2026)",
        ]
    )

    with tab_live:
        _render_real_time_tab()

    with tab_1t_val:
        _render_first_round_tab()

    with tab_2t_val:
        _render_second_round_validation_tab()


if __name__ == "__main__":
    render_dashboard()
