# Snapshot e resumo em PowerPoint

O seletor **Base das demonstrações** oferece **Consolidada / Prudencial** e **Individual**. O botão **Resumo em PowerPoint**, abaixo da data-base, exporta a instituição e o perímetro selecionados. A geração é sob demanda; o pacote usa os mesmos valores, comparações e históricos da tela.

Os primeiros dois slides conservam os **15 indicadores** do Snapshot, distribuídos em oito linhas de porte, capital e rentabilidade e sete de funding e qualidade da carteira. Tabelas, textos e gráficos são objetos Office nativos editáveis; cada gráfico mantém sua planilha incorporada. Os históricos conservam até oito competências e suas lacunas. Ausência integral do histórico aparece como N/D, sem gráfico artificial.

Na sequência vêm a Tabela de Peers e a Carteira 4.966, com até três competências reais da instituição até a data-base, em ordem cronológica. Fontes, referências, valores brutos, escopo e ressalvas também ficam nas notas dos slides. Os períodos e dados indisponíveis permanecem explícitos.

## Escopo e fontes

Na base Consolidada / Prudencial, o recorte corresponde ao conglomerado prudencial ou à instituição independente disponível no IFData. O exemplo Itaú Jun/26 tem seis slides: dois de Snapshot, dois de Peers e dois de Carteira 4.966. Cada linha identifica o relatório; o IFData é trimestral e os estágios do Cadoc 4060 são mensais, alinhados ao fechamento trimestral.

Na base Individual, a identidade é a pessoa jurídica selecionada, por código oficial ou nome canônico exato. Balanço, carteira, captações e lucro usam o IFData Rel. 1 individual; o custo de captação usa os Rel. 4 e Rel. 1 individuais quando disponíveis. O lucro de setembro/dezembro é recomposto com junho para obter o acumulado anual; sem essa base, o YTD permanece N/D. O lucro trimestral exige os componentes necessários à subtração. O ROE individual usa o patrimônio líquido atual, com essa definição visível na tela e nas notas.

Capital regulatório, estágios, PDD e arrasto permanecem **N/D na Individual** quando falta fonte no mesmo perímetro. O conglomerado não completa essas lacunas. A Carteira 4.966 individual tem um slide que explica a indisponibilidade dos Rel. 16 e Rel. 2 nos caches desse recorte. Nos exemplos Individual de Itaú e Bradesco, o pacote tem quatro slides, três tabelas e nove gráficos editáveis.

## Indicadores de arrasto e cobertura

| Indicador | Subtítulo | Definição | Fonte e leitura |
| --- | --- | --- | --- |
| Inadimplência >90 dias | Arrasto · % da carteira | Saldo integral das operações com alguma parcela vencida há mais de 90 dias, incluindo parcelas a vencer, dividido pela carteira total do trimestre | IFData Rel. 16, trimestral, desde mar/2025. Alta pede atenção; queda é usualmente favorável |
| Cobertura dos vencidos >90 dias | PDD / vencidos por arrasto | PDD dividida pelo saldo integral dos vencidos por arrasto | IFData Rel. 2 + Rel. 16, mesma competência e perímetro. Cobertura aproximada; leia PDD e vencidos conjuntamente |

A PDD soma, em módulo, somente **e2 + f2 + g2 + h2** do Rel. 2. Ela também cobre ativos fora dos vencidos. O agregado **Perda Esperada** dos outros cards pode incluir hedge e ajustes de valor justo; esse agregado tem definição própria. A Carteira 4.966 usa o mesmo modelo da aba, com os Rel. 16 e Rel. 2 fixados ao mesmo manifesto e correspondência por identidade canônica ou código oficial.

## Deltas e cores

Todos os percentuais e múltiplos usam **subtração**, conforme a unidade do indicador. Capital, retorno, custo anualizado e taxas de risco usam bps inteiros; coberturas e demais proporções usam p.p. com duas casas. Crédito/Captações, perdas ou PDD/carteira, custo/receita e percentuais da base comum da Carteira 4.966 usam p.p. Alavancagem usa diferença em x. Saldos usam crescimento relativo em %, com referência válida; montantes de risco preservam sua leitura de crédito.

Para insumos percentuais em escala decimal, o delta em bps é **(atual − referência) × 10.000** e o delta em p.p. é **(atual − referência) × 100**. A escala dos insumos deve ser resolvida antes da conversão. O delta é a diferença de níveis convertida à unidade indicada.

Exemplos: 2,18% → 2,25% corresponde a **+0,07 p.p. ou +7 bps**; 15,18% → 14,77% corresponde a **−41 bps**; cobertura 193,10% → 193,50% corresponde a **+0,40 p.p.** Os cálculos usam valores sem arredondamento. Movimentos inferiores à precisão exibida preservam a direção com “<1 bp” ou “<0,01 p.p.”.

Verde indica direção usualmente favorável; vermelho indica atenção. Capital, ROE e cobertura têm leitura usual de alta favorável; vencidos e estágios 2 e 3 têm leitura usual de queda favorável. Saldos e razões sem interpretação unívoca ficam neutros. Alertas na observação atual ou de referência neutralizam a cor; as setas conservam a direção do movimento.

O custo de captação inverte o sinal da despesa contábil para apresentar o custo. Valores negativos podem representar receitas ou reversões: o sinal permanece no nível, no delta e na leitura da cor. Uma alta do custo pede atenção; uma queda é usualmente favorável. O cálculo não troca valores negativos por suas magnitudes.

O detalhe no ponto final do histórico acompanha a comparação trimestral elegível: marcador discreto nos gráficos de linha ou última barra colorida. Exige os dois pontos finais disponíveis e movimento real; lacunas, saldos contextuais e janelas YTD ficam neutros. Nos cards do Snapshot, o YTD compara os mesmos meses por YoY. Comparações incompatíveis com a mudança de formato IFData em 2025 permanecem sinalizadas.

## N/D e uso móvel

Zero válido aparece como zero, inclusive **0,00%**. Dado ausente ou denominador inválido permanece **N/D**; **†** indica uma causa identificada. Uma competência ausente fica vazia no gráfico e na planilha incorporada, preservando sua posição temporal. A ajuda dos cards funciona por toque e teclado. A responsividade foi verificada no navegador; o layout mantém cards compactos e alvos de ajuda de 44 px.

## Validação da versão publicada em 10/10/2026

A [PR #326](https://github.com/abalroar/tomaconta/pull/326) foi integrada e o app público reiniciado. A suíte completa aprovou **1.148 testes**, com 14 avisos de dependências já existentes.

A validação complementar aprovou **109 testes direcionados de deltas**, após explicitar a escala decimal dos insumos na auditoria, preservando os cálculos. Os **18 testes de PowerPoint** foram repetidos após ajustar a exibição do marcador `†`. O Excel público da Carteira 4.966 também teve **110 deltas de 13 linhas** recalculados em auditoria independente de números e cores.

| Recorte validado | Conteúdo nativo | Preservação dos dados |
| --- | --- | --- |
| Itaú Prudencial, download público | 6 slides, 6 tabelas, 15 gráficos e 15 XLSX; sem imagens raster | Os 15 cards, deltas e históricos coincidem com o local validado. NPL Jun/26: 2,33%, +7 bps; cobertura: 187,41%, −6,13 p.p.; ambos com marcador vermelho |
| Itaú Individual, local e download público | 4 slides, 3 tabelas, 9 gráficos e 9 XLSX; sem imagens raster | Nove valores disponíveis e seis N/D de risco/capital. Conteúdo público igual ao local, exceto horário da consulta |
| Bradesco Individual, local e download público | 4 slides, 3 tabelas, 9 gráficos e 9 XLSX; sem imagens raster | Valores, fontes e escopo coincidem com a tela; seis N/D preservados. Conteúdo público igual ao local, exceto horário da consulta |
| Guanabara Individual, local e download público | 4 slides, 3 tabelas, 9 gráficos e 9 XLSX; sem imagens raster | Os 15 valores atuais e seis valores de Peers em Jun/26 permanecem N/D. Os nove históricos conservam Jun/26 vazio e 11 lacunas no total, sem substituir por zero. Conteúdo público igual ao local, exceto horário da consulta |

Os arquivos foram abertos e inspecionados no PowerPoint para Mac, sem reparo. O comando **Edit Data in Excel** abriu a planilha incorporada de um gráfico nativo, com as oito competências em `Sheet1!A1:B9`. A verificação estrutural conciliou valores das notas e tabelas, cache dos gráficos e XLSX, além de conferir escopo, lacunas, cores e geometria. Todos os slides dos exemplos locais também foram renderizados e inspecionados, sem cortes ou sobreposição de fontes, subtítulos e rodapés.

O download público Individual do Itaú comprova a correção do cache: ativo de Set/25 de **R$ 2.058.293.253.947,90** e lucro trimestral de Dez/25 de **R$ 7.044.771.202,28**, presentes nas notas, no gráfico e na planilha incorporada.

## Compatibilidade e regressões preservadas

O aviso de reparo da primeira versão foi reproduzido no PowerPoint Mac: identificadores de eixo acima de Int32 removiam o conteúdo dos dois primeiros slides. O exportador usa IDs positivos pequenos, com todas as referências cruzadas no mesmo mapeamento. A ordem OOXML foi corrigida: `c:spPr` precede `c:txPr` e `c:externalData`; bordas das células precedem o preenchimento. Os testes verificam ordem, unicidade e alcance dos IDs, inclusive os marcadores finais.

A revisão anterior de Bradesco, SBXPAY e Guanabara, ainda com 13 cards, identificou dois percentuais zero da SBXPAY mostrados como `N/A`. Essa regressão continua coberta: o formatador do Snapshot preserva **0,00%** para zeros e **N/D** para ausências, mantendo valores brutos, referências e lacunas.
