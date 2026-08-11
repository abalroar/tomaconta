# Investigação de viabilidade — Custo de Crédito e Saldo por Estágios no menu Rankings

**Data:** 2026-08-11
**Commit investigado:** `de8a28f` (= `origin/main`, 16/07/2026)
**Escopo:** investigação apenas. Nenhum código, coluna ou aba foi criado ou alterado.
**Ambiente de verificação:** repositório local + assets do release `v1.1-cache` baixados para leitura.

---

## 0. Resumo executivo

| Pedido | Viável hoje? | Confiança nos dados | Bloqueio principal |
|---|---|---|---|
| **1. Ranking de Custo de Crédito** | **Sim** | **Alta** | Nenhum bloqueio de dado. Exige decisões metodológicas (anualização, denominador, quebra estrutural em 2025). |
| **2. Saldo por Carteira por Estágios** | **Não, como especificado** | **Baixa** | O "ativo" por estágio do Cadoc 4060 **não é carteira de crédito** (+117% de gap) e só existe para **51 de 1.403** instituições. |

**Defasagem temporal (Set-25):** não reproduzível no código. Todas as fontes que alimentam a aba Rankings vão até **Mar-26 (`1/2026`)**. Classificado como **indeterminado — requer validação no ambiente em execução** (detalhe na seção 3).

---

## 1. Tarefa 1 — Custo de Crédito (aba DRE)

### 1.1 Onde os dados estão

| Item | Localização exata |
|---|---|
| Cache | `dre` — `data/cache/dre/dados.parquet` (local) / asset `dre_dados.parquet` do release `v1.1-cache` |
| Fonte | BCB IFData **Relatório 4** (DRE), conglomerado prudencial |
| Registro de cache | `utils/ifdata_cache/relatorios_completos.py:404` (`nome="dre"`, `relatorio_tipo=4`) |
| Aba que consome | `app1.py:21021` — `menu == "DRE (Ind. e Congl.)" and dre_consolidada_tipo == "Conglomerado Prudencial"` |
| Versão individual | `app1.py:22207` (cache `dre_individual`) |
| Mapa de rubricas | `data/dre_mapping.json` e `data/dre_gerencial_mapping.json` |
| Colunas exigidas pelo cálculo | `utils/ifdata_cache/derived_metrics.py:60-68` (`DRE_REQUIRED_COLUMNS`) |

Dimensões verificadas do `dre_dados.parquet`: **62.061 linhas × 96 colunas**, **45 períodos** de `1/2015` a `1/2026`.

### 1.2 Nomes exatos das colunas — Despesa de PDD

Layout **IFData 2025+** (pós Res. 4.966). Todos os nomes abaixo são literais no parquet:

| Coluna | Papel |
|---|---|
| `Resultado com Perda Esperada (f)` | **Total** de perda esperada |
| `Resultado com Perda Esperada de Aplicações Interfinanceiras de Liquidez (f1)` | componente |
| `Resultado com Perda Esperada de TVM (f2)` | componente |
| **`Resultado com Perda Esperada de Operações de Crédito (f3)`** | **componente exclusivo de crédito** |
| `Resultado com Perda Esperada de Arrendamento (f4)` | componente |
| `Resultado com Perda Esperada de Outras Operações com Características de Concessão de Crédito (f5)` | componente |
| `Resultado com Perda Esperada de Outros Ativos Geradores de Renda (f6)` | componente |
| `Resultado com Perdas Esperadas de Outras Operações (q)` | fora da intermediação |
| `Resultados de Perda Esperada com Transações de Pagamento (l2)` | fora da intermediação |

**Identidade verificada:** `f = f1+f2+f3+f4+f5+f6` fecha exatamente em `1/2026` — `max|diferença| = 0,00` nas 1.403 instituições.

Layout **legado (≤ 2024):** `Resultado de Provisão para Créditos de Difícil Liquidação (b5)`. **Não existe abertura por tipo de ativo antes de 2025** — não há equivalente de `f3`.

### 1.3 Nomes exatos das colunas — Receita de Crédito

| Coluna | Papel |
|---|---|
| `Rendas de Operações de Crédito (c)` | **Total** (2025+) |
| `Receita de Juros com Operações de Crédito (c1)` | componente |
| `Ajuste de Variação Cambial de Operações de Crédito (c2)` | componente |
| `Ajuste a Valor Justo e Ajuste de Hedge de Valor Justo de Operações de Crédito (c3)` | componente |
| `Outros Resultados de Operações de Crédito (c4)` | componente |
| `Rendas de Arrendamento Financeiro (d)` | receita adjacente |
| `Rendas de Outras Operações com Características de Concessão de Crédito (e)` | receita adjacente |
| `Rendas de Operações de Crédito (a1)` | **legado (≤ 2024)** |

**Identidade verificada:** `c = c1+c2+c3+c4` fecha exatamente em `1/2026` — `max|diferença| = 0,00`.

### 1.4 Granularidade e cobertura

**Periodicidade:** trimestral, mas com **acumulação irregular** — este é o ponto metodológico mais importante.

O IFData 2025+ publica o Relatório 4 assim:
- `1/AAAA` (Mar) = 1T isolado
- `2/AAAA` (Jun) = 1S acumulado
- `3/AAAA` (Set) = **Jul–Set** (reinicia no semestre, não é YTD de 9 meses)
- `4/AAAA` (Dez) = **Jul–Dez** (2S acumulado)

Portanto `YTD(Set) = valor(Set) + valor(Jun)` e `YTD(Dez) = valor(Dez) + valor(Jun)`.

- Regra já implementada em `app1.py:9507` — `_compute_ytd_irregular_ifdata_frame()`, com `regra_ytd ∈ {raw_ifdata_mar_ou_jun, raw_ifdata_set_ou_dez_mais_jun, junho_ausente}`.
- Testes que fixam o comportamento: `tests/test_dre_ytd.py`.
- **Confirmação empírica** (`ITAU - PRUDENCIAL`, `Rendas de Operações de Crédito (c)`, R$ bi): `1/2025 = 30,73` · `2/2025 = 65,06` · `3/2025 = 38,49` · `4/2025 = 79,57` · `1/2026 = 35,20`. O valor de Set cai frente a Jun — comprova o reinício semestral.

**Cobertura por período** (instituições com valor não nulo):

| Período | `Resultado com Perda Esperada (f)` | `... de Operações de Crédito (f3)` | `Rendas de Op. de Crédito (c)` | `... (b5)` legado | `... (a1)` legado |
|---|---|---|---|---|---|
| 4/2024 | 0 | 0 | 0 | 1.373 | 1.373 |
| 1/2025 | 1.372 | 1.372 | 1.372 | 0 | 0 |
| 2/2025 | 1.380 | 1.380 | 1.380 | 0 | 0 |
| 3/2025 | 1.393 | 1.393 | 1.393 | 0 | 0 |
| 4/2025 | 1.406 | 1.406 | 1.406 | 0 | 0 |
| **1/2026** | **1.403** | **1.403** | **1.403** | 0 | 0 |

Cobertura de **100% da população** em todos os períodos do layout novo. **Quebra estrutural limpa em `1/2025`**: os campos novos e os legados nunca coexistem.

### 1.5 Fórmula mais plausível

A fórmula de mercado para "custo de crédito" (*cost of risk*) é despesa de provisão sobre carteira, anualizada:

```
Custo de Crédito (%) = |Resultado com Perda Esperada de Operações de Crédito (f3)|
                       ÷ Carteira de Crédito*
                       × fator de anualização
```

- **Numerador:** `f3` (crédito puro). Usar `f` (total) mistura provisão de TVM e aplicações interfinanceiras e infla o indicador para bancos com tesouraria grande.
- **Denominador:** `Carteira de Crédito*` — já é a métrica canônica do Ranking (`app1.py:18725`, alias resolvido em `_normalizar_indicadores_rankings`, `app1.py:15068`).
- **Fator de anualização:** deve seguir a regra irregular. Sobre o YTD reconstruído: Mar `×4`, Jun `×2`, Set `×(12/9)`, Dez `×1`. Sobre o valor bruto do trimestre isolado: `×4`.

**Prototipagem executada** (`1/2026`, `f3` anualizado `×4` ÷ `Carteira de Crédito*`):

| Instituição | Carteira (R$ bi) | f3 (R$ bi) | Custo de Crédito anualizado |
|---|---|---|---|
| CAIXA ECONÔMICA FEDERAL | 1.410,3 | −7,49 | 2,12% |
| ITAÚ | 1.272,6 | −9,72 | 3,06% |
| BB | 1.218,6 | −18,37 | 6,03% |
| BRADESCO | 953,1 | −9,23 | 3,87% |
| SANTANDER | 589,4 | −5,35 | 3,63% |
| BNDES | 420,9 | −0,32 | 0,30% |
| BTG PACTUAL | 225,6 | −1,55 | 2,75% |
| NU PAGAMENTOS | 194,4 | −7,38 | 15,19% |
| MERCADO PAGO IP | 83,1 | −6,42 | 30,92% |

Resultados coerentes com o perfil de risco conhecido de cada nome — o indicador se comporta como esperado. **1.064 de 1.403** instituições produzem valor válido (as demais têm carteira zero/nula, o que é correto: não se calcula custo de crédito sem carteira).

**Sobre "Despesa de PDD − Receita de Crédito":** não é padrão de mercado e não deve ser adotado. Subtrair dois fluxos de resultado com naturezas distintas produz um número sem interpretação econômica estabelecida. O que existe como padrão, e é sustentado pelos dados, é a **razão** `|f3| ÷ c` — leitura de "quanto da receita de crédito é consumida pela provisão". Prototipada: Caixa 19,0% · Itaú 27,6% · BB 51,4% · Bradesco 31,2% · Nubank 46,5% · Mercado Pago 82,4%. É um indicador complementar legítimo, mas **não é** o "custo de crédito".

**Já existe no app** um indicador vizinho: `Desp PDD / Resultado Intermediação Fin. Bruto` (`utils/ifdata_cache/derived_metrics.py:33`, cache `derived_metrics`), que usa `f` **total** no numerador e o resultado bruto de intermediação no denominador. É conceitualmente diferente do custo de crédito e não substitui o pedido.

---

## 2. Tarefa 2 — Saldo por Carteira por Estágios (aba Peers Tabela)

### 2.1 Como o campo "ativo" é dividido hoje

Origem: **Cadoc 4060** (Balancete/Balanço Geral Consolidado Prudencial), cache `bloprudencial` (`data/cache/bloprudencial/dados.parquet`, 1.061.577 linhas, períodos `202303`→`202603`).

Extração em `app1.py:9401-9403`:

| Conta COSIF | `NOME_CONTA` no 4060 | Campo no app |
|---|---|---|
| `3311000002` | ESTÁGIO 1 | `Carteira Estágio 1` |
| `3312000001` | ESTÁGIO 2 | `Ativos Estágio 2` |
| `3313000000` | ESTÁGIO 3 | `Ativos Estágio 3` |

Documentado na UI em `app1.py:16777-16779` e no Glossário em `app1.py:27120-27122`.
Filtro de documento em `app1.py:8790` — mantém apenas `DOCUMENTO == 4060`, descartando o `4066` que aparece junto nos arquivos de Jun/Dez (evitaria duplicação ~2x).

### 2.2 Os três estágios reconciliam entre si? **Sim, mas com um quarto bloco**

A conta-pai é `3310000003` — *Ativos Financeiros - Classificação por Estágios de Risco de Crédito*. Ela **não** é a soma de E1+E2+E3:

| Período | E1 | E2 | E3 | Simpl. Não-Probl. `3314000009` | Simpl. Probl. `3315000008` | **Soma** | **Pai `3310000003`** |
|---|---|---|---|---|---|---|---|
| 202509 | 14.467,84 | 395,40 | 534,82 | 141,42 | 11,46 | **15.550,94** | **15.550,94** |
| 202603 | 15.373,71 | 451,89 | 555,23 | 130,31 | 13,43 | **16.524,57** | **16.524,56** |

*(R$ bilhões, soma de todas as IFs do 4060)*

A identidade fecha **exatamente**. Conclusão: instituições que adotam a **metodologia simplificada** da Res. 4.966 reportam em `3314`/`3315` e **não reportam estágios**. Gap em Mar-26: **R$ 143,7 bi (0,87% do pai)**. Um gráfico de "3 estágios" omite esse bloco silenciosamente.

### 2.3 A soma dos estágios reconcilia com a Carteira de Crédito do Ranking? **Não**

Reconciliação feita com o dataset curado do próprio app (`data/bundled/critical_screens/dados.parquet`, período `1/2026`), que já resolve o pareamento instituição↔4060 pela mesma lógica de produção:

| Métrica | Valor |
|---|---|
| IFs com os 3 estágios simultâneos **e** `Carteira de Crédito*` | **51** |
| Σ (E1+E2+E3) | **R$ 16.315,6 bi** |
| Σ `Carteira de Crédito*` das mesmas 51 IFs | **R$ 7.520,0 bi** |
| **Gap** | **R$ 8.795,6 bi (+117,0%)** |
| Razão E123/Carteira — mediana | **1,93x** |

Casos individuais (Mar-26, R$ bi):

| Instituição | E1 | E2 | E3 | Σ | `Carteira de Crédito*` | Gap |
|---|---|---|---|---|---|---|
| ITAÚ | 2.926,3 | 67,7 | 61,7 | 3.055,7 | 1.272,6 | +140% |
| BB | 2.535,2 | 47,7 | 110,7 | 2.693,6 | 1.218,6 | +121% |
| CAIXA | 2.224,9 | 34,9 | 104,1 | 2.363,9 | 1.410,3 | +68% |
| BRADESCO | 2.024,1 | 49,8 | 83,9 | 2.157,8 | 953,1 | +126% |
| SANTANDER | 1.316,7 | 54,0 | 48,9 | 1.419,6 | 589,4 | +141% |
| BANCO SICOOB | 225,1 | 7,8 | 2,2 | 235,0 | 43,0 | +447% |
| XP | 162,5 | 1,6 | 0,9 | 165,1 | 37,5 | +341% |
| JP MORGAN | 105,5 | 0,5 | 0,0 | 106,0 | 2,7 | +3.825% |

### 2.4 Hipótese da divergência — estrutural, verificada na árvore de contas

A divergência **não é erro de pareamento nem de qualidade**. É definição de escopo, comprovada pela estrutura do 4060:

```
3300000006  INSTRUMENTOS FINANCEIROS E ARRENDAMENTO - RISCO DE CRÉDITO
├── 3310000003  Ativos Financeiros - Classificação por Estágios de Risco de Crédito
│   ├── 3311000002  ESTÁGIO 1
│   ├── 3312000001  ESTÁGIO 2
│   ├── 3313000000  ESTÁGIO 3
│   ├── 3314000009  METODOLOGIA SIMPLIFICADA - ATIVOS NÃO PROBLEMÁTICOS
│   └── 3315000008  METODOLOGIA SIMPLIFICADA - ATIVOS PROBLEMÁTICOS
├── 3320000000  Ativos Financeiros - Classificação por Carteiras de Provisão (C1..C5)
├── 3330000007  Créditos Baixados como Prejuízo
├── 3340000004  Compromissos de Crédito e Crédito a Liberar
└── 3350000001  Garantias Financeiras Prestadas
```

O objeto classificado é **"Ativos Financeiros"** sujeitos a perda esperada — o que inclui TVM a custo amortizado, aplicações interfinanceiras de liquidez, disponibilidades e outros recebíveis, **além** das operações de crédito. Não é "carteira de crédito".

Os casos extremos confirmam a leitura: JP Morgan (banco de atacado/tesouraria) tem E1 de R$ 105,5 bi contra carteira de R$ 2,7 bi; Sicoob/Sicredi consolidam ativos do sistema cooperativo muito além da carteira da entidade reportada no IFData.

**Não há desagregação mais fina na fonte.** Verificado diretamente no arquivo bruto `202509BLOPRUDENCIAL 2.CSV` (45.513 linhas): sob o prefixo `331` existem **apenas** as cinco contas acima — nenhum desdobramento por tipo de ativo ou por carteira de crédito. E o Relatório 2 do IFData (`ativo_dados.parquet`, 42 colunas) **não possui nenhuma coluna de estágio**.

### 2.5 Cobertura — o bloqueio prático

Em `1/2026`, sobre o universo de 1.403 instituições da aba Rankings:

| Corte | Instituições | % |
|---|---|---|
| Universo Rankings | 1.403 | 100% |
| Com match no BLOPRUDENCIAL (`Trace::Bloprudencial::Status == available`) | 128 | 9,1% |
| Sem match (`institution_match_missing`) | 1.275 | 90,9% |
| Com `Carteira Estágio 1` | 78 | 5,6% |
| Com `Ativos Estágio 2` | 55 | 3,9% |
| Com `Ativos Estágio 3` | 55 | 3,9% |
| **Com os três estágios simultâneos** | **51** | **3,6%** |

Contrapeso: essas 51 IFs concentram **R$ 7.520,0 bi de R$ 8.512,0 bi** de carteira do SFN — **88,3% do estoque**. Ou seja: cobre bem o topo, mas é inviável como *ranking* de 1.400 nomes.

---

## 3. Tarefa 3 — Defasagem temporal da aba Ranking

### 3.1 Processo responsável pela atualização

Documentado em `docs/diagnostico_fontes_aba_atualizar_base.md` §2 — linha "Rankings": caches `principal` (+ `capital`), pastas `data/cache/principal/` e `data/cache/capital/`.

Cadeia completa:

| Etapa | Arquivo / processo |
|---|---|
| Extração (API Olinda/IFData) | `utils/ifdata_cache/extractor.py` |
| Cache Rankings | `utils/ifdata_cache/principal.py` (`PrincipalCache`) · `utils/ifdata_cache/capital.py` |
| Orquestração via UI | aba **"Atualizar Base"** — `app1.py:25535` |
| Orquestração via CLI | `tools/update_caches_cli.py --tipo principal --tipo capital` |
| CLI com snapshot/rollback | `tools/refresh_cache_backend.py` |
| Distribuição | `utils/ifdata_cache/release_config.py` → tag `v1.1-cache`, assets `principal_dados.parquet` / `capital_dados.parquet` |
| Leitura pelo dropdown | `_get_rankings_filters_context()` — `app1.py:13935` → lê `metadata["periodos"]` do cache `principal` |
| Ordenação / default | `ordenar_periodos()` `app1.py:3841` · `_periodo_mais_recente()` `app1.py:3891` |

### 3.2 O que foi verificado

Nenhuma das três hipóteses do enunciado se confirma no commit `de8a28f`:

| Verificação | Resultado |
|---|---|
| `data/cache/principal/metadata.json` → `periodos` | contém `1/2026` (45 períodos) |
| `data/cache/principal/dados.parquet` → `1/2026` | **1.403 linhas**; `Carteira de Crédito`, `Patrimônio Líquido`, `Lucro Líquido YTD`, `Captações` com **100% de preenchimento** |
| `data/cache/capital/dados.parquet` → `1/2026` | 446 IFs com `Índice de Capital Principal` e `Índice de Capital Nível I` |
| Release `v1.1-cache` → `principal_metadata.json` | último período `1/2026` |
| Release → `dre_metadata.json`, `ativo_metadata.json` | último período `1/2026` |
| Release → `manifest.json` | `expected_periods.quarterly = "1/2026"` |
| Release → `bloprudencial_metadata.json` | último período `202603` |
| `data/bundled/critical_screens/dados.parquet` | inclui `1/2026` |
| Branch de trabalho vs `origin/main` | idênticos (`de8a28f`) |

**Conclusão: (a) não é limitação da fonte, (b) não é rotina que não cobre a aba, (c) não é dependência não executada.** O pipeline entregou Mar-26 e a aba lê exatamente esse metadado.

### 3.3 Classificação: indeterminado — requer validação manual no ambiente em execução

A defasagem não é reproduzível a partir do repositório. Hipóteses ordenadas por plausibilidade, todas verificáveis apenas no host:

1. **Estado local do deploy divergente do repositório (mais provável).**
   `PrincipalCache` tem `max_idade_horas = 168.0` (`utils/ifdata_cache/principal.py:30`) e o `timestamp_salvamento` do metadata é `2026-06-22`. Desde 29/06 o cache local é considerado expirado, o que faz `BaseCache.carregar()` (`utils/ifdata_cache/base.py:441`) ir ao remoto e, em caso de sucesso, **sobrescrever** `data/cache/principal/*` via `salvar_local()`.
   Como `data/cache/` está no `.gitignore` **mas os arquivos estão versionados** (`git ls-files data/cache/` retorna os parquets), essa sobrescrita deixa arquivos rastreados modificados no host — o que **bloqueia um deploy que atualiza por `git pull`** e congela a instância num cache anterior. É o único mecanismo encontrado capaz de produzir um teto de período arbitrário sem nenhuma alteração de código.
   *Verificar no host:* `git status --short data/cache/`, `stat -c '%y' data/cache/principal/dados.parquet`, e o campo `periodos` do `metadata.json` efetivamente em disco.

2. **Memoização de processo do Streamlit.**
   `_carregar_dados_periodos_preparados()` é `@st.cache_resource` sem TTL (`app1.py:14780`); `_get_rankings_filters_context()` é `@st.cache_data(ttl=900)` (`app1.py:13934`). A chave de invalidação é `mtime + size` do arquivo local (`_cache_file_token`, `app1.py:14703`). Se o arquivo em disco não mudou, nada invalida. Explica atraso, não um teto fixo em Set-25 — a menos que combinado com a hipótese 1.
   *Verificar:* reiniciar o app / "limpar cache" na aba Atualizar Base e reobservar o dropdown.

3. **Superfície observada diferente da suposta.**
   `Set/25` aparece com frequência em artefatos anteriores do projeto (`202509BLOPRUDENCIAL 2.CSV` na raiz, `docs/investigacao_perda_esperada_estagio3_bb_set25.md`, `docs/investigacao_dre_a1.md`). Vale confirmar se a observação veio da aba Rankings em produção ou de um export/print antigo.
   *Verificar:* screenshot do dropdown "períodos" da aba Rankings no ambiente atual.

---

## 4. Bloqueios técnicos encontrados

| # | Bloqueio | Severidade | Afeta |
|---|---|---|---|
| B1 | **Escopo do estágio ≠ carteira de crédito.** Cadoc 4060 classifica *Ativos Financeiros*; gap agregado de +117% (R$ 8.795,6 bi) vs `Carteira de Crédito*` em Mar-26. Sem desagregação na fonte. | **Alta** | Pedido 2 |
| B2 | **Cobertura de 3,6%.** Apenas 51 de 1.403 IFs têm os três estágios em Mar-26 (88,3% do estoque de carteira, mas 3,6% dos nomes). | **Alta** | Pedido 2 |
| B3 | **Metodologia simplificada omitida.** `3314`/`3315` (R$ 143,7 bi em Mar-26) ficam fora de um gráfico de 3 estágios; a soma dos estágios não fecha a conta-pai `3310000003`. | Média | Pedido 2 |
| B4 | **YTD irregular do Relatório 4.** Set e Dez reiniciam no semestre. Qualquer indicador novo de DRE que ignore `_compute_ytd_irregular_ifdata_frame` (`app1.py:9507`) produzirá erro grosseiro em 3T e 4T. | Média | Pedido 1 |
| B5 | **Quebra estrutural em 1/2025.** `f3` (PDD de crédito) não existe antes de 2025; o legado `b5` é PDD total sem abertura. Série histórica longa só é possível com métrica menos precisa e nota de quebra. | Média | Pedido 1 |
| B6 | **Defasagem Set-25 não reproduzível** — indeterminado, requer inspeção do host (seção 3.3). Se confirmada, qualquer indicador novo herda a mesma defasagem. | Média | Ambos |
| B7 | **`data/cache/` versionado apesar do `.gitignore`.** Risco operacional de sobrescrita pelo runtime bloqueando atualização por `git pull`. Contraria a recomendação do próprio `docs/diagnostico_fontes_aba_atualizar_base.md` §4.4. | Média | Infra |

---

## 5. Recomendação

### Pedido 1 — Custo de Crédito: **implementar**

Viável hoje, dados 100% cobertos de `1/2025` a `1/2026`, fórmula de mercado sustentada pelos campos existentes. Decisões a fechar antes:

1. **Numerador:** `f3` (crédito puro) — recomendado — ou `f` (total). Sugestão: `f3` como principal, `f` disponível como variante rotulada.
2. **Denominador:** `Carteira de Crédito*` de fim de período (simples, consistente com o resto do Ranking) ou carteira média `(t + t-1)/2` (mais correto tecnicamente, mas perde o primeiro período da série).
3. **Anualização:** Mar `×4`, Jun `×2`, Set `×(12/9)`, Dez `×1` sobre o YTD reconstruído.
4. **Horizonte:** iniciar em `1/2025` e sinalizar a quebra, ou não oferecer histórico pré-2025.

### Pedido 2 — Saldo por Estágios: **renegociar o escopo antes de implementar**

Como "Saldo **por Carteira** por Estágios" não é entregável com os dados atuais — o número exibido seria ~2x a carteira e induziria a erro. Três alternativas honestas, em ordem de preferência:

- **(A)** Renomear e reposicionar como **"Ativos Financeiros por Estágio de Risco (Cadoc 4060)"**, restrito às IFs com cobertura, com nota de escopo explícita e sem chamá-lo de carteira. Entregável em poucos dias.
- **(B)** Usar a classificação **C1–C5 do Relatório 16** (`Carteira Total 4.966`, `carteira_instrumentos`), que **é** carteira de crédito e tem cobertura de **1.104 IFs** em Mar-26 — se a intenção da chefe for "qualidade da carteira por faixa de risco", esta é a fonte correta.
- **(C)** Manter estágios apenas como **ratio** já existente (`Ativos Estágio 3 / Carteira de Crédito`, `Perda Esperada / Estágio 3`), sem expor o saldo absoluto.

**Recomendação:** (A) + (B) combinados — o saldo por estágio como visão de risco de crédito sobre ativos financeiros, e o C1–C5 como visão de carteira. Levar as duas opções à chefe antes de codificar.

---

## 6. Rastreabilidade — índice de verificações

| Afirmação | Onde foi verificada |
|---|---|
| Colunas de PDD e Receita de Crédito | `dre_dados.parquet` (release `v1.1-cache`), 96 colunas |
| Identidades `f = Σfi` e `c = Σci` | cálculo sobre `1/2026`, 1.403 IFs, `max\|dif\| = 0,00` |
| YTD irregular | `app1.py:9507-9544`; `tests/test_dre_ytd.py`; série ITAÚ 2025 |
| Contas de estágio | `app1.py:9401-9403`; `app1.py:16777-16779`; `app1.py:27120-27122` |
| Árvore de contas do 4060 | `data/cache/bloprudencial/dados.parquet` e `202509BLOPRUDENCIAL 2.CSV` (raiz) |
| Identidade da conta-pai `3310000003` | soma por período `202509` e `202603` |
| Gap estágios vs carteira | `data/bundled/critical_screens/dados.parquet`, `1/2026` |
| Cobertura por instituição | `Trace::Bloprudencial::Status` em `critical_screens`, `1/2026` |
| Ausência de estágio no Rel. 2 | `ativo_dados.parquet`, 42 colunas |
| Períodos das fontes do Ranking | `data/cache/{principal,capital}/metadata.json` + assets do release |
| `expected_periods` do release | `manifest.json` do release `v1.1-cache` |
| Mapa aba→cache | `docs/diagnostico_fontes_aba_atualizar_base.md` §2 |
| Expiração de cache e sobrescrita | `utils/ifdata_cache/principal.py:30`; `utils/ifdata_cache/base.py:441-470` |
