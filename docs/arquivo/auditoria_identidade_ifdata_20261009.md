# Auditoria e reparo da identidade das instituições — 09/10/2026

## Diagnóstico

A atualização aceitava cadastro vazio ou paginado parcialmente, preenchia nomes com `[IF código]` e podia substituir um cache válido. Havia três leitores de cadastro e resoluções históricas independentes. Não foi confirmado que a causa depende do horário noturno: na consulta desta auditoria, a API Olinda forneceu os nomes.

Foram examinados 3.761 arquivos Parquet locais e publicados no repositório, em 19 famílias de dados, incluindo partições do histórico de taxas. A conferência também abrangeu os 13 assets IFData e derivados do release `v2.0-cache`, identificado no diagnóstico público como o release configurado no runtime. O release de referência do código e dos bundles continua sendo `v1.1-cache`.

| Local / release | Cache | Linhas com nome ausente ou ID | Competências |
|---|---|---:|---|
| Runtime local e bundle do repositório / v1.1-cache | Passivo | 1.406 em cada cópia | Dez/25 |
| v2.0-cache | Passivo | 1.406 | Dez/25 |
| v2.0-cache | Resumo Individual | 271 | Mar/25 a Mar/26 |
| v2.0-cache | DRE Individual | 12 | Mar/25 a Mar/26 |
| v2.0-cache | Derivado Individual | 24 | Mar/25 a Mar/26 |

Os demais arquivos examinados não apresentaram a mesma perda. As dimensões de instituições do histórico de taxas tinham 277 e 279 nomes resolvidos nas duas cópias examinadas. Campos sem nome de instituição individual em 98 linhas do BLOPRUDENCIAL permaneciam identificados pelo conglomerado CBSF DTVM; no COSIF 4010, as 345.835 linhas sem nome de conglomerado tinham nome da instituição individual. Esses campos refletem o perímetro da fonte.

## Correção dos dados

O reparo altera somente a coluna `Instituição`. O teste de igualdade compara todas as outras colunas antes e depois, incluindo valores, ausências, códigos, competências, métricas e unidades. Os históricos e o número de linhas são preservados; o Parquet é relido e comparado antes da substituição. Há backup dos arquivos e metadados anteriores em `data/cache_versions/identity-*`.

Os cadastros oficiais foram persistidos para Mar/25, Jun/25, Set/25, Dez/25 e Mar/26, com checksum dos registros. Dez/25 reúne 5.850 códigos: 5.849 da Olinda e o código `C0084930`, LISTO SCD - PRUDENCIAL, confirmado nos arquivos oficiais do IF.data. Mar/26 também precisou do cadastro financeiro para `C0052395`, QI, cuja identidade é distinta de QI SCD - PRUDENCIAL (`C0084882`).

A correspondência utiliza a competência e o CodInst exato, conservando prefixos e zeros à esquerda. O cadastro financeiro é lido separadamente; seus nomes não substituem os do cadastro geral quando um código aparece em ambos. Nos derivados antigos sem coluna CodInst, a chave só é recuperada quando consta literalmente no marcador `[IF código]`.

Fontes: [cadastro Olinda Dez/25](https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata/IfDataCadastro(AnoMes=202512)), [IF.data oficial](https://www3.bcb.gov.br/ifdata/index.html). URLs, hashes, contagens e competências estão em [ifdata_identity_repair_20261009.json](ifdata_identity_repair_20261009.json) e nos metadados de cada reparo.

## Proteção das atualizações

- Os três extratores usam o mesmo leitor de cadastro, com paginação completa e detecção de páginas repetidas.
- Uma resposta incompleta, vazia, conflitante ou com competência divergente recupera a cópia validada da própria competência ou o cadastro oficial IF.data. Sem cobertura, a extração informa falha.
- Os dez caches IFData e os três derivados recusam gravar ou publicar nomes ausentes e nomes substituídos por IDs.
- Salvamentos parciais, finais, remotos e os fallbacks do app propagam falhas, preservando o arquivo anterior.
- Nomes legítimos com números, como BS2, N26 e C6 BANK, continuam aceitos.
- O bundle de Passivo recebe uma revisão de publicação para que um runtime anterior não prevaleça sobre a correção.

## Reprodução

```sh
.venv/bin/python tools/audit_ifdata_identity.py --root CAMINHO_DO_PROJETO
.venv/bin/python tools/audit_ifdata_identity.py --root CAMINHO_DO_PROJETO --repair --registry data/bundled/institution_registry --output auditoria.json
.venv/bin/python -m pytest -q
```

O comando sem `--repair` faz somente leitura. O reparo verifica todos os períodos e códigos antes de alterar o primeiro arquivo; executá-lo novamente sobre arquivos corrigidos não produz mudanças. A auditoria verifica identidade e persistência; não reestima os números nem as fórmulas financeiras.

## Validação

- 806 testes aprovados, com 14 avisos preexistentes de Matplotlib/Pyparsing.
- Os 13 bundles IFData e derivados do repositório passaram pelos gates de identidade e qualidade aplicáveis.
- Uma extração real do Passivo Dez/25 pela Olinda retornou 1.406 instituições com nomes resolvidos pelo novo fluxo.
- Os testes simulam falha de cadastro, paginação incompleta/repetida, checksum inválido, código sem cobertura, gravação rejeitada e reparo por competência; verificam que o arquivo anterior e os dados numéricos são preservados.

## Persistência publicada

Os reparos foram publicados em `v1.1-cache` (Passivo e manifesto) e `v2.0-cache` (Passivo, Resumo Individual, DRE Individual, derivado individual e manifesto). Os 12 assets foram baixados novamente do GitHub e comparados por SHA-256. Os cinco Parquets baixados não contêm nomes ausentes ou IDs como nome, e todas as demais colunas são idênticas às dos assets anteriores. Os manifestos preservam os demais datasets e as atualizações prévias de SCR e taxas.
