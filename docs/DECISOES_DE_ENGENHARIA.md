# Decisões de Engenharia e Registros de Arquitetura (ADRs) · Horizonte Eleitoral

Este documento reúne os **Registros de Decisão de Arquitetura (Architecture Decision Records - ADRs)** e as justificativas técnicas e lógicas para as escolhas de engenharia do sistema **Horizonte Eleitoral**.

---

## Índice dos Registros de Decisão (ADRs)

- [ADR 001: Armazenamento Imutável de Artefatos Brutos e Identificadores Determinísticos](#adr-001-armazenamento-imutável-de-artefatos-brutos-e-identificadores-determinísticos)
- [ADR 002: Reconciliação Estrita de Snapshots e Política "Failure-Stop" contra Divergências](#adr-002-reconciliação-estrita-de-snapshots-e-política-failure-stop-contra-divergências)
- [ADR 003: Publicação Atômica via os.replace e Desacoplamento da Apresentação](#adr-003-publicação-atômica-via-osreplace-e-desacoplamento-da-apresentação)
- [ADR 004: Armazenamento Colunar Apache Parquet e Motor Analítico DuckDB](#adr-004-armazenamento-colunar-apache-parquet-e-motor-analítico-duckdb)
- [ADR 005: Substituição do Modelo Hierárquico V1 pelo HORIZON-MRP (V2) com Elasticidade Municipal](#adr-005-substituição-do-modelo-hierárquico-v1-pelo-horizon-mrp-v2-com-elasticidade-municipal)
- [ADR 006: Coleta Não-Invasiva na API do TSE (Rate Limiting, Polling 304 e Gate das 17h)](#adr-006-coleta-não-invasiva-na-api-do-tse-rate-limiting-polling-304-e-gate-das-17h)
- [ADR 007: Cascata Hierárquica Espacial de Pareamento Geográfico com Penalização de Incerteza](#adr-007-cascata-hierárquica-espacial-de-pareamento-geográfico-com-penalização-de-incerteza)

---

## ADR 001: Armazenamento Imutável de Artefatos Brutos e Identificadores Determinísticos

### Status
Aprovado e Implementado.

### Contexto
Sistemas de ingestão eleitoral lidam com fontes externas governamentais que sofrem retransmissões, instabilidades de rede e eventuais correções de totalização. Sobrescrever respostas brutas ou utilizar identificadores aleatórios (UUIDs) destrói a auditabilidade forense e impede o replay exato de corridas passadas.

### Decisão
1. Toda resposta recebida da API do TSE é encapsulada em um `RawArtifactRequest` e salva em disco como `RawArtifact` em regime append-only.
2. Cada artefato calcula obrigatoriamente o hash SHA-256 do corpo exato em bytes e preserva URL de origem, código de resposta HTTP, timestamp UTC e headers normalizados.
3. Identificadores são determinísticos gerados pela função `deterministic_id(prefix, payload)`, calculando o hash SHA-256 da representação canônica dos metadados. O mesmo arquivo coletado sob as mesmas condições sempre terá o mesmo identificador estável.
4. É proibida a deleção ou sobrescrita de qualquer arquivo dentro do cofre bruto (`data/`).

### Consequências
- **Positivas:** Rastreabilidade absoluta de dados; auditoria independente simplificada; reprodutibilidade perfeita de simulações.
- **Trade-offs:** Demanda maior espaço em disco (mitigado pela compactação Parquet nas fases subsequentes).

---

## ADR 002: Reconciliação Estrita de Snapshots e Política "Failure-Stop" contra Divergências

### Status
Aprovado e Implementado.

### Contexto
Durante a apuração, os arquivos de resumo geral (como EA20) e os arquivos detalhados de seções (como EA16) podem sofrer atrasos de replicação nos CDNs do TSE. Em sistemas frágeis, desenvolvedores costumam aplicar "gambiarras matemáticas" (forçar votos artificiais em brancos/nulos) para forçar as somas a fecharem.

### Decisão
1. O `ReconciliationEngine` valida minuciosamente o total de seções totalizadas no agregado contra a soma exata dos boletins individuais recebidos.
2. Se houver divergência de contagem, o snapshot recebe o status `SnapshotStatus.INCONSISTENT` e a geração da projeção é **imediatamente bloqueada**.
3. É expressamente proibido alterar votos observados para "fazer a conta fechar". O sistema adota a política de *failure-stop*: um erro visível e transparente é preferível a uma projeção gerada sobre dados corrompidos.
4. Enquanto um snapshot estiver inconsistente, os consumidores (API e Dashboard) continuam servindo a última versão consistente publicada (`latest.json`), acompanhada de um aviso diagnóstico nos logs.

### Consequências
- **Positivas:** Impossibilidade matemática de gerar previsões baseadas em dados dessincronizados do TSE.
- **Trade-offs:** Em momentos raros de dessincronização do CDN do TSE, a projeção aguarda o próximo ciclo de polling sem atualizar imediatamente.

---

## ADR 003: Publicação Atômica via os.replace e Desacoplamento da Apresentação

### Status
Aprovado e Implementado.

### Contexto
Em sistemas de tempo real, consumidores web (Streamlit e FastAPI) consultam o estado da apuração com alta concorrência. Se o motor preditivo escrever diretamente no arquivo de destino `latest.json`, leitores concorrentes podem ler JSONs incompletos ou corrompidos durante a operação de escrita.

Além disso, permitir que o Streamlit execute cálculos preditivos pesados em cada interação do usuário degrada a performance da aplicação e mistura responsabilidades.

### Decisão
1. O `AtomicPublisher` grava a projeção primeiro em um arquivo temporário (`tempfile.NamedTemporaryFile`) localizado no mesmo dispositivo de armazenamento do arquivo final.
2. Após a serialização completa e validação de integridade, executa a operação atômica nativa do sistema operacional (`os.replace`). No Windows e Linux, `os.replace` é garantido em nível de sistema de arquivos como atômico, assegurando que nenhum processo leitor veja um estado intermediário.
3. Desacoplamento estrito: O Streamlit é desenhado como um leitor passivo de projeções já publicadas. Ele nunca faz chamadas de rede ao TSE nem executa simulações pesadas durante requisições de página.

### Consequências
- **Positivas:** Zero risco de race condition ou leitura de payload truncado; tempo de resposta do dashboard abaixo de 100ms; arquitetura escalável e resiliente.

---

## ADR 004: Armazenamento Colunar Apache Parquet e Motor Analítico DuckDB

### Status
Aprovado e Implementado.

### Contexto
A base eleitoral brasileira de 2026 possui **499.206 seções eleitorais**. Nos ensaios iniciais, carregar essa base via arquivos CSV e iterar sobre listas de dicionários Python consumia mais de 45 segundos por marco e demandava mais de 3 GB de memória RAM.

### Decisão
1. Criação do pipeline de conversão e exportação para o formato colunar **Apache Parquet** na camada analítica (`data/final/catalog_2026.parquet` e `data/final/elasticity_2018_2022.parquet`).
2. O catálogo consolida chaves de seção, dados demográficos, bases históricas de 2022 e votos observados em formato tipado e comprimido (Snappy).
3. Integração com a biblioteca colunar **DuckDB**, permitindo executar consultas analíticas SQL em memória com alta velocidade:
   ```powershell
   uv run horizonte-eleitoral --query-sql "SELECT state, count(*), sum(electorate) FROM 'data/final/catalog_2026.parquet' GROUP BY state"
   ```
4. Adoção do Parquet como formato padrão para o replay do Streamlit e para as rotinas de backtesting.

### Consequências
- **Positivas:** O tempo de carga das 499k seções despencou de 45s para **menos de 0,8 segundo**; o uso de memória caiu em mais de 70%; viabilizou a linha do tempo interativa no Streamlit.

---

## ADR 005: Substituição do Modelo Hierárquico V1 pelo HORIZON-MRP (V2) com Elasticidade Municipal

### Status
Aprovado e Implementado (V1 arquivado como baseline legado; HORIZON-MRP estabelecido como modelo oficial).

### Contexto
A primeira versão do modelo multinível (`HierarchicalBayesianModelV1`) utilizava pós-estratificação regional e encolhimento bayesiano estático em 3 níveis (Nacional, Regional e Estadual). Contudo, testes empíricos em larga escala revelaram que o modelo V1 demorava para reagir em municípios que historicamente apresentavam grande volatilidade eleitoral (alta sensibilidade a ciclos econômicos e demográficos).

### Decisão
1. Criação do **HORIZON-MRP** (*Hierarchical Optimal Regression & Inferred Zonal Outcomes Network*), implementado na classe `HierarchicalBayesianModelV2` (aliases `HorizonMRP` e `HierarchicalBayesianModel`), como o modelo ativo oficial do projeto.
2. Incorporação do `MunicipalElasticityIndex` a partir da série histórica multi-ciclo 2018–2022.
3. Modulação dinâmica do fator de encolhimento municipal $K_{\text{eff}} = \frac{K_{\text{muni}}}{1 + s \cdot \text{vol}_m}$, permitindo que municípios voláteis acelerem o aprendizado da evidência de 2026, enquanto municípios estáveis preservem a ancoragem na base histórica de 2022.
4. O `HierarchicalBayesianModelV1` foi mantido no código apenas como artefato arquivado para fins de governança, auditoria histórica e comparação no módulo `horizonte_eleitoral.backtest.compare`.

### Consequências
- **Positivas:** Redução do MAE nacional de 0,55 pp para 0,30 pp logo aos 2% do eleitorado apurado; redução no erro de saldo entre os líderes (Lead Error).
- **Consistência:** A interface gráfica e os ensaios operacionais utilizam exclusivamente o HORIZON-MRP.

---

## ADR 006: Coleta Não-Invasiva na API do TSE (Rate Limiting, Polling 304 e Gate das 17h)

### Status
Aprovado e Implementado.

### Contexto
Na noite de eleição, os servidores do TSE são alvo de tráfego intenso de milhões de cidadãos e veículos de imprensa. Uma ferramenta automatizada deve se comportar de forma extremamente cidadã, minimizando o impacto na infraestrutura pública.

### Decisão
1. O `TSEAsyncClient` implementa um limitador de taxa (**Token Bucket**) estrito de no máximo 20 requisições por segundo e concorrência máxima de 10 conexões simultâneas.
2. Implementação de polling condicional: requisições HTTP enviam os cabeçalhos `If-None-Match` (com o último ETag) e `If-Modified-Since`. Se o TSE não tiver dados novos, responde com `HTTP 304 Not Modified`, economizando largura de banda e processamento de ambos os lados.
3. Implementação de Gate de Horário (`is_election_night_window`): o coletor automático bloqueia requisições fora do período de apuração (domingos após as 17h de Brasília), evitando disparos acidentais em dias comuns. Para desenvolvimento, ensaios e testes, existe a flag de controle `--ignore-time-gate`.

### Consequências
- **Positivas:** Carga praticamente nula nos servidores do TSE; cumprimento integral das boas práticas de engenharia de internet pública.

---

## ADR 007: Cascata Hierárquica Espacial de Pareamento Geográfico com Penalização de Incerteza

### Status
Aprovado e Implementado.

### Contexto
Entre uma eleição e outra, zonas eleitorais sofrem remanejamentos: escolas fecham, novos locais de votação são inaugurados e seções são agregadas. Portanto, não existe correspondência biunívoca 100% perfeita entre os códigos de seção de 2022 e 2026.

### Decisão
1. O `GeographicMatcher` constrói uma cascata espacial determinística em seis estágios:
   - **Classe A (EXACT):** Mesmo código de local, zona, município e UF.
   - **Classe B (SAME_COMPLEX):** Distância Haversine $\le 100\text{m}$ no mesmo município.
   - **Classe C (NEIGHBORING):** Vizinhos mais próximos até $5.000\text{m}$ ponderados pelo inverso da distância ($1/d$).
   - **Classe D (SAME_ZONE):** Média das seções históricas da mesma zona eleitoral.
   - **Classe E (SAME_MUNICIPALITY):** Média das seções históricas do mesmo município.
   - **Classe F (UNMATCHED):** Fallback estadual.
2. A incerteza do modelo de Monte Carlo é multiplicada por um fator proporcional à incerteza do pareamento (variando de $1.0\times$ para a Classe A até $4.0\times$ para a Classe F).
3. Nunca duplicar votos: seções agregadas recebem a distribuição percentual histórica daquele local, e não o número absoluto de votos do pleito anterior.

### Consequências
- **Positivas:** O sistema consegue parear 100% das seções de 2026 sem intervenção manual, mantendo intervalos de confiança alargados de forma estatisticamente justa onde o histórico é imperfeito.
