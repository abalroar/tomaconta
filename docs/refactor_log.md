# Refatoração da Base de Dados — Log incremental

## Etapa 1 — Contrato e inventário central (implementada)

### O que mudou

- Criado `utils/ifdata_cache/metric_registry.py` com:
  - registro central de métricas (`METRIC_REGISTRY`)
  - contratos de datasets (`DATASET_CONTRACTS`)
  - funções utilitárias de consulta e validação de contrato.
- Exportações públicas do novo módulo adicionadas em `utils/ifdata_cache/__init__.py`.
- Criada documentação técnica `docs/data_pipeline.md` com visão de pipeline e guia de manutenção.

### Como testar

1. Rodar testes de contrato/registry.
2. Rodar testes de métricas derivadas já existentes para garantir não regressão.

### Risco

- Baixo: mudança aditiva (sem alterar fórmulas ativas nas abas).


## Ajuste pós-review

- Removida dependência de `pandas` em `metric_registry.py` (validação agora aceita interface estrutural `empty/columns`).
- Testes de `tests/test_metric_registry.py` reescritos para usar `FakeDataFrame`, permitindo execução em ambiente mínimo.


## Integração inicial do registry ao cálculo derivado

- `derived_metrics.py` passou a consumir labels/formatação/fórmulas de métricas derivadas a partir de `metric_registry.py`, removendo duplicação de catálogo.
- Mantido fallback local para preservar retrocompatibilidade se o registry estiver incompleto.
- Testes do registry ampliados para validar consistência dos helpers de métricas derivadas.


## Otimização urgente peers (performance)

- Substituído lookup O(n) por célula (`df[(inst)&(periodo)]`) por índice em memória `(Instituição, Período) -> row` com cache em `df.attrs`.
- Adicionado recorte prévio dos caches extras por bancos/períodos selecionados antes de montar a tabela peers.
- Objetivo: reduzir drasticamente tempo da aba com múltiplos bancos (ex.: 15 bancos).


## Leitura filtrada no cache (Parquet)

- Adicionada função `_carregar_cache_relatorio_slice` para carregar recortes por período/instituição direto do arquivo de cache (com `pyarrow.dataset` quando disponível).
- A aba **Peers (Tabela)** passou a carregar `ativo/passivo/carteiras/dre/capital` já filtrados, reduzindo I/O e memória antes do cálculo.
- Fallback preservado: se filtro parquet falhar, carrega e filtra em pandas.


## Cache agressivo do pré-processamento de Rankings

- Extraído pré-processamento pesado da aba Rankings para `_get_rankings_base_df` com `@st.cache_data` (normalização de lucro, CET1 e merge complementar).
- Cache invalidado por token de versão dos caches `principal/capital`, flag de mescla de capital e assinatura de aliases.
- Objetivo: remover recomputação completa a cada clique no multiselect de bancos.


## Hotfix NameError na aba Peers

- Reintroduzido `_slice_cache_for_peers` como shim de compatibilidade para evitar quebra em deployments com código parcial (erro `NameError`).
- Mantida lógica de recorte por `Instituição`/`Período` sem impacto na semântica dos indicadores.


## Export PNG no Ranking

- Adicionado utilitário `_plotly_fig_to_png_bytes` para converter figuras Plotly em PNG.
- Incluído botão de exportação PNG no ranking geral e no ranking de Basileia (capital).
- Fallback amigável quando engine de imagem não estiver disponível no ambiente.


## Hardening de compatibilidade Peers

- Adicionado `_get_slice_cache_for_peers_fn()` para resolver dinamicamente o recorte de peers com fallback defensivo.
- Evita `NameError` em cenários de deploy parcial/misto, mantendo o recorte por banco/período no fluxo da aba.


## Warnings de groupby (pandas futuro)

- Definido `observed=False` explicitamente nos `groupby` com categorias para silenciar `FutureWarning` e estabilizar comportamento entre versões de pandas.


## Correções funcionais Peers/Rankings

- Na aba **Peers (Tabela)**, aplicado `_normalizar_lucro_liquido(df)` antes da montagem para garantir `Lucro Líquido Acumulado YTD` consistente (mesma lógica da aba Rankings).
- Na aba **Rankings > Deltas**, o formato de eixo e rótulo para variáveis percentuais agora usa a coluna base (`coluna_variavel`) e exibe `%` em `Δ absoluto` (ex.: `6.23%` em vez de `0.06`).

## Mensuração de usabilidade — Peers (Tabela)

Para responder objetivamente se ainda há tarefas pendentes e se houve ganho real de tempo, o fluxo recomendado é:

1. Rodar o app e capturar logs (stdout) contendo `[PEERS_PERF]` e `[ROE_TRACE]`.
2. Executar pelo menos 3 trocas de banco (com os mesmos períodos) para reduzir ruído.
3. Agregar os logs com o script:

```bash
python tools/measure_peers_usability.py --log-file streamlit.log --sla-seconds 3.0
```

O relatório (`docs/peers_usability_report.json`) traz:
- `interactive_total` com min/p50/p95/média (sem export);
- `stages` com tempos por etapa;
- `top_bottlenecks` (maiores médias);
- `sla_pass` (meta p95 <= 3s por interação);
- `roe_consistency` comparando último trace de peers vs scatter para o mesmo alvo.

### Critério prático de aceite de UX
- **Meta principal:** `interactive_total.p95_s <= 3.0`.
- **Meta ideal:** p50 próximo de 2s.
- Se `sla_pass = false`, priorizar otimização dos 2 primeiros itens em `top_bottlenecks`.
