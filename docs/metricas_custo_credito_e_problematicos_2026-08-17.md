# Métricas de custo de crédito e ativos problemáticos — o que foi implementado

**Data:** 2026-08-17
**Branch:** `claude/tomaconta-pdd-estagios-metrics-uhumsk`
**Critério de corte adotado:** só entram métricas com **mais de 1.000 instituições** e **mais de 70% do saldo** do SFN. As razões de estágio do Cadoc 4060 ficaram de fora por esse critério — ver §5.

---

## 1. Resumo

Três métricas passaram a existir em **Rankings, Peers (Tabela) e Scatter Plot**. Duas são novas; uma já existia nos Rankings e foi propagada para as demais abas.

| Métrica | Situação anterior | Cobertura em `1/2026` | Abas onde aparece agora |
|---|---|---:|---|
| **Custo de Crédito (%)** | existia só em Rankings | **1.060 / 1.403 (75,6%)** | Rankings, Peers (Tabela), Scatter Plot, Snapshot, Glossário |
| **Custo de Crédito / Receita de Crédito (%)** | não existia | **1.035 / 1.403 (73,8%)** | Rankings, Peers (Tabela), Scatter Plot, Snapshot, Glossário |
| **Ativos Problemáticos / Carteira Total** | calculada no cache curado, nunca exibida | **1.075 / 1.403 (76,6%)** | Rankings, Peers (Tabela), Scatter Plot, Snapshot, Glossário |

Uma quarta linha entrou junto em Peers por usar exatamente o mesmo par de fontes e o mesmo perímetro do indicador de ativos problemáticos: **Inadimplência / Carteira Total** (1.075 IFs). Ela já era calculada no cache curado e também nunca havia sido exposta.

---

## 2. Fonte de cada dado, campo a campo

### 2.1 Custo de Crédito (%)

| Papel | Campo | Fonte |
|---|---|---|
| Numerador | `Resultado com Perda Esperada de Operações de Crédito (f3)` | **IFData Relatório 4** (DRE), conglomerado prudencial |
| Denominador | `Carteira de Crédito*` = `Valor Contábil Bruto (e1+f1+g1+h1)` | **IFData Relatório 2** (Ativo) |

```
Custo de Crédito (%) = |f3| YTD anualizado ÷ Carteira de Crédito*
```

- **YTD:** o Rel. 4 publica Set como Jul–Set e Dez como Jul–Dez. O YTD é reconstruído somando junho. Sem junho publicado, o período fica N/D.
- **Anualização:** Mar ×4, Jun ×2, Set ×12/9, Dez ×1. Necessária porque o numerador é fluxo e o denominador é estoque.
- **Escopo do numerador:** apenas operações de crédito. Não inclui TVM (`f2`), aplicações interfinanceiras (`f1`) nem os demais componentes do `f` total.

### 2.2 Custo de Crédito / Receita de Crédito (%)

| Papel | Campo | Fonte |
|---|---|---|
| Numerador | `Resultado com Perda Esperada de Operações de Crédito (f3)` | **IFData Relatório 4** (DRE) |
| Denominador | `Rendas de Operações de Crédito (c)` | **IFData Relatório 4** (DRE) |

```
Custo de Crédito / Receita de Crédito (%) = |f3| YTD ÷ (c) YTD
```

- **Sem anualização.** Numerador e denominador são fluxos do mesmo período: qualquer fator se cancela na razão (`|f3·k| ÷ (c·k) = |f3| ÷ c`). É a única das três imune à decisão de anualização, e há teste fixando esse invariante.
- **Reconstrução de YTD continua obrigatória** por comparabilidade — sem ela o 3T compararia um trimestre isolado com o YTD do 1T.
- **Receita zero, negativa ou ausente → N/D.** São as ~370 instituições que não operam crédito. Nunca zero, nunca infinito.

### 2.3 Ativos Problemáticos / Carteira Total — a origem do dado

Esta é a métrica sobre a qual havia mais dúvida, então vale o detalhe completo.

| Papel | Campo publicado | Fonte |
|---|---|---|
| Numerador | `Ativos problemáticos` | **IFData Relatório 16** |
| Denominador | `Total Geral` | **IFData Relatório 16** |

**O relatório.** Relatório 16 do IFData — *"Carteira de crédito ativa por carteiras de instrumentos financeiros"*, o relatório da Res. CMN 4.966. Extraído da API Olinda do BCB (`olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata`, `numeroRelatorio=16`), cache `carteira_instrumentos` (`utils/ifdata_cache/relatorios_completos.py:459`). Periodicidade trimestral, perímetro de conglomerado prudencial.

**As colunas.** O relatório traz a carteira aberta em `C1`..`C5` (níveis de risco), mais `Carteira não Informada`, `Total Exterior`, `Total não Individualizado`, o `Total Geral`, e duas colunas de qualidade: `Inadimplência` e `Ativos problemáticos`. O contrato dessas colunas está fixado em `utils/ifdata_cache/carteira_4966_quality.py:22-47`.

**O que "ativo problemático" significa.** Não é um cálculo do Toma Conta — é um campo **publicado pelo BCB**, com definição prudencial no **art. 24 da Res. CMN 4.557**. Abrange a operação que atende a qualquer um dos critérios:

1. está em atraso relevante superior a **90 dias**; ou
2. há indicação de que a obrigação **não será integralmente honrada** sem recurso a garantia ou colateral.

O segundo critério é o que separa a métrica da simples inadimplência: uma operação reestruturada por dificuldade financeira do devedor pode estar adimplente e ainda assim ser ativo problemático. Por isso `Ativos Problemáticos / Carteira Total` (mediana 7,4%) fica sistematicamente acima de `Inadimplência / Carteira Total` (mediana 2,8%) — as duas linhas aparecem juntas em Peers exatamente para deixar essa diferença visível.

**Por que o perímetro é limpo.** Numerador e denominador saem do **mesmo relatório, da mesma linha, do mesmo perímetro**. Não há reconciliação entre fontes, não há descasamento de escopo, não há match a fazer. É a diferença estrutural em relação às razões de estágio do Cadoc 4060, cujo numerador vem de uma fonte contábil mensal com escopo de *ativos financeiros* e cujo denominador vem do Rel. 2 com escopo de *carteira de crédito*.

**Não é Estágio 3.** Os dois conceitos são próximos mas não equivalentes. Na investigação de 17/08, sobre as 49 instituições com ambos em Mar-26: mediana de diferença absoluta de 8,5%, e o Estágio 3 ficou **+19,7% acima** dos ativos problemáticos no agregado — consequência do escopo mais largo do 4060. Metade dos nomes coincide dentro de 5%; a outra metade diverge materialmente. O glossário e o tooltip trazem esse aviso.

---

## 3. Onde cada ratio ficou guardado

A regra aplicada: **cada razão é calculada uma vez, no cache que a aba consome**, e nenhuma é recalculada na renderização.

| Cache (parquet) | Formato | O que passou a guardar | Quem lê |
|---|---|---|---|
| `derived_metrics` | LONG (`Instituição, Período, Métrica, Valor, Unidade`) | as **três** razões | Rankings, Scatter Plot |
| `critical_screens` | WIDE (uma coluna por métrica) | as **três** razões + 3 colunas `Trace::` | Peers (Tabela), Snapshot |

**Por que as duas camadas.** Rankings e Scatter leem o cache derivado (leve, formato long, filtrável por métrica); Peers e Snapshot leem o cache curado (largo, com traces para a memória de cálculo). Manter as duas evita que Peers precise carregar o parquet long inteiro e que Rankings precise carregar as 108 colunas do curado.

**Como a duplicação é controlada.** `Ativos Problemáticos / Carteira Total` é calculada nos dois caches a partir do mesmo Relatório 16. Isso é uma duplicação real, e por isso virou invariante verificado: `test_camada_curada_e_cache_derivado_concordam_em_ativos_problematicos` falha se as duas camadas divergirem.

**Colunas `Trace::` novas no cache curado.** Alimentam o tooltip e a memória de cálculo, para que numerador e denominador apareçam explicitamente na tela:

- `Trace::Custo de Crédito::PDD Crédito YTD`
- `Trace::Custo de Crédito::PDD Crédito Anualizada`
- `Trace::Custo de Crédito::Receita de Crédito YTD`

**Decisão de denominador em Peers.** O `Custo de Crédito (%)` do cache curado divide pela **mesma `Carteira de Crédito*` renderizada na linha acima na tabela**, e não por um denominador paralelo. Sem isso, a memória de cálculo mostraria um número que não fecha com o que o usuário vê na tela.

`CRITICAL_SCREENS_SCHEMA_VERSION` subiu de **4 para 5**. As versões 3 e 4 seguem aceitas em runtime, e `_derive_runtime_compatible_metrics` recompõe as razões novas a partir dos componentes quando o artefato local é antigo — sem nunca imputar zero.

---

## 4. Onde cada métrica aparece

| Aba | Como chega lá | Métricas |
|---|---|---|
| **Rankings** | `_anexar_metricas_derivadas_rankings` faz merge do cache derivado; só a métrica selecionada é lida | as três |
| **Peers (Tabela)** | seções novas *Custo de Crédito* e *Qualidade Carteira 4.966* em `PEERS_TABELA_LAYOUT` | as três + Inadimplência / Carteira Total |
| **Scatter Plot** | automático: `anexar_metricas_derivadas_periodo` pivota `DERIVED_METRICS` | as três (eixos X, Y e tamanho) |
| **Snapshot** | consome o mesmo cache curado de Peers | as três |
| **Glossário** | tabela de indicadores, com fonte, fórmula, interpretação e limitação | as três |

Em Peers, a tabela ganhou duas seções:

```
Balanço
Custo de Crédito                  ← nova
  Custo de Crédito (%)
  Custo de Crédito / Receita de Crédito (%)
Qualidade Carteira 4.966          ← nova
  Ativos Problemáticos / Carteira Total
  Inadimplência / Carteira Total
Qualidade Carteira 4060           (inalterada)
Alavancagem
Desempenho
```

A separação entre *4.966* e *4060* é deliberada: são fontes, perímetros e coberturas diferentes, e agrupá-las na mesma seção sugeriria comparabilidade que não existe.

### Base individual

`Custo de Crédito / Receita de Crédito (%)` funciona na base individual (o Rel. 4 individual existe). `Ativos Problemáticos / Carteira Total` fica **N/D** na base individual: não existe Relatório 16 individual, e a alternativa — herdar o valor consolidado — produziria um número errado. O mesmo tratamento que `Custo de Crédito (%)` já recebia por falta de Rel. 2 individual.

---

## 5. O que não foi implementado, e por quê

**As três razões de estágio do Cadoc 4060** — `Estágio 2 / Carteira`, `Estágio 3 / Carteira` e `Estágios 2+3 / Carteira` — ficaram de fora.

| Métrica | Cobertura em `1/2026` | Passa no critério? |
|---|---:|---|
| Estágio 2 / Carteira | 52 de 1.403 (3,7%) | não |
| Estágio 3 / Carteira | 54 de 1.403 (3,8%) | não |
| Estágios 2+3 / Carteira | 50 de 1.403 (3,6%) | não |
| *(com o gate de identidade proposto)* | 109 de 1.403 (7,8%) | ainda não |

Mesmo com o *gate de reconciliação* identificado na investigação de 17/08 — que dobraria a cobertura de 50 para 109 instituições — o resultado fica em 7,8% dos nomes, uma ordem de grandeza abaixo do corte de 1.000 IFs.

O motivo é estrutural, não de implementação: **só 159 conglomerados publicam a árvore 331 do Cadoc 4060**, e apenas 128 têm match prudencial confiável com o universo do app. A cobertura em saldo é alta (89% da carteira do SFN), mas a cobertura em nomes não permite análise da maioria das instituições.

`Ativos Problemáticos / Carteira Total` responde à mesma pergunta de negócio — qual a parcela deteriorada da carteira — com **1.075 instituições em vez de 109**, escopo estritamente de crédito e sem descasamento de perímetro. A linha existente `Ativos Estágio 3 / Carteira de Crédito` foi mantida em Peers, sem alteração, para quem precisar da leitura contábil por estágio.

---

## 6. Arquivos alterados

| Arquivo | Mudança |
|---|---|
| `utils/ifdata_cache/metric_registry.py` | duas `MetricDefinition` novas; `DERIVED_METRIC_KEYS` de 3 para 5 |
| `utils/ifdata_cache/derived_metrics.py` | constantes das métricas; `_carteira_instrumentos_lookup`; cálculo das duas razões; `df_carteira_instrumentos` em `build_derived_metrics` e no materializador |
| `utils/ifdata_cache/critical_screens.py` | `_build_desp_capt_lookup` → `_build_dre_ratios_lookup`; 2 colunas de métrica e 3 de trace; schema 4 → 5; backfill de runtime |
| `utils/ifdata_cache/release_ops.py` | `carteira_instrumentos` como fonte de `derived_metrics`; bloqueado no alvo individual |
| `utils/ifdata_cache/__init__.py` | reexporta as duas constantes |
| `tabs/peers_config.py` | duas seções novas; 4 verbetes de glossário; componentes de razão; `PEERS_TRACE_COMPONENTS` |
| `app1.py` | `_anexar_custo_credito_rankings` → `_anexar_metricas_derivadas_rankings` (aceita lista); indicadores e glossário de Rankings; recomputo curado em Peers; memória de cálculo; ajuda inline; tabela do Glossário |
| `tests/test_custo_credito_receita_e_problematicos.py` | **novo** — 25 testes |
| `tests/test_peers_exports.py` | contrato de seções e linhas atualizado |
| `data/bundled/derived_metrics/`, `data/bundled/critical_screens/` | parquets rematerializados |

### Refactor incluído

`_anexar_custo_credito_rankings` estava fixo em uma única métrica. Virou `_anexar_metricas_derivadas_rankings(df, periodos, metricas)`, que faz um pivot largo de qualquer conjunto de métricas derivadas. Sem isso, cada métrica nova exigiria uma cópia da função. A aba continua lendo **apenas a métrica selecionada** — carregar as três a cada troca de indicador varreria o parquet long inteiro sem necessidade.

### Testes

354 testes passam, incluindo os 25 novos. Os invariantes que valem a pena destacar:

- a razão PDD/Receita **não muda** quando numerador e denominador são escalados juntos (prova a ausência de anualização);
- ausência de Relatório 16 → N/D, nunca zero; zero publicado → 0%, nunca N/D;
- ausência de junho bloqueia Set e Dez;
- ausência da coluna `f3` (layout ≤ 2024) deixa as duas métricas de custo em N/D sem afetar a do Rel. 16;
- cache curado e cache derivado concordam em `Ativos Problemáticos / Carteira Total`;
- `PEERS_TRACE_COMPONENTS` não pode sair de sincronia com `PEERS_RATIO_COMPONENTS`.

---

## 7. Permanência dos dados

Os parquets rematerializados foram **commitados em `data/bundled/`**. O app resolve `arquivo_dados` preferindo o cache de runtime e caindo para o bundled (`utils/ifdata_cache/base.py:243`), então a partir do deploy desta branch as três métricas ficam disponíveis **sem download, sem recomputação e sem nenhuma ação manual**.

Republicar os assets do release `v1.1-cache` **não foi possível a partir desta sessão**: o proxy do ambiente bloqueia criação e edição de releases (`403 — Creating, editing, or deleting releases is not permitted for this session type`), independentemente do token. Isso não impede nada, porque o bundled já garante a permanência. Se você quiser mesmo assim atualizar o release, o caminho sem CLI é a aba **Atualizar Base** → *recalcular dependentes agora* → publicar, que usa o token já configurado nos secrets do Streamlit.
