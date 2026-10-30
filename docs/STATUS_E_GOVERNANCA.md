# Status do Projeto, Governança e Delete-Zone · Horizonte Eleitoral

Este documento constitui a visão canônica do **Status de Saúde Atual**, da **Zona de Exclusão (Delete-Zone)** e dos **Padrões de Governança Contínua** do projeto Horizonte Eleitoral.

---

## 1. Status de Saúde Atual do Sistema

| Dimensão | Métrica / Status | Evidência Canônica |
|---|---|---|
| **Suíte de Testes Automatizados** | **190 testes passando (100% sucesso)** | `uv run pytest` |
| **Cobertura de Testes** | Unitários, Contrato, Integração, E2E e Swing | Diretório `tests/` |
| **Tipagem Estática** | **100% Strict** (zero avisos) | `uv run mypy src` |
| **Linting e Formatação** | **100% Conforme** PEP 8 | `uv run ruff check .` e `uv run ruff format --check .` |
| **Versão Mínima de Runtime** | Python 3.12+ (testado em 3.12 e 3.13) | `pyproject.toml` |
| **Validação com Dados Reais** | **499.206 seções eleitorais** (1º e 2º Turnos de 2026) | `catalog_2026.parquet` e `catalog_2026_2t.parquet` (`5.716` municípios TSE) |
| **Integração em Tempo Real** | **TSE CDN Oficial 2026 2º Turno (Eleição 6258, BR + 28 UFs)** | Condicionamento live aos votos reais do 2T (`second_round_live.py`) |
| **Precisão Preditiva (Início da Apuração)** | **MAE = 0,06 pp** (1T em 2%) e **MAE = 0,09 pp** (2T em 5% às 19h30) | Validação retroativa pós-19h sem vazamento (`checkpoints_2026_2t.json`) |

---

## 2. Zona de Exclusão (Delete-Zone)

Sob as regras de *Living Docs Governance*, a **Delete-Zone** documenta formalmente componentes, abordagens e arquivos que foram intencionalmente descontinuados, substituídos ou proibidos de reintrodução.

| Componente ou Conceito | Por que foi Removido / Descontinuado | Substituto Oficial | Condição para Revisitar |
|---|---|---|---|
| **Shift aditivo com corte (`max(0, hist + delta)`) e swing agregado com viés de Jensen** | O shift aditivo linear distorce a geometria do simplex e introduz viés de até 1,0 pp de margem; o swing log-ratio agregado sofre do viés não-linear de Jensen (+0,43 pp em amostra). | `calibrated_logratio_swing` via Newton-Raphson (`src/horizonte_eleitoral/models/swing.py`) e formulação exponencial $p_{ik} \propto b_{ik} e^{\delta_k}$. | **Estritamente proibido** retornar a shifts aditivos lineares ou fórmulas agregadas não calibradas. |
| **`HierarchicalBayesianModelV1` como modelo padrão** | O modelo V1 utilizava encolhimento aditivo estático e sofria de viés de Jensen na reconstrução. | **`HORIZON-MRP`** (`HierarchicalBayesianModelV2`, com MRP calibrado e encolhimento bayesiano). | Reativar apenas como baseline de comparação histórica (`--compare-v1-v2`). |
| **Iteração linha por linha sobre CSVs de 500k seções** | Carregar `sections_2026.csv` em Python puro consumia 45s e mais de 3 GB de RAM, inviabilizando o dashboard interativo. | Catálogo colunar `catalog_2026.parquet` e consultas via DuckDB em memória (<0,8s). | Proibido retornar para carga linha por linha de CSVs em rotinas de produção ou dashboard. |
| **Uso de `unittest` ou `unittest.mock`** | O projeto adota testes funcionais modernos com fixtures nativas e tipagem pytest. | `pytest` e `pytest-mock` (fixture `mocker`). | **Estritamente proibido** pelo padrão global do projeto. |
| **Ajuste artificial de votos para "fechar conta"** | Adulterar contagens para conciliar arquivos com divergência mascara problemas de replicação nos CDNs do TSE. | `ReconciliationEngine` com política de *Failure-Stop* (`SnapshotStatus.INCONSISTENT`). | Nunca revisitar. A inviolabilidade dos dados oficiais é um princípio inegociável. |
| **Arquivos de planejamento legado (`docs/*.md` antigos)** | `ESPECIFICACAO_TECNICA_DE_IMPLEMENTACAO.md`, `ETAPAS_DE_IMPLEMENTACAO.md` e `PLANO_DE_ORQUESTRACAO.md` continham previsões de implementação antes do desenvolvimento das fases de Parquet, DuckDB, Modelo V2 e 2º Turno. | Nova suíte em `docs/` (`README.md`, `ARQUITETURA.md`, `METODOLOGIA_ESTATISTICA.md`, `DECISOES_DE_ENGENHARIA.md`, `STATUS_E_GOVERNANCA.md`). | Mantidos apenas no histórico do Git. |
| **Diretório plano e desordenado de dados (`data/real`)** | Misturar arquivos ZIP brutos, CSVs intermediários e Parquets/JSONs finais em um mesmo diretório dificultava a governança de dados, auditoria e separação de responsabilidades. | Sistema tripartido de dados: `data/raw/` (dados brutos imutáveis), `data/norm/` (dados intermediários normalizados) e `data/final/` (artefatos de produção colunares Parquet e JSONs). | Proibido reintroduzir acúmulo desordenado de arquivos em diretório plano. |
| **Projeção live do 2º Turno sem condicionamento aos votos reais da API TSE** | Reutilizar `group_votes` estáticos do 1º turno do `catalog_2026.parquet` congelava a projeção em ~49,07% PT / 50,93% PL independentemente dos votos apurados no 2º turno. | `project_second_round_live` (`src/horizonte_eleitoral/simulation/second_round_live.py`) condicionado a `NormalizedTotalization` (`BR` + 28 UFs). | **Estritamente proibido** projetar rodadas em tempo real sem injetar os votos reais apurados pelo TSE. |

---

## 3. Padrões de Engenharia e Contribuição

Todo código desenvolvido ou revisado deve cumprir os seguintes critérios inegociáveis:

### 3.1 Padrão Python e Estrutura
- **Python 3.12+** utilizando type hints modernos (`X | None`, `list[str]`, `Sequence[T]`).
- **Dataclasses Imutáveis:** Entidades de domínio devem usar `@dataclass(frozen=True, slots=True)`.
- **Decimal em Distribuições:** Participações percentuais e somas de votos que requerem precisão exata devem utilizar `Decimal` para evitar imprecisões de representação binária IEEE 754.
- **Tratamento de Exceções:** Exceções devem ser tipadas e herdar da hierarquia de domínio (`ValidationError`, `InvariantViolationError`, `ConfigurationError`). É proibido `except Exception: pass` silencioso em lógica de negócio.

### 3.2 Docstrings Google Style
Toda função, classe, método e módulo público deve possuir docstring completa:
```python
def predict(
    self,
    *,
    observations: list[SectionObservation],
    pending: list[PendingSection],
    groups: tuple[str, ...] = ("PT", "PL", "OUTROS"),
) -> ForecastResult:
    """Gera previsao pontual esperada do modelo sobre secoes pendentes.

    Args:
        observations: Secoes observadas ja totalizadas pelo TSE.
        pending: Secoes pendentes de totalizacao.
        groups: Codigos dos grupos politicos avaliados.

    Returns:
        ForecastResult com shares projetados somando 1.0.

    Raises:
        InvariantViolationError: Se as secoes contiverem dados inconsistentes.
    """
```

### 3.3 Gerenciamento de Dependências com Astral `uv`
- Nunca instale pacotes diretamente com `pip`.
- Para adicionar uma dependência de produção: `uv add <pacote>`.
- Para adicionar uma dependência de desenvolvimento: `uv add --dev <pacote>`.
- Para sincronizar o ambiente virtual: `uv sync`.

---

## 4. Comandos de Verificação Operacional

Antes de qualquer commit, execute o ciclo completo de garantia de qualidade:

```powershell
# 1. Checagem e formatacao de estilo com Ruff
uv run ruff format --check .
uv run ruff check .

# 2. Verificacao estatica de tipos estrita com MyPy
uv run mypy src

# 3. Execucao de toda a suite de testes (190 testes)
uv run pytest

# 4. Execucao com medicao de cobertura de codigo
uv run pytest --cov=src --cov-report=term-missing
```

---

## 5. Roadmap e Próximos Passos

1. **Expansão para Eleições Governamentais de 2026:**
   - Adaptação dos modelos hierárquicos para as 27 disputas estaduais para governador, utilizando dados históricos regionalizados de 2018 e 2022.
2. **Integração com WebSocket para Atualizações Push:**
   - Criação de endpoint de subscrição SSE (*Server-Sent Events*) ou WebSocket no FastAPI para atualização instantânea dos clientes web sem necessidade de polling de tela.
3. **Calibração de Turnout com Covariáveis Climáticas e Históricas:**
   - Refinamento do modelo de abstenção em `simulation/turnout.py` para ponderar abstenção histórica por faixa etária e índice pluviométrico nas capitais no dia da eleição.
