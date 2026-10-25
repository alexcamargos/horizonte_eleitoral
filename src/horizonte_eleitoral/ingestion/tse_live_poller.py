"""Servico de polling e monitoramento oficial da API do TSE com janela de apuracao."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from horizonte_eleitoral.domain.enums import ArtifactType
from horizonte_eleitoral.domain.errors import SourceUnavailableError, ValidationError
from horizonte_eleitoral.ingestion.client import TSEAsyncClient
from horizonte_eleitoral.ingestion.discovery import TSEPathResolver
from horizonte_eleitoral.normalization.adapters import normalize_ea20
from horizonte_eleitoral.normalization.models import NormalizedTotalization
from horizonte_eleitoral.publishing.models import PublishedProjectionPayload
from horizonte_eleitoral.simulation.election_night_runner import (
    simulate_2026_second_round_checkpoint,
)

BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")


def is_election_night_window(
    dt: datetime | None = None,
    *,
    ignore_gate: bool = False,
) -> bool:
    """Verifica se o momento atual esta dentro da janela de apuracao do dia da eleicao.

    A apuracao oficial do TSE comeca as 17h (horario de Brasilia, UTC-3) de domingo.
    Caso ignore_gate seja True (ambiente de testes/ensaio local), a verificacao e liberada.

    Args:
        dt: Data/hora em UTC ou com timezone. Se None, utiliza datetime.now(UTC).
        ignore_gate: Se True, ignora a restricao horaria para ensaios e testes.

    Returns:
        True se estiver dentro da janela de apuracao ou ignore_gate ativado; False caso contrario.

    Raises:
        None.
    """
    if ignore_gate:
        return True

    now_utc = dt if dt is not None else datetime.now(UTC)
    local_time = now_utc.astimezone(BRASILIA_TZ)

    # 6 representa Domingo no padrao ISO de Python (segunda=0 ... domingo=6)
    is_sunday = local_time.weekday() == 6
    is_after_17h = local_time.hour >= 17

    return is_sunday and is_after_17h


@dataclass
class TSEPollerLogEntry:
    """Registro imutavel de auditoria de uma tentativa de checagem na API do TSE.

    Attributes:
        timestamp: Horario em que a checagem foi realizada.
        http_status: Codigo de resposta HTTP ou status de bloqueio.
        totalized_electorate_pct: Percentual de eleitorado apurado observado.
        has_new_data: Se a checagem identificou novos votos ou avanco de apuracao.
        message: Descricao textual do resultado da checagem.
        url: URL oficial consultada no TSE.
    """

    timestamp: datetime
    http_status: int
    totalized_electorate_pct: float
    has_new_data: bool
    message: str
    url: str

    def to_dict(self) -> dict[str, Any]:
        """Converte o registro em dicionario para exibicao no dashboard.

        Returns:
            Dicionario contendo campos formatados para visualizacao tabular.

        Raises:
            None.
        """
        return {
            "Horário": self.timestamp.strftime("%H:%M:%S"),
            "Status": self.http_status,
            "Apurado (%)": f"{self.totalized_electorate_pct:.2f}%",
            "Dados Novos": "Sim" if self.has_new_data else "Não",
            "Mensagem": self.message,
            "URL": self.url,
        }


class TSELivePoller:
    """Gerenciador de checagens periodicas na API oficial do TSE com deteccao de novidades."""

    def __init__(
        self,
        client: TSEAsyncClient,
        resolver: TSEPathResolver,
        *,
        election_id: str = "6258",
        round_num: int = 2,
        ignore_schedule_gate: bool = False,
        target_url: str | None = None,
        endpoint_type: str = "totalization",
    ) -> None:
        """Inicializa o monitorador com o cliente HTTP, resolvedor e configuracoes de eleicao.

        Args:
            client: Instancia configurada de TSEAsyncClient com allowlist e rate limits.
            resolver: Resolvedor canonico de rotas oficiais TSEPathResolver.
            election_id: Identificador oficial do pleito (ex: '6258').
            round_num: Turno da eleicao avaliado (1 ou 2).
            ignore_schedule_gate: Permite ignorar o gate de domingo 17h para testes.
            target_url: URL completa opcional para forcar endpoint especifico.
            endpoint_type: Tipo do endpoint ('totalization', 'divulgacao', 'simplificada', 'auto').

        Returns:
            None.

        Raises:
            None.
        """
        self._client = client
        self._resolver = resolver
        self._election_id = election_id
        self._round_num = round_num
        self._ignore_schedule_gate = ignore_schedule_gate
        self._target_url = target_url
        self._endpoint_type = endpoint_type

        self._last_etag: str | None = None
        self._last_modified: str | None = None
        self._last_totalized_pct: float = 0.0
        self._last_observed_votes: dict[str, int] = {}
        self._last_published_payload: PublishedProjectionPayload | None = None
        self._history_log: list[TSEPollerLogEntry] = []

    def get_target_url(self) -> str:
        """Retorna a URL canonica que sera consultada pelo poller.

        Returns:
            URL resolvida para consulta da totalizacao.

        Raises:
            None.
        """
        if self._target_url:
            return self._target_url
        if self._endpoint_type == "divulgacao":
            return self._resolver.url_for_divulgacao(round_num=self._round_num)
        if self._endpoint_type == "simplificada":
            return self._resolver.url_for_divulgacao_simplificada(round_num=self._round_num)
        if self._endpoint_type == "auto":
            if "resultados.tse.jus.br" in self._resolver.base_url:
                return self._resolver.url_for_divulgacao(round_num=self._round_num)
        return self._resolver.url_for_totalization()

    @property
    def last_totalized_pct(self) -> float:
        """Percentual mais recente de eleitorado totalizado observado pelo poller."""
        return self._last_totalized_pct

    @property
    def last_published_payload(self) -> PublishedProjectionPayload | None:
        """Ultima projecao oficial gerada e publicada a partir de dados novos."""
        return self._last_published_payload

    @property
    def history_log(self) -> list[TSEPollerLogEntry]:
        """Historico completo de auditoria das consultas ao TSE."""
        return list(self._history_log)

    async def check_for_updates(
        self,
        *,
        now: datetime | None = None,
    ) -> tuple[bool, NormalizedTotalization | None, str]:
        """Consulta a API do TSE e detecta se ha dados novos de apuracao disponiveis.

        Verifica a janela temporal de domingo apos as 17h. Se autorizada, dispara requisicao
        condicional utilizando ETag. Ao receber resposta 200, valida se o percentual
        de apuracao ou contagem de votos validos avancou.

        Args:
            now: Data e hora de referencia para avaliacao da janela temporal.

        Returns:
            Tupla contendo:
                - has_new_data: Booleano indicando se ha novos dados para recalcular projecao.
                - totalization: Instancia normalizada de NormalizedTotalization ou None.
                - message: Mensagem detalhada sobre o resultado da checagem.

        Raises:
            ValidationError: Se a URL nao estiver na allowlist oficial.
            SourceUnavailableError: Se o TSE estiver temporariamente inacessivel.
        """
        check_time = now if now is not None else datetime.now(UTC)

        target_url = self.get_target_url()

        # 1. Verificacao da janela temporal de apuracao (Domingo apos 17h)
        if not is_election_night_window(check_time, ignore_gate=self._ignore_schedule_gate):
            msg = (
                "Aguardando início da apuração oficial "
                "(domingos a partir das 17:00 no horário de Brasília)."
            )
            self._history_log.append(
                TSEPollerLogEntry(
                    timestamp=check_time,
                    http_status=0,
                    totalized_electorate_pct=self._last_totalized_pct,
                    has_new_data=False,
                    message=msg,
                    url=target_url,
                )
            )
            return False, None, msg

        # 2. Resolucao da URL oficial do TSE
        try:
            raw_response = await self._client.fetch(
                election_id=self._election_id,
                artifact_type=ArtifactType.EA20,
                url=target_url,
                etag=self._last_etag,
                last_modified=self._last_modified,
            )
        except (SourceUnavailableError, ValidationError) as err:
            err_msg = f"Falha ao consultar API do TSE: {err}"
            self._history_log.append(
                TSEPollerLogEntry(
                    timestamp=check_time,
                    http_status=503,
                    totalized_electorate_pct=self._last_totalized_pct,
                    has_new_data=False,
                    message=err_msg,
                    url=target_url,
                )
            )
            raise

        # 3. Tratamento de HTTP 304 (Not Modified)
        if raw_response.http_status == 304:
            msg = "Sem alterações no TSE (HTTP 304 - Not Modified). Projeção mantida."
            self._history_log.append(
                TSEPollerLogEntry(
                    timestamp=check_time,
                    http_status=304,
                    totalized_electorate_pct=self._last_totalized_pct,
                    has_new_data=False,
                    message=msg,
                    url=target_url,
                )
            )
            return False, None, msg

        # 4. Tratamento de HTTP 404 (Arquivo ainda nao disponibilizado)
        if raw_response.http_status == 404:
            msg = "Arquivo de totalização ainda não disponibilizado pelo TSE (HTTP 404)."
            self._history_log.append(
                TSEPollerLogEntry(
                    timestamp=check_time,
                    http_status=404,
                    totalized_electorate_pct=self._last_totalized_pct,
                    has_new_data=False,
                    message=msg,
                    url=target_url,
                )
            )
            return False, None, msg

        # 5. Tratamento de HTTP 200 (Conteudo recebido com sucesso)
        totalization = normalize_ea20(raw_response.body, round_num=self._round_num)
        total_elec = totalization.total_electorate
        tot_elec = totalization.totalized_electorate
        current_pct = round((tot_elec / total_elec) * 100.0, 2) if total_elec > 0 else 0.0

        headers_dict = dict(raw_response.headers)
        new_etag = headers_dict.get("etag")
        new_last_modified = headers_dict.get("last-modified")

        current_votes = dict(totalization.candidate_group_votes)

        # Se ainda nao houve votos e apuracao esta em 0%, mantem status de prontidao sem recalcular
        if current_pct == 0.0 and sum(current_votes.values()) == 0:
            msg = (
                f"Conectado à API oficial do TSE ({totalization.total_sections} seções). "
                "Aguardando início da contagem dos votos oficiais."
            )
            self._history_log.append(
                TSEPollerLogEntry(
                    timestamp=check_time,
                    http_status=200,
                    totalized_electorate_pct=0.0,
                    has_new_data=False,
                    message=msg,
                    url=target_url,
                )
            )
            return False, totalization, msg

        has_new_progress = current_pct > self._last_totalized_pct
        has_new_votes = (
            current_votes != self._last_observed_votes and sum(current_votes.values()) > 0
        )
        has_new_data = (
            has_new_progress or has_new_votes or (self._last_etag is None and current_pct > 0.0)
        )

        if has_new_data:
            self._last_totalized_pct = current_pct
            self._last_observed_votes = current_votes
            if new_etag:
                self._last_etag = new_etag
            if new_last_modified:
                self._last_modified = new_last_modified

            msg = (
                f"Novos dados detectados no TSE! "
                f"Apuração avançou para {current_pct:.2f}% do eleitorado."
            )
            self._history_log.append(
                TSEPollerLogEntry(
                    timestamp=check_time,
                    http_status=200,
                    totalized_electorate_pct=current_pct,
                    has_new_data=True,
                    message=msg,
                    url=target_url,
                )
            )
            return True, totalization, msg

        msg = f"Dados oficiais inalterados no TSE ({current_pct:.2f}% apurado)."
        self._history_log.append(
            TSEPollerLogEntry(
                timestamp=check_time,
                http_status=200,
                totalized_electorate_pct=current_pct,
                has_new_data=False,
                message=msg,
                url=target_url,
            )
        )
        return False, totalization, msg

    async def run_poller_cycle(
        self,
        *,
        sections_catalog: list[dict[str, Any]] | None = None,
        num_draws: int = 500,
        seed: int = 42,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Executa um ciclo completo de checagem e recalculo preditivo caso haja dados novos.

        Args:
            sections_catalog: Catalogo opcional de secoes reais para calibracao bayesiana.
            num_draws: Quantidade de sorteios Monte Carlo na projecao.
            seed: Semente deterministica pseudo-aleatoria.
            now: Data/hora opcional de referencia para o ciclo.

        Returns:
            Dicionario contendo status do ciclo, flag has_new_data, mensagem e payload de projecao.

        Raises:
            SourceUnavailableError: Se o TSE estiver indisponivel.
        """
        has_new, totalization, msg = await self.check_for_updates(now=now)

        if not has_new or totalization is None:
            return {
                "has_new_data": False,
                "message": msg,
                "totalization": totalization,
                "projection": self._last_published_payload,
            }

        # Quando ha dados novos, executa a projecao do 2º turno majoritario
        progress_pct = max(0.0001, min(1.0, self._last_totalized_pct / 100.0))

        payload = simulate_2026_second_round_checkpoint(
            progress_pct=progress_pct,
            sections_catalog=sections_catalog,
            num_draws=num_draws,
            seed=seed,
            observed_at=now or datetime.now(UTC),
        )

        self._last_published_payload = payload

        return {
            "has_new_data": True,
            "message": msg,
            "totalization": totalization,
            "projection": payload,
        }
