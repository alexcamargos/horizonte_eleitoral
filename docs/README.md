# Portal de Documentação Técnica · Horizonte Eleitoral

Bem-vindo à documentação técnica oficial do **Horizonte Eleitoral**, a infraestrutura estatística e computacional de alta fidelidade para projeção preditiva da eleição presidencial brasileira de 2026.

Esta documentação é mantida sob a disciplina de **Living Docs Governance**, garantindo rastreabilidade, prevenção contra desatualização e atribuição clara de responsabilidades entre os documentos do projeto.

---

## Estrutura da Documentação

A documentação está organizada em quatro papéis canônicos não-sobrepostos, complementada por detalhamentos metodológicos e de governança:

```text
horizonte_eleitoral/
├── AGENTS.md                          # [Constituição] Regras centrais, invariantes e diretrizes de agentes
├── README.md                          # [Visão Geral] Guia do repositório, instalação rápida e comandos
└── docs/
    ├── README.md                      # [Este Portal] Índice canônico de navegação
    ├── ARQUITETURA.md                 # [Mapa] Arquitetura, componentes, fronteiras e jump table
    ├── METODOLOGIA_ESTATISTICA.md     # [Metodologia] Formulação matemática, 4 baselines e HORIZON-MRP
    ├── DECISOES_DE_ENGENHARIA.md      # [Histórico / ADRs] Registros de Decisão de Arquitetura e lógica
    └── STATUS_E_GOVERNANCA.md         # [Status & Delete-Zone] Saúde dos testes, delete-zone e roadmap
```

---

## Guia de Leitura por Perfil

### Para Desenvolvedores de Software e Engenheiros de Dados
1. Comece pelo [README.md principal](../README.md) para configurar o ambiente com `uv` e rodar a suíte de testes.
2. Leia o [Mapa de Arquitetura](ARQUITETURA.md) para compreender as fronteiras entre os pacotes (`domain`, `ingestion`, `normalization`, `reconciliation`, `storage`, `publishing`, `api`, `dashboard`).
3. Consulte as [Decisões de Engenharia (ADRs)](DECISOES_DE_ENGENHARIA.md) para entender por que o cofre é imutável, como a publicação atômica opera e como o Apache Parquet e o DuckDB foram introduzidos.
4. Consulte [Status e Governança](STATUS_E_GOVERNANCA.md) antes de submeter código para verificar padrões de qualidade e convenções de teste.

### Para Estatísticos, Cientistas de Dados e Pesquisadores
1. Leia a [Metodologia Estatística](METODOLOGIA_ESTATISTICA.md), que detalha o fenômeno do viés geográfico da apuração no Brasil, os 4 baselines de referência, a formulação matemática do modelo hierárquico bayesiano (MRP), o índice de elasticidade municipal multi-ciclo (2018–2022) e a simulação de Monte Carlo.
2. Explore a seção de resultados empíricos em [Metodologia Estatística](METODOLOGIA_ESTATISTICA.md#6-resultados-empíricos-na-eleição-de-2026-499206-seções), com o comparativo de precisão entre o modelo legado V1 e o HORIZON-MRP em 100% da base real de 2026.
3. Consulte o [ADR 005 em Decisões de Engenharia](DECISOES_DE_ENGENHARIA.md#adr-005-substituição-do-modelo-hierárquico-v1-pelo-modelo-v2-com-elasticidade-municipal).

### Para Jornalistas de Dados e Operadores Eleitorais
1. Leia o [README.md principal](../README.md) para entender por que a apuração preliminar do TSE distorce a realidade política nos momentos iniciais (efeito "virada de apuração").
2. Execute o painel interativo Streamlit (`uv run horizonte-eleitoral --dashboard`) para navegar na linha do tempo interativa e visualizar as faixas preditivas de 90%.
3. Consulte a seção de [Interpretação Responsável em Metodologia Estatística](METODOLOGIA_ESTATISTICA.md#7-diretrizes-de-comunicação-e-ética-editorial).

---

## Tabela de Atalhos Rápidos (Jump Table)

| Necessidade | Onde Ir | Verificação Recomendada |
|---|---|---|
| Instalar e rodar o projeto localmente | [README.md](../README.md#início-rápido) | `uv sync; uv run pytest` |
| Compreender os contratos de domínio imutáveis | [`src/horizonte_eleitoral/domain/`](../src/horizonte_eleitoral/domain/) | [`tests/unit/test_domain.py`](../tests/unit/test_domain.py) |
| Entender a formulação matemática do HORIZON-MRP | [Metodologia Estatística](METODOLOGIA_ESTATISTICA.md#3-horizon-mrp-modelo-hierárquico-bayesiano-v2-mrp-calibrado-com-encolhimento) | [`tests/unit/test_hierarchical_v2.py`](../tests/unit/test_hierarchical_v2.py) |
| Entender o cálculo de elasticidade 2018–2022 | [`src/horizonte_eleitoral/historical/elasticity.py`](../src/horizonte_eleitoral/historical/elasticity.py) | [`tests/unit/test_elasticity.py`](../tests/unit/test_elasticity.py) |
| Ver como é garantida a consistência de apuração | [`src/horizonte_eleitoral/reconciliation/`](../src/horizonte_eleitoral/reconciliation/) | [`tests/unit/test_reconciliation.py`](../tests/unit/test_reconciliation.py) |
| Subir a aplicação Streamlit interativa | [README.md](../README.md#executando-o-dashboard-streamlit) | `uv run horizonte-eleitoral --dashboard` |
| Saber por que um módulo antigo foi removido | [Status e Governança](STATUS_E_GOVERNANCA.md#zona-de-exclusão-delete-zone) | [ADR 005](DECISOES_DE_ENGENHARIA.md#adr-005) |
