# Revisão da página Sobre — 09/10/2026

## Interface e conteúdo

| Before | After | Why |
| --- | --- | --- |
| Cinco números em duas linhas e gráfico sempre visível | Seletor Resumo / Por semana; resumo em uma linha no desktop | Reduzir a altura e permitir escolher a informação |
| Alertas de atualização manual, botão e formulário de parâmetros | Atualização automática, data do cálculo e metodologia recolhida | Eliminar a etapa manual e reduzir controles na página inicial |
| Cartões de módulos sem ação e nomes antigos | Links com os mesmos nomes do menu atual | Facilitar o acesso e evitar referências a abas retiradas |
| Crédito BC, SPB, Contas COSIF e demonstrações individuais ausentes | Catálogo com todos os módulos de análise e o Glossário | Refletir os módulos publicados |
| Contribuições FGC/FGCoop descritas como módulo próprio | Recurso identificado dentro de Contas COSIF | Corresponder à navegação existente |
| Capital principal identificado como Tier 1 | CET1 separado de Capital Nível 1 e Basileia Total | Corrigir a nomenclatura |
| Crédito / PL descrito como percentual | Carteira / PL descrito como múltiplo | Corresponder à unidade usada em Peers e Evolução |
| Catálogo de métricas anterior aos novos painéis | Custo de crédito, custo / receita, NPL, ativos problemáticos, estágios e coberturas; SGS, SCR.data e SPB | Incluir indicadores e recortes implementados após junho |
| Exportação descrita somente como Excel / CSV | Office editável e formatos disponíveis por módulo | Refletir PPTX nativo e os downloads atuais |
| Fontes descritas de forma incompleta | IFData, COSIF, CDSFN, SGS, SCR.data e SPB; memória de cálculo, perímetros e N/D | Explicar a origem e os limites dos dados |
| Stack anterior às exportações Office e armazenamento Parquet | Bibliotecas e fontes alinhadas às implementações existentes | Atualizar a descrição técnica |

As descrições foram conferidas contra o dispatcher de `app1.py`, `tabs/peers_table.py`, `tabs/mercado_credito.py`, os exportadores nativos e o registro de métricas em `utils/ifdata_cache/metric_registry.py`. O teste de catálogo compara os nomes com os menus do dispatcher para detectar futuras inclusões sem descrição.

## Consulta e cálculo

Consulta completa em 09/10/2026 às 18:55 de Brasília, na revisão principal `6f56f9b07eefe86a9f1a5c64a137eb791ed64218`:

| Item | Resultado |
| --- | ---: |
| Horas entre commits | 219,53 h |
| Overhead | 54,00 h |
| Total estimado | 273,53 h |
| Sessões | 162 |
| Sessão média | 1,69 h |
| Commits únicos | 875 |
| Commits repetidos desconsiderados | 226 |

Mantidos os parâmetros anteriores: nova sessão quando o intervalo supera 90 minutos, mais 20 minutos de overhead por sessão. Datas de autoria são ordenadas em uma única linha do tempo; duplicatas são removidas por SHA ou data e mensagem. A semana começa na segunda-feira em Brasília. A sessão inteira pertence à semana de início. Semanas sem atividade são incluídas com zero.

O GitHub informa que `abalroar/ficadeolho` redireciona para `abalroar/tomaconta`. A lista histórica de três nomes foi preservada, resolvendo os dois repositórios canônicos antes da paginação:

| Repositório | Revisão consultada | Commits consultados | Merges excluídos | Considerados antes da deduplicação |
| --- | --- | ---: | ---: | ---: |
| abalroar/tomaconta-dev | 0714a46e4e6b67553396a80a3c05e9b6b77f9d60 | 803 | 370 | 433 |
| abalroar/tomaconta | 6f56f9b07eefe86a9f1a5c64a137eb791ed64218 | 1.062 | 394 | 668 |

Merges agora são identificados pelo número de pais do commit. O algoritmo anterior dependia de prefixos na mensagem. Recalculando o corte antigo de 03/06/2026 às 15:27:03 UTC com o histórico atual e o critério corrigido, o resultado é 235,92 h, 127 sessões e 774 commits, comparado a 236,01 h, 127 sessões e 776 commits no snapshot anterior. A diferença de 0,09 h nesse corte acompanha a exclusão correta de merges; o aumento até outubro decorre da ampliação do histórico.

As horas representam uma estimativa de atividade por commits. O histórico não mede toda a duração do trabalho. O overhead é uma hipótese; os cenários exibidos na metodologia não constituem intervalo estatístico.

## Atualização automática

- O snapshot distribuído permanece em `data/dev_hours_cache.json`.
- Consultas em execução gravam `data/cache/development_hours/estimate.json`, ignorado pelo Git, através de substituição atômica.
- A primeira visita com cálculo expirado (24 horas), ausente ou incompatível inicia a consulta em segundo plano. Uma página aberta também verifica a validade periodicamente.
- Sessões simultâneas compartilham a mesma consulta. O último cálculo íntegro continua visível.
- A paginação usa uma revisão fixa por repositório para evitar deslocamento de páginas por novos commits.
- Erros e limites de API preservam valores e data. Uma nova tentativa ocorre após 15 minutos, enquanto a página estiver aberta ou no próximo acesso após o prazo.
- O GitHub é consultado para leitura; a atualização automática não publica arquivos no repositório.

## Validação

Testes cobrem agrupamento no limite de 90 minutos, overhead, deduplicação entre históricos, fuso de Brasília, sessões que cruzam semanas, semanas sem atividade, aliases, paginação fixa, merges, fallback de autenticação pública, falhas de consulta, validade de cache, escrita atômica, atualização compartilhada, preservação e nova tentativa automática. O teste Streamlit verifica a exclusão mútua entre Resumo e Por semana. O catálogo é conferido contra os menus atuais.

A inspeção visual local confirmou resumo compacto, gráfico e metodologia recolhida. Um teste no navegador iniciou a consulta real a partir do snapshot de junho: 236,0 h permaneceram visíveis durante a consulta e o valor mudou automaticamente para 273,5 h, sem intervenção do usuário. A publicação deve ser conferida separadamente da aprovação e merge do código.

Validação do código: 838 testes passaram; o check de unicidade do dispatcher e `git diff --check` passaram. Os avisos da suíte são de depreciação em dependências do Matplotlib.
