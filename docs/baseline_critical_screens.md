# Baseline — telas críticas (Peers / Rankings / DRE)

Este documento registra o baseline técnico da etapa de medição para as telas críticas.

## Escopo medido

- **Peers**: leitura de cache + filtro por `Período` e `Instituição`.
- **Rankings**: filtro por período + ordenação Top 15 de coluna numérica.
- **DRE**: carga de dataset DRE + recorte por último período.

## Ferramenta de medição

Script: `tools/benchmark_critical_screens.py`.

Comando:

```bash
python tools/benchmark_critical_screens.py --repeats 5
```

Saída esperada:
- `docs/baseline_critical_screens.json` com tempos `min/mediana/máx/média` por operação.

## Resultado no ambiente desta execução

A execução automática neste ambiente não conseguiu concluir benchmark por ausência de dependências Python necessárias (`pandas`, `pyarrow`).

> Status: **pendente de execução em ambiente com dependências do projeto instaladas**.

## Próximos passos (implementação incremental)

1. Rodar benchmark e salvar JSON baseline.
2. Adicionar feature flag para backend de dados (parquet atual x duckdb experimental), mantendo parquet como default.
3. Reexecutar benchmark com mesma amostra/filtros e comparar deltas por operação.
4. Validar paridade UI/export nas telas afetadas antes de qualquer troca de padrão.
