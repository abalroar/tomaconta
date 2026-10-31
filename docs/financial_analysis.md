# Análise financeira

As quatro visões ficam visíveis no módulo contábil. A análise prudencial reúne
COSIF mensal (4066 para o balanço; 4060 para o resultado) e IF.data trimestral
(relatórios 1, 2, 4, 5 e 16). As demais DREs mantêm suas fontes e cálculos.

## Apresentação

`utils/financial_statement_style.py` concentra tipografia, cores e larguras:
Calibri, laranja `#EC7000` reservado a cabeçalhos do site e do PowerPoint, grafite
`#2F3640` nas faixas do Excel, linhas `#E8EAED` e subtotais `#F3F5F6`.
`utils/prudential_presentation.py` define as linhas-chave (`KEY_ROWS`), os grupos
contábeis (`PAGE_GROUPS`) e a formatação comum de valores. Os helpers nativos de
PowerPoint foram extraídos do Snapshot para `utils/presentation_tables.py`; o layout
e os cálculos do Snapshot foram preservados.

- Tela: instituição, períodos e **Exportar** na mesma linha; rótulo ajustado ao texto,
  limitado a 320 px (170 px em tela estreita, com quebra de linha); valor e percentual
  lado a lado; cabeçalho e coluna de contas fixos na rolagem.
- Excel: Comitê, Balanço, DRE e Carteira 4.966 visíveis; fontes, mapa e validações
  ocultos e reexibíveis. Fórmulas e valores numéricos continuam editáveis. O Comitê
  fica em A4 paisagem, com dois períodos por página e os dois painéis terminando
  juntos. As demais abas ficam em A4 retrato, com até quatro períodos por página e
  títulos e contas repetidos; a escala é fixa, sem encolher para caber.
- PowerPoint: tabelas nativas, até quatro períodos e 21 linhas por slide, com
  cabeçalhos repetidos. Os slides seguem os grupos contábeis, e a conta principal
  acompanha as subcontas. Nenhuma linha da seleção é descartada na paginação.
- Formato brasileiro com LCID `416` no Excel. Montantes em R$ milhões. Negativos em
  vermelho, zeros e `N/D` em cinza; valores abaixo de R$ 0,5 milhão aparecem como
  `<1`, sem alterar o número guardado. `N/D` continua diferente de zero. A DRE
  permanece acumulada no semestre.

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
resultados usam períodos com igual número de meses do semestre. `--rules arquivo.json`
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
