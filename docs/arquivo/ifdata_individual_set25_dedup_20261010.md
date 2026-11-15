# IFData Individual — reconciliação de setembro de 2025

Os JSON oficiais do IFData/OData de setembro de 2025 repetem exatamente três vezes cada célula dos relatórios Individual 1 (Resumo) e 4 (DRE). O extrator somava essas cópias no pivot, inflando os saldos e resultados desse trimestre.

A reconstrução usa uma ocorrência de cada célula oficial, identificada por instituição, competência, relatório, grupo, conta e coluna. Células com conteúdos conflitantes são rejeitadas. As sete rubricas monetárias do Resumo e as rubricas da DRE reconciliaram integralmente com o valor publicado anteriormente, que correspondia a três vezes a célula única. Os demais períodos, códigos, nomes e quantidades de linhas foram preservados.

O cache de métricas Individual foi reconstruído com os relatórios 1 e 4, unindo e agrupando por `CodInst`. Os denominadores de captações e carteira pertencem à mesma pessoa jurídica. A base Individual conserva `N/D` para ativos problemáticos, capital e carteira prudencial sem fonte do mesmo escopo. O lucro anual acumulado e o trimestre isolado do Snapshot usam a periodicidade semestral do IFData: setembro corresponde a julho–setembro; dezembro corresponde a julho–dezembro.

Exemplo de controle: o ativo individual do Itaú em Set/25 passa a R$ 2.058,29 bilhões; o lucro isolado do 4T25 passa a R$ 7,04 bilhões. O valor reconstruído provém das células oficiais únicas.

O [registro de reconciliação](ifdata_individual_set25_dedup_20261010.json) contém URLs, hashes dos JSON brutos, contagens, testes de reconciliação e os sete arquivos de publicação com caminhos relativos ao repositório. O manifesto completo parte da versão publicada em `v1.1-cache` consultada em 10/10/2026 e preserva todos os outros caches, arquivos e gates, incluindo o histórico de taxas.

Para reproduzir em uma cópia dos bundles anteriores à correção, com os JSON brutos e o manifesto publicado salvos localmente:

```sh
python tools/repair_ifdata_individual_202509.py \
  --repo /caminho/do/repositorio \
  --summary-json /caminho/olinda-individual-202509.json \
  --dre-json /caminho/olinda-individual-dre-202509.json \
  --manifest-json /caminho/manifest-publicado.json
```

O script exige a reconciliação com os bundles anteriores e interrompe a execução se houver divergência ou célula conflitante.
