"""Motor de calculo de elasticidade e volatilidade eleitoral municipal multi-ciclo."""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from horizonte_eleitoral.domain.errors import ValidationError


@dataclass(frozen=True, slots=True)
class MunicipalElasticityProfile:
    """Perfil de volatilidade e deslocamento de votos de um municipio entre 2018 e 2022.

    Attributes:
        municipality_key: Chave unica no formato 'UF:CD_MUNICIPIO'.
        state: Sigla da Unidade Federativa.
        municipality_code: Codigo do municipio preservando zeros a esquerda.
        valid_votes_2018: Total de votos validos computados em 2018.
        valid_votes_2022: Total de votos validos computados em 2022.
        pt_share_2018: Proporcao de votos do PT em 2018.
        pt_share_2022: Proporcao de votos do PT em 2022.
        pl_share_2018: Proporcao de votos do PL/Direita em 2018.
        pl_share_2022: Proporcao de votos do PL/Direita em 2022.
        pt_swing: Deslocamento de share do PT (2022 - 2018).
        pl_swing: Deslocamento de share do PL/Direita (2022 - 2018).
        volatility: Escalar de volatilidade eleitoral (|pt_swing| + |pl_swing|) / 2.
    """

    municipality_key: str
    state: str
    municipality_code: str
    valid_votes_2018: int
    valid_votes_2022: int
    pt_share_2018: float
    pt_share_2022: float
    pl_share_2018: float
    pl_share_2022: float
    pt_swing: float
    pl_swing: float
    volatility: float

    def __post_init__(self) -> None:
        """Valida se campos obrigatorios e percentuais estao em limites validos.

        Raises:
            ValidationError: Se algum dado obrigatorio for invalido ou negativo.
        """
        if not self.municipality_key or ":" not in self.municipality_key:
            raise ValidationError("municipality_key deve ter o formato 'UF:CD_MUNICIPIO'.")
        if not self.state or len(self.state) != 2:
            raise ValidationError("state deve conter sigla de UF valida com 2 letras.")
        if self.valid_votes_2018 < 0 or self.valid_votes_2022 < 0:
            raise ValidationError("Votos validos nao podem ser negativos.")
        if self.volatility < 0.0:
            raise ValidationError("volatility nao pode ser negativa.")


class MunicipalElasticityIndex:
    """Indice analitico imutavel de elasticidade historica municipal."""

    def __init__(
        self,
        profiles: dict[str, MunicipalElasticityProfile],
        state_avg_volatility: dict[str, float] | None = None,
        national_avg_volatility: float | None = None,
    ) -> None:
        """Inicializa o indice de elasticidade com os perfis municipais consolidados.

        Args:
            profiles: Dicionario mapeando 'UF:CD_MUNICIPIO' para MunicipalElasticityProfile.
            state_avg_volatility: Dicionario opcional de volatilidade media por estado.
            national_avg_volatility: Escalar opcional de volatilidade media nacional.

        Returns:
            None.

        Raises:
            None.
        """
        self._profiles = dict(profiles)

        if state_avg_volatility is not None and national_avg_volatility is not None:
            self._state_avg = dict(state_avg_volatility)
            self._national_avg = float(national_avg_volatility)
        else:
            state_totals: dict[str, float] = defaultdict(float)
            state_counts: dict[str, int] = defaultdict(int)
            total_vol = 0.0

            for p in self._profiles.values():
                state_totals[p.state] += p.volatility
                state_counts[p.state] += 1
                total_vol += p.volatility

            self._state_avg = {
                st: (state_totals[st] / state_counts[st]) if state_counts[st] > 0 else 0.05
                for st in state_counts
            }
            count = len(self._profiles)
            self._national_avg = (total_vol / count) if count > 0 else 0.05

    @property
    def total_municipalities(self) -> int:
        """Retorna o total de municipios catalogados no indice.

        Returns:
            Quantidade de municipios indexados.
        """
        return len(self._profiles)

    @property
    def national_average_volatility(self) -> float:
        """Retorna a volatilidade media nacional.

        Returns:
            Media escalar de volatilidade nacional.
        """
        return self._national_avg

    def get_profile(self, municipality_key: str) -> MunicipalElasticityProfile | None:
        """Obtem o perfil detalhado de um municipio especifico.

        Args:
            municipality_key: Identificador 'UF:CD_MUNICIPIO'.

        Returns:
            Objeto MunicipalElasticityProfile ou None se o municipio nao existir.

        Raises:
            None.
        """
        return self._profiles.get(municipality_key)

    def get_volatility(self, municipality_key: str, state: str | None = None) -> float:
        """Retorna a volatilidade historica do municipio com fallback para UF e nacional.

        Args:
            municipality_key: Chave do municipio (ex: 'SP:71072').
            state: Sigla da UF opcional para busca de media estadual.

        Returns:
            Escalar de volatilidade entre 0.0 e 1.0.

        Raises:
            None.
        """
        prof = self._profiles.get(municipality_key)
        if prof is not None:
            return prof.volatility

        uf = state or (municipality_key.split(":")[0] if ":" in municipality_key else "")
        if uf and uf in self._state_avg:
            return self._state_avg[uf]
        return self._national_avg

    def save_parquet(self, path: Path) -> int:
        """Salva os perfis de elasticidade em arquivo Parquet colunar otimizado.

        Args:
            path: Caminho de destino para o arquivo Parquet.

        Returns:
            Quantidade total de registros gravados.

        Raises:
            None.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        keys: list[str] = []
        states: list[str] = []
        codes: list[str] = []
        v18: list[int] = []
        v22: list[int] = []
        pt18: list[float] = []
        pt22: list[float] = []
        pl18: list[float] = []
        pl22: list[float] = []
        pt_sw: list[float] = []
        pl_sw: list[float] = []
        vols: list[float] = []

        for p in self._profiles.values():
            keys.append(p.municipality_key)
            states.append(p.state)
            codes.append(p.municipality_code)
            v18.append(p.valid_votes_2018)
            v22.append(p.valid_votes_2022)
            pt18.append(p.pt_share_2018)
            pt22.append(p.pt_share_2022)
            pl18.append(p.pl_share_2018)
            pl22.append(p.pl_share_2022)
            pt_sw.append(p.pt_swing)
            pl_sw.append(p.pl_swing)
            vols.append(p.volatility)

        table = pa.Table.from_arrays(
            [
                pa.array(keys, type=pa.string()),
                pa.array(states, type=pa.string()),
                pa.array(codes, type=pa.string()),
                pa.array(v18, type=pa.int64()),
                pa.array(v22, type=pa.int64()),
                pa.array(pt18, type=pa.float64()),
                pa.array(pt22, type=pa.float64()),
                pa.array(pl18, type=pa.float64()),
                pa.array(pl22, type=pa.float64()),
                pa.array(pt_sw, type=pa.float64()),
                pa.array(pl_sw, type=pa.float64()),
                pa.array(vols, type=pa.float64()),
            ],
            names=[
                "municipality_key",
                "state",
                "municipality_code",
                "valid_votes_2018",
                "valid_votes_2022",
                "pt_share_2018",
                "pt_share_2022",
                "pl_share_2018",
                "pl_share_2022",
                "pt_swing",
                "pl_swing",
                "volatility",
            ],
        )
        pq.write_table(table, path, compression="zstd")
        return len(keys)

    @classmethod
    def load_parquet(cls, path: Path) -> MunicipalElasticityIndex:
        """Carrega o indice de elasticidade a partir de arquivo Parquet.

        Args:
            path: Caminho para o arquivo Parquet.

        Returns:
            Instancia inicializada de MunicipalElasticityIndex.

        Raises:
            FileNotFoundError: Se o arquivo nao existir.
        """
        if not path.exists():
            raise FileNotFoundError(f"Arquivo de elasticidade nao encontrado: {path}")

        table = pq.read_table(path)
        pydict = table.to_pydict()
        profiles: dict[str, MunicipalElasticityProfile] = {}

        n_rows = len(pydict["municipality_key"])
        for i in range(n_rows):
            key = str(pydict["municipality_key"][i])
            prof = MunicipalElasticityProfile(
                municipality_key=key,
                state=str(pydict["state"][i]),
                municipality_code=str(pydict["municipality_code"][i]),
                valid_votes_2018=int(pydict["valid_votes_2018"][i]),
                valid_votes_2022=int(pydict["valid_votes_2022"][i]),
                pt_share_2018=float(pydict["pt_share_2018"][i]),
                pt_share_2022=float(pydict["pt_share_2022"][i]),
                pl_share_2018=float(pydict["pl_share_2018"][i]),
                pl_share_2022=float(pydict["pl_share_2022"][i]),
                pt_swing=float(pydict["pt_swing"][i]),
                pl_swing=float(pydict["pl_swing"][i]),
                volatility=float(pydict["volatility"][i]),
            )
            profiles[key] = prof

        return cls(profiles)

    @classmethod
    def build_from_csvs(
        cls,
        path_2018: Path | str,
        path_2022: Path | str,
    ) -> MunicipalElasticityIndex:
        """Agrega votos municipais de 2018 e 2022 e constroi o indice analitico.

        Args:
            path_2018: Caminho para o CSV de 2018 (historical_2018.csv).
            path_2022: Caminho para o CSV de 2022 (historical_2022.csv).

        Returns:
            Instancia completa de MunicipalElasticityIndex.

        Raises:
            FileNotFoundError: Se algum dos arquivos nao for localizado.
        """
        p18 = Path(path_2018)
        p22 = Path(path_2022)
        if not p18.exists():
            raise FileNotFoundError(f"Arquivo de 2018 nao encontrado: {p18}")
        if not p22.exists():
            raise FileNotFoundError(f"Arquivo de 2022 nao encontrado: {p22}")

        def _aggregate_by_municipality(
            csv_path: Path,
        ) -> dict[str, dict[str, Any]]:
            agg: dict[str, dict[str, Any]] = defaultdict(
                lambda: {"state": "", "muni": "", "valid": 0, "pt": 0, "pl": 0}
            )
            with open(csv_path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    raw_uf = row.get("state") or row.get("SG_UF", "")
                    uf = str(raw_uf).strip().upper()
                    raw_muni = row.get("municipality_code") or row.get("CD_MUNICIPIO", "")
                    muni = str(raw_muni).strip().zfill(5)
                    if not uf or not muni:
                        continue
                    key = f"{uf}:{muni}"
                    entry = agg[key]
                    entry["state"] = uf
                    entry["muni"] = muni

                    v = int(row.get("valid_votes", 0) or 0)
                    pt = int(row.get("votes_pt", 0) or 0)
                    pl = int(row.get("votes_pl", 0) or 0)

                    entry["valid"] += v
                    entry["pt"] += pt
                    entry["pl"] += pl
            return agg

        agg_18 = _aggregate_by_municipality(p18)
        agg_22 = _aggregate_by_municipality(p22)

        # Intersecao e uniao de municipios
        all_keys = set(agg_18.keys()).union(set(agg_22.keys()))
        profiles: dict[str, MunicipalElasticityProfile] = {}

        for key in all_keys:
            d18 = agg_18.get(key, {})
            d22 = agg_22.get(key, {})

            uf = str(d22.get("state") or d18.get("state", key.split(":")[0]))
            muni = str(d22.get("muni") or d18.get("muni", key.split(":")[1]))

            v18 = int(d18.get("valid", 0))
            v22 = int(d22.get("valid", 0))

            pt_sh_18 = (d18.get("pt", 0) / v18) if v18 > 0 else 0.30
            pl_sh_18 = (d18.get("pl", 0) / v18) if v18 > 0 else 0.50

            pt_sh_22 = (d22.get("pt", 0) / v22) if v22 > 0 else 0.45
            pl_sh_22 = (d22.get("pl", 0) / v22) if v22 > 0 else 0.45

            pt_sw = round(pt_sh_22 - pt_sh_18, 6)
            pl_sw = round(pl_sh_22 - pl_sh_18, 6)
            vol = round((abs(pt_sw) + abs(pl_sw)) / 2.0, 6)

            profiles[key] = MunicipalElasticityProfile(
                municipality_key=key,
                state=uf,
                municipality_code=muni,
                valid_votes_2018=v18,
                valid_votes_2022=v22,
                pt_share_2018=round(pt_sh_18, 6),
                pt_share_2022=round(pt_sh_22, 6),
                pl_share_2018=round(pl_sh_18, 6),
                pl_share_2022=round(pl_sh_22, 6),
                pt_swing=pt_sw,
                pl_swing=pl_sw,
                volatility=vol,
            )

        return cls(profiles)
