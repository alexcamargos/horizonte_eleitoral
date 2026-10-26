"""Modulo de construcao dos graficos interativos de projecao eleitoral em Altair."""

from __future__ import annotations

from typing import Any, cast

import altair as alt
import pandas as pd  # type: ignore[import-untyped]

COLOR_MAP: dict[str, str] = {
    "PT": "#e34948",
    "PL": "#2a78d6",
    "OUTROS": "#8a8983",
}

CANDIDATE_NAMES: dict[str, str] = {
    "PT": "Lula (PT)",
    "PL": "Flávio Bolsonaro (PL)",
    "OUTROS": "Outros candidatos (soma)",
}


def prepare_chart_dataframe(points: list[dict[str, Any]]) -> pd.DataFrame:
    """Converte a lista de pontos historicos de apuracao em DataFrame tabular para o Altair.

    Args:
        points: Lista de pontos contendo x (% apurado), t (horario), apurado e projecao.

    Returns:
        pd.DataFrame normalizado com colunas [x, t, bloco, candidato, apurado, projecao, q05, q95].

    Raises:
        None.
    """
    rows: list[dict[str, Any]] = []
    for p in points:
        x_val = float(p.get("x", 0.0))
        t_val = str(p.get("t", ""))
        apurado_map = p.get("apurado", {})
        projecao_map = p.get("projecao") or {}
        faixa_map = p.get("faixa") or {}

        for bloco in ("PT", "PL", "OUTROS"):
            obs_val = apurado_map.get(bloco)
            proj_val = projecao_map.get(bloco) if projecao_map else None

            q05_val: float | None = None
            q95_val: float | None = None
            if faixa_map and bloco in faixa_map and faixa_map[bloco]:
                q05_val = float(faixa_map[bloco][0])
                q95_val = float(faixa_map[bloco][1])

            rows.append(
                {
                    "x": x_val,
                    "t": t_val,
                    "bloco": bloco,
                    "candidato": CANDIDATE_NAMES.get(bloco, bloco),
                    "apurado": obs_val,
                    "projecao": proj_val,
                    "q05": q05_val,
                    "q95": q95_val,
                }
            )

    return pd.DataFrame(rows)


def build_projection_chart(
    points: list[dict[str, Any]],
    height_main: int = 340,
    height_sub: int = 140,
) -> alt.VConcatChart | alt.Chart:
    """Gera o grafico visual composto em Altair para acompanhamento da apuracao.

    Contem dois paineis compartilhando o eixo horizontal (0% a 100% de apuracao):
    - Painel Superior: Disputa principal (PT vs PL) com linhas de apuracao, linhas
      de projecao tracejadas, faixas sombreadas de IC 90% e linha de 50%.
    - Painel Secundario: Outros candidatos com apuracao, projecao e faixa de 90%.

    Args:
        points: Lista cronologica de pontos de apuracao e projecao.
        height_main: Altura em pixels do painel principal.
        height_sub: Altura em pixels do subpainel de outros candidatos.

    Returns:
        Instancia de alt.VConcatChart concatenando verticalmente os dois paineis.

    Raises:
        None.
    """
    if not points:
        empty_df = pd.DataFrame({"x": [0.0, 100.0], "y": [50.0, 50.0]})
        empty_chart = (
            alt.Chart(empty_df)
            .mark_line(color="#cbd5e1", strokeDash=[4, 4])
            .encode(
                x=alt.X("x:Q", title="% do eleitorado apurado", scale=alt.Scale(domain=[0, 100])),
                y=alt.Y("y:Q", title="% dos votos válidos", scale=alt.Scale(domain=[0, 100])),
            )
            .properties(
                title=alt.TitleParams(
                    text="Aguardando dados de apuração...",
                    subtitle=(
                        "Os gráficos serão preenchidos conforme as seções "
                        "forem totalizadas pelo TSE."
                    ),
                    subtitleColor="#64748b",
                    subtitleFontSize=11,
                ),
                height=height_main,
            )
        )
        return cast(alt.Chart, empty_chart)

    df = prepare_chart_dataframe(points)
    df_main = df[df["bloco"].isin(["PT", "PL"])].copy()
    df_outros = df[df["bloco"] == "OUTROS"].copy()

    color_scale = alt.Scale(
        domain=["PT", "PL", "OUTROS"],
        range=[COLOR_MAP["PT"], COLOR_MAP["PL"], COLOR_MAP["OUTROS"]],
    )

    # ----------------- PAINEL PRINCIPAL (PT vs PL) -----------------
    base_main = alt.Chart(df_main).encode(
        x=alt.X(
            "x:Q",
            title=None,
            scale=alt.Scale(domain=[0, 100]),
            axis=alt.Axis(
                labels=True,
                ticks=True,
                domain=False,
                grid=True,
                values=[0, 20, 40, 60, 80, 100],
                format=".0f",
            ),
        ),
    )

    # Faixas de 90% de confianca (area translúcida mais contrastante)
    df_main_ci = df_main[df_main["q05"].notna() & df_main["q95"].notna()]
    band_main = (
        alt.Chart(df_main_ci)
        .mark_area(opacity=0.26)
        .encode(
            x="x:Q",
            y=alt.Y("q05:Q"),
            y2="q95:Q",
            color=alt.Color("bloco:N", scale=color_scale, legend=None),
        )
    )

    # Linha pontilhada de projecao final
    df_main_proj = df_main[df_main["projecao"].notna()]
    line_main_proj = (
        alt.Chart(df_main_proj)
        .mark_line(strokeDash=[4, 4], strokeWidth=2.4)
        .encode(
            x="x:Q",
            y=alt.Y("projecao:Q"),
            color=alt.Color("bloco:N", scale=color_scale, legend=None),
        )
    )

    # Linha solida de resultado apurado
    line_main_obs = base_main.mark_line(strokeWidth=2.6).encode(
        y=alt.Y(
            "apurado:Q",
            title="% dos votos válidos",
            scale=alt.Scale(domain=[30, 60], clamp=True),
            axis=alt.Axis(format=".0f", tickCount=6),
        ),
        color=alt.Color("bloco:N", scale=color_scale, legend=None),
        tooltip=[
            alt.Tooltip("t:N", title="Horário"),
            alt.Tooltip("x:Q", title="% Eleitorado Apurado", format=".2f"),
            alt.Tooltip("candidato:N", title="Candidatura"),
            alt.Tooltip("apurado:Q", title="% Apurado Agora", format=".2f"),
            alt.Tooltip("projecao:Q", title="% Projeção Final", format=".2f"),
            alt.Tooltip("q05:Q", title="IC 90% Inferior", format=".2f"),
            alt.Tooltip("q95:Q", title="IC 90% Superior", format=".2f"),
        ],
    )

    # Linha de referencia horizontal de 50% (vitoria em 1o turno)
    rule_50 = (
        alt.Chart(pd.DataFrame({"y": [50.0]}))
        .mark_rule(color="#94a3b8", strokeDash=[3, 3], strokeWidth=1.2)
        .encode(y="y:Q")
    )
    text_50 = (
        alt.Chart(pd.DataFrame({"x": [98.0], "y": [50.8], "text": ["50% (1º turno)"]}))
        .mark_text(align="right", fontSize=11, color="#475569")
        .encode(x="x:Q", y="y:Q", text="text:N")
    )

    chart_main = alt.layer(band_main, line_main_proj, line_main_obs, rule_50, text_50).properties(
        height=height_main,
        title=alt.TitleParams(
            text="Evolução da apuração e da projeção: Lula (PT) e Flávio Bolsonaro (PL)",
            subtitle=(
                "Linha contínua: Apurado oficial (TSE) · "
                "Linha tracejada: Projeção final · "
                "Faixa sombreada: Intervalo de 90% (IC 90%)"
            ),
            subtitleColor="#64748b",
            subtitleFontSize=11,
        ),
    )

    # ----------------- PAINEL SECUNDARIO (OUTROS) -----------------
    base_sub = alt.Chart(df_outros).encode(
        x=alt.X(
            "x:Q",
            title="% do eleitorado nas seções totalizadas pelo TSE",
            scale=alt.Scale(domain=[0, 100]),
            axis=alt.Axis(format=".0f", values=[0, 20, 40, 60, 80, 100], grid=True),
        ),
    )

    df_sub_ci = df_outros[df_outros["q05"].notna() & df_outros["q95"].notna()]
    band_sub = (
        alt.Chart(df_sub_ci)
        .mark_area(opacity=0.26)
        .encode(
            x="x:Q",
            y="q05:Q",
            y2="q95:Q",
            color=alt.Color("bloco:N", scale=color_scale, legend=None),
        )
    )

    df_sub_proj = df_outros[df_outros["projecao"].notna()]
    line_sub_proj = (
        alt.Chart(df_sub_proj)
        .mark_line(strokeDash=[4, 4], strokeWidth=2.0)
        .encode(
            x="x:Q",
            y="projecao:Q",
            color=alt.Color("bloco:N", scale=color_scale, legend=None),
        )
    )

    line_sub_obs = base_sub.mark_line(strokeWidth=2.2).encode(
        y=alt.Y(
            "apurado:Q",
            title="Outros %",
            scale=alt.Scale(domain=[0, 20], clamp=True),
            axis=alt.Axis(format=".0f", tickCount=4),
        ),
        color=alt.Color("bloco:N", scale=color_scale, legend=None),
        tooltip=[
            alt.Tooltip("t:N", title="Horário"),
            alt.Tooltip("x:Q", title="% Eleitorado Apurado", format=".1f"),
            alt.Tooltip("apurado:Q", title="% Apurado Agora", format=".2f"),
            alt.Tooltip("projecao:Q", title="% Projeção Final", format=".2f"),
        ],
    )

    chart_sub = alt.layer(band_sub, line_sub_proj, line_sub_obs).properties(
        height=height_sub,
        title=alt.TitleParams(
            text="Outros candidatos (soma)",
            subtitle=(
                "Linha contínua: Apurado oficial (TSE) · "
                "Linha tracejada: Projeção final · "
                "Faixa sombreada: Intervalo de 90% (IC 90%)"
            ),
            subtitleColor="#64748b",
            subtitleFontSize=11,
        ),
    )

    composed_chart = alt.vconcat(chart_main, chart_sub).resolve_scale(x="shared")
    return cast(alt.VConcatChart, composed_chart)


def build_second_round_chart(
    points: list[dict[str, Any]],
    height: int = 380,
    final_result: dict[str, float] | None = None,
) -> alt.Chart:
    """Gera o grafico visual em Altair para o 2º Turno Majoritario (PT vs PL).

    Painel unificado de disputa majoritaria com linha de maioria absoluta (50%),
    faixas de credibilidade de 90%, linhas de apuracao oficial e de projecao final,
    alem de linhas de referencia opcionais com o gabarito oficial consolidado no TSE.

    Args:
        points: Lista cronologica de pontos de apuracao e projecao do 2º turno.
        height: Altura em pixels do grafico.
        final_result: Resultado final oficial opcional {'PT': ..., 'PL': ...} para auditoria.

    Returns:
        Instancia de alt.Chart com a visualizacao da disputa do segundo turno.

    Raises:
        None.
    """
    if not points:
        empty_df = pd.DataFrame({"x": [0.0, 100.0], "y": [50.0, 50.0]})
        empty_chart = (
            alt.Chart(empty_df)
            .mark_line(color="#cbd5e1", strokeDash=[4, 4])
            .encode(
                x=alt.X("x:Q", title="% do eleitorado apurado", scale=alt.Scale(domain=[0, 100])),
                y=alt.Y("y:Q", title="% dos votos válidos", scale=alt.Scale(domain=[0, 100])),
            )
            .properties(
                title=alt.TitleParams(
                    text="Aguardando dados de apuração do 2º Turno...",
                    subtitle=(
                        "O gráfico será preenchido conforme as seções "
                        "forem totalizadas pelo TSE após as 17h."
                    ),
                    subtitleColor="#64748b",
                    subtitleFontSize=11,
                ),
                height=height,
            )
        )
        return cast(alt.Chart, empty_chart)

    df = prepare_chart_dataframe(points)
    is_valid = df["apurado"].notna() | df["projecao"].notna()
    df_2t = df[df["bloco"].isin(["PT", "PL"]) & is_valid].copy()

    color_scale = alt.Scale(
        domain=["PT", "PL"],
        range=[COLOR_MAP["PT"], COLOR_MAP["PL"]],
    )

    base = alt.Chart(df_2t).encode(
        x=alt.X(
            "x:Q",
            title="% do eleitorado nas seções totalizadas pelo TSE",
            scale=alt.Scale(domain=[0, 100]),
            axis=alt.Axis(
                labels=True,
                ticks=True,
                domain=False,
                grid=True,
                values=[0, 20, 40, 60, 80, 100],
                format=".0f",
            ),
        ),
    )

    # Faixas de 90% de credibilidade
    df_ci = df_2t[df_2t["q05"].notna() & df_2t["q95"].notna()]
    band = (
        alt.Chart(df_ci)
        .mark_area(opacity=0.25)
        .encode(
            x="x:Q",
            y=alt.Y("q05:Q"),
            y2="q95:Q",
            color=alt.Color("bloco:N", scale=color_scale, legend=None),
        )
    )

    # Linha pontilhada de projecao final do modelo v2
    df_proj = df_2t[df_2t["projecao"].notna()]
    line_proj = (
        alt.Chart(df_proj)
        .mark_line(strokeDash=[4, 4], strokeWidth=2.6)
        .encode(
            x="x:Q",
            y=alt.Y("projecao:Q"),
            color=alt.Color("bloco:N", scale=color_scale, legend=None),
        )
    )

    # Linha solida de apuracao oficial observada
    line_obs = base.mark_line(strokeWidth=2.8).encode(
        y=alt.Y(
            "apurado:Q",
            title="% dos votos válidos (2º Turno)",
            scale=alt.Scale(domain=[35, 65], clamp=True),
            axis=alt.Axis(format=".0f", tickCount=7),
        ),
        color=alt.Color("bloco:N", scale=color_scale, legend=None),
        tooltip=[
            alt.Tooltip("t:N", title="Horário"),
            alt.Tooltip("x:Q", title="% Eleitorado Apurado", format=".2f"),
            alt.Tooltip("candidato:N", title="Candidatura"),
            alt.Tooltip("apurado:Q", title="% Apurado Agora", format=".2f"),
            alt.Tooltip("projecao:Q", title="% Projeção Final", format=".2f"),
            alt.Tooltip("q05:Q", title="IC 90% Inferior", format=".2f"),
            alt.Tooltip("q95:Q", title="IC 90% Superior", format=".2f"),
        ],
    )

    # Linha de 50% (Maioria absoluta / Eleito)
    rule_50 = (
        alt.Chart(pd.DataFrame({"y": [50.0]}))
        .mark_rule(color="#94a3b8", strokeDash=[3, 3], strokeWidth=1.5)
        .encode(y="y:Q")
    )
    text_50 = (
        alt.Chart(pd.DataFrame({"x": [98.0], "y": [50.8], "text": ["50% (Maioria Absoluta)"]}))
        .mark_text(align="right", fontSize=11, fontWeight="bold", color="#94a3b8")
        .encode(x="x:Q", y="y:Q", text="text:N")
    )

    layers: list[alt.Chart] = [band, line_proj, line_obs, rule_50, text_50]

    if final_result and "PT" in final_result and "PL" in final_result:
        f_pt = float(final_result["PT"])
        f_pl = float(final_result["PL"])
        final_df = pd.DataFrame(
            [
                {
                    "bloco": "PT",
                    "y": f_pt,
                    "x": 99.0,
                    "label_y": f_pt + 1.0 if f_pt >= f_pl else f_pt - 1.2,
                    "label": f"Final TSE PT: {f_pt:.2f}%".replace(".", ","),
                },
                {
                    "bloco": "PL",
                    "y": f_pl,
                    "x": 99.0,
                    "label_y": f_pl - 1.2 if f_pt >= f_pl else f_pl + 1.0,
                    "label": f"Final TSE PL: {f_pl:.2f}%".replace(".", ","),
                },
            ]
        )
        rule_final = (
            alt.Chart(final_df)
            .mark_rule(strokeDash=[2, 4], strokeWidth=1.3, opacity=0.6)
            .encode(
                y="y:Q",
                color=alt.Color("bloco:N", scale=color_scale, legend=None),
            )
        )
        text_final = (
            alt.Chart(final_df)
            .mark_text(align="right", fontSize=10, fontWeight="bold", opacity=0.85)
            .encode(
                x="x:Q",
                y="label_y:Q",
                text="label:N",
                color=alt.Color("bloco:N", scale=color_scale, legend=None),
            )
        )
        layers.extend([rule_final, text_final])

    subtitle_text = (
        "Linha contínua: Apurado oficial TSE · "
        "Linha tracejada: Projeção final · "
        "Faixa sombreada: Intervalo de 90% (IC 90%)"
    )
    if final_result:
        subtitle_text += " · Pontilhado fino: Resultado oficial 100% TSE"

    chart = alt.layer(*layers).properties(
        height=height,
        title=alt.TitleParams(
            text="Projeção Presidencial 2º Turno: Lula (PT) vs Flávio Bolsonaro (PL)",
            subtitle=subtitle_text,
            subtitleColor="#94a3b8",
            subtitleFontSize=11,
        ),
    )

    return cast(alt.Chart, chart)


def build_second_round_error_chart(
    points: list[dict[str, Any]],
    height: int = 230,
) -> alt.Chart:
    """Gera o grafico comparativo de erro absoluto retroativo (Modelo V2 vs Urna Bruta TSE).

    Compara ao longo das ondas (>= 2% apurado) o erro absoluto em pontos percentuais (pp)
    da contagem parcial bruta das urnas contra o erro da projecao bayesiana V2 em relacao
    ao resultado oficial definitivo do 2º turno no TSE.

    Args:
        points: Lista cronologica de pontos contendo o bloco ``metrics``.
        height: Altura em pixels do grafico.

    Returns:
        Instancia de alt.Chart com as curvas de erro absoluto e meta de 0,50 pp.

    Raises:
        None.
    """
    rows: list[dict[str, Any]] = []
    for p in points:
        x_val = float(p.get("x", 0.0))
        t_val = str(p.get("t", ""))
        metrics = p.get("metrics") or {}
        raw_mae = metrics.get("raw_mae_pp")
        mod_mae = metrics.get("model_mae_pp")
        covered = metrics.get("ci_90_covered")
        cov_str = "Sim" if covered is True else ("Não" if covered is False else "–")

        if raw_mae is not None and x_val >= 2.0:
            rows.append(
                {
                    "x": x_val,
                    "t": t_val,
                    "serie": "Urna Bruta TSE (sem modelo)",
                    "erro_pp": float(raw_mae),
                    "cobertura_ic": cov_str,
                }
            )
        if mod_mae is not None and x_val >= 2.0:
            rows.append(
                {
                    "x": x_val,
                    "t": t_val,
                    "serie": "Projeção Bayesiana V2",
                    "erro_pp": float(mod_mae),
                    "cobertura_ic": cov_str,
                }
            )

    if not rows:
        empty_df = pd.DataFrame({"x": [0.0, 100.0], "y": [0.5, 0.5]})
        empty_chart = (
            alt.Chart(empty_df)
            .mark_line(color="#cbd5e1", strokeDash=[4, 4])
            .encode(
                x=alt.X("x:Q", title="% do eleitorado apurado", scale=alt.Scale(domain=[0, 100])),
                y=alt.Y("y:Q", title="Erro absoluto (pp)", scale=alt.Scale(domain=[0, 2.0])),
            )
            .properties(
                title=alt.TitleParams(
                    text="Auditoria Retroativa de Erro Absoluto (aguardando ≥ 2,0% apurado)",
                    subtitle=(
                        "O comparativo de precisão do modelo é liberado a partir do "
                        "limiar estatístico de 2,0% do eleitorado apurado."
                    ),
                    subtitleColor="#64748b",
                    subtitleFontSize=11,
                ),
                height=height,
            )
        )
        return cast(alt.Chart, empty_chart)

    df_err = pd.DataFrame(rows)
    max_err = max(1.0, float(df_err["erro_pp"].max()) * 1.18)

    err_scale = alt.Scale(
        domain=["Projeção Bayesiana V2", "Urna Bruta TSE (sem modelo)"],
        range=["#0f766e", "#94a3b8"],
    )
    dash_scale = alt.Scale(
        domain=["Projeção Bayesiana V2", "Urna Bruta TSE (sem modelo)"],
        range=[[1, 0], [5, 4]],
    )

    lines = (
        alt.Chart(df_err)
        .mark_line(strokeWidth=2.6, point=True)
        .encode(
            x=alt.X(
                "x:Q",
                title="% do eleitorado nas seções totalizadas pelo TSE",
                scale=alt.Scale(domain=[0, 100]),
                axis=alt.Axis(values=[0, 20, 40, 60, 80, 100], format=".0f", grid=True),
            ),
            y=alt.Y(
                "erro_pp:Q",
                title="Erro absoluto vs Final TSE (pp)",
                scale=alt.Scale(domain=[0, round(max_err, 2)], clamp=True),
                axis=alt.Axis(format=".2f", tickCount=5),
            ),
            color=alt.Color(
                "serie:N",
                scale=err_scale,
                legend=alt.Legend(title=None, orient="top"),
            ),
            strokeDash=alt.StrokeDash("serie:N", scale=dash_scale, legend=None),
            tooltip=[
                alt.Tooltip("t:N", title="Horário"),
                alt.Tooltip("x:Q", title="% Eleitorado Apurado", format=".1f"),
                alt.Tooltip("serie:N", title="Série Avaliada"),
                alt.Tooltip("erro_pp:Q", title="Erro Absoluto (pp)", format=".2f"),
                alt.Tooltip("cobertura_ic:N", title="Dentro do IC 90%?"),
            ],
        )
    )

    rule_target = (
        alt.Chart(pd.DataFrame({"y": [0.50]}))
        .mark_rule(color="#d97706", strokeDash=[3, 3], strokeWidth=1.2)
        .encode(y="y:Q")
    )
    text_target = (
        alt.Chart(pd.DataFrame({"x": [98.5], "y": [0.56], "text": ["Meta histórica: 0,50 pp"]}))
        .mark_text(align="right", fontSize=10, color="#b45309")
        .encode(x="x:Q", y="y:Q", text="text:N")
    )

    composed = alt.layer(lines, rule_target, text_target).properties(
        height=height,
        title=alt.TitleParams(
            text="Qualidade Retroativa do Modelo: Erro Absoluto ao Longo da Apuração (pp)",
            subtitle=(
                "Distância em pontos percentuais para o resultado oficial final do TSE "
                "(quanto menor, mais preciso)"
            ),
            subtitleColor="#94a3b8",
            subtitleFontSize=11,
        ),
    )
    return cast(alt.Chart, composed)
