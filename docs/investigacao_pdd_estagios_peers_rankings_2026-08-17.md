# Investigação — cinco métricas de PDD e Estágios em Peers (Tabela) e Rankings

**Data:** 2026-08-17
**Branch:** `claude/tomaconta-pdd-estagios-metrics-uhumsk`
**Base analisada:** `dcdce20` (= `origin/main`)
**Escopo:** investigação. Nenhuma métrica, coluna ou aba foi criada ou alterada.
**Ambiente de verificação:** parquets versionados em `data/bundled/` (`critical_screens`, `derived_metrics`, `bloprudencial`, `principal`) + asset `dre_dados.parquet` do release `v1.1-cache`, baixado para leitura.

---

## 0. Resumo executivo

| # | Métrica pedida | Já existe? | Onde cabe | Cobertura em `1/2026` | Veredito |
|---|---|---|---|---:|---|
| 1 | **Custo de PDD / Carteira** | **Sim** — é o `Custo de Crédito (%)` já em produção nos Rankings | **Falta em Peers** | 1.060 / 1.403 (75,6%) | **Replicar em Peers.** Zero trabalho de dado. |
| 2 | **Custo de PDD / Receita de Crédito** | Não | Peers **e** Rankings | 1.035 / 1.403 (73,8%) | **Implementar.** Menor custo/benefício do lote. |
| 3 | **Estágio 2 / Carteira** | Não | **Peers apenas** | 52 hoje → **109 com o gate de identidade** | **Implementar com o gate.** Fora do Ranking. |
| 4 | **Estágio 3 / Carteira** | **Sim** — já é linha de Peers | — | 54 hoje → **109 com o gate** | **Ampliar cobertura.** Nada a criar. |
| 5 | **Estágios 2+3 / Carteira** | Não | **Peers apenas** | 50 hoje → **109 com o gate** | **Implementar com o gate.** Fora do Ranking. |

**Três conclusões que mudam a conversa com a chefe:**

1. **Duas das cinco métricas já existem.** A #1 é o `Custo de Crédito (%)` entregue nos Rankings no commit `c068300`; a #4 é a linha `Ativos Estágio 3 / Carteira de Crédito` da seção *Qualidade Carteira 4060* em Peers. O pedido real é **três métricas novas + duas propagações de aba**.

2. **A objeção histórica contra os estágios não se aplica a estas métricas.** A auditoria de 11/08 bloqueou "Saldo por Carteira por Estágios" porque a soma E1+E2+E3 é **+117%** maior que a `Carteira de Crédito*`. Verificado agora: esse gap é **quase inteiramente E1**. Em `1/2026`, sobre as 50 IFs com cobertura completa: **ΣE1/ΣCarteira = 203,6%**, mas **ΣE2/ΣCarteira = 6,0%**, **ΣE3/ΣCarteira = 7,4%** e **Σ(E2+E3)/ΣCarteira = 13,3%** — ordens de grandeza economicamente plausíveis. As métricas pedidas são justamente aquelas em que o descasamento de perímetro do 4060 é **menor**, não maior.

3. **Existe um ganho de cobertura de 2,2× que ninguém explorou.** A identidade `3310000003 = E1+E2+E3+3314+3315` fecha dentro de 0,5% para **159 de 159** conglomerados em `202603` — e para **todos os trimestres testados** (`202503`, `202506`, `202509`, `202512`, `202603`). Quando a identidade fecha e uma linha-filha está ausente, ela é **zero reportado por omissão**, não dado faltante. Aplicar esse *gate de reconciliação* leva a cobertura das razões de estágio de **50 para 109 instituições** no universo do app (3,6% → 7,8% dos nomes; 88,3% → 89,1% da carteira do SFN). Ver §4.

---

## 1. Estado atual — o que já está construído

### 1.1 Métrica #1 já está em produção

`Custo de Crédito (%)` está registrado em `utils/ifdata_cache/metric_registry.py:132`, calculado em `utils/ifdata_cache/derived_metrics.py:678-705`, materializado no cache `derived_metrics` (formato LONG) e anexado aos Rankings por `_anexar_custo_credito_rankings` (`app1.py:15481`). Fórmula em produção:

```
Custo de Crédito (%) = |Resultado com Perda Esperada de Operações de Crédito (f3)| YTD anualizado
                       ÷ Carteira de Crédito*
```

Cobertura medida no `derived_metrics_dados.parquet` versionado:

| Período | Linhas | Válidas | Mediana | p90 | Máx |
|---|---:|---:|---:|---:|---:|
| 1/2025 | 1.372 | 1.062 | 2,36% | 10,00% | 17.160% |
| 2/2025 | 1.380 | 1.060 | 2,20% | 9,50% | 146% |
| 3/2025 | 1.393 | 1.049 | 2,45% | 8,19% | 114% |
| 4/2025 | 1.406 | 1.038 | 2,23% | 9,47% | 100% |
| **1/2026** | **1.403** | **1.060** | **3,54%** | **12,54%** | **81%** |

**O que falta:** a métrica **não aparece em Peers (Tabela)**. `CRITICAL_EXTRA_METRICS` (`utils/ifdata_cache/critical_screens.py:56`) não a inclui, e `PEERS_TABELA_LAYOUT` (`tabs/peers_config.py:3`) não tem a linha. Peers hoje carrega `Desp Captação / Captação` do mesmo cache derivado — o caminho de leitura já existe e é reaproveitável.

### 1.2 Métrica #4 já é linha de Peers

`Ativos Estágio 3 / Carteira de Crédito` está na seção **Qualidade Carteira 4060** (`tabs/peers_config.py:58`), com componentes declarados em `PEERS_RATIO_COMPONENTS` (`tabs/peers_config.py:160`) e cálculo em `critical_screens.py:1941`. Cobertura em `1/2026`: **54 instituições**.

### 1.3 Vizinhas que já existem e não devem ser confundidas

| Métrica em produção | Numerador | Denominador | Por que não substitui o pedido |
|---|---|---|---|
| `Desp PDD / Resultado Intermediação Fin. Bruto` | `f` **total** (com sinal) | receita bruta de intermediação (a+b+c+d+e) | Numerador mistura PDD de TVM e interfinanceiras; denominador inclui receita de tesouraria. Spearman de −0,798 contra a métrica #2: mesma ordenação invertida pelo sinal, conceito diferente. |
| `Perda Esperada / Carteira de Crédito*` | **saldo** de provisão (Rel. 2) | carteira | Estoque, não fluxo. É cobertura de provisão, não custo do período. |
| `Perda Esperada / Est2+3` | saldo de provisão | E2 + E3 | Estoque sobre estoque. Já usa a soma E2+E3 — precedente direto para a métrica #5. |
| `Ativos Problemáticos / Carteira Total` | Rel. 16, escopo crédito | Rel. 16 `Total Geral` | **Cobertura de 1.075 IFs.** É o concorrente sério da métrica #4 — ver §5.3. |

---

## 2. Métrica #2 — Custo de PDD / Receita de Crédito

### 2.1 Fonte e fórmula

Ambos os campos vêm do **Relatório 4 (DRE)**, conglomerado prudencial, layout IFData 2025+:

```
Custo de PDD / Receita de Crédito (%)
  = |Resultado com Perda Esperada de Operações de Crédito (f3)| YTD
    ÷ Rendas de Operações de Crédito (c) YTD
```

**Vantagem estrutural sobre a métrica #1:** numerador e denominador são **fluxos do mesmo período**, então o fator de anualização se cancela algebricamente (`|f3·k| ÷ (c·k) = |f3| ÷ c`). Não há decisão de anualização a tomar — é a única das cinco métricas imune ao bloqueio B4 da auditoria anterior.

A reconstrução YTD **continua obrigatória**, porém, por comparabilidade: o Rel. 4 publica Set como Jul–Set e Dez como Jul–Dez, então sem `_compute_ytd_irregular_ifdata_frame` (`app1.py:9507`) o 3T compararia um trimestre isolado com um YTD de 1T. A regra `junho_ausente → NaN` deve valer igualmente.

### 2.2 Cobertura medida

| Período | Linhas | Válidas (`c > 0`) | `c ≤ 0` | `c` = N/D (junho ausente) |
|---|---:|---:|---:|---:|
| 1/2025 | 1.372 | 1.039 | 333 | 0 |
| 2/2025 | 1.380 | 1.040 | 340 | 0 |
| 3/2025 | 1.393 | 1.046 | 315 | 32 |
| 4/2025 | 1.406 | 1.046 | 294 | 66 |
| **1/2026** | **1.403** | **1.035** | **368** | **0** |

As ~330 instituições com `c ≤ 0` são as que não operam crédito — o N/D é o resultado correto, não uma falha.

### 2.3 Distribuição em `1/2026` (N = 1.035)

| p10 | p25 | mediana | p75 | p90 | p95 | p99 | máx |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1,4% | 7,4% | **18,8%** | 30,9% | 49,7% | 77,5% | 234,8% | 13.023% |

Grandes bancos, `1/2026`:

| Instituição | Receita de crédito (R$ bi) | f3 (R$ bi) | **PDD / Receita** | Custo de Crédito (%) |
|---|---:|---:|---:|---:|
| CAIXA ECONÔMICA FEDERAL | 39,35 | −7,49 | **19,0%** | 2,1% |
| BB | 35,73 | −18,37 | **51,4%** | 6,0% |
| ITAÚ | 35,20 | −9,72 | **27,6%** | 3,1% |
| BRADESCO | 29,60 | −9,23 | **31,2%** | 3,9% |
| SANTANDER | 26,12 | −5,35 | **20,5%** | 3,6% |
| NU PAGAMENTOS | 15,86 | −7,38 | **46,5%** | 15,2% |
| MERCADO PAGO IP | 7,79 | −6,42 | **82,4%** | 30,9% |
| BTG PACTUAL | 7,59 | −1,55 | **20,5%** | 2,8% |
| BNDES | 7,20 | −0,32 | **4,4%** | 0,3% |

Os números reproduzem exatamente a prototipagem da auditoria de 11/08 (§1.5) e são coerentes com o perfil de risco conhecido de cada nome.

### 2.4 A métrica é redundante com a #1?

Não. Spearman entre as duas em `1/2026` (N = 1.017): **0,843** — ordenação parecida, mas com deslocamentos materiais. Caixa é 715º em Custo de Crédito e 510º em PDD/Receita; Santander é 509º e 477º; BB sobe de 266º para 99º. São leituras distintas:

- **Custo de Crédito** = custo por unidade de **exposição** (fluxo ÷ estoque). Responde "quanto a carteira custa".
- **PDD / Receita de Crédito** = fração da **margem** consumida por provisão (fluxo ÷ fluxo). Responde "quanto sobra da receita".

Um banco de spread alto e risco alto (Nubank: 15,2% de custo, 46,5% da receita) fica muito diferente de um banco de spread baixo e risco baixo (BNDES: 0,3% e 4,4%). A segunda métrica é o teste de sustentabilidade do modelo de crédito que a primeira não faz.

### 2.5 Riscos de implementação

**R1 — Cauda longa.** 30 instituições acima de 100% e 12 acima de 200% em `1/2026`, com máximo de 13.023%. São nomes de receita de crédito residual. O `Custo de Crédito (%)` já convive com isso (máx. de 17.160% em `1/2025`), então **não é um bloqueio novo** — mas se a métrica entrar no Ranking em barras, o eixo fica ilegível. Recomendação: **piso de materialidade no Ranking** (ex.: exigir `Rendas de Operações de Crédito (c)` acima de um limiar), divulgado na própria tela, e nenhum piso em Peers, onde o usuário escolhe os nomes.

**R2 — Sinal.** Em `1/2026`, `f3` é negativo em 890 IFs, zero em 385 e **positivo em 128** (reversão líquida de provisão — XP, Facta, Original, Sicredi entre elas). O `Custo de Crédito (%)` aplica `.abs()` (fixado em `tests/test_custo_credito.py:148`), o que transforma uma reversão em "custo". A métrica #2 herdaria a mesma distorção. **Duas saídas honestas:** preservar o sinal (uma reversão vira valor negativo, legível como crédito de provisão) ou manter `.abs()` por consistência e sinalizar no tooltip. Recomendo **preservar o sinal na métrica nova e abrir a discussão de retrofit na #1** — mas isso é decisão de produto, não técnica.

**R3 — Quebra estrutural em `1/2025`.** `f3` e `c` só existem no layout 2025+. Períodos até `4/2024` ficam N/D, exatamente como o `Custo de Crédito (%)` já se comporta. Sem novidade.

---

## 3. Métricas #3, #4 e #5 — razões de estágio sobre carteira

### 3.1 O gap de perímetro é real, mas é um problema de E1

A árvore do Cadoc 4060 classifica **"Ativos Financeiros" sujeitos a perda esperada** — inclui TVM a custo amortizado, aplicações interfinanceiras e outros recebíveis, além da carteira de crédito. Daí o +117% agregado apontado em 11/08. Decomposto em `1/2026`, sobre as 50 IFs com E2, E3 e carteira simultâneos:

| Numerador | Σ (R$ bi) | ÷ Σ Carteira de Crédito* (R$ 7.520 bi) |
|---|---:|---:|
| E1 | 15.311,7 | **203,6%** ← todo o gap está aqui |
| E2 | 450,1 | **6,0%** |
| E3 | 553,3 | **7,4%** |
| E2 + E3 | 1.003,4 | **13,3%** |
| *(controle)* Ativos Problemáticos Rel. 16 | 462,0 | 6,1% |

**Leitura:** ativos de tesouraria praticamente não migram para estágios 2 e 3 — ficam em E1. As razões pedidas são, portanto, materialmente menos contaminadas que o saldo bruto de estágios. Elas continuam **enviesadas para cima** (numerador de escopo mais largo que o denominador), mas na ordem de 1 a 2 pontos percentuais no agregado, não de 2×.

### 3.2 Distribuição por instituição em `1/2026` (N = 50)

| Razão | p10 | p25 | mediana | p75 | p90 | máx |
|---|---:|---:|---:|---:|---:|---:|
| **E2 / Carteira** | 1,4% | 2,5% | **4,2%** | 8,4% | 14,6% | 26,0% |
| **E3 / Carteira** | 1,3% | 4,2% | **7,0%** | 8,7% | 13,8% | 42,7% |
| **(E2+E3) / Carteira** | 5,4% | 7,3% | **11,3%** | 17,7% | 23,5% | 60,2% |
| *(controle)* Ativos Problem. / Carteira | 0,8% | 3,5% | 5,4% | 7,2% | 12,7% | 28,0% |

Top 10 por carteira, `1/2026`:

| Instituição | Carteira (R$ bi) | E2/Cart. | E3/Cart. | **(E2+E3)/Cart.** | Problem. Rel.16/Cart. |
|---|---:|---:|---:|---:|---:|
| CAIXA ECONÔMICA FEDERAL | 1.410,3 | 2,5% | 7,4% | **9,9%** | 7,0% |
| ITAÚ | 1.272,6 | 5,3% | 4,9% | **10,2%** | 3,4% |
| BB | 1.218,6 | 3,9% | 9,1% | **13,0%** | 8,1% |
| BRADESCO | 953,1 | 5,2% | 8,8% | **14,0%** | 5,6% |
| SANTANDER | 589,4 | 9,2% | 8,3% | **17,5%** | 7,2% |
| BNDES | 420,9 | 21,3% | 4,5% | **25,9%** | 3,9% |
| BTG PACTUAL | 225,6 | 8,4% | 6,3% | **14,7%** | 5,2% |
| NU PAGAMENTOS | 194,4 | 11,9% | 15,6% | **27,4%** | 15,1% |
| SAFRA | 145,7 | 6,2% | 4,1% | **10,2%** | 3,3% |
| BANCO C6 | 100,1 | 1,9% | 4,1% | **6,1%** | 4,0% |

### 3.3 Controle externo — E3 contra "Ativos Problemáticos" do Rel. 16

O Relatório 16 (`Carteira Total 4.966`) publica **Ativos problemáticos** com escopo *de crédito*, o que dá um controle independente do E3. Em `1/2026`, sobre as 49 IFs com ambos:

| Medida | Resultado |
|---|---:|
| Mediana de \|diferença\| | **8,5%** |
| Diferença agregada (ΣE3 vs ΣProblem.) | **+19,7%** |
| Até 2% | 15 / 49 |
| Até 5% | 22 / 49 |
| Até 10% | 25 / 49 |
| Acima de 25% | 14 / 49 |

**Interpretação:** o E3 do 4060 fica sistematicamente **acima** dos ativos problemáticos do Rel. 16 — consistente com o escopo mais largo (ativos financeiros vs. carteira de crédito). Para cerca de metade dos nomes as duas medidas coincidem dentro de 5%; para a outra metade divergem materialmente. **Isso não invalida a métrica #4 — invalida chamá-la de "inadimplência".** O rótulo precisa dizer *Estágio 3 (Cadoc 4060)*, como já diz hoje.

### 3.4 Outliers que exigem tratamento

| Instituição | Sintoma | Causa provável |
|---|---|---|
| **BCO COOPERATIVO SICREDI** | E2 = R$ 34 mi e E3 = R$ 25 mi contra carteira de R$ 48,4 bi → razão de 0,0% | Entidade reportante do 4060 é a central, não o sistema cooperativo consolidado. Mesmo sintoma já registrado na auditoria do Pilar 3. |
| **BANCO SICOOB** | E2/Carteira = 18,2% com Problem./Carteira = 2,9% | E1 de R$ 225 bi contra carteira de R$ 43 bi — consolidação do sistema cooperativo muito além da entidade do IFData. |
| **BNDES** | E2/Carteira = 21,3% | Provavelmente real (carteira de longo prazo com aumento significativo de risco), mas merece nota. |
| **JP MORGAN, XP, Goldman, Morgan Stanley** | E1 ≫ carteira | Perfil de tesouraria. As razões E2/E3 continuam pequenas, mas o denominador é frágil. |

Recomendação: **não filtrar silenciosamente**. Marcar no tooltip/memória de cálculo quando `E1 / Carteira de Crédito*` exceder um limiar (ex.: 3×), sinalizando descasamento de perímetro na própria célula — padrão já usado em `Trace::Carteira::Status` e `Trace::Qualidade Carteira::Status`.

---

## 4. Descoberta central — o gate de identidade dobra a cobertura

### 4.1 O problema

Em `1/2026`, o `critical_screens` entrega:

| Coluna | IFs com valor |
|---|---:|
| `Carteira Estágio 1` | 78 |
| `Ativos Estágio 2` | 55 |
| `Ativos Estágio 3` | 55 |
| E2 **e** E3 **e** carteira > 0 | **50** |
| `Trace::Bloprudencial::Status == available` | **128** |

Ou seja: **78 instituições reportam E1, mas só 55 reportam E2/E3.** A implementação atual preserva N/D para as 23 restantes — decisão correta sob a regra "ausência ≠ zero" do projeto.

### 4.2 A verificação

A conta-pai `3310000003` obedece a identidade:

```
3310000003 = 3311000002 (E1) + 3312000001 (E2) + 3313000000 (E3)
           + 3314000009 (simpl. não problemático) + 3315000008 (simpl. problemático)
```

Testado no `bloprudencial_dados.parquet` versionado, filtrando `DOCUMENTO == 4060`:

| Período | Conglomerados com a conta-pai | Identidade fecha < 0,5% | Falha |
|---|---:|---:|---:|
| 202503 | 149 | **149** | 0 |
| 202506 | 155 | **155** | 0 |
| 202509 | 158 | **158** | 0 |
| 202512 | 158 | **158** | 0 |
| 202603 | 159 | **159** | 0 |

E, especificamente para os 25 conglomerados de `202603` que reportam E1 **sem** E2: a identidade fecha **exatamente (gap relativo = 0,0000) em 25 de 25**. Exemplos: Goldman Sachs (pai = 16,21 bi = E1 16,19 + E3 0,02), Scotiabank (pai = E1 = 15,10 bi), BNY Mellon (pai = E1 = 2,17 bi).

**Conclusão: a linha ausente é zero reportado por omissão, e isso é demonstrável linha a linha — não presumido.**

### 4.3 A regra proposta

> **Gate de reconciliação 4060.** Para um par (conglomerado, competência), se `3310000003` estiver presente e `|3310000003 − Σ(filhos presentes)| / 3310000003 < 0,5%`, então cada conta-filha ausente pode ser lida como **0 (zero derivado por identidade)**, marcada em trace como `zero_por_identidade`. Se a identidade **não** fechar, ou se a conta-pai estiver ausente, tudo permanece **N/D**.

Isso respeita o princípio "ausência ≠ zero" porque o zero **não é imputado — é deduzido de uma identidade contábil fechada**, com falha explícita quando ela não fecha.

### 4.4 Ganho medido

| Universo | Sem gate | Com gate |
|---|---:|---:|
| Conglomerados no 4060 com E2 utilizável (`202603`) | 55 | **159** |
| Conglomerados no 4060 com E3 utilizável (`202603`) | 55 | **159** |
| **IFs no app com razão de estágio (`1/2026`)** | **50** (3,6%) | **109** (7,8%) |
| Cobertura da carteira do SFN | 88,3% | **89,1%** |
| Cobertura do ativo total do SFN | 87,9% | **89,5%** |

O teto de 109 é o `Trace::Bloprudencial::Status == available` (128 IFs), menos as que não têm carteira > 0. **O gargalo deixa de ser o reporte dos estágios e passa a ser o pareamento instituição ↔ 4060** — que é um problema diferente, endereçável, e que hoje deixa 1.275 IFs sem match.

### 4.5 Extensão relacionada — "Ativos Problemáticos 4060"

Verificado em `202603`: os conjuntos de reportantes de `3313000000` (E3) e `3315000008` (simplificada problemática) são **disjuntos** — interseção = 0, união = 115 conglomerados. A instituição usa a metodologia por estágios **ou** a simplificada, nunca as duas.

Portanto, uma métrica definida como:

```
Ativos Problemáticos 4060 = 3313000000 + 3315000008
```

cobre **115 conglomerados em vez de 55**, ao custo de somar R$ 13,4 bi (2,4% do total de E3). É a definição que a auditoria do Pilar 3 já recomendou como comparador primário (§3, "4060 problemático = Estágio 3 + método simplificado problemático").

**Contrapartida:** não existe equivalente simplificado para o Estágio 2. As métricas #3 e #5 ficam estruturalmente limitadas aos reportantes de estágio; só a #4 se beneficia dessa extensão. Se a chefe quiser uma única linha de "qualidade" com cobertura máxima, o caminho é `Ativos Problemáticos 4060 / Carteira`, não `Estágio 3 / Carteira`.

---

## 5. Decisões metodológicas a fechar

### 5.1 Qual denominador de carteira

| Opção | Cobertura em `1/2026` | Prós | Contras |
|---|---:|---|---|
| **`Carteira de Crédito*`** (Rel. 2, VCB e1+f1+g1+h1) — *recomendada* | 1.403 | Já é o denominador canônico do app e da linha `Estágio 3 / Carteira` existente. Consistência interna total. | Descasa de perímetro com o numerador 4060 (viés de +1 a 2 p.p. no agregado). |
| `Carteira Total 4.966` (Rel. 16, `Total Geral`) | 1.104 | Escopo estritamente de crédito. | Introduz um segundo denominador de carteira na mesma tabela — confunde o leitor. |
| Conta-pai `3310000003` | 159 no 4060 | Numerador e denominador do mesmo perímetro; identidade fecha em 100%. | O resultado deixa de ser "NPL ratio": E3/pai = 3,4% agregado. Responde outra pergunta. |

**Recomendação:** manter `Carteira de Crédito*`, pelo precedente da linha #4 já em produção e pela consistência com o resto da seção. Expor a conta-pai como **linha de trace na memória de cálculo**, não como denominador alternativo na tabela.

### 5.2 Nome das linhas

A palavra "carteira" no numerador seria enganosa. Sugestão alinhada ao vocabulário já usado em `tabs/peers_config.py`:

| Métrica | Rótulo sugerido |
|---|---|
| #1 | `Custo de Crédito (%)` — reaproveitar o nome já em produção nos Rankings |
| #2 | `Custo de Crédito / Receita de Crédito` |
| #3 | `Ativos Estágio 2 / Carteira de Crédito` |
| #5 | `Ativos Estágio 2+3 / Carteira de Crédito` |

O `PEERS_GLOSSARIO_RESUMIDO` já traz a ressalva de escopo nas linhas de estágio existentes; as novas devem repetir o mesmo texto.

### 5.3 O concorrente do Rel. 16

`Ativos Problemáticos / Carteira Total` já existe em `CRITICAL_EXTRA_METRICS` com **1.075 IFs** de cobertura em `1/2026` (mediana 7,4%) — vinte vezes mais que as razões de estágio. Ele **não está exposto em `PEERS_TABELA_LAYOUT`**.

Se a pergunta da chefe é *"qual a qualidade da carteira de crédito"*, essa é a métrica com melhor cobertura e escopo correto. Se a pergunta é *"como os bancos classificam seus ativos sob a Res. 4.966"*, os estágios são a resposta certa. **As duas coisas cabem lado a lado na mesma seção**, e expor a do Rel. 16 é o item de maior cobertura marginal deste relatório — custa uma linha em `peers_config.py` e nada mais.

---

## 6. Onde cada métrica cabe

| Métrica | Peers (Tabela) | Rankings | Snapshot | Justificativa |
|---|:--:|:--:|:--:|---|
| #1 Custo de PDD / Carteira | **Sim** | *já está* | Sim | 75,6% de cobertura. |
| #2 Custo de PDD / Receita | **Sim** | **Sim** | Sim | 73,8% de cobertura, ratio invariante à anualização. |
| #3 Estágio 2 / Carteira | **Sim** | **Não** | Sim | 7,8% dos nomes. Um "ranking" de 109 de 1.403 induz a erro. |
| #4 Estágio 3 / Carteira | *já está* | **Não** | Sim | Idem. |
| #5 Estágios 2+3 / Carteira | **Sim** | **Não** | Sim | Idem. |
| *(bônus)* Ativos Problem. / Carteira Total | **Sim** | **Avaliar** | Sim | 76,6% de cobertura — o único candidato de estágio-equivalente viável em Ranking. |

**Regra de cobertura sugerida para os Rankings** (alinhada ao que a auditoria do Pilar 3 propôs): publicar um indicador no Ranking só quando cobrir **≥ 60% dos nomes** ou quando a tela exibir a cobertura na própria interface. As métricas #1 e #2 passam; #3, #4 e #5 não passam. `Ativos Problemáticos / Carteira Total` passa.

---

## 7. Caminho de implementação

### 7.1 Métrica #2 — cache derivado (menor esforço, maior retorno)

Segue exatamente o molde do `Custo de Crédito (%)` implementado em `c068300`:

1. `utils/ifdata_cache/metric_registry.py` — nova `MetricDefinition` (`custo_credito_receita`), sem `AnnualizationRule` (o fator cancela — documentar isso em `notes`), e inclusão em `DERIVED_METRIC_KEYS`.
2. `utils/ifdata_cache/derived_metrics.py` — constante `METRIC_CUSTO_CREDITO_RECEITA`; a coluna `rec_credito` já está em `DRE_REQUIRED_COLUMNS:68`; cálculo em `build_derived_metrics` reaproveitando `desp_pdd_credito_ytd` e adicionando `rec_credito_ytd = _acumular_dre_ytd_por_periodo(df_base, rec_credito)`. **Não anualizar nenhum dos dois.**
3. `utils/ifdata_cache/__init__.py` — reexportar a constante (o padrão de import está fixado por `tests/test_custo_credito.py:334`).
4. `app1.py` — `indicadores_config` e `ordem_prioritaria` (~`18999`), `_RANKINGS_GLOSSARIO` (~`19041`), `RANKINGS_FAMILY_PRINCIPAL_LIGHT` e `RANKINGS_FAMILY_DERIVED` (`14127`/`14137`), `VARS_PERCENTUAL` (`5425`), tabela do Glossário (`27426`).
5. `_anexar_custo_credito_rankings` (`15481`) precisa **generalizar para uma lista de métricas** em vez de ganhar uma cópia — hoje ele é hard-coded em `METRIC_CUSTO_CREDITO`. É o momento certo de extrair `_anexar_metricas_derivadas_rankings(df, metricas, periodos)`.

Rematerialização: `tools/update_caches_cli.py` + publicação do asset `derived_metrics_dados.parquet` no release, conforme `docs/runbook_cache_release.md`.

### 7.2 Métricas #1 (em Peers), #3 e #5 — camada curada

Pontos de toque mapeados a partir da linha `Ativos Estágio 3 / Carteira de Crédito` já existente:

| Arquivo | Linha de referência | O que muda |
|---|---|---|
| `utils/ifdata_cache/critical_screens.py` | `56` | Adicionar a `CRITICAL_EXTRA_METRICS` |
| ” | `1941` | Novas entradas no dict de linhas do builder |
| ” | `583-594` | `_derive_runtime_compatible_metrics` — backfill para bundles legados |
| ” | `39` | **Bump de `CRITICAL_SCREENS_SCHEMA_VERSION` 4 → 5** e revisão de `RUNTIME_COMPATIBLE_SCHEMA_VERSIONS` |
| `tabs/peers_config.py` | `46` | Linhas em `PEERS_TABELA_LAYOUT`, seção *Qualidade Carteira 4060* |
| ” | `131` | Verbetes em `PEERS_GLOSSARIO_RESUMIDO` |
| ” | `159` | `PEERS_RATIO_COMPONENTS` (ver ressalva abaixo) |
| ” | `170` | `PEERS_ALLOWANCE_RATIO_METRICS` se usar magnitude |
| `app1.py` | `1335` | Lista de variáveis percentuais |
| ” | `5724` | Mapa de componentes do tooltip |
| ” | `8604` | Inicialização do dict `extra` |
| ” | `9427` | Cálculo em `_preparar_metricas_extra_peers` |
| ” | `9875` | Recomposição do ratio a partir dos componentes |
| ” | `10622-10632` | Memória de cálculo (`ratio_map`) |
| ” | `17051` | Texto de ajuda da aba |
| ” | `27434` | Tabela do Glossário |
| `tools/materialize_critical_screens.py` | — | Rematerializar `data/bundled/critical_screens/` |

### 7.3 Dívida técnica que este pedido expõe

**`PEERS_RATIO_COMPONENTS` só aceita um par (numerador, denominador).** Por isso `Perda Esperada / Est2+3` precisou de um `if label == ...` dedicado em `app1.py:10080` e de um helper próprio, `_somar_estagios_2_3_peers` (`app1.py:9511`). A métrica #5 cairia no mesmo caso e viraria a **segunda** exceção hard-coded.

**Recomendação:** antes de adicionar #5, generalizar o contrato para aceitar `numerador` como tupla de componentes:

```python
PEERS_RATIO_COMPONENTS = {
    "Ativos Estágio 2+3 / Carteira de Crédito": (
        ("Ativos Estágio 2", "Ativos Estágio 3"),   # numerador = soma, min_count=2
        "Carteira de Crédito Bruta",
    ),
}
```

Isso elimina os dois branches especiais, faz `Perda Esperada / Est2+3` e a métrica #5 usarem o mesmo caminho, e evita que a terceira razão composta crie uma terceira exceção. É refactor de baixo risco com cobertura de teste já existente (`tests/test_peers_exports.py`).

### 7.4 Testes necessários

**Métrica #2:**
- ratio invariante ao fator de anualização (mesmo valor com `×4` e sem);
- `junho_ausente` → N/D em 3T e 4T;
- `c ≤ 0` → N/D, nunca zero nem infinito;
- ausência de `f3` (layout ≤ 2024) → N/D em toda a série;
- decisão de sinal fixada por teste, qualquer que seja ela;
- regressão de import (o boot não pode importar a constante do pacote — molde em `tests/test_custo_credito.py:334`).

**Gate de identidade:**
- identidade fecha → filha ausente vira `0` com trace `zero_por_identidade`;
- identidade **não** fecha → tudo N/D, sem imputação;
- conta-pai ausente → N/D;
- zero efetivamente reportado permanece distinguível de zero derivado;
- E3 ∩ simplificada-problemática = ∅ (regressão do pressuposto de §4.5);
- regressão de `DOCUMENTO == 4060` (não somar 4066).

**Razões de estágio:**
- `(E2+E3)` usa `min_count=2` — um componente ausente **não** vira soma parcial;
- denominador zero/ausente → N/D;
- memória de cálculo exibe numerador, denominador e fórmula;
- cobertura mínima respeitada no Ranking (bloqueio de #3/#4/#5).

---

## 8. Recomendação final

**Fazer agora, em uma entrega:**

1. **Métrica #2** (`Custo de Crédito / Receita de Crédito`) em Peers e Rankings — 73,8% de cobertura, sem decisão de anualização pendente, molde já existente no `derived_metrics`.
2. **Métrica #1 em Peers** — a métrica já está calculada e versionada; é propagação de aba.
3. **Expor `Ativos Problemáticos / Carteira Total`** em Peers — já está no `critical_screens`, 1.075 IFs, escopo de crédito correto. Maior ganho de cobertura por linha de código de todo o lote.

**Fazer em seguida, com o refactor de §7.3 antes:**

4. **Gate de identidade do 4060** — dobra a cobertura das razões de estágio (50 → 109) e é pré-requisito para que #3 e #5 nasçam úteis em vez de nascer com 3,6% de preenchimento.
5. **Métricas #3 e #5** em Peers, **explicitamente fora dos Rankings**, com o rótulo de escopo já usado nas linhas de estágio existentes.

**Levar à chefe antes de codificar:**

- As métricas #1 e #4 **já existem** — vale confirmar se ela as viu nas abas atuais antes de tratá-las como pedido novo.
- O numerador dos estágios é *ativos financeiros*, não *carteira de crédito*. O viés no agregado é de ~1 a 2 p.p., não de 2×, mas o rótulo precisa dizer isso.
- A decisão de sinal (§2.5, R2): reversão de provisão vira custo positivo ou valor negativo?
- Se o objetivo for "qualidade da carteira" com cobertura ampla, `Ativos Problemáticos / Carteira Total` (Rel. 16) responde melhor que `Estágio 3 / Carteira` (4060) — 1.075 IFs contra 109.

---

## 9. Rastreabilidade

| Afirmação | Verificada em |
|---|---|
| `Custo de Crédito (%)` em produção nos Rankings | `metric_registry.py:132`, `derived_metrics.py:678-705`, `app1.py:15481`, `app1.py:18999` |
| Ausente de Peers | `critical_screens.py:56` (`CRITICAL_EXTRA_METRICS`), `tabs/peers_config.py:3` |
| `Estágio 3 / Carteira` já é linha de Peers | `tabs/peers_config.py:58`, `critical_screens.py:1941` |
| Cobertura e distribuição do `Custo de Crédito (%)` | `data/bundled/derived_metrics/dados.parquet`, períodos `1/2025`–`1/2026` |
| Colunas `f3` e `c`; cobertura da métrica #2 | asset `dre_dados.parquet` do release `v1.1-cache` (62.061 × 96) |
| Sinal de `f3` (890 neg. / 385 zero / 128 pos.) | idem, `1/2026` |
| Spearman #1 × #2 = 0,843; #2 × PDD/Intermediação = −0,798 | cruzamento `dre` × `derived_metrics`, `1/2026`, N = 1.017 |
| Gap de perímetro concentrado em E1 (ΣE1/ΣCart. = 203,6%) | `data/bundled/critical_screens/dados.parquet`, `1/2026`, N = 50 |
| Distribuições de E2/Cart., E3/Cart., (E2+E3)/Cart. | idem |
| Controle E3 × Ativos Problemáticos Rel. 16 | idem, N = 49 |
| Identidade da conta-pai fecha em 159/159 e em todos os trimestres | `data/bundled/bloprudencial/dados.parquet`, `DOCUMENTO == 4060` |
| 25 de 25 IFs com E1 sem E2 fecham a identidade exatamente | idem, `202603` |
| E3 ∩ simplificada-problemática = ∅; união = 115 | idem, `202603` |
| Ganho de cobertura 50 → 109 IFs | `Trace::Bloprudencial::Status`, `1/2026` |
| Cobertura de `Ativos Problemáticos / Carteira Total` = 1.075 | `critical_screens`, `1/2026` |
| Exceção hard-coded de `Perda Esperada / Est2+3` | `app1.py:10080-10088`, `app1.py:9511` |
| Regra YTD irregular do Rel. 4 | `app1.py:9507-9556`, `tests/test_dre_ytd.py` |
| Versionamento do schema curado | `critical_screens.py:39-40`, `data/bundled/critical_screens/metadata.json` |

### Investigações anteriores relacionadas

- `docs/investigacao_viabilidade_custo_credito_e_estagios_2026-08-11.md` — origem do bloqueio B1/B2 revisto aqui em §3.1 e §4.
- `docs/diagnostico_rankings_custo_credito_2026-08-11.md`
- Auditoria Pilar 3 CR1/CR2 × Cadoc 4060 (12/08/2026) — origem da definição `problemático = E3 + 3315`, confirmada em §4.5.
