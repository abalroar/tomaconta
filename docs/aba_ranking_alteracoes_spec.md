# Aba Ranking — Alterações Funcionais e de UX (Spec)

## Escopo
Este documento consolida as alterações necessárias na **Aba Ranking** para:
- melhorar leitura visual dos gráficos;
- manter consistência de cálculo (médias e referência SFN);
- padronizar formatação numérica e arredondamento;
- garantir exportação prática para uso no Excel;
- registrar padrões generalizáveis para a base de conhecimento (Obsidian).

---

## 1) Gráfico — Toggle de Data Labels

### Objetivo
Permitir ao usuário fixar/ocultar os valores exibidos no gráfico por meio de um toggle explícito.

### Requisito funcional
- Incluir toggle **"Data labels"** na área de configuração do gráfico da Aba Ranking.
- Estados:
  - **Ligado:** exibir valores numéricos junto aos elementos do gráfico.
  - **Desligado:** ocultar valores no gráfico.
- O estado do toggle deve afetar:
  - visualização na tela;
  - export do gráfico (PNG) com os labels exatamente como vistos no momento do clique.

### Critérios de aceite
- Ao alternar o toggle, o gráfico deve atualizar sem recarregar a página inteira.
- O export PNG deve respeitar o estado atual do toggle.
- A leitura dos labels deve seguir a regra de formatação numérica brasileira descrita neste spec.

---

## 2) Gráfico — Médias de Referência

### Objetivo
Adicionar duas linhas de referência ao gráfico para facilitar comparação:
1. **Média dos nomes selecionados**;
2. **Média SFN**.

### Requisito funcional
- Para qualquer seleção ativa no gráfico:
  - plotar linha horizontal **pontilhada preta** para a média dos nomes selecionados;
  - plotar linha horizontal adicional para **Média SFN** (estilo visual distinto da primeira, preservando contraste).
- Ambas as médias devem aparecer na legenda.
- Exibir no rodapé da aba texto explicando critérios de cálculo.

### Critérios de cálculo (texto obrigatório no rodapé)
Texto sugerido (padrão mínimo):

> **Critérios de cálculo das médias:**
> - **Média Selecionados:** média aritmética simples considerando apenas as instituições atualmente selecionadas e com valor válido no período/variável.
> - **Média SFN:** média aritmética simples da mesma variável e mesmo período para o universo SFN disponível na base, considerando apenas valores válidos.
> - Valores ausentes (NaN) são tratados como **N/D** na visualização e **não entram** no cálculo das médias.

### Critérios de aceite
- A linha “Média Selecionados” deve refletir exatamente o subconjunto filtrado na tela.
- A linha “Média SFN” deve permanecer estável para o mesmo período/variável, independentemente dos nomes selecionados.
- Legenda e tooltip devem identificar claramente cada média.

---

## 3) Formatação Numérica, Escala e Arredondamento

### Princípios
- Padrão brasileiro obrigatório:
  - decimal com vírgula (`15,5%`);
  - milhar com ponto (`1.545`).
- Não arredondar de forma que gere falsa equivalência visual.
- Em comparação lado a lado (justaposição), priorizar precisão suficiente para preservar diferença perceptível.

### Tabela padrão de escala (referência oficial)

| Magnitude       | Exibição      | Exemplo     |
| --------------- | ------------- | ----------- |
| < 1.000         | Valor literal | R$ 850      |
| ≥ 1.000         | Milhares      | R$ 1,2 mil  |
| ≥ 1.000.000     | Milhões (MM)  | R$ 1.500 MM |
| ≥ 1.000.000.000 | Bilhões (bi)  | R$ 1,0 bi   |
| Percentuais     | 1–2 casas     | 12,5%       |
| Delta de %      | p.p.          | +2,0 p.p.   |

### Regras de arredondamento (obrigatórias)
- Nunca misturar escalas no mesmo gráfico (ex.: uma barra em MM e outra em bi).
- Se o arredondamento em 1 casa colapsar valores distintos em rótulos iguais, aumentar precisão (2+ casas) até diferenciar.
- Para percentuais:
  - padrão = 1 casa;
  - usar 2 casas quando dispersão for baixa e houver risco de equivalência aparente.
- Para delta de variáveis percentuais, usar sempre **p.p.** (não variação % sobre %).

### Critérios de aceite
- Exemplo crítico deve ser resolvido: valores próximos (ex.: 1,535 tri vs 1,590 tri) não podem parecer iguais após formatação.
- Todos os números exibidos na Aba Ranking devem seguir padrão brasileiro.

---

## 4) Tabela Descritiva do Gráfico (na Aba)

### Objetivo
Disponibilizar tabela pronta para uso analítico e exportável sem fricção.

### Requisito funcional
- A tabela descritiva deve existir para o recorte exibido no gráfico.
- Deve ficar sempre dentro de um **expander** (evitar poluição visual).
- Deve existir botão simples: **"Exportar p/ Excel"**.

### Estrutura de dados para export
- Formato preferencial de período: **MM/AAAA** (ex.: `03/2025`).
- Para origem trimestral (`1/AAAA`, `2/AAAA`, `3/AAAA`, `4/AAAA`), converter para mês de fechamento:
  - `1T` → `03/AAAA`
  - `2T` → `06/AAAA`
  - `3T` → `09/AAAA`
  - `4T` → `12/AAAA`
- Layout da planilha:
  - **uma instituição por linha**;
  - **um período por coluna**;
  - evitar repetição de instituição em múltiplas linhas para o mesmo contexto.
- Objetivo: permitir uso direto no Excel sem necessidade de Pivot Table para tarefas básicas.

### Regras de ausência
- Na UI: ausência exibida como **N/D**.
- No Excel: célula vazia para ausência (sem forçar zero).

### Critérios de aceite
- Export deve abrir no Excel com período reconhecível como data no formato MM/AAAA.
- Estrutura exportada deve ser imediatamente manipulável para gráfico/manual sem pivot obrigatória.

---

## 5) Paridade UI ↔ Export

### Regra
Sempre que houver exportação, o conteúdo deve refletir a mesma lógica da tela (filtros, ordem e recorte).

### Diretriz operacional
- Export deve carregar valores brutos para análise (sem perda de precisão).
- Caso haja necessidade de versão formatada para leitura, incluir coluna complementar formatada sem substituir o valor bruto.
- Se houver divergência inevitável entre UI e export, documentar no código com comentário explícito:
  - `# EXPORT: difere da UI porque ...`

---

## 6) Padrões Generalizáveis (Extração para Obsidian)

> Critério aplicado: incluir padrão quando a regra se aplica a pelo menos uma situação além da Aba Ranking.

| Nome descritivo | Filename sugerido | Tags | Regra em uma frase |
|---|---|---|---|
| Persistência de Data Labels em Gráficos | `persistencia-data-labels-graficos.md` | #ux #layout #data #product | Qualquer gráfico com toggle de labels deve exportar imagem exatamente com o estado visual ativo no momento do export. |
| Linha de Média por Escopo de Filtro | `linha-media-por-escopo-filtro.md` | #math #data #filter #ux | Médias derivadas de seleção devem considerar apenas o subconjunto filtrado e excluir valores ausentes do cálculo. |
| Linha de Benchmark Global Paralela à Seleção | `linha-benchmark-global.md` | #math #data #product #scope | Além da média do recorte, exibir benchmark global com critério fixo para contextualizar desempenho relativo. |
| Formatação Numérica Sensível à Dispersão | `formatacao-sensivel-dispersao.md` | #formatting #math #ux | A precisão decimal deve aumentar quando o arredondamento puder ocultar diferenças relevantes entre valores próximos. |
| Escala Única por Visualização Comparativa | `escala-unica-por-grafico.md` | #formatting #ux #data | Em gráficos comparativos, aplicar uma única unidade de escala para todos os elementos para evitar interpretação ambígua. |
| Ausência Explícita sem Fallback Numérico | `ausencia-explicita-sem-fallback.md` | #data #product #scope | Dados ausentes devem ser exibidos como N/D na interface e vazios no export, sem substituição por zero ou interpolação automática. |
| Padrão de Data Amigável ao Excel | `padrao-data-mm-aaaa-excel.md` | #export #data #formatting | Para export analítico mensal, usar MM/AAAA para maximizar reconhecimento de data e reduzir retrabalho manual. |
| Tabela Pronta para Consumo sem Pivot | `tabela-larga-sem-pivot.md` | #export #layout #product | Sempre priorizar estrutura com entidade em linha e tempo em coluna para uso direto no Excel sem dependência de tabela dinâmica. |
| Paridade Semântica UI e Export | `paridade-semantica-ui-export.md` | #export #product #scope | O arquivo exportado deve preservar filtros, ordenação e regras de cálculo visíveis na interface para evitar inconsistência analítica. |

---

## 7) Checklist de Implementação (Aba Ranking)

- [ ] Adicionar toggle "Data labels" e amarrar ao render do gráfico.
- [ ] Garantir persistência do estado do toggle no export PNG.
- [ ] Adicionar linha pontilhada preta de "Média Selecionados".
- [ ] Adicionar linha de "Média SFN" com estilo distinto e legenda.
- [ ] Incluir texto de critérios de cálculo no rodapé da aba.
- [ ] Aplicar tabela padrão de escala para todos os labels/tooltips/tabela.
- [ ] Implementar arredondamento adaptativo para evitar equivalência falsa.
- [ ] Renderizar tabela descritiva dentro de expander.
- [ ] Implementar botão "Exportar p/ Excel" para tabela descritiva.
- [ ] Garantir formato de período MM/AAAA no export.
- [ ] Garantir layout instituição em linha × período em coluna.
- [ ] Validar paridade de filtros, ordem e cálculo entre UI e export.

---

## 8) Nome do artefato
Arquivo gerado conforme convenção solicitada:
- `aba_ranking_alteracoes_spec.md`

> Caminho no repositório: `docs/aba_ranking_alteracoes_spec.md`
