# Revisão de Performance — Aba `Peers (Tabela)`

Data: 2026-04-16  
Escopo: diagnóstico de latência da aba `Peers (Tabela)` com foco em fluxo de execução, tempos medidos, gargalos confirmados e plano de otimização sem alterar a lógica financeira.

## Resumo Executivo

- O gargalo principal da aba **não** está na montagem da tabela, nem na renderização HTML, nem nos cálculos derivados da própria grade.
- O problema dominante está no **carregamento do contexto e do slice do `critical_screens`**, especificamente no caminho que suplementa `Core Funding` e `Crédito / Captações` em runtime.
- A abertura fria da aba, antes mesmo de o usuário interagir, passa por [_get_peers_filters_context](../app1.py) em [app1.py:12549](../app1.py:12549), que hoje chama [_carregar_cache_relatorio_slice](../app1.py) em [app1.py:6656](../app1.py:6656) **sem filtros**.
- Esse loader, ao carregar `critical_screens`, sempre entra em [load_critical_screens_slice](../utils/ifdata_cache/critical_screens.py:2018), que por sua vez sempre chama [_supplement_runtime_missing_funding](../utils/ifdata_cache/critical_screens.py:2194).
- A suplementação faz um caminho caro: carrega `passivo` e `principal` inteiros e depois canonicaliza nomes com [canonicalize_institution_dataframe](../utils/ifdata_cache/institutions.py:326), que usa `DataFrame.apply(axis=1)` linha a linha.
- Evidência central:
  - contexto da aba (`_get_peers_filters_context`) em cold start: **71,0s**
  - mesmo contexto com cache quente: **0,0s**
  - leitura mínima equivalente para montar os dropdowns diretamente do parquet (`Instituição`, `Período`): **0,013s**
- A latência do slice filtrado para 1 banco x 3 períodos e 5 bancos x 3 períodos continua alta (**~9–13s cold**) porque o filtro por instituição só é aplicado **depois** da canonicalização do `passivo`.
- Todo o restante da aba é barato:
  - cálculo da tabela: **0,002–0,007s**
  - status analítico: **0,012–0,073s**
  - HTML: **0,000–0,003s**
- Conclusão: a causa raiz é **estrutural e confirmada**. A aba está acoplada a uma suplementação pesada de funding em runtime, inclusive para tarefas que não precisam dela.

## Metodologia

1. Mapeamento do fluxo real da aba no código.
2. Medição por etapa com scripts controlados em Python usando os próprios helpers da aplicação.
3. Separação entre:
   - carga de contexto de filtros
   - carga do slice curado
   - suplementação de funding
   - cálculo da tabela
   - status/tooltip
   - renderização HTML
4. Comparação entre cold path e warm path.
5. Verificação explícita de custo estrutural por:
   - período
   - quantidade de peers
   - tamanho do dataframe final

## Fluxo de Execução Real da Aba

### 1. Entrada do usuário e contexto inicial

Ramo principal da aba:
- [app1.py:15476](../app1.py:15476) `elif menu == "Peers (Tabela)"`

Blocos executados ao abrir a aba:
- `_garantir_cache_telas_criticas("Peers (Tabela)")` em [app1.py:15489](../app1.py:15489)
- `_get_peers_filters_context(_cache_version_token("critical_screens"))` em [app1.py:15498](../app1.py:15498)
- montagem dos dropdowns de bancos e períodos em [app1.py:15506](../app1.py:15550)

### 2. Carregamento do slice quando o usuário já tem seleção

Com bancos/períodos escolhidos:
- expansão de períodos para cálculo comparativo em [app1.py:15568](../app1.py:15576)
  - períodos exibidos
  - mesmo trimestre do ano anterior
  - dezembro do ano anterior
- carga do slice curado:
  - [_carregar_cache_relatorio_slice](../app1.py:6656) chamada em [app1.py:15584](../app1.py:15584)

### 3. Cálculo e preparação da tabela

Depois do slice:
- [_preparar_metricas_extra_peers_from_slice](../app1.py:8206) em [app1.py:15594](../app1.py:15594)
- [_montar_tabela_peers](../app1.py:8231) em [app1.py:15604](../app1.py:15604)
- [_build_peers_status_lookup](../app1.py:9124) em [app1.py:15618](../app1.py:15618)
- [_merge_peers_analytical_tooltips](../app1.py:9145) em [app1.py:15625](../app1.py:15625)
- [_render_peers_table_html](../app1.py:8448) em [app1.py:15629](../app1.py:15629)
- `st.markdown(html_tabela, unsafe_allow_html=True)` em [app1.py:15647](../app1.py:15647)

### 4. Exportações

Os exports **não** entram no caminho interativo inicial:
- só são preparados após clique em `Preparar arquivos de exportação` em [app1.py:15670](../app1.py:15670)
- portanto não são causa da lentidão ao abrir a aba

## Evidência de Execução e Tempos Medidos

### A. Tamanho real da base `critical_screens`

Parquet local:
- caminho: `data/cache/critical_screens/dados.parquet`
- tamanho em disco: **13 MB**
- linhas: **60.578**
- colunas: **79**
- períodos: **44**
- instituições: **3.146**

Leitura mínima do parquet, só com `Instituição` e `Período`:
- `dataset.to_table(columns=["Instituição","Período"])`: **0,0027s**
- `to_pandas()`: **0,0020s**
- `unique + sort`: **0,0082s**
- total para montar dropdowns sem suplementação: **0,0129s**

### B. Contexto da aba antes da seleção do usuário

Função medida:
- [_get_peers_filters_context](../app1.py:12549)

Resultado:
- cold start: **71,001s**
- warm cache: **0,0s**

Diagnóstico:
- para montar apenas a lista de bancos e períodos, a aba hoje paga o custo de abrir o `critical_screens` inteiro e suplementar funding em runtime.

### C. Slice filtrado da aba

#### Cenário 1 — 1 banco, 1 período

Parâmetros:
- banco: `ITAU - PRUDENCIAL`
- período exibido: `4/2025`

Resultado:
- `_carregar_cache_relatorio_slice(... critical_screens ...)` cold: **5,494s**
- mesmo call com cache quente: **0,0s**
- dataframe final: **3 linhas**
- memória final do slice: **0,003 MB**

#### Cenário 2 — 1 banco, 3 períodos

Parâmetros:
- banco: `ITAU - PRUDENCIAL`
- períodos exibidos: `4/2025`, `3/2025`, `2/2025`
- períodos internos expandidos: `2/2024`, `2/2025`, `3/2024`, `3/2025`, `4/2023`, `4/2024`, `4/2025`

Resultado:
- `_carregar_cache_relatorio_slice(... critical_screens ...)` cold: **12,899s**
- cache quente: **0,0s**
- dataframe final: **7 linhas**
- memória final do slice: **0,007 MB**

#### Cenário 3 — 5 peers, 3 períodos

Parâmetros:
- bancos:
  - `ITAU - PRUDENCIAL`
  - `BRADESCO - PRUDENCIAL`
  - `SANTANDER - PRUDENCIAL`
  - `CAIXA ECONÔMICA FEDERAL - PRUDENCIAL`
  - `BB - PRUDENCIAL`
- períodos exibidos: `4/2025`, `3/2025`, `2/2025`

Resultado:
- `_carregar_cache_relatorio_slice(... critical_screens ...)` cold: **9,462s**
- cache quente: **0,0s**
- dataframe final: **35 linhas**

Observação importante:
- o custo não cresce muito com o número de peers porque o filtro por instituição é aplicado tarde demais, depois da canonicalização do `passivo`.

### D. Suplementação de funding isolada

Funções medidas:
- [_load_runtime_passivo_support](../utils/ifdata_cache/critical_screens.py:2075)
- [_supplement_runtime_missing_funding](../utils/ifdata_cache/critical_screens.py:2194)

#### Custo por recorte

1 banco, 1 período:
- `support_load`: **1,963s**
- `supplement_total`: **1,721s**

1 banco, 3 períodos:
- `support_load`: **4,864s**
- `supplement_total`: **5,234s**

1 banco, 7 períodos internos (cenário real da aba):
- `support_load`: **9,214s**
- shape de saída: **7 x 7**

5 bancos, 7 períodos internos:
- `support_load`: **9,265s**
- shape de saída: **35 x 7**

Interpretação:
- o custo é praticamente o mesmo para 1 peer e 5 peers porque a suplementação depende principalmente do **número de períodos expandidos**, não do número final de peers.

### E. Subetapas internas da suplementação

Medição em 5 peers / 3 períodos exibidos:

- `manager.carregar("passivo")`: **0,036s**
- `manager.carregar("principal")`: **0,005s**
- filtro por período no `passivo`: **0,002s**
- `canonicalize_institution_dataframe(passivo, extra_frames=(principal,))`: **4,101s**
- filtro final por instituição: **0,0s**
- loop final de resolução de funding: **0,003s**

Volume nesse ponto:
- `passivo` bruto: **60.658 x 34** | **26,316 MB**
- `principal` bruto: **60.658 x 19** | **19,445 MB**
- `passivo` já filtrado por 3 períodos: **4.179 x 34**
- `passivo` depois da canonicalização: **4.179 x 34**
- `passivo` depois de filtrar 5 instituições: **15 x 34**

Conclusão:
- a maior parte do custo está em **canonicalizar 4.179 linhas para depois ficar com 15**.

### F. Renderização e pós-processamento da tabela

#### 1 banco / 3 períodos
- `_preparar_metricas_extra_peers_from_slice`: **0,003s**
- `_montar_tabela_peers`: **0,003s**
- `_build_peers_status_lookup`: **0,019s**
- `_merge_peers_analytical_tooltips`: **0,000s**
- `_render_peers_table_html`: **0,001s**
- HTML gerado: **17.897 chars**

#### 5 peers / 3 períodos
- `_preparar_metricas_extra_peers_from_slice`: **0,003s**
- `_montar_tabela_peers`: **0,007s**
- `_build_peers_status_lookup`: **0,073s**
- `_merge_peers_analytical_tooltips`: **0,000s**
- `_render_peers_table_html`: **0,003s**
- HTML gerado: **58.959 chars**

Conclusão:
- tabela, tooltips, formatação e HTML **não são o gargalo**.

## Causas Raiz Priorizadas

### 1. Causa raiz principal — contexto da aba aciona carga integral e suplementação de funding sem necessidade

Local:
- [app1.py:12549](../app1.py:12549) `_get_peers_filters_context`
- [app1.py:6656](../app1.py:6656) `_carregar_cache_relatorio_slice`
- [utils/ifdata_cache/critical_screens.py:2018](../utils/ifdata_cache/critical_screens.py:2018) `load_critical_screens_slice`
- [utils/ifdata_cache/critical_screens.py:2194](../utils/ifdata_cache/critical_screens.py:2194) `_supplement_runtime_missing_funding`

Evidência:
- para montar só `bancos_todos` e `periodos_disponiveis`, o código lê o `critical_screens` inteiro e aciona suplementação de funding.
- medição:
  - caminho atual do contexto: **71,001s**
  - leitura mínima equivalente só com duas colunas: **0,0129s**

Impacto:
- a aba pode parecer “travada” antes mesmo da primeira interação do usuário.

### 2. Causa raiz secundária — suplementação de funding faz trabalho pesado antes de filtrar as instituições selecionadas

Local:
- [utils/ifdata_cache/critical_screens.py:2075](../utils/ifdata_cache/critical_screens.py:2075) `_load_runtime_passivo_support`

Evidência:
- fluxo atual:
  1. carrega `passivo` e `principal` inteiros
  2. filtra por período
  3. canonicaliza todo o `passivo` filtrado
  4. só então filtra as instituições selecionadas
- no cenário 5 peers / 3 períodos:
  - canonicaliza **4.179** linhas
  - para entregar apenas **15** linhas úteis

Impacto:
- a latência passa a depender muito mais do número de períodos expandidos do que do número de peers efetivamente exibidos.

### 3. Causa raiz secundária — canonicalização linha a linha com `DataFrame.apply(axis=1)`

Local:
- [utils/ifdata_cache/institutions.py:326](../utils/ifdata_cache/institutions.py:326) `canonicalize_institution_dataframe`

Evidência:
- a função resolve nome por linha usando `out.apply(_resolve_name, axis=1)`
- medição:
  - em `4.179` linhas: **4,101s**
  - em `60.658` linhas: **>30s** (timeout)

Impacto:
- é o principal componente interno do custo da suplementação.

### 4. Causa secundária — expansão silenciosa do conjunto de períodos

Local:
- [app1.py:15568](../app1.py:15568) a [app1.py:15576](../app1.py:15576)

Evidência:
- ao escolher 3 períodos na UI, a aba passa a trabalhar com **7 períodos internos**:
  - períodos exibidos
  - YoY dos períodos
  - dezembro do ano anterior para ROE
- medição da suplementação:
  - 1 período: **1,963s**
  - 3 períodos: **4,864s**
  - 7 períodos: **9,214s**

Impacto:
- o usuário percebe “3 períodos”, mas o pipeline paga custo equivalente a 7.

## Hipóteses Consideradas e Rejeitadas

### “A tabela HTML é o problema”
Rejeitada.

Evidência:
- HTML 5 peers / 3 períodos: **0,003s**
- string final: ~**59 KB**

### “Os cálculos analíticos dos indicadores são o problema”
Rejeitada para o hot path atual.

Evidência:
- `_montar_tabela_peers`: **0,002–0,007s**
- `_preparar_metricas_extra_peers_from_slice`: **0,003s**

### “As exportações estão atrasando a aba”
Rejeitada.

Evidência:
- exports só são gerados depois do clique em `Preparar arquivos de exportação`
- o código já deixa isso fora do tempo interativo inicial

### “O warm cache não funciona”
Rejeitada.

Evidência:
- `_get_peers_filters_context`: **71,001s -> 0,0s**
- `_carregar_cache_relatorio_slice` filtrado: **5–13s -> 0,0s**

Problema real:
- o warm path funciona; o cold path é que está estruturalmente caro demais.

## Diagnóstico Consolidado

### Causa raiz confirmada

A aba `Peers (Tabela)` está lenta principalmente porque:

1. o contexto inicial dos filtros é construído a partir de uma leitura integral do `critical_screens`;
2. esse loader sempre suplementa funding em runtime;
3. a suplementação carrega `passivo` e `principal` grandes, canonicaliza demais e só depois recorta as instituições;
4. a canonicalização é feita com `apply(axis=1)`, que custa segundos mesmo em recortes médios;
5. o usuário paga esse custo mesmo quando a aba só precisa listar bancos e períodos.

### Causa quase confirmada adicional

O slice frio da aba poderia ficar muito mais rápido se:
- a suplementação de funding fosse pré-materializada no próprio `critical_screens`, ou
- a suplementação runtime usasse slices prunados de `passivo`/`principal` em vez de dataframes completos.

## Plano de Correção Incremental

### P0 — Separar o contexto de filtros da suplementação de funding

Mudança:
- reescrever [_get_peers_filters_context](../app1.py:12549) para:
  - ler só `Instituição` e `Período` do parquet `critical_screens`, ou
  - consumir isso de metadata pronta
- proibir que esse caminho chame `_supplement_runtime_missing_funding`

Ganho esperado:
- abertura fria da aba deve sair da faixa de **71s** para algo próximo de **0,02s–0,2s**

Risco:
- baixo

Validação:
- dropdowns de bancos/períodos iguais aos atuais
- nenhuma diferença numérica na tabela final

Arquivos:
- [app1.py](../app1.py)
- opcionalmente [utils/ifdata_cache/critical_screens.py](../utils/ifdata_cache/critical_screens.py)

### P1 — Tirar o filtro de instituições para antes da canonicalização do support de funding

Mudança:
- em [_load_runtime_passivo_support](../utils/ifdata_cache/critical_screens.py:2075), filtrar por instituição antes de canonicalizar, usando:
  - nomes já canônicos
  - variantes registradas no metadata (`canonical_variants`, `raw_to_canonical`)
  - ou um mapa leve instituição->conglomerado

Ganho esperado:
- reduzir drasticamente o custo do slice frio
- cenário 5 peers / 7 períodos não deveria precisar canonicalizar milhares de linhas para entregar 35

Risco:
- médio, porque mexe em matching institucional

Validação:
- comparar `Core Funding` e `Crédito / Captações` em amostra de peers antes/depois
- garantir que nenhum peer válido some por erro de matching

Arquivos:
- [utils/ifdata_cache/critical_screens.py](../utils/ifdata_cache/critical_screens.py)
- [utils/ifdata_cache/institutions.py](../utils/ifdata_cache/institutions.py)

### P1 — Substituir `canonicalize_institution_dataframe(... apply(axis=1))` por resolução vetorizada

Mudança:
- remover `apply(axis=1)` do caminho quente
- preferir:
  - normalização vetorizada da coluna
  - mapeamento por dicionário
  - tratamento separado apenas das exceções/placeholder

Ganho esperado:
- cortar a maior parte dos **4,1s** hoje gastos para canonicalizar `4.179` linhas

Risco:
- médio

Validação:
- igualdade do nome canônico final para amostra ampla de instituições
- sem regressão nas abas que usam o mesmo pipeline de canonicalização

Arquivos:
- [utils/ifdata_cache/institutions.py](../utils/ifdata_cache/institutions.py)

### P2 — Evitar suplementação runtime quando `critical_screens` já estiver íntegro

Mudança:
- em [load_critical_screens_slice](../utils/ifdata_cache/critical_screens.py:2018), só chamar `_supplement_runtime_missing_funding` se o slice realmente contiver `Core Funding`/`Crédito / Captações` faltantes

Ganho esperado:
- quando o bundle já vier íntegro, o slice filtrado cai para custo quase puro de parquet

Risco:
- baixo

Validação:
- medir slices com e sem missing
- garantir que casos faltantes continuem sendo recompostos corretamente

Arquivos:
- [utils/ifdata_cache/critical_screens.py](../utils/ifdata_cache/critical_screens.py)

### P2 — Fazer `_load_runtime_passivo_support` carregar slices, não caches completos

Mudança:
- trocar `manager.carregar("passivo")` e `manager.carregar("principal")` integrais por leitura prunada por `Período` e, quando possível, `Instituição`

Ganho esperado:
- menos RAM transitória
- menos cópias de dataframes

Risco:
- médio

Validação:
- shape e valores de support idênticos

Arquivos:
- [utils/ifdata_cache/critical_screens.py](../utils/ifdata_cache/critical_screens.py)
- possivelmente helpers de leitura em `manager`/caches

### P3 — Opcional: metadata canônica pronta para dropdowns

Mudança:
- materializar em `metadata.json` do `critical_screens`:
  - `instituicoes_disponiveis`
  - `periodos_disponiveis`

Ganho esperado:
- abertura inicial da aba praticamente instantânea, sem ler parquet algum

Risco:
- baixo

Validação:
- metadata coerente com parquet materializado

Arquivos:
- [utils/ifdata_cache/critical_screens.py](../utils/ifdata_cache/critical_screens.py)
- [app1.py](../app1.py)

## Estratégia de Testes

### Testes de correção numérica

1. Regressão da aba Peers para amostra de 5 bancos x 3 períodos:
   - `Core Funding*`
   - `Crédito / Captações`
   - `Carteira de Crédito*`
   - `Perda Esperada / Carteira`
   - `CET1`
   - `Basileia`

2. Paridade entre:
   - `Snapshot`
   - `Peers (Tabela)`
   - `critical_screens`

3. Amostras com instituições placeholder / aliases / prudencial

### Testes de performance

1. `test_peers_filters_context_does_not_trigger_funding_support`
2. `test_peers_filtered_slice_cold_under_threshold`
3. `test_peers_filtered_slice_warm_under_threshold`
4. `test_runtime_support_filters_institution_before_canonicalization`

### Testes de consistência funcional

1. Mesmos bancos/períodos nos dropdowns antes/depois
2. Mesma ordenação
3. Mesma tabela HTML em conteúdo numérico
4. Exportações preservadas

## Atualização — Primeira Rodada de Otimização Implementada

As prioridades `P0` e `P1` foram implementadas nesta rodada.

### Mudanças aplicadas

1. **Contexto leve da Peers**
   - `_get_peers_filters_context` deixou de chamar o slice pesado de `critical_screens`
   - o contexto agora lê apenas `Instituição` e `Período` do parquet curado

2. **Filtro antecipado no suporte de funding**
   - `_load_runtime_passivo_support` agora:
     - filtra `principal` por períodos
     - resolve códigos candidatos das instituições selecionadas
     - poda `passivo` por código/nome antes da canonicalização

3. **Testes de regressão**
   - a montagem dos filtros não pode mais usar o slice pesado
   - o suporte de funding precisa chegar reduzido à canonicalização

### Before / After medido

| Cenário | Antes | Depois | Ganho |
|---|---:|---:|---:|
| Contexto da aba (`_get_peers_filters_context`) cold | 71,001s | 0,053s | ~1339x |
| `_load_runtime_passivo_support` 1 peer / 7 períodos internos | 9,214s | 1,729s | ~5,3x |
| `_load_runtime_passivo_support` 5 peers / 7 períodos internos | 9,265s | 1,594s | ~5,8x |
| Slice `critical_screens` cold 1 peer / 1 período | 5,494s | 1,596s | ~3,4x |
| Slice `critical_screens` cold 1 peer / 3 períodos | 12,899s | 1,452s | ~8,9x |
| Slice `critical_screens` cold 5 peers / 3 períodos | 9,462s | 1,448s | ~6,5x |

### Leitura técnica do resultado

- O maior gargalo da aba foi praticamente removido: o usuário não precisa mais esperar o custo da suplementação de funding só para ver filtros.
- O cold path do slice deixou a faixa de `~9–13s` e caiu para `~1,45–1,60s` nos cenários medidos.
- O custo residual segue concentrado na canonicalização/suplementação de funding, mas agora sobre um universo muito menor.
- A próxima fronteira, se ainda necessária, é a vetorização de `canonicalize_institution_dataframe` ou uma pré-materialização mais completa do funding no curado.

## Atualização — Segunda Rodada de Otimização Implementada

A fronteira residual identificada na rodada anterior estava em `_build_selected_institution_code_map`, que ainda canonicalizava muitos nomes do `principal` desnecessariamente.

### Mudanças aplicadas

1. **Mapa direto de códigos a partir do `principal`**
   - quando o `principal` já traz nomes canônicos iguais aos selecionados na aba, o código agora:
     - filtra o `principal` por nome direto
     - constrói o `code_map` sem canonicalizar milhares de nomes
   - a canonicalização nominal virou apenas fallback raro

2. **Canonicalização rápida do suporte**
   - `_canonicalize_support_passivo_dataframe` passou a resolver linhas do `passivo` por `CodInst` de forma vetorizada
   - o caminho lento `canonicalize_institution_dataframe(... apply(axis=1))` fica restrito às sobras não resolvidas

### Before / After medido

| Cenário | Antes da 2ª rodada | Depois da 2ª rodada | Ganho |
|---|---:|---:|---:|
| `_build_selected_institution_code_map` (5 peers / 7 períodos internos) | 1,533s | 0,002s | ~766x |
| `_load_runtime_passivo_support` 1 peer / 7 períodos internos | 1,729s | 0,045s | ~38x |
| `_load_runtime_passivo_support` 5 peers / 7 períodos internos | 1,594s | 0,048s | ~33x |
| Slice `critical_screens` cold 1 peer / 1 período | 1,596s | 0,226s | ~7,1x |
| Slice `critical_screens` cold 1 peer / 3 períodos | 1,452s | 0,063s | ~23x |
| Slice `critical_screens` cold 5 peers / 3 períodos | 1,448s | 0,070s | ~20,7x |

### Leitura técnica do resultado

- A suplementação de funding deixou de ser um gargalo perceptível na `Peers (Tabela)`.
- O contexto da aba já estava em `0,053s`; agora o slice frio também caiu para faixa de `~0,06–0,23s` nos cenários medidos.
- Neste ponto, a aba deixou de depender de recomputação cara para abrir e passou a operar em cima de um recorte curado efetivamente leve.
- A próxima otimização só faria sentido se surgir nova evidência de latência fora do Python, por exemplo custo de navegador/DOM ou alguma rota específica de export.

## Medição Final — Caminho End-to-End da Aba

Depois das duas rodadas, o caminho Python completo da `Peers (Tabela)` ficou assim:

| Cenário | Slice | Métricas extra | Montagem tabela | UI/tooltip/html | Total Python |
|---|---:|---:|---:|---:|---:|
| 1 peer / 3 períodos | 0,232s | 0,002s | 0,002s | 0,015s | 0,251s |
| 5 peers / 3 períodos | 0,071s | 0,003s | 0,007s | 0,063s | 0,143s |

Leitura técnica:
- o hot path de dados deixou de ser o problema dominante da aba;
- a renderização Python/HTML também ficou pequena;
- se ainda houver lentidão percebida em uso real, a hipótese principal deixa de ser backend de dados e passa a ser:
  - custo de browser/DOM do Streamlit,
  - latência de sessão/rede do front,
  - ou alguma etapa fora do fluxo principal medido aqui.

### Ajuste final aplicado

- a `Memória de cálculo — Peers (Tabela)` passou a ser lazy:
  - antes, o painel montava `tabs + dataframe` para todos os bancos sempre;
  - no cenário de 5 peers isso custava ~`0,309s` mesmo sem o usuário abrir ou usar a memória;
  - agora o carregamento detalhado só acontece quando o usuário ativa explicitamente a memória de cálculo.

## Conclusão

O diagnóstico é claro:

- A aba `Peers (Tabela)` não está lenta por causa da tabela.
- Ela está lenta porque paga um custo pesado de suplementação de funding em runtime no lugar errado do fluxo.
- O maior erro arquitetural hoje é usar o mesmo loader pesado tanto para:
  - abrir dropdowns
  - quanto montar o slice final da tabela

Prioridade recomendada:
1. cortar o contexto inicial da suplementação
2. filtrar instituições antes da canonicalização
3. vetorização da canonicalização
4. suplementação runtime apenas quando realmente necessária

Nenhuma dessas mudanças exige sacrificar consistência numérica. Ao contrário: o caminho correto é deixar a aba cada vez mais dependente de uma base curada pronta e cada vez menos dependente de recomputação pesada em tempo de abertura.

## Revalidação — 2026-04-17 (Rodada de Auditoria)

Data: 2026-04-17  
Escopo: revisão profunda, ponta a ponta, da aba `Peers (Tabela)` para confirmar que as rodadas P0/P1/P2 estão aplicadas, medir o caminho real hoje e identificar resíduos.

### Confirmação do código em produção

Inspeção do `app1.py` (linhas 15478–15879) e `utils/ifdata_cache/critical_screens.py`:

| Item | Local | Status |
|---|---|---|
| Contexto leve `load_critical_screens_filters_context` | [critical_screens.py:2075–2124](../utils/ifdata_cache/critical_screens.py:2075) | ✅ P0 aplicado: lê só `Instituição`/`Período`, sem suplementação |
| `_get_peers_filters_context` cacheado `@st.cache_data(ttl=900)` | [app1.py:12561–12564](../app1.py:12561) | ✅ decorador presente |
| Slice filtrado `_carregar_cache_relatorio_slice` | [app1.py:6664–6720](../app1.py:6664) | ✅ `@st.cache_data(ttl=3600)` + filtro PyArrow |
| Pré-filtro de instituições no suporte | [critical_screens.py:2299–2315](../utils/ifdata_cache/critical_screens.py:2299) | ✅ P1 aplicado: poda `passivo` por nome/`CodInst` antes de canonicalizar |
| Canonicalização vetorizada via `CodInst` | [critical_screens.py:2223–2229](../utils/ifdata_cache/critical_screens.py:2223) | ✅ P2 aplicado: `map(selected_code_map)` resolve a maioria |
| Suplementação só quando há NaN | [critical_screens.py:2398–2404](../utils/ifdata_cache/critical_screens.py:2398) | ✅ guarda condicional |
| Memória de cálculo lazy | [app1.py:15769–15814](../app1.py:15769) | ✅ `st.toggle` dentro de expander `expanded=False` |
| Exports on-demand | [app1.py:15673–15711](../app1.py:15673) | ✅ só após `st.button("Preparar arquivos…")` |
| Mini-glossário e painel de diagnóstico | [app1.py:15752–15855](../app1.py:15752) | ✅ dentro de expander e só em `modo_diagnostico` |

Resíduos confirmados:

- `canonicalize_institution_dataframe` ainda usa `apply(axis=1)` ([institutions.py:326–363](../utils/ifdata_cache/institutions.py:326)), mas hoje só processa o resíduo não resolvido pelo `CodInst` (em regime permanente, `0` linhas).
- `build_institution_to_conglomerate_map` é chamado duas vezes dentro do `load_critical_screens_slice` (linhas 2046 e 2068). Inofensivo porque é `@lru_cache(maxsize=8)` ([institutions.py:222](../utils/ifdata_cache/institutions.py:222)), mas é redundância que pode ser removida.

### Medições de hoje (2026-04-17)

Ambiente: container limpo, sem `data/cache/passivo` e sem `data/cache/critical_screens` pré-materializados. Bootstrap do `critical_screens` é feito a partir de `data/bundled/critical_screens/dados.parquet` (13,85 MB).

#### Pré-condições medidas

- Parquet `critical_screens` após bootstrap: 13,85 MB, 60.658 linhas, 79 colunas, 3.146 instituições, 44 períodos.
- Parquet `passivo` baixado sob demanda pelo `CacheManager` do GitHub Releases na primeira chamada a `manager.carregar("passivo")`. Tamanho: 4,7 MB (60.658 × 34 colunas).
- Parquet `principal` local: 5,1 MB (60.658 × 19 colunas).

#### A. Leitura mínima (piso de performance)

| Etapa | Tempo |
|---|---:|
| open dataset + schema | 0,002s |
| `to_table(["Instituição","Período"])` | 0,008s |
| `to_pandas` | 0,001s |
| `unique + sort` | 0,004s |
| **Total piso para dropdowns** | **0,016s** |

#### B. `load_critical_screens_filters_context`

| Execução | Tempo |
|---|---:|
| cold | 0,060s |
| warm (reexecução) | 0,031s |
| bancos_todos | 3.146 |
| períodos_disponiveis | 44 |

Veredito: objetivo da P0 preservado. Custo pequeno e inclui conversões de schema.

#### C. Slice filtrado (`load_critical_screens_slice`)

Peers e períodos simulando o caminho real da aba (`periodos_ext_peers` = exibidos + YoY + dez-YoY):

| Cenário | Cold | Warm |
|---|---:|---:|
| 1 peer / 1 período (inclui 1ª download do `passivo`) | 1,175s | 0,232s |
| 1 peer / 3 períodos | 0,212s | 0,209s |
| 5 peers / 3 períodos | 0,222s | 0,222s |

Observação 1: na primeira chamada da sessão, `_supplement_runtime_missing_funding` aciona `manager.carregar("passivo")`, que dispara download do GitHub Releases quando o parquet local não existe. Esse custo aparece somente na primeira suplementação real da sessão e é amortizado em chamadas seguintes (parquet já materializado em disco).

Observação 2: chamadas subsequentes ficam dentro do alvo (~0,2s), mesmo em "cold" do ponto de vista do `@st.cache_data` (porque o PyArrow reader volta ao parquet). O warm hit do `@st.cache_data` reduz a zero em Streamlit real — aqui aparece igual ao cold porque o teste rodou fora do runtime Streamlit.

#### D. Internos da suplementação — 5 peers / 3 períodos expandidos

| Etapa | Tempo |
|---|---:|
| `manager.carregar("passivo")` (já materializado) | 0,012s |
| `manager.carregar("principal")` | 0,010s |
| `_load_runtime_passivo_support` cold | 0,169s |
| `_load_runtime_passivo_support` warm | 0,180s |
| shape final do support | (20, 7) |

Confirmação: o suporte deixou de ser gargalo. Custo estável e proporcional ao recorte real.

#### E. Operações de tabela — fingerprint

Sobre o slice final (20 × 81, ~15 KB):

| Operação | Tempo |
|---|---:|
| `Período.astype(str)` | 0,000s |
| `groupby("Instituição").size()` | 0,000s |
| `sort_values(["Instituição","Período"])` | 0,001s |

Confirmação: assembly da tabela não é gargalo.

### Comparação com medições da rodada anterior

| Cenário | Doc anterior (2026-04-16, pós P2) | Hoje (2026-04-17) |
|---|---:|---:|
| Contexto da aba cold | 0,053s | 0,060s |
| Slice 1 peer / 1 período cold | 0,226s | 1,175s (inclui 1ª download passivo) / 0,232s warm |
| Slice 1 peer / 3 períodos cold | 0,063s | 0,212s |
| Slice 5 peers / 3 períodos cold | 0,070s | 0,222s |
| Suporte 5 peers / 7 períodos internos | 0,048s | 0,169s |

Leitura:

- Os valores de hoje estão próximos, mas ~2–4× acima dos medidos em 2026-04-16. A diferença é explicada por:
  - ambiente diferente (I/O local variável);
  - `to_pandas` chamado cada iteração sem cache do Streamlit runtime;
  - primeira execução incluiu o custo de bootstrap do `critical_screens` e o download do `passivo` do GitHub Releases.
- Mesmo assim, todas as medições seguem **abaixo de 1,2s** no cold-cold e **abaixo de 0,25s** em cold-cold com suporte já materializado.
- O ganho declarado nas rodadas P0/P1/P2 é real e se mantém.

### Gargalo Remanescente #1 — Primeira sessão paga download de `passivo` do GitHub Releases

#### Evidência

- Bootstrap do `critical_screens` traz apenas o próprio parquet curado (13,85 MB).
- A suplementação de funding depende de `passivo` e `principal`.
- `principal` já está em `data/cache/principal/` (distribuído com o bundle/release ou pré-baixado por outras abas).
- `passivo` **não** está entre os caches que o `CacheManager` mantém pré-materializados localmente. Logo, a primeira chamada a `manager.carregar("passivo")` dispara `fonte: github_releases` — confirmado pelo `metadata.json` gerado em `data/cache/passivo/metadata.json`: `"fonte": "github_releases", "timestamp_salvamento": "2026-04-17T03:41:55.112069"`.
- Em rede típica o download agrega tempo visível ao usuário (no ambiente do teste aqui, ~1s a 4s).

#### Impacto

- Ocorre **uma vez por ambiente**, não a cada sessão.
- Só afeta deploys novos, containers recriados, ou quando o release do `passivo` é invalidado.
- Não é reproduzível a partir da segunda abertura da aba.

### Gargalo Remanescente #2 — `canonicalize_institution_dataframe` ainda é `apply(axis=1)`

#### Evidência

- [institutions.py:326–363](../utils/ifdata_cache/institutions.py:326) mantém `out.apply(_resolve_name, axis=1)`.
- Em rodada P2, o caminho é reduzido a residue (rows que o mapa por `CodInst` não resolveu). Em amostras reais, residue = 0.

#### Impacto

- Inexistente hoje em cenários medidos. Mas qualquer regressão que aumente o residue (por exemplo, se o `principal` vier com `CodInst` faltante para algum conglomerado novo) volta a pagar `apply(axis=1)`.

### Gargalo Remanescente #3 — Redundância na montagem do slice

#### Evidência

- `load_critical_screens_slice` chama `build_institution_to_conglomerate_map` **duas vezes** ([critical_screens.py:2046 e 2068](../utils/ifdata_cache/critical_screens.py:2046)), uma por caminho.
- Ambas as chamadas são instantâneas (LRU cache), mas a segunda invocação é código morto — deixou de ser necessária quando o filtro do PyArrow passou a rodar sempre.

#### Impacto

- Zero em tempo. Relevância puramente de code hygiene.

### Gargalo Remanescente #4 — `_carregar_cache_relatorio_slice` não revalida invalidação fina

#### Evidência

- Chave do cache (`tipo_cache`, `cache_token`, `periodos`, `instituicoes`) usa a tupla `instituicoes_slice_tuple` construída em [app1.py:15584](../app1.py:15584).
- Qualquer mudança na tupla (mesma seleção em ordem diferente) gera cache miss. Hoje o código já `sorted(...)` a tupla, então em geral é estável.

#### Impacto

- Baixo. Pode ser revisado se no futuro a UI introduzir reordenações manuais.

### Plano de correção incremental (residual, opcional)

Todos os itens abaixo são **pequenos polimentos**; a aba não está mais lenta. Só fazem sentido se o objetivo for perseguir o piso absoluto.

#### R1 — Pré-bake de `passivo` no bundle

- **Mudança**: incluir `data/bundled/passivo/dados.parquet` no bundle inicial (análogo ao `critical_screens`). Opcional: derivar a partir do bundle apenas as colunas usadas pela suplementação (7 colunas em vez de 34).
- **Ganho**: remove o download único de ~1s a 4s da primeira sessão.
- **Risco**: baixo; apenas aumenta o tamanho do container/deploy. Uma variante enxuta (apenas as colunas necessárias) mantém o container leve.
- **Arquivos**: `scripts/` de build do bundle, `utils/ifdata_cache/critical_screens.py` (opcional, para preferir bundle sobre download).
- **Validação**: conferir que `metadata.json["fonte"]` deixa de vir como `github_releases` na primeira abertura.

#### R2 — Vetorizar `canonicalize_institution_dataframe`

- **Mudança**: substituir `apply(axis=1)` por:
  1. `CodInst.map(code_to_name)` vetorizado;
  2. para os casos de placeholder/código-como-nome, uma `Series.where(mask, mapped).where(~mask2, resolver_vectorizado)`;
  3. fallback a `canonicalize_institution_name` apenas para nomes remanescentes, via `unique → dict → map`.
- **Ganho**: elimina a pior cauda. Em cenários com residue alto (>1k linhas) recupera ~4s.
- **Risco**: médio. A função é usada por outras abas; regressão de matching é o perigo real.
- **Arquivos**: [utils/ifdata_cache/institutions.py](../utils/ifdata_cache/institutions.py).
- **Validação**: comparar antes/depois o nome canônico resolvido para 100% das linhas de `passivo`, `principal`, `ativo` e `capital`; falhar o teste se algum nome divergir.

#### R3 — Materializar `Core Funding` no próprio `critical_screens`

- **Mudança**: gerar `Core Funding` e `Crédito / Captações` diretamente no parquet curado durante o build do cache, eliminando a necessidade de `_supplement_runtime_missing_funding` em tempo de aba.
- **Ganho**: remove toda a carga residual de `passivo`/`principal` do hot path. Tirar ~0,17s do slice cold e reduzir memória transitória.
- **Risco**: médio. Requer que o pipeline de build do `critical_screens` saiba aplicar `resolve_core_funding_value` com as mesmas regras (2024 vs 2025+).
- **Arquivos**: pipeline de build do `critical_screens` (provavelmente `utils/ifdata_cache/critical_screens.py` e/ou `scripts/`).
- **Validação**: paridade total com a suplementação atual em amostra completa (44 períodos, 3.146 instituições). Falhar se houver divergência > epsilon.

#### R4 — Limpar a dupla chamada de `build_institution_to_conglomerate_map` em `load_critical_screens_slice`

- **Mudança**: mover a chamada para dentro de um escopo único; OR refatorar para usar o mapa passado como argumento.
- **Ganho**: zero em tempo; limpeza de código.
- **Risco**: muito baixo.
- **Arquivos**: [utils/ifdata_cache/critical_screens.py](../utils/ifdata_cache/critical_screens.py).

### Estratégia de testes recomendada

1. **Regressão numérica** (P0):
   - Fixar amostra canônica: 5 peers × 3 períodos × todas as métricas da `PEERS_TABELA_LAYOUT`.
   - Snapshot do `valores` produzido por `_montar_tabela_peers` antes e depois de qualquer alteração R*.
   - Falhar se qualquer célula divergir (exceto `NaN` para `NaN`).

2. **Regressão de performance** (P1):
   - Teste em `pytest` importando os helpers reais:
     - `test_filters_context_under_100ms`
     - `test_slice_1peer_1period_cold_under_500ms` (após R1: o passivo já está bundled)
     - `test_slice_5peers_3periods_cold_under_500ms`
     - `test_support_no_apply_axis_1_in_hot_path` (introspecção do `_canonicalize_support_passivo_dataframe`)

3. **Paridade entre abas** (P1):
   - Mesmas células de `Core Funding*`, `Crédito / Captações`, `CET1`, `Basileia`, `Carteira de Crédito*` devem coincidir entre `Snapshot`, `Peers (Tabela)` e leitura direta do `critical_screens`.

4. **Invalidação de cache** (P2):
   - Rodar a aba duas vezes com seleção idêntica: confirmar 2º cold → warm.
   - Rodar a aba com `(a,b,c)` e depois `(c,b,a)`: confirmar que a `sorted(...)` estabiliza a chave e evita miss.

5. **Integridade do bundle** (P2, se R1):
   - CI deve checar que `data/bundled/passivo/dados.parquet` existe (ou a variante enxuta) e tem ao menos as colunas: `Instituição`, `Período`, `CodInst`, `Captações (e) = (a) + (b) + (c) + (d)`, `Instrumentos de Dívida Elegíveis a Capital (h)`.

### Diagnóstico consolidado — 2026-04-17

- A aba `Peers (Tabela)` **não está mais lenta**. As rodadas P0/P1/P2 foram aplicadas com sucesso e se mantêm.
- Medições de hoje confirmam contexto cold ≤ 0,1s, slice cold ≤ 0,25s em regime permanente (com `passivo` já baixado), e operações de tabela em tempo desprezível.
- A única latência perceptível ainda possível é **a primeira sessão de um ambiente novo**, por causa do download único do `passivo` via GitHub Releases. O fix natural (R1) é pré-bundlar o `passivo` junto do `critical_screens`.
- Os demais resíduos (`apply(axis=1)` no residue, dupla chamada de `build_institution_to_conglomerate_map`) são cosméticos e não impactam o usuário hoje.
- Nenhum dos ajustes propostos sacrifica consistência numérica. R3 (materializar Core Funding no parquet curado) é o caminho certo se o objetivo for eliminar qualquer dependência runtime de `passivo`/`principal`; mas não é mais urgente.

### Veredito

- Causa raiz original: **resolvida**.
- Residual acionável: **R1** (pré-bake do `passivo` no bundle) — ganho concreto apenas na primeira sessão.
- Demais itens: **polimento** sem ganho percebido.
- Próxima ação recomendada se houver nova reclamação de lentidão: medir **primeiro** se é na primeira abertura do ambiente (R1 candidate) ou se é consistente mesmo em sessões já warm (investigar fora do backend: Streamlit DOM, rede, ou novos cálculos não mapeados).
