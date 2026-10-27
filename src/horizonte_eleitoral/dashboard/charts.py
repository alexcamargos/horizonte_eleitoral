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
        projecao_map = p.get("projecao") or p.get("preliminar") or {}
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
    active_wave: float | None = None,
    final_result: dict[str, float] | None = None,
    extend_to_end: bool = True,
) -> alt.VConcatChart | alt.Chart:
    """Gera o grafico visual composto em Altair para acompanhamento da apuracao do 1º Turno.

    Contem dois paineis compartilhando o eixo horizontal (0% a 100% de apuracao):
    - Painel Superior: Disputa principal (PT vs PL - Lula vs Flávio Bolsonaro) com
      linhas de apuracao oficial do TSE, linhas e pontos de projecao nos marcos apurados,
      projecao estendida ate o final (100%), faixas de credibilidade de 90%, linha de 50%
      e rotulos com o resultado final projetado no encerramento (100%).
    - Painel Secundario: Outros candidatos (soma) com apuracao, projecao estendida ate
      100%, faixa de 90% e rotulo do resultado projetado final.

    Args:
        points: Lista cronologica de pontos de apuracao e projecao.
        height_main: Altura em pixels do painel principal.
        height_sub: Altura em pixels do subpainel de outros candidatos.
        active_wave: Percentual apurado da onda ativa (ex.: 8.0) para cursor ou marco.
        final_result: Resultado oficial definitivo opcional {'PT': ..., 'PL': ..., 'OUTROS': ...}.
        extend_to_end: Se True, projeta a estimativa do marco ativo ate 100% da apuracao.

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

    # Identificacao do marco ativo e ponto de referencia da projecao
    latest_point = points[-1]
    current_wave = (
        float(active_wave) if active_wave is not None else float(latest_point.get("x", 0.0))
    )

    ref_point = latest_point
    if active_wave is not None:
        matched = [p for p in points if abs(float(p.get("x", 0.0)) - active_wave) < 0.15]
        if matched:
            ref_point = matched[0]

    proj_map = ref_point.get("projecao") or ref_point.get("preliminar") or {}
    faixa_map = ref_point.get("faixa") or {}

    # Calculo dinamico de escala vertical do painel principal (PT vs PL)
    y_min_main = 28.0
    y_max_main = 62.0
    if not df_main.empty:
        obs_vals = [v for v in df_main["apurado"].dropna() if isinstance(v, (int, float))]
        q05_vals = [v for v in df_main["q05"].dropna() if isinstance(v, (int, float))]
        q95_vals = [v for v in df_main["q95"].dropna() if isinstance(v, (int, float))]
        if obs_vals or q05_vals:
            lowest = min(obs_vals + q05_vals)
            y_min_main = min(28.0, float(lowest) - 2.0)
        if obs_vals or q95_vals:
            highest = max(obs_vals + q95_vals)
            y_max_main = max(62.0, float(highest) + 2.0)

    y_scale_main = alt.Scale(domain=[y_min_main, y_max_main], clamp=True)

    # Calculo dinamico de escala vertical do subpainel (OUTROS)
    y_max_sub = 18.0
    if not df_outros.empty:
        obs_sub = [v for v in df_outros["apurado"].dropna() if isinstance(v, (int, float))]
        q95_sub = [v for v in df_outros["q95"].dropna() if isinstance(v, (int, float))]
        if obs_sub or q95_sub:
            highest_sub = max(obs_sub + q95_sub)
            y_max_sub = max(18.0, float(highest_sub) + 2.0)

    y_scale_sub = alt.Scale(domain=[0.0, y_max_sub], clamp=True)

    # ----------------- PAINEL PRINCIPAL (PT vs PL) -----------------
    df_main_obs = df_main[df_main["apurado"].notna()]
    base_main = alt.Chart(df_main_obs).encode(
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
                titlePadding=12,
            ),
        ),
    )

    # Faixas de 90% de credibilidade historicas observadas
    df_main_ci = df_main[df_main["q05"].notna() & df_main["q95"].notna()]
    band_main = (
        alt.Chart(df_main_ci)
        .mark_area(opacity=0.22)
        .encode(
            x="x:Q",
            y=alt.Y("q05:Q", scale=y_scale_main),
            y2="q95:Q",
            color=alt.Color("bloco:N", scale=color_scale, legend=None),
        )
    )

    # Linha tracejada de projecao final nos marcos apurados
    df_main_proj = df_main[df_main["projecao"].notna()]
    line_main_proj = (
        alt.Chart(df_main_proj)
        .mark_line(strokeDash=[4, 4], strokeWidth=2.4)
        .encode(
            x="x:Q",
            y=alt.Y("projecao:Q", scale=y_scale_main),
            color=alt.Color("bloco:N", scale=color_scale, legend=None),
        )
    )

    # Pontos de projecao em cada percentual analisado (com tooltips)
    points_main_proj = (
        alt.Chart(df_main_proj)
        .mark_circle(size=45, opacity=0.9)
        .encode(
            x="x:Q",
            y=alt.Y("projecao:Q", scale=y_scale_main),
            color=alt.Color("bloco:N", scale=color_scale, legend=None),
            tooltip=[
                alt.Tooltip("t:N", title="Horário"),
                alt.Tooltip("x:Q", title="% Eleitorado Apurado no Marco", format=".2f"),
                alt.Tooltip("candidato:N", title="Candidatura"),
                alt.Tooltip(
                    "projecao:Q",
                    title="% Projeção Final (Lá no final)",
                    format=".2f",
                ),
                alt.Tooltip("q05:Q", title="IC 90% Inferior", format=".2f"),
                alt.Tooltip("q95:Q", title="IC 90% Superior", format=".2f"),
            ],
        )
    )

    # Linha solida de apuracao oficial do TSE
    line_main_obs = base_main.mark_line(strokeWidth=2.8).encode(
        y=alt.Y(
            "apurado:Q",
            title="% dos votos válidos",
            scale=y_scale_main,
            axis=alt.Axis(format=".0f", tickCount=6),
        ),
        color=alt.Color("bloco:N", scale=color_scale, legend=None),
    )

    points_main_obs = base_main.mark_circle(size=35, opacity=0.85).encode(
        y=alt.Y("apurado:Q", scale=y_scale_main),
        color=alt.Color("bloco:N", scale=color_scale, legend=None),
        tooltip=[
            alt.Tooltip("t:N", title="Horário"),
            alt.Tooltip("x:Q", title="% Eleitorado Apurado", format=".2f"),
            alt.Tooltip("candidato:N", title="Candidatura"),
            alt.Tooltip("apurado:Q", title="% Apurado no TSE Agora", format=".2f"),
            alt.Tooltip("projecao:Q", title="% Projeção Final Estimada", format=".2f"),
            alt.Tooltip("q05:Q", title="IC 90% Inferior", format=".2f"),
            alt.Tooltip("q95:Q", title="IC 90% Superior", format=".2f"),
        ],
    )

    # Linha de referencia horizontal de 50% (vitoria em 1o turno)
    rule_50 = (
        alt.Chart(pd.DataFrame({"y": [50.0]}))
        .mark_rule(color="#94a3b8", strokeDash=[3, 3], strokeWidth=1.2)
        .encode(y=alt.Y("y:Q", scale=y_scale_main))
    )
    text_50 = (
        alt.Chart(pd.DataFrame({"x": [98.0], "y": [50.8], "text": ["50% (1º turno)"]}))
        .mark_text(align="right", fontSize=11, color="#64748b", fontWeight="bold")
        .encode(x="x:Q", y=alt.Y("y:Q", scale=y_scale_main), text="text:N")
    )

    layers_main: list[alt.Chart] = [
        band_main,
        line_main_proj,
        points_main_proj,
        line_main_obs,
        points_main_obs,
        rule_50,
        text_50,
    ]

    # Projecao Estendida para o Final da Apuracao (100%) no Painel Principal
    if extend_to_end and current_wave < 100.0 and proj_map:
        fwd_main_rows: list[dict[str, Any]] = []
        for bloco in ("PT", "PL"):
            if bloco in proj_map and proj_map[bloco] is not None:
                p_val = float(proj_map[bloco])
                q05_val = (
                    float(faixa_map[bloco][0])
                    if (faixa_map and bloco in faixa_map and faixa_map[bloco])
                    else p_val
                )
                q95_val = (
                    float(faixa_map[bloco][1])
                    if (faixa_map and bloco in faixa_map and faixa_map[bloco])
                    else p_val
                )
                cand = CANDIDATE_NAMES.get(bloco, bloco)
                fwd_main_rows.extend(
                    [
                        {
                            "x": current_wave,
                            "bloco": bloco,
                            "candidato": cand,
                            "projecao": p_val,
                            "q05": q05_val,
                            "q95": q95_val,
                        },
                        {
                            "x": 100.0,
                            "bloco": bloco,
                            "candidato": cand,
                            "projecao": p_val,
                            "q05": q05_val,
                            "q95": q95_val,
                        },
                    ]
                )

        if fwd_main_rows:
            df_fwd_main = pd.DataFrame(fwd_main_rows)
            band_main_fwd = (
                alt.Chart(df_fwd_main)
                .mark_area(opacity=0.16)
                .encode(
                    x="x:Q",
                    y=alt.Y("q05:Q", scale=y_scale_main),
                    y2="q95:Q",
                    color=alt.Color("bloco:N", scale=color_scale, legend=None),
                )
            )
            line_main_fwd = (
                alt.Chart(df_fwd_main)
                .mark_line(strokeDash=[3, 3], strokeWidth=2.2, opacity=0.9)
                .encode(
                    x="x:Q",
                    y=alt.Y("projecao:Q", scale=y_scale_main),
                    color=alt.Color("bloco:N", scale=color_scale, legend=None),
                )
            )
            layers_main.extend([band_main_fwd, line_main_fwd])

    # Rotulos e Marcadores Terminais em 100% no Painel Principal
    if proj_map and ("PT" in proj_map or "PL" in proj_map):
        term_main_rows: list[dict[str, Any]] = []
        pt_p = float(proj_map.get("PT", 0.0))
        pl_p = float(proj_map.get("PL", 0.0))
        pt_offset = -1.2 if pt_p < pl_p else 1.2
        pl_offset = 1.2 if pl_p >= pt_p else -1.2

        for bloco in ("PT", "PL"):
            if bloco in proj_map and proj_map[bloco] is not None:
                p_val = float(proj_map[bloco])
                cand = CANDIDATE_NAMES.get(bloco, bloco)
                offset = pt_offset if bloco == "PT" else pl_offset
                q05_str = (
                    f"{faixa_map[bloco][0]:.1f}%" if (faixa_map and bloco in faixa_map) else ""
                )
                q95_str = (
                    f"{faixa_map[bloco][1]:.1f}%" if (faixa_map and bloco in faixa_map) else ""
                )
                ic_suffix = f" [{q05_str} - {q95_str}]".replace(".", ",") if q05_str else ""
                label_text = f"{cand}: {p_val:.2f}%{ic_suffix}".replace(".", ",")
                term_main_rows.append(
                    {
                        "x": 100.0,
                        "bloco": bloco,
                        "candidato": cand,
                        "projecao": p_val,
                        "label_y": p_val + offset,
                        "label": label_text,
                        "q05": (
                            float(faixa_map[bloco][0])
                            if (faixa_map and bloco in faixa_map)
                            else p_val
                        ),
                        "q95": (
                            float(faixa_map[bloco][1])
                            if (faixa_map and bloco in faixa_map)
                            else p_val
                        ),
                        "origem": f"Marco {current_wave:.1f}%",
                    }
                )

        if term_main_rows:
            df_term_main = pd.DataFrame(term_main_rows)
            points_main_term = (
                alt.Chart(df_term_main)
                .mark_circle(size=80, stroke="#ffffff", strokeWidth=1.5)
                .encode(
                    x="x:Q",
                    y=alt.Y("projecao:Q", scale=y_scale_main),
                    color=alt.Color("bloco:N", scale=color_scale, legend=None),
                    tooltip=[
                        alt.Tooltip(
                            "origem:N",
                            title="Projeção Calculada no Marco",
                        ),
                        alt.Tooltip("candidato:N", title="Candidatura"),
                        alt.Tooltip(
                            "projecao:Q",
                            title="% Projeção Final (100% Apuração)",
                            format=".2f",
                        ),
                        alt.Tooltip("q05:Q", title="IC 90% Inferior", format=".2f"),
                        alt.Tooltip("q95:Q", title="IC 90% Superior", format=".2f"),
                    ],
                )
            )
            text_main_term = (
                alt.Chart(df_term_main)
                .mark_text(align="right", dx=-10, fontSize=11, fontWeight="bold")
                .encode(
                    x="x:Q",
                    y=alt.Y("label_y:Q", scale=y_scale_main),
                    text="label:N",
                    color=alt.Color("bloco:N", scale=color_scale, legend=None),
                )
            )
            layers_main.extend([points_main_term, text_main_term])

    # Cursor vertical ativo no marco selecionado se nao estendido
    if active_wave is not None and not extend_to_end:
        rule_act = (
            alt.Chart(pd.DataFrame({"x": [current_wave]}))
            .mark_rule(color="#f59e0b", strokeDash=[2, 2], strokeWidth=1.5)
            .encode(x="x:Q")
        )
        layers_main.append(rule_act)

    # Gabarito oficial de referencia opcional
    if final_result and "PT" in final_result and "PL" in final_result:
        f_pt = float(final_result["PT"])
        f_pl = float(final_result["PL"])
        final_main_df = pd.DataFrame(
            [
                {
                    "bloco": "PT",
                    "y": f_pt,
                    "x": 100.0,
                    "label": f"Final TSE PT: {f_pt:.2f}%".replace(".", ","),
                },
                {
                    "bloco": "PL",
                    "y": f_pl,
                    "x": 100.0,
                    "label": f"Final TSE PL: {f_pl:.2f}%".replace(".", ","),
                },
            ]
        )
        rule_final_main = (
            alt.Chart(final_main_df)
            .mark_rule(strokeDash=[2, 4], strokeWidth=1.2, opacity=0.55)
            .encode(
                y=alt.Y("y:Q", scale=y_scale_main),
                color=alt.Color("bloco:N", scale=color_scale, legend=None),
            )
        )
        layers_main.append(rule_final_main)

    chart_main = alt.layer(*layers_main).properties(
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
    df_sub_ci = df_outros[df_outros["q05"].notna() & df_outros["q95"].notna()]
    band_sub = (
        alt.Chart(df_sub_ci)
        .mark_area(opacity=0.22)
        .encode(
            x="x:Q",
            y=alt.Y("q05:Q", scale=y_scale_sub),
            y2="q95:Q",
            color=alt.Color("bloco:N", scale=color_scale, legend=None),
        )
    )

    df_sub_proj = df_outros[df_outros["projecao"].notna()]
    line_sub_proj = (
        alt.Chart(df_sub_proj)
        .mark_line(strokeDash=[4, 4], strokeWidth=2.2)
        .encode(
            x="x:Q",
            y=alt.Y("projecao:Q", scale=y_scale_sub),
            color=alt.Color("bloco:N", scale=color_scale, legend=None),
        )
    )

    points_sub_proj = (
        alt.Chart(df_sub_proj)
        .mark_circle(size=45, opacity=0.9)
        .encode(
            x="x:Q",
            y=alt.Y("projecao:Q", scale=y_scale_sub),
            color=alt.Color("bloco:N", scale=color_scale, legend=None),
            tooltip=[
                alt.Tooltip("t:N", title="Horário"),
                alt.Tooltip(
                    "x:Q",
                    title="% Eleitorado Apurado no Marco",
                    format=".1f",
                ),
                alt.Tooltip(
                    "projecao:Q",
                    title="% Projeção Final Outros",
                    format=".2f",
                ),
                alt.Tooltip("q05:Q", title="IC 90% Inferior", format=".2f"),
                alt.Tooltip("q95:Q", title="IC 90% Superior", format=".2f"),
            ],
        )
    )

    df_sub_obs = df_outros[df_outros["apurado"].notna()]
    base_sub = alt.Chart(df_sub_obs).encode(
        x=alt.X(
            "x:Q",
            title="% do eleitorado nas seções totalizadas pelo TSE",
            scale=alt.Scale(domain=[0, 100]),
            axis=alt.Axis(format=".0f", values=[0, 20, 40, 60, 80, 100], grid=True),
        ),
    )

    line_sub_obs = base_sub.mark_line(strokeWidth=2.4).encode(
        y=alt.Y(
            "apurado:Q",
            title="Outros %",
            scale=y_scale_sub,
            axis=alt.Axis(format=".0f", tickCount=4),
        ),
        color=alt.Color("bloco:N", scale=color_scale, legend=None),
    )

    points_sub_obs = base_sub.mark_circle(size=35, opacity=0.85).encode(
        y=alt.Y("apurado:Q", scale=y_scale_sub),
        color=alt.Color("bloco:N", scale=color_scale, legend=None),
        tooltip=[
            alt.Tooltip("t:N", title="Horário"),
            alt.Tooltip("x:Q", title="% Eleitorado Apurado", format=".1f"),
            alt.Tooltip("apurado:Q", title="% Apurado Agora", format=".2f"),
            alt.Tooltip(
                "projecao:Q",
                title="% Projeção Final Estimada",
                format=".2f",
            ),
        ],
    )

    layers_sub: list[alt.Chart] = [
        band_sub,
        line_sub_proj,
        points_sub_proj,
        line_sub_obs,
        points_sub_obs,
    ]

    # Projecao Estendida para o Final (100%) no Subpainel de Outros
    if (
        extend_to_end
        and current_wave < 100.0
        and proj_map
        and "OUTROS" in proj_map
        and proj_map["OUTROS"] is not None
    ):
        outros_val = float(proj_map["OUTROS"])
        q05_outros = (
            float(faixa_map["OUTROS"][0])
            if (faixa_map and "OUTROS" in faixa_map and faixa_map["OUTROS"])
            else outros_val
        )
        q95_outros = (
            float(faixa_map["OUTROS"][1])
            if (faixa_map and "OUTROS" in faixa_map and faixa_map["OUTROS"])
            else outros_val
        )
        df_fwd_sub = pd.DataFrame(
            [
                {
                    "x": current_wave,
                    "bloco": "OUTROS",
                    "projecao": outros_val,
                    "q05": q05_outros,
                    "q95": q95_outros,
                },
                {
                    "x": 100.0,
                    "bloco": "OUTROS",
                    "projecao": outros_val,
                    "q05": q05_outros,
                    "q95": q95_outros,
                },
            ]
        )
        band_sub_fwd = (
            alt.Chart(df_fwd_sub)
            .mark_area(opacity=0.16)
            .encode(
                x="x:Q",
                y=alt.Y("q05:Q", scale=y_scale_sub),
                y2="q95:Q",
                color=alt.Color("bloco:N", scale=color_scale, legend=None),
            )
        )
        line_sub_fwd = (
            alt.Chart(df_fwd_sub)
            .mark_line(strokeDash=[3, 3], strokeWidth=2.0, opacity=0.9)
            .encode(
                x="x:Q",
                y=alt.Y("projecao:Q", scale=y_scale_sub),
                color=alt.Color("bloco:N", scale=color_scale, legend=None),
            )
        )
        layers_sub.extend([band_sub_fwd, line_sub_fwd])

    # Rotulos e Marcadores Terminais em 100% no Subpainel de Outros
    if proj_map and "OUTROS" in proj_map and proj_map["OUTROS"] is not None:
        outros_val = float(proj_map["OUTROS"])
        q05_str = f"{faixa_map['OUTROS'][0]:.1f}%" if (faixa_map and "OUTROS" in faixa_map) else ""
        q95_str = f"{faixa_map['OUTROS'][1]:.1f}%" if (faixa_map and "OUTROS" in faixa_map) else ""
        ic_suffix = f" [{q05_str} - {q95_str}]".replace(".", ",") if q05_str else ""
        label_outros = f"Outros (soma): {outros_val:.2f}%{ic_suffix}".replace(".", ",")

        df_term_sub = pd.DataFrame(
            [
                {
                    "x": 100.0,
                    "bloco": "OUTROS",
                    "candidato": "Outros candidatos (soma)",
                    "projecao": outros_val,
                    "label_y": min(y_max_sub - 1.0, outros_val + 1.2),
                    "label": label_outros,
                    "q05": (
                        float(faixa_map["OUTROS"][0])
                        if (faixa_map and "OUTROS" in faixa_map)
                        else outros_val
                    ),
                    "q95": (
                        float(faixa_map["OUTROS"][1])
                        if (faixa_map and "OUTROS" in faixa_map)
                        else outros_val
                    ),
                    "origem": f"Marco {current_wave:.1f}%",
                }
            ]
        )
        points_sub_term = (
            alt.Chart(df_term_sub)
            .mark_circle(size=80, stroke="#ffffff", strokeWidth=1.5)
            .encode(
                x="x:Q",
                y=alt.Y("projecao:Q", scale=y_scale_sub),
                color=alt.Color("bloco:N", scale=color_scale, legend=None),
                tooltip=[
                    alt.Tooltip(
                        "origem:N",
                        title="Projeção Calculada no Marco",
                    ),
                    alt.Tooltip("candidato:N", title="Candidatura"),
                    alt.Tooltip(
                        "projecao:Q",
                        title="% Projeção Final (100% Apuração)",
                        format=".2f",
                    ),
                    alt.Tooltip("q05:Q", title="IC 90% Inferior", format=".2f"),
                    alt.Tooltip("q95:Q", title="IC 90% Superior", format=".2f"),
                ],
            )
        )
        text_sub_term = (
            alt.Chart(df_term_sub)
            .mark_text(align="right", dx=-10, fontSize=11, fontWeight="bold")
            .encode(
                x="x:Q",
                y=alt.Y("label_y:Q", scale=y_scale_sub),
                text="label:N",
                color=alt.Color("bloco:N", scale=color_scale, legend=None),
            )
        )
        layers_sub.extend([points_sub_term, text_sub_term])

    if active_wave is not None and not extend_to_end:
        rule_sub_act = (
            alt.Chart(pd.DataFrame({"x": [current_wave]}))
            .mark_rule(color="#f59e0b", strokeDash=[2, 2], strokeWidth=1.5)
            .encode(x="x:Q")
        )
        layers_sub.append(rule_sub_act)

    if final_result and "OUTROS" in final_result:
        f_outros = float(final_result["OUTROS"])
        final_sub_df = pd.DataFrame(
            [
                {
                    "bloco": "OUTROS",
                    "y": f_outros,
                    "x": 100.0,
                    "label": f"Final TSE Outros: {f_outros:.2f}%".replace(".", ","),
                }
            ]
        )
        rule_final_sub = (
            alt.Chart(final_sub_df)
            .mark_rule(strokeDash=[2, 4], strokeWidth=1.2, opacity=0.55)
            .encode(
                y=alt.Y("y:Q", scale=y_scale_sub),
                color=alt.Color("bloco:N", scale=color_scale, legend=None),
            )
        )
        layers_sub.append(rule_final_sub)

    chart_sub = alt.layer(*layers_sub).properties(
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
) -> alt.LayerChart | alt.Chart:
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
                titlePadding=12,
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

    # Linha pontilhada de projecao final do HORIZON-MRP
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

    return cast(alt.LayerChart | alt.Chart, chart)


def build_second_round_error_chart(
    points: list[dict[str, Any]],
    height: int = 300,
    y_max: float | None = None,
    active_wave: float | None = None,
) -> alt.LayerChart | alt.Chart:
    """Gera o gráfico comparativo de erro absoluto retroativo (HORIZON-MRP vs Urna Bruta TSE).

    Compara ao longo das ondas (>= 2% apurado) o erro absoluto em pontos percentuais (pp)
    da contagem parcial bruta das urnas contra o erro da projeção HORIZON-MRP em relação
    ao resultado oficial definitivo do 2º turno no TSE.

    Args:
        points: Lista cronológica de pontos contendo o bloco ``metrics``.
        height: Altura em pixels do gráfico (padrão: 300).
        y_max: Teto vertical opcional da escala em pp. Se None, utiliza foco inteligente
            (4.0 pp se houver viés inicial desproporcional, preservando legibilidade).
        active_wave: Percentual apurado da onda ativa (ex.: 10.0) para inclusão de marcador
            vertical de auditoria e destaque do ponto avaliado.

    Returns:
        Instância de alt.Chart com curvas de erro absoluto, meta histórica e destaque da onda.

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
                    "serie": "Urna Bruta TSE (Sem Modelo)",
                    "erro_pp": float(raw_mae),
                    "cobertura_ic": cov_str,
                }
            )
        if mod_mae is not None and x_val >= 2.0:
            rows.append(
                {
                    "x": x_val,
                    "t": t_val,
                    "serie": "Projeção HORIZON-MRP",
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
            .properties(height=height)
        )
        return cast(alt.Chart, empty_chart)

    df_err = pd.DataFrame(rows)
    max_err = max(1.0, float(df_err["erro_pp"].max()))

    effective_y_max = y_max if y_max is not None else (4.0 if max_err > 4.0 else max_err * 1.15)
    effective_y_max = max(1.0, round(effective_y_max, 2))

    df_err["erro_real_pp"] = df_err["erro_pp"]
    df_err["erro_plot_pp"] = df_err["erro_pp"].clip(upper=effective_y_max)

    max_x = float(df_err["x"].max())
    if max_x <= 15.0:
        x_domain = [0.0, max(12.0, max_x + 2.0)]
        x_values = [0, 2, 5, 10, 12] if max_x <= 10.0 else [0, 5, 10, 15]
    else:
        x_domain = [0.0, 100.0]
        x_values = [0, 20, 40, 60, 80, 100]

    err_scale = alt.Scale(
        domain=["Projeção HORIZON-MRP", "Urna Bruta TSE (Sem Modelo)"],
        range=["#0d9488", "#94a3b8"],
    )
    dash_scale = alt.Scale(
        domain=["Projeção HORIZON-MRP", "Urna Bruta TSE (Sem Modelo)"],
        range=[[1, 0], [5, 4]],
    )

    lines = (
        alt.Chart(df_err)
        .mark_line(strokeWidth=2.6, point=True)
        .encode(
            x=alt.X(
                "x:Q",
                title="% do eleitorado nas seções totalizadas pelo TSE",
                scale=alt.Scale(domain=x_domain),
                axis=alt.Axis(values=x_values, format=".0f", grid=True, titlePadding=10),
            ),
            y=alt.Y(
                "erro_plot_pp:Q",
                title="Erro absoluto vs Final TSE (pp)",
                scale=alt.Scale(domain=[0, effective_y_max], clamp=True),
                axis=alt.Axis(format=".2f", tickCount=5, titlePadding=10),
            ),
            color=alt.Color(
                "serie:N",
                scale=err_scale,
                legend=alt.Legend(
                    title=None,
                    orient="top",
                    labelLimit=0,
                    labelFontSize=12,
                    symbolSize=100,
                    symbolStrokeWidth=2.5,
                    padding=8,
                ),
            ),
            strokeDash=alt.StrokeDash("serie:N", scale=dash_scale, legend=None),
            tooltip=[
                alt.Tooltip("t:N", title="Horário"),
                alt.Tooltip("x:Q", title="% Eleitorado Apurado", format=".1f"),
                alt.Tooltip("serie:N", title="Série Avaliada"),
                alt.Tooltip("erro_real_pp:Q", title="Erro Real vs Final TSE (pp)", format=".2f"),
                alt.Tooltip("cobertura_ic:N", title="Dentro do IC 90%?"),
            ],
        )
    )

    rule_target = (
        alt.Chart(pd.DataFrame({"y": [0.50]}))
        .mark_rule(color="#d97706", strokeDash=[3, 3], strokeWidth=1.4)
        .encode(y="y:Q")
    )
    target_label_x = min(96.0, max(10.0, max_x - 1.0))
    text_target = (
        alt.Chart(
            pd.DataFrame(
                {
                    "x": [target_label_x],
                    "y": [0.58],
                    "text": ["Meta histórica: 0,50 pp"],
                }
            )
        )
        .mark_text(align="right", fontSize=11, fontWeight="bold", color="#d97706")
        .encode(x="x:Q", y="y:Q", text="text:N")
    )

    layers: list[alt.Chart] = [lines, rule_target, text_target]

    # Indicador de pontos excedentes limitados na escala (ex.: urna bruta a 2% e 5%)
    df_clamped = df_err[df_err["erro_real_pp"] > effective_y_max].copy()
    if not df_clamped.empty:
        df_clamped["label_clamped"] = df_clamped["erro_real_pp"].apply(
            lambda v: f"↑ {v:.1f} pp".replace(".", ",")
        )
        text_clamped = (
            alt.Chart(df_clamped)
            .mark_text(
                align="center",
                dy=-10,
                fontSize=10,
                fontWeight="bold",
                color="#64748b",
            )
            .encode(
                x="x:Q",
                y="erro_plot_pp:Q",
                text="label_clamped:N",
            )
        )
        layers.append(text_clamped)

    # Marcador da onda ativa avaliada
    if active_wave is not None and active_wave >= 2.0:
        rule_active = (
            alt.Chart(pd.DataFrame({"x": [active_wave]}))
            .mark_rule(color="#0d9488", strokeDash=[2, 2], strokeWidth=1.5, opacity=0.75)
            .encode(x="x:Q")
        )
        text_active = (
            alt.Chart(
                pd.DataFrame(
                    {
                        "x": [active_wave],
                        "y": [effective_y_max * 0.92],
                        "text": [f"Marco atual: {active_wave:.1f}%".replace(".", ",")],
                    }
                )
            )
            .mark_text(
                align="left" if active_wave <= 75.0 else "right",
                dx=6 if active_wave <= 75.0 else -6,
                fontSize=11,
                fontWeight="bold",
                color="#0d9488",
            )
            .encode(x="x:Q", y="y:Q", text="text:N")
        )
        layers.extend([rule_active, text_active])

        df_active_point = df_err[
            (df_err["serie"] == "Projeção HORIZON-MRP")
            & (df_err["x"].round(1) == round(active_wave, 1))
        ]
        if not df_active_point.empty:
            circle_active = (
                alt.Chart(df_active_point)
                .mark_circle(size=130, color="#0d9488", stroke="#ffffff", strokeWidth=2)
                .encode(x="x:Q", y="erro_plot_pp:Q")
            )
            err_val = float(df_active_point["erro_real_pp"].iloc[0])
            lbl_active_val = (
                alt.Chart(df_active_point)
                .mark_text(
                    align="left" if active_wave <= 80.0 else "right",
                    dx=10 if active_wave <= 80.0 else -10,
                    dy=-8,
                    fontSize=11,
                    fontWeight="bold",
                    color="#0d9488",
                )
                .encode(
                    x="x:Q",
                    y="erro_plot_pp:Q",
                    text=alt.value(f"Erro: {err_val:.2f} pp".replace(".", ",")),
                )
            )
            layers.extend([circle_active, lbl_active_val])

    composed = alt.layer(*layers).properties(height=height)
    return cast(alt.LayerChart | alt.Chart, composed)
