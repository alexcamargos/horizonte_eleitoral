# Metodologia Estatística e Preditiva · Horizonte Eleitoral

Este documento detalha os fundamentos estatísticos, matemáticos e probabilísticos do sistema **Horizonte Eleitoral**, explicando como o algoritmo prevê o resultado final das eleições presidenciais brasileiras antes da conclusão da apuração oficial pelo Tribunal Superior Eleitoral (TSE).

---

## 1. O Problema Fundamental: O Viés Geográfico da Apuração Eleitoral

### 1.1 A Ilusão dos Números Preliminares ("Virada de Apuração")

Na noite da eleição, as urnas eletrônicas brasileiras encerram a votação às 17h (horário de Brasília). A partir desse instante, os boletins de urna (BUs) são transmitidos aos servidores do TSE e totalizados progressivamente.

No entanto, **o ritmo de transmissão das urnas não é homogêneo nem aleatório**:
- Estados das regiões **Sul**, **Centro-Oeste** e municípios do **interior de São Paulo** transmitem seus boletins com velocidade muito superior à média nacional, atingindo frequentemente 50% a 70% de apuração nas primeiras duas horas.
- Municípios populosos de grandes regiões metropolitanas (como a capital paulista e a Baixada Fluminense) e a região **Nordeste** possuem logística de transmissão que costuma concluir a apuração mais tarde.

Como o comportamento eleitoral brasileiro apresenta forte correlação geográfica e demográfica:
1. Um candidato com forte apelo no Sul/Sudeste/Centro-Oeste pode acumular uma vantagem artificial de **10 a 20 pontos percentuais** nos primeiros 10% a 30% da apuração oficial.
2. À medida que as urnas do Nordeste e das periferias metropolitanas são processadas, a curva de apuração sofre uma inflexão drástica (o chamado efeito de "virada").
3. Essa dinâmica natural da totalização gera ansiedade pública, desinformação e suspeitas infundadas sobre a integridade das urnas.

### 1.2 Objetivo do Motor Preditivo

O Horizonte Eleitoral elimina essa distorção ao separar estritamente:
- **Votos Apurados Observados:** O que já está nas urnas abertas e totalizadas pelo TSE (fato histórico consolidado).
- **Votos Pendentes Estimados:** A distribuição esperada de votos das seções que **ainda não foram apuradas**, condicionada ao perfil histórico daquela seção exata e à evidência amostral já revelada pelo mesmo município, estado e país.

---

## 2. Catálogo de Modelos de Referência (Baselines)

Para garantir rigor científico, o sistema implementa e compara continuamente 4 modelos de referência (baselines). Todos entregam o mesmo objeto matemático: o vetor de proporções projetadas de votos válidos $\hat{p}_k \in [0,1]$, com $\sum_k \hat{p}_k = 1$ (campo `projected_shares` de `ForecastResult`).

**Equação comum de totalização (Baselines 2, 3 e 4).** Os votos observados são mantidos intactos e cada seção pendente $j$ contribui com seus votos válidos esperados distribuídos segundo uma probabilidade projetada $p_{jk}$:
$$\hat{Y}_k = \sum_{i \in \text{Obs}} y_{ik} + \sum_{j \in \text{Pend}} \hat{V}_j \cdot p_{jk}, \qquad \hat{p}_k = \frac{\hat{Y}_k}{\sum_{m} \hat{Y}_m}$$
Onde $\hat{V}_j = E_j \cdot \tau_j \cdot \nu_j$ é o eleitorado $E_j$ ponderado pelas taxas esperadas de comparecimento ($\tau_j \approx 0.80$) e votos válidos ($\nu_j \approx 0.95$). Os três baselines diferem **exclusivamente** na definição de $p_{jk}$.

### Baseline 1: Apurado Bruto (Raw Count)
Representa a média ingênua dos votos válidos apurados até o instante $t$:
$$\hat{p}_k^{(t)} = \frac{\sum_{i \in \text{Obs}} y_{ik}}{\sum_{i \in \text{Obs}} V_i}$$
Onde $y_{ik}$ são os votos do grupo político $k$ na seção $i$, e $V_i$ é o total de votos válidos da seção.
- **Limitação:** Sofre com todo o viés de ritmo geográfico de apuração. Nos primeiros 10% de apuração de 2026, apresentou erro superior a **9,4 pontos percentuais**.

### Baseline 2: Base Histórica Pura sem Swing (Historical No-Swing)
Projeta as seções pendentes aplicando diretamente sua participação histórica da eleição de 2022 na [equação comum de totalização](#2-catálogo-de-modelos-de-referência-baselines):
$$p_{jk} = b_{jk}^{(2022)}$$
Onde $b_{jk}^{(2022)}$ é a proporção de votos do grupo $k$ na seção $j$ em 2022.
- **Limitação:** Ignora completamente o deslocamento (swing) da eleição corrente em relação a 2022.

### Baseline 3: Swing Nacional Composicional (National Swing)
Estima o deslocamento médio nacional em espaço logarítmico (log-ratios) entre as seções observadas e suas respectivas bases históricas em 2022.

**Estimador Calibrado (Padrão):**
Resolve por Newton-Raphson amortecido as equações de calibração exata (equivalente à máxima verossimilhança de interceptos multinomial logit com offsets $\ln b_{ik}$):
$$\sum_{i \in \text{Obs}} V_i \cdot \frac{b_{ik}^{(2022)} e^{\delta_k}}{\sum_m b_{im}^{(2022)} e^{\delta_m}} = Y_k^{\text{obs}}$$
Por construção, o estimador calibrado elimina o viés de agregação gerado pela não-linearidade da softmax (desigualdade de Jensen), reproduzindo com exatidão os votos observados quando projetado sobre as próprias seções apuradas.

**Aproximação Agregada (Legado, `SwingEstimator.AGGREGATE`):**
Forma fechada sobre os totais agregados, com $B_k^{\text{obs}} = \sum_{i \in \text{Obs}} V_i \cdot b_{ik}^{(2022)}$:
$$\delta_k^{\text{nat}} = \ln\left(\frac{Y_k^{\text{obs}} + \epsilon}{Y_{\text{ref}}^{\text{obs}} + \epsilon}\right) - \ln\left(\frac{B_k^{\text{obs}} + \epsilon}{B_{\text{ref}}^{\text{obs}} + \epsilon}\right)$$
Mantida para auditoria histórica.

Aplica o deslocamento às seções pendentes via softmax estabilizada, e o $p_{jk}$ resultante substitui $b_{jk}^{(2022)}$ na [equação comum de totalização](#2-catálogo-de-modelos-de-referência-baselines):
$$p_{jk} = \frac{b_{jk}^{(2022)} \cdot e^{\delta_k^{\text{nat}}}}{\sum_{m} b_{jm}^{(2022)} \cdot e^{\delta_m^{\text{nat}}}}$$
- **Limitação:** Assume que o Brasil se move de maneira uniforme, sem capturar divergências regionais (ex.: o Nordeste oscilar numa direção diferente do Sul).

### Baseline 4: Swing Estadual com Encolhimento por Credibilidade (UF Swing with Shrinkage)
Calcula o swing individual de cada Unidade Federativa ($\delta_{u, k}$) via estimador calibrado e o encolhe em direção ao swing nacional por meio de um fator de credibilidade com **pseudo-contagem fixa**:
$$\delta_{u, k}^* = \lambda_u \cdot \delta_{u, k}^{\text{raw}} + (1 - \lambda_u) \cdot \delta_k^{\text{nat}}, \quad \text{onde } \lambda_u = \frac{N_u^{\text{obs}}}{N_u^{\text{obs}} + K}$$
Com $K = 30$ seções (hiperparâmetro `shrinkage_k`). O swing encolhido da UF $u(j)$ de cada seção pendente é aplicado pela mesma softmax do Baseline 3, e o $p_{jk}$ resultante substitui $b_{jk}^{(2022)}$ na [equação comum de totalização](#2-catálogo-de-modelos-de-referência-baselines):
$$p_{jk} = \frac{b_{jk}^{(2022)} \cdot e^{\delta_{u(j),k}^*}}{\sum_{m} b_{jm}^{(2022)} \cdot e^{\delta_{u(j),m}^*}}$$
Em UFs sem nenhuma seção apurada ($N_u^{\text{obs}} = 0$, logo $\lambda_u = 0$), usa-se $\delta_{u,k}^* = \delta_k^{\text{nat}}$.

**Natureza do estimador.** A fórmula equivale à média a posteriori de um modelo normal-normal em que a razão entre a variância por seção e a variância entre UFs é fixada a priori ($\sigma^2 / \tau^2 = K$), na forma de uma credibilidade linear do tipo Bühlmann com $K$ constante. **Não se trata de James-Stein nem de Empirical Bayes**: nesses estimadores o fator de encolhimento é estimado a partir da dispersão empírica entre os grupos (Efron & Morris, 1973; Efron & Hastie, 2016, cap. 7), o que não ocorre aqui.

**Limitações conhecidas.**
- $K$ não é estimado nem calibrado por backtest; ele não reage à dispersão observada entre as UFs em cada corte.
- $N_u^{\text{obs}}$ conta seções como se fossem amostras independentes. Como $K$ está na escala de seções, $\lambda_u \to 1$ rapidamente (ex.: 2.000 seções apuradas $\Rightarrow \lambda_u \approx 0{,}985$), e o viés de seleção da ordem de chegada das urnas não é atenuado pelo encolhimento.

---

## 3. Modelo Hierárquico Bayesiano V2 (MRP Calibrado com Encolhimento)

O **HierarchicalBayesianModelV2** é o modelo ativo padrão do Horizonte Eleitoral. Ele integra a metodologia de Regressão Multinível e Pós-Estratificação (**MRP**) com o estimador de **swing log-ratio calibrado** via Newton-Raphson, eliminando por completo o viés de agregação não-linear decorrente da desigualdade de Jensen.

### 3.1 Estimação de Swing Log-Ratio Calibrada

Para cada nível geográfico observado (região e UF), o vetor de deslocamento eleitoral $\boldsymbol{\delta} \in \mathbb{R}^K$ (com $\delta_{\text{ref}} = 0$) é obtido resolvendo via Newton-Raphson amortecido a equação de consistência:
$$\sum_{i \in \text{Obs}} V_i \frac{b_{ik}^{(2022)} \cdot e^{\delta_k}}{\sum_{m} b_{im}^{(2022)} \cdot e^{\delta_m}} = Y_k^{\text{obs}}$$
Diferente da aproximação linearizada aditiva (que gerava distorções no simplex e requeria cortes artificiais $\max(0, \cdot)$) ou da média log-ratio agregada fechada (que sofria do viés de Jensen $\mathbb{E}[g(X)] \neq g(\mathbb{E}[X])$ de até $+0{,}43\text{ pp}$), o estimador calibrado garante **reconstrução exata** dos votos observados e projeção estritamente válida no simplex $(0, 1)^K$ para qualquer urna não aberta.

### 3.2 Estrutura Hierárquica Multinível (MRP)

O modelo propaga o deslocamento eleitoral em estratos aninhados:

```mermaid
graph TD
    NAT["1. Efeito Nacional (MRP Ponderado por Censo)"] --> REG["2. Efeitos Regionais (5 Macro-Regiões, K_reg=30)"]
    REG --> UF["3. Efeitos Estaduais (27 UFs, K_uf=20)"]
    UF --> SEC["Seção Eleitoral Pendente (Projeção Softmax)"]
```

#### Nível 1: Efeito Nacional Ponderado por Pós-Estratificação (MRP)
Em vez de calcular a média aritmética simples das seções apuradas (que seria dominada pelas regiões que apuram mais rápido), o efeito nacional $\boldsymbol{\delta}_{\text{nat}}$ é sintetizado através da **pós-estratificação censitária regional ancorada no prior histórico**. Cada região observada é ponderada por sua credibilidade amostral $\lambda_r$ e pelo seu peso oficial no eleitorado nacional $\omega_r$, enquanto as regiões pendentes permanecem ancoradas no prior histórico nulo ($\boldsymbol{\delta}_0 = \mathbf{0}$):
$$\boldsymbol{\delta}_{\text{nat}} = \sum_{r \in \mathcal{R}_{\text{obs}}} \omega_r \cdot \lambda_r \cdot \boldsymbol{\delta}_{r}^{\text{raw}}, \quad \text{onde } \lambda_r = \frac{N_r^{\text{obs}}}{N_r^{\text{obs}} + K_{\text{reg}}}$$
Essa ancoragem impede que os primeiros boletins de urna de uma única macro-região rápida (como o Sul) imponham seu swing regional a 100% do país nos minutos iniciais da totalização.

Os pesos $\omega_r$ refletem a distribuição censitária oficial do eleitorado brasileiro junto ao TSE:
- **Sudeste:** 42,8%
- **Nordeste:** 27,1%
- **Sul:** 14,8%
- **Norte:** 8,0%
- **Centro-Oeste:** 7,0%

#### Nível 2: Encolhimento Regional para o Nacional
$$\lambda_r = \frac{N_r^{\text{obs}}}{N_r^{\text{obs}} + K_{\text{reg}}}, \quad \boldsymbol{\delta}_r = \lambda_r \boldsymbol{\delta}_{r}^{\text{raw}} + (1 - \lambda_r) \boldsymbol{\delta}_{\text{nat}} \quad (K_{\text{reg}} = 30)$$

#### Nível 3: Encolhimento Estadual para o Regional
$$\lambda_u = \frac{N_u^{\text{obs}}}{N_u^{\text{obs}} + K_{\text{uf}}}, \quad \boldsymbol{\delta}_u = \lambda_u \boldsymbol{\delta}_{u}^{\text{raw}} + (1 - \lambda_u) \boldsymbol{\delta}_{\text{reg}(u)} \quad (K_{\text{uf}} = 20)$$
Se uma UF ainda não possui seções apuradas no corte avaliado ($N_u^{\text{obs}} = 0$), herda deterministicamente $\boldsymbol{\delta}_{\text{reg}(u)}$.

#### Nível 4: Nível Municipal e Elasticidade Histórica (Opcional)
O modelo preserva compatibilidade com o índice de elasticidade municipal multi-ciclo 2018–2022 (`MunicipalElasticityIndex`, salvo em `data/real/elasticity_2018_2022.parquet`):
$$\lambda_m = \frac{N_m^{\text{obs}}}{N_m^{\text{obs}} + K_{\text{eff}}(m)}, \quad K_{\text{eff}}(m) = \frac{K_{\text{muni}}}{1 + s \cdot \text{vol}_m}$$
*Constatação empírica:* Nos marcos precoces (1% a 10%), a estimação de 5.570 parâmetros municipais isolados injeta ruído amostral devido à heterogeneidade espacial intra-municipal das primeiras urnas abertas. Por padrão, a projeção ativa adota a ancoragem robusta no estrato estadual (Nível 3), mantendo o Nível 4 disponível sob demanda via hiperparâmetro `shrinkage_muni`.

### 3.3 Condicionamento em Tempo Real do 2º Turno (`second_round_live.py`)

Durante a apuração ao vivo do 2º turno na CDN oficial do TSE (eleição `6258`), os boletins de urna individuais só são liberados após o encerramento da totalização, enquanto a API pública fornece em tempo real os consolidados agregados nacional (`br`) e estaduais (`27 UFs + ZZ`, arquivos `*-c0001-e006258-u.json`). Para eliminar qualquer desconexão entre votos reais do 2º turno e o catálogo analítico:

1. **Prior Territorial de Máxima Resolução (1º Turno 2026):** As 499.206 seções do catálogo são indexadas vetorizadamente em ~6.500 estratos homogêneos de Zona Eleitoral (`UF:município:zona`), utilizando a proporção bilateral homologada no 1º turno de 2026 ($b_{s,\text{PT}}^{(1\text{T})}, b_{s,\text{PL}}^{(1\text{T})}$) como covariável base (com fallback automático para 2022).
2. **Suficiência Estatística e Preservação Inteira Exata:** Como na equação de calibração por máxima verossimilhança $\sum_{z \in \text{Obs}_u} V_z p_z(\boldsymbol{\delta}_u) = \mathbf{Y}_u^{\text{obs}}$ o vetor oficial apurado $(Y_{u,\text{PL}}^{\text{obs}}, Y_{u,\text{PT}}^{\text{obs}})$ é estatística suficiente exata para $\boldsymbol{\delta}_u$, `allocate_stratum_observations` reconstrói os estratos observados preservando de forma inteira e inalterada os votos oficiais do TSE em cada UF (e no consolidado `BR` como fallback).
3. **Pós-Estratificação do Eleitorado Pendente por UF:** Os estratos ainda não abertos em cada UF ($E_{u}^{\text{pend}}$) recebem o swing estadual encolhido $\boldsymbol{\delta}_u$ do `HierarchicalBayesianModelV2` e propagam incerteza espacial no `MonteCarloSimulator`, convergindo com erro zero (`0,00 pp`) quando `pending_electorate == 0`.

---

## 4. Simulação Preditiva Estocástica de Monte Carlo

A estimativa pontual informa o valor esperado central, mas os operadores eleitorais e a sociedade precisam de **intervalos de credibilidade calibrados**.

O `MonteCarloSimulator` executa **2.000 sorteios estocásticos vetorizados** propagando incertezas em múltiplas escalas:

### 4.1 Incerteza Macro Nacional
A incerteza agregada nacional combina o Fator de Correção de População Finita (FPC, proporcional a $\sqrt{p_{\text{nat\_pend}}}$) com o decaimento da incerteza amostral inicial à medida que seções $N_{\text{obs}}$ são totalizadas:
$$\sigma_{\text{nat}} = 0.018 \cdot \sqrt{p_{\text{nat\_pend}}} \cdot \max\left(0.20, \frac{1}{\sqrt{1 + N_{\text{obs}} / 50}}\right)$$
Quando $p_{\text{nat\_pend}} \to 0$ (100% de apuração), $\sigma_{\text{nat}}$ converge monotonicamente e com exatidão a zero.

### 4.2 Incerteza Estadual Ponderada por Pareamento
Para cada estado $u$, o desvio-padrão a posteriori $\sigma_u$ é calibrado pela teoria de amostragem finita e ajustado pela qualidade média de pareamento geográfico das seções pendentes ($q_{\text{avg}} \in [1.0, 4.0]$):
$$\sigma_u = \frac{0.035}{\sqrt{N_u^{\text{obs}} / 20 + 1}} \cdot \sqrt{p_{u\_\text{pend}}} \cdot \sqrt{q_{\text{avg}}}$$
Onde $p_{u\_\text{pend}}$ representa a proporção de seções pendentes no estado $u$.

### 4.3 Sorteio e Geração dos Intervalos
Para cada sorteio $s \in \{1, \dots, 2000\}$:
1. Sorteiam-se perturbações normais multivariadas $\mathbf{z}_{\text{nat}}^{(s)} \sim \mathcal{N}(0, \sigma_{\text{nat}}^2)$ e $\mathbf{z}_u^{(s)} \sim \mathcal{N}(0, \sigma_u^2)$.
2. Os votos esperados das seções pendentes são integrados aos votos determinísticos das seções já apuradas.
3. Computa-se a distribuição empírica dos shares projetados.
4. Extraem-se os quantis de credibilidade de 90%:
   - **Limite Inferior:** $q_{05}$ (percentil 5%).
   - **Mediana Preditiva:** $q_{50}$ (percentil 50%).
   - **Limite Superior:** $q_{95}$ (percentil 95%).

### 4.4 Cálculo da Probabilidade de Segundo Turno
A regra constitucional brasileira estipula que um candidato vence em 1º turno apenas se obtiver mais de 50% dos votos válidos. A probabilidade preditiva de 2º turno é dada pela contagem direta dos sorteios:
$$P(\text{2º Turno}) = \frac{1}{S} \sum_{s=1}^{S} \mathbb{I}\left(\max_{k} \hat{p}_k^{(s)} \le 0.50\right)$$
Onde $\mathbb{I}(\cdot)$ é a função indicadora.

---

## 5. Cascata de Pareamento Geográfico (Geographic Matching)

Para saber qual é a base histórica de uma seção de 2026, o `GeographicMatcher` aplica uma cascata hierárquica em seis estágios, penalizando a incerteza estatística quando o pareamento é menos preciso:

```mermaid
flowchart TD
    M0["Seção de 2026"] --> C1{"Mesmo Local, Zona, Muni, UF?"}
    C1 -- Sim --> EXACT["Classe A: EXACT (Mult: 1.0x)"]
    C1 -- Não --> C2{"Distância Haversine <= 100m no mesmo município?"}
    C2 -- Sim --> COMPLEX["Classe B: SAME_COMPLEX (Mult: 1.2x)"]
    C2 -- Não --> C3{"Vizinhos até 5.000m no município?"}
    C3 -- Sim --> NEIGHBOR["Classe C: NEIGHBORING (Decaimento exp(-d/1000), Mult: 1.5x)"]
    C3 -- Não --> C4{"Outras seções na mesma Zona Eleitoral?"}
    C4 -- Sim --> ZONE["Classe D: SAME_ZONE (Mult: 2.0x)"]
    C4 -- Não --> C5{"Outras seções no mesmo Município?"}
    C5 -- Sim --> MUNI_FALLBACK["Classe E: SAME_MUNICIPALITY (Mult: 2.5x)"]
    C5 -- Não --> STATE_FALLBACK["Classe F: UNMATCHED (Média da UF, Mult: 4.0x)"]
```

A distância geodésica entre locais é calculada via fórmula de **Haversine**:
$$d = 2 R \arcsin\left(\sqrt{\sin^2\left(\frac{\Delta \phi}{2}\right) + \cos(\phi_1)\cos(\phi_2)\sin^2\left(\frac{\Delta \lambda}{2}\right)}\right)$$
Onde $R = 6.371.000\text{ m}$.

Quando não há correspondência exata de localidade mas existem seções vizinhas no mesmo município dentro do raio de tolerância ($d \le 5.000\text{ m}$), a composição histórica agregada é estimada por ponderação com decaimento exponencial suave da distância geodésica:
$$w_j = \exp\left(-\frac{d_j}{1000\text{ m}}\right)$$
Garantindo transição espacial contínua e sem singularidades numéricas.

---

## 6. Resultados Empíricos na Eleição de 2026 (499.206 Seções)

O sistema foi rigorosamente validado contra os **499.206 boletins de urna reais** da eleição presidencial de 2026, comparando o Modelo V1 com o Modelo V2 nos marcos percentuais oficiais:

| Marco (% Apurado) | Apurado Bruto (PT / PL) | Projeção V2 (PT / PL) | Intervalo V2 90% PT | Intervalo V2 90% PL | Erro Médio Absoluto (V2) |
|---|---|---|---|---|---|
| **2.0%** (17:06) | 35.77% / 55.14% | **45.25% / 46.99%** | [44.66%, 45.80%] | [46.41%, 47.52%] | **0.06 pp** |
| **5.0%** (17:15) | 35.62% / 55.35% | **45.32% / 46.87%** | [44.78%, 45.85%] | [46.34%, 47.38%] | **0.11 pp** |
| **10.0%** (17:30) | 35.71% / 55.30% | **45.28% / 46.92%** | [44.79%, 45.75%] | [46.46%, 47.37%] | **0.08 pp** |
| **20.0%** (18:00) | 36.20% / 54.89% | **45.20% / 46.98%** | [44.81%, 45.56%] | [46.62%, 47.32%] | **0.03 pp** |
| **50.0%** (19:30) | 38.77% / 52.61% | **45.17% / 47.01%** | [45.02%, 45.30%] | [46.87%, 47.13%] | **0.01 pp** |
| **80.0%** (21:00) | 42.46% / 49.36% | **45.16% / 47.02%** | [45.14%, 45.18%] | [47.00%, 47.04%] | **0.01 pp** |
| **100.0%** (22:00) | **45.16% / 47.03%** | **45.16% / 47.03%** | [45.16%, 45.16%] | [47.03%, 47.03%] | **0.00 pp (Gabarito)** |

### Destaques da Evidência Empírica
1. **Com apenas 2% do eleitorado apurado**, enquanto o apurado bruto exibia o PL com 55,14% contra 35,77% do PT (distorção regional de quase 20 pontos), o Modelo V2 consolidado com swing calibrado já projetava **PT 45.25% e PL 46.99%**, com um erro médio absoluto de apenas **0.06 pp** em relação ao resultado oficial final (45.16% vs 47.03%).
2. **O resultado final coube rigorosamente dentro da faixa de 90%** em todos os instantes temporais.
3. **Probabilidade de 2º Turno:** O sistema estimou **100% de probabilidade de 2º turno** desde o marco de 2%, alertando corretamente a sociedade de que a eleição presidencial não seria decidida na primeira rodada.

### 6.1 Métricas de Avaliação de Desempenho e Backtest

A calibração e a acurácia dos modelos preditivos são auditadas continuamente por meio de métricas determinísticas implementadas no módulo `backtest.metrics`:

1. **Erro Médio Absoluto (MAE):**
   Mede a discrepância média absoluta entre as proporções projetadas $\hat{p}_k$ e os resultados oficiais finais $p_k$ entre todos os grupos políticos:
   $$\text{MAE} = \frac{1}{K} \sum_{k=1}^K |\hat{p}_k - p_k|$$

2. **Viés Direcional do Líder (Leader Directional Bias):**
   Calcula o erro assinado exclusivamente sobre o candidato líder do pleito no resultado oficial final ($g_1 = \arg\max_k p_k$):
   $$\text{Bias} = \hat{p}_{g_1} - p_{g_1}$$
   *Justificativa teórica:* No simplex fechado de probabilidade ($\sum_k \hat{p}_k = \sum_k p_k = 1$), a média aritmética ingênua dos resíduos $\frac{1}{K} \sum (\hat{p}_k - p_k)$ é identicamente zero por definição algébrica. O viés direcional ancorado no líder captura com fidelidade sobre-estimações ($\text{Bias} > 0$) ou sub-estimações ($\text{Bias} < 0$) do candidato vencedor.

3. **Erro na Margem de Liderança (Lead Error):**
   Mede a precisão da vantagem projetada entre o primeiro e o segundo colocado ($g_1, g_2$):
   $$\text{Lead Error} = \left| (\hat{p}_{g_1} - \hat{p}_{g_2}) - (p_{g_1} - p_{g_2}) \right|$$

### 6.2 Validação Retroativa Oficial no 2º Turno de 2026 (5.716 Municípios TSE)

Com o encerramento de **100,00% das seções** do 2º turno presidencial de 2026 (Eleição `6258`, **Lula PT · 13 `51,79%` (`64.256.232` votos) vs Flávio Bolsonaro PL · 22 `48,21%` (`59.826.041` votos)** em `5.716` municípios e `28` abrangências estaduais/exterior), o módulo `backtest.second_round_validation` reconstitui retroativamente cada marco sob **Zero Data Leakage** estrito (`catalog_2026_2t.parquet`), respeitando integralmente a cronologia real de 25/10/2026 — na qual a divulgação do TSE permaneceu **estacionada em `0,25%` entre `17h07` e `19h00` BRT** devido à prorrogação do horário de votação pelo STF, retomando o fluxo nacional somente **após as `19h00` BRT**:

| Marco (% Eleitorado) | Horário BRT | Urna Bruta TSE (PT / PL) | Erro Urna Bruta | Projeção V2 (PT / PL) | Intervalo V2 90% PT | MAE Modelo V2 | Cobertura IC 90% |
|---|---|---|---|---|---|---|---|
| **0,25%** | 17:07–19:00 | 53,65% / 46,35% | 1,86 pp | *Preliminar (< 2% · Suspenso STF)* | — | — | — |
| **1,0%** | 19:10 | 67,14% / 32,86% | 15,35 pp | *Preliminar (< 2,0%)* | — | — | — |
| **2,0%** | 19:20 | 69,00% / 31,00% | 17,21 pp | **50,94% / 49,06%** | [50,45%, 51,45%] | **0,85 pp** | Não |
| **5,0%** | 19:30 | 58,92% / 41,08% | 7,13 pp | **51,70% / 48,30%** | [51,41%, 52,01%] | **0,09 pp** | Sim |
| **15,0%** | 19:44 | 50,57% / 49,43% | 1,22 pp | **51,73% / 48,27%** | [51,55%, 51,94%] | **0,06 pp** | Sim |
| **25,0%** | 19:55 | 48,98% / 51,02% *(PL líder)* | 2,81 pp | **51,68% / 48,32%** | [51,56%, 51,82%] | **0,11 pp** | Sim |
| **30,0%** | 20:00 | 49,15% / 50,85% *(PL líder)* | 2,64 pp | **51,70% / 48,30%** | [51,58%, 51,82%] | **0,09 pp** | Sim |
| **50,0%** | 20:17 | 49,86% / 50,14% *(PL líder)* | 1,93 pp | **51,73% / 48,27%** | [51,66%, 51,79%] | **0,06 pp** | Sim |
| **60,0%** | 20:25 | 50,38% / 49,62% *(Virada PT)* | 1,41 pp | **51,75% / 48,25%** | [51,69%, 51,80%] | **0,04 pp** | Sim |
| **80,0%** | 20:42 | 51,07% / 48,93% | 0,72 pp | **51,77% / 48,23%** | [51,74%, 51,79%] | **0,02 pp** | Sim |
| **90,0%** | 20:52 | 51,34% / 48,66% | 0,45 pp | **51,77% / 48,23%** | [51,76%, 51,79%] | **0,02 pp** | Sim |
| **100,0%** | 23:21 | **51,79% / 48,21%** | **0,00 pp** | **51,79% / 48,21%** | [51,79%, 51,79%] | **0,00 pp** | Sim |

- **Imunidade à "Falsa Virada" de Apuração (`19h46 – 20h24`):** Durante os 38 minutos em que Flávio Bolsonaro liderou a urna bruta (`20%` a `50%` apurado, com `PL` chegando a `51,02%` às `19h55` enquanto a Bahia prorrogada até as 19h iniciava sua transmissão), o Modelo V2 nunca se deixou enganar pelo viés geográfico e manteve **Lula (PT) projetado entre `51,68%` e `51,73%`** com erro inferior a **`0,11 pp`**.
- **Calibração Probabilística:** O modelo acertou o vencedor em **100% dos marcos (`>= 2%`)** e manteve o resultado oficial final (`51,79%`) dentro do intervalo de credibilidade de 90% em **95,2% das ondas** (`20/21`, sendo `100%` de cobertura contínua de `5%` a `100%`).

---

## 7. Diretrizes de Comunicação e Ética Editorial

O Horizonte Eleitoral adota salvaguardas éticas fundamentais:
- **A previsão não é apuração oficial:** A única autoridade com poder homologatório de votos é o Tribunal Superior Eleitoral.
- **Transparência das Incertezas:** Toda estimativa publicada é acompanhada obrigatoriamente da faixa preditiva $[q_{05}, q_{95}]$ e de indicadores de cobertura.
- **Proibição de Declaração Precoce de Vitória:** Nenhuma vitória é projetada pelo algoritmo a menos que o limite inferior do líder ($q_{05}$) supere com significância estatística o limite superior do segundo colocado ($q_{95}$).
