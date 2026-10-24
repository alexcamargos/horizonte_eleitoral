"""Resolucao e descoberta formal de caminhos oficiais do TSE a partir de EA11 e EA12."""

from __future__ import annotations

from dataclasses import dataclass

from horizonte_eleitoral.domain.enums import ArtifactType
from horizonte_eleitoral.domain.errors import ValidationError


@dataclass(frozen=True, slots=True)
class TSEPathResolver:
    """Deriva caminhos canônicos oficiais sem inventar URLs arbitrarias.

    Attributes:
        base_url: Host base do TSE (e.g. 'https://dadosabertos.tse.jus.br' ou simulador).
        election_id: Codigo oficial da eleicao (e.g. '002026').
    """

    base_url: str
    election_id: str

    def __post_init__(self) -> None:
        """Valida que base_url e election_id sao validos.

        Raises:
            ValidationError: Se base_url nao for HTTPS ou election_id for vazio.
        """
        if not self.base_url.startswith("https://"):
            raise ValidationError("base_url deve iniciar com https://.")
        if not self.election_id or not self.election_id.strip():
            raise ValidationError("election_id nao pode ser vazio.")

    def url_for_config(self, artifact_type: ArtifactType) -> str:
        """Retorna a URL oficial para arquivos de configuracao geral (EA11 ou EA12).

        Args:
            artifact_type: Tipo do artefato desejado.

        Returns:
            URL completa resolvida.

        Raises:
            ValidationError: Se o tipo nao for de configuracao global.
        """
        if artifact_type not in (ArtifactType.EA11, ArtifactType.EA12):
            raise ValidationError(
                f"{artifact_type.value} nao e um artefato de configuracao global."
            )
        clean_base = self.base_url.rstrip("/")
        return f"{clean_base}/{self.election_id}/config/{artifact_type.value.lower()}.json"

    def url_for_summary(self, artifact_type: ArtifactType, state: str | None = None) -> str:
        """Retorna URL de resumo de atualizacoes (EA14 ou EA15).

        Args:
            artifact_type: EA14 (resumo de UFs) ou EA15 (resumo de municipios).
            state: UF de duas letras, obrigatoria para EA15.

        Returns:
            URL completa resolvida.

        Raises:
            ValidationError: Se EA15 nao receber UF valida.
        """
        clean_base = self.base_url.rstrip("/")
        if artifact_type is ArtifactType.EA14:
            return f"{clean_base}/{self.election_id}/summary/ea14-br.json"
        if artifact_type is ArtifactType.EA15:
            if not state or len(state) != 2:
                raise ValidationError("state de 2 letras e obrigatorio para EA15.")
            return f"{clean_base}/{self.election_id}/summary/ea15-{state.lower()}.json"
        raise ValidationError(f"{artifact_type.value} nao e um resumo de atualizacoes.")

    def url_for_sections(
        self,
        artifact_type: ArtifactType,
        state: str,
        municipality_code: str,
        zone: str | None = None,
        section: str | None = None,
    ) -> str:
        """Retorna URL para inventario e estado de secoes (EA16 ou EA18).

        Args:
            artifact_type: EA16 (lista de secoes) ou EA18 (detalhe da secao).
            state: UF de 2 letras.
            municipality_code: Codigo do municipio.
            zone: Numero da zona (obrigatorio para EA18).
            section: Numero da secao (obrigatorio para EA18).

        Returns:
            URL completa resolvida.

        Raises:
            ValidationError: Se parametros obrigatorios estiverem ausentes.
        """
        clean_base = self.base_url.rstrip("/")
        st = state.lower()
        if artifact_type is ArtifactType.EA16:
            return f"{clean_base}/{self.election_id}/sections/{st}/{municipality_code}/ea16.json"
        if artifact_type is ArtifactType.EA18:
            if not zone or not section:
                raise ValidationError("zone e section sao obrigatorios para EA18.")
            return (
                f"{clean_base}/{self.election_id}/sections/{st}/{municipality_code}/"
                f"{zone}/{section}/ea18.json"
            )
        raise ValidationError(f"{artifact_type.value} nao e um artefato de secoes.")

    def url_for_totalization(self, state: str | None = None) -> str:
        """Retorna URL de totalizacao oficial EA20 no menor escopo necessario.

        Args:
            state: UF especifica ou None para consolidado nacional (BR).

        Returns:
            URL completa para EA20.

        Raises:
            None.
        """
        clean_base = self.base_url.rstrip("/")
        scope_suffix = state.lower() if state else "br"
        return f"{clean_base}/{self.election_id}/totalization/ea20-{scope_suffix}.json"

    def url_for_divulgacao(
        self,
        *,
        cargo_code: str = "c0001",
        state: str | None = None,
        round_num: int = 2,
    ) -> str:
        """Retorna URL oficial de divulgacao de resultados da CDN do TSE (br-c0001-e*-u.json).

        Args:
            cargo_code: Codigo do cargo (padrao: 'c0001' para Presidente).
            state: UF de 2 letras ou None para consolidado nacional ('br').
            round_num: Turno da eleicao (1 ou 2).

        Returns:
            URL canonica de divulgacao de totalizacao.

        Raises:
            None.
        """
        clean_base = self.base_url.rstrip("/")
        st = state.lower() if state else "br"
        election_code = (
            self.election_id.lstrip("0")
            if self.election_id.isdigit() and self.election_id != "0"
            else self.election_id
        )
        padded_code = self.election_id.zfill(6) if self.election_id.isdigit() else self.election_id
        return (
            f"{clean_base}/oficial/ele2026/{election_code}/dados/"
            f"{st}/{st}-{cargo_code}-e{padded_code}-u.json"
        )

    def url_for_divulgacao_simplificada(
        self,
        *,
        cargo_code: str = "c0001",
        state: str | None = None,
        round_num: int = 2,
    ) -> str:
        """Retorna URL oficial de dados simplificados da CDN do TSE (br-c0001-e*-r.json).

        Args:
            cargo_code: Codigo do cargo (padrao: 'c0001' para Presidente).
            state: UF de 2 letras ou None para consolidado nacional ('br').
            round_num: Turno da eleicao (1 ou 2).

        Returns:
            URL canonica de dados simplificados de totalizacao.

        Raises:
            None.
        """
        clean_base = self.base_url.rstrip("/")
        st = state.lower() if state else "br"
        election_code = (
            self.election_id.lstrip("0")
            if self.election_id.isdigit() and self.election_id != "0"
            else self.election_id
        )
        padded_code = self.election_id.zfill(6) if self.election_id.isdigit() else self.election_id
        return (
            f"{clean_base}/oficial/ele2026/{election_code}/dados-simplificados/"
            f"{st}/{st}-{cargo_code}-e{padded_code}-r.json"
        )
