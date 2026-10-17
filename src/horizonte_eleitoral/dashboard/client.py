"""Cliente HTTP desacoplado para consumo da API de projecoes pelo dashboard."""

from __future__ import annotations

from typing import Any, cast

import httpx

from horizonte_eleitoral.domain.errors import SourceUnavailableError


class DashboardApiClient:
    """Consome exclusivamente os endpoints publicos da API de leitura com timeout."""

    def __init__(self, base_url: str = "http://127.0.0.1:8000", timeout: float = 5.0) -> None:
        """Inicializa o cliente com endereco base e timeout rigoroso.

        Args:
            base_url: Endereco base da API FastAPI.
            timeout: Limite maximo de espera em segundos por requisicao.
        """
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def get_latest_projection(self, geography: str = "BR") -> dict[str, Any] | None:
        """Busca a projecao mais recente para a geografia solicitada.

        Args:
            geography: Escopo territorial (e.g. 'BR', 'UF:SP').

        Returns:
            Dicionario com o payload JSON da projecao ou None se nao houver dados.

        Raises:
            SourceUnavailableError: Se a API estiver inacessivel.
        """
        url = f"{self._base_url}/v1/projections/latest"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.get(url, params={"geography": geography})
                if response.status_code == 200:
                    return cast(dict[str, Any], response.json())
                if response.status_code == 404:
                    return None
                raise SourceUnavailableError(
                    f"API retornou status HTTP {response.status_code} em {url}."
                )
        except httpx.RequestError as error:
            raise SourceUnavailableError(f"Nao foi possivel conectar a API em {url}.") from error

    def get_projection_history(self, geography: str = "BR") -> list[dict[str, Any]]:
        """Busca a sequencia historica de projecoes para a geografia solicitada.

        Args:
            geography: Escopo territorial (e.g. 'BR', 'UF:SP').

        Returns:
            Lista de dicionarios com os payloads JSON das projecoes historicas.

        Raises:
            SourceUnavailableError: Se a API estiver inacessivel.
        """
        url = f"{self._base_url}/v1/projections/history"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.get(url, params={"geography": geography})
                if response.status_code == 200:
                    return cast(list[dict[str, Any]], response.json())
                raise SourceUnavailableError(
                    f"API retornou status HTTP {response.status_code} em {url}."
                )
        except httpx.RequestError as error:
            raise SourceUnavailableError(f"Nao foi possivel conectar a API em {url}.") from error

    def get_data_health(self) -> dict[str, Any]:
        """Consulta o diagnostico de integridade e defasagem dos dados.

        Returns:
            Dicionario com status de saude, idade dos dados e contagens.

        Raises:
            SourceUnavailableError: Se a API estiver inacessivel.
        """
        url = f"{self._base_url}/v1/health/data"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.get(url)
                if response.status_code == 200:
                    return cast(dict[str, Any], response.json())
                raise SourceUnavailableError(
                    f"API retornou status HTTP {response.status_code} em {url}."
                )
        except httpx.RequestError as error:
            raise SourceUnavailableError(f"Nao foi possivel conectar a API em {url}.") from error

    def get_model_card(self) -> dict[str, Any]:
        """Consulta a ficha metodologica do modelo (Model Card).

        Returns:
            Dicionario com versao, metodologia e limitacoes.

        Raises:
            SourceUnavailableError: Se a API estiver inacessivel.
        """
        url = f"{self._base_url}/v1/model-card"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.get(url)
                if response.status_code == 200:
                    return cast(dict[str, Any], response.json())
                raise SourceUnavailableError(
                    f"API retornou status HTTP {response.status_code} em {url}."
                )
        except httpx.RequestError as error:
            raise SourceUnavailableError(f"Nao foi possivel conectar a API em {url}.") from error
