"""Aplicacao Streamlit de alta precisao para acompanhamento e projecao eleitoral 2026."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import streamlit as st

from horizonte_eleitoral.config import load_settings
from horizonte_eleitoral.dashboard.charts import (
    build_projection_chart,
    build_second_round_chart,
)
from horizonte_eleitoral.dashboard.components import (
    render_candidate_cards,
    render_chart_guide,
    render_editorial_header,
    render_history_table,
    render_model_card_expander,
    render_p2t_banner,
    render_polling_log_table,
    render_polling_status_box,
    render_second_round_candidate_cards,
    render_state_diff_table,
)
from horizonte_eleitoral.dashboard.replay import (
    build_second_round_live_point,
    build_second_round_replay_point,
    generate_replay_timeline,
    generate_state_projections,
    load_replay_catalog,
)
from horizonte_eleitoral.dashboard.styles import get_custom_css
from horizonte_eleitoral.ingestion.client import TSEAsyncClient
from horizonte_eleitoral.ingestion.discovery import TSEPathResolver
from horizonte_eleitoral.ingestion.tse_live_poller import (
    TSELivePoller,
    is_election_night_window,
)

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


def _render_first_round_tab() -> None:
    """Renderiza a aba de historico e validacao do 1º Turno de 2026 com o catalogo real."""
    st.markdown("### Histórico e Validação do Modelo · 1º Turno 2026")
    st.caption(
        "Acompanhe o comportamento do algoritmo bayesiano multinível Versão 2 "
        "com dados reais consolidados de 499.206 seções eleitorais de 2026."
    )

    if "replay_wave" not in st.session_state:
        st.session_state.replay_wave = 10.0

    col_btn1, col_btn2, col_btn3, col_btn4 = st.columns(4)
    if col_btn1.button("⏪ Início (1%)", use_container_width=True, key="btn_1t_1"):
        st.session_state.replay_wave = 1.0
    if col_btn2.button("◀️ -10%", use_container_width=True, key="btn_1t_m10"):
        st.session_state.replay_wave = max(1.0, float(st.session_state.replay_wave) - 10.0)
    if col_btn3.button("▶️ +10%", use_container_width=True, key="btn_1t_p10"):
        st.session_state.replay_wave = min(100.0, float(st.session_state.replay_wave) + 10.0)
    if col_btn4.button("⏩ Fim (100%)", use_container_width=True, key="btn_1t_100"):
        st.session_state.replay_wave = 100.0

    current_wave_pct = st.slider(
        "Progresso do Eleitorado Apurado (%):",
        min_value=1.0,
        max_value=100.0,
        value=float(st.session_state.replay_wave),
        step=1.0,
        format="%.1f%%",
        key="slider_1t",
    )
    st.session_state.replay_wave = current_wave_pct
    current_wave = current_wave_pct / 100.0

    with st.spinner("Computando projeção bayesiana da rodada com o catálogo de 2026..."):
        catalog = get_replay_catalog()
        points = generate_replay_timeline(catalog=catalog, current_wave=current_wave)
        states_data = generate_state_projections(catalog=catalog, wave=current_wave)

    latest_point = points[-1] if points else None
    electorate_pct = latest_point["x"] if latest_point else current_wave_pct
    updated_str = latest_point["t"] if latest_point else "17:00"
    prob_2t = latest_point.get("p_2turno") if latest_point else None

    # Cabecalho Editorial
    render_editorial_header(
        electorate_pct=electorate_pct,
        updated_str=updated_str,
        environment="replay",
    )

    # Cartoes de Candidatos
    render_candidate_cards(latest_point=latest_point)

    # Probabilidade de 2o Turno
    render_p2t_banner(prob_2t=prob_2t)

    # Grafico Interativo Duplo em Altair
    st.markdown("#### Evolução da Apuração e Projeção Final")
    render_chart_guide()
    chart = build_projection_chart(points=points)
    st.altair_chart(chart, use_container_width=True)

    # Tabela Historica Expansivel
    with st.expander("📊 Ver os dados em tabela histórica"):
        render_history_table(points=points)

    # Projecao por Estado Expansivel
    with st.expander("🗺️ Diferença entre a urna e a pesquisa em cada estado (UFs)"):
        render_state_diff_table(states_data=states_data)

    # Metodologia e Model Card - Exclusivo Modelo Versao 2
    render_model_card_expander(
        {
            "model_version": "2026.2 (Bayesiano Multinível V2 - Elasticidade 2018–2022)",
            "target_error_margin": (
                "0.5 pp a partir de 2% do eleitorado apurado (validado em 100% da base)"
            ),
            "disclaimer": (
                "Interface conectada exclusivamente ao Modelo Versão 2. "
                "A Versão 1 encontra-se arquivada como base legada de auditoria."
            ),
        }
    )


def _init_second_round_state() -> None:
    """Inicializa as variaveis de estado de sessao necessarias para o 2º Turno."""
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


def _render_second_round_tab() -> None:
    """Renderiza a aba de Tempo Real e Projecao para o 2º Turno Majoritario Oficial."""
    _init_second_round_state()

    st.markdown("### Tempo Real Oficial TSE · 2º Turno Majoritário 2026")
    st.caption(
        "Captura oficial de dados na API do TSE com checagens automáticas a cada 5 minutos "
        "após as 17h de domingo e projeção bayesiana contínua da disputa Lula vs Bolsonaro."
    )

    settings = load_settings()
    ignore_gate = st.sidebar.checkbox(
        "Ignorar janela das 17h (Modo Teste / Demonstração)",
        value=True,
        help=(
            "Permite executar checagens e simulações na API mesmo "
            "fora do horário de votação oficial."
        ),
    )
    election_id = st.sidebar.text_input(
        "Código da Eleição 2T TSE:",
        value=settings.tse_election_id_2t,
        help="Código oficial do pleito majoritário no TSE (padrão: 6258).",
    )
    endpoint_type = st.sidebar.selectbox(
        "Tipo de Endpoint TSE:",
        options=["divulgacao", "simplificada", "totalization"],
        index=0,
        help="divulgacao (u.json completo), simplificada (r.json) ou totalization (ea20).",
    )

    is_window_active = is_election_night_window(ignore_gate=ignore_gate)

    latest_pt = (
        st.session_state.second_round_points[-1] if st.session_state.second_round_points else None
    )

    # 1. Caixa informativa com o status do monitoramento automatico
    render_polling_status_box(
        last_check_str=st.session_state.last_check_str,
        current_pct=float(st.session_state.second_round_pct),
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

    # 2. Painel de Controles e Botoes de Disparo
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

    with st.expander("🛠️ Simulação Manual de Ensaio (Opcional)", expanded=False):
        sim_step = st.selectbox(
            "Simular avanço de apuração do TSE:",
            options=[10.0, 20.0, 35.0, 50.0, 65.0, 80.0, 95.0, 100.0],
            index=2,
            format_func=lambda x: f"Onda TSE: {x:.1f}% do eleitorado apurado",
            help="Seleciona um percentual para simular a chegada de nova totalização do TSE.",
        )
        btn_sim = st.button("🚀 Forçar Passo Simulado")

    def _poll_and_update(sim_pct: float | None = None) -> tuple[bool, str]:
        now_dt = datetime.now(UTC)
        check_time_str = now_dt.strftime("%H:%M:%S UTC")
        local_time_str = now_dt.astimezone(BRASILIA_TZ).strftime("%H:%M")
        st.session_state.last_check_str = check_time_str

        tse_client = TSEAsyncClient(settings)
        resolver = TSEPathResolver(
            base_url="https://resultados.tse.jus.br",
            election_id=election_id,
        )
        poller = TSELivePoller(
            client=tse_client,
            resolver=resolver,
            election_id=election_id,
            round_num=2,
            ignore_schedule_gate=ignore_gate,
            endpoint_type=endpoint_type,
        )

        try:
            has_new, tot, status_msg = asyncio.run(poller.check_for_updates(now=now_dt))
        except Exception as exc:
            has_new = False
            tot = None
            status_msg = f"Aviso de conexão com o TSE: {exc}"

        if tot is not None and (tot.valid_votes > 0 or tot.totalized_sections > 0):
            catalog = (
                get_replay_catalog()
                if (tot.totalized_electorate / max(1, tot.total_electorate)) >= 0.02
                else None
            )
            new_point = build_second_round_live_point(
                totalization=tot,
                time_str=local_time_str,
                catalog=catalog,
            )
            existing = [
                p
                for p in st.session_state.second_round_points
                if abs(p["x"] - new_point["x"]) < 0.01 and p.get("apurado") == new_point["apurado"]
            ]
            if not existing:
                st.session_state.second_round_points.append(new_point)
                st.session_state.second_round_points.sort(key=lambda p: float(p["x"]))

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
                        "URL": poller.get_target_url(),
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
                        "URL": poller.get_target_url(),
                    }
                )
                return False, status_msg
        elif sim_pct is not None and sim_pct > float(st.session_state.second_round_pct):
            new_point = _execute_second_round_step(sim_pct)
            st.session_state.last_status_msg = (
                f"Passo simulado processado! Totalização em {new_point['x']:.2f}%."
            )
            st.session_state.tse_log_entries.append(
                {
                    "Horário": check_time_str,
                    "Status": 200,
                    "Apurado (%)": f"{new_point['x']:.2f}%",
                    "Dados Novos": "Sim",
                    "Mensagem": "Passo simulado disparado pelo operador.",
                    "URL": "simulacao://local",
                }
            )
            return True, st.session_state.last_status_msg
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
                    "Apurado (%)": f"{st.session_state.second_round_pct:.2f}%",
                    "Dados Novos": "Não",
                    "Mensagem": status_msg,
                    "URL": poller.get_target_url(),
                }
            )
            return False, status_msg

    # Sincronizacao automatica inicial ao abrir a aba
    if not st.session_state.second_round_points and "tse_initial_sync_done" not in st.session_state:
        st.session_state.tse_initial_sync_done = True
        _poll_and_update()

    # Execucao do disparo manual
    if btn_check:
        with st.spinner("Consultando API oficial do TSE e processando dados..."):
            has_new, msg = _poll_and_update()
            if has_new:
                st.success(f"✅ {msg}")
            else:
                st.info(f"ℹ️ {msg}")

    if btn_sim:
        new_point = _execute_second_round_step(sim_step)
        st.session_state.last_status_msg = (
            f"Passo simulado processado! Totalização em {new_point['x']:.2f}%."
        )
        st.session_state.tse_log_entries.append(
            {
                "Horário": datetime.now(UTC).strftime("%H:%M:%S UTC"),
                "Status": 200,
                "Apurado (%)": f"{new_point['x']:.2f}%",
                "Dados Novos": "Sim",
                "Mensagem": "Passo simulado disparado pelo operador.",
                "URL": "simulacao://local",
            }
        )
        st.success(f"✅ {st.session_state.last_status_msg}")

    # 3. Fragmento de verificacao automatica periodica (Auto-Pull)
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

    # 4. Cartoes de Candidatos do 2º Turno (Lula vs Flávio Bolsonaro)
    st.markdown("---")
    latest_2t_point = (
        st.session_state.second_round_points[-1] if st.session_state.second_round_points else None
    )

    render_second_round_candidate_cards(latest_point=latest_2t_point)

    # 5. Grafico de Projecao do 2º Turno em Altair
    st.markdown("#### Evolução da Apuração e Projeção · 2º Turno")
    chart_2t = build_second_round_chart(points=st.session_state.second_round_points)
    st.altair_chart(chart_2t, use_container_width=True)

    # 6. Tabela Historica das Ondas do 2º Turno
    with st.expander("📊 Ver histórico de ondas da apuração do 2º Turno"):
        render_history_table(points=st.session_state.second_round_points)

    # 7. Log de Requisicoes a API Oficial do TSE
    with st.expander("🌐 Log detalhado de requisições à API Oficial do TSE"):
        render_polling_log_table(st.session_state.tse_log_entries)


def render_dashboard() -> None:
    """Renderiza a aplicacao visual completa com navegacao em duas abas especializadas."""
    st.set_page_config(
        page_title="Horizonte Eleitoral · Apuração e Projeção 2026",
        page_icon="🗳️",
        layout="wide",
    )

    # Injeta estilos CSS editoriais
    st.markdown(get_custom_css(), unsafe_allow_html=True)

    st.sidebar.title("🗳️ Horizonte Eleitoral")
    st.sidebar.caption(
        "Sistema de Projeção Bayesiana Multinível V2 com Elasticidade Municipal 2018–2022."
    )

    # Estrutura principal dividida em duas abas
    tab_1t, tab_2t = st.tabs(
        [
            "📊 Histórico do 1º Turno (Validação e Replay)",
            "⚡ Tempo Real - 2º Turno (Apuração Oficial TSE)",
        ]
    )

    with tab_1t:
        _render_first_round_tab()

    with tab_2t:
        _render_second_round_tab()


if __name__ == "__main__":
    render_dashboard()
