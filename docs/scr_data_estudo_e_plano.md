# SCR.data — Estudo da fonte e plano da aba "Inadimplência (SCR)"

Data do estudo: 2026-08-31
Autor: sessão de estudo Claude Code
Status: **implementado em 2026-08-31** (fases 1 a 4). O que mudou em relação ao plano
está registrado em §10.

Objetivo: nova aba no Toma Conta que renderize inadimplência do SCR por **faixa de renda**,
**produto** e **região**, com visões "geral" (agregado Brasil) e "geral por produto"
(sem recorte de renda) igualmente acessíveis.

Escopo explicitamente **excluído** pelo pedido: recortes por `origem` (origem/destinação de
recursos) e por `cnae_ocupacao` (CNAE PJ / natureza da ocupação PF).

---

## 1. Sumário executivo — as cinco decisões

| # | Decisão | Recomendação |
|---|---|---|
| 1 | Formato da fonte | ZIP anual de CSVs mensais em `https://www.bcb.gov.br/pda/desig/scrdata_{ANO}.zip`. **Não há API Olinda** para SCR.data. |
| 2 | Grão do fato | `data_base × uf × segmento × cliente × porte × modalidade × submodalidade` (dropando `cnae_ocupacao`, `origem`, `indexador`) |
| 3 | Armazenamento | Parquet **shardado por ano** (`scr_data_{ano}.parquet`, ~9 MB/ano) + 1 cubo-resumo Brasil/região sempre carregado (~14 MB) — tudo em GitHub Release, padrão `extra_release_assets` |
| 4 | Produto | `submodalidade` (55 valores) é o nível útil; `modalidade` (13) **fica no grão** — não é rollup por lookup (ver §4-L) |
| 5 | Métrica-título | `inadimplência % = Σ carteira_inadimplencia / Σ carteira_ativa` — **sempre razão de somas, nunca média de razões** |

Medições reais feitas nesta sessão (amostra jan–jun/2026 + jul–dez/2012, 12 meses reais):

| Cubo | Grão | Linhas/mês | MB/mês | MB (168 meses) |
|---|---|---|---|---|
| `c_full` | uf × segmento × cliente × porte × submodalidade | ~31.000 | 0,74 | **~125 MB** |
| `c_core` | uf × cliente × porte × submodalidade | ~13.100 | 0,33 | ~57 MB |
| `c_uf_mod` | uf × cliente × porte × modalidade | ~3.200 | 0,09 | ~15 MB |
| `c_regiao` | região × cliente × porte × submodalidade | ~2.900 | 0,08 | **~14 MB** |
| `c_segmento` | segmento × cliente × porte × submodalidade | ~1.940 | 0,05 | ~9 MB |
| `c_brasil` | cliente × porte × submodalidade | ~650 | 0,02 | ~3,4 MB |

(parquet zstd, dimensões como `category`, métricas em `float32` na unidade R$ mil)

---

## 2. Como o BCB disponibiliza os dados

### 2.1 Canal e formato

- Página oficial: <https://www.bcb.gov.br/estabilidadefinanceira/scrdata>
- Dataset CKAN: <https://dadosabertos.bcb.gov.br/dataset/scr_data>
  (o `package_show` da API CKAN exige `User-Agent` não-default; sem ele o WAF do BCB devolve HTML de erro)
- **Não existe endpoint Olinda para SCR.** `olinda.bcb.gov.br/olinda/servico/SCR/...` responde `401 Usuário não autenticado`.
  A única via programática é o download dos ZIPs anuais.

| Recurso | URL |
|---|---|
| Dados mensais V2 (atual) | `https://www.bcb.gov.br/pda/desig/scrdata_{ANO}.zip` |
| Dados mensais V1 (**descontinuada**, só até jun/2025) | `https://www.bcb.gov.br/pda/desig/planilha_{ANO}.zip` |
| Metodologia V2 | `https://www.bcb.gov.br/pda/desig/metodologia_versao2.pdf` |
| Tutorial | `https://www.bcb.gov.br/content/estabilidadefinanceira/scr/scr.data/tutorial.pdf` |
| Leiaute doc 3040 (define porte, modalidades) | `https://www.bcb.gov.br/estabilidadefinanceira/scrdoc3040` |
| Instruções de preenchimento 3040 | `.../Leiaute_de_documentos/scrdoc3040/SCR_InstrucoesDePreenchimento_Doc3040.pdf` |

Usar **sempre a V2**. A V1 está congelada.

### 2.2 Cobertura e periodicidade

- **Histórico**: começa em **jul/2012** (`scrdata_2012.zip` contém `scrdata_201207.csv` … `201212.csv`).
- **Última data-base disponível hoje**: **jun/2026** (`scrdata_2026.zip`, 6 CSVs).
- **168 data-bases mensais** no total.
- Atualização: último dia útil do mês, com defasagem de ~30 dias após o fechamento do período
  (ex.: `scrdata_2026.zip` foi republicado em 29/ago/2026 já com jun/2026).
- **O ZIP anual é reescrito inteiro a cada mês** — o `Last-Modified` do ano corrente muda mensalmente,
  e anos passados também são revisados (o de 2023 foi republicado em mar/2026). Isso obriga
  o pipeline a checar `Last-Modified`/`ETag` por ano, não só o ano corrente.

### 2.3 Tamanhos brutos

| Ano | ZIP | CSV descompactado |
|---|---|---|
| 2012 (6 meses) | 57 MB | ~63 MB/mês |
| 2023 | 174 MB | ~100 MB/mês |
| 2025 | 180 MB | ~102 MB/mês |
| 2026 (6 meses) | 91 MB | ~102 MB/mês |

Cada CSV mensal tem **~313.000 linhas × 24 colunas**, separador `;`, decimal `,`, encoding
UTF-8 **com BOM** (usar `encoding="utf-8-sig"`), todos os campos entre aspas.

Total bruto a baixar para reconstruir a série completa: **~2,0 GB** de ZIPs (15 arquivos).
Isso é trabalho de pipeline offline, nunca do Streamlit.

### 2.4 Schema do CSV (idêntico em 2012 e 2026)

```
data_base;uf;segmento;cliente;cnae_ocupacao;porte;modalidade;submodalidade;origem;indexador;
numero_de_operacoes;a_vencer_ate_90_dias;a_vencer_de_91_ate_360_dias;a_vencer_de_361_ate_1080_dias;
a_vencer_de_1081_ate_1800_dias;a_vencer_de_1801_ate_5400_dias;a_vencer_acima_de_5400_dias;
carteira_a_vencer;vencido_de_15_ate_90_dias;vencido_acima_de_90_dias;carteira_vencida;
carteira_ativa;carteira_inadimplencia;ativo_problematico
```

---

## 3. Dicionário — todos os critérios apresentados

### 3.1 Dimensões

| Campo | Valores | Nota |
|---|---|---|
| `data_base` | último dia do mês (`"2026-06-30"`) | 168 valores desde jul/2012 |
| `uf` | 27 UFs | **baseado no CEP de residência da PF ou da sede da PJ**, não no local da agência |
| `segmento` | Arrendamento, Banco, Cooperativa, Desenvolvimento/Fomento, Financeira, Fintech, Instituição de pagamento, Outros | 8 valores; **Fintech e IP só existem a partir de datas recentes** (2012 tem apenas 6) |
| `cliente` | PF, PJ | equivalente ao corte do IF.data |
| `cnae_ocupacao` | 30 valores (Seção CNAE p/ PJ, natureza da ocupação p/ PF) | **fora de escopo — será descartado na agregação** |
| `porte` | 13 valores (9 faixas de renda PF + 4 portes PJ + "Indisponível" compartilhado) | ver 3.3 |
| `modalidade` | 13 valores | Anexo 3 do doc 3040 |
| `submodalidade` | 55 valores em 2026 (48 em 2012) | Anexo 3; **rolla up para `modalidade`** |
| `origem` | Sem/Com destinação específica | **fora de escopo** |
| `indexador` | Prefixado, Pós-fixado, Flutuantes, Índices de preços, TCR/TRFC, Outros | **fora de escopo** |

Mapeamento de segmento (do PDF de metodologia):

| Segmento agregado | Tipos cadastrados no BCB |
|---|---|
| Arrendamento | Sociedade de Arrendamento Mercantil |
| Banco | Banco Múltiplo, CEF, Banco do Brasil, Banco Comercial, Banco Múltiplo Cooperativo, Banco de Investimento, Banco Comercial Estrangeiro, Banco de Câmbio |
| Cooperativa | Cooperativa de Crédito |
| Desenvolvimento/Fomento | BNDES, Banco de Desenvolvimento, Agência de Fomento |
| Financeira | Sociedade de Crédito, Financiamento e Investimento |
| **Fintech** | **Sociedade de Empréstimo entre Pessoas (SEP), Sociedade de Crédito Direto (SCD)** |
| **Instituição de Pagamento** | **Instituição de Pagamento** |
| Outros | APE, Companhia Hipotecária, SCM, Corretora TVM, Distribuidora TVM |

> Para o Toma Conta este é o recorte mais diferenciado: é a única série pública que separa
> carteira e inadimplência de **SCD/SEP e IPs** do resto do sistema, mensalmente, por UF e produto.

### 3.2 Modalidades (13) e submodalidades (55)

Modalidades: Adiantamentos a depositantes · Empréstimos · Direitos creditórios descontados ·
Financiamentos · Financiamentos à exportação · Financiamentos à importação · Financiamentos com
interveniência · Financiamentos rurais (ex-financiamentos rurais e agroindustriais) ·
Financiamentos imobiliários · Financiamentos de títulos e valores mobiliários · Financiamentos de
infraestrutura e desenvolvimento · Operações de arrendamento · Outros créditos.

As 55 submodalidades incluem os produtos que interessam ao painel: `Cartão de crédito — compra à
vista e parcelado lojista`, `… compra, fatura parcelada ou saque financiado pela IF emitente`,
`Crédito rotativo vinculado a cartão de crédito`, `Cheque especial`, `Crédito pessoal — com/sem
consignação em folha`, `Aquisição de bens — veículos automotores`, `Financiamento habitacional —
SFH`, `Home Equity`, `Capital de giro (≤365d / >365d / teto rotativo)`, `Desconto de duplicatas`,
`Recebíveis adquiridos`, `Antecipação de fatura de cartão de crédito`, `Microcrédito`, etc.

**Atenção à sujeira do texto**: `"Financiamento habitacional \x96 exceto SFH"` traz um byte 0x96
(en-dash CP1252) e `"Cartão de crédito - compra à vista e parcelado lojista "` /
`"Comercialização "` têm espaço à direita. O ETL precisa normalizar (`strip()` + fix de encoding)
antes de virar categoria.

### 3.3 Porte — **os critérios que o pedido destaca**

#### PJ — porte por faturamento (Anexo 24/25 do doc 3040, Instruções de Preenchimento)

| Porte | Critério | Base legal |
|---|---|---|
| **Micro** | receita bruta anual **≤ R$ 360.000** | LC 123/2006, art. 3º, I |
| **Pequeno** | receita bruta anual **> R$ 360.000 e ≤ R$ 4.800.000** | LC 123/2006, art. 3º, II (redação da LC 155/2016) |
| **Médio** | receita bruta anual **> R$ 4.800.000 e ≤ R$ 300.000.000**, **desde que o ativo total não seja superior a R$ 240.000.000** | — |
| **Grande** | receita bruta anual **> R$ 300.000.000** **ou** ativo total **> R$ 240.000.000** | Lei 11.638/2007, art. 3º, parágrafo único |
| **Indisponível** | porte não informado; só permitido se o campo `FatAnual` for **≤ R$ 1,00** | — |

Pontos que precisam aparecer no tooltip da aba:

1. Os limites são **nominais e fixos em lei** — nunca foram corrigidos por inflação desde
   2016 (PJ pequena) / 2007 (grande). Ao longo de 14 anos de série há **migração puramente
   inflacionária** de porte: uma empresa que não cresceu em termos reais sobe de faixa.
   Toda leitura de "inadimplência de pequenas empresas em 2013 vs 2026" carrega esse viés.
2. "Grande" é um teste **OU**: faturamento > R$ 300 mi **ou** ativo > R$ 240 mi. Uma holding
   patrimonial com faturamento baixo cai em "Grande".
3. Não há faixa "MEI" no `porte`; MEI aparece em `cnae_ocupacao` (fora de escopo) para PF.

#### PF — faixa de renda por salários mínimos

| Porte | Faixa (renda mensal bruta individual) |
|---|---|
| Sem rendimento | — |
| Até 1 salário mínimo | ≤ 1 SM |
| Mais de 1 a 2 salários mínimos | (1, 2] SM |
| Mais de 2 a 3 salários mínimos | (2, 3] SM |
| Mais de 3 a 5 salários mínimos | (3, 5] SM |
| Mais de 5 a 10 salários mínimos | (5, 10] SM |
| Mais de 10 a 20 salários mínimos | (10, 20] SM |
| Acima de 20 salários mínimos | > 20 SM |
| Indisponível | renda não informada (`FatAnual` ≤ R$ 1,00) |

- A faixa é medida em **SM vigente na data-base**, então a fronteira em reais se move todo ano.
  Para deixar isso legível, o painel deve oferecer a legenda em R$ usando o salário mínimo do
  período: **SGS série 1619** (`https://api.bcb.gov.br/dados/serie/bcdata.sgs.1619/dados`),
  verificada nesta sessão (R$ 1.412 em 2024, R$ 1.518 em 2025).
- Admite-se **renda presumida ou estimada** quando não há comprovação — a faixa não é renda
  verificada.

### 3.4 Métricas

| Campo | Definição |
|---|---|
| `numero_de_operacoes` | nº de operações no recorte. **`-1` = valor suprimido** |
| `a_vencer_ate_90_dias` … `a_vencer_acima_de_5400_dias` | 6 buckets de vencimento futuro |
| `carteira_a_vencer` | soma dos 6 buckets a vencer |
| `vencido_de_15_ate_90_dias` | atraso curto (indicador antecedente) |
| `vencido_acima_de_90_dias` | atraso longo |
| `carteira_vencida` | vencido 15–90 + vencido >90 |
| `carteira_ativa` | a vencer + vencida |
| `carteira_inadimplencia` | **saldo total** (a vencer + vencido) das operações que têm *alguma* parcela vencida há mais de 90 dias |
| `ativo_problematico` | saldo das operações classificadas como ativo problemático |

Definições (metodologia V2, seção 2):

- **Inadimplência %** = `carteira_inadimplencia / carteira_ativa`. Note que o numerador é o
  **saldo contaminado inteiro**, não só a parcela vencida — por isso é sempre maior que
  `vencido_acima_de_90_dias / carteira_ativa`. Ambos são úteis e devem coexistir no painel.
- **Ativo problemático %** = `ativo_problematico / carteira_ativa`. Inclui atraso > 90 dias **e**
  operações com indício de não pagamento integral (reestruturações com deterioração significativa,
  níveis de risco E–H **até dez/2024**).
- **Quebra de série em jan/2025**: a partir daí só entram operações marcadas pelas IFs como ativo
  problemático (característica especial 19). A régua E–H deixou de valer. **A série de ativo
  problemático precisa de marcador visual de quebra em jan/2025.**
- Escopo: operações > R$ 1.000 até mai/2016 e > R$ 200 a partir de jun/2016 — **segunda quebra de
  série**, relevante para `numero_de_operacoes` e para faixas de renda baixa.
- Não inclui dependências/controladas no exterior. Há tolerância declarada entre o total do SCR e
  os saldos contábeis — **os números não batem com IF.data/COSIF por construção**, e a aba deve
  dizer isso.

---

## 4. Armadilhas metodológicas que o código precisa tratar

| # | Armadilha | Tratamento |
|---|---|---|
| A | `numero_de_operacoes = -1` (supressão) — **82.946 de 313.374 linhas em jun/2026 (26%), cobrindo R$ 511 bi = 6,7% da carteira** | Converter `-1` → `0` na soma e carregar coluna auxiliar `ops_suprimidas` (contagem de linhas suprimidas) para exibir "nº de operações subestimado" no rodapé. Nunca somar `-1`. |
| B | Média de razões | Toda taxa deve ser recalculada como `Σ num / Σ den` após o filtro. Proibir qualquer `mean()` de percentual. |
| C | Quebra jan/2025 no ativo problemático | Faixa sombreada + nota no gráfico |
| D | Quebra jun/2016 no limiar de R$ 1.000 → R$ 200 | Nota; afeta principalmente contagem de operações e faixas de renda baixa |
| E | `Cartão de crédito - não migrado`: R$ 69 bi com **77,4% de inadimplência** em jun/2026 | Categoria residual/legado. Não pode aparecer como "produto mais inadimplente" sem rótulo de alerta; considerar agrupar em "Cartão de crédito (legado)" |
| F | `Indisponível` no `porte` mistura PF e PJ e tem inadimplência muito acima da média (14,1% PF / 2,9% PJ) | Sempre segregar por `cliente` antes de ler `porte`; manter "Indisponível" visível (não descartar) com % da carteira ao lado |
| G | Portes PF e PJ compartilham a **mesma coluna** | O filtro de `cliente` é obrigatório na visão por renda; PF e PJ nunca no mesmo eixo de porte |
| H | Segmentos Fintech/IP não existem no início da série | Gráfico por segmento deve começar quando a categoria aparece, sem zero-fill enganoso |
| I | Submodalidades mudam de 48 (2012) para 55 (2026) | `dim_produto` versionada; nota de "categoria criada em …" |
| J | UF é do CEP do tomador | Escrever isso no cabeçalho da visão regional — não é onde o crédito foi concedido |
| K | Encoding CP1252 residual e espaços à direita nos rótulos | Normalizar no ETL |

---

## 5. Estratégia de armazenamento no cache do GitHub

### 5.1 Por que shardar

O grão completo pedido (sem CNAE/origem/indexador) é **~5,2 milhões de linhas / ~125 MB**
em parquet zstd para os 168 meses. Isso é:

- confortável para **GitHub Release** (limite de 2 GB por asset) — mas
- pesado para cold start do Streamlit Cloud e para `raw.githubusercontent.com` (limite prático de 100 MB/arquivo).

Solução: **shard por ano + um cubo-resumo leve**.

### 5.2 Layout proposto

```
data/cache/scr_data/
├── dados.parquet                 # cubo-resumo: regiao × cliente × porte × submodalidade (~14 MB, 168 meses)
├── dim_produto.parquet           # submodalidade → modalidade, ordem, flag legado, primeira data-base
├── dim_porte.parquet             # porte → cliente, tipo (renda/faturamento), ordem, rótulo curto, critério
├── dim_geo.parquet               # uf → regiao, nome, código IBGE
├── dim_segmento.parquet          # segmento → descrição, tipos cadastrados, primeira data-base
├── historico_manifest.json       # por ano: Last-Modified/ETag do ZIP, sha256, nº linhas, data-bases
├── metadata.json                 # padrão BaseCache
└── staging/
    ├── checkpoint.json           # ingestão resumível por ano (padrão taxas_juros_historico)
    └── annual/
        ├── 2012.parquet          # grão completo: uf × segmento × cliente × porte × submodalidade
        ├── …
        └── 2026.parquet          # ~9 MB/ano
```

Assets no Release (`extra_release_assets`, mesmo padrão de `taxas_juros_historico`):

```
scr_data_dados.parquet
scr_data_dim_produto.parquet
scr_data_dim_porte.parquet
scr_data_dim_geo.parquet
scr_data_dim_segmento.parquet
scr_data_manifest.json
scr_data_ano_2012.parquet … scr_data_ano_2026.parquet     (15 assets)
```

### 5.3 Contrato de carregamento em runtime

1. **Sempre**: baixa `scr_data_dados.parquet` (~14 MB) + as 4 dims (< 100 KB). Isso já entrega
   as visões geral, por produto, por faixa de renda e por região (5 regiões) na série completa.
2. **Sob demanda**: ao ligar "detalhe por UF" ou "por segmento de IF", baixa apenas os
   `scr_data_ano_{ano}.parquet` do intervalo selecionado (default: últimos 36 meses ≈ 27 MB).
3. Botão explícito "carregar histórico completo (jul/2012 →)" com aviso de ~125 MB.
4. `@st.cache_data(ttl=...)` por `(ano_inicial, ano_final, detalhe)`.

### 5.4 Schema do fato anual

| Coluna | Tipo | Nota |
|---|---|---|
| `data_base` | `category` (`YYYY-MM`) | |
| `uf` | `category` | |
| `segmento` | `category` | |
| `cliente` | `category` | PF/PJ |
| `porte` | `category` | |
| `modalidade` | `category` | fica no grão: o rollup não é 1:1 (§4-L) |
| `submodalidade` | `category` | |
| `numero_de_operacoes` | `int32` | com `-1` zerado |
| `ops_suprimidas` | `int32` | nº de linhas-fonte suprimidas agregadas |
| `carteira_ativa` | `float32` | **R$ mil** |
| `vencido_de_15_ate_90_dias` | `float32` | R$ mil |
| `vencido_acima_de_90_dias` | `float32` | R$ mil |
| `carteira_inadimplencia` | `float32` | R$ mil |
| `ativo_problematico` | `float32` | R$ mil |

Descartados por serem derivados ou fora de escopo: os 6 buckets `a_vencer_*`, `carteira_a_vencer`
(= `carteira_ativa − carteira_vencida`), `carteira_vencida` (= soma dos dois vencidos),
`cnae_ocupacao`, `origem`, `indexador`.

> `float32` tem ~7 dígitos significativos. Em R$ mil, um saldo de R$ 4,7 trilhões vira 4,7e9 —
> erro relativo ~1e-7, irrelevante para percentuais. Se preferir margem, usar `float64` custa
> ~+35% de tamanho (~170 MB no total) e continua viável.

### 5.5 Pipeline de atualização

Um extrator novo, offline, no padrão resumível de `taxas_juros_historico`:

1. `HEAD` em cada `scrdata_{ano}.zip` → compara `Last-Modified`/`Content-Length` com
   `historico_manifest.json`. Só rebaixa anos que mudaram.
2. Stream do ZIP para disco temporário; itera CSVs mensais sem descompactar tudo.
3. Por CSV: `read_csv(sep=";", decimal=",", encoding="utf-8-sig", usecols=…)` em chunks,
   normaliza rótulos, zera `-1`, agrega no grão do §5.4.
4. Grava `staging/annual/{ano}.parquet`; atualiza `checkpoint.json` (retomável).
5. Materializa `dados.parquet` (rollup região) e as 4 dims a partir dos anuais.
6. Quality gate: soma de `carteira_ativa` por data-base contra o mês anterior (variação > ±10%
   falha), nº de data-bases esperado, cobertura das 27 UFs, ausência de porte fora do domínio.
7. Publica no Release via `release_ops`.

Custo estimado do rebuild completo: ~2 GB de download, ~40–60 min. Update mensal incremental:
~180 MB (só o ano corrente), poucos minutos.

---

## 6. Dashboard padrão proposto

Rótulo de menu: **"Inadimplência (SCR)"**, em `MENU_PRINCIPAL`, após "Carteira 4.966".

### 6.1 Barra de contexto global (topo, sempre visível)

`Data-base` (slider até jun/2026) · `Cliente` (PF / PJ / Ambos) · `Métrica` (Inadimplência % /
Ativo problemático % / Atraso 15–90d %) · `Recorte de IF` (Todos / por segmento).

O default é deliberadamente **"tudo agregado"**: PF+PJ, todos os segmentos, Brasil, todos os
produtos, todas as faixas — a visão geral pedida.

### 6.2 Seção 1 — Panorama (a visão "geral")

- **4 KPIs**: carteira ativa (R$ tri), inadimplência %, ativo problemático %, atraso 15–90d %,
  cada um com Δ m/m e Δ 12m.
- **Série temporal principal**: inadimplência % total, com linhas PF e PJ sobrepostas,
  jul/2012 → hoje. Marcadores de quebra em jun/2016 e jan/2025.
- **Barra empilhada** da composição da carteira (a vencer / 15–90d / >90d).

### 6.3 Seção 2 — Por produto (a visão "geral por produto", sem renda)

- **Barra horizontal ordenada**: inadimplência % por submodalidade na data-base selecionada,
  com o tamanho da carteira codificado na largura/rótulo. Filtro de carteira mínima
  (default R$ 1 bi) para não deixar cauda longa dominar.
- **Toggle modalidade ↔ submodalidade** (rollup via `dim_produto`).
- **Small multiples**: séries temporais dos 6–9 produtos escolhidos, eixo Y compartilhado.
- **Heatmap produto × tempo** (últimos 36 meses) para leitura de ciclo.

### 6.4 Seção 3 — Por faixa de renda / porte

- Toggle **PF (faixa de renda em SM)** ↔ **PJ (porte por faturamento)**, nunca no mesmo eixo.
- **Barras ordenadas pela faixa** (não pelo valor) — a ordem natural da renda é a informação.
  Rótulo duplo: "Mais de 1 a 2 SM" + equivalente em R$ do mês (via SGS 1619).
- **Séries temporais por faixa**, com opção "indexado a 100 na data inicial" para comparar
  dinâmica em vez de nível.
- **Painel PJ**: card fixo com a tabela de critérios de faturamento do §3.3 e o alerta de
  não-correção inflacionária dos limites.
- **Cruzamento renda × produto**: heatmap faixa × submodalidade da métrica selecionada.

### 6.5 Seção 4 — Por região

- **Coroplético do Brasil por UF** (`st.plotly_chart` com geojson de UFs, ou `pydeck` já no
  requirements). Escala divergente ancorada na média Brasil.
- **Toggle região (5) ↔ UF (27)**.
- **Ranking de UFs** com carteira ao lado (evita ler RR como "pior estado" sobre base minúscula).
- **Séries temporais por região**, 5 linhas.
- **Cruzamento região × faixa de renda** e **região × produto** em heatmap.

### 6.6 Seção 5 — Por segmento de IF (extensão natural do projeto)

- Inadimplência % de **Fintech (SCD/SEP)** e **Instituição de Pagamento** contra Banco,
  Cooperativa e Financeira, com carteira ao lado. Início de série por categoria.
- Esta é a seção que conecta o SCR ao resto do Toma Conta.

### 6.7 Rodapé de toda a aba

Fonte, data-base, nota de divergência com IF.data/COSIF, % da carteira com `numero_de_operacoes`
suprimido, e link para a metodologia V2. Botão de download CSV do recorte visível.

### 6.8 Princípios de leitura embutidos na UI

1. Nenhuma taxa sem o **denominador ao lado** (carteira em R$).
2. Filtro de materialidade default para rankings.
3. Toda quebra de série marcada no gráfico, não só no texto.
4. Ordem categórica fixa para faixas de renda e portes.

---

## 7. Plano de implementação

### Fase 1 — Ingestão e cache (sem UI)
- `utils/ifdata_cache/scr_data.py`: `SCRDataCache(BaseCache)` com download por ano, checkpoint
  resumível, agregação, dims, `extra_release_assets`, `historico_manifest.json`.
- Registrar em `utils/ifdata_cache/manager.py` (`CACHES_INFO` + `_registrar_caches_padrao`).
- `tools/update_caches_cli.py` / `tools/refresh_cache_backend.py`: incluir `scr_data`.
- Entregável: `data/cache/scr_data/` populado localmente + assets publicados no Release.

### Fase 2 — Camada de consulta (sem Streamlit)
- `utils/scr_data_query.py`: funções puras sobre DataFrame — `taxa(df, num, den, by=[...])`,
  `serie_temporal`, `ranking`, `heatmap`, rollup submodalidade→modalidade, mapa UF→região,
  conversão SM→R$ via SGS 1619 (cacheado).
- Módulo independente de Streamlit, como `tabs/carteira_4966.py`. 100% testável.

### Fase 3 — Aba
- `tabs/scr_inadimplencia.py`: especificação declarativa das 5 seções (mesmo espírito do
  `RowSpec`/`GroupSpec` de `carteira_4966.py`), sem Streamlit.
- Em `app1.py`: adicionar `"Inadimplência (SCR)"` a `MENU_PRINCIPAL`, entrada em
  `CACHE_DEPENDENCIAS_POR_ABA` (`["scr_data"]`), nota em `_nota_cache_dependencia`, e o bloco
  `elif menu == "Inadimplência (SCR)":` no dispatcher.
- Rodar `python scripts/check_menu_dispatch_uniqueness.py`.

### Fase 4 — Glossário e testes
- Verbetes no Glossário: inadimplência SCR, ativo problemático, porte PJ por faturamento, faixa
  de renda em SM, quebras de série, supressão `-1`.
- `tests/test_scr_data_cache.py` — parsing do CSV (BOM, decimal, `-1`, encoding sujo), agregação,
  idempotência do checkpoint.
- `tests/test_scr_data_query.py` — razão de somas, rollup, ordem de categorias, mapa UF→região.
- `tests/test_scr_inadimplencia_ui.py` — spec das seções, no molde de `tests/test_taxas_juros_ui.py`.

Ordem de merge sugerida: Fase 1 → 2 → 3 → 4, cada uma em commit próprio.

---

## 8. Decisões

Confirmadas em 2026-08-31:

1. **`segmento` entra no fato.** Grão final `data_base × uf × segmento × cliente × porte ×
   submodalidade`, ~125 MB no histórico completo, shardado em ~9 MB/ano. O corte
   Fintech (SCD/SEP) e Instituição de Pagamento é o diferencial da aba.
2. **Janela default: últimos 36 meses** (~27 MB de cold start no grão detalhado), com botão
   explícito "carregar histórico completo (jul/2012 →)". O cubo-resumo `dados.parquet`
   (~14 MB) já traz a série inteira desde 2012 para as visões geral / produto / renda / região.
3. **`Cartão de crédito - não migrado` fica isolado, com alerta**: submodalidade preservada
   (o total continua batendo com o SCR), rótulo de alerta na UI e exclusão automática dos
   rankings de "produto mais inadimplente".

Assumidas por default (dizer se quiser mudar):

4. **Nível de produto default: `submodalidade`**, com toggle para `modalidade` via rollup
   de `dim_produto`.
5. **Coroplético em Plotly** com geojson de UFs embarcado (~100 KB em `data/bundled/`),
   já que `plotly` está no `requirements.txt`. Fallback para ranking em barras se o geojson
   pesar demais no cold start.

---

## 9. O que a implementação mudou em relação ao plano

Três coisas só apareceram ao rodar o pipeline e a aba de verdade:

1. **`modalidade` entrou no grão.** O plano previa `modalidade` como dimensão de rollup
   (`dim_produto` mapeando submodalidade → modalidade). Falso: **a submodalidade não é filha
   estrita da modalidade**. Em jun/2026, cinco submodalidades aparecem sob mais de uma
   modalidade — `Financiamento de projeto` sob seis delas, `Microcrédito` dividido entre
   Empréstimos (R$ 6,8 bi) e Financiamentos (R$ 2,6 bi). Um rollup por lookup atribuiria
   errado ~R$ 430 bi de carteira. As duas colunas ficam no fato e o rollup virou um `groupby`.
   Custo: +10% de tamanho (138 MB em vez de 125 MB no histórico completo).

2. **Nova coluna `carteira_suprimida`.** Sem ela não dá para dizer honestamente quanto da
   carteira tem contagem de operações sigilosa: depois da agregação, uma linha do fato reúne
   dezenas de linhas-fonte, e olhar a carteira das linhas que *tocam* alguma supressão dava
   43% em vez dos 6,7% reais. A coluna guarda só a carteira das linhas-fonte suprimidas.

3. **Coroplético: nada de `fitbounds`, e reorientação dos anéis.** O `d3-geo`, que o Plotly usa
   nos traces `geo`, usa a convenção de winding **oposta** à da RFC 7946 e trata o anel
   anti-horário da malha do IBGE como o *complemento* do polígono — o mapa saía como um
   retângulo preenchido com o formato do estado recortado como buraco. O arquivo em
   `data/bundled/geo/` fica no padrão e a inversão acontece em `carregar_geojson_uf()`.
   O `fitbounds="locations"` também foi trocado por enquadramento fixo do Brasil: dentro de
   coluna do Streamlit ele depende do tamanho do container no primeiro paint.

Dois bugs menores caçados na tela e cobertos por teste de regressão: `add_vline` com
`annotation_text` estoura (`TypeError`) em eixo categórico, e um `.replace(".", ",")` largo
demais transformava "p.p." em "p,p,".

### Arquivos

| Arquivo | Papel |
|---|---|
| `utils/ifdata_cache/scr_data.py` | ETL, cache, dimensões, validação, publicação no release |
| `utils/scr_data_query.py` | camada de consulta (razão de somas, ordens, janelas, SM) |
| `tabs/scr_inadimplencia.py` | spec das 5 seções e construtores, sem Streamlit |
| `app1.py` | rota `elif menu == "Inadimplência (SCR)"` + menu + glossário |
| `data/bundled/geo/uf_brasil.geojson` | malha das UFs (IBGE, ~96 KB, versionada) |
| `tests/test_scr_data_cache.py` | 39 testes de ETL |
| `tests/test_scr_data_query.py` | 47 testes da camada de consulta |
| `tests/test_scr_inadimplencia_ui.py` | 46 testes da spec e do contrato da rota |

### Como reconstruir o cache

```bash
python tools/update_caches_cli.py --tipo scr_data
```

Rebuild completo (2012→hoje): ~2 GB de download, ~4 min. Atualização mensal: só o ano
corrente, pois o comando compara `Last-Modified`/`Content-Length` de cada ZIP com o manifesto.

---

## 10. Anexos — evidências desta sessão

Inadimplência por porte, jun/2026 (calculado do CSV bruto):

| PF — faixa | % carteira PF | Inad. % | AP % |
|---|---|---|---|
| Acima de 20 SM | 20,96 | 4,84 | 8,50 |
| Mais de 5 a 10 SM | 18,20 | 4,21 | 7,29 |
| Mais de 3 a 5 SM | 14,87 | 5,09 | 8,65 |
| Mais de 1 a 2 SM | 13,16 | 7,57 | 11,89 |
| Mais de 10 a 20 SM | 12,95 | 3,87 | 6,32 |
| Mais de 2 a 3 SM | 10,29 | 5,79 | 10,17 |
| Até 1 SM | 6,65 | 9,31 | 12,58 |
| Indisponível | 2,62 | 14,06 | 18,84 |
| Sem rendimento | 0,31 | 23,40 | 26,37 |

| PJ — porte | % carteira PJ | Inad. % | AP % |
|---|---|---|---|
| Grande | 51,51 | 0,53 | 4,03 |
| Médio | 24,65 | 4,53 | 8,08 |
| Pequeno | 14,18 | 7,89 | 12,10 |
| Micro | 5,97 | 5,39 | 9,61 |
| Indisponível | 3,70 | 2,93 | 6,78 |

Totais jun/2026: carteira ativa **R$ 7,64 tri** (PF 4,69 / PJ 2,95), inadimplência **4,63%**,
ativo problemático **8,22%**.

A curva PF é **monotônica decrescente na renda com uma inversão no topo**: "Acima de 20 SM"
(4,84%) é mais inadimplente que "10 a 20 SM" (3,87%) e "5 a 10 SM" (4,21%). Vale investigar
na aba — provavelmente mix de produto (crédito imobiliário e cartão de alto limite).
