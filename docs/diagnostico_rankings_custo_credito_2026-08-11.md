# Diagnóstico — falhas da aba Rankings / Custo de Crédito

**Data:** 2026-08-11
**Commit analisado:** `cdd1dcd` (= `origin/main`)
**Base de evidência:** log de runtime do Streamlit Cloud (20:23–20:53) + medições locais sobre os parquets reais.

---

## 1. Inventário dos erros

Seis falhas distintas aparecem no log. Três são artefatos de deploy e já não reproduzem; três são reais.

| # | Erro | Origem | Estado |
|---|---|---|---|
| E1 | `ImportError: cannot import name 'METRIC_CUSTO_CREDITO'` | módulo defasado em `sys.modules` | **Resolvido** em `ad88c7e` (20:24:38) |
| E2 | `SyntaxError` em `app1.py:23353` | leitura parcial do arquivo durante `git pull` | **Transitório** |
| E3 | `KeyError: 'utils.cdsfn_live'` / `KeyError: 'utils.ifdata_cache'` | invalidação de módulo durante hot reload | **Transitório** |
| E4 | `KeyError: 'Período'` em `app1.py:19135` | fonte vazia + ausência de contrato de vazio | **Real, reproduzível** |
| E5 | `rankings_df_source_principal_prepared: 50–110 s` | enriquecimento integral no caminho de leitura | **Real, medido** |
| E6 | Mar-26 ausente no seletor | dupla fonte de verdade para períodos | **Real, pendente de 1 confirmação** |

### E2 — não é bug de código

`main` compila (`python -m py_compile app1.py`, exit 0) e a linha 23353 está dentro de um `for` comum, sem `try`. O erro surgiu às `20:24:48`, **dois segundos** depois de `[20:24:46] 🐙 Pulling code changes from Github...`: o `script_cache` do Streamlit fez `ast.parse` sobre um `app1.py` de 1,3 MB / 27.359 linhas ainda sendo escrito pelo git. É um sintoma do monólito, não uma causa.

### E3 — corrida de invalidação de módulo

`KeyError: 'utils.ifdata_cache'` dentro de `_find_and_load_unlocked` ocorre quando o pacote-pai sai de `sys.modules` no meio do import de um filho. O watcher de módulos locais do Streamlit invalida módulos alterados enquanto o script roda. Também transitório, e também agravado por o app importar ~40 módulos locais no topo de um único script.

---

## 2. E4 — a falha que derruba a aba

### Reprodução

```
df = pd.DataFrame()          # o que _get_rankings_direct_df devolve
df[df['Período'] == '1/2026'] # -> KeyError: 'Período'
```

O traceback confirma: `pandas/core/indexes/range.py:417` só é alcançado quando `df.columns` é um `RangeIndex`, ou seja, DataFrame **sem nenhuma coluna**.

### Cadeia

`app1.py:19135` usa `df` sem verificar se a fonte devolveu algo:

```python
df = _get_rankings_source_df(...)          # pode devolver pd.DataFrame()
...
df_periodo = df[df['Período'] == periodo_pool_ref].copy()   # estoura aqui
```

`_get_rankings_direct_df` tem **dois** caminhos para o vazio:

1. `_carregar_dados_periodos_preparados(...)` devolve `None` — quando `carregar_formato_antigo()` falha (download remoto sem sucesso e leitura local inválida).
2. Nenhuma chave de `dados_periodos` casa com `periodos_filter` — quando o período selecionado na UI **não existe no dataset que o loader devolveu**.

O log mostra o comportamento intermitente esperado dessas duas condições: em `20:44` a mesma seleção rodou até o fim (`rankings_plot_render_single: 0.002s`), em `20:45` e `20:53` voltou vazia (`rankings_derived_merge: 0.000s` = a função saiu logo no guard de vazio).

### Alcance

`principal_prepared` serve **`Carteira de Crédito*`, `Core Funding*` e agora `Custo de Crédito (%)`**. A fragilidade é anterior a este indicador; o Custo de Crédito apenas passou a exercitá-la com frequência. Indicadores em `principal_light` (`Ativo Total`, `Patrimônio Líquido`) seguem rodando em 4–8 s porque não passam por esse caminho.

---

## 3. E5 — o custo de 50–110 s, medido

`principal_prepared` → `_carregar_dados_periodos_preparados`, que para servir **um** indicador de **um** período executa:

1. `carregar_formato_antigo()` — download de ~5,4 MB do release (cache expirado, ver §4.3);
2. `_anexar_carteira_credito_bruta()` — carrega o cache `ativo` (~5,5 MB) e roda `df.apply(..., axis=1)` sobre 62.061 linhas;
3. `_anexar_core_funding()` — carrega o cache `passivo` (~5 MB);
4. `recalcular_metricas_derivadas()` + `_sincronizar_roe_anualizado()` sobre a base inteira.

Medição local (máquina rápida; o Cloud é mais lento, o que fecha com os 50–110 s observados):

| Operação | Tempo |
|---|---|
| `_anexar_carteira_credito_bruta` (apply linha a linha) | **29,5 s** |
| Só o `resolve_carteira_credito_bruta_value` escalar, extrapolado | 2,9 s |
| **Equivalente vetorizado** (`_resolve_carteira_credito_bruta_series`) | **0,086 s** |

O resolver escalar responde por 10% do custo; os outros 90% são a materialização linha a linha do `apply`. **A versão vetorizada, com equivalência já travada por teste, é 343× mais rápida e existe no repositório desde `448dc8e`** — foi escrita para o `derived_metrics` e não foi aproveitada aqui.

**Memória não é o gargalo:** o dicionário preparado ocupa 14,1 MB e o cache `ativo` 24,5 MB. Descarto OOM como causa da intermitência.

---

## 4. Causas-raiz

### 4.1 Dupla fonte de verdade para "quais períodos existem"

| Consumidor | Fonte |
|---|---|
| Seletor de períodos (`_get_rankings_filters_context`) | lê `data/cache/principal/dados.parquet` **direto do disco** |
| Dados do gráfico (`_get_rankings_direct_df`) | lê via `cache.carregar()`, que pode **substituir** esse arquivo por um download remoto |

Duas leituras diferentes respondendo à mesma pergunta. Quando divergem, a UI oferece um período que o caminho de dados não serve — e o resultado é o DataFrame vazio de E4.

Antes de `cdd1dcd` o seletor lia `metadata["periodos"]`; eu troquei para o parquet. A troca corrigiu o metadata truncado, mas **aprofundou a divisão**: em vez de unificar a fonte, criou uma terceira leitura. Foi correção de sintoma na camada de UI, não de arquitetura.

### 4.2 Caminho de leitura acoplado a enriquecimento

Não existe camada curada para Rankings. Cada leitura reexecuta ingestão + junção + derivação da base inteira, em processo, dentro do request. É o que produz E5 e o que torna E4 sensível a rede.

Snapshot e Peers **não** têm esse problema porque consomem `critical_screens` — um parquet curado, materializado offline, com todas as colunas prontas. Rankings ficou de fora dessa migração.

### 4.3 Cache mutável em runtime sobre arquivo versionado

`PrincipalCache` tem `max_idade_horas=168`, e `cache_valido()` calcula a idade pelo `timestamp_salvamento` do metadata (`2026-06-22`, ~50 dias). Em todo container novo o cache nasce "expirado" → `carregar()` baixa do release → `salvar_local()` **reescreve parquet e metadata**.

Consequências encadeadas:
- muda o `mtime` → muda `_cache_file_token("principal")` → invalida o `@st.cache_resource` de `_carregar_dados_periodos_preparados` → o pipeline de 100 s roda de novo;
- os arquivos são **versionados no git** apesar de `data/cache/` estar no `.gitignore`, então o runtime suja a árvore (foi o que aconteceu na minha própria execução local);
- `_salvar_parcial` em modo substituição grava só os períodos extraídos (`df_final = df_novos`), degradando o dataset de forma permanente e silenciosa.

### 4.4 Ausência de contrato de vazio

Nenhuma fronteira entre loader e UI garante schema. `_get_rankings_source_df` pode devolver `pd.DataFrame()` sem colunas e a aba assume `'Período'` presente.

### 4.5 Decisão errada minha ao plugar o indicador

Coloquei `Custo de Crédito (%)` em `principal_prepared` para "trazer Carteira de Crédito*/Ativo Total para pool e ponderação". O indicador precisa apenas de `Instituição`, `Período`, `Ativo Total` (pool) e a coluna do cache derivado — `principal_light` bastaria, a 4–8 s. Pendurei um indicador novo no caminho mais lento e mais frágil do app.

---

## 5. Plano de execução

Fases independentes e entregáveis; as duas primeiras resolvem o sintoma, as três seguintes resolvem a arquitetura.

### Fase 0 — Estancar (imediato)

| Ação | Arquivo |
|---|---|
| Mover `Custo de Crédito (%)` para `principal_light` (só precisa de pool + coluna derivada) | `_resolve_rankings_source_family` |
| Guard de vazio: se a fonte devolver DataFrame sem `Período`, exibir aviso acionável e `st.stop()` do bloco, em vez de estourar | `app1.py:19135` |
| Trocar o `apply` de `_anexar_carteira_credito_bruta` pela série vetorizada já testada | `_anexar_carteira_credito_bruta` |

Efeito esperado: fim do `KeyError`, `principal_prepared` de ~100 s para ~5 s, Custo de Crédito fora do caminho pesado.
Risco: baixo. A equivalência do vetorizado já tem teste; o guard é aditivo.

### Fase 1 — Fonte única de períodos

Um único `rankings_periodos_disponiveis()` consumido pelo seletor **e** pelo caminho de dados, derivado do mesmo loader. Teste que trava a invariante: *todo período oferecido na UI devolve pelo menos uma linha*.

Efeito: elimina a classe de erro "UI oferece o que os dados não têm" — inclusive E6.

### Fase 2 — Curated layer para Rankings

Estender `critical_screens` (ou criar `rankings_curated`) com as colunas que Rankings usa, materializado offline por `tools/`, publicado como asset de release e **lido em modo somente-leitura**. Rankings passa a ler um parquet pronto, como Snapshot e Peers já fazem.

Efeito: remove ingestão e derivação do request. Alinha Rankings ao padrão que já funciona no resto do app.

### Fase 3 — Cache imutável no runtime

- `data/cache/` deixa de ser gravável pelo app: download vai para um diretório efêmero, artefato versionado vira *bundled* somente-leitura (padrão de `critical_screens`).
- `_salvar_parcial` nunca reduz a cobertura de períodos: merge incremental como default, substituição só via CLI explícita.
- Remover `data/cache/*.parquet` do versionamento (hoje contraria o próprio `.gitignore` e o runbook em `docs/diagnostico_fontes_aba_atualizar_base.md` §4).

### Fase 4 — Observabilidade

Rodapé por aba com período máximo, origem do dado (bundled / release / local) e timestamp. Hoje é impossível distinguir "dado não existe" de "cache degradado" sem acesso ao servidor — foi exatamente o que travou este diagnóstico.

### Fase 5 — Reduzir a superfície do monólito

E2 e E3 são consequência de um único script de 27 mil linhas com ~40 imports locais e três guards de `importlib.reload`. Extrair as abas para módulos sob `tabs/` (padrão já iniciado com `tabs/carteira_4966.py`) reduz o custo de parse por rerun e a janela de corrida do watcher.

---

## 6. Sequência recomendada

1. **Fase 0** agora — devolve a aba ao ar.
2. **Fase 1** na sequência — fecha a classe de erro do seletor.
3. **Fase 2** como próximo bloco de trabalho — é a correção arquitetural de fato.
4. Fases 3–5 como backlog priorizado.

## 7. Pendência de confirmação

**E6** é o único item que não consigo fechar daqui. Depois da Fase 0, com a aba abrindo, verificar se `Mar/26` aparece no seletor de períodos. Se não aparecer, o parquet no servidor está truncado e o remédio é republicar `principal` e `capital` cobrindo 2015→2026 em modo incremental (`tools/refresh_cache_backend.py`), confirmando os assets no release `v1.1-cache`. Sinal objetivo: `principal` com bem menos que ~62.000 registros na aba "Atualizar Base".
