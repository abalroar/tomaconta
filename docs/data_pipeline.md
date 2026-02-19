# Toma Conta — Pipeline de Dados (estado atual + contrato etapa 1)

## Visão geral

A base de dados do app segue hoje um fluxo orientado a cache local em parquet com fallback em pickle:

1. **Ingestão (API Olinda/BCB)**
   - Extração por relatório via `utils/ifdata_cache/extractor.py`.
2. **Staging operacional (cache por relatório)**
   - Persistência em `data/cache/<tipo>/dados.parquet` + `metadata.json`.
3. **Curated de uso analítico (parcial)**
   - `derived_metrics` em formato long/tidy.
   - `dados_periodos` em memória (`session_state`) no formato `{periodo -> DataFrame}`.
4. **Consumo pelas abas**
   - Rankings, Peers, Scatter, DRE, Carteira 4.966 etc.
5. **Export**
   - Excel/CSV, incluindo export de dados puros em alguns fluxos (ex.: Peers).

## Contrato canônico (introduzido na Etapa 1)

Foi criado um contrato inicial de datasets e um registro central de métricas em:

- `utils/ifdata_cache/metric_registry.py`

### Contratos de datasets (mínimo)

- `principal_curated`: chave `Instituição + Período`
- `capital_curated`: chave `Instituição + Período`
- `derived_metrics_long`: chave `Instituição + Período + Métrica`

### Registro de métricas (inventário inicial)

Cada métrica possui:

- fórmula canônica (informativa)
- dependências (colunas base)
- unidade
- escala interna
- regra de anualização (quando aplicável)
- formato sugerido de display (UI)
- tabela(s) de origem

## Decisão técnica registrada (sem alterar cálculo existente)

- **Escala interna recomendada para percentuais: decimal (0–1)**.
- Formatação percentual (0–100) deve ocorrer **apenas na camada de apresentação/export formatado**.

> Observação: nesta etapa, essa decisão foi registrada como contrato e inventário; não houve migração ampla de todas as rotas de cálculo.

## Como adicionar nova métrica (guia curto)

1. Adicionar nova entrada em `METRIC_REGISTRY` com `key` estável.
2. Preencher fórmula, dependências, unidade e escala interna.
3. Se houver anualização, incluir `AnnualizationRule`.
4. Criar/ajustar teste cobrindo:
   - presença no registro
   - escala esperada
   - validação de contrato do dataset de saída (quando aplicável)
5. Só depois integrar a métrica no cálculo/aba específica.

## Como atualizar cache (estado atual)

1. Usar a aba **Atualizar Base** para extração por período.
2. Validar `metadata.json` do cache salvo (`timestamp`, `total_registros`, `periodos`).
3. Se necessário, publicar no GitHub Releases via fluxo existente da UI.

## Próximos passos planejados (fora da Etapa 1)

- Migração progressiva de cálculos duplicados para consumo direto do registro central.
- Materialização de tabelas curated por domínio para reduzir recomputação nas abas.
- Política mais estrita de fallback para evitar uso silencioso de cache stale.
