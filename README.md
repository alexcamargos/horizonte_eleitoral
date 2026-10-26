# Horizonte Eleitoral · Sistema de Projeção Preditiva 2026

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Package Manager: uv](https://img.shields.io/badge/package_manager-uv-purple.svg)](https://docs.astral.sh/uv/)
[![Tests: 183 Passed](https://img.shields.io/badge/tests-183%20passed-brightgreen.svg)](tests/)
[![Type Checker: mypy strict](https://img.shields.io/badge/types-mypy%20strict-blue.svg)](pyproject.toml)
[![Code Style: ruff](https://img.shields.io/badge/code%20style-ruff-black.svg)](https://github.com/astral-sh/ruff)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

O **Horizonte Eleitoral** é uma plataforma analítica de alta precisão desenhada para projetar o resultado final das eleições presidenciais brasileiras durante a apuração oficial do Tribunal Superior Eleitoral (TSE).

Combinando **Regressão Multinível com Pós-Estratificação (MRP)**, **encolhimento bayesiano adaptativo modulado por elasticidade municipal multi-ciclo** e **simulações estocásticas de Monte Carlo**, o sistema antecipa os números finais da eleição com erro médio inferior a **0,5 ponto percentual** logo nos primeiros minutos da apuração, mitigando o viés do ritmo geográfico de transmissão de urnas.

---

## Por que o Horizonte Eleitoral é Necessário?

Na noite da eleição, o totalizador bruto do TSE não reflete a realidade do resultado final nas primeiras horas:
- Estados do Sul, Centro-Oeste e o interior paulista transmitem suas urnas com velocidade muito superior à média nacional.
- O Nordeste e as periferias de grandes regiões metropolitanas apuram mais tarde.
- Essa assimetria logística cria **vantagens artificiais de 10 a 20 pontos percentuais** nos primeiros 20% da apuração oficial, gerando falsas impressões de "viradas dramáticas", ansiedade coletiva e espaço para desinformação.

O **Horizonte Eleitoral** resolve este desafio: em vez de assumir que o país votou como as primeiras urnas que chegaram, o motor preditivo estima cada uma das seções eleitorais ainda pendentes com base na sua ancoragem histórica de 2022, ajustada dinamicamente pelo sinal revelado no município, estado e região na eleição atual.

---

## Principais Capacidades

- **Modelo Hierárquico Bayesiano V2 (MRP Adaptativo):** Modelação em 4 níveis (Nacional ponderado pelo censo $\rightarrow$ 5 Macro-regiões $\rightarrow$ 27 UFs $\rightarrow$ 5.570+ Municípios).
- **Índice de Elasticidade Municipal (2018–2022):** Modula o fator de encolhimento bayesiano (*shrinkage*). Municípios com alta volatilidade histórica aprendem mais rápido da eleição atual; municípios estáveis mantêm sólida proteção contra ruído estatístico.
- **Acurácia Validada em 499.206 Seções Reais (1º e 2º Turnos de 2026):**
  - **1º Turno:** Com apenas **2,0% do eleitorado apurado**, o modelo projetou **PT 45,25% e PL 46,99%** frente ao resultado oficial final de **45,16% vs 47,03%** (**MAE = 0,06 pp**).
  - **2º Turno (100% das seções oficiais TSE · 5.716 municípios):** Reproduz fielmente a suspensão em **0,25%** entre `17h07` e `19h00` BRT (prorrogação do STF) e a retomada após as `19h00` BRT. Às **19h30 (5,0% apurado)** já cravou **PT 51,70% vs PL 48,30%** (`MAE = 0,09 pp`), e durante toda a janela das **19h46 às 20h24** — quando Flávio Bolsonaro liderava a urna bruta (`PL 51,02% vs PT 48,98%` em `25%`) — o Modelo V2 sustentou a vitória de Lula (**51,68% vs 48,32%**, `MAE = 0,11 pp`) rumo ao resultado final homologado (**51,79% vs 48,21%**).
- **Simulação de Monte Carlo com Intervalos de Credibilidade de 90%:** 2.000 sorteios estocásticos vetorizados propagando incertezas macro e micro, gerando faixas preditivas confiáveis $[q_{05}, q_{95}]$ e probabilidades calibradas de vitória / 2º turno.
- **Catálogo Colunar Parquet & DuckDB:** Carga de meio milhão de seções em menos de 0,8 segundo e suporte a consultas SQL analíticas em memória instantâneas.
- **Painel Visual Interativo Streamlit:** Três abas especializadas:
  - **Aba 1 (Histórico & Validação · 2º Turno 2026):** Replay retroativo de 1% a 100% contra os dados reais divulgados pelo TSE (`5.716` municípios), painel executivo de qualidade preditiva, curva de decaimento do erro absoluto (`Modelo V2` vs `Urna Bruta`), auditoria marco a marco e diagnóstico por UF.
  - **Aba 2 (Replay & Validação · 1º Turno 2026):** Linha do tempo navegável (1% a 100%), gráficos Altair com faixas de incerteza, cards de candidatos, tabelas estaduais e model card metodológico.
  - **Aba 3 (Tempo Real · 2º Turno Oficial):** Conexão assíncrona oficial à API do TSE com suporte a polling inteligente (ETag 304), disparos manuais e simulação de novas ondas.
- **Integridade e Governança Imutável:** Cofre de dados brutos com verificação SHA-256, reconciliação estrita (*Failure-Stop* contra dados dessincronizados) e gravação atômica (`tempfile` + `os.replace`).

---

## Início Rápido

### Pré-requisitos
- **Python 3.12 ou superior**
- Gerenciador de pacotes **Astral `uv`** ([como instalar o uv](https://docs.astral.sh/uv/))

### 1. Clonando o Repositório e Instalando Dependências
```powershell
# Clone o repositorio
git clone https://github.com/seu-usuario/horizonte-eleitoral.git
cd horizonte-eleitoral

# Sincronize o ambiente virtual e dependencias com o uv
uv sync
```

### 2. Executando o Painel Interativo (Streamlit)
```powershell
uv run horizonte-eleitoral --dashboard
```
O navegador abrirá automaticamente em `http://localhost:8501`, disponibilizando a visualização do 1º Turno (Replay histórico dos 499k BUs) e do 2º Turno (Tempo real na API do TSE).

---

## Interface de Linha de Comando (CLI)

O executável de linha de comando `horizonte-eleitoral` disponibiliza diversas rotinas analíticas e operacionais:

### Simulação de Marcos do 1º Turno (Dados Reais de 2026)
```powershell
# Simular o comportamento nos primeiros 10% do eleitorado apurado
uv run horizonte-eleitoral --simulate-2026-10pct

# Simular marcos a 50% da apuracao com 500 sorteios Monte Carlo
uv run horizonte-eleitoral --wave 0.50 --draws 500

# Executar sequencialmente todos os marcos de 10% a 100%
uv run horizonte-eleitoral --simulate-2026-all-10pct
```

### Simulação e Consolidação Histórica do 2º Turno Majoritário
```powershell
# Consolidar os 5.716 municipios oficiais da CDN do TSE em catalog_2026_2t.parquet e pre-calcular checkpoints_2026_2t.json
uv run horizonte-eleitoral --build-2026-2t-history

# Simular com 50% das urnas do 2º turno apuradas
uv run horizonte-eleitoral --simulate-2026-2t-pct 50.0
```

### Consultas Analíticas Diretas em SQL via DuckDB
O catálogo analítico de 499.206 seções (`data/real/catalog_2026.parquet`) pode ser consultado via SQL diretamente pelo terminal:
```powershell
# Contagem de secoes e eleitorado total por estado
uv run horizonte-eleitoral --query-sql "SELECT state, count(*) AS secoes, sum(electorate) AS eleitores FROM 'data/real/catalog_2026.parquet' GROUP BY state ORDER BY eleitores DESC LIMIT 5"

# Top 5 municipios com maior deslocamento de votos
uv run horizonte-eleitoral --query-sql "SELECT municipality_key, pt_swing, pl_swing, volatility FROM 'data/real/elasticity_2018_2022.parquet' ORDER BY volatility DESC LIMIT 5"
```

### Comparativo Head-to-Head entre Modelo V1 e Modelo V2
```powershell
uv run horizonte-eleitoral --compare-v1-v2
```

### Consulta Manual à API Oficial do TSE
```powershell
uv run horizonte-eleitoral --poll-tse-live --ignore-time-gate
```

---

## Qualidade de Código e Testes Automatizados

O projeto mantém padrões estritos de engenharia de software com 100% de conformidade:

```powershell
# Executar a suite completa de 183 testes automatizados (pytest)
uv run pytest

# Executar testes com relatorio detalhado de cobertura
uv run pytest --cov=src --cov-report=term-missing

# Verificacao estatica rigorosa de tipos (mypy strict)
uv run mypy src

# Verificacao e formatacao de estilo de codigo (ruff)
uv run ruff format --check .
uv run ruff check .
```

---

## Estrutura do Repositório

```text
horizonte_eleitoral/
├── AGENTS.md                  # [Constituição] Regras centrais e diretrizes operacionais
├── README.md                  # [Este arquivo] Guia geral e instruções de execução
├── pyproject.toml             # Configuração do projeto, dependências uv, ruff e mypy
├── uv.lock                    # Trava determinística de versões de dependências
│
├── docs/                      # Suíte de Documentação Técnica Canônica (Living Docs)
│   ├── README.md              # Portal e índice geral da documentação
│   ├── ARQUITETURA.md         # [Mapa] Arquitetura de software, componentes e fluxo de dados
│   ├── METODOLOGIA_ESTATISTICA.md # [Metodologia] Formulação matemática, modelos e simulações
│   ├── DECISOES_DE_ENGENHARIA.md  # [Histórico / ADRs] Registros de Decisão de Arquitetura
│   └── STATUS_E_GOVERNANCA.md # [Status] Saúde dos testes, delete-zone e regras de contribuição
│
├── src/horizonte_eleitoral/   # Código-fonte da aplicação
│   ├── api/                   # Camada de API REST (FastAPI)
│   ├── backtest/              # Ferramental de avaliação preditiva, métricas e comparação
│   ├── dashboard/             # Aplicação web Streamlit (gráficos Altair e visualização)
│   ├── domain/                # Núcleo de regras e entidades imutáveis (Zero I/O)
│   ├── historical/            # Pareamento geográfico e índice de elasticidade 2018-2022
│   ├── ingestion/             # Clientes HTTP, rate limiter e poller oficial do TSE
│   ├── models/                # Baselines 1..4 e Modelo Hierárquico Bayesiano V2
│   ├── normalization/         # Adaptadores dos arquivos do TSE (EA11..EA20)
│   ├── observability/         # Logging estruturado JSON com rastreabilidade
│   ├── publishing/            # Publicação atômica thread-safe de projeções (os.replace)
│   ├── reconciliation/        # Validador de consistência matemática dos dados (Failure-Stop)
│   ├── simulation/            # Motor Monte Carlo vetorizado e estimativa de comparecimento
│   └── storage/               # Persistência local append-only e serialização segura
│
├── tests/                     # Suíte de Testes Automatizados (183 testes)
│   ├── contract/              # Testes de contrato de domínio e API
│   ├── e2e/                   # Ensaio operacional ponta a ponta de noite eleitoral
│   ├── integration/           # Testes de integração entre componentes e persistência
│   ├── unit/                  # Testes unitários puros com isolamento de dependências
│   └── fixtures/              # Dados de teste determinísticos para execução sem rede
│
├── scripts/                   # Utilitários de consolidação e pré-computação de dados
└── data/                      # Cofre local de dados e arquivos Parquet analíticos
```

---

## Documentação Técnica Completa

Para aprofundar-se em qualquer aspecto técnico do projeto, consulte os documentos dedicados em [`docs/`](docs/):

- **[Mapa de Arquitetura e Componentes (`docs/ARQUITETURA.md`)](docs/ARQUITETURA.md):** Fluxo de dados, fronteiras de módulo e tabela de atalhos rápidos.
- **[Metodologia Estatística e Preditiva (`docs/METODOLOGIA_ESTATISTICA.md`)](docs/METODOLOGIA_ESTATISTICA.md):** Detalhamento matemático dos baselines, do modelo hierárquico V2 com elasticidade municipal, do algoritmo de Monte Carlo e dos resultados em 499k seções.
- **[Decisões de Engenharia e ADRs (`docs/DECISOES_DE_ENGENHARIA.md`)](docs/DECISOES_DE_ENGENHARIA.md):** Registros formais de decisão (ADR 001 a ADR 007) justificando o cofre imutável, a publicação atômica, o uso de Parquet/DuckDB e as políticas de coleta.
- **[Status do Projeto e Governança (`docs/STATUS_E_GOVERNANCA.md`)](docs/STATUS_E_GOVERNANCA.md):** Indicadores de qualidade, Zona de Exclusão (*Delete-Zone*) e diretrizes de desenvolvimento.
- **[Constituição de Agentes (`AGENTS.md`)](AGENTS.md):** Invariantes de desenvolvimento e conduta para agentes e contribuidores.

---

## Aviso Legal e Ético

1. **A projeção preditiva não é apuração oficial:** A única autoridade legal com prerrogativa de homologar resultados eleitorais no Brasil é o **Tribunal Superior Eleitoral (TSE)**. O Horizonte Eleitoral é uma ferramenta independente de modelagem estatística, ciência de dados e pesquisa acadêmica/jornalística baseada estritamente em dados públicos.
2. **Uso Cidadão da Infraestrutura:** O sistema segue rigorosas políticas de limitação de taxa e cabeçalhos condicionais (`HTTP 304`), gerando impacto de rede praticamente nulo nos servidores de divulgação de resultados.
