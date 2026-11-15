# DRE × COSIF — Investigação e proposta (Etapa 0)

## Objetivo
Mapear, na aba **DRE**, as linhas exibidas para as contas **COSIF** correspondentes, de forma que o tooltip (ⓘ) e o mini-glossário mostrem o mapeamento exatamente como referenciado no IFData.

## Escopo da Etapa 0
Implementar um piloto validado para a linha:
- **Res. Derivativos**
- Referência IFData: **Resultado com Derivativos (i)**
- Regra de composição exibida no tooltip:
  - **Somatório das contas COSIF [7158000003] + [8155000005]**

## Evidências coletadas
1. A aplicação já possui tooltip por linha na DRE e mini-glossário com texto explicativo.
2. O repositório contém amostra de balancete COSIF 4060 com os códigos:
   - `7158000003` — Rendas em operações com derivativos
   - `8155000005` — (-) Despesas em operações com derivativos
3. A linha de DRE já usa a denominação IFData **Resultado com Derivativos (i)**.

## Proposta de evolução (fases)
1. **Etapa 0 (esta entrega):**
   - inserir estrutura de mapeamento COSIF local no bloco DRE;
   - preencher o caso validado de derivativos;
   - exibir no tooltip referência IFData + fórmula COSIF;
   - registrar no mini-glossário que o piloto foi ativado.
2. **Etapa 1:**
   - expandir para demais linhas de intermediação (a…j), priorizando itens mais usados.
3. **Etapa 2:**
   - mover o mapeamento para arquivo versionado (`data/dre_cosif_mapping.json`), com revisão por linha e trilha de validação.
4. **Etapa 3:**
   - incluir validação automática: comparar soma das contas COSIF com o valor da linha IFData (tolerância configurável).

## Observações técnicas
- A estrutura adicionada no código permite ampliar o mapeamento sem alterar o renderer.
- O texto foi mantido em português e no mesmo padrão de linguagem da interface atual.


## Evolução aplicada
- A etapa 0 passou a usar arquivo versionado com de-para por linha (`data/dre_cosif_mapping.json`), incluindo conta COSIF e descrição exibidas no tooltip (ⓘ).

## Fonte estável (COSIF oficial)
- Para reduzir fragilidade de scraping HTML/JS, o app passa a suportar enriquecimento por PDF oficial do COSIF:
  - `https://www3.bcb.gov.br/aplica/cosif/manual/completo_contas.pdf`
- Estratégia aplicada:
  1. cache local do PDF em `data/cache/cosif/`;
  2. parse de linhas `código + descrição` por regex;
  3. persistência de dicionário local para reuso rápido;
  4. uso desse dicionário para preencher/atualizar descrições COSIF no tooltip e na aba exportável `Glossário COSIF`.
