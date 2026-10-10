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

- Suíte completa: 1.005 testes passaram, com 14 avisos de dependências já existentes.
- Exemplo real baixado pelo botão local: seis tabelas nativas, 13 gráficos e 13 planilhas incorporadas; zero imagens raster.
- Integridade OOXML e geometria: zero achados; avisos conservadores de altura das tabelas de Peers/classificação conferidos visualmente.
- Seis slides importados e renderizados; tabelas de Peers e Carteira também inspecionadas no PowerPoint. IDs de eixos normalizados para UInt32, com referências cruzadas preservadas.
- Layouts móveis compactos sem estouro horizontal dos cards e ajuda com alvo de 44 px. Teste de responsividade no navegador; não equivale a teste em aparelhos físicos.
- Downloads pelo Chrome: Itaú com seis slides e ATTRUS com cobertura parcial, capital ausente preservado e página explicando a ausência da Carteira 4.966.
