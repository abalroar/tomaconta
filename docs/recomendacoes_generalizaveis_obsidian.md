# Tomaconta — Recomendações Generalizáveis (base para Obsidian + ChatGPT/Claude)

> Objetivo: consolidar padrões recorrentes observados nas interações de produto, dados e implementação do projeto **abalroar/tomaconta**, para reuso em futuros prompts e execuções.
>
> Escopo: diretrizes para UX analítica, comparação temporal, formatação BR, exportação, ausência de dados, ranking/peers e conceitos contábeis (incluindo DRE/COSIF).

---

## 1) Princípios-mãe que se repetem no projeto

1. **Consistência semântica acima de conveniência visual**
   - UI e export devem representar o mesmo recorte, mesma ordem e mesma lógica de cálculo.
2. **Ausência explícita sempre vence fallback silencioso**
   - `NaN`/ausente vira `N/D` na tela e célula vazia no export.
3. **Precisão orientada por comparabilidade**
   - A regra de arredondamento deve preservar diferenças relevantes e evitar “falsa equivalência”.
4. **Base temporal correta antes de comparar**
   - Comparação só é válida quando o tipo de base (tri vs tri, acum vs acum) é coerente.
5. **Começar simples e expandir por complemento**
   - Primeiro entregar opção de maior cobertura de uso; depois adicionar flexibilidade controlada.

---

## 2) Padrões numéricos e de unidades (obrigatórios)

### 2.1 Padrão brasileiro de exibição
- Decimal com vírgula e milhar com ponto.
- Aplicar o mesmo padrão em labels, tooltips, tabelas e eixos.

### 2.2 Escala inteligente (monetário/absoluto)
- `< 1.000` → valor literal (`R$ 850`)
- `≥ 1.000` → mil (`R$ 1,2 mil`)
- `≥ 1.000.000` → MM (`R$ 1.500 MM`)
- `≥ 1.000.000.000` → bi (`R$ 1,0 bi`)
- `≥ 1.000.000.000.000` → tri (`R$ 1,0 tri`)

### 2.3 Percentuais, p.p. e abreviações
- Indicador percentual (ROE, Basileia etc.) deve ser exibido em `%`.
- **Delta de indicador percentual = sempre `p.p.`**, nunca `% sobre %`.
- Percentual: 1 casa por padrão; 2 casas quando dispersão baixa exigir.
- Razões podem usar sufixo `x` quando aplicável.

### 2.4 Regra anti-falsa-equivalência
- Se arredondamento colapsar valores distintos em texto idêntico, aumentar casas decimais até diferenciar.
- Nunca misturar escalas na mesma visualização comparativa (ex.: uma barra em MM e outra em bi no mesmo gráfico).

---

## 3) Comparação temporal (trimestre, acumulado e deltas)

### 3.1 Tipos de comparação a reconhecer
1. **Trimestres coincidentes (YoY trimestral):** ex. `09/2025 vs 09/2024`.
2. **Trimestres consecutivos (QoQ):** ex. `09/2025 vs 06/2025`.
3. **Trimestres não coincidentes e não consecutivos:** ex. `09/2025 vs 03/2025`.

### 3.2 Regra de habilitação de indicadores
- Ao selecionar 2 períodos, a UI deve habilitar apenas indicadores com comparabilidade válida para aquele par temporal.
- Separar explicitamente:
  - **Tri vs tri** para dados trimestrais;
  - **Acum vs acum** para acumulados.

### 3.3 Dados brutos junto de deltas
- Sempre que houver gráfico de variação/delta, exibir bloco/tabela de valores brutos dos mesmos períodos.
- Finalidade: reduzir troca de contexto e acelerar interpretação.

---

## 4) Regras de UX analítica recorrentes

### 4.1 Ranking: simplicidade primeiro
- Preferir pools prontos (Top 5/10/15/20) como modo padrão.
- Evolução opcional: customização controlada (colunas extras, ordenação alternativa).

### 4.2 Pool + entidade fora do pool
- Permitir inserir instituição específica fora do top selecionado e mantê-la na posição real do ranking.
- Destacar visualmente a entidade “injetada”.

### 4.3 Ordenação e leitura visual coerentes
- “Maior → menor” deve bater com posição visual do gráfico/tabela (maior no topo em barra horizontal).
- Evitar conflito entre label textual e ordem desenhada.

### 4.4 Cor e codificação visual
- Em cross-section de período único, usar cor uniforme para evitar inferência de categorias inexistentes.

### 4.5 Toggle que impacta export
- Se houver toggle de data labels, o PNG exportado deve refletir exatamente o estado visível da tela.

### 4.6 Referências estatísticas explícitas
- Quando fizer sentido de produto, incluir linha de média dos selecionados e benchmark global (ex.: média SFN).
- Rodapé metodológico deve explicar universo e tratamento de ausências.

---

## 5) Exportação e paridade UI ↔ arquivo

1. Exportar apenas onde agrega valor analítico (ex.: tabela sim; certos gráficos, não).
2. Estrutura preferencial para Excel: **wide** (entidade por linha, período por coluna).
3. Data de período em `MM/AAAA` para melhor reconhecimento em planilhas.
4. Valor ausente:
   - UI: `N/D`
   - Export: vazio
5. Manter valores brutos no export (sem perder precisão); quando necessário, adicionar coluna formatada complementar.
6. Se houver divergência inevitável entre UI e export, documentar com comentário explícito no código.

---

## 6) Ausência de dados e robustez

- Não interpolar ponto inexistente em série temporal.
- Não converter ausência para zero por conveniência.
- Não remover silenciosamente linhas/entidades com ausência: mostrar estado sem dados.
- Separar “universo de seleção” de “disponibilidade no recorte atual” (dropdown amplo + mensagem contextual de indisponibilidade).

---

## 7) Catálogo de instituições e aliases

- Centralizar construção do universo mestre de instituições para evitar inconsistência entre abas.
- Normalização de nomes/aliases deve ocorrer em ponto único de verdade.
- O fato de uma IF não ter dado em uma aba/período não deve removê-la do catálogo de seleção.

---

## 8) Conceitos contábeis e documentação técnica

### 8.1 DRE e transparência de composição
- Em linhas de DRE com maior ambiguidade, exibir referência IFData + composição COSIF no tooltip.
- Manter mapeamento versionado em arquivo de dados (não hardcoded disperso), com trilha de evolução.

### 8.2 Terminologia e glossário
- Quando houver termo contábil não trivial, reforçar com mini-glossário de apoio na interface.
- Priorizar linguagem objetiva em português, consistente entre tooltip, tabela e export.

### 8.3 Escala interna vs apresentação
- Padronizar internamente escala de cálculo (ex.: percentuais em decimal 0–1) e converter para formato de apresentação somente na borda (UI/export formatado).

---

## 9) Performance e implementação (boas práticas recorrentes)

- Evitar recomputação pesada em interação de filtro: usar cache de pré-processamento quando aplicável.
- Priorizar recorte de dados cedo (por período/instituição) antes de joins e agregações.
- Substituir lookups O(n) repetitivos por índices em memória quando houver gargalo em tabela grande.
- Medir usabilidade com indicadores objetivos (p50/p95 por interação) antes/depois da mudança.
- Compatibilidade defensiva em deploy parcial: shims/funções-resolvedoras pontuais podem evitar quebra sem alterar semântica.

---

## 10) Marcadores, escrita e convenções editoriais (para prompts futuros)

### 10.1 Marcadores de decisão
- `✅ Implementar / manter`
- `❌ Não implementar / remover`
- `🐛 Corrigir`
- `⚠️ Atenção / risco`

### 10.2 Padrão de seções recomendado
1. Objetivo
2. Regra funcional
3. Critérios de aceite
4. Casos-limite (ausência, arredondamento, período)
5. Impacto em export
6. Padrão generalizável (1 frase)

### 10.3 Estilo de texto
- Frases curtas, regra em bullet, exemplo concreto, decisão explícita.
- Sempre separar **dado bruto** de **dado formatado** quando isso impactar análise.

---

## 11) Notas atômicas sugeridas para Obsidian

| # | Nota | Tags |
|---|---|---|
| 1 | `delta-percentual-sempre-pp.md` | `#formatting #math #contabil` |
| 2 | `base-temporal-consistente.md` | `#data #timeseries #math` |
| 3 | `dados-brutos-ao-lado-do-delta.md` | `#ux #layout #analytics` |
| 4 | `escala-unica-por-visualizacao.md` | `#formatting #ux #charts` |
| 5 | `arredondamento-anti-falsa-equivalencia.md` | `#formatting #math` |
| 6 | `paridade-ui-export.md` | `#export #product #data` |
| 7 | `ausencia-explicita-sem-fallback.md` | `#data #quality #ux` |
| 8 | `pool-com-entidade-fora-do-top.md` | `#ux #ranking #filter` |
| 9 | `catalogo-mestre-de-instituicoes.md` | `#data #governance #ux` |
| 10 | `dre-cosif-tooltip-transparente.md` | `#contabil #dre #cosif #glossario` |
| 11 | `data-mm-aaaa-para-excel.md` | `#export #excel #formatting` |
| 12 | `toggle-visual-reflete-no-png.md` | `#ux #export #charts` |
| 13 | `benchmark-global-com-media-filtrada.md` | `#analytics #math #ux` |
| 14 | `normalizacao-unica-de-aliases.md` | `#data #identity #governance` |
| 15 | `medir-p95-antes-de-otimizar.md` | `#performance #engineering` |

---

## 12) Template reutilizável (colar em novas tarefas)

```md
# [NOME DA FUNCIONALIDADE] — Regras e Padrões

## 1. Objetivo
- [1 linha]

## 2. Regras funcionais
- [regra 1]
- [regra 2]

## 3. Formatação / unidades
- [monetário, %, p.p., casas decimais]

## 4. Dados ausentes
- UI: N/D
- Export: vazio
- Sem fallback em cascata

## 5. Export e paridade
- [ordem/filtros/recorte iguais à UI]

## 6. Critérios de aceite
- [check 1]
- [check 2]

## 7. Padrões generalizáveis extraídos
- [padrão A] -> `nome-da-nota-atomica.md`
- [padrão B] -> `nome-da-nota-atomica.md`
```

---

## 13) Checklist rápido antes de fechar qualquer entrega

- [ ] A comparação temporal está semanticamente correta?
- [ ] Percentual foi tratado corretamente (`%` vs `p.p.`)?
- [ ] Escala e arredondamento preservam diferenças relevantes?
- [ ] Ausências aparecem como `N/D` (UI) e vazio (export)?
- [ ] UI e export estão em paridade de filtros/ordem/cálculo?
- [ ] Estrutura exportável está pronta para uso no Excel sem retrabalho?
- [ ] Decisões de produto simples vs flexível foram explícitas?

