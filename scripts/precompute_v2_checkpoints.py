"""Script para precomputar marcos de projecao da noite eleitoral com Modelo Versao 2 (v2)."""

from __future__ import annotations

import json
from pathlib import Path

from horizonte_eleitoral.config import get_final_data_dir
from horizonte_eleitoral.dashboard.replay import DEFAULT_CHECKPOINTS, load_replay_catalog
from horizonte_eleitoral.simulation.election_night_runner import simulate_2026_real_checkpoint


def precompute_checkpoints_v2(
    output_path: Path | None = None,
    num_draws: int = 200,
    seed: int = 42,
) -> None:
    """Computa os marcos padronizados utilizando o Modelo V2 com elasticidade 2018-2022.

    Args:
        output_path: Caminho para gravacao do arquivo JSON. Se None,
            grava em data/final/checkpoints_2026.json.
        num_draws: Quantidade de repeticoes Monte Carlo por marco.
        seed: Semente pseudoaleatoria para reproducibilidade.

    Returns:
        None.

    Raises:
        FileNotFoundError: Se o catalogo de secoes de 2026 nao for localizado.
    """
    if output_path is None:
        output_path = get_final_data_dir() / "checkpoints_2026.json"
    print("Carregando catalogo completo de 2026 para precomputacao com Modelo V2...")
    catalog = load_replay_catalog(limit_sections=None)
    print(f"Catalogo carregado ({len(catalog)} secoes). Processando marcos V2...")

    points: dict[str, dict[str, object]] = {}

    for wave in DEFAULT_CHECKPOINTS:
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

        hora_base = 17 * 60 + int(wave * 300)
        h_str = f"{hora_base // 60:02d}:{hora_base % 60:02d}"

        key = f"{wave:.3f}"
        points[key] = {
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
        print(f"  -> Marco {key} ({x_val}%): projecao={projecao}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(points, f, indent=2, ensure_ascii=False)

    print(f"Precomputacao concluida: {len(points)} marcos gravados em {output_path}.")


if __name__ == "__main__":
    precompute_checkpoints_v2()
