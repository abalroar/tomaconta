# Estatísticas Crédito BC — SGS/BCB

## Escopo implementado

O módulo `Estatísticas Crédito BC` reúne séries mensais agregadas de:

- concessões e prazo médio das novas operações;
- saldos do SFN, crédito ampliado, tomador, produto, porte e controle;
- pré-inadimplência, inadimplência, provisão e cobertura;
- comprometimento de renda, endividamento e desocupação;
- taxas médias de juros e spreads;
- glossário metodológico e registry consultável.

As páginas de expectativas trimestrais, inadimplência por renda, cortes
Longtail/Small/Medium/Corporate e séries Serasa permanecem sinalizadas na
interface como pendências. As fotografias não fornecem códigos ou artefatos
suficientes para cadastrá-las com rastreabilidade.

## Arquitetura

```text
registry central
  -> provedor BCData/SGS ou provedor externo registrado
  -> SGSCreditCache.materialize_history()
  -> data/cache/mercado_credito_sgs/dados.parquet
  -> transformações auditáveis
  -> tabs/mercado_credito.py
```

O fato Parquet usa o formato longo:

| coluna | conteúdo |
|---|---|
| `data` | competência da observação |
| `codigo` | código SGS, quando aplicável |
| `serie` | alias estável do registry |
| `nome_oficial` | descrição oficial |
| `valor` | valor numérico sem zero-fill |
| `unidade` | unidade canônica |
| `frequencia` | frequência da série |
| `provedor` | identificador do provedor |

Os códigos ficam exclusivamente em `utils/sgs_credit_registry.py`. O contrato
`SeriesProvider` permite acrescentar fontes externas sem alterar a camada de
transformação ou os gráficos.

## Atualização

Histórico completo:

```bash
.venv/bin/python tools/update_caches_cli.py \
  --tipo mercado_credito_sgs \
  --modo overwrite \
  --mensal-inicio 201101 \
  --mensal-fim 202608
```

Atualização incremental:

```bash
.venv/bin/python tools/update_caches_cli.py \
  --tipo mercado_credito_sgs \
  --modo incremental \
  --mensal-inicio 202601
```

O mesmo fluxo está disponível em `Atualizar Base`, com publicação opcional dos
assets `mercado_credito_sgs_dados.parquet` e
`mercado_credito_sgs_metadata.json` no GitHub Releases configurado para o app.

## Fórmulas

- Índice IPCA: `100 × Π(1 + IPCA_mensal / 100)`.
- Crescimento real em 12 meses:
  `(X_t / IPCAIndex_t) / (X_t-12 / IPCAIndex_t-12) - 1`.
- Participação: `componente / total`.
- Variação de taxa ou spread: `x_t - x_t-12`, em pontos percentuais.
- Cobertura: `(provisão / carteira) / (inadimplência / carteira)`.
- Comprometimento total: amortização do principal + juros.

Somatórios exigem todos os componentes esperados no mês. Uma observação ausente
permanece ausente; ela não é interpolada nem convertida em zero.

## Privacidade dos materiais de referência

A pasta `bcb-if/` está no arquivo local `.git/info/exclude`. Esse ajuste impede
inclusão acidental das fotografias e notas privadas sem criar uma regra
compartilhada no repositório.
