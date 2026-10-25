"""Testes unitarios para o Modelo Hierarquico Versao 2 (v2) com encolhimento adaptativo."""

from __future__ import annotations

import pytest

from horizonte_eleitoral.historical.elasticity import (
    MunicipalElasticityIndex,
    MunicipalElasticityProfile,
)
from horizonte_eleitoral.models.base import PendingSection, SectionObservation
from horizonte_eleitoral.models.hierarchical import HierarchicalBayesianModelV1
from horizonte_eleitoral.models.hierarchical_v2 import HierarchicalBayesianModelV2


def _make_sample_observations() -> list[SectionObservation]:
    """Cria secoes observadas de amostra para testes."""
    return [
        SectionObservation(
            section_id="SP:71072:0001:0001",
            state="SP",
            municipality_code="71072",
            valid_votes=300,
            group_votes=(("OUTROS", 30), ("PL", 150), ("PT", 120)),
            historical_shares=(("OUTROS", 0.10), ("PL", 0.50), ("PT", 0.40)),
        ),
        SectionObservation(
            section_id="BA:38490:0001:0002",
            state="BA",
            municipality_code="38490",
            valid_votes=400,
            group_votes=(("OUTROS", 20), ("PL", 80), ("PT", 300)),
            historical_shares=(("OUTROS", 0.05), ("PL", 0.25), ("PT", 0.70)),
        ),
    ]


def _make_sample_pending() -> list[PendingSection]:
    """Cria secoes pendentes de amostra para testes."""
    return [
        PendingSection(
            section_id="SP:71072:0001:0003",
            state="SP",
            municipality_code="71072",
            electorate=400,
            historical_shares=(("OUTROS", 0.10), ("PL", 0.50), ("PT", 0.40)),
        ),
        PendingSection(
            section_id="BA:38490:0001:0004",
            state="BA",
            municipality_code="38490",
            electorate=500,
            historical_shares=(("OUTROS", 0.05), ("PL", 0.25), ("PT", 0.70)),
        ),
    ]


def test_hierarchical_v2_empty_observations() -> None:
    """Verifica comportamento com zero observacoes, gerando projecao baseada no prior."""
    model = HierarchicalBayesianModelV2()
    pending = _make_sample_pending()
    result = model.predict(observations=[], pending=pending)

    assert result.model_name == "hierarchical_bayesian_composite_v2"
    assert len(result.projected_shares) == 3
    total_share = sum(s for _, s in result.projected_shares)
    assert total_share == pytest.approx(1.0, abs=1e-4)


def test_hierarchical_v2_with_observations_and_elasticity() -> None:
    """Verifica que v2 projeta valores consistentes e respeita a soma de 1.0."""
    prof_sp = MunicipalElasticityProfile(
        municipality_key="SP:71072",
        state="SP",
        municipality_code="71072",
        valid_votes_2018=10000,
        valid_votes_2022=12000,
        pt_share_2018=0.25,
        pt_share_2022=0.40,
        pl_share_2018=0.65,
        pl_share_2022=0.50,
        pt_swing=0.15,
        pl_swing=-0.15,
        volatility=0.15,
    )
    idx = MunicipalElasticityIndex(profiles={"SP:71072": prof_sp})
    model_v2 = HierarchicalBayesianModelV2(elasticity_index=idx)

    obs = _make_sample_observations()
    pending = _make_sample_pending()
    result = model_v2.predict(observations=obs, pending=pending)

    assert result.model_name == "hierarchical_bayesian_composite_v2"
    total_share = sum(s for _, s in result.projected_shares)
    assert total_share == pytest.approx(1.0, abs=1e-4)
    assert result.total_projected_valid > 0


def test_hierarchical_v1_v2_compatibility() -> None:
    """Compara V1 e V2 com os mesmos dados e valida contratos compativeis."""
    obs = _make_sample_observations()
    pending = _make_sample_pending()

    model_v1 = HierarchicalBayesianModelV1()
    model_v2 = HierarchicalBayesianModelV2()

    res_v1 = model_v1.predict(observations=obs, pending=pending)
    res_v2 = model_v2.predict(observations=obs, pending=pending)

    assert res_v1.model_name == "hierarchical_bayesian_composite"
    assert res_v2.model_name == "hierarchical_bayesian_composite_v2"

    # Sem indice de elasticidade fornecido, v2 usa default proximo de v1
    v1_dict = dict(res_v1.projected_shares)
    v2_dict = dict(res_v2.projected_shares)

    for g in ("PT", "PL", "OUTROS"):
        assert abs(v1_dict[g] - v2_dict[g]) < 0.05


def test_hierarchical_v2_zero_lockout_and_large_delta() -> None:
    """Valida que shares historicos nulos recebem piso e grandes deltas nao causam overflow."""
    obs = [
        SectionObservation(
            section_id="SP:1:1",
            state="SP",
            municipality_code="71072",
            valid_votes=1000,
            group_votes=(("OUTROS", 10), ("PL", 10), ("PT", 980)),
            historical_shares=(("OUTROS", 0.05), ("PL", 0.90), ("PT", 0.05)),
        )
    ]
    # Secao pendente onde PT tinha exatamente 0.0% no historico
    pending = [
        PendingSection(
            section_id="SP:1:2",
            state="SP",
            municipality_code="71072",
            electorate=1000,
            historical_shares=(("OUTROS", 0.10), ("PL", 0.90), ("PT", 0.0)),
        )
    ]
    model = HierarchicalBayesianModelV2()
    result = model.predict(observations=obs, pending=pending)

    shares = dict(result.projected_shares)
    assert abs(sum(shares.values()) - 1.0) < 1e-4
    # Com piso regularizador de 1e-5 e swing fortemente favoravel ao PT,
    # o PT deve receber uma projecao estritamente positiva em vez de 0.0 perpetuo
    assert shares["PT"] > 0.0


def test_hierarchical_v2_sparse_reporting_stability() -> None:
    """Verifica que uma unica secao no Sul nao impoe seu swing descontrolado ao Nordeste."""
    obs = [
        SectionObservation(
            section_id="RS:1:1",
            state="RS",
            municipality_code="0001",
            valid_votes=1000,
            group_votes=(("OUTROS", 10), ("PL", 790), ("PT", 200)),
            historical_shares=(("OUTROS", 0.10), ("PL", 0.45), ("PT", 0.45)),
        )
    ]
    # Secao pendente na Bahia (Nordeste) com eleitorado representativo e historico pro-PT
    pending = [
        PendingSection(
            section_id="BA:1:1",
            state="BA",
            municipality_code="0002",
            electorate=10000,
            historical_shares=(("OUTROS", 0.05), ("PL", 0.25), ("PT", 0.70)),
        )
    ]
    model = HierarchicalBayesianModelV2()
    result = model.predict(observations=obs, pending=pending)

    shares = dict(result.projected_shares)
    # Com a ancoragem de credibilidade, a secao da Bahia deve preservar maioria do PT
    assert shares["PT"] > shares["PL"]


def test_hierarchical_v2_lazy_elasticity_loading() -> None:
    """Verifica que o indice de elasticidade so e carregado se shrinkage_muni for ativo."""
    # Sem shrinkage municipal, elasticity_index deve permanecer None para evitar I/O desnecessario
    model_no_muni = HierarchicalBayesianModelV2(shrinkage_muni=None, auto_load_default=True)
    assert model_no_muni._elasticity_index is None

    # Com shrinkage municipal ativo e auto_load_default=False, permanece None
    model_manual = HierarchicalBayesianModelV2(shrinkage_muni=10.0, auto_load_default=False)
    assert model_manual._elasticity_index is None


def test_hierarchical_v2_municipal_shrinkage_and_elasticity() -> None:
    """Verifica a estimacao de efeitos municipais com e sem indice de elasticidade."""
    obs = _make_sample_observations()
    pending = _make_sample_pending()
    groups = ("OUTROS", "PL", "PT")

    # 1. Sem indice de elasticidade (volatilidade padrao 0.05)
    model_default_vol = HierarchicalBayesianModelV2(
        shrinkage_muni=10.0,
        auto_load_default=False,
    )
    d_nat, d_reg, d_uf, d_muni = model_default_vol.estimate_effects(obs, groups)
    assert len(d_muni) == 2
    assert "SP:71072" in d_muni
    assert "BA:38490" in d_muni

    res_default = model_default_vol.predict(observations=obs, pending=pending, groups=groups)
    assert res_default.total_projected_valid > 0

    # 2. Com indice de elasticidade customizado (alta volatilidade -> maior encolhimento para UF)
    prof_volatile = MunicipalElasticityProfile(
        municipality_key="SP:71072",
        state="SP",
        municipality_code="71072",
        valid_votes_2018=10000,
        valid_votes_2022=12000,
        pt_share_2018=0.25,
        pt_share_2022=0.40,
        pl_share_2018=0.65,
        pl_share_2022=0.50,
        pt_swing=0.15,
        pl_swing=-0.15,
        volatility=0.80,
    )
    prof_stable = MunicipalElasticityProfile(
        municipality_key="SP:71072",
        state="SP",
        municipality_code="71072",
        valid_votes_2018=10000,
        valid_votes_2022=12000,
        pt_share_2018=0.25,
        pt_share_2022=0.40,
        pl_share_2018=0.65,
        pl_share_2022=0.50,
        pt_swing=0.15,
        pl_swing=-0.15,
        volatility=0.01,
    )

    idx_vol = MunicipalElasticityIndex(profiles={"SP:71072": prof_volatile})
    model_vol = HierarchicalBayesianModelV2(
        elasticity_index=idx_vol,
        shrinkage_muni=10.0,
        elasticity_sensitivity=5.0,
    )
    _, _, _, d_muni_vol = model_vol.estimate_effects(obs, groups)

    idx_stable = MunicipalElasticityIndex(profiles={"SP:71072": prof_stable})
    model_stable = HierarchicalBayesianModelV2(
        elasticity_index=idx_stable,
        shrinkage_muni=10.0,
        elasticity_sensitivity=5.0,
    )
    _, _, d_uf_stable, d_muni_stable = model_stable.estimate_effects(obs, groups)

    # Municipio estavel preserva mais do swing local (distancia do efeito estadual e maior)
    # Municipio volatil encolhe mais em direcao ao estado (distancia do efeito estadual e menor)
    uf_sp = d_uf_stable["SP"]["PT"]
    diff_stable = abs(d_muni_stable["SP:71072"]["PT"] - uf_sp)
    diff_vol = abs(d_muni_vol["SP:71072"]["PT"] - uf_sp)
    assert diff_vol < diff_stable
