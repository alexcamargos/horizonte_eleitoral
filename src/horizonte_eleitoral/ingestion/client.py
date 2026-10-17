"""Cliente HTTP assincrono com rate limit, cache e protecao de fonte oficial do TSE."""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from horizonte_eleitoral.config import Settings
from horizonte_eleitoral.domain.enums import ArtifactType
from horizonte_eleitoral.domain.errors import SourceUnavailableError, ValidationError
from horizonte_eleitoral.domain.models import RawArtifactRequest
from horizonte_eleitoral.ingestion.rate_limiter import AsyncRateLimiter


class TSEAsyncClient:
    """Cliente HTTP com allowlist, rate limiting, retentativas e suporte a ETag."""

    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
        base_backoff_seconds: float = 0.5,
    ) -> None:
        """Inicializa o cliente com configuracoes de limites e hosts permitidos.

        Args:
            settings: Objeto Settings contendo allowlist de hosts e taxas maximas.
            http_client: Instancia opcional de httpx.AsyncClient (para injecao/testes).
            max_retries: Numero maximo de tentativas para erros transientes 5xx/429.
            base_backoff_seconds: Tempo base para calculo de backoff exponencial com jitter.

        Returns:
            None.

        Raises:
            None.
        """
        self._settings = settings
        self._allowed_hosts = set(settings.allowed_tse_hosts)
        self._rate_limiter = AsyncRateLimiter(
            max_rate=settings.max_requests_per_second,
            max_concurrency=settings.max_concurrency,
        )
        self._http_client = http_client or httpx.AsyncClient(timeout=10.0)
        self._max_retries = max_retries
        self._base_backoff = base_backoff_seconds

    def validate_url(self, url: str) -> None:
        """Verifica se a URL pertence aos dominios permitidos do TSE.

        Args:
            url: URL completa para validacao.

        Returns:
            None.

        Raises:
            ValidationError: Se a URL nao for HTTPS ou nao pertencer a allowlist.
        """
        parsed = urlsplit(url)
        if parsed.scheme != "https":
            raise ValidationError("Apenas URLs HTTPS sao aceitas para o TSE.")
        host = (parsed.hostname or "").lower()
        if host not in self._allowed_hosts:
            raise ValidationError(
                f"O host '{host}' nao consta na allowlist de hosts TSE permitidos: "
                f"{self._allowed_hosts}."
            )

    async def fetch(
        self,
        *,
        election_id: str,
        artifact_type: ArtifactType,
        url: str,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> RawArtifactRequest:
        """Executa a requisicao HTTP respeitando limites, cache e retentativas.

        Args:
            election_id: Identificador da eleicao.
            artifact_type: Tipo oficial do artefato (EA11 a EA20).
            url: URL completa do arquivo no TSE.
            etag: Valor ETag previo para cabecalho If-None-Match.
            last_modified: Data previa para cabecalho If-Modified-Since.

        Returns:
            RawArtifactRequest com corpo, status e cabecalhos de resposta.

        Raises:
            ValidationError: Se a URL violar a politica de seguranca.
            SourceUnavailableError: Se a fonte estiver indisponivel apos retentativas.
        """
        self.validate_url(url)

        headers: dict[str, str] = {}
        if etag is not None:
            headers["If-None-Match"] = etag
        if last_modified is not None:
            headers["If-Modified-Since"] = last_modified

        last_exception: Exception | None = None

        for attempt in range(self._max_retries + 1):
            await self._rate_limiter.acquire()
            collected_at = datetime.now(UTC)
            try:
                response = await self._http_client.get(url, headers=headers)

                # HTTP 200 (Novo conteudo) ou 304 (Nao modificado)
                if response.status_code in (200, 304):
                    response_headers = tuple((k.lower(), v) for k, v in response.headers.items())
                    return RawArtifactRequest(
                        election_id=election_id,
                        artifact_type=artifact_type,
                        source_url=url,
                        collected_at=collected_at,
                        http_status=response.status_code,
                        body=response.content,
                        headers=response_headers,
                    )

                # HTTP 404 (Arquivo ainda nao gerado)
                if response.status_code == 404:
                    response_headers = tuple((k.lower(), v) for k, v in response.headers.items())
                    return RawArtifactRequest(
                        election_id=election_id,
                        artifact_type=artifact_type,
                        source_url=url,
                        collected_at=collected_at,
                        http_status=404,
                        body=b"",
                        headers=response_headers,
                    )

                # Erros recuperaveis: 429 ou 5xx
                if response.status_code in (429, 500, 502, 503, 504):
                    if attempt < self._max_retries:
                        jitter = random.uniform(0.1, 0.5)
                        backoff = (self._base_backoff * (2**attempt)) + jitter
                        await asyncio.sleep(backoff)
                        continue
                    raise SourceUnavailableError(
                        f"Fonte TSE retornou HTTP {response.status_code} "
                        f"apos {attempt + 1} tentativas em {url}."
                    )

                raise SourceUnavailableError(
                    f"Resposta HTTP inesperada {response.status_code} da fonte TSE em {url}."
                )

            except httpx.RequestError as error:
                last_exception = error
                if attempt < self._max_retries:
                    jitter = random.uniform(0.1, 0.5)
                    backoff = (self._base_backoff * (2**attempt)) + jitter
                    await asyncio.sleep(backoff)
                    continue
                raise SourceUnavailableError(
                    f"Falha de comunicacao com a fonte TSE em {url} apos {attempt + 1} tentativas."
                ) from last_exception
            finally:
                self._rate_limiter.release()

        raise SourceUnavailableError(f"Esgotadas tentativas para acessar {url}.")
