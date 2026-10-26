"""Componentes visuais e funcoes puras de formatacao para o dashboard Streamlit."""

from __future__ import annotations

from typing import Any

import streamlit as st

CANDIDATE_METADATA: dict[str, dict[str, str]] = {
    "PT": {"nome": "Lula", "partido": "PT", "bloco": "PT", "cor": "#e34948"},
    "PL": {"nome": "Flávio Bolsonaro", "partido": "PL", "bloco": "PL", "cor": "#2a78d6"},
    "OUTROS": {"nome": "Outros candidatos", "partido": "", "bloco": "OUTROS", "cor": "#8a8983"},
}

# Peso aproximado de cada estado no colegio eleitoral brasileiro
UF_ELECTORATE_WEIGHT: dict[str, float] = {
    "SP": 22.16,
    "MG": 10.41,
    "RJ": 8.23,
    "BA": 7.11,
    "RS": 5.40,
    "PR": 5.37,
    "PE": 4.54,
    "CE": 4.31,
    "PA": 3.93,
    "SC": 3.58,
    "GO": 3.12,
    "MA": 3.11,
    "PB": 2.00,
    "ES": 1.90,
    "AM": 1.70,
    "RN": 1.69,
    "AL": 1.54,
    "PI": 1.52,
    "MT": 1.50,
    "DF": 1.44,
    "MS": 1.30,
    "SE": 1.08,
    "RO": 0.81,
    "TO": 0.70,
    "AC": 0.38,
    "AP": 0.37,
    "RR": 0.24,
}


def fmt_pct(val: float | None, decimals: int = 1) -> str:
    """Formata valor numerico em string percentual com virgula no padrao brasileiro.

    Args:
        val: Valor numerico ou None.
        decimals: Quantidade de casas decimais.

    Returns:
        String percentual formatada (ex: '45,2%') ou '–' se None.

    Raises:
        None.
    """
    if val is None:
        return "–"
    return f"{val:.{decimals}f}".replace(".", ",") + "%"


def format_staleness_badge(stale_seconds: int) -> tuple[str, str]:
    """Determina o rotulo e o estilo do indicador de defasagem temporal.

    Args:
        stale_seconds: Tempo decorrido em segundos desde o corte dos dados.

    Returns:
        Tupla com (texto_exibicao, nivel_alerta).

    Raises:
        None.
    """
    minutes = stale_seconds // 60
    if stale_seconds < 120:
        return f"Atualizado há {stale_seconds}s", "normal"
    if stale_seconds < 600:
        return f"Atualizado há {minutes} min", "normal"
    if stale_seconds < 1800:
        return f"Alerta: dados com {minutes} min de defasagem", "warning"
    return f"Crítico: dados desatualizados ({minutes} min)", "error"


def parse_group_card_metrics(group_data: dict[str, Any]) -> dict[str, str]:
    """Extrai e formata os rotulos dos cards de um grupo politico.

    Args:
        group_data: Dicionario contendo code, observed_share, projected_share, q05, q95.

    Returns:
        Dicionario formatado com textos claros para Apurado e Projecao.

    Raises:
        None.
    """
    code = str(group_data.get("code", "OUTROS"))
    obs = float(group_data.get("observed_share", 0.0))
    proj = float(group_data.get("projected_share", 0.0))
    q05 = float(group_data.get("q05", 0.0))
    q95 = float(group_data.get("q95", 0.0))

    return {
        "title": f"Candidatura {code}",
        "projected_display": f"{proj:.1f}%",
        "ci_display": f"IC 90%: [{q05:.1f}% - {q95:.1f}%]",
        "observed_display": f"{obs:.1f}% apurado",
    }


def render_editorial_header(
    electorate_pct: float,
    updated_str: str,
    environment: str = "oficial",
    status_text: str = "",
    round_num: int = 1,
) -> None:
    """Renderiza o cabecalho institucional editorial identico ao da aplicacao de referencia.

    Args:
        electorate_pct: Percentual do eleitorado nas secoes totalizadas pelo TSE.
        updated_str: Horario ou data da ultima atualizacao dos dados.
        environment: Ambiente da execucao ('oficial', 'replay' ou 'simulado').
        status_text: Mensagem textual opcional adicional de status.
        round_num: Turno da eleicao presidencial (1 ou 2).

    Returns:
        None.

    Raises:
        None.
    """
    turno_label = "2º turno" if round_num == 2 else "1º turno"
    st.markdown(
        f'<p class="editorial-sobretitulo">Eleições 2026 · Presidente · {turno_label}</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<h1 class="editorial-titulo">Apuração com projeção do resultado final</h1>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="editorial-autoria">por <strong>Horizonte Eleitoral</strong> · '
        "Análise temporal e validação estatística</p>",
        unsafe_allow_html=True,
    )

    # Dica sutil para navegacao mobile
    st.markdown(
        '<div class="mobile-sidebar-hint">💡 <strong>Dica:</strong> Toque no ícone '
        "<strong>&gt;&gt;</strong> no topo esquerdo para acessar os controles de apuração.</div>",
        unsafe_allow_html=True,
    )

    # Selo de alerta sobre a confiabilidade estatistica
    if electorate_pct < 2.0:
        badge_html = '<span class="selo-alerta">projeção imprecisa até 2% apurado</span>'
    elif electorate_pct < 5.0:
        badge_html = '<span class="selo-alerta">projeção preliminar</span>'
    else:
        badge_html = '<span class="selo-estavel">projeção estável</span>'

    pct_str = f"{electorate_pct:.2f}%".replace(".", ",")
    if "–" in updated_str:
        hora_str = updated_str
    elif " " in updated_str:
        hora_str = updated_str.split()[-1]
    else:
        hora_str = updated_str[-8:] if len(updated_str) >= 8 else updated_str

    status_bar_html = (
        f'<div class="editorial-status-bar">'
        f"<span><strong>{pct_str}</strong> do eleitorado apurado · atualizado às "
        f"<strong>{hora_str}</strong></span>"
        f"{badge_html}"
        f"</div>"
    )
    st.markdown(status_bar_html, unsafe_allow_html=True)

    # Avisos de ambiente
    if environment == "replay" and round_num == 2:
        st.markdown(
            '<div class="banner-aviso">'
            "<strong>Auditoria Retroativa (Dados Oficiais TSE):</strong> reprodução fiel do "
            "2º turno de 25/10/2026 — incluindo a paralisação em <strong>0,25%</strong> entre "
            "<strong>17h07 e 19h00 BRT</strong> (prorrogação do STF) e a retomada nacional após "
            "as <strong>19h00 BRT</strong> — confrontando a projeção estatística "
            "com o resultado final do TSE."
            "</div>",
            unsafe_allow_html=True,
        )
    elif environment == "replay":
        st.markdown(
            '<div class="banner-aviso">'
            "<strong>Demonstração:</strong> reprodução da apuração na ordem real de chegada "
            "dos boletins de urna do TSE com a projeção bayesiana do 1º turno."
            "</div>",
            unsafe_allow_html=True,
        )
    elif environment == "simulado":
        st.markdown(
            '<div class="banner-aviso">'
            "<strong>Simulação Sintética:</strong> dados gerados com variabilidade empírica "
            "para testes de estresse operacional e latência."
            "</div>",
            unsafe_allow_html=True,
        )


def render_p2t_banner(prob_2t: float | None) -> None:
    """Renderiza o painel visual estruturado com a probabilidade estimada de 2o turno.

    Apresenta linguagem editorial clara, indicador semantico e barra visual de probabilidade.

    Args:
        prob_2t: Fracao no intervalo [0, 1] ou None se ainda indisponivel.

    Returns:
        None.

    Raises:
        None.
    """
    if prob_2t is None:
        p2t_display = "–"
        fill_pct = 0.0
        badge_text = "Aguardando dados"
    elif prob_2t >= 0.995:
        p2t_display = "> 99%"
        fill_pct = 99.0
        badge_text = "Praticamente certo"
    elif prob_2t <= 0.005:
        p2t_display = "< 1%"
        fill_pct = 1.0
        badge_text = "Improvável"
    else:
        pct_num = round(prob_2t * 100)
        p2t_display = f"{pct_num}%"
        fill_pct = float(pct_num)
        if pct_num >= 90:
            badge_text = "Altíssima probabilidade"
        elif pct_num >= 65:
            badge_text = "Provável"
        elif pct_num >= 35:
            badge_text = "Cenário aberto"
        else:
            badge_text = "Pouco provável"

    banner_html = (
        f'<div class="painel-p2t-container">'
        f'<div class="painel-p2t-topo">'
        f'<span class="painel-p2t-titulo">'
        f"Chance de decisão em 2º turno (sem maioria absoluta no 1º turno):"
        f"</span>"
        f'<div class="painel-p2t-lado-direito">'
        f'<span class="p2t-badge">{badge_text}</span>'
        f'<span class="p2t-destaque">{p2t_display}</span>'
        f"</div>"
        f"</div>"
        f'<div class="p2t-barra-trilha">'
        f'<div class="p2t-barra-preenchimento" style="width: {fill_pct:.1f}%;"></div>'
        f"</div>"
        f'<div class="painel-p2t-subtitulo">'
        f"Estimativa bayesiana baseada nas simulações preditivas: probabilidade de que nenhum "
        f"candidato alcance 50% + 1 dos votos válidos na apuração definitiva de hoje."
        f"</div>"
        f"</div>"
    )
    st.markdown(banner_html, unsafe_allow_html=True)


def render_candidate_cards(
    latest_point: dict[str, Any] | None,
    groups_payload: list[dict[str, Any]] | None = None,
) -> None:
    """Renderiza a grade de 3 cartoes de candidatos com hierarquia clara e identificador de lider.

    Apresenta em primeiro plano a projecao com faixa de confianca e, em bloco secundario destacado,
    o percentual ja totalizado na urna pelo TSE com esclarecimento de viés de contagem.

    Args:
        latest_point: Dicionario do ponto mais recente com apurado, projecao e faixa.
        groups_payload: Lista opcional vinda da API oficial caso latest_point seja None.

    Returns:
        None.

    Raises:
        None.
    """
    col_pt, col_pl, col_outros = st.columns(3)
    blocos = [("PT", col_pt), ("PL", col_pl), ("OUTROS", col_outros)]

    # 1. Extrai valores para identificar o lider da projecao
    cand_data: dict[str, dict[str, Any]] = {}
    for bloco, _ in blocos:
        obs_val: float | None = None
        proj_val: float | None = None
        q05_val: float | None = None
        q95_val: float | None = None

        if latest_point is not None:
            obs_map = latest_point.get("apurado") or {}
            obs_val = obs_map.get(bloco)

            proj_map = latest_point.get("projecao")
            if proj_map and bloco in proj_map:
                proj_val = proj_map[bloco]

            faixa_map = latest_point.get("faixa")
            if faixa_map and bloco in faixa_map and faixa_map[bloco]:
                q05_val = faixa_map[bloco][0]
                q95_val = faixa_map[bloco][1]
        elif groups_payload is not None:
            for g in groups_payload:
                if g.get("code") == bloco:
                    obs_val = float(g.get("observed_share", 0.0))
                    proj_val = float(g.get("projected_share", 0.0))
                    q05_val = float(g.get("q05", 0.0))
                    q95_val = float(g.get("q95", 0.0))
                    break

        cand_data[bloco] = {
            "obs": obs_val,
            "proj": proj_val,
            "q05": q05_val,
            "q95": q95_val,
        }

    # Identifica o lider projetado (apenas entre candidaturas principais)
    proj_pt = cand_data["PT"]["proj"] or 0.0
    proj_pl = cand_data["PL"]["proj"] or 0.0
    lider_bloco = "PT" if proj_pt > proj_pl else ("PL" if proj_pl > proj_pt else "")

    for bloco, col in blocos:
        meta = CANDIDATE_METADATA.get(bloco, {"nome": bloco, "partido": "", "cor": "#64748b"})
        nome = meta["nome"]
        partido = f"({meta['partido']})" if meta["partido"] else ""

        obs_val = cand_data[bloco]["obs"]
        proj_val = cand_data[bloco]["proj"]
        q05_val = cand_data[bloco]["q05"]
        q95_val = cand_data[bloco]["q95"]

        is_lider = bloco == lider_bloco and proj_val is not None and bloco != "OUTROS"
        badge_lider_html = (
            '<span class="cartao-badge-lider">Líder projetado</span>' if is_lider else ""
        )
        card_class = "cartao-candidato cartao-lider" if is_lider else "cartao-candidato"

        # Formata textos dos cartoes
        if proj_val is not None:
            valor_proj_str = f"{proj_val:.2f}".replace(".", ",")
            rotulo_str = "Projeção do resultado final"
            if q05_val is not None and q95_val is not None:
                q05_s = f"{q05_val:.2f}".replace(".", ",")
                q95_s = f"{q95_val:.2f}".replace(".", ",")
                faixa_str = f'<div class="cartao-faixa">Intervalo de 90%: {q05_s}% – {q95_s}%</div>'
            else:
                faixa_str = ""
        elif obs_val is not None:
            valor_proj_str = f"{obs_val:.2f}".replace(".", ",")
            rotulo_str = "Projeção preliminar (< 2% apurado)"
            faixa_str = '<div class="cartao-faixa">Aguardando dados para IC</div>'
        else:
            valor_proj_str = "–"
            rotulo_str = "Aguardando apuração"
            faixa_str = ""

        obs_str = f"{obs_val:.2f}%".replace(".", ",") if obs_val is not None else "–"

        # Explicacao de vies quando ha diferenca perceptivel entre urna e projecao
        vies_nota = ""
        if proj_val is not None and obs_val is not None and abs(proj_val - obs_val) >= 2.0:
            diff = proj_val - obs_val
            sinal = "+" if diff > 0 else ""
            diff_str = f"{sinal}{diff:.1f} pp".replace(".", ",")
            vies_nota = (
                f'<div class="cartao-vies-nota">'
                f"Diferença de {diff_str} decorre da ordem de apuração regional das urnas."
                "</div>"
            )

        val_html = (
            f'<div class="cartao-valor-destaque">{valor_proj_str}'
            '<span style="font-size: 0.5em; color: var(--texto-mut);">%</span></div>'
        )

        card_html = (
            f'<div class="{card_class}">'
            f'<div class="cartao-cabecalho">'
            f'<span class="chave-cor chave-{bloco}"></span>'
            f"<span>{nome}</span>"
            f'<span class="cartao-partido">{partido}</span>'
            f"{badge_lider_html}"
            f"</div>"
            f"{val_html}"
            f'<div class="cartao-rotulo">{rotulo_str}</div>'
            f"{faixa_str}"
            f'<div class="cartao-apurado-container">'
            f'<span class="cartao-apurado-label">Votos na urna agora:</span>'
            f'<span class="cartao-apurado-valor">{obs_str}</span>'
            f"</div>"
            f"{vies_nota}"
            f"</div>"
        )
        with col:
            st.markdown(card_html, unsafe_allow_html=True)


def format_table_projection_cell(
    bloco: str,
    proj: dict[str, float] | None,
    faixa: dict[str, list[float]] | None,
) -> str:
    """Formata celula da tabela com valor pontual projetado e intervalo de confianca.

    Args:
        bloco: Codigo do grupo politico ('PT', 'PL', 'OUTROS').
        proj: Dicionario de projecoes pontuais ou None.
        faixa: Dicionario com tuplas/listas [q05, q95] ou None.

    Returns:
        String formatada com '45,20% (44,50–45,90)' ou '–'.

    Raises:
        None.
    """
    if proj and bloco in proj:
        val = f"{proj[bloco]:.2f}".replace(".", ",")
        if faixa and bloco in faixa and faixa[bloco]:
            f0 = f"{faixa[bloco][0]:.2f}".replace(".", ",")
            f1 = f"{faixa[bloco][1]:.2f}".replace(".", ",")
            return f"{val}% ({f0}–{f1})"
        return f"{val}%"
    return "–"


def render_history_table(points: list[dict[str, Any]]) -> None:
    """Renderiza a tabela detalhada do historico de pontos de apuracao.

    Args:
        points: Lista de pontos em ordem cronologica.

    Returns:
        None.

    Raises:
        None.
    """
    if not points:
        st.info("Nenhum registro histórico disponível.")
        return

    table_rows: list[dict[str, str]] = []
    # Mostra do mais recente para o mais antigo
    for p in reversed(points):
        t_str = str(p.get("t", ""))
        x_val = float(p.get("x", 0.0))
        x_str = (
            f"{x_val:.2f}%".replace(".", ",") if x_val < 1.0 else f"{x_val:.1f}%".replace(".", ",")
        )
        obs = p.get("apurado") or {}
        proj = p.get("projecao")
        faixa = p.get("faixa") or {}

        # Identifica se a projecao ainda estava em fase preliminar
        pt_proj_cell = (
            format_table_projection_cell("PT", proj, faixa)
            if x_val >= 2.0
            else "– (Aguardando > 2%)"
        )
        pl_proj_cell = (
            format_table_projection_cell("PL", proj, faixa)
            if x_val >= 2.0
            else "– (Aguardando > 2%)"
        )
        outros_proj_cell = (
            format_table_projection_cell("OUTROS", proj, faixa)
            if x_val >= 2.0
            else "– (Aguardando > 2%)"
        )

        table_rows.append(
            {
                "Horário": t_str,
                "% Apurado": x_str,
                "Lula (PT) Urna": fmt_pct(obs.get("PT"), 2),
                "Lula (PT) Projeção [IC 90%]": pt_proj_cell,
                "Flávio (PL) Urna": fmt_pct(obs.get("PL"), 2),
                "Flávio (PL) Projeção [IC 90%]": pl_proj_cell,
                "Outros Urna": fmt_pct(obs.get("OUTROS"), 2),
                "Outros Projeção [IC 90%]": outros_proj_cell,
            }
        )

    st.dataframe(table_rows, hide_index=True, use_container_width=True)


def render_state_diff_table(states_data: list[dict[str, Any]]) -> None:
    """Renderiza a tabela de diferenca entre urna e pesquisa por estado (UF).

    Permite ordenacao por maior colegio eleitoral, percentual apurado ou ordem alfabetica.

    Args:
        states_data: Lista de registros por estado com 'uf', 'x', 'PT', 'PL', 'diff_PT', 'diff_PL'.

    Returns:
        None.

    Raises:
        None.
    """
    if not states_data:
        st.info("Dados por estado ainda não disponíveis.")
        return

    st.markdown(
        """
        <p style="font-size: 0.88rem; color: var(--texto-mut); margin-bottom: 8px;">
            Projeção do resultado final em cada estado (% dos votos válidos) e a diferença
            em pontos percentuais para a última pesquisa divulgada (convertida para válidos).
        </p>
        """,
        unsafe_allow_html=True,
    )

    col_sort, _ = st.columns([2, 3])
    with col_sort:
        sort_mode = st.selectbox(
            "Ordenar estados por:",
            options=[
                "Maior Colégio Eleitoral (SP, MG, RJ, BA...)",
                "Mais Apurados Primeiro (% Apurado)",
                "Ordem Alfabética (UF)",
            ],
            index=0,
            key="sort_uf_table",
        )

    sorted_states = list(states_data)
    if sort_mode.startswith("Maior"):
        sorted_states.sort(key=lambda s: UF_ELECTORATE_WEIGHT.get(s["uf"], 0.0), reverse=True)
    elif sort_mode.startswith("Mais"):
        sorted_states.sort(key=lambda s: float(s["x"]), reverse=True)
    else:
        sorted_states.sort(key=lambda s: s["uf"])

    formatted_rows: list[dict[str, str]] = []
    for s in sorted_states:
        uf = s["uf"]
        x_val = s["x"]
        x_str = f"{x_val:.1f}%".replace(".", ",")
        pt_val = s["PT"]
        pl_val = s["PL"]
        diff_pt = s.get("diff_PT", 0.0)
        diff_pl = s.get("diff_PL", 0.0)

        sign_pt = "+" if diff_pt > 0 else ""
        sign_pl = "+" if diff_pl > 0 else ""

        pt_display = f"{pt_val:.1f}% ({sign_pt}{diff_pt:.1f} pp)".replace(".", ",")
        pl_display = f"{pl_val:.1f}% ({sign_pl}{diff_pl:.1f} pp)".replace(".", ",")

        status_uf = "Totalizado" if x_val >= 99.0 else ("Em apuração" if x_val >= 2.0 else "Início")
        lider_estado = "Lula (PT)" if pt_val > pl_val else "Flávio (PL)"
        peso_str = (
            f"{UF_ELECTORATE_WEIGHT.get(uf, 0.0):.1f}%".replace(".", ",")
            if uf in UF_ELECTORATE_WEIGHT
            else "–"
        )

        formatted_rows.append(
            {
                "UF": uf,
                "Peso Brasil": peso_str,
                "% Apurado": x_str,
                "Líder Projetado": lider_estado,
                "Lula (PT) Projeção (vs Pesquisa)": pt_display,
                "Flávio (PL) Projeção (vs Pesquisa)": pl_display,
                "Status": status_uf,
            }
        )

    st.dataframe(formatted_rows, hide_index=True, use_container_width=True)


def render_model_card_expander(card_info: dict[str, Any] | None) -> None:
    """Renderiza a ficha tecnica metodologica institucional (Model Card) em cards estruturados.

    Args:
        card_info: Dicionario com metadados metodologicos ou None para valores padrao.

    Returns:
        None.

    Raises:
        None.
    """
    with st.expander("ℹ️ Método e Transparência Metodológica"):
        st.markdown(
            """
            <div class="model-card-grid">
                <div class="model-card-box">
                    <div class="model-card-box-titulo">📥 Fontes de Dados Oficiais</div>
                    <div class="model-card-box-desc">
                        A cada ciclo de apuração são processados os arquivos de totalização do TSE.
                        Divergências entre arquivos são reconciliadas antes da emissão de qualquer
                        estimativa para garantir integridade.
                    </div>
                </div>
                <div class="model-card-box">
                    <div class="model-card-box-titulo">📍 Pareamento Territorial</div>
                    <div class="model-card-box-desc">
                        Cada seção de 2026 é pareada com o resultado de 2022 do seu próprio
                        local de votação (ou vizinhança geográfica mais próxima). 93%+ possuem
                        pareamento exato no mesmo local.
                    </div>
                </div>
                <div class="model-card-box">
                    <div class="model-card-box-titulo">🧮 HORIZON-MRP com Elasticidade</div>
                    <div class="model-card-box-desc">
                        O <strong>HORIZON-MRP</strong>
                        (Hierarchical Optimal Regression & Inferred Zonal Outcomes Network)
                        modula o encolhimento bayesiano (shrinkage) de cada município com base
                        na sua volatilidade histórica entre 2018 e 2022. Municípios mais elásticos
                        absorvem os dados da urna de 2026 mais rápido.
                    </div>
                </div>
                <div class="model-card-box">
                    <div class="model-card-box-titulo">🏛️ Arquivamento da Versão 1</div>
                    <div class="model-card-box-desc">
                        O Modelo Versão 1 (apenas 2022/2026 com encolhimento fixo) foi arquivado
                        e documentado como baseline legado. O dashboard conecta-se exclusivamente
                        ao HORIZON-MRP após vitória no benchmark de 100% da base.
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if card_info:
            st.markdown("---")
            col_v, col_m = st.columns(2)
            with col_v:
                mod_ver = card_info.get("model_version", "HORIZON-MRP v2026.2")
                st.markdown(f"**Versão do Modelo:** `{mod_ver}`")
            with col_m:
                meta_err = card_info.get("target_error_margin", "0.5 pp")
                st.markdown(f"**Meta Histórica de Erro:** {meta_err}")
            st.caption(f"_{card_info.get('disclaimer', '')}_")


def build_chart_guide_html(round_num: int = 1) -> str:
    """Gera o HTML editorial contendo a orientacao de leitura e a legenda visual dos graficos.

    Apresenta a descricao conceitual da convergencia entre votos apurados e projecao final,
    alem de duas secoes de legenda:
    1. Convencao de Linhas e Camadas: linha solida (apurado TSE), linha tracejada
       (projecao final), area sombreada (faixa de 90%) e linha pontilhada (limiar de 50%).
    2. Convencao de Candidaturas: cores associadas ao PT, PL e (no 1º turno) Outros candidatos.

    Args:
        round_num: Turno da eleicao presidencial (1 ou 2).

    Returns:
        String contendo a estrutura HTML formatada com classes CSS do dashboard.

    Raises:
        None.
    """
    linha_50_label = "50% (Maioria Absoluta)" if round_num == 2 else "50% (1º Turno)"
    gabarito_html = (
        """
                <span class="grafico-legenda-item">
                    <span class="amostra-linha-gabarito"></span>
                    <span>Resultado Final TSE (100%)</span>
                </span>"""
        if round_num == 2
        else ""
    )
    outros_html = (
        ""
        if round_num == 2
        else """
                <span class="grafico-legenda-item">
                    <span class="chave-cor chave-OUTROS"></span>
                    <span>Outros (soma)</span>
                </span>"""
    )
    return f"""
    <div class="grafico-guia-container">
        <div class="grafico-descricao">
            <strong>Como interpretar:</strong> O gráfico apresenta a convergência entre os
            <strong>votos apurados</strong> divulgados pelo TSE e a <strong>projeção final</strong>
            estimada pelo modelo HORIZON-MRP (Bayesiano Multinível). À medida que mais seções
            são totalizadas (eixo horizontal), o modelo corrige vieses regionais e a margem de
            incerteza estatística (faixa sombreada) se estreita em direção ao resultado definitivo.
        </div>
        <div class="grafico-legenda-grid">
            <div class="grafico-legenda-bloco">
                <span class="grafico-legenda-titulo">SÉRIES:</span>
                <span class="grafico-legenda-item">
                    <span class="amostra-linha-solida"></span>
                    <span>Apurado (TSE)</span>
                </span>
                <span class="grafico-legenda-item">
                    <span class="amostra-linha-tracejada"></span>
                    <span>Projeção Final</span>
                </span>
                <span class="grafico-legenda-item">
                    <span class="amostra-faixa-ic"></span>
                    <span>Faixa de 90% (IC)</span>
                </span>
                <span class="grafico-legenda-item">
                    <span class="amostra-linha-50"></span>
                    <span>{linha_50_label}</span>
                </span>{gabarito_html}
            </div>
            <div class="grafico-legenda-bloco">
                <span class="grafico-legenda-titulo">CANDIDATURAS:</span>
                <span class="grafico-legenda-item">
                    <span class="chave-cor chave-PT"></span>
                    <span>Lula (PT)</span>
                </span>
                <span class="grafico-legenda-item">
                    <span class="chave-cor chave-PL"></span>
                    <span>Flávio Bolsonaro (PL)</span>
                </span>{outros_html}
            </div>
        </div>
    </div>
    """


def render_chart_guide(round_num: int = 1) -> None:
    """Renderiza a descricao e a legenda visual dos graficos no dashboard Streamlit.

    Args:
        round_num: Turno da eleicao presidencial (1 ou 2).

    Returns:
        None.

    Raises:
        None.
    """
    st.markdown(build_chart_guide_html(round_num=round_num), unsafe_allow_html=True)


def render_second_round_candidate_cards(
    latest_point: dict[str, Any] | None = None,
    groups_payload: list[dict[str, Any]] | None = None,
) -> None:
    """Renderiza os cartoes de destaque da disputa direta do 2º Turno (Lula vs Bolsonaro).

    Exibe os percentuais apurados no TSE, projecoes finais com intervalo de 90%
    e probabilidade de vitoria majoritaria para cada candidato.

    Args:
        latest_point: Ponto cronologico mais recente com apurado, projecao e faixa.
        groups_payload: Lista opcional de dicionarios de grupos da API REST.

    Returns:
        None.

    Raises:
        None.
    """
    # 1. Extracao de dados a partir de groups_payload (API) ou latest_point (Replay/Poller)
    data_pt: dict[str, Any] = {"obs": 0.0, "proj": None, "q05": None, "q95": None}
    data_pl: dict[str, Any] = {"obs": 0.0, "proj": None, "q05": None, "q95": None}

    if groups_payload:
        for g in groups_payload:
            code = g.get("code")
            wp = g.get("win_probability")
            win_prob_val = float(wp) if wp is not None else None
            if code == "PT":
                data_pt = {
                    "obs": float(g.get("observed_share", 0.0)),
                    "proj": float(g.get("projected_share", 0.0)),
                    "q05": float(g.get("q05", 0.0)),
                    "q95": float(g.get("q95", 0.0)),
                    "win_prob": win_prob_val,
                }
            elif code == "PL":
                data_pl = {
                    "obs": float(g.get("observed_share", 0.0)),
                    "proj": float(g.get("projected_share", 0.0)),
                    "q05": float(g.get("q05", 0.0)),
                    "q95": float(g.get("q95", 0.0)),
                    "win_prob": win_prob_val,
                }
    elif latest_point:
        ap = latest_point.get("apurado", {})
        pr = latest_point.get("projecao") or {}
        fa = latest_point.get("faixa") or {}
        wp_map = latest_point.get("win_probability") or {}

        data_pt["obs"] = float(ap.get("PT", 0.0))
        if pr and "PT" in pr:
            data_pt["proj"] = float(pr["PT"])
            if fa and "PT" in fa:
                data_pt["q05"] = float(fa["PT"][0])
                data_pt["q95"] = float(fa["PT"][1])
        if wp_map and "PT" in wp_map:
            data_pt["win_prob"] = float(wp_map["PT"])

        data_pl["obs"] = float(ap.get("PL", 0.0))
        if pr and "PL" in pr:
            data_pl["proj"] = float(pr["PL"])
            if fa and "PL" in fa:
                data_pl["q05"] = float(fa["PL"][0])
                data_pl["q95"] = float(fa["PL"][1])
        if wp_map and "PL" in wp_map:
            data_pl["win_prob"] = float(wp_map["PL"])

    # 2. Calculo da probabilidade estatistica de vitoria baseada na simulacao Monte Carlo
    wp_pt = data_pt.get("win_prob")
    wp_pl = data_pl.get("win_prob")
    has_projection = data_pt["proj"] is not None and data_pl["proj"] is not None

    if wp_pt is not None and wp_pl is not None:
        pt_prob_win = max(0.1, min(99.9, round(wp_pt * 100.0, 1)))
        pl_prob_win = max(0.1, min(99.9, round(wp_pl * 100.0, 1)))
    elif has_projection:
        margin = float(data_pt["proj"] or 0.0) - 50.0
        pt_prob_win = max(1.0, min(99.0, 50.0 + margin * 20.0))
        pl_prob_win = 100.0 - pt_prob_win
    else:
        pt_prob_win = 50.0
        pl_prob_win = 50.0

    pt_proj_val = (
        fmt_pct(data_pt["proj"], decimals=2)
        if data_pt["proj"]
        else fmt_pct(data_pt["obs"], decimals=2)
    )
    pt_ci_val = (
        f"IC 90%: [{fmt_pct(data_pt['q05'], decimals=2)} – {fmt_pct(data_pt['q95'], decimals=2)}]"
        if data_pt["q05"]
        else "Projeção preliminar (< 2% apurado)"
    )
    pt_lead = " (Liderança)" if pt_prob_win > 50 else ""

    pl_proj_val = (
        fmt_pct(data_pl["proj"], decimals=2)
        if data_pl["proj"]
        else fmt_pct(data_pl["obs"], decimals=2)
    )
    pl_ci_val = (
        f"IC 90%: [{fmt_pct(data_pl['q05'], decimals=2)} – {fmt_pct(data_pl['q95'], decimals=2)}]"
        if data_pl["q05"]
        else "Projeção preliminar (< 2% apurado)"
    )
    pl_lead = " (Liderança)" if pl_prob_win > 50 else ""

    if has_projection:
        pt_cls = "chance-lider" if pt_prob_win >= 50 else "chance-secundario"
        pl_cls = "chance-lider" if pl_prob_win > 50 else "chance-secundario"
        pt_footer_html = (
            f'<div class="chance-vitoria-box {pt_cls}">'
            f"🏆 Chance de Vitória: {pt_prob_win:.1f}%{pt_lead}"
            f"</div>"
        )
        pl_footer_html = (
            f'<div class="chance-vitoria-box {pl_cls}">'
            f"🏆 Chance de Vitória: {pl_prob_win:.1f}%{pl_lead}"
            f"</div>"
        )
    else:
        pt_footer_html = (
            '<div class="chance-vitoria-box chance-preliminar">'
            "⏳ Projeção consolidada e IC a partir de 2,0% apurado"
            "</div>"
        )
        pl_footer_html = (
            '<div class="chance-vitoria-box chance-preliminar">'
            "⏳ Projeção consolidada e IC a partir de 2,0% apurado"
            "</div>"
        )

    col1, col2 = st.columns(2)

    with col1:
        st.markdown(
            f"""
            <div class="card-candidato card-candidato-pt">
                <div class="card-cand-header">
                    <span class="card-nome">Lula</span>
                    <span class="badge-partido badge-partido-pt">PT · 13</span>
                </div>
                <div class="card-projecao card-projecao-pt">
                    {pt_proj_val}
                </div>
                <div class="card-faixa">
                    {pt_ci_val}
                </div>
                <div class="card-apurado">
                    Oficial apurado: <strong>{fmt_pct(data_pt["obs"], decimals=2)}</strong>
                </div>
                {pt_footer_html}
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(
            f"""
            <div class="card-candidato card-candidato-pl">
                <div class="card-cand-header">
                    <span class="card-nome">Flávio Bolsonaro</span>
                    <span class="badge-partido badge-partido-pl">PL · 22</span>
                </div>
                <div class="card-projecao card-projecao-pl">
                    {pl_proj_val}
                </div>
                <div class="card-faixa">
                    {pl_ci_val}
                </div>
                <div class="card-apurado">
                    Oficial apurado: <strong>{fmt_pct(data_pl["obs"], decimals=2)}</strong>
                </div>
                {pl_footer_html}
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_polling_status_box(
    last_check_str: str,
    current_pct: float,
    is_auto_active: bool,
    is_window_open: bool,
    status_message: str = "",
    *,
    totalized_sections: int | None = None,
    total_sections: int | None = None,
    sections_pct: float | None = None,
    totalized_electorate: int | None = None,
    total_electorate: int | None = None,
    electorate_pct: float | None = None,
    tse_timestamp_str: str | None = None,
) -> None:
    """Renderiza a caixa visual informativa de status da sincronizacao com o TSE.

    Exibe os percentuais e contagens oficiais de secoes totalizadas e eleitorado apurado,
    com formatacao no padrao brasileiro (pt-BR) e compatibilidade com o portal do TSE.

    Args:
        last_check_str: Horario da ultima checagem na API do TSE.
        current_pct: Percentual atual de apuracao (padrao de compatibilidade).
        is_auto_active: Se o polling automatico a cada 5 min esta ativo.
        is_window_open: Se a janela oficial das 17h de domingo esta aberta.
        status_message: Mensagem detalhada sobre o ultimo retorno da API.
        totalized_sections: Quantidade de secoes eleitorais ja totalizadas.
        total_sections: Total geral de secoes eleitorais no pleito.
        sections_pct: Percentual oficial de secoes totalizadas (ex: 0.25 para 0,25%).
        totalized_electorate: Total de eleitores aptos nas secoes apuradas.
        total_electorate: Total nacional de eleitores aptos a votar.
        electorate_pct: Percentual do eleitorado ja totalizado (ex: 0.43 para 0,43%).
        tse_timestamp_str: Timestamp oficial emitido pelo TSE (ex: '25/10/2026 17:06:27').

    Returns:
        None.

    Raises:
        None.
    """
    badge_cls = (
        "status-badge-active" if is_window_open or is_auto_active else "status-badge-waiting"
    )
    badge_title = (
        "🟢 MONITORAMENTO AUTOMÁTICO ATIVO (A CADA 5 MIN)"
        if is_window_open or is_auto_active
        else "⏳ AGUARDANDO DOMINGO APÓS 17H (HORÁRIO DE BRASÍLIA)"
    )

    tse_time_html = (
        f" · Atualização TSE: <strong>{tse_timestamp_str}</strong>" if tse_timestamp_str else ""
    )

    msg_html = f'<div class="status-msg">ℹ️ {status_message}</div>' if status_message else ""

    if totalized_sections is not None and total_sections is not None and total_sections > 0:
        sec_p = (
            sections_pct
            if sections_pct is not None
            else round((totalized_sections / total_sections) * 100.0, 2)
        )
        sec_pct_str = f"{sec_p:.2f}%".replace(".", ",")
        sec_tot_str = f"{totalized_sections:,}".replace(",", ".")
        sec_all_str = f"{total_sections:,}".replace(",", ".")

        if (
            totalized_electorate is not None
            and total_electorate is not None
            and total_electorate > 0
        ):
            elec_p = (
                electorate_pct
                if electorate_pct is not None
                else round((totalized_electorate / total_electorate) * 100.0, 2)
            )
            elec_pct_str = f"{elec_p:.2f}%".replace(".", ",")
            elec_tot_str = f"{totalized_electorate:,}".replace(",", ".")
            elec_all_str = f"{total_electorate:,}".replace(",", ".")
        else:
            elec_pct_str = f"{current_pct:.2f}%".replace(".", ",")
            elec_tot_str = "–"
            elec_all_str = "–"

        sec_sub = f'<span class="status-sub">({sec_tot_str} de {sec_all_str})</span>'
        elec_sub = f'<span class="status-sub">({elec_tot_str} de {elec_all_str})</span>'
        stats_html = (
            '<div class="status-grid">'
            '<div class="status-item">'
            '<div class="status-lbl">Seções Totalizadas (TSE Oficial)</div>'
            f'<div class="status-val">{sec_pct_str} {sec_sub}</div>'
            "</div>"
            '<div class="status-item status-item-divider">'
            '<div class="status-lbl">Eleitorado em Seções Apuradas</div>'
            f'<div class="status-val">{elec_pct_str} {elec_sub}</div>'
            "</div>"
            "</div>"
        )
    else:
        curr_str = f"{current_pct:.2f}%".replace(".", ",")
        stats_html = (
            '<div style="margin-top: 10px; font-size: 0.90rem; color: var(--texto-mut);">'
            "Totalização Oficial no TSE: "
            '<strong style="font-size: 1.1rem; color: var(--texto-card);">'
            f"{curr_str}</strong>"
            "</div>"
        )

    container_html = (
        '<div class="status-box-container">'
        '<div class="status-box-header">'
        f'<span class="status-badge {badge_cls}">'
        f"{badge_title}"
        "</span>"
        f'<span class="status-time">'
        f"Última verificação: <strong>{last_check_str}</strong>{tse_time_html}"
        "</span>"
        "</div>"
        f"{stats_html}"
        f"{msg_html}"
        "</div>"
    )
    st.markdown(container_html, unsafe_allow_html=True)


def render_polling_log_table(log_entries: list[dict[str, Any]]) -> None:
    """Renderiza tabela interativa com o historico recente de requisicoes a API do TSE.

    Args:
        log_entries: Lista de dicionarios formatados de registros de checagem.

    Returns:
        None.

    Raises:
        None.
    """
    if not log_entries:
        st.caption("Nenhuma requisição registrada nesta sessão ainda.")
        return

    import pandas as pd  # type: ignore[import-untyped]

    df_log = pd.DataFrame(log_entries)
    st.dataframe(df_log, use_container_width=True, hide_index=True)


def render_second_round_validation_panel(
    latest_point: dict[str, Any] | None,
    validation_summary: dict[str, Any],
) -> None:
    """Renderiza o painel de KPIs de auditoria retroativa do HORIZON-MRP frente ao resultado TSE.

    Args:
        latest_point: Ponto avaliado no marco percentual selecionado pelo usuario.
        validation_summary: Indicadores consolidados retornados por
            ``summarize_second_round_validation``.

    Returns:
        None.

    Raises:
        None.
    """
    final_map = validation_summary.get("final_oficial") or {"PT": 51.77, "PL": 48.23}
    f_pt = float(final_map.get("PT", 51.77))
    f_pl = float(final_map.get("PL", 48.23))
    margin_pp = abs(f_pt - f_pl)
    winner_name = "Lula (PT)" if f_pt >= f_pl else "Flávio (PL)"

    metrics = (latest_point.get("metrics") or {}) if latest_point else {}
    mod_mae = metrics.get("model_mae_pp")
    raw_mae = metrics.get("raw_mae_pp")
    mae_gain = metrics.get("mae_gain_pp")
    covered_now = metrics.get("ci_90_covered")

    if mod_mae is not None and raw_mae is not None:
        mae_str = f"{float(mod_mae):.2f} pp".replace(".", ",")
        raw_str = f"{float(raw_mae):.2f} pp".replace(".", ",")
        if mae_gain is not None and float(mae_gain) > 0.0:
            gain_s = f"{float(mae_gain):.2f} pp".replace(".", ",")
            sub_mae = f"Urna bruta: {raw_str} · HORIZON-MRP reduziu {gain_s} de viés"
        else:
            sub_mae = f"Erro da urna bruta neste marco: {raw_str}"
    else:
        mae_str = "Preliminar"
        raw_s = f"{float(raw_mae):.2f} pp".replace(".", ",") if raw_mae is not None else "–"
        sub_mae = f"Aguardando ≥ 2,0% apurado (Urna bruta: {raw_s})"

    cov_rate = validation_summary.get("ci_90_coverage_pct")
    cov_rate_str = (
        f"{float(cov_rate):.1f}% das ondas".replace(".", ",") if cov_rate is not None else "–"
    )
    if covered_now is True:
        cov_main = "✅ Dentro do IC 90%"
        cov_sub = f"Cobertura global na série: {cov_rate_str}"
    elif covered_now is False:
        cov_main = "⚠️ Fora do IC 90%"
        cov_sub = f"Cobertura global na série: {cov_rate_str}"
    else:
        cov_main = "⏳ Aguardando ≥ 2%"
        cov_sub = "Intervalo liberado a partir de 2,0% apurado"

    call_pct = validation_summary.get("statistical_call_pct")
    call_time = validation_summary.get("statistical_call_time")
    mean_mod = validation_summary.get("mean_model_mae_pp")
    if call_pct is not None:
        call_val = f"{float(call_pct):.1f}% apurado".replace(".", ",")
        time_note = f"às {call_time} BRT" if call_time else ""
        mean_note = (
            f" · MAE médio: {float(mean_mod):.2f} pp".replace(".", ",")
            if mean_mod is not None
            else ""
        )
        call_sub = f"Probabilidade de vitória ≥ 95% {time_note}{mean_note}".strip()
    else:
        call_val = "Em evolução"
        call_sub = "Avance o controle para atingir confiança ≥ 95%"

    gabarito_val = f"{fmt_pct(f_pt, 2)} × {fmt_pct(f_pl, 2)}"
    gabarito_sub = (
        f"Eleito: {winner_name} · Vantagem final de "
        f"{f'{margin_pp:.2f}'.replace('.', ',')} pp no TSE"
    )

    panel_html = (
        '<div class="kpi-validacao-grid">'
        '<div class="kpi-validacao-card" style="border-top: 3px solid var(--kpi-top-gabarito);">'
        '<div class="kpi-validacao-label">Gabarito Oficial TSE (Final)</div>'
        f'<div class="kpi-validacao-valor">{gabarito_val}</div>'
        f'<div class="kpi-validacao-sub">{gabarito_sub}</div>'
        "</div>"
        '<div class="kpi-validacao-card" style="border-top: 3px solid #0d9488;">'
        '<div class="kpi-validacao-label">Erro Absoluto da Projeção</div>'
        f'<div class="kpi-validacao-valor">{mae_str}</div>'
        f'<div class="kpi-validacao-sub">{sub_mae}</div>'
        "</div>"
        '<div class="kpi-validacao-card" style="border-top: 3px solid #3b82f6;">'
        '<div class="kpi-validacao-label">Calibração do Intervalo (IC 90%)</div>'
        f'<div class="kpi-validacao-valor">{cov_main}</div>'
        f'<div class="kpi-validacao-sub">{cov_sub}</div>'
        "</div>"
        '<div class="kpi-validacao-card" style="border-top: 3px solid #16a34a;">'
        '<div class="kpi-validacao-label">Consolidação Matemática (≥ 95%)</div>'
        f'<div class="kpi-validacao-valor">{call_val}</div>'
        f'<div class="kpi-validacao-sub">{call_sub}</div>'
        "</div>"
        "</div>"
    )
    st.markdown(panel_html, unsafe_allow_html=True)


def render_second_round_history_table(points: list[dict[str, Any]]) -> None:
    """Renderiza a tabela historica e de auditoria onda a onda especifica do 2º Turno.

    Args:
        points: Lista cronologica de pontos do 2º turno.

    Returns:
        None.

    Raises:
        None.
    """
    if not points:
        st.info("Nenhum registro histórico disponível para o 2º turno.")
        return

    table_rows: list[dict[str, str]] = []
    for p in reversed(points):
        t_str = str(p.get("t", ""))
        x_val = float(p.get("x", 0.0))
        x_str = (
            f"{x_val:.2f}%".replace(".", ",") if x_val < 1.0 else f"{x_val:.1f}%".replace(".", ",")
        )
        obs = p.get("apurado") or {}
        proj = p.get("projecao")
        faixa = p.get("faixa") or {}
        wp_map = p.get("win_probability") or {}
        metrics = p.get("metrics") or {}

        has_proj = proj is not None and x_val >= 2.0
        pt_proj_cell = (
            format_table_projection_cell("PT", proj, faixa) if has_proj else "– (Aguardando ≥ 2%)"
        )
        pl_proj_cell = (
            format_table_projection_cell("PL", proj, faixa) if has_proj else "– (Aguardando ≥ 2%)"
        )

        wp_pt = wp_map.get("PT")
        prob_str = (
            f"{float(wp_pt) * 100.0:.1f}%".replace(".", ",")
            if has_proj and wp_pt is not None
            else "–"
        )

        raw_mae = metrics.get("raw_mae_pp")
        mod_mae = metrics.get("model_mae_pp")
        cov = metrics.get("ci_90_covered")

        row: dict[str, str] = {
            "Horário": t_str,
            "% Apurado": x_str,
            "Lula (PT) Urna": fmt_pct(obs.get("PT"), 2),
            "Lula (PT) Projeção [IC 90%]": pt_proj_cell,
            "Flávio (PL) Urna": fmt_pct(obs.get("PL"), 2),
            "Flávio (PL) Projeção [IC 90%]": pl_proj_cell,
            "Chance Vitória PT": prob_str,
        }
        if raw_mae is not None or mod_mae is not None:
            row["Erro Urna (pp)"] = (
                f"{float(raw_mae):.2f}".replace(".", ",") if raw_mae is not None else "–"
            )
            row["Erro HORIZON-MRP (pp)"] = (
                f"{float(mod_mae):.2f}".replace(".", ",")
                if has_proj and mod_mae is not None
                else "–"
            )
            row["No IC 90%?"] = "Sim" if cov is True else ("Não" if cov is False else "–")
        table_rows.append(row)

    st.dataframe(table_rows, hide_index=True, use_container_width=True)


def render_second_round_state_table(states_data: list[dict[str, Any]]) -> None:
    """Renderiza a tabela estadual de projecao e validacao retroativa do 2º Turno (27 UFs + ZZ).

    Args:
        states_data: Lista de dicionarios por UF gerada por
            ``generate_second_round_state_projections``.

    Returns:
        None.

    Raises:
        None.
    """
    if not states_data:
        st.info("Dados estaduais do 2º turno ainda não disponíveis.")
        return

    st.markdown(
        """
        <p style="font-size: 0.88rem; color: var(--texto-mut); margin-bottom: 8px;">
            Comparação em cada estado (UF + Exterior ZZ) entre os votos parciais na urna no marco
            selecionado, a projeção estadual do HORIZON-MRP e o resultado final homologado no TSE.
        </p>
        """,
        unsafe_allow_html=True,
    )

    col_sort, _ = st.columns([2, 3])
    with col_sort:
        sort_mode = st.selectbox(
            "Ordenar estados por:",
            options=[
                "Maior Colégio Eleitoral (SP, MG, RJ, BA...)",
                "Mais Apurados Primeiro (% Apurado)",
                "Menor Erro do HORIZON-MRP (pp)",
                "Ordem Alfabética (UF)",
            ],
            index=0,
            key="sort_uf_table_2t",
        )

    sorted_states = list(states_data)
    if sort_mode.startswith("Maior"):
        sorted_states.sort(key=lambda s: UF_ELECTORATE_WEIGHT.get(str(s["uf"]), 0.05), reverse=True)
    elif sort_mode.startswith("Mais"):
        sorted_states.sort(key=lambda s: float(s.get("x", 0.0)), reverse=True)
    elif sort_mode.startswith("Menor"):
        sorted_states.sort(key=lambda s: float(s.get("erro_modelo_pp", 0.0)))
    else:
        sorted_states.sort(key=lambda s: str(s["uf"]))

    formatted_rows: list[dict[str, str]] = []
    for s in sorted_states:
        uf = str(s["uf"])
        x_val = float(s.get("x", 0.0))
        x_str = f"{x_val:.1f}%".replace(".", ",")
        obs_pt = s.get("apurado_PT")
        proj_pt = float(s.get("PT", 50.0))
        final_pt = float(s.get("final_PT", 50.0))
        prior_1t = float(s.get("prior_1t_PT", 50.0))
        err_pp = float(s.get("erro_modelo_pp", abs(proj_pt - final_pt)))

        peso_str = (
            f"{UF_ELECTORATE_WEIGHT[uf]:.1f}%".replace(".", ",")
            if uf in UF_ELECTORATE_WEIGHT
            else "0,5%"
        )
        lider_final = "Lula (PT)" if final_pt >= 50.0 else "Flávio (PL)"

        formatted_rows.append(
            {
                "UF": uf,
                "Peso Brasil": peso_str,
                "% Apurado": x_str,
                "Lula (PT) Urna Parcial": fmt_pct(obs_pt, 2) if obs_pt is not None else "–",
                "Lula (PT) Projeção HORIZON-MRP": fmt_pct(proj_pt, 2),
                "Lula (PT) Final TSE 2T": fmt_pct(final_pt, 2),
                "1º Turno Bilateral (PT)": fmt_pct(prior_1t, 2),
                "Erro HORIZON-MRP (pp)": f"{err_pp:.2f} pp".replace(".", ","),
                "Vencedor UF": lider_final,
            }
        )

    st.dataframe(formatted_rows, hide_index=True, use_container_width=True)


def render_general_model_documentation() -> None:
    """Renderiza a documentacao explicativa abrangente e didatica do modelo HORIZON-MRP.

    Apresenta a fundamentacao estatistica, o fluxo de dados em tempo real, a arquitetura
    hierarquica multinivel (Nacional -> Regional -> Estadual -> Municipal), a calibracao
    de swing via Newton-Raphson, o motor Monte Carlo e os principios de governanca.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    with st.expander(
        "📖 Como o Horizonte Eleitoral Funciona · Documentação e Metodologia do Modelo",
        expanded=False,
    ):
        st.markdown(
            """
            ### Fundamentação Científica e Arquitetura do Modelo HORIZON-MRP

            O **Horizonte Eleitoral** é um sistema analítico de alta precisão desenhado para
            estimar o resultado final das eleições presidenciais brasileiras antes da conclusão
            da apuração oficial pelo Tribunal Superior Eleitoral (TSE), eliminando as ilusões
            causadas pela ordem de transmissão das urnas eletrônicas.
            """
        )

        col_d1, col_d2 = st.columns(2)
        with col_d1:
            st.markdown(
                """
                #### 1. O Problema: Viés Geográfico da Apuração
                - **Transmissão Heterogênea:** As urnas no Brasil não são transmitidas ao acaso.
                  Estados do Sul, Centro-Oeste e o interior de São Paulo fecham e transmitem seus
                  boletins muito mais rápido do que grandes metrópoles e o Nordeste.
                - **A Falsa "Virada":** Nos primeiros 10% a 30% da apuração, um candidato com apelo
                  no Centro-Sul pode abrir até 10–20 pontos percentuais de vantagem artificial.
                - **A Solução:** O algoritmo nunca olha apenas a média bruta das urnas abertas.
                  Ele separa **Votos Observados** (intocáveis) e projeta as **Seções Pendentes**
                  com base no seu perfil histórico e no deslocamento revelado pela eleição atual.
                """
            )
        with col_d2:
            st.markdown(
                """
                #### 2. O Modelo Preditivo: HORIZON-MRP
                - **Significado:** *Hierarchical Optimal Regression & Inferred Zonal Outcomes*.
                - **Estrutura Multinível em 4 Camadas:**
                  1. **Nível 1 (Nacional):** Efeito nacional ponderado pelo Censo Eleitoral
                     (Sudeste: 42,8%, Nordeste: 27,1%, Sul: 14,8%, Norte: 8,0%, Centro-Oeste: 7,0%)
                     ancorado no prior nulo para evitar contaminação regional precoce.
                  2. **Nível 2 (Regional):** Encolhimento bayesiano das 5 macro-regiões
                     ($K_{\\text{reg}}=30$).
                  3. **Nível 3 (Estadual):** Encolhimento específico das 27 UFs
                     ($K_{\\text{uf}}=20$).
                  4. **Nível 4 (Municipal):** Ajuste fino pelo Índice de Elasticidade Municipal.
                """
            )

        st.markdown("---")
        col_d3, col_d4 = st.columns(2)
        with col_d3:
            st.markdown(
                """
                #### 3. Inovação: Swing Calibrado por Newton-Raphson
                - **Eliminação do Viés de Jensen:** Softmax agregadas sofrem da desigualdade de
                  Jensen ($\\mathbb{E}[g(X)] \\neq g(\\mathbb{E}[X])$), gerando erros sistemáticos
                  de até $+0,43$ pp.
                - **Consistência Exata:** O HORIZON-MRP resolve a equação de consistência eleitoral
                  por **Newton-Raphson amortecido** sobre os dados observados.
                  Garante reconstrução exata dos votos observados e projeções estritamente válidas
                  no simplex probabilístico.
                """
            )
        with col_d4:
            st.markdown(
                """
                #### 4. Incerteza Calibrada via Monte Carlo
                - **2.000 Sorteios Vetorizados:** A cada marco de apuração, o simulador estocástico
                  propaga incertezas em escala nacional, regional e municipal.
                - **Correção de População Finita (FPC):** À medida que as urnas são abertas e
                  o eleitorado pendente tende a zero, o intervalo de credibilidade de 90%
                  $[q_{05}, q_{95}]$ estreita-se gradativamente até colapsar monotonicamente
                  em erro zero ($0,00$ pp).
                - **Limiar de 2,0%:** Nenhuma projeção consolidada é liberada antes de 2% do
                  eleitorado apurado, classificando números anteriores apenas como preliminares.
                """
            )

        st.markdown("---")
        st.markdown(
            """
            #### 5. Pilares de Engenharia e Governança de Dados
            <div class="model-card-grid">
                <div class="model-card-box">
                    <div class="model-card-box-titulo">🔒 Zero Data Leakage</div>
                    <div class="model-card-box-desc">
                        Nenhum cálculo tem acesso a dados do futuro. O corte temporal é cego
                        para qualquer seção eleitoral cuja urna ainda não foi totalizada.
                    </div>
                </div>
                <div class="model-card-box">
                    <div class="model-card-box-titulo">🛑 Consistência Failure-Stop</div>
                    <div class="model-card-box-desc">
                        O reconciliador valida seções (EA16) com a totalização (EA20).
                        Se houver divergência, o snapshot é bloqueado. Nunca alteramos votos.
                    </div>
                </div>
                <div class="model-card-box">
                    <div class="model-card-box-titulo">📦 Imutabilidade Append-Only</div>
                    <div class="model-card-box-desc">
                        Respostas da API do TSE são armazenadas com hash SHA-256 e manifestos.
                        Sobrescritas com conteúdo distinto lançam erro de imutabilidade.
                    </div>
                </div>
                <div class="model-card-box">
                    <div class="model-card-box-titulo">⚡ Apache Parquet & DuckDB</div>
                    <div class="model-card-box-desc">
                        499.206 seções pareadas processadas em formato colunar Parquet
                        com consultas analíticas em memória via DuckDB para resposta ágil.
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
