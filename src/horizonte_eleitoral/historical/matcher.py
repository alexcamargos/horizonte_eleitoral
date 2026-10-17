"""Servico de pareamento geografico hierarquico em cascata para secoes eleitorais."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence

from horizonte_eleitoral.domain.enums import MatchQuality
from horizonte_eleitoral.domain.models import SectionKey
from horizonte_eleitoral.historical.models import HistoricalLocation, MatchCandidate

EARTH_RADIUS_METERS = 6371000.0


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcula a distancia geodesica aproximada entre dois pontos em metros.

    Args:
        lat1: Latitude do ponto 1 em graus.
        lon1: Longitude do ponto 1 em graus.
        lat2: Latitude do ponto 2 em graus.
        lon2: Longitude do ponto 2 em graus.

    Returns:
        Distancia em metros calculada via formula de Haversine.

    Raises:
        ValueError: Se alguma coordenada estiver fora dos limites geograficos.
    """
    if not -90.0 <= lat1 <= 90.0 or not -90.0 <= lat2 <= 90.0:
        raise ValueError("Latitude deve estar entre -90 e 90 graus.")
    if not -180.0 <= lon1 <= 180.0 or not -180.0 <= lon2 <= 180.0:
        raise ValueError("Longitude deve estar entre -180 e 180 graus.")

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_METERS * c


class GeographicMatcher:
    """Motor de pareamento em cascata entre locais de 2026 e o historico.

    A cascata implementa as seguintes etapas de qualidade:
    - A_EXATA: Mesmo codigo de local, zona, municipio e UF.
    - B_MESMO_COMPLEXO: Distancia euclidiana/haversine menor ou igual a 100m.
    - C_VIZINHA: Vizinhos mais proximos no mesmo municipio ate 5000m.
    - D_MESMA_ZONA: Media das secoes historicas da mesma zona eleitoral.
    - E_MESMO_MUNICIPIO: Media das secoes historicas do mesmo municipio.
    - F_SEM_PAREAMENTO: Fallback estadual marcado para penalizacao de incerteza.
    """

    def __init__(self, locations: Sequence[HistoricalLocation]) -> None:
        """Inicializa o indexador espacial e cadastral com os locais historicos.

        Args:
            locations: Sequencia de locais historicos disponiveis.

        Returns:
            None.

        Raises:
            None.
        """
        self._exact_index: dict[tuple[str, str, str, str], HistoricalLocation] = {}
        self._zone_index: dict[tuple[str, str, str], list[HistoricalLocation]] = defaultdict(list)
        self._municipality_index: dict[tuple[str, str], list[HistoricalLocation]] = defaultdict(
            list
        )
        self._state_index: dict[str, list[HistoricalLocation]] = defaultdict(list)

        for loc in locations:
            exact_key = (loc.state, loc.municipality_code, loc.zone, loc.local_code)
            self._exact_index[exact_key] = loc

            zone_key = (loc.state, loc.municipality_code, loc.zone)
            self._zone_index[zone_key].append(loc)

            muni_key = (loc.state, loc.municipality_code)
            self._municipality_index[muni_key].append(loc)

            self._state_index[loc.state].append(loc)

    def match(
        self,
        section: SectionKey,
        *,
        local_code: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        max_neighbors: int = 5,
        complex_distance_threshold: float = 100.0,
        max_neighbor_distance: float = 5000.0,
    ) -> tuple[MatchCandidate, ...]:
        """Localiza candidatas de pareamento para uma secao segundo a cascata de qualidade.

        Args:
            section: Chave completa da secao eleitoral de 2026.
            local_code: Codigo do local de votacao da secao em 2026, se conhecido.
            latitude: Latitude decimal do local de 2026, se disponivel.
            longitude: Longitude decimal do local de 2026, se disponivel.
            max_neighbors: Numero maximo de vizinhos a incluir na classe C.
            complex_distance_threshold: Limiar em metros para considerar mesmo complexo.
            max_neighbor_distance: Limiar em metros para considerar vizinho no municipio.

        Returns:
            Tupla ordenada de candidatas de pareamento com pesos normalizados somando 1.0.

        Raises:
            None.
        """
        state = section.municipality.state
        muni_code = section.municipality.municipality_code
        zone = section.zone

        # 1. Correspondencia Exata (Classe A)
        if local_code is not None:
            exact_key = (state, muni_code, zone, local_code)
            exact_match = self._exact_index.get(exact_key)
            if exact_match is not None:
                return (
                    MatchCandidate(
                        candidate_location_id=exact_match.location_id,
                        method=MatchQuality.EXACT,
                        distance_meters=0.0,
                        weight=1.0,
                        rank=1,
                    ),
                )

        # 2 e 3. Proximidade Geografica no Municipio (Classes B e C)
        muni_locations = self._municipality_index.get((state, muni_code), [])
        if latitude is not None and longitude is not None and muni_locations:
            geo_candidates: list[tuple[float, HistoricalLocation]] = []
            for loc in muni_locations:
                if loc.latitude is not None and loc.longitude is not None:
                    dist = haversine_distance(latitude, longitude, loc.latitude, loc.longitude)
                    geo_candidates.append((dist, loc))

            if geo_candidates:
                geo_candidates.sort(key=lambda item: item[0])
                closest_dist, closest_loc = geo_candidates[0]

                # Classe B - Mesmo complexo (< 100m)
                if closest_dist <= complex_distance_threshold:
                    return (
                        MatchCandidate(
                            candidate_location_id=closest_loc.location_id,
                            method=MatchQuality.SAME_COMPLEX,
                            distance_meters=closest_dist,
                            weight=1.0,
                            rank=1,
                        ),
                    )

                # Classe C - Vizinhos proximos no municipio (< max_neighbor_distance)
                neighbors = [
                    (dist, loc)
                    for dist, loc in geo_candidates[:max_neighbors]
                    if dist <= max_neighbor_distance
                ]
                if neighbors:
                    # Decaimento exponencial dos pesos: w = exp(-d / 1000)
                    raw_weights = [math.exp(-d / 1000.0) for d, _ in neighbors]
                    total_weight = sum(raw_weights)
                    candidates: list[MatchCandidate] = []
                    for rank, ((dist, loc), raw_w) in enumerate(
                        zip(neighbors, raw_weights, strict=True), start=1
                    ):
                        candidates.append(
                            MatchCandidate(
                                candidate_location_id=loc.location_id,
                                method=MatchQuality.NEIGHBORING,
                                distance_meters=dist,
                                weight=raw_w / total_weight,
                                rank=rank,
                            )
                        )
                    return tuple(candidates)

        # 4. Mesma Zona Eleitoral (Classe D)
        zone_locations = self._zone_index.get((state, muni_code, zone), [])
        if zone_locations:
            weight = 1.0 / len(zone_locations)
            return tuple(
                MatchCandidate(
                    candidate_location_id=loc.location_id,
                    method=MatchQuality.SAME_ZONE,
                    distance_meters=None,
                    weight=weight,
                    rank=idx,
                )
                for idx, loc in enumerate(zone_locations, start=1)
            )

        # 5. Mesmo Municipio (Classe E)
        if muni_locations:
            weight = 1.0 / len(muni_locations)
            return tuple(
                MatchCandidate(
                    candidate_location_id=loc.location_id,
                    method=MatchQuality.SAME_MUNICIPALITY,
                    distance_meters=None,
                    weight=weight,
                    rank=idx,
                )
                for idx, loc in enumerate(muni_locations, start=1)
            )

        # 6. Sem pareamento no Municipio (Classe F - Fallback Estadual)
        state_locations = self._state_index.get(state, [])
        if state_locations:
            weight = 1.0 / len(state_locations)
            return tuple(
                MatchCandidate(
                    candidate_location_id=loc.location_id,
                    method=MatchQuality.UNMATCHED,
                    distance_meters=None,
                    weight=weight,
                    rank=idx,
                )
                for idx, loc in enumerate(state_locations, start=1)
            )

        return ()
