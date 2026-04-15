# Investigação técnica da aba DRE/TRE

Data: 2026-04-15  
Escopo: diagnóstico da aba `DRE (Ind. e Congl.)`, com foco na ramificação `Conglomerado Prudencial` da interface.  
Observação de nomenclatura: no código e na UI atual, o nome correto é **DRE**. Não encontrei uma aba separada chamada `TRE`; neste relatório, `DRE/TRE` foi normalizado para **DRE consolidada**.

## Resumo executivo

Foram confirmados **dois problemas independentes e materiais** na DRE consolidada:

1. **Quebra de renderização em Dez/2025**  
   A quebra não está na fonte bruta nem no render HTML final. Ela ocorre antes, na camada de **mapeamento de colunas**. A base `dre` mudou de schema entre `3/2025` e `4/2025`, e a aba continua usando um mapeamento rígido com os nomes antigos.  
   Resultado: as linhas a partir de `Desp. PDD Outras Operações` deixam de ser populadas em `4/2025`, apesar de os dados existirem na base bruta.

2. **Lucro líquido acumulado incorreto em Set/2025**  
   A regra correta é acumular o semestre: **Jun raw + Set raw**. A base bruta do Itaú confirma isso. O problema está na função `_compute_ytd_irregular_ifdata_frame` em [app1.py](/Users/matheusjprates/tomaconta/app1.py:7622): ela calcula uma máscara booleana antes de um `merge` e reaplica essa máscara depois, sobre um dataframe reindexado.  
   Resultado: o YTD fica **cru** em várias linhas de Set/Dez. No caso do lucro do Itaú em `3/2025`, a aba acaba ficando perto de `11,77 bi` em vez de `34,40 bi`.

Achado adicional importante:

- O problema do YTD **não é exclusivo do lucro**. Comparando a função atual com uma recomputação index-safe, encontrei **40.212 linhas divergentes em 2025** dentro da DRE consolidada mapeada.  
- A base DRE tem **duas famílias de schema**:
  - `2015–2024`: estrutura detalhada `a1..j`
  - `2025`: estrutura nova `a..aa`, com uma segunda mudança em `4/2025`, quando o bloco final desloca letras (`r/x/z` etc.)
- Para uma futura DRE ajustada, a base oficial do BC é **mais rica do que a aba atual mostra**, mas a comparabilidade com a planilha manual muda muito entre `<=2024` e `2025+`.

---

## 1) Cadeia de dados auditada

### 1.1 Fluxo consolidado observado no código

Ramificação auditada:

- menu `DRE (Ind. e Congl.)` com tipo `Conglomerado Prudencial` em [app1.py](/Users/matheusjprates/tomaconta/app1.py:19762)

Fluxo principal:

1. Carregamento do cache bruto `dre` via `load_dre_data()`
2. Mapeamento de linhas via `load_dre_mapping()` hardcoded em [app1.py](/Users/matheusjprates/tomaconta/app1.py:19860)
3. Construção de `df_valores` em `_build_dre_base(...)` em [app1.py](/Users/matheusjprates/tomaconta/app1.py:20197)
4. Reconstrução YTD via `_compute_ytd_irregular_ifdata_frame(...)` em [app1.py](/Users/matheusjprates/tomaconta/app1.py:7622)
5. Cálculo YoY em `compute_yoy(...)`
6. Concatenação com métricas derivadas
7. Renderização final em `render_table_like_carteira_4966(...)` em [app1.py](/Users/matheusjprates/tomaconta/app1.py:20300)

### 1.2 Observação importante sobre mapeamentos

O repositório já possui um arquivo versionado com tentativa de dualidade old/new:

- [data/dre_mapping.json](/Users/matheusjprates/tomaconta/data/dre_mapping.json)

Porém:

- a **DRE consolidada atual não usa esse arquivo**; ela usa `load_dre_mapping()` hardcoded em `app1.py`
- mesmo o `data/dre_mapping.json` está **incompleto para `4/2025`**, porque ainda aponta para `s/t/u/v/y/z/aa`, enquanto a base real de `4/2025` usa `r/s/t/u/x/y/z`

Conclusão:

- há hoje **duas fontes de verdade de mapeamento** para DRE, nenhuma delas completamente atualizada para `4/2025`

---

## 2) Diagnóstico do problema de Dez/2025

### 2.1 Sintoma observado

Na aba DRE consolidada, em `4/2025`, os valores aparecem até:

- `Desp. PDD Outras Operações`

E as linhas abaixo deixam de ser populadas.

### 2.2 Linhas afetadas

As linhas que deixam de aparecer a partir dali são:

- `Desp. JSCP Cooperativas`
- `Desp. Tributárias`
- `Res. Participação Controladas`
- `Outras Receitas`
- `Outras Despesas`
- `IR/CSLL`
- `Res. Participação Lucro`
- `Lucro Líquido Período Acumulado`

Observação refinada após a implementação:

- em `4/2025`, `Desp. JSCP Cooperativas` não está apenas mal mapeada; a linha está **efetivamente ausente na fonte bruta** desse período
- já as demais linhas do bloco final continuam existindo, mas sob **novos códigos/letras**

### 2.3 Evidência objetiva na base bruta

Contraste entre `3/2025` e `4/2025`:

#### `3/2025`

Para `1393/1393` instituições:

- `Despesas Tributárias (s)` preenchido
- `Imposto de Renda e Contribuição Social (y)` preenchido
- `Lucro Líquido (aa) = (x) + (y) + (z)` preenchido

#### `4/2025`

Para `1406/1406` instituições:

- `Despesas de Juros Sobre Capital Próprio de Cooperativas (r)` = `0/1406`
- `Despesas Tributárias (s)` = `0/1406`
- `Despesas Tributárias (r)` = `1406/1406`
- `Resultado de Participações (t)` = `0/1406`
- `Resultado de Participações (s)` = `1406/1406`
- `Outras Receitas (u)` = `0/1406`
- `Outras Receitas (t)` = `1406/1406`
- `Outras Despesas (v)` = `0/1406`
- `Outras Despesas (u)` = `1406/1406`
- `Imposto de Renda e Contribuição Social (y)` = `0/1406`
- `Imposto de Renda e Contribuição Social (x)` = `1406/1406`
- `Participações no Lucro (z)` = `0/1406`
- `Participações no Lucro (y)` = `1406/1406`
- `Lucro Líquido (aa) = (x) + (y) + (z)` = `0/1406`
- `Lucro Líquido (z) = (w) + (x) + (y)` = `1406/1406`

### 2.4 Causa raiz confirmada

Causa raiz confirmada: **mudança de schema da base DRE em `4/2025` + mapeamento rígido desatualizado na aba**.

Com nuance:

- `Desp. JSCP Cooperativas` ficou indisponível porque a fonte de `4/2025` não traz essa linha preenchida
- as demais linhas do bloco final ficaram indisponíveis na aba por **mapeamento stale**, apesar de existirem na base

Onde a perda acontece:

1. `load_dre_mapping()` usa fontes antigas:
   - `Despesas Tributárias (s)`
   - `Resultado de Participações (t)`
   - `Outras Receitas (u)`
   - `Outras Despesas (v)`
   - `Imposto de Renda e Contribuição Social (y)`
   - `Participações no Lucro (z)`
   - `Lucro Líquido (aa) = (x) + (y) + (z)`

2. `_build_dre_base(...)` em [app1.py](/Users/matheusjprates/tomaconta/app1.py:20215) resolve colunas com `find_column(...)`

3. Para `4/2025`, essas fontes não resolvem porque a base real deslocou as letras

4. Quando `colunas` fica vazio, a linha entra em:
   - `if not colunas: continue`

5. A linha não entra em `df_valores`

6. Logo, não chega a `df_ytd`, nem ao `render_table_like_carteira_4966(...)`

### 2.5 O que **não** é a causa

Com evidência:

- **não é ausência de dado na fonte**
- **não é erro de extração**
- **não é erro de merge**
- **não é erro de pivot**
- **não é erro do HTML da tabela**

É um **erro de mapeamento/seleção de coluna**, anterior à renderização.

### 2.6 Evidência concreta com Itaú

Em `4/2025`, para `ITAU - PRUDENCIAL`:

- `Despesas Tributárias (r)` = `-4,669 bi`
- `Resultado de Participações (s)` = `3,971 bi`
- `Outras Receitas (t)` = `62,008 bi`
- `Outras Despesas (u)` = `-56,292 bi`
- `Imposto de Renda e Contribuição Social (x)` = `-0,957 bi`
- `Participações no Lucro (y)` = `-5,561 bi`
- `Lucro Líquido (z) = (w) + (x) + (y)` = `24,089 bi`

Todos esses campos existem na base bruta, mas a aba atual continua procurando:

- `... (s)/(t)/(u)/(v)/(y)/(z)/(aa)` da estrutura anterior

---

## 3) Diagnóstico do problema de acumulado em Set/2025 e Dez/2025

### 3.1 Regra de negócio correta

Pelo comportamento da base do BC:

- `1/2025` = trimestre/semestre inicial do ano
- `2/2025` = acumulado Jan–Jun
- `3/2025` = bloco do segundo semestre acumulado até Set
- `4/2025` = bloco do segundo semestre acumulado até Dez

Para construir o **acumulado anual (YTD)**:

- `Mar` -> usar valor cru de `1/2025`
- `Jun` -> usar valor cru de `2/2025`
- `Set` -> `Jun cru + Set cru`
- `Dez` -> `Jun cru + Dez cru`

### 3.2 Caso de referência: Itaú Unibanco

Valores brutos observados na base:

- `1/2025`: `11,133 bi`
- `2/2025`: `22,630 bi`
- `3/2025`: `11,772 bi`
- `4/2025`: `24,089 bi` (na nova coluna `Lucro Líquido (z) = (w) + (x) + (y)`)

Acumulados corretos esperados:

- `Set/2025` YTD = `22,630 bi + 11,772 bi = 34,402 bi`
- `Dez/2025` YTD = `22,630 bi + 24,089 bi = 46,719 bi`

### 3.3 Onde a lógica falha

Função afetada:

- `_compute_ytd_irregular_ifdata_frame(...)` em [app1.py](/Users/matheusjprates/tomaconta/app1.py:7622)

Trecho relevante:

1. A função cria `mask_set_dez = out["mes"].isin([9, 12])`
2. Depois faz `out = out.merge(jun, on=keys, how="left")`
3. Em seguida reaplica a **máscara antiga**:
   - `out.loc[mask_set_dez, "ytd"] = ...`

Problema:

- `mask_set_dez` foi calculada **antes** do `merge`
- o `merge` produz um dataframe novo, com novo índice
- a máscara antiga é reaplicada em um dataframe reindexado

Isso torna a atribuição **dependente do alinhamento incidental do índice**, e não da linha correta.

### 3.4 Evidência objetiva do erro

Comparando a função atual com uma recomputação idêntica, porém **index-safe**, para a linha `Lucro Líquido Período Acumulado`:

- divergências em `2025`: **1.970 linhas**

Para o Itaú:

- valor atual em `3/2025` após a função atual: `11,772 bi`
- valor correto com recomputação index-safe: `34,402 bi`

Comparando a DRE mapeada inteira:

- divergências totais em `2025`: **40.212 linhas**

Rótulos mais afetados:

- `Desp. Adm`
- `Resultado Int. Financeira Líquido`
- `Resultado de Intermediação Financeira Bruto`
- `Desp. Pessoal`
- `Desp. PDD`
- `Rec. Crédito`
- `Outras Prestações de Serviços`
- `Lucro Líquido Período Acumulado`

### 3.5 Causa raiz confirmada

Causa raiz principal confirmada: **bug de alinhamento de índice na função de YTD**.

### 3.6 Relação com Dez/2025

Para `4/2025`, existem **dois problemas encadeados**:

1. **mapeamento quebrado**: a linha de lucro nem entra com a coluna correta (`z`, não `aa`)
2. **mesmo com o mapeamento corrigido**, a função atual de YTD ainda precisaria ser consertada para somar corretamente `Jun + Dez`

Portanto:

- setembro está errado por bug de YTD
- dezembro está hoje duplamente comprometido: **mapeamento + YTD**

---

## 4) Evidências coletadas

### 4.1 Evidência de transição de schema

Famílias de schema observadas no cache bruto `data/cache/dre/dados.parquet`:

- `2015–2024`: estrutura detalhada `a1..j`
- `1/2025–3/2025`: estrutura nova `a..aa`
- `4/2025`: estrutura nova com bloco final deslocado:
  - `r/s/t/u/x/y/z`
  - agregador final muda para `Lucro Líquido (z) = (w) + (x) + (y)`

### 4.2 Evidência de cobertura por período

Colunas detalhadas antigas:

- `Rendas de Operações de Crédito (a1)` -> preenchida até `4/2024`
- `Despesas de Captação (b1)` -> preenchida até `4/2024`
- `Resultado Operacional (e) = (c) + (d)` -> preenchida até `4/2024`
- `Resultado Não Operacional (f)` -> preenchida até `4/2024`
- `Lucro Líquido (j) = (g) + (h) + (i)` -> preenchida até `4/2024`

Colunas da DRE nova:

- `Rendas de Aplicações Interfinanceiras de Liquidez (a)` -> `1/2025..4/2025`
- `Despesas de Captações (g)` -> `1/2025..4/2025`
- `Resultado com Transações de Pagamento (l)` -> `1/2025..4/2025`
- `Lucro Líquido (aa)` -> apenas `1/2025..3/2025`
- `Lucro Líquido (z)` -> apenas `4/2025`

### 4.3 Evidência de granularidade útil para uma DRE ajustada futura

Em `4/2025`, para os 10 maiores bancos, a base traz `10/10` preenchimento para:

- `Despesa de Juros com Captações (g1)`
- `Ajuste de Variação Cambial de Captações (g2)`
- `Ajuste de Hedge de Valor Justo de Captações (g3)`
- `Outros Resultados de Captações (g4)`
- `Resultado com Serviços por Transações de Pagamento (l1)`
- `Resultados de Perda Esperada com Transações de Pagamento (l2)`
- `Outros Resultados com Transações de Pagamento (l3)`
- `Rendas de Tarifas Bancárias (m)`
- `Outras Rendas de Prestação de Serviços (n)`

Ou seja:

- a base oficial é **mais rica** do que a aba atual usa
- mas a estrutura **não é a mesma** da planilha manual

---

## 5) Estudo comparativo: DRE oficial do BC vs planilha manual de spread

### 5.1 Bancos usados no confronto

Top 10 por `Ativo Total` em `4/2025`:

- ITAU - PRUDENCIAL
- BB - PRUDENCIAL
- CAIXA ECONÔMICA FEDERAL - PRUDENCIAL
- BRADESCO - PRUDENCIAL
- SANTANDER - PRUDENCIAL
- BNDES - PRUDENCIAL
- BTG PACTUAL - PRUDENCIAL
- NU PAGAMENTOS - PRUDENCIAL
- XP - PRUDENCIAL
- SAFRA - PRUDENCIAL

### 5.2 Estrutura observável da planilha manual (imagem)

Linhas principais visíveis na planilha manual:

- Receitas Interm. Financeira
  - Operações de Crédito
  - Fianças e Garantias
  - Títulos e Val. Mobiliários
  - Derivativos
  - Carteira Câmbio
- Despesas Interm. Financeira
  - Captação de Mercado
  - Empréstimos e Repasses
- Resultado Interm. Financeira Bruto
- Provisões
- Resultado Líq Interm. Financeira
- Outras Rec./Desp. Operac.
  - Receitas de Serviços
  - Despesas Administrativas
  - Gastos de Pessoal
  - Tributos
  - Res. Part. Coligadas
  - Outras Receitas/Despesas
- Resultado Operacional
- Res. Não Operacional
- Participações no resultado
- I.R. / C.S.
  - I.R.
  - C.S.
  - Ativo Fiscal Diferido

### 5.3 Matriz de cobertura direta na base oficial (top 10 bancos)

Cobertura direta observada para os 10 maiores bancos:

| Linha manual | 4/2024 | 4/2025 |
|---|---:|---:|
| Operações de Crédito | 10/10 | 10/10 |
| TVM | 10/10 | 10/10 |
| Derivativos | 10/10 | 10/10 |
| Câmbio | 10/10 | 0/10 (sem linha direta) |
| Captação de Mercado | 10/10 | 10/10 |
| Empréstimos e Repasses | 10/10 | 0/10 (sem linha direta) |
| Receitas de Serviços | 10/10 | 10/10 |
| Tarifas Bancárias | 10/10 | 10/10 |
| Gastos de Pessoal | 10/10 | 10/10 |
| Despesas Administrativas | 10/10 | 10/10 |
| Tributos | 10/10 | 10/10 |
| Part. Coligadas/Controladas | 10/10 | 10/10 |
| Outras Receitas | 10/10 | 10/10 |
| Outras Despesas | 10/10 | 10/10 |
| Resultado Operacional | 10/10 | 0/10 (sem linha direta) |
| Resultado Não Operacional | 10/10 | 0/10 (sem linha direta) |
| IR/CSLL | 10/10 | 10/10 |
| Participações no Lucro | 10/10 | 10/10 |
| Lucro Líquido | 10/10 | 10/10 |

### 5.4 Diferenças relevantes de classificação e granularidade

#### A. Operações de Crédito

- **BC antigo (`<=2024`)**: `Rendas de Operações de Crédito (a1)`
- **BC 2025+**: `Rendas de Operações de Crédito (c)`
- **Situação**: comparável e direta

#### B. Fianças e Garantias

- **Não encontrei linha direta** na base oficial atual
- **Situação**: ausente na base oficial disponível no Toma Conta
- **Implicação**: a DRE ajustada futura não pode inventar essa linha sem outra fonte

#### C. Títulos e Valores Mobiliários

- **BC antigo**: `Rendas de Operações com TVM (a3)`
- **BC 2025+**: `Rendas de Títulos e Valores Mobiliários (b)`
- **Situação**: comparável e direta

#### D. Derivativos

- **BC antigo**: `Rendas de Operações com Instrumentos Financeiros Derivativos (a4)`
- **BC 2025+**: `Resultado com Derivativos (i)`
- **Situação**: direta, mas a semântica pode mudar de “renda” para “resultado”

#### E. Carteira Câmbio

- **BC antigo**: `Resultado de Operações de Câmbio (a5)` direto
- **BC 2025+**: não há linha direta equivalente
- **Situação**: quebra de comparabilidade estrutural
- **Implicação**: em `2025+`, câmbio parece estar absorvido em outras linhas de intermediação, não isolado

#### F. Captação de Mercado

- **BC antigo**: `Despesas de Captação (b1)`
- **BC 2025+**: `Despesas de Captações (g)` e também `g1..g4`
- **Situação**: direta e até mais rica em 2025+, mas a aba atual usa só o agregado
- **Implicação**: a DRE ajustada futura pode separar juros, variação cambial, hedge e outros resultados de captação

#### G. Empréstimos e Repasses

- **BC antigo**: `Despesas de Obrigações por Empréstimos e Repasses (b2)` direto
- **BC 2025+**: sem linha direta
- **Situação**: quebra de comparabilidade estrutural

#### H. Provisões

- **BC antigo**: `Resultado de Provisão para Créditos de Difícil Liquidação (b5)`
- **BC 2025+**: `Resultado com Perda Esperada (f)` e `Resultado com Perdas Esperadas de Outras Operações (q)`
- **Situação**: parcialmente comparável, mas `2025+` já separa “outras operações”
- **Implicação**: a planilha manual precisará decidir se `Provisões` inclui só crédito (`f`) ou também outras operações (`q`)

#### I. Receitas de Serviços

- **BC antigo**: `Rendas de Prestação de Serviços (d1)` + `Rendas de Tarifas Bancárias (d2)`
- **BC 2025+**:
  - `Rendas de Tarifas Bancárias (m)`
  - `Outras Rendas de Prestação de Serviços (n)`
  - `Resultado com Transações de Pagamento (l)` e sublinhas `l1..l3`

- **Situação crítica**:
  - a linha manual sugere **receita**
  - `Resultado com Transações de Pagamento (l)` é **resultado líquido**, não receita bruta

- **Implicação**:
  - somar `l + m + n` para chamar de `Receitas de Serviços` seria potencialmente enganoso
  - para `2025+`, a linha manual precisa de decisão conceitual explícita

#### J. Despesas Administrativas

- **BC antigo**: `Despesas Administrativas (d4)`
- **BC 2025+**: `Despesas Administrativas (p)`
- **Situação**: direta

#### K. Gastos de Pessoal

- **BC antigo**: `Despesas de Pessoal (d3)`
- **BC 2025+**: `Despesas de Pessoal (o)`
- **Situação**: direta

#### L. Tributos

- **BC antigo**: `Despesas Tributárias (d5)`
- **BC 2025+**: existe linha direta, mas muda de código/letra entre `1–3/2025` e `4/2025`
- **Situação**: direta, porém afetada hoje pela quebra de mapping da aba

#### M. Resultado de Participações / Coligadas

- **BC antigo**: `Resultado de Participações (d6)`
- **BC 2025+**: linha direta existe, mas troca de `t` para `s` em `4/2025`
- **Situação**: direta, mas hoje quebrada na aba em `4/2025`

#### N. Outras Receitas / Despesas

- **BC antigo**:
  - `Outras Receitas Operacionais (d7)`
  - `Outras Despesas Operacionais (d8)`
- **BC 2025+**:
  - `Outras Receitas (t)`
  - `Outras Despesas (u)`
  - agregadores `v/w`

- **Situação**: comparável por blocos, mas não idêntica

#### O. Resultado Operacional

- **BC antigo**: linha direta `Resultado Operacional (e) = (c) + (d)`
- **BC 2025+**: **sem linha direta**
- **Situação**: precisa ser reconstruído por regra

#### P. Resultado Não Operacional

- **BC antigo**: linha direta `Resultado Não Operacional (f)`
- **BC 2025+**: **sem linha direta**
- **Situação**: não comparável diretamente

#### Q. IR / CS

- **BC antigo**: `Imposto de Renda e Contribuição Social (h)`
- **BC 2025+**: linha total existe, mas muda de `y` para `x` em `4/2025`
- **Situação**: total comparável

#### R. IR, CS e Ativo Fiscal Diferido separados

- **Não encontrei linhas separadas** para:
  - IR
  - CS
  - Ativo Fiscal Diferido

- **Situação**: a planilha manual tem granularidade maior do que a fonte oficial disponível no app

### 5.5 Conclusão do estudo comparativo

Para a futura DRE ajustada:

- **até 2024**, a base oficial do BC está **muito mais próxima** da estrutura da planilha manual
- **em 2025+**, há duas mudanças:
  1. a taxonomia da DRE muda
  2. parte dos subtotais clássicos (`Resultado Operacional`, `Resultado Não Operacional`, `Empréstimos e Repasses`, `Câmbio`) deixa de existir como linha direta

Logo:

- a futura DRE ajustada **não pode ser tratada como simples re-rotulagem da DRE oficial**
- ela vai precisar de **regras de reconstrução por período/schema**
- e haverá linhas da planilha manual que **não poderão ser reproduzidas fielmente** sem nova fonte externa ou convenção explícita

---

## 6) Causa raiz confirmada e hipóteses ordenadas

### 6.1 Problema Dez/2025

**Causa raiz confirmada**:

- stale mapping hardcoded no `load_dre_mapping()` da DRE consolidada
- perda dos dados em `_build_dre_base(...)`

### 6.2 Problema de acumulado em Set/2025

**Causa raiz principal confirmada**:

- bug de máscara/índice em `_compute_ytd_irregular_ifdata_frame(...)`

### 6.3 Problema de acumulado em Dez/2025

**Hipótese principal confirmada em duas camadas**:

1. o lucro não entra porque o mapeamento procura `aa`, mas o dado está em `z`
2. corrigido o mapeamento, a função atual de YTD ainda precisará ser corrigida para devolver `Jun + Dez`

### 6.4 Hipóteses secundárias descartadas

Descartadas com evidência:

- ausência de dado na fonte
- falha de extração
- falha de merge final da aba
- falha do render HTML
- problema localizado apenas no Itaú

---

## 7) Plano de correção recomendado

### 7.1 P0 — Corrigir o resolvedor de colunas da DRE consolidada

Objetivo:

- fazer a DRE consolidada resolver corretamente:
  - schema antigo `2015–2024`
  - schema novo `1/2025–3/2025`
  - schema novo deslocado `4/2025`

Abordagem recomendada:

- sair do `load_dre_mapping()` hardcoded com fonte única por linha
- usar um mapping declarativo por linha com **variantes de fonte**
- resolver por:
  1. fonte direta válida na linha/período
  2. conflito explícito se mais de uma variante vier preenchida
  3. indisponibilidade explícita se nenhuma vier preenchida

Regra importante:

- **não somar variantes**
- **não fazer fallback silencioso por substring**

Pontos de revisão:

- [app1.py](/Users/matheusjprates/tomaconta/app1.py:19860) `load_dre_mapping()`
- [app1.py](/Users/matheusjprates/tomaconta/app1.py:20215) construção `fonte_para_coluna`
- [data/dre_mapping.json](/Users/matheusjprates/tomaconta/data/dre_mapping.json)

### 7.2 P0 — Corrigir `_compute_ytd_irregular_ifdata_frame(...)`

Objetivo:

- eliminar o bug de alinhamento de índice

Abordagem recomendada:

- recalcular a máscara **depois** do `merge`, ou
- resetar índice antes do merge e trabalhar com index novo, ou
- substituir o `merge` por um `map` explícito do valor de junho por chave

Regra correta:

- Mar = raw
- Jun = raw
- Set = Jun + Set
- Dez = Jun + Dez
- se junho não existir, Set/Dez = `NaN` e não zero

Pontos de revisão:

- [app1.py](/Users/matheusjprates/tomaconta/app1.py:7622)

### 7.3 P0 — Separar semanticamente `valor_raw_periodo` de `valor_ytd`

Objetivo:

- impedir que a UI misture valor cru do semestre com valor acumulado anual

Abordagem recomendada:

- manter ambos no dataframe final
- o toggle `Lucro Líquido Acumulado` vs `Lucro Líquido Trimestral` deve operar sobre colunas semanticamente distintas

### 7.4 P1 — Tornar a quebra de schema auditável

Objetivo:

- detectar automaticamente mudanças futuras na nomenclatura da fonte DRE

Abordagem:

- validação por período:
  - se `3/2025` usa `aa`, `4/2025` não pode continuar exigindo `aa`
  - se `4/2025` tem `z`, a materialização deve acusar quando o mapping ainda procurar `aa`

### 7.5 P1 — Preparar base para futura DRE ajustada

Objetivo:

- construir uma camada intermediária que preserve:
  - linha oficial do BC
  - subcomponentes disponíveis
  - schema family (`old_2015_2024`, `new_2025_q1_q3`, `new_2025_q4_shifted`)

Sem isso, a DRE ajustada vai nascer com reconciliações frágeis.

---

## 8) Proposta de testes

### 8.1 Testes para Dez/2025

- Validar que `4/2025` popula as linhas abaixo de `Desp. PDD Outras Operações`
- Casos mínimos:
  - Itaú
  - Bradesco
  - Banco do Brasil
- Critério de aceite:
  - `Desp. Tributárias`
  - `Res. Participação Controladas`
  - `Outras Receitas`
  - `Outras Despesas`
  - `IR/CSLL`
  - `Res. Participação Lucro`
  - `Lucro Líquido Período Acumulado`
  todas presentes e reconciliadas com a coluna bruta correta

### 8.2 Testes para lucro acumulado

Casos mínimos:

- Itaú `3/2025`
  - raw = `11,772 bi`
  - Jun = `22,630 bi`
  - YTD esperado = `34,402 bi`

- Itaú `4/2025`
  - raw harmonizado = `24,089 bi`
  - Jun = `22,630 bi`
  - YTD esperado = `46,719 bi`

### 8.3 Testes de não regressão

- `3/2025` continua usando `aa/y/s/t/u/v`
- `4/2025` usa `z/x/r/s/t/u`
- `4/2024` continua usando a família antiga `a1..j`

### 8.4 Testes estruturais

- nenhuma linha pode ser descartada apenas porque a variante A do schema ficou vazia se a variante B do mesmo período estiver preenchida
- se duas variantes conflitantes vierem preenchidas ao mesmo tempo, o teste deve falhar e exigir decisão explícita

---

## 9) Recomendações acionáveis

1. **Corrigir primeiro o mapeamento de `4/2025`**, porque hoje a metade final da DRE não chega à tabela.
2. **Corrigir imediatamente o motor YTD**, porque ele está afetando o lucro e outras linhas em 2025.
3. **Não implementar a DRE ajustada antes de estabilizar a DRE oficial**, senão a camada ajustada herdará dois erros de base.
4. **Adotar um mapping declarativo por família de schema**, em vez de manter fontes hardcoded em `app1.py`.
5. **Tratar `2025+` como regime metodológico diferente de `<=2024`** na futura DRE ajustada.
6. **Não chamar `Resultado com Transações de Pagamento` de `Receitas de Serviços` sem decisão contábil explícita**, porque o dado é de resultado líquido, não receita bruta.
7. **Assumir desde já que algumas linhas da planilha manual não têm equivalência direta em `2025+`**:
   - Fianças e Garantias
   - Empréstimos e Repasses
   - Carteira Câmbio
   - Resultado Não Operacional
   - IR / CS / AFD separados

---

## 10) Conclusão

O problema de `Dez/2025` está fechado com causa raiz confirmada: **schema change + mapping stale**.  
O problema do lucro acumulado de `Set/2025` também está fechado com causa raiz confirmada: **bug de YTD por máscara calculada antes do merge**.  
Para `Dez/2025`, o valor ainda depende de **duas correções**: mapping e YTD.

A base oficial do BC disponível no Toma Conta é suficiente para consertar a aba DRE atual e também para iniciar uma DRE ajustada futura, mas essa futura camada terá que respeitar explicitamente a ruptura estrutural entre:

- DRE detalhada antiga (`2015–2024`)
- DRE nova (`2025+`)

Sem essa separação, a plataforma continuará sujeita a números corretos na origem, porém incompletos, não acumulados ou mal classificados na camada final.
