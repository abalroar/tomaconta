# Atualização geral — junho de 2026

Publicação: `tomaconta-jun26-20260911-v1`, preparada em 10/09/2026 (Brasília).
Release geral: `v1.1-cache`. O SCR mantém seu release próprio `v1.2-scr-cache`.
A identidade e os SHA-256 dos 50 assets estão em `atualizacao_jun26_auditoria.json`.

## Cobertura

| Base | Registros de jun/26 | Histórico após atualização |
|---|---:|---:|
| Principal prudencial | 1.398 | 63.459 |
| Principal individual | 1.622 | 28.114 |
| Capital | 1.325 | 61.653 |
| Ativo / Passivo / DRE prudencial, cada | 1.342 | 63.403 |
| DRE individual | 1.571 | 28.063 |
| Carteira PF / PJ, cada | 1.101 | 6.649 |
| Carteira por instrumentos 4.966 | 1.101 | 8.018 |
| Snapshot / Peers / métricas curadas | 1.398 | 63.379 |
| COSIF 4060/4066 | 84.805 | 1.244.497 |
| COSIF 4010 | 345.835 | 345.835 |
| SGS | 130 séries | 24.042 observações |
| SCR, resumo regional | 3.640 | 594.290 |
| Taxas de juros | 16.169 | 2.764.031 |

Os relatórios mantêm seus perímetros próprios. Uma instituição cadastrada pode
não publicar valores em determinado relatório; a ausência permanece ausente.
Os derivados prudencial e individual foram recalculados com 317.015 e 140.315
linhas, respectivamente. As métricas curadas de junho usam também os trimestres
de 2025 e março/2026 para lucro trimestral, anualização e PL de dezembro anterior.
As linhas curadas anteriores foram preservadas integralmente.

SCR e Taxas já continham julho/2026. O download real do resumo SCR confirmou
junho e julho; os seis arquivos de Taxas versionados no Git foram alinhados ao
release geral, que ainda tinha uma versão anterior. As 130 séries SGS já cobriam
junho e foram preservadas, inclusive observações posteriores.

### Meios de pagamento — SPB

Os 12 conjuntos foram obtidos integralmente pela ingestão existente, totalizando
753.069 linhas. Núcleo trimestral e cartões têm junho/2026; núcleo mensal tem
julho/2026. Os nove conjuntos abaixo ainda terminam em **1T2026 na fonte BCB**:
intercâmbio, desconto, portador, ATM, terminais, estabelecimentos credenciados,
infraestrutura de estabelecimentos, canais de serviços e canais de transações.
O detalhe por conjunto, URL de consulta e hash está no arquivo de auditoria.
Esses nove conjuntos não são apresentados como atualizados até junho.

### Consultas sob demanda

Balanço, DRE e DMPL (Ind.) usa o documento 9011 do CDSFN sob demanda. A consulta
oficial de junho do Itaú (`60701190`) foi validada: BP, DRE, DRA, DFC e DMPL,
unidade informada pelo documento de R$ milhões. A disponibilidade continua
individual; esta validação não afirma cobertura de todos os documentos 9011.
Conselho e Diretoria mantém consulta cadastral corrente, sem competência mensal
materializada no aplicativo.

## Fonte IF.data e preservação do histórico

A API Olinda retornou HTTP 500 nas consultas de junho e nos controles de março.
Foi incluído o backend explícito `TOMACONTA_IFDATA_SOURCE=web`, que lê os mesmos
arquivos oficiais utilizados por [IF.data](https://www3.bcb.gov.br/ifdata/):
catálogo `rest/relatorios2025a2030`, cadastro, descritores e cinco áreas de valores.
As URLs e os hashes de cada arquivo constam dos metadados das bases.

O leitor usa valores brutos em reais e razões decimais. Não executa código da
fonte nem replica a formatação visual em milhares/percentuais. Valida competência,
perímetro, código, duplicidades e arquivos obrigatórios. O identificador interno
`c0` localiza células; `c33` identifica a instituição. Para conglomerados de arquivos
anteriores a junho, `c34=4` permite normalizar o prefixo de `c33` para `C`.

A reconciliação de março comparou 295.784 valores: 295.217 coincidem e 567 divergem.
Nos exemplos de conglomerados divergentes, o valor antigo era o dobro do arquivo
atual. A causa não foi confirmada com a API indisponível. Esses valores históricos
não foram substituídos. A auditoria de todos os dez caches confirma igualdade
exata dos valores e códigos anteriores. A normalização de nomes já existente no
app ajustou 620 rótulos em cada base individual e 120 na carteira por instrumentos.

```bash
.venv/bin/python scripts/ingest_ifdata_web.py 202606
```

O comando usa `CacheManager.extrair_periodos_com_salvamento(..., modo="incremental")`
e exige o histórico anterior. Depois da ingestão, executar os materializadores
existentes de derivados e telas críticas, validar cobertura e promover parquet e
metadata pareados para `data/bundled`. Para atualizar somente junho nas telas
críticas, calcular com contexto de 2025 e 1T2026 e anexar apenas junho ao histórico.
O BLOPRUDENCIAL recebeu abril, maio e junho; 4066 aparece no fechamento semestral.

## Reinício, release e validação

Os 16 caches atualizados/preservados neste pacote acompanham o código em
`data/bundled`, além do 4010 já publicado. A leitura reconhece a identidade da
publicação. Um runtime sem essa identidade ou com menos períodos não encobre o
bundle. Atualizações posteriores completas podem precedê-lo. Downloads do release
global legado não recebem automaticamente a identidade do bundle atual.
Os metadados de publicação têm SHA-256, e as funções de tela usam tokens dos
arquivos para invalidar resultados processados de DRE, COSIF e SPB.

A validação real copiou os bundles para um diretório vazio, bloqueou a rede e
configurou `TOMACONTA_RELEASE_TAG=v2.0-cache`: os 17 caches, incluindo os 12
conjuntos SPB e o 4010, carregaram os artefatos publicados. Os testes também cobrem
runtime antigo, extração incompleta e preservação dos arquivos versionados.

Validação de código: **733 testes aprovados**, 14 avisos de dependências já
existentes; pico de RSS de 892,8 MiB sob limite de 1 GiB. Dispatcher de menu sem
rótulos duplicados e `git diff --check` sem erros. Os quatro gates de Snapshot/Peers,
Rankings e DRE individual/consolidado estão alinhados em `202606`.

O 4010 permanece conforme `cosif_4010_202606.md`: 1.752 CNPJs, AR em 270 e VR em
107. CR permanece N/D, pois a subconta específica não está no extrato público.

A validação visual identificou desalinhamento de índices no cálculo de despesa de
captação após recortar trimestres. O índice agora é normalizado antes do merge;
um teste com índices descontínuos verifica a média YTD e a razão de junho.
O indicador voltou a ter dados em 1.010 instituições em junho.

Os downloads reais do release foram comparados por SHA-256: 50 assets e o
manifest, com recibo em `atualizacao_jun26_downloads.json`. O detalhe anual SCR
de 2026 também foi baixado: 235.736 linhas, 33.953 de junho, preservando julho.

Na validação pública da DRE prudencial, as rubricas finais ainda aplicavam o
layout anterior em 2026. A seleção de layout agora mantém, desde dez/2025, as
colunas de tributos `(r)`, IR/CSLL `(x)` e lucro líquido `(z)` publicadas nos
arquivos de março e junho/2026. A DRE individual usa o mesmo resolvedor por período, mantendo o perímetro
individual. A correção é de leitura; não altera os assets
financeiros nem seus hashes. Testes cobrem o zero e as colunas reais de junho.
Validação complementar da leitura DRE: 736 testes aprovados, 14 avisos existentes,
pico RSS 796,8 MiB; dispatcher e diff sem erros.

O manifest oficial também acompanha o código em `data/cache/manifest.json`,
caminho consumido pelo diagnóstico DRE existente. Assim, o diagnóstico compara
junho com o artefato publicado mesmo sob configuração global legada. O token
da tabela DRE inclui a revisão do layout para invalidar resultados calculados
antes da correção, mesmo quando o parquet permanece idêntico.

A abertura direta da DRE gerencial com runtime vazio selecionava o primeiro
parquet encontrado, que era Taxas de Juros (2.764.031 linhas). A seleção padrão
agora usa somente DRE, respeitando a precedência do bundle publicado sobre um
runtime legado. Sem parquet DRE, a tela aguarda seleção explícita. Testes
reproduzem o runtime vazio com Taxas presente e a convivência com DRE antiga.
