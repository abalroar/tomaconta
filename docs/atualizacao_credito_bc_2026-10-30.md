# Crédito BC — publicação de 29/10/2026

Atualização das 130 séries BCData/SGS que alimentam Estatísticas Crédito BC,
com consulta em 30/10/2026. Crédito, concessões, juros, spreads, atrasos e
provisões chegam a setembro/2026. Os quatro indicadores de endividamento e
comprometimento das famílias chegam a agosto/2026. Selic e CDI têm
observações de outubro; a data máxima global do arquivo não representa a
competência do crédito.

Fonte da divulgação: [Banco Central, nota de 29/10/2026](https://www.bcb.gov.br/content/estatisticas/hist_estatisticasmonetariascredito/202610_Texto_de_estatisticas_monetarias_e_de_credito.pdf).
As séries são consultadas no endpoint público
`https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados`, conforme o
registro `utils/sgs_credit_registry.py`.

## Escopo e validação

- Janela reconsultada: janeiro/2025 a 30/10/2026.
- 24.299 observações de 130 séries: 129 registros adicionais e 373 valores
  revisados em relação ao bundle anterior.
- Nenhuma duplicidade de série/competência e nenhum nulo nos campos
  série, código, data e valor. Todas as chaves históricas foram preservadas.
- Histórico anterior a janeiro/2025 idêntico ao anterior.
- 116 testes existentes passaram, cobrindo dados, comentários, gráficos e
  exportação. Dez páginas SGS renderizadas por AppTest sem exceções ou
  erros, com setembro/agosto explicitados na legenda.
- Comentários revistos com fontes e competências próprias. Participações,
  variações reais e cobertura usam as mesmas fórmulas dos gráficos.
- SCR.data mantém seu conjunto e calendário próprios; esta publicação
  atualiza as estatísticas SGS. O comentário por renda explicita a diferença.

A coleta inicial incompleta foi descartada pelo materializador. A retomada
salvou as respostas por série e só materializou a base após completar as 130.

## Artefatos

Publicação: `tomaconta-credito-202609-20261030-v1`, release `v1.1-cache`.

O bundle Parquet e seu metadata são publicados com o código. O manifesto
atualiza somente a entrada SGS, suas competências e os hashes dos dois
assets, conservando os demais caches. A identificação de publicação força
a leitura da nova geração mesmo quando há um runtime anterior.

SHA-256 do Parquet:
`4274f48cd379176dcd7f268556e76489c83fd9237e165d1cd7c005ae2c377130`.

Evidências locais da rodada em `outputs/credito-sfn-2026-10-30/`:
`validation.json`, `revisions.csv`, `indicators.json`, `responses/`,
`ui_validation.json`, logs de coleta e testes, backup do release anterior
e os três arquivos preparados para publicação.

Os testes locais comprovam o conteúdo preparado. A confirmação da
publicação exige conferir os assets remotos e as competências servidas pelo
aplicativo após a integração.
