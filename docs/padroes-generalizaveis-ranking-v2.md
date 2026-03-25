# Padrões Generalizáveis — Ranking (v2)

## 2026-03-25 — Atualização (append-only)

### Cor Uniforme em Cross-Section de Período Único
- **Filename:** `cor-uniforme-cross-section.md`
- **Tags:** #ux #data #layout
- **Regra:** Em gráficos cross-section com um único período, todas as barras usam a mesma cor para não sugerir categorias inexistentes.

### Coerência Label ↔ Ordenação Visual
- **Filename:** `coerencia-label-ordenacao.md`
- **Tags:** #ux #layout #product
- **Regra:** Em barras horizontais, "Maior → Menor" deve colocar o maior valor no topo visual (posição y=0).

### Toggle de Data Labels para Export
- **Filename:** `toggle-data-labels-export.md`
- **Tags:** #ux #export #layout
- **Regra:** Disponibilizar toggle persistente para mostrar/ocultar labels de valores no gráfico, facilitando export autocontido.

### Linhas de Referência Estatística com Rodapé Metodológico
- **Filename:** `linhas-referencia-rodape.md`
- **Tags:** #ux #data #math #product
- **Regra:** Exibir média da seleção e média SFN com cores distintas e incluir nota metodológica explícita na tela.

### Anti-Falsa-Equivalência no Arredondamento
- **Filename:** `anti-falsa-equivalencia-arredondamento.md`
- **Tags:** #formatting #math #data
- **Regra:** Ajustar casas decimais dinamicamente para que valores distintos não resultem no mesmo texto formatado quando comparados lado a lado.

### Separadores Numéricos Brasileiros como Padrão
- **Filename:** `separadores-numericos-br.md`
- **Tags:** #formatting #ux
- **Regra:** Usar vírgula para decimais e ponto para milhar em toda exibição numérica da UI de ranking.

### Tabela Wide para Export sem Pivot
- **Filename:** `tabela-wide-export-sem-pivot.md`
- **Tags:** #export #data #layout
- **Regra:** Tabela abaixo do gráfico deve estar em formato wide (instituição por linha, período por coluna).

### Data como `MM/YYYY` para Reconhecimento Excel
- **Filename:** `data-mm-yyyy-excel.md`
- **Tags:** #formatting #export #data
- **Regra:** Colunas de período da tabela usam `MM/YYYY` para reconhecimento imediato no Excel.

### Tabela de Dados em Expander
- **Filename:** `tabela-dados-expander.md`
- **Tags:** #ux #layout #product
- **Regra:** Dados de apoio ao gráfico devem ficar dentro de expander colapsado por padrão.

### Append-Only em Arquivos de Conhecimento
- **Filename:** `append-only-conhecimento.md`
- **Tags:** #product #scope
- **Regra:** Atualizações do repositório de padrões devem ser somente por append, preservando histórico.
