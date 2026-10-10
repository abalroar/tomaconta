# Snapshot e resumo em PowerPoint

O botão **Resumo em PowerPoint**, abaixo da data-base, exporta a instituição do Snapshot. A geração é sob demanda, sem carregar as fontes da Carteira 4.966 durante a abertura da página.

O exemplo Itaú Jun/26 tem seis slides: dois de Snapshot, dois de Tabela de Peers e dois de Carteira 4.966. Os primeiros dois conservam os 13 indicadores, os deltas QoQ/YoY e os mini-históricos. São tabelas, textos e gráficos Office nativos; cada gráfico tem planilha incorporada. Não há imagens raster. Os históricos usam os mesmos oito pontos da tela, preservando lacunas.

As tabelas seguem a paleta laranja/branco e a política de leitura das duas abas. Cada fonte seleciona até três competências reais da instituição até o corte do Snapshot, em ordem cronológica. Peers conserva o cache curado usado pelo Snapshot, inclusive capital ausente, sem reconstruir a base global durante o download. Fontes, valores brutos, referências, escopo e ressalvas ficam nas notas dos slides. Menos de três competências e ausência da Carteira são declaradas; outra instituição ou perímetro não substitui o recorte.

## Leitura financeira

Os cards e o PPTX consomem o mesmo payload de comparação. Taxas usam subtração em bps inteiros; coberturas e Crédito/Captações usam p.p.; saldos usam crescimento relativo com referência positiva. YTD compara os mesmos meses. A mudança IFData de 2025 bloqueia comparações incompatíveis. Montantes e razões contextuais têm cor neutra; capital, ROE e cobertura têm direção favorável de alta. Despesas negativas preservam o sinal da fonte e usam a magnitude para a cor.

A Carteira usa o modelo compartilhado da aba, com Rel. 16 e provisões do Rel. 2 fixados ao mesmo manifesto. O cruzamento usa identidade canônica ou código oficial. PDD soma somente e2 + f2 + g2 + h2. O agregado Perda Esperada do Snapshot pode incluir hedge e valor justo; a diferença aparece no arquivo.

## Revisão visual

| Before | After | Why |
| --- | --- | --- |
| Filetes verdes/vermelhos | Borda neutra e deltas com seta/cor | Indicação discreta e direta |
| Crescimento monetário favorável automaticamente | Saldos e razões contextuais neutros | Preserva a leitura de crédito |
| Ajuda por hover | Ajuda por toque e teclado | Uso em dispositivos móveis |
| Histórico com pontos ausentes compactados | Lacunas na posição temporal original | Evita conexão entre competências ausentes |
| Exportação dispersa nas abas | Resumo em PowerPoint no Snapshot | Acesso direto ao recorte da instituição |

## Validação

- Suíte completa: 1.006 testes passaram, com 14 avisos de dependências já existentes; teste de exportação repetido após o ajuste final dos IDs.
- Exemplo real baixado pelo botão local: seis tabelas nativas, 13 gráficos e 13 planilhas incorporadas; zero imagens raster.
- Integridade OOXML e geometria: zero achados; avisos conservadores de altura das tabelas de Peers/classificação conferidos visualmente.
- Seis slides importados e renderizados; tabelas de Peers e Carteira também inspecionadas no PowerPoint. A primeira validação nativa não cobriu a abertura do arquivo público com os gráficos do Snapshot; a correção abaixo registra a reprodução e a nova conferência.
- Layouts móveis compactos sem estouro horizontal dos cards e ajuda com alvo de 44 px. Teste de responsividade no navegador; não equivale a teste em aparelhos físicos.
- Downloads pelo Chrome: Itaú com seis slides e ATTRUS com cobertura parcial, capital ausente preservado e página explicando a ausência da Carteira 4.966.

## Compatibilidade com PowerPoint

O arquivo público original reproduziu o aviso de reparo no PowerPoint Mac. O reparo removia o conteúdo dos dois slides de Snapshot. Identificadores de eixos convertidos de negativos para UInt32 podiam exceder Int32; uma cópia com IDs positivos pequenos abriu normalmente. O exportador agora remapeia os IDs e todas as referências cruzadas no âmbito de cada gráfico.

A ordem OOXML também foi corrigida: `c:spPr` precede `c:txPr` e `c:externalData`; bordas de células precedem seu preenchimento. Inserções opcionais de eixos e lacunas respeitam os elementos sucessores. A regressão verifica a ordem, unicidade e alcance dos IDs em todos os gráficos e tabelas. O teste rejeita a versão anterior. A comparação dos arquivos preserva todas as tabelas, séries e valores financeiros.

## Instituições com cobertura parcial

A comparação dos downloads públicos de Bradesco, SBXPAY IP e Banco Guanabara conferiu os 13 cards com a tela e as notas dos slides, incluindo seus deltas. Bradesco conservou seis tabelas e 13 gráficos nativos; SBXPAY, quatro tabelas e sete gráficos, com um slide de Carteira 4.966 indisponível; Guanabara, seis tabelas e 12 gráficos. Cada gráfico mantém sua planilha incorporada. As lacunas de Jun/26 do Guanabara são células vazias na planilha e pontos ausentes no gráfico; históricos integralmente ausentes permanecem sem gráfico.

A revisão identificou dois zeros válidos de funding do SBXPAY exibidos como `N/A` por um formatador legado. O formatador específico do Snapshot agora mostra `0,00%` para percentuais zero e `N/D` para valores ausentes ou inválidos, mantendo `†` quando há uma ressalva identificada. Valores brutos, referências, deltas e históricos permanecem preservados.

O Resumo em PowerPoint do Snapshot usa a base Consolidada / Prudencial, incluindo instituições independentes disponíveis nessa fonte. O seletor de base Individual pertence à Tabela de Peers; o Snapshot ainda não oferece uma exportação nesse perímetro.
