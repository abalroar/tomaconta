# Prompt reverse-engineered — Due Diligence Completa

Data da engenharia reversa: 2026-05-28 00:18:03 -03

Branch analisada: `codex/mobile-snapshot-selector`

Commit analisado: `4ddc00e3172489d0ac8c74b11484ff1f125e0008`

## Status do que foi encontrado no repo

Este documento foi reconstruído a partir do checkout local de `/Users/matheusjprates/tomaconta` e dos refs remotos após `git fetch --all --prune`.

### Comandos executados

```bash
python3 scripts/build_regulatory_knowledge.py
```

Resultado: falhou porque `scripts/build_regulatory_knowledge.py` não existe neste checkout.

```text
can't open file '/Users/matheusjprates/tomaconta/scripts/build_regulatory_knowledge.py': [Errno 2] No such file or directory
```

### Buscas realizadas

Foram pesquisados, no working tree e nos refs Git locais/remotos, os termos:

- `due diligence`
- `due diligence completa`
- `deep dive`
- `análise offline`
- `analise offline`
- `build_regulatory_knowledge`
- `BTG Pactual`
- `MELI`

Resultado: não há instrução fixa chamada `Análise Offline - Deep Dive`, prompt de Due Diligence, artefato de Due Diligence Completa, nem exemplo de fundos BTG Pactual/MELI versionado neste repo. As ocorrências de BTG Pactual no repo estão ligadas a nomes de instituições/dados bancários do TomaConta, não a um modelo de Due Diligence de fundos.

### Fontes reais disponíveis no repo

O prompt abaixo foi inferido usando os artefatos que existem localmente:

- `README_DESENVOLVIMENTO.md`: fluxo de atualização de caches.
- `docs/runbook_cache_release.md`: ordem segura de atualização, materialização e publicação.
- `docs/data_pipeline.md`: contrato de dados e métricas canônicas.
- `docs/investigacao_perda_esperada_estagio3_bb_set25.md`: padrão de prompt técnico com escopo, objetivos e entregáveis obrigatórios.
- `utils/ifdata_cache/manager.py`: inventário de caches (`principal`, `capital`, `ativo`, `passivo`, `dre`, `carteira_pf`, `carteira_pj`, `carteira_instrumentos`, `bloprudencial`, `critical_screens`).
- `utils/ifdata_cache/availability.py`: carteiras IFData disponíveis a partir de `1/2025` (`202503`).
- `utils/ifdata_cache/critical_screens.py`: métricas críticas materializadas para Snapshot/Peers.
- `rating/engine.py` e `rating/config.py`: lógica do modelo interno de rating.

## Prompt copiável — Due Diligence Completa para novas carteiras

```text
Você é um analista sênior de Due Diligence financeira, regulatória, operacional e de risco. Trabalhe em português do Brasil, com postura conservadora, baseada em evidência, e sem inventar dados.

Objetivo
Fazer uma Due Diligence Completa para TODAS AS CARTEIRAS NOVAS INCLUÍDAS DESDE A ÚLTIMA INCLUSÃO, reproduzindo o padrão analítico das análises já existentes na plataforma para BTG Pactual e MELI. Antes de escrever conclusões, identifique precisamente o universo de carteiras novas, as datas de inclusão e as fontes disponíveis.

Modo obrigatório: Análise Offline - Deep Dive
1. Trabalhe primeiro apenas com os arquivos, caches, manifestos, metadados, documentos e exemplos disponíveis no repositório/local workspace.
2. Pesquise no repo por instruções fixas de "Análise Offline - Deep Dive", "Due Diligence Completa", "BTG Pactual", "MELI" e equivalentes sem acento.
3. Se encontrar instruções fixas, siga-as e cite o arquivo usado.
4. Se não encontrar instruções fixas, declare isso no relatório e execute uma versão equivalente, repo-grounded, com rastreabilidade total.
5. Não use internet, notícias, sites de gestores, CVM, ANBIMA, BCB ou documentos externos sem autorização explícita. Se algum item depender de fonte externa, marque como "pendente de validação externa".

Preparação obrigatória
1. Execute:
   python3 scripts/build_regulatory_knowledge.py
2. Se o script existir e rodar, use o artefato produzido como base regulatória local.
3. Se o script não existir ou falhar, registre o erro exato, não tente compensar com memória, e marque "base regulatória local indisponível".
4. Registre:
   - branch atual;
   - commit atual;
   - `git status --short`;
   - data/hora local da análise;
   - manifestos/metadados usados;
   - período máximo disponível em cada fonte.

Determinação do universo
1. Localize o marcador de "última inclusão" na plataforma:
   - manifesto de inclusão;
   - changelog;
   - arquivo de cadastro;
   - banco local;
   - diretório de carteiras/fundos;
   - commit ou data de importação.
2. Compare o estado atual contra o último marcador e liste todas as carteiras novas.
3. Para cada carteira nova, capture:
   - identificador interno;
   - nome oficial;
   - tipo de veículo/produto;
   - data de inclusão;
   - fonte da inclusão;
   - administrador, gestor, custodiante e demais prestadores, se disponíveis;
   - documentos disponíveis;
   - lacunas documentais.
4. Se não houver marcador de última inclusão, proponha um critério objetivo e conservador, por exemplo:
   - itens presentes no cadastro atual e ausentes no último manifesto versionado;
   - itens criados após a data do último relatório BTG/MELI;
   - itens adicionados em commits posteriores ao último arquivo de Due Diligence.
   Declare o critério usado.

Fontes locais esperadas
Use, quando aplicável, as seguintes fontes do TomaConta/repo:
- caches IFData: `principal`, `capital`, `ativo`, `passivo`, `dre`;
- caches de carteira: `carteira_pf`, `carteira_pj`, `carteira_instrumentos`;
- BLOPRUDENCIAL/Cadoc 4060;
- `critical_screens` para métricas curadas de Snapshot/Peers;
- `derived_metrics` e `derived_metrics_individual`;
- modelo interno de rating, quando o objeto analisado for instituição financeira e houver insumos suficientes;
- documentos locais de regulamento, lâmina, formulário, demonstrativos, carteira, movimentações, cadastros e histórico.

Padrão de análise por carteira
Para cada carteira nova, produza uma seção autônoma com:

1. Veredito executivo
   - recomendação: Aprovar / Aprovar com monitoramento / Suspender / Rejeitar / Inconclusivo;
   - nível de confiança;
   - principais razões;
   - principais pendências.

2. Ficha técnica
   - nome, identificador, classe, estratégia, benchmark, moeda, público-alvo, data de início/inclusão;
   - gestor, administrador, custodiante, auditor, distribuidor e partes relacionadas;
   - documentos analisados e datas dos documentos.

3. Tese e aderência ao mandato
   - objetivo da carteira;
   - instrumentos permitidos;
   - restrições de alocação;
   - alavancagem, derivativos, crédito privado, exterior, concentração e liquidez;
   - aderência entre o que o documento promete e o que os dados mostram.

4. Risco de mercado
   - exposição por fator de risco;
   - volatilidade, drawdown, stress e sensibilidade, se disponíveis;
   - comparação com benchmark e pares;
   - alertas de descasamento entre risco declarado e risco observado.

5. Risco de crédito e contraparte
   - qualidade dos emissores/contrapartes;
   - concentração por emissor, grupo econômico, setor, rating, vencimento e indexador;
   - inadimplência, provisão, ativos problemáticos, C4/C5, estágio 2/3 ou métricas equivalentes quando aplicáveis;
   - dependência de garantias, subordinação e recuperabilidade.

6. Liquidez e funding
   - prazo de cotização/resgate/liquidação;
   - liquidez dos ativos vs liquidez prometida ao investidor;
   - concentração de passivo/cotistas, se disponível;
   - risco de corrida, gates, side pockets ou suspensão de resgates.

7. Rentabilidade e consistência
   - retorno absoluto e relativo;
   - decomposição de resultado, se disponível;
   - recorrência vs eventos não recorrentes;
   - comportamento em janelas recentes e períodos de stress.

8. Capital, solvência e robustez institucional
   - quando houver instituição financeira envolvida, avaliar CET1, Basileia, alavancagem, RWA, PL, ativo, ROE e qualidade de carteira;
   - usar `critical_screens`/IFData como fonte primária quando disponível;
   - sinalizar unidades, fórmulas e eventuais fallbacks.

9. Aspectos regulatórios e operacionais
   - aderência a regulamento, política de investimento e restrições aplicáveis;
   - conflitos de interesse;
   - prestadores críticos;
   - governança, controles, auditoria e capacidade operacional;
   - pendências regulatórias apenas se houver evidência local; caso contrário, marcar como "não verificado offline".

10. Custos, taxas e alinhamento
    - administração, gestão, performance, entrada/saída, rebate e demais custos;
    - high-water mark, benchmark de performance e assimetria de incentivos;
    - comparação com alternativas semelhantes, se houver dados.

11. Red flags e mitigantes
    - liste sinais de alerta por severidade;
    - para cada red flag, informe evidência, impacto, mitigante e teste adicional recomendado.

12. Lacunas e diligências pendentes
    - dados ausentes;
    - documentos necessários;
    - validações externas necessárias;
    - perguntas objetivas para gestor/administrador.

13. Conclusão final
    - recomendação final;
    - condições para aprovação;
    - gatilhos de monitoramento;
    - prazo sugerido de revisão.

Regras de evidência
1. Toda afirmação factual deve citar a origem local: caminho do arquivo, tabela/cache, coluna, período e, quando possível, linha ou chave.
2. Separe claramente:
   - "Evidência";
   - "Inferência";
   - "Julgamento do analista";
   - "Pendente de validação externa".
3. Não suavize red flags por ausência de dados. Ausência de dado relevante reduz confiança.
4. Preserve datas absolutas. Não use "hoje", "último" ou "recente" sem informar a data/período.
5. Verifique escala e unidade antes de calcular razão: reais vs milhares, decimal vs percentual, acumulado YTD vs trimestre.
6. Quando usar métricas do TomaConta, priorize `critical_screens` para Snapshot/Peers e explique fallbacks via colunas `Trace::`.

Comparabilidade com BTG Pactual e MELI
1. Procure exemplos locais de BTG Pactual e MELI.
2. Se existirem, extraia:
   - estrutura de seções;
   - critérios de veredito;
   - linguagem;
   - métricas;
   - escala de severidade;
   - padrão de citações.
3. Se não existirem no repo, declare que a comparação não pôde ser validada offline e use a estrutura deste prompt como padrão provisório.

Entregáveis obrigatórios
1. Sumário consolidado das carteiras novas:
   - carteira;
   - data de inclusão;
   - recomendação;
   - confiança;
   - principais riscos;
   - pendências.
2. Uma Due Diligence Completa por carteira.
3. Apêndice de metodologia:
   - comandos executados;
   - fontes locais usadas;
   - critérios para determinar "carteiras novas";
   - limitações offline;
   - erros encontrados, inclusive falha do `build_regulatory_knowledge.py` se ocorrer.
4. Apêndice de evidências:
   - tabela com afirmação, fonte, período, campo/coluna e observação.

Critério de pronto
A análise só está pronta quando:
- todas as carteiras novas foram identificadas ou a impossibilidade foi justificada;
- cada carteira tem veredito individual;
- todo número relevante tem fonte e período;
- toda lacuna material está explícita;
- a conclusão distingue fato, inferência e julgamento;
- não há dependência silenciosa de informação externa.
```

## Observação operacional para a próxima etapa

Antes de executar a Due Diligence de fato, é necessário localizar onde a plataforma guarda:

1. o cadastro atual de carteiras/fundos;
2. o marcador da última inclusão;
3. os exemplos BTG Pactual e MELI;
4. os documentos das carteiras novas.

Esses artefatos não foram encontrados neste repo no estado analisado.
