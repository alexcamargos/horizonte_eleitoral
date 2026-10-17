# Diretrizes para Agentes e Desenvolvedores · Horizonte Eleitoral

Este documento constitui a **Constituição Técnica** do projeto **Horizonte Eleitoral** sob os princípios de *Living Docs Governance*. Todos os agentes autônomos e desenvolvedores que operam neste repositório devem obedecer estritamente a estas regras.

---

## 1. Princípios Inegociáveis

1. **Dados Brutos são Sagrados e Imutáveis:** Respostas da API do TSE ou arquivos baixados jamais são modificados ou sobrescritos. São gravados com hash SHA-256, URL de origem, timestamp UTC e headers no cofre imutável (`RawArtifact`).
2. **Reproduzibilidade Determinística:** Toda projeção é reprodutível. Nenhuma função preditiva utiliza números aleatórios sem semente (`seed`) controlada e explícita.
3. **Consistência antes de Previsão (Failure-Stop):** Um snapshot divergente (onde a soma dos boletins de urna diverge da totalização oficial) é marcado como `INCONSISTENT` e bloqueia a publicação. **Nunca altere votos para "fazer fechar a conta"**.
4. **Sem Vazamento Temporal (Data Leakage):** Nenhuma simulação, backtest ou replay pode ter acesso a dados do futuro em relação ao marco temporal avaliado.
5. **Separação de Responsabilidades (Desacoplamento):** O dashboard Streamlit e a API FastAPI são consumidores somente leitura de projeções publicadas atomicamente. Eles **nunca** realizam coletas HTTP no TSE nem ajustam modelos estatísticos pesados durante o ciclo de renderização.
6. **Um Fato, Um Dono Canônico:** Cada fato sobre o projeto possui um único local canônico de governança. Não duplique texto entre documentos; use links relativos.

---

## 2. Mapa dos Papéis de Documentação (Living Docs)

| Papel | Arquivo Canônico | Responsabilidade Exclusiva |
|---|---|---|
| **Constituição** | [`AGENTS.md`](AGENTS.md) | Regras inegociáveis, convenções de código e restrições ético-estatísticas. |
| **Mapa** | [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) | O que existe, onde mora, fronteiras entre módulos e tabela de navegação rápida. |
| **Metodologia** | [`docs/METODOLOGIA_ESTATISTICA.md`](docs/METODOLOGIA_ESTATISTICA.md) | Formulação matemática, modelos de referência, modelo hierárquico V2 e simulação Monte Carlo. |
| **Histórico / ADRs** | [`docs/DECISOES_DE_ENGENHARIA.md`](docs/DECISOES_DE_ENGENHARIA.md) | Decisões duráveis de arquitetura (ADRs), justificativas lógicas e histórico de desenho. |
| **Status & Delete-Zone** | [`docs/STATUS_E_GOVERNANCA.md`](docs/STATUS_E_GOVERNANCA.md) | Saúde atual da suíte, roadmap, regras de contribuição e zona de exclusão de artefatos obsoletos. |

---

## 3. Padrões de Código e Engenharia

- **Versão do Python:** Python 3.12 ou superior.
- **Gerenciador de Dependências:** Astral `uv` exclusivamente (`uv run ...`, `uv add ...`). Não utilize comandos `pip` isolados.
- **Padrão de Código:** Estrita adesão ao **PEP 8**, verificado e formatado via `ruff`.
- **Tipagem Estática:** `mypy src --strict` obrigatório. Toda função pública, método e fronteira de módulo deve ter type hints completos.
- **Docstrings:** Formato **Google Style** obrigatório para todo módulo, classe, método e função pública (`Args:`, `Returns:`, `Raises:`).
- **Testes Automatizados:**
  - Framework exclusivo: `pytest`.
  - Mocking exclusivo: `pytest-mock` (fixture `mocker`).
  - **Proibição estrita:** É vedado o uso de `unittest`, `unittest.TestCase` ou `unittest.mock`.
  - Todos os testes devem ser baseados em funções puras com fixtures nativas do pytest.

---

## 4. Sequência Operacional para Agentes

Ao iniciar uma tarefa neste repositório:
1. **Consulte a Constituição** (`AGENTS.md`): internalize os limites e invariantes.
2. **Consulte o Mapa** ([`docs/ARQUITETURA.md`](docs/ARQUITETURA.md)): localize os pacotes e arquivos envolvidos.
3. **Consulte o Status e a Delete-Zone** ([`docs/STATUS_E_GOVERNANCA.md`](docs/STATUS_E_GOVERNANCA.md)): certifique-se de não reintroduzir abordagens abandonadas (ex.: reativar Modelo V1 ou iteradores CSV lentos).
4. **Verifique antes de Concluir:**
   ```powershell
   uv run ruff format --check .
   uv run ruff check .
   uv run mypy src
   uv run pytest
   ```
