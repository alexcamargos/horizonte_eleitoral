# Diretrizes para Agentes e Desenvolvedores · Horizonte Eleitoral

Este documento constitui a **Constituição Técnica** do projeto **Horizonte Eleitoral** sob os princípios de *Living Docs Governance*. Todos os agentes autônomos e desenvolvedores que operam neste repositório devem obedecer estritamente a estas regras.

---

## 1. Princípios Inegociáveis (Alinhados à Implementação Atual)

1. **Dados Brutos e Registros de Auditoria são Sagrados e Imutáveis (`Append-Only`):**
   - Respostas da API do TSE (`RawArtifactRequest`) ou arquivos baixados jamais são modificados ou sobrescritos.
   - No `LocalArtifactStore` (`src/horizonte_eleitoral/storage/local.py`), corpos binários são deduplicados por hash em `raw/sha256/<prefix>/<sha256>.blob` com escrita exclusiva (`open("xb")`) e manifestos JSON canônicos (`RawArtifact`) em `raw/manifests/`, contendo hash SHA-256, URL HTTPS de origem, status HTTP, timestamp UTC e cabeçalhos normalizados. Qualquer tentativa de sobrescrita com conteúdo distinto lança `ImmutableWriteError`.
   - Registros de linhagem (`FileLineageRepository` / `LineageRecord`), snapshots (`FileSnapshotRepository` / `CountSnapshot`, protegido por `SnapshotConflictError`) e migrações relacionais em `migrations/` seguem o mesmo contrato estritamente *append-only*.

2. **Reproduzibilidade e Identidade Determinística:**
   - Toda entidade auditável e projeção possui identificador determinístico gerado por `deterministic_id(namespace, payload)` (`src/horizonte_eleitoral/domain/identity.py`), aplicando SHA-256 sobre a serialização JSON canônica ordenada (prefixos `artifact:`, `lineage:`, `snapshot:` e `projection:`).
   - Nenhuma função preditiva, simulação estocástica (`MonteCarloSimulator`) ou ordenação cronológica de chegada de seções (`compute_section_arrival_score`, baseada em transformação Box-Muller sobre o hash MD5 de `section_id`) utiliza números aleatórios sem semente (`seed`) explícita e controlada (`np.random.default_rng(seed)`).

3. **Consistência antes de Previsão (*Failure-Stop*):**
   - O `ReconciliationEngine` (`src/horizonte_eleitoral/reconciliation/reconciler.py`) valida a consistência entre os estados individuais das seções (`NormalizedSectionState` / EA16) e a totalização consolidada (`NormalizedTotalization` / EA20), além de monitorar a defasagem temporal (`max_stale_seconds`).
   - Quando há divergência na contagem de seções totalizadas, o snapshot e o relatório recebem `SnapshotStatus.DIVERGENT` (valor `"DIVERGENTE"`), em oposição a `SnapshotStatus.CONSISTENT` (`"CONSISTENTE"`).
   - O `AtomicPublisher.publish()` bloqueia imediatamente qualquer snapshot cujo status não seja `SnapshotStatus.CONSISTENT`, lançando `ReconciliationError` e preservando intacta a última projeção válida publicada. **Nunca altere votos observados para "fazer fechar a conta"**.

4. **Sem Vazamento Temporal (*Zero Data Leakage*) e Limiar Mínimo de Projeção:**
   - Nenhuma simulação, backtest (`TimelineReplayer`), ensaio (`election_night_runner`) ou replay do dashboard pode acessar votos reais de urnas ainda não abertas no marco avaliado. O catálogo é particionado estritamente pelo corte (`cutoff`): seções apuradas tornam-se `SectionObservation` e seções não totalizadas tornam-se `PendingSection` (contendo apenas `electorate`, taxas esperadas de comparecimento/validade e `historical_shares`).
   - Projeções finais e intervalos de credibilidade de 90% ($[q_{05}, q_{95}]$) só são liberados como projeção consolidada a partir de **2,0% do eleitorado apurado** (`totalized_electorate_pct >= 2.0`); abaixo desse limiar, os números são classificados apenas como preliminares.

5. **Separação de Responsabilidades e Fronteiras de Isolamento:**
   - **Núcleo Puro sem I/O:** Os pacotes `domain/`, `models/`, `reconciliation/`, `simulation/` e `backtest/` nunca realizam operações de I/O de rede, banco de dados ou interface gráfica, nem leem `os.environ` diretamente. Configurações (`Settings` em `src/horizonte_eleitoral/config.py`) são carregadas exclusivamente nas bordas (`cli.py`, `api/`, `dashboard/`).
   - **Publicação Atômica e API Somente Leitura:** A API FastAPI (`src/horizonte_eleitoral/api/app.py`) é estritamente somente leitura (`/v1/projections/latest`, `/v1/projections/history`, `/v1/projections/{projection_id}`, `/v1/health/data`, `/v1/model-card`), consumindo o `AtomicPublisher` (que realiza troca atômica em memória protegida por `threading.Lock`, mantendo histórico por geografia e ID).
   - **Dashboard Streamlit em Três Abas:** O painel (`src/horizonte_eleitoral/dashboard/app.py`) opera de forma desacoplada em três frentes:
     1. *Aba 1 (2º Turno · Histórico e Validação Retroativa):* Carrega o catálogo analítico consolidado `catalog_2026_2t.parquet` em cache (`@st.cache_resource`) e utiliza marcos pré-computados (`data/real/checkpoints_2026_2t.json`) para auditar retroativamente, onda a onda, a precisão do modelo frente ao resultado final oficial do TSE (`5.716` municípios e `28` UFs);
     2. *Aba 2 (1º Turno · Replay e Validação):* Carrega o catálogo analítico `catalog_2026.parquet` em cache (`@st.cache_resource`) e prioriza marcos pré-computados (`data/real/checkpoints_2026.json`) para evitar recálculo pesado durante a navegação;
     3. *Aba 3 (2º Turno · Tempo Real TSE):* Realiza checagens controladas via `TSELivePoller` e `TSEAsyncClient`, respeitando *allowlist* HTTPS, *rate limit* Token Bucket (`AsyncRateLimiter`), cabeçalhos condicionais (`If-None-Match` / `If-Modified-Since` com suporte a `HTTP 304`) e a janela oficial de domingo após as 17h BRT (`is_election_night_window`).

6. **Modelo Preditivo Padrão (V2) e Performance Colunar (Parquet / DuckDB):**
   - O modelo ativo padrão do projeto é o `HierarchicalBayesianModelV2` (alias `HierarchicalBayesianModel` em `horizonte_eleitoral.models`), que modula o encolhimento (*shrinkage*) municipal pelo `MunicipalElasticityIndex` (2018–2022, salvo em `data/real/elasticity_2018_2022.parquet`). O `HierarchicalBayesianModelV1` permanece arquivado apenas para auditoria e comparação histórica (`--compare-v1-v2`).
   - O processamento da base real (499.206 seções) deve utilizar armazenamento colunar **Apache Parquet** (`pyarrow`) e consultas analíticas em memória via **DuckDB** (`RealDataLoader`). É proibido reintroduzir leitura iterativa lenta de CSVs brutos no caminho crítico do dashboard ou das simulações padrão.

7. **Um Fato, Um Dono Canônico (*Living Docs*):**
   - Cada fato sobre o projeto possui um único local canônico de governança. Não duplique texto extenso entre documentos; utilize links relativos.

---

## 2. Mapa dos Papéis de Documentação (Living Docs)

| Papel | Arquivo Canônico | Responsabilidade Exclusiva |
|---|---|---|
| **Constituição** | [`AGENTS.md`](AGENTS.md) | Regras inegociáveis, fronteiras de isolamento, convenções de código e restrições ético-estatísticas. |
| **Visão Geral & CLI** | [`README.md`](README.md) | Guia de início rápido, instalação com `uv` e catálogo de comandos operacionais da CLI. |
| **Portal Docs** | [`docs/README.md`](docs/README.md) | Índice navegável da documentação técnica e roteiros de leitura por perfil. |
| **Mapa** | [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) | O que existe, onde mora cada pacote em `src/horizonte_eleitoral/`, fronteiras e *jump table*. |
| **Metodologia** | [`docs/METODOLOGIA_ESTATISTICA.md`](docs/METODOLOGIA_ESTATISTICA.md) | Formulação matemática, 4 baselines, modelo hierárquico V2 com elasticidade e simulação Monte Carlo. |
| **Histórico / ADRs** | [`docs/DECISOES_DE_ENGENHARIA.md`](docs/DECISOES_DE_ENGENHARIA.md) | Decisões duráveis de arquitetura (ADR 001 a ADR 007), justificativas lógicas e *trade-offs*. |
| **Status & Delete-Zone** | [`docs/STATUS_E_GOVERNANCA.md`](docs/STATUS_E_GOVERNANCA.md) | Saúde atual da suíte (183 testes), *Delete-Zone*, padrões de contribuição e roadmap. |
| **Migrações SQL** | [`migrations/README.md`](migrations/README.md) | Regras *append-only* para evolução do schema relacional de auditoria (`migrations/001_foundation.sql`). |

---

## 3. Padrões de Código e Engenharia

- **Versão do Python:** Python 3.12 ou superior (`requires-python = ">=3.12"`). Utilize recursos modernos da linguagem (`X | None`, `list[...]`, `tuple[...]`, `Sequence[...]`, `Protocol`, `StrEnum`).
- **Gerenciador de Dependências:** Astral `uv` exclusivamente (`uv sync`, `uv run ...`, `uv add ...`). Não sugira nem utilize comandos `pip` isolados no desenvolvimento local.
- **Padrão de Código e Estilo:** Estrita adesão ao **PEP 8**, verificado e formatado via `ruff` (`line-length = 100`, `target-version = "py312"`, regras `E`, `F`, `I`, `N`, `UP`, `B`). Agrupe imports na ordem padrão: biblioteca padrão, pacotes de terceiros e módulos locais (`horizonte_eleitoral`).
- **Tipagem Estática:** `uv run mypy src` com `strict = true` obrigatório (`warn_unreachable = true`, `warn_unused_configs = true`). Toda função, método e fronteira de módulo deve possuir *type hints* completos.
- **Contratos de Domínio e Exceções:**
  - Entidades de domínio e objetos de valor devem ser imutáveis com `@dataclass(frozen=True, slots=True)`.
  - Identificadores externos do TSE (`election_id`, `municipality_code`, `zone`, `section`, `local_code`) devem ser preservados como `str`, mantendo zeros à esquerda.
  - Distribuições formais de domínio (`VoteDistribution`) utilizam `Decimal` com validação de soma `1.0` dentro de `SHARE_TOLERANCE = Decimal("0.000001")`.
  - Erros de negócio e infraestrutura devem utilizar a hierarquia tipada derivada de `HorizonteEleitoralError` (`ValidationError`, `ConfigurationError`, `InvariantViolationError`, `ReconciliationError`, `SourceUnavailableError`, `ArtifactNotFoundError`, `ArtifactStorageError`, `ImmutableWriteError`, `SnapshotConflictError`).
- **Docstrings:** Formato **Google Style** obrigatório para todo módulo, classe, método e função (`Args:`, `Returns:`, `Raises:`). Preserve comentários e docstrings existentes que não sejam afetados por suas alterações.
- **Testes Automatizados:**
  - Framework exclusivo: `pytest` (com `pytest-asyncio` para testes assíncronos e `pytest-cov` para cobertura), estruturado em `tests/unit/`, `tests/contract/`, `tests/integration/` e `tests/e2e/`.
  - Mocking exclusivo: `pytest-mock` (fixture `mocker`).
  - **Proibição estrita:** É vedado o uso de `unittest`, `unittest.TestCase` ou `unittest.mock`.
  - Todos os testes devem ser baseados em funções puras com fixtures nativas do `pytest` e executar de forma 100% determinística e offline (usando `tests/fixtures/`).

---

## 4. Sequência Operacional para Agentes

Ao iniciar qualquer tarefa neste repositório:
1. **Consulte a Constituição** ([`AGENTS.md`](AGENTS.md)): internalize os limites, contratos de domínio e invariantes.
2. **Consulte o Mapa** ([`docs/ARQUITETURA.md`](docs/ARQUITETURA.md)): localize os pacotes, módulos e testes correspondentes.
3. **Consulte o Status e a Delete-Zone** ([`docs/STATUS_E_GOVERNANCA.md`](docs/STATUS_E_GOVERNANCA.md)): certifique-se de não reintroduzir abordagens descontinuadas (ex.: `HierarchicalBayesianModelV1` como padrão ou leitura sequencial lenta de CSVs de 500k seções).
4. **Execute a Verificação Completa de Qualidade antes de Concluir:**
   ```powershell
   uv run ruff format --check .
   uv run ruff check .
   uv run mypy src
   uv run pytest
   ```

