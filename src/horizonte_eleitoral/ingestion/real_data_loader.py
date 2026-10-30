"""Carregador e agregador de dados reais do TSE para ensaios e replays eleitorais."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import zipfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from horizonte_eleitoral.domain.enums import MatchQuality
from horizonte_eleitoral.domain.errors import ValidationError
from horizonte_eleitoral.domain.models import ElectionKey, MunicipalityKey, SectionKey
from horizonte_eleitoral.historical.matcher import GeographicMatcher
from horizonte_eleitoral.historical.models import (
    HistoricalLocation,
    HistoricalVoteProfile,
    MatchCandidate,
)
from horizonte_eleitoral.historical.profile_builder import HistoricalProfileBuilder

DEFAULT_CANDIDATE_TAXONOMY: dict[str, str] = {
    "13": "PT",
    "22": "PL",
}

# Perfil de velocidade de transmissao e apuracao regional baseado no historico oficial do TSE
STATE_ARRIVAL_PROFILE: dict[str, tuple[float, float]] = {
    # Exterior (ZZ): Urnas encerram e transmitem mais cedo devido ao fuso horario
    "ZZ": (0.10, 0.08),
    # Muito rapidos: Distrito Federal, Sul (SC, PR, RS) e Centro-Oeste (MS, MT, GO)
    "DF": (0.22, 0.12),
    "SC": (0.27, 0.14),
    "PR": (0.28, 0.14),
    "RS": (0.30, 0.15),
    "MS": (0.30, 0.14),
    "MT": (0.32, 0.15),
    "GO": (0.34, 0.15),
    # Norte intermediario / Estados com contagem rapida
    "RO": (0.35, 0.15),
    "RR": (0.36, 0.15),
    "TO": (0.38, 0.16),
    "ES": (0.36, 0.15),
    # Sudeste de grande porte: interior apura rapido, capitais e grandes colegios demoram mais
    "SP": (0.44, 0.20),
    "RJ": (0.46, 0.19),
    "MG": (0.48, 0.19),
    "AC": (0.50, 0.18),
    "AP": (0.50, 0.18),
    # Nordeste e Norte profundo (logistica desafiadora, comunidades remotas e filas)
    "AL": (0.55, 0.18),
    "SE": (0.56, 0.18),
    "RN": (0.58, 0.18),
    "PB": (0.60, 0.18),
    "CE": (0.62, 0.18),
    "PE": (0.63, 0.18),
    "PA": (0.65, 0.19),
    "AM": (0.66, 0.20),
    "MA": (0.68, 0.18),
    "BA": (0.70, 0.18),
    "PI": (0.71, 0.18),
}


def compute_section_arrival_score(section_id: str, state: str) -> float:
    """Calcula score continuo de chegada da secao calibrado com a velocidade do TSE.

    Utiliza a distribuicao normal regional do estado e a transformacao Box-Muller
    sobre o hash MD5 da secao eleitoral para garantir que a dispersao entre secoes
    seja deterministica, sem estado externo e estritamente reprodutivel.

    Args:
        section_id: Identificador unico da secao (ex: 'SP:71072:0001:0001').
        state: Sigla da Unidade Federativa com 2 caracteres.

    Returns:
        Score escalar continuo que define a ordem cronologica de chegada da secao.

    Raises:
        None.
    """
    mean, std = STATE_ARRIVAL_PROFILE.get(state.upper(), (0.50, 0.20))
    digest = hashlib.md5(section_id.encode("utf-8")).digest()
    u1 = (int.from_bytes(digest[:4], "big") + 1) / (2**32 + 1)
    u2 = (int.from_bytes(digest[4:8], "big") + 1) / (2**32 + 1)
    z0 = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
    return mean + z0 * std


@dataclass(frozen=True, slots=True)
class RealSectionRecord:
    """Registro de secao eleitoral real com dados de apuracao e totalizacao.

    Attributes:
        section_id: Identificador unico da secao (ex: 'SP:71072:0001:0001').
        state: Sigla da Unidade Federativa com 2 letras maiusculas.
        municipality_code: Codigo do municipio preservando zeros a esquerda.
        zone: Numero da zona eleitoral preservando zeros a esquerda.
        section: Numero da secao eleitoral preservando zeros a esquerda.
        electorate: Eleitorado total apto a votar na secao.
        valid_votes: Total de votos validos computados.
        blank_votes: Votos em branco computados.
        null_votes: Votos nulos computados.
        group_votes: Votos validos por grupo politico ('PT', 'PL', 'OUTROS').
        totalized_timestamp: Data e hora da geracao/totalizacao da urna.
        sequence_order: Ordem ordinal de chegada/processamento da secao.
        local_code: Codigo do local de votacao, se disponivel.
        latitude: Latitude decimal do local, se disponivel.
        longitude: Longitude decimal do local, se disponivel.
    """

    section_id: str
    state: str
    municipality_code: str
    zone: str
    section: str
    electorate: int
    valid_votes: int
    blank_votes: int
    null_votes: int
    group_votes: tuple[tuple[str, int], ...]
    totalized_timestamp: datetime | None = None
    sequence_order: int = 0
    local_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    def __post_init__(self) -> None:
        """Valida que campos obrigatorios sao nao vazios e votos sao nao negativos.

        Raises:
            ValidationError: Se state, municipality_code, zone ou section forem invalidos.
        """
        if not self.state or len(self.state) != 2:
            raise ValidationError("state deve ser uma sigla de UF valida com 2 caracteres.")
        if not self.municipality_code:
            raise ValidationError("municipality_code nao pode ser vazio.")
        if not self.zone:
            raise ValidationError("zone nao pode ser vazia.")
        if not self.section:
            raise ValidationError("section nao pode ser vazia.")
        if self.electorate < 0:
            raise ValidationError("electorate nao pode ser negativo.")
        if self.valid_votes < 0:
            raise ValidationError("valid_votes nao pode ser negativo.")

    def to_catalog_dict(
        self,
        historical_shares: tuple[tuple[str, float], ...],
        match_quality: str = "EXACT",
    ) -> dict[str, Any]:
        """Converte o registro para o formato consumido pelo pipeline de ensaio eleitoral.

        Args:
            historical_shares: Proporcoes historicas normalizadas dos grupos politicos.
            match_quality: Metodo ou classificacao de qualidade do pareamento espacial.

        Returns:
            Dicionario compativel com o catalogo de secoes do ensaio eleitoral.

        Raises:
            None.
        """
        return {
            "section_id": self.section_id,
            "state": self.state,
            "municipality_code": self.municipality_code,
            "zone": self.zone,
            "section": self.section,
            "electorate": self.electorate,
            "valid_votes": self.valid_votes,
            "group_votes": self.group_votes,
            "historical_shares": historical_shares,
            "match_quality": match_quality,
            "totalized_timestamp": self.totalized_timestamp,
            "sequence_order": self.sequence_order,
        }


def _open_file_text_stream(path: Path | str) -> tuple[io.TextIOBase, Any]:
    """Abre um arquivo comum ou arquivo zipado contendo CSV/JSON para leitura de texto.

    Args:
        path: Caminho para o arquivo CSV, JSON ou ZIP.

    Returns:
        Tupla (stream de texto, objeto de fechamento de recurso).

    Raises:
        FileNotFoundError: Se o arquivo nao for encontrado.
        ValueError: Se o arquivo zip estiver vazio ou nao contiver CSV/JSON legivel.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Arquivo nao encontrado: {file_path}")

    if file_path.suffix.lower() == ".zip":
        archive = zipfile.ZipFile(file_path)
        candidates = [
            n
            for n in archive.namelist()
            if n.lower().endswith(".csv") or n.lower().endswith(".json")
        ]
        if not candidates:
            archive.close()
            raise ValueError(f"Nenhum arquivo CSV ou JSON encontrado no pacote ZIP: {file_path}")
        target_name = candidates[0]
        binary_stream = archive.open(target_name)
        text_stream = io.TextIOWrapper(binary_stream, encoding="latin1")
        return text_stream, archive

    stream = open(file_path, encoding="utf-8-sig", errors="replace")
    return stream, stream


def _parse_datetime(dt_str: str | None, hh_str: str | None = None) -> datetime | None:
    """Interpreta data e hora em formatos comuns do TSE ou ISO.

    Args:
        dt_str: Texto da data (ex: '04/10/2026' ou '2026-10-04T17:00:00Z').
        hh_str: Texto opcional da hora (ex: '17:04:47').

    Returns:
        Objeto datetime em UTC ou None se a conversao falhar.

    Raises:
        None.
    """
    if not dt_str:
        return None
    raw = dt_str.strip()
    if hh_str and hh_str.strip():
        raw = f"{raw} {hh_str.strip()}"

    for fmt in (
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        iso_parsed = datetime.fromisoformat(raw)
        if iso_parsed.tzinfo is None:
            iso_parsed = iso_parsed.replace(tzinfo=UTC)
        return iso_parsed
    except ValueError:
        return None


class RealDataLoader:
    """Carregador de dados reais de 2022 e 2026 a partir de arquivos oficiais ou consolidados."""

    def __init__(self, taxonomy: Mapping[str, str] | None = None) -> None:
        """Inicializa o carregador com taxonomia partidaria de candidatos.

        Args:
            taxonomy: Mapeamento opcional de numero de candidato para grupo ('PT', 'PL', etc.).

        Returns:
            None.

        Raises:
            None.
        """
        self._taxonomy = dict(taxonomy or DEFAULT_CANDIDATE_TAXONOMY)

    def load_2018_historical_data(
        self,
        path: Path | str,
        limit_rows: int | None = None,
        filter_ufs: Sequence[str] | None = None,
    ) -> tuple[list[HistoricalLocation], dict[str, HistoricalVoteProfile]]:
        """Carrega dados historicos de 2018 com taxonomia ideologica compatibilizada.

        Mapeia candidatos de 2018 para grupos canonicos ('PT', 'PL' para Direita/Bolsonaro).

        Args:
            path: Caminho para o arquivo CSV, JSON ou ZIP com os dados de 2018.
            limit_rows: Limite opcional de linhas a processar.
            filter_ufs: Lista opcional de siglas de UFs para filtrar.

        Returns:
            Tupla contendo a lista de HistoricalLocation e o dicionario de HistoricalVoteProfile.

        Raises:
            FileNotFoundError: Se o arquivo nao existir.
            ValidationError: Se o formato for invalido.
        """
        # Salva taxonomia atual e injeta 17 -> PL para 2018
        orig_tax = dict(self._taxonomy)
        try:
            self._taxonomy["17"] = "PL"
            self._taxonomy["13"] = "PT"
            return self.load_2022_historical_data(
                path, limit_rows=limit_rows, filter_ufs=filter_ufs
            )
        finally:
            self._taxonomy = orig_tax

    def load_2022_historical_data(
        self,
        path: Path | str,
        limit_rows: int | None = None,
        filter_ufs: Sequence[str] | None = None,
    ) -> tuple[list[HistoricalLocation], dict[str, HistoricalVoteProfile]]:
        """Carrega dados historicos de 2022 de arquivos consolidados ou do TSE.

        Args:
            path: Caminho para o arquivo CSV, JSON ou ZIP com os dados de 2022.
            limit_rows: Limite opcional de linhas a processar.
            filter_ufs: Lista opcional de siglas de UFs para filtrar.

        Returns:
            Tupla contendo a lista de HistoricalLocation e o dicionario de HistoricalVoteProfile.

        Raises:
            FileNotFoundError: Se o arquivo nao existir.
            ValidationError: Se o formato for invalido.
        """
        text_stream, closer = _open_file_text_stream(path)
        try:
            first_line = text_stream.readline()
            if not first_line:
                raise ValidationError("Arquivo de historico de 2022 esta vazio.")
            text_stream.seek(0)

            # Verifica se e JSON
            if first_line.strip().startswith("[") or first_line.strip().startswith("{"):
                return self._load_2022_json(text_stream, filter_ufs)

            # Detecta delimitador CSV (ponto-e-virgula ou virgula)
            delimiter = ";" if ";" in first_line else ","
            reader = csv.DictReader(text_stream, delimiter=delimiter)
            fieldnames = [f.strip() for f in (reader.fieldnames or [])]

            # Detecta se e formato bruto do TSE (linhas por votavel) ou consolidado
            is_raw_tse = "NR_VOTAVEL" in fieldnames and "QT_VOTOS" in fieldnames

            if is_raw_tse:
                return self._parse_2022_raw_tse_csv(reader, limit_rows, filter_ufs)
            return self._parse_2022_consolidated_csv(reader, limit_rows, filter_ufs)
        finally:
            if hasattr(closer, "close"):
                closer.close()

    def _load_2022_json(
        self,
        stream: io.TextIOBase,
        filter_ufs: Sequence[str] | None = None,
    ) -> tuple[list[HistoricalLocation], dict[str, HistoricalVoteProfile]]:
        """Carrega locais e votos historicos a partir de JSON estruturado.

        Args:
            stream: Stream de texto contendo o JSON.
            filter_ufs: UFs permitidas.

        Returns:
            Tupla com lista de HistoricalLocation e dicionario de HistoricalVoteProfile.

        Raises:
            ValidationError: Se a estrutura JSON nao for uma lista valida.
        """
        try:
            data = json.load(stream)
        except json.JSONDecodeError as error:
            raise ValidationError("JSON de historico 2022 malformado.") from error

        if not isinstance(data, list):
            raise ValidationError("JSON de historico 2022 deve ser uma lista de registros.")

        allowed_ufs = {uf.upper() for uf in filter_ufs} if filter_ufs else None
        locations: list[HistoricalLocation] = []
        votes: dict[str, HistoricalVoteProfile] = {}

        for item in data:
            if not isinstance(item, dict):
                continue
            uf = str(item.get("state") or item.get("SG_UF", "")).upper()
            if allowed_ufs and uf not in allowed_ufs:
                continue

            muni = str(item.get("municipality_code") or item.get("CD_MUNICIPIO", "")).zfill(5)
            zone = str(item.get("zone") or item.get("NR_ZONA", "")).zfill(4)
            loc_val = item.get("local_code") or item.get("NR_LOCAL_VOTACAO", "0001")
            local_code = str(loc_val).zfill(4)
            loc_id = str(item.get("location_id") or f"{uf}:{muni}:{zone}:{local_code}")

            electorate = int(item.get("electorate") or item.get("QT_APTOS", 0) or 0)
            valid_votes = int(item.get("valid_votes") or item.get("QT_VOTOS_VALIDOS", 0) or 0)
            raw_to = item.get("turnout") or item.get("QT_COMPARECIMENTO", valid_votes)
            turnout = int(raw_to or valid_votes)

            # Extrai votos por grupo
            pt_votes = int(item.get("votes_pt") or item.get("pt_votes", 0) or 0)
            pl_votes = int(item.get("votes_pl") or item.get("pl_votes", 0) or 0)
            outros_votes = int(item.get("votes_outros") or item.get("outros_votes", 0) or 0)

            if valid_votes == 0 and (pt_votes + pl_votes + outros_votes) > 0:
                valid_votes = pt_votes + pl_votes + outros_votes
            if turnout < valid_votes:
                turnout = valid_votes

            lat = float(item["latitude"]) if item.get("latitude") is not None else None
            lon = float(item["longitude"]) if item.get("longitude") is not None else None

            locations.append(
                HistoricalLocation(
                    location_id=loc_id,
                    state=uf,
                    municipality_code=muni,
                    zone=zone,
                    local_code=local_code,
                    latitude=lat,
                    longitude=lon,
                    electorate=electorate,
                )
            )
            votes[loc_id] = HistoricalVoteProfile(
                location_id=loc_id,
                valid_votes=valid_votes,
                turnout=turnout,
                group_votes=(("OUTROS", outros_votes), ("PL", pl_votes), ("PT", pt_votes)),
            )

        return locations, votes

    def _parse_2022_consolidated_csv(
        self,
        reader: csv.DictReader[str],
        limit_rows: int | None,
        filter_ufs: Sequence[str] | None,
    ) -> tuple[list[HistoricalLocation], dict[str, HistoricalVoteProfile]]:
        """Processa CSV consolidado com um registro por local ou secao eleitoral de 2022.

        Args:
            reader: Leitor CSV tipado.
            limit_rows: Limite maximo de linhas a ler.
            filter_ufs: UFs selecionadas.

        Returns:
            Tupla com lista de HistoricalLocation e dicionario de HistoricalVoteProfile.

        Raises:
            None.
        """
        allowed_ufs = {uf.upper() for uf in filter_ufs} if filter_ufs else None
        locations: list[HistoricalLocation] = []
        votes: dict[str, HistoricalVoteProfile] = {}

        for i, row in enumerate(reader):
            if limit_rows is not None and i >= limit_rows:
                break
            uf = str(row.get("state") or row.get("SG_UF", "")).strip().upper()
            if not uf or (allowed_ufs and uf not in allowed_ufs):
                continue

            muni = str(row.get("municipality_code") or row.get("CD_MUNICIPIO", "")).strip().zfill(5)
            zone = str(row.get("zone") or row.get("NR_ZONA", "")).strip().zfill(4)
            loc_val = row.get("local_code") or row.get("NR_LOCAL_VOTACAO", "0001")
            local_code = str(loc_val).strip().zfill(4)
            loc_id = str(row.get("location_id") or f"{uf}:{muni}:{zone}:{local_code}")

            electorate = int(row.get("electorate") or row.get("QT_APTOS", 0) or 0)
            valid_votes = int(row.get("valid_votes") or row.get("QT_VOTOS_VALIDOS", 0) or 0)
            turnout = int(row.get("turnout") or row.get("QT_COMPARECIMENTO", 0) or 0)

            pt = int(row.get("votes_pt") or row.get("pt_votes", 0) or 0)
            pl = int(row.get("votes_pl") or row.get("pl_votes", 0) or 0)
            outros = int(row.get("votes_outros") or row.get("outros_votes", 0) or 0)

            if valid_votes == 0:
                valid_votes = pt + pl + outros
            if turnout < valid_votes:
                turnout = valid_votes

            lat_str = row.get("latitude")
            lon_str = row.get("longitude")
            lat = float(lat_str) if lat_str and lat_str.strip() else None
            lon = float(lon_str) if lon_str and lon_str.strip() else None

            locations.append(
                HistoricalLocation(
                    location_id=loc_id,
                    state=uf,
                    municipality_code=muni,
                    zone=zone,
                    local_code=local_code,
                    latitude=lat,
                    longitude=lon,
                    electorate=electorate,
                )
            )
            votes[loc_id] = HistoricalVoteProfile(
                location_id=loc_id,
                valid_votes=valid_votes,
                turnout=turnout,
                group_votes=(("OUTROS", outros), ("PL", pl), ("PT", pt)),
            )

        return locations, votes

    def _parse_2022_raw_tse_csv(
        self,
        reader: csv.DictReader[str],
        limit_rows: int | None,
        filter_ufs: Sequence[str] | None,
    ) -> tuple[list[HistoricalLocation], dict[str, HistoricalVoteProfile]]:
        """Agrega CSV bruto do TSE com votacao por candidato em locais historicos de 2022.

        Args:
            reader: Leitor CSV posicionado nas linhas do arquivo do TSE.
            limit_rows: Limite de linhas a processar.
            filter_ufs: UFs permitidas.

        Returns:
            Tupla com lista de HistoricalLocation e dicionario de HistoricalVoteProfile.

        Raises:
            None.
        """
        allowed_ufs = {uf.upper() for uf in filter_ufs} if filter_ufs else None
        loc_map: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"PT": 0, "PL": 0, "OUTROS": 0, "valid": 0, "turnout": 0}
        )
        meta_map: dict[str, tuple[str, str, str, str]] = {}

        for i, row in enumerate(reader):
            if limit_rows is not None and i >= limit_rows:
                break
            # Filtra apenas eleicao para Presidente se coluna de cargo estiver presente
            cargo = str(row.get("DS_CARGO") or row.get("CD_CARGO", "")).upper()
            if cargo and cargo not in ("PRESIDENTE", "1"):
                continue

            uf = str(row.get("SG_UF", "")).strip().upper()
            if not uf or (allowed_ufs and uf not in allowed_ufs):
                continue

            muni = str(row.get("CD_MUNICIPIO", "")).strip().zfill(5)
            zone = str(row.get("NR_ZONA", "")).strip().zfill(4)
            local = str(row.get("NR_LOCAL_VOTACAO", "0001")).strip().zfill(4)
            loc_id = f"{uf}:{muni}:{zone}:{local}"

            if loc_id not in meta_map:
                meta_map[loc_id] = (uf, muni, zone, local)

            qt_votes = int(row.get("QT_VOTOS", 0) or 0)
            cand = str(row.get("NR_VOTAVEL", "")).strip()

            loc_map[loc_id]["turnout"] += qt_votes
            if cand not in ("95", "96", "BRANCO", "NULO"):
                loc_map[loc_id]["valid"] += qt_votes
                group = self._taxonomy.get(cand, "OUTROS")
                loc_map[loc_id][group] += qt_votes

        locations: list[HistoricalLocation] = []
        votes: dict[str, HistoricalVoteProfile] = {}

        for loc_id, (uf, muni, zone, local) in meta_map.items():
            data = loc_map[loc_id]
            valid = data["valid"]
            turnout = max(valid, data["turnout"])
            pt_v = data["PT"]
            pl_v = data["PL"]
            outros_v = data["OUTROS"]

            locations.append(
                HistoricalLocation(
                    location_id=loc_id,
                    state=uf,
                    municipality_code=muni,
                    zone=zone,
                    local_code=local,
                    electorate=int(round(turnout / 0.80)) if turnout > 0 else 0,
                )
            )
            votes[loc_id] = HistoricalVoteProfile(
                location_id=loc_id,
                valid_votes=valid,
                turnout=turnout,
                group_votes=(("OUTROS", outros_v), ("PL", pl_v), ("PT", pt_v)),
            )

        return locations, votes

    def load_2026_results_data(
        self,
        path: Path | str,
        limit_rows: int | None = None,
        filter_ufs: Sequence[str] | None = None,
    ) -> list[RealSectionRecord]:
        """Carrega resultados reais de 2026 por secao a partir de CSV, JSON ou ZIP do TSE.

        Args:
            path: Caminho para o arquivo CSV, JSON ou ZIP com apuracao de 2026.
            limit_rows: Limite de registros a processar.
            filter_ufs: UFs permitidas.

        Returns:
            Lista ordenada de RealSectionRecord correspondentes as secoes da eleicao.

        Raises:
            FileNotFoundError: Se o arquivo nao for encontrado.
            ValidationError: Se o arquivo estiver corrompido ou malformado.
        """
        text_stream, closer = _open_file_text_stream(path)
        try:
            first_line = text_stream.readline()
            if not first_line:
                raise ValidationError("Arquivo de apuracao de 2026 esta vazio.")
            text_stream.seek(0)

            if first_line.strip().startswith("[") or first_line.strip().startswith("{"):
                return self._load_2026_json(text_stream, filter_ufs)

            delimiter = ";" if ";" in first_line else ","
            reader = csv.DictReader(text_stream, delimiter=delimiter)
            fieldnames = [f.strip() for f in (reader.fieldnames or [])]

            is_raw_tse = "NR_VOTAVEL" in fieldnames and "QT_VOTOS" in fieldnames
            if is_raw_tse:
                return self._parse_2026_raw_tse_csv(reader, limit_rows, filter_ufs)
            return self._parse_2026_consolidated_csv(reader, limit_rows, filter_ufs)
        finally:
            if hasattr(closer, "close"):
                closer.close()

    def _load_2026_json(
        self,
        stream: io.TextIOBase,
        filter_ufs: Sequence[str] | None,
    ) -> list[RealSectionRecord]:
        """Carrega secoes reais de 2026 a partir de JSON estruturado.

        Args:
            stream: Stream de texto contendo o JSON.
            filter_ufs: UFs permitidas.

        Returns:
            Lista de RealSectionRecord.

        Raises:
            ValidationError: Se o JSON nao for uma lista valida.
        """
        try:
            data = json.load(stream)
        except json.JSONDecodeError as error:
            raise ValidationError("JSON de apuracao 2026 malformado.") from error

        if not isinstance(data, list):
            raise ValidationError("JSON de apuracao 2026 deve ser uma lista de secoes.")

        allowed_ufs = {uf.upper() for uf in filter_ufs} if filter_ufs else None
        records: list[RealSectionRecord] = []

        for order, item in enumerate(data, start=1):
            if not isinstance(item, dict):
                continue
            uf = str(item.get("state") or item.get("SG_UF", "")).upper()
            if allowed_ufs and uf not in allowed_ufs:
                continue

            muni = str(item.get("municipality_code") or item.get("CD_MUNICIPIO", "")).zfill(5)
            zone = str(item.get("zone") or item.get("NR_ZONA", "")).zfill(4)
            sec = str(item.get("section") or item.get("NR_SECAO", "")).zfill(4)
            sec_id = str(item.get("section_id") or f"{uf}:{muni}:{zone}:{sec}")
            local = str(item.get("local_code") or item.get("NR_LOCAL_VOTACAO", "0001")).zfill(4)

            electorate = int(item.get("electorate") or item.get("QT_APTOS", 0) or 0)
            valid_votes = int(item.get("valid_votes") or item.get("QT_VOTOS_VALIDOS", 0) or 0)
            blank_votes = int(item.get("blank_votes") or item.get("QT_VOTOS_BRANCOS", 0) or 0)
            null_votes = int(item.get("null_votes") or item.get("QT_VOTOS_NULOS", 0) or 0)

            pt = int(item.get("votes_pt") or item.get("pt_votes", 0) or 0)
            pl = int(item.get("votes_pl") or item.get("pl_votes", 0) or 0)
            outros = int(item.get("votes_outros") or item.get("outros_votes", 0) or 0)

            if valid_votes == 0:
                valid_votes = pt + pl + outros
            if electorate == 0:
                electorate = int(round((valid_votes + blank_votes + null_votes) / 0.80))

            dt_parsed = _parse_datetime(item.get("timestamp") or item.get("DT_GERACAO"))

            records.append(
                RealSectionRecord(
                    section_id=sec_id,
                    state=uf,
                    municipality_code=muni,
                    zone=zone,
                    section=sec,
                    electorate=electorate,
                    valid_votes=valid_votes,
                    blank_votes=blank_votes,
                    null_votes=null_votes,
                    group_votes=(("OUTROS", outros), ("PL", pl), ("PT", pt)),
                    totalized_timestamp=dt_parsed,
                    sequence_order=order,
                    local_code=local,
                )
            )

        return records

    def _parse_2026_consolidated_csv(
        self,
        reader: csv.DictReader[str],
        limit_rows: int | None,
        filter_ufs: Sequence[str] | None,
    ) -> list[RealSectionRecord]:
        """Processa CSV consolidado com um registro por secao de 2026.

        Args:
            reader: Leitor CSV tipado.
            limit_rows: Limite de linhas a ler.
            filter_ufs: UFs permitidas.

        Returns:
            Lista de RealSectionRecord.

        Raises:
            None.
        """
        allowed_ufs = {uf.upper() for uf in filter_ufs} if filter_ufs else None
        records: list[RealSectionRecord] = []

        for i, row in enumerate(reader, start=1):
            if limit_rows is not None and i > limit_rows:
                break
            uf = str(row.get("state") or row.get("SG_UF", "")).strip().upper()
            if not uf or (allowed_ufs and uf not in allowed_ufs):
                continue

            muni = str(row.get("municipality_code") or row.get("CD_MUNICIPIO", "")).strip().zfill(5)
            zone = str(row.get("zone") or row.get("NR_ZONA", "")).strip().zfill(4)
            sec = str(row.get("section") or row.get("NR_SECAO", "")).strip().zfill(4)
            sec_id = str(row.get("section_id") or f"{uf}:{muni}:{zone}:{sec}")
            loc_val = row.get("local_code") or row.get("NR_LOCAL_VOTACAO", "0001")
            local = str(loc_val).strip().zfill(4)

            electorate = int(row.get("electorate") or row.get("QT_APTOS", 0) or 0)
            valid_votes = int(row.get("valid_votes") or row.get("QT_VOTOS_VALIDOS", 0) or 0)
            blank_votes = int(row.get("blank_votes") or row.get("QT_VOTOS_BRANCOS", 0) or 0)
            null_votes = int(row.get("null_votes") or row.get("QT_VOTOS_NULOS", 0) or 0)

            pt = int(row.get("votes_pt") or row.get("pt_votes", 0) or 0)
            pl = int(row.get("votes_pl") or row.get("pl_votes", 0) or 0)
            outros = int(row.get("votes_outros") or row.get("outros_votes", 0) or 0)

            if valid_votes == 0:
                valid_votes = pt + pl + outros
            if electorate == 0:
                total_ballots = valid_votes + blank_votes + null_votes
                electorate = int(round(total_ballots / 0.80)) if total_ballots > 0 else 0

            dt_parsed = _parse_datetime(
                row.get("timestamp") or row.get("DT_GERACAO"),
                row.get("HH_GERACAO"),
            )

            records.append(
                RealSectionRecord(
                    section_id=sec_id,
                    state=uf,
                    municipality_code=muni,
                    zone=zone,
                    section=sec,
                    electorate=electorate,
                    valid_votes=valid_votes,
                    blank_votes=blank_votes,
                    null_votes=null_votes,
                    group_votes=(("OUTROS", outros), ("PL", pl), ("PT", pt)),
                    totalized_timestamp=dt_parsed,
                    sequence_order=i,
                    local_code=local,
                )
            )

        return records

    def _parse_2026_raw_tse_csv(
        self,
        reader: csv.DictReader[str],
        limit_rows: int | None,
        filter_ufs: Sequence[str] | None,
    ) -> list[RealSectionRecord]:
        """Agrega linhas por candidato da apuracao do TSE em secoes consolidadas de 2026.

        Args:
            reader: Leitor CSV posicionado nas linhas do TSE.
            limit_rows: Limite de linhas a agregar.
            filter_ufs: UFs permitidas.

        Returns:
            Lista de RealSectionRecord.

        Raises:
            None.
        """
        allowed_ufs = {uf.upper() for uf in filter_ufs} if filter_ufs else None
        sections_data: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "PT": 0,
                "PL": 0,
                "OUTROS": 0,
                "valid": 0,
                "blank": 0,
                "null": 0,
                "turnout": 0,
                "timestamp": None,
                "local": "0001",
            }
        )
        meta_dict: dict[str, tuple[str, str, str, str]] = {}
        order_dict: dict[str, int] = {}
        seq = 0

        for i, row in enumerate(reader):
            if limit_rows is not None and i >= limit_rows:
                break
            cargo = str(row.get("DS_CARGO") or row.get("CD_CARGO", "")).upper()
            if cargo and cargo not in ("PRESIDENTE", "1"):
                continue

            uf = str(row.get("SG_UF", "")).strip().upper()
            if not uf or (allowed_ufs and uf not in allowed_ufs):
                continue

            muni = str(row.get("CD_MUNICIPIO", "")).strip().zfill(5)
            zone = str(row.get("NR_ZONA", "")).strip().zfill(4)
            sec = str(row.get("NR_SECAO", "")).strip().zfill(4)
            sec_id = f"{uf}:{muni}:{zone}:{sec}"

            if sec_id not in meta_dict:
                seq += 1
                order_dict[sec_id] = seq
                meta_dict[sec_id] = (uf, muni, zone, sec)

            votes = int(row.get("QT_VOTOS", 0) or 0)
            cand = str(row.get("NR_VOTAVEL", "")).strip()
            local = str(row.get("NR_LOCAL_VOTACAO", "0001")).strip().zfill(4)

            s_entry = sections_data[sec_id]
            s_entry["turnout"] += votes
            s_entry["local"] = local

            if s_entry["timestamp"] is None:
                s_entry["timestamp"] = _parse_datetime(row.get("DT_GERACAO"), row.get("HH_GERACAO"))

            if cand in ("95", "BRANCO"):
                s_entry["blank"] += votes
            elif cand in ("96", "NULO"):
                s_entry["null"] += votes
            else:
                s_entry["valid"] += votes
                group = self._taxonomy.get(cand, "OUTROS")
                s_entry[group] += votes

        records: list[RealSectionRecord] = []
        for sec_id, (uf, muni, zone, sec) in meta_dict.items():
            entry = sections_data[sec_id]
            valid = entry["valid"]
            turnout = entry["turnout"]
            electorate = int(round(turnout / 0.80)) if turnout > 0 else 0

            records.append(
                RealSectionRecord(
                    section_id=sec_id,
                    state=uf,
                    municipality_code=muni,
                    zone=zone,
                    section=sec,
                    electorate=electorate,
                    valid_votes=valid,
                    blank_votes=entry["blank"],
                    null_votes=entry["null"],
                    group_votes=(
                        ("OUTROS", entry["OUTROS"]),
                        ("PL", entry["PL"]),
                        ("PT", entry["PT"]),
                    ),
                    totalized_timestamp=entry["timestamp"],
                    sequence_order=order_dict[sec_id],
                    local_code=entry["local"],
                )
            )

        return records

    def build_real_election_catalog(
        self,
        historical_locations: Sequence[HistoricalLocation],
        historical_votes: Mapping[str, HistoricalVoteProfile],
        results_2026: Sequence[RealSectionRecord],
        configured_groups: tuple[str, ...] = ("OUTROS", "PL", "PT"),
    ) -> list[dict[str, Any]]:
        """Pareia secoes reais de 2026 com o historico de 2022 e monta o catalogo ordenado.

        Args:
            historical_locations: Locais eleitorais conhecidos de 2022.
            historical_votes: Votos historicos por local de 2022.
            results_2026: Secoes com apuracao real de 2026.
            configured_groups: Grupos partidarios esperados para projecao.

        Returns:
            Lista ordenada de dicionarios compativeis com o pipeline de simulacao.

        Raises:
            ValidationError: Se results_2026 estiver vazio.
        """
        if not results_2026:
            raise ValidationError("results_2026 nao pode ser vazio para construir o catalogo.")

        matcher = GeographicMatcher(historical_locations)
        profile_builder = HistoricalProfileBuilder(
            historical_votes=historical_votes,
            configured_groups=configured_groups,
        )

        election_key = ElectionKey("002026", "01", "PRESIDENTE")
        catalog_items: list[dict[str, Any]] = []

        for record in results_2026:
            sec_key = SectionKey(
                election=election_key,
                municipality=MunicipalityKey(record.state, record.municipality_code),
                zone=record.zone,
                section=record.section,
            )

            candidates = matcher.match(
                sec_key,
                local_code=record.local_code,
                latitude=record.latitude,
                longitude=record.longitude,
            )

            if not candidates:
                # Fallback extremo caso o matcher estadual nao encontre candidatos
                candidates = (
                    MatchCandidate(
                        candidate_location_id="FALLBACK_NATIONAL",
                        method=MatchQuality.UNMATCHED,
                        distance_meters=None,
                        weight=1.0,
                        rank=1,
                    ),
                )

            profile = profile_builder.build_profile(sec_key, candidates)
            hist_shares = tuple(
                (grp, float(share)) for grp, share in sorted(profile.shares, key=lambda x: x[0])
            )

            catalog_items.append(
                record.to_catalog_dict(
                    historical_shares=hist_shares,
                    match_quality=str(profile.primary_method.value),
                )
            )

        # Verifica se os registros de apuracao possuem timestamps distintos preexistentes
        unique_timestamps = {
            r.totalized_timestamp for r in results_2026 if r.totalized_timestamp is not None
        }
        has_distinct_timestamps = len(unique_timestamps) > 1

        if has_distinct_timestamps:
            # Preserva a ordem cronologica dada pelos timestamps explicitos
            catalog_items.sort(
                key=lambda x: (
                    x.get("totalized_timestamp") or datetime.min.replace(tzinfo=UTC),
                    x.get("sequence_order", 0),
                )
            )
        else:
            # Aplica ordenacao cronologica regional calibrada com a velocidade historica do TSE
            catalog_items.sort(
                key=lambda x: (
                    compute_section_arrival_score(str(x["section_id"]), str(x["state"])),
                    str(x["section_id"]),
                )
            )
            # Atribui timestamps realistas ao longo da noite da eleicao (17:05 as 22:30 UTC)
            start_time = datetime(2026, 10, 4, 17, 5, 0, tzinfo=UTC)
            total_duration_secs = 19500
            n = len(catalog_items)
            for rank, item in enumerate(catalog_items, start=1):
                fraction = (rank - 1) / max(1, n - 1)
                elapsed = int(total_duration_secs * (fraction**1.1))
                item["totalized_timestamp"] = start_time + timedelta(seconds=elapsed)
                item["sequence_order"] = rank

        return catalog_items

    def save_catalog_csv(
        self,
        catalog: Sequence[Mapping[str, Any]],
        path: Path | str,
    ) -> int:
        """Serializa catalogo de eleicao consolidado para arquivo CSV otimizado.

        Args:
            catalog: Sequencia de dicionarios com atributos das secoes eleitorais.
            path: Caminho de destino para gravacao do arquivo CSV.

        Returns:
            Quantidade total de registros de secoes gravados com sucesso.

        Raises:
            IOError: Se houver falha de escrita no sistema de arquivos.
        """
        dest_path = Path(path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "section_id",
                    "state",
                    "municipality_code",
                    "zone",
                    "section",
                    "local_code",
                    "electorate",
                    "valid_votes",
                    "votes_pt",
                    "votes_pl",
                    "votes_outros",
                    "blank_votes",
                    "null_votes",
                    "hist_pt",
                    "hist_pl",
                    "hist_outros",
                    "timestamp",
                    "sequence_order",
                ]
            )
            for item in catalog:
                g_dict = dict(item.get("group_votes", ()))
                h_dict = dict(item.get("historical_shares", ()))
                ts = item.get("totalized_timestamp")
                ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts or "")
                writer.writerow(
                    [
                        str(item.get("section_id", "")),
                        str(item.get("state", "")),
                        str(item.get("municipality_code", "")),
                        str(item.get("zone", "")),
                        str(item.get("section", "")),
                        str(item.get("local_code", "0001")),
                        int(item.get("electorate", 0)),
                        int(item.get("valid_votes", 0)),
                        int(g_dict.get("PT", 0)),
                        int(g_dict.get("PL", 0)),
                        int(g_dict.get("OUTROS", 0)),
                        int(item.get("blank_votes", 0)),
                        int(item.get("null_votes", 0)),
                        float(h_dict.get("PT", 0.0)),
                        float(h_dict.get("PL", 0.0)),
                        float(h_dict.get("OUTROS", 0.0)),
                        ts_str,
                        int(item.get("sequence_order", 0)),
                    ]
                )
        return len(catalog)

    def load_catalog_csv(
        self,
        path: Path | str,
        limit_rows: int | None = None,
        filter_ufs: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Carrega catalogo previamente pareado e consolidado a partir de CSV.

        Args:
            path: Caminho para o arquivo CSV de catalogo consolidado.
            limit_rows: Limite maximo opcional de secoes a carregar.
            filter_ufs: Lista opcional de siglas de UFs permitidas.

        Returns:
            Lista de dicionarios de secoes prontos para a simulacao.

        Raises:
            FileNotFoundError: Se o arquivo nao existir.
            ValidationError: Se o arquivo estiver vazio ou corrompido.
        """
        src_path = Path(path)
        if not src_path.exists():
            raise FileNotFoundError(f"Arquivo de catalogo nao encontrado: {src_path}")

        allowed_ufs = {uf.upper() for uf in filter_ufs} if filter_ufs else None
        items: list[dict[str, Any]] = []

        with open(src_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                if limit_rows is not None and i >= limit_rows:
                    break
                uf = str(row.get("state", "")).strip().upper()
                if not uf or (allowed_ufs and uf not in allowed_ufs):
                    continue

                ts_val = _parse_datetime(row.get("timestamp"))
                items.append(
                    {
                        "section_id": str(row["section_id"]),
                        "state": uf,
                        "municipality_code": str(row["municipality_code"]).zfill(5),
                        "zone": str(row["zone"]).zfill(4),
                        "section": str(row["section"]).zfill(4),
                        "local_code": str(row.get("local_code", "0001")).zfill(4),
                        "electorate": int(row.get("electorate", 0) or 0),
                        "valid_votes": int(row.get("valid_votes", 0) or 0),
                        "blank_votes": int(row.get("blank_votes", 0) or 0),
                        "null_votes": int(row.get("null_votes", 0) or 0),
                        "group_votes": (
                            ("OUTROS", int(row.get("votes_outros", 0) or 0)),
                            ("PL", int(row.get("votes_pl", 0) or 0)),
                            ("PT", int(row.get("votes_pt", 0) or 0)),
                        ),
                        "historical_shares": (
                            ("OUTROS", float(row.get("hist_outros", 0.0) or 0.0)),
                            ("PL", float(row.get("hist_pl", 0.0) or 0.0)),
                            ("PT", float(row.get("hist_pt", 0.0) or 0.0)),
                        ),
                        "totalized_timestamp": ts_val,
                        "sequence_order": int(row.get("sequence_order", 0) or (i + 1)),
                    }
                )

        if not items:
            raise ValidationError(f"Nenhum registro valido encontrado no catalogo: {src_path}")

        return items

    def save_catalog_parquet(
        self,
        catalog: Sequence[Mapping[str, Any]],
        path: Path | str,
        compression: str = "zstd",
    ) -> int:
        """Serializa catalogo de eleicao consolidado para arquivo Apache Parquet analitico.

        Args:
            catalog: Sequencia de dicionarios com atributos das secoes eleitorais.
            path: Caminho de destino para gravacao do arquivo Parquet.
            compression: Algoritmo de compressao colunar ('zstd', 'snappy', etc.).

        Returns:
            Quantidade total de registros de secoes gravados com sucesso.

        Raises:
            IOError: Se houver falha de escrita no sistema de arquivos.
            ValidationError: Se o catalogo estiver vazio.
        """
        if not catalog:
            raise ValidationError("Catalogo vazio nao pode ser gravado em formato Parquet.")

        dest_path = Path(path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        n = len(catalog)
        sec_ids: list[str] = [str(item.get("section_id", "")) for item in catalog]
        states: list[str] = [str(item.get("state", "")).strip().upper() for item in catalog]
        munis: list[str] = [
            str(item.get("municipality_code", "")).strip().zfill(5) for item in catalog
        ]
        zones: list[str] = [str(item.get("zone", "")).strip().zfill(4) for item in catalog]
        secs: list[str] = [str(item.get("section", "")).strip().zfill(4) for item in catalog]
        locals_: list[str] = [
            str(item.get("local_code", "0001")).strip().zfill(4) for item in catalog
        ]
        elecs: list[int] = [int(item.get("electorate", 0) or 0) for item in catalog]
        valids: list[int] = [int(item.get("valid_votes", 0) or 0) for item in catalog]

        pts: list[int] = []
        pls: list[int] = []
        outros: list[int] = []
        blanks: list[int] = []
        nulls: list[int] = []
        h_pts: list[float] = []
        h_pls: list[float] = []
        h_outros: list[float] = []
        tss: list[datetime | None] = []
        seqs: list[int] = []
        match_qualities: list[str] = [
            str(item.get("match_quality", "EXACT") or "EXACT") for item in catalog
        ]

        for item in catalog:
            g_dict = dict(item.get("group_votes", ()))
            h_dict = dict(item.get("historical_shares", ()))
            pts.append(int(g_dict.get("PT", 0) or 0))
            pls.append(int(g_dict.get("PL", 0) or 0))
            outros.append(int(g_dict.get("OUTROS", 0) or 0))
            blanks.append(int(item.get("blank_votes", 0) or 0))
            nulls.append(int(item.get("null_votes", 0) or 0))
            h_pts.append(float(h_dict.get("PT", 0.0) or 0.0))
            h_pls.append(float(h_dict.get("PL", 0.0) or 0.0))
            h_outros.append(float(h_dict.get("OUTROS", 0.0) or 0.0))

            raw_ts = item.get("totalized_timestamp")
            tz_ts: datetime | None = None
            if isinstance(raw_ts, datetime):
                tz_ts = raw_ts.astimezone(UTC) if raw_ts.tzinfo else raw_ts.replace(tzinfo=UTC)
            elif isinstance(raw_ts, str) and raw_ts:
                tz_ts = _parse_datetime(raw_ts)
            tss.append(tz_ts)
            seqs.append(int(item.get("sequence_order", 0) or 0))

        table = pa.table(
            {
                "section_id": pa.array(sec_ids, type=pa.string()),
                "state": pa.array(states, type=pa.string()),
                "municipality_code": pa.array(munis, type=pa.string()),
                "zone": pa.array(zones, type=pa.string()),
                "section": pa.array(secs, type=pa.string()),
                "local_code": pa.array(locals_, type=pa.string()),
                "electorate": pa.array(elecs, type=pa.int32()),
                "valid_votes": pa.array(valids, type=pa.int32()),
                "votes_pt": pa.array(pts, type=pa.int32()),
                "votes_pl": pa.array(pls, type=pa.int32()),
                "votes_outros": pa.array(outros, type=pa.int32()),
                "blank_votes": pa.array(blanks, type=pa.int32()),
                "null_votes": pa.array(nulls, type=pa.int32()),
                "hist_pt": pa.array(h_pts, type=pa.float64()),
                "hist_pl": pa.array(h_pls, type=pa.float64()),
                "hist_outros": pa.array(h_outros, type=pa.float64()),
                "match_quality": pa.array(match_qualities, type=pa.string()),
                "timestamp": pa.array(tss, type=pa.timestamp("us", tz="UTC")),
                "sequence_order": pa.array(seqs, type=pa.int32()),
            }
        )

        pq.write_table(table, dest_path, compression=compression)
        return n

    def load_catalog_parquet(
        self,
        path: Path | str,
        limit_rows: int | None = None,
        filter_ufs: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Carrega catalogo a partir de arquivo Apache Parquet analitico de alta performance.

        Utiliza predicate pushdown para carregar apenas as secoes solicitadas diretamente
        do formato colunar comprimido.

        Args:
            path: Caminho para o arquivo Apache Parquet consolidado.
            limit_rows: Limite maximo opcional de secoes a carregar.
            filter_ufs: Lista opcional de siglas de UFs permitidas.

        Returns:
            Lista de dicionarios de secoes prontos para simulacao e projecao.

        Raises:
            FileNotFoundError: Se o arquivo nao for localizado.
            ValidationError: Se o arquivo estiver vazio ou corrompido.
        """
        src_path = Path(path)
        if not src_path.exists():
            raise FileNotFoundError(f"Arquivo Parquet nao encontrado: {src_path}")

        allowed_ufs = [uf.upper() for uf in filter_ufs] if filter_ufs else None
        filters = None
        if allowed_ufs:
            filters = [("state", "in", allowed_ufs)]

        try:
            table = pq.read_table(src_path, filters=filters)
        except Exception as error:
            raise ValidationError(f"Falha ao ler arquivo Parquet '{src_path}': {error}") from error

        if table.num_rows == 0:
            raise ValidationError(f"Nenhum registro encontrado no catalogo Parquet: {src_path}")

        if limit_rows is not None and table.num_rows > limit_rows:
            table = table.slice(0, limit_rows)

        cols = table.to_pydict()
        n = table.num_rows

        sec_ids = cols["section_id"]
        states = cols["state"]
        munis = cols["municipality_code"]
        zones = cols["zone"]
        sections = cols["section"]
        locals_ = cols["local_code"]
        elecs = cols["electorate"]
        valids = cols["valid_votes"]
        pts = cols["votes_pt"]
        pls = cols["votes_pl"]
        outros = cols["votes_outros"]
        blanks = cols["blank_votes"]
        nulls = cols["null_votes"]
        h_pts = cols["hist_pt"]
        h_pls = cols["hist_pl"]
        h_outros = cols["hist_outros"]
        tss = cols["timestamp"]
        seqs = cols["sequence_order"]
        match_qualities = (
            [str(mq or "EXACT") for mq in cols["match_quality"]]
            if "match_quality" in cols
            else ["EXACT"] * n
        )

        items: list[dict[str, Any]] = [
            {
                "section_id": str(sec_ids[i]),
                "state": str(states[i]),
                "municipality_code": str(munis[i]).zfill(5),
                "zone": str(zones[i]).zfill(4),
                "section": str(sections[i]).zfill(4),
                "local_code": str(locals_[i]).zfill(4),
                "electorate": int(elecs[i] or 0),
                "valid_votes": int(valids[i] or 0),
                "blank_votes": int(blanks[i] or 0),
                "null_votes": int(nulls[i] or 0),
                "group_votes": (
                    ("OUTROS", int(outros[i] or 0)),
                    ("PL", int(pls[i] or 0)),
                    ("PT", int(pts[i] or 0)),
                ),
                "historical_shares": (
                    ("OUTROS", float(h_outros[i] or 0.0)),
                    ("PL", float(h_pls[i] or 0.0)),
                    ("PT", float(h_pts[i] or 0.0)),
                ),
                "match_quality": match_qualities[i],
                "totalized_timestamp": tss[i],
                "sequence_order": int(seqs[i] or (i + 1)),
            }
            for i in range(n)
        ]

        return items

    def query_catalog_sql(
        self,
        path: Path | str,
        sql_query: str,
    ) -> duckdb.DuckDBPyRelation:
        """Executa consultas analiticas SQL de alta performance diretamente no arquivo Parquet.

        A palavra-chave 'catalog' na query SQL e automaticamente mapeada para o arquivo Parquet.
        Exemplo:
            loader.query_catalog_sql(path, "SELECT state, sum(valid_votes) FROM catalog")

        Args:
            path: Caminho para o arquivo Parquet.
            sql_query: Instrucao SQL analitica a executar.

        Returns:
            Relacao DuckDB contendo o resultado da consulta otimizada.

        Raises:
            FileNotFoundError: Se o arquivo Parquet nao existir.
            ValidationError: Se a instrucao SQL for invalida.
        """
        src_path = Path(path)
        if not src_path.exists():
            raise FileNotFoundError(f"Arquivo Parquet nao encontrado: {src_path}")

        norm_path = src_path.as_posix()
        formatted_sql = sql_query
        if "from catalog" in formatted_sql.lower() or "join catalog" in formatted_sql.lower():
            formatted_sql = re.sub(r"(?i)\bcatalog\b", f"'{norm_path}'", formatted_sql)

        try:
            rel = duckdb.query(formatted_sql)
            if rel is None:
                raise ValidationError("Consulta DuckDB nao retornou uma relacao valida.")
            return rel
        except ValidationError:
            raise
        except Exception as error:
            raise ValidationError(f"Erro na execucao da consulta SQL no DuckDB: {error}") from error
