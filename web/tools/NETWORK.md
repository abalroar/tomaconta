# Dados do mapa bancário

`export_network.py` publica `web/public/data/bank-network.json` e `bank-network-ufs.geojson`. Não altera os indicadores IF.data, o engine contábil ou a interface.

```sh
# Na raiz, em ambiente Python próprio para coleta:
python -m pip install -r web/tools/requirements-network.txt
python web/tools/export_network.py
# Reconsultar todas as fontes, preservando o resultado anterior se a coleta falhar:
python web/tools/export_network.py --refresh
python -m unittest discover -s web/tests -p test_network_pipeline.py
# Testes do pacote versionado, sem rede ou Python:
cd web
node --test tests/network-data.test.mjs
```

As páginas BCB são ordenadas por `CnpjBase,CnpjSequencial,CnpjDv`, com `$top=1000` e `$skip` até a primeira página incompleta. Duplicidade de CNPJ completo, posições misturadas, divergência de UF ou totais não reconciliados interrompem a geração. Fontes e hashes ficam no cache `data/cache/bank_network`; metadados e hashes das páginas integram o dataset publicado. `--agencies` e `--agencies-evidence` permitem reutilizar um levantamento completo cujo SHA-256 e totais sejam conferidos.

O cadastro usado nos vínculos IF.data acompanha `institutions.json.latestPeriod` do candidato. Use `--catalog-dir CAMINHO` quando `institutions.json` e `statements/crosswalk.json` estiverem no staging de uma revisão; o padrão é `ROOT/web/public/data`. `--period YYYYMM` (ou YYYY-MM) pode explicitar essa competência e deve concordar com esse catálogo. O script não escolhe competência pelo relógio nem fixa junho/2026. Se o cadastro oficial daquela competência não estiver disponível, a geração falha preservando a publicação anterior. Os hashes do catálogo e do crosswalk usados são registrados com as fontes do vínculo.

O recorte inclui exatamente Banco Múltiplo, Banco Comercial e Caixa Econômica Federal. Na posição **05/11/2026**, são **12.818 registros, 139 CNPJ-base e 2.885 municípios**. A fonte completa contém 13.574 registros de 639 instituições. Não se somam postos, caixas eletrônicos, correspondentes ou cobertura digital. `DataInicio` não é interpretada como histórico de abertura/fechamento.

O BCB fornece código municipal IBGE de sete dígitos neste snapshot; todas as 12.818 observações do recorte têm correspondência exata. O adaptador admite código de seis dígitos apenas quando seu prefixo possui uma única correspondência no universo IBGE. Não há associação por nome. As localidades e malhas simplificadas oficiais vêm das APIs IBGE, v1 e v4. O ponto territorial é `representative_point` do polígono municipal, validado dentro dele depois do arredondamento a seis casas; ele não localiza a agência nem a sede municipal.

O arquivo contém os 5.571 municípios oficiais, incluindo 2.686 com `total=0` no recorte. Uma geometria simplificada inválida, **4121356 — Rancho Alegre D'Oeste/PR**, fica com coordenadas `null`; o município possui zero registros no recorte. Nenhuma agência deixa de ser representada por falta de ponto. A geometria estadual preserva os 27 polígonos oficiais; apenas ordenação e identificação da UF são acrescentadas.

A unidade de identidade do mapa é o **CNPJ-base individual**. Todos os 139 CNPJ-base são consultados no cadastro individual oficial IF.data **jun/26**: `c33` identifica a instituição e `c15`, descrito nos metadados como Código do Conglomerado Prudencial, identifica o grupo. O código é ligado ao catálogo existente por seu crosswalk exato e único. São 100 vínculos e 39 resultados `null`, com motivo em `analysisLinkStatus`; não se escolhe entre aliases. Isso mantém separados o cadastro de agências de nov/26 e os dados prudenciais de jun/26; as agências não são consolidadas como grupo.

Agências: Banco Central do Brasil, [ODbL](https://dadosabertos.bcb.gov.br/dataset/agencias). Cartografia: IBGE, [CC BY 4.0](https://www.ibge.gov.br/biblioteca/visualizacao/livros/liv102152.pdf), com [documentação das malhas simplificadas](https://servicodados.ibge.gov.br/api/docs/malhas?versao=4). Agregação e pontos representativos: Toma Conta. A atribuição acompanha os metadados para uso na interface e nos derivados.

Os testes públicos conferem reconciliações municipal/banco/UF, recorte, zeros e coordenadas ausentes, identidade de todos os vínculos e SHA-256 da geometria. Os testes Python não requerem Parquet, QA local nem rede; cobrem paginação, código territorial, ambiguidades e preservação da versão anterior diante de falhas. A geração verifica a posição interna dos pontos usando a malha municipal original da consulta. Geografia ausente para qualquer registro positivo interrompe a publicação. Essas checagens não validam endereços individuais de agências.
