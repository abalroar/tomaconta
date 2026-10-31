# Análise financeira

As quatro visões ficam visíveis no módulo contábil. A análise prudencial reúne
COSIF mensal (4066 para o balanço; 4060 para o resultado) e IF.data trimestral
(relatórios 1, 2, 4, 5 e 16). As demais DREs mantêm suas fontes e cálculos.

## Apresentação

`utils/financial_statement_style.py` concentra tipografia, cores e larguras:
Calibri, laranja `#EC7000` reservado a cabeçalhos do site e do PowerPoint, faixas no mesmo laranja, linhas `#E8EAED` e subtotais `#F3F5F6`.
`utils/prudential_presentation.py` define as linhas-chave (`KEY_ROWS`), os grupos
contábeis (`PAGE_GROUPS`) e a formatação comum de valores. Os helpers nativos de
PowerPoint foram extraídos do Snapshot para `utils/presentation_tables.py`; o layout
e os cálculos do Snapshot foram preservados.

- Padrão da tela: os quatro últimos trimestres fechados e consecutivos com dados,
  a partir da data de acesso. As competências mensais continuam selecionáveis.
- Tela: instituição, períodos e **Exportar** na mesma linha; rótulo ajustado ao texto,
  limitado a 320 px (170 px em tela estreita, com quebra de linha); cabeçalho e coluna
  de contas fixos. A aba Carteira 4.966 usa o modelo e a tabela do menu Carteira 4.966.
- Excel: Comitê, Balanço, DRE, Carteira e Evolução visíveis; fontes, mapa, validações
  e a Carteira calculada ocultos e reexibíveis. O Comitê fica em A4 paisagem; as
  demonstrações, em retrato, com até quatro períodos por página.
- PowerPoint: um slide com Balanço e DRE dos três últimos períodos selecionados,
  os slides da Carteira 4.966 e o da Evolução; tudo nativo e editável. O detalhe
  de todos os períodos fica no Excel.
- Formato brasileiro com LCID `416` no Excel. Totais e linhas-chave em faixa laranja, com negativos em branco.
  Negativos em vermelho, zeros em cinza. Dado indisponível aparece como `–`; no
  Excel a célula continua guardando `N/D`, sem confundir ausência com zero.
- Evolução: uma só unidade no gráfico, R$ bi quando Lucro ou PL alcança R$ 10 bi e
  R$ mm abaixo disso. Lucro em verde e prejuízo em vermelho, sem contorno.
- DRE: acumulada no ano. Março e junho já vêm acumulados; setembro e dezembro somam o
  fechamento de junho. Sem junho, a DRE fica indisponível em vez de parcial.
- ROE do Balanço: resultado acumulado no ano × 12 / meses do ano / PL médio entre a data-base e
  dezembro do ano anterior, a mesma base do Snapshot. Sem os dois saldos, fica indisponível.
- NIM Bruta e NIM pós-PDD (métricas gerenciais): resultado acumulado no ano × 12 /
  meses do ano / carteira média. A carteira é Operações de Crédito Líq. do Balanço, na
  média entre a data-base e dezembro do ano anterior.
- Intermediação: uma regra única pelas contas COSIF, sem reclassificação por instituição.
  Quando o sinal difere do Resultado de Intermediação do Rel. 4, a linha recebe asterisco
  e a nota traz os dois valores, automaticamente. Registro da base:
  `python tools/audit_prudential_rel4.py --output registro.csv`.
- Snapshot: **Exportar Snapshot**, **Exportar material de comitê** e **Excel**, na base
  Consolidada / Prudencial. Comparação com pares e liquidez regulatória não estão incluídas.

## Atualização

Na raiz do repositório, com o ambiente Python do projeto:

```sh
python tools/update_financial_analysis.py --data-base 2026-09
```

Sem `--data-base`, procura o último mês publicado, a partir do mês anterior ao
atual. Só um HTTP 404 autoriza tentar o mês anterior; erros de acesso ou de servidor
encerram a operação. O IF.data é atualizado na última competência trimestral
publicada até o mês escolhido, respeitando seu calendário próprio.

O comando copia a geração consumida para uma área temporária, importa o CSV com
parser estrito, substitui integralmente a competência e usa os extratores IF.data
existentes. Códigos oficiais identificam instituições novas automaticamente.
Nenhuma etapa usa LLM, extração por imagem ou associação aproximada de nomes.

Antes da promoção, verifica chaves, campos, contas patrimoniais, fechamento do
balanço, composição, resultado contra grupos 7/8 e composição da carteira. A
tolerância operacional para somas monetárias é R$ 1, além de precisão numérica;
ela não altera números nem tolerâncias exibidas pelo modelo contábil. Conciliações
entre documentos/fontes, indicadores prudenciais e indisponibilidades ficam no
relatório operacional. Diferenças entre universos não recebem ajustes artificiais.

Variações a partir de 50%, com efeito de pelo menos R$ 1 milhão, geram registro
para revisão. Estoques usam a competência anterior disponível por instituição;
resultados usam o mesmo mês do ano anterior, já que a DRE é acumulada no ano. `--rules arquivo.json`
permite configurar `rounding_brl`, `anomaly_relative` e `anomaly_material_brl`.

As fontes são guardadas por SHA-256 em `data/cache/financial_analysis_sources/`.
Os relatórios de execução ficam em `data/cache/financial_analysis_updates/`.
Uma reprovação impede a promoção. A repetição de uma carga idêntica retorna
`unchanged`, sem regravar as bases ou duplicar registros.

Depois das validações, os mesmos materializadores do projeto recompõem os
consumidores dependentes. Com `TOMACONTA_OFFICIAL_STORE_DIR`, a ativação usa a
revisão completa e a comparação com o identificador anterior. No armazenamento
legado, usa as transações recuperáveis de cada cache e restaura as bases anteriores
se alguma gravação falhar; a troca global atômica exige o armazenamento oficial.
O comando opera no ambiente escolhido e não publica automaticamente uma release
de dados no GitHub. A publicação remota continua no fluxo administrativo existente.

Para validar um arquivo já recebido sem alterar a base ativa:

```sh
python tools/update_financial_analysis.py --data-base 2026-06 --csv arquivo.CSV --offline --check-only
```

`--offline` utiliza os relatórios IF.data já guardados. Sem essa opção, a origem
IF.data é consultada novamente, mesmo quando o CSV foi fornecido localmente.
Datas fora do catálogo suportado pelos extratores falham explicitamente.

## Verificação e limites

```sh
python tools/audit_prudential_coverage.py --xlsx --pptx --output cobertura.json
python -m pytest tests/test_prudential_analysis.py tests/test_snapshot_pptx_export.py
```

Cobertura verificada em 30/10/2026: 205 conglomerados, 34 competências, 5.319
pares instituição/mês e 205 seleções comparativas, sem duplicidade COSIF. Isso
confirma a geração para a população existente; não pressupõe publicação de todas
as instituições em todas as datas. Fontes históricas sem `CodInst` permanecem sem
associação por código e produzem `N/D`. A atualização exige identidade nos dados
novos. Resultados de Transfero em 09/2023 têm informação patrimonial incompleta na
origem; a lacuna foi preservada.

Pendência separada dos cálculos: o extrator legado de capital contém uma regra
de conversão de percentuais maiores que 1. Essa regra deve ser revisada com fontes
primárias para instituições com índices acima de 100%; não foi alterada nesta tarefa.
