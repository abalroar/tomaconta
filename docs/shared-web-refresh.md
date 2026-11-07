# Atualização compartilhada do Toma Conta

O site lê uma geração imutável de dados e dos módulos contábeis originais. O usuário solicita uma atualização; o Worker registra a fila; um workflow do próprio repositório executa os coletores Python existentes, valida os resultados e publica um novo manifesto. A troca da geração ativa ocorre em uma operação condicional no D1. Falhas deixam a geração publicada disponível.

## Componentes e integração

- `web/server/shared.js`: API, identidade do executor, fila, reserva, armazenamento por hash, dependências e publicação.
- `web/server/shared-schema.js`: tabelas exclusivas do serviço financeiro, criadas de forma idempotente no primeiro acesso.
- `scripts/tomaconta_shared_runner.py`: executor e materialização usando os módulos originais.
- `.github/workflows/tomaconta-shared.yml`: execução manual e consulta periódica da fila.

Bindings obrigatórios: `TOMACONTA_DB` (D1) e `TOMACONTA_BUCKET` (R2), ambos dedicados ao Toma Conta. O código não usa `PHOTOS_DB`, `PHOTOS_BUCKET` ou a autenticação da galeria.

No Worker principal, encaminhar `/tomaconta/api/shared/…` para `handleShared(request, env)` **antes** da guarda geral de métodos HTTP. O padrão existente `assets.run_worker_first: ["/tomaconta/api/*"]` já abrange estas rotas. O import deve preservar `shared-schema.js` como dependência do bundle.

Criação e configuração pelo responsável pela publicação, após conferir a conta:

```sh
wrangler d1 create tomaconta-shared
wrangler r2 bucket create tomaconta-shared
```

Adicionar os bindings e o identificador retornado do D1 ao `wrangler.jsonc`. O executor usa OIDC; este contrato dispensa copiar o token pessoal do GitHub ou cadastrar um segredo estático de executor.

## Identidade do executor

Todas as rotas `/runner/…` exigem `Authorization: Bearer <JWT>` emitido pelo GitHub Actions. A audiência exata é `https://matheusprat.es/tomaconta/api/shared/runner`. O Worker verifica a assinatura RS256 com o JWKS fixo do emissor `https://token.actions.githubusercontent.com` e exige:

| Claim | Valor |
| --- | --- |
| `repository` | `abalroar/tomaconta` |
| `repository_id` | `1141557164` |
| `repository_owner_id` | `255978345` |
| `ref` | `refs/heads/main` |
| `workflow_ref` | `abalroar/tomaconta/.github/workflows/tomaconta-shared.yml@refs/heads/main` |
| `event_name` | `schedule` ou `workflow_dispatch` |
| `runner_environment` | `github-hosted` |

Também são verificados `exp`, `nbf`, `iat`, `sha`, `workflow_sha`, `run_id` e `run_attempt`. A reserva fica vinculada ao par execução/tentativa. A renovação do JWT durante a mesma execução preserva essa identidade. O workflow precisa de `id-token: write`; as demais permissões podem permanecer de leitura. Os claims e a emissão estão documentados na [referência OIDC do GitHub](https://docs.github.com/en/actions/reference/security/oidc).

## API pública

Prefixo de todas as rotas: `/tomaconta/api/shared`.

| Método e rota | Contrato |
| --- | --- |
| `GET /current` | `{revision,publishedAt,summary,builtIn,configured}`. Sem configuração retorna `revision:null,builtIn:true,configured:false`; antes da primeira publicação retorna `builtIn:true,configured:true`. |
| `GET /data/{revision}/{path}` | Arquivo publicado de `web/data/{path}`; versão imutável, ETag SHA-256 e cabeçalho `X-TomaConta-Revision`. Também aceita `HEAD`. |
| `GET /jobs` | Últimos 40 pedidos com estado, progresso, mensagem e resultado. |
| `GET /jobs/{id}` | Estado de um pedido. Não expõe a reserva nem a identidade do executor. |
| `POST /jobs` | Solicita plano permitido, com `Origin` do mesmo site e `Idempotency-Key` de 32 caracteres hexadecimais. |
| `GET /revisions` | Últimas 30 gerações publicadas, com resumo e relação de origem. |

Planos: `{kind,mode?,period?,start?,end?,uf?}`. `kind` aceita `financeiro`, `individual`, `mercado_credito_sgs`, `mercado_imobiliario`, `scr_data`, `spb_meios_pagamento`, `rede_agencias` ou `tudo`; `mode` aceita `incremental` (padrão) ou `overwrite`. `period` usa `YYYY-MM` nos planos financeiros; a visão individual exige mês de fim de trimestre. As demais fontes de séries aceitam `start` e `end` juntos, até 24 meses. `rede_agencias` atualiza o cadastro atual BCB/IBGE e rejeita competência, janela histórica e UF. `uf` aceita `br` e as 27 siglas apenas no plano imobiliário. O coletor imobiliário original conserva as 28 abrangências na geração.

A fila admite até quatro pedidos pendentes e uma execução ativa global. Há deduplicação por plano, uma atualização ativa por fonte, intervalo de 15 minutos após sucesso e de 60 segundos após falha. A API pública não aceita decisões de classificação contábil nem `rebuild`. A criação pública de pedidos fica indisponível até a importação inicial explícita.

## API do executor

| Método e rota | Entrada e saída principais |
| --- | --- |
| `GET /runner/pending` | `{pending:boolean}`; consulta leve antes de instalar dependências pesadas. |
| `POST /runner/seed` | `{kind:"bootstrap"}` → `{id}`. Exige `workflow_dispatch` e ausência de geração ativa. |
| `POST /runner/claim` | Retorna `{job,base}`; `job` contém `id`, `params`, `lease_id`, `lease_until`, `base_revision`, `result`; `base` contém o manifesto completo ou `null`. |
| `POST /runner/jobs/{id}/heartbeat` | `{lease,progress,message}`; `progress` entre 0 e 1. `/progress` é um alias. |
| `PUT /runner/blobs/{sha}?job={id}` | Bytes originais; exige `X-Lease-Id` e `Content-Length`. O R2 verifica o SHA-256 informado antes da confirmação no D1. |
| `GET /runner/blobs/{sha}` | Restaura bytes da geração anterior no diretório de trabalho do executor. |
| `POST /runner/jobs/{id}/prepare` | `{lease,parent,files,summary}` → `{revision}`. Valida arquivos e dependências; preserva a geração ativa. Repetir o mesmo candidato retorna a mesma revisão. |
| `POST /runner/jobs/{id}/publish` | `{lease,revision}` → `{revision,published:true}`; compare-and-swap contra a geração de origem e a reserva vigente. Repetir após sucesso é idempotente. |
| `POST /runner/jobs/{id}/fail` | `{lease,error,needsReview?,result?}`. Conserva a base publicada. |
| `POST /runner/restore` | `{revision,expectedCurrent}`; exige execução manual, geração já publicada e compare-and-swap. |

A reserva dura 180 segundos. O executor deve enviar heartbeat a cada 30 segundos, inclusive durante coleta, validação e envio de arquivos. Uma execução interrompida pode ser retomada em até três tentativas com nova reserva; o manifesto de origem permanece o mesmo. Depois disso, o pedido recebe estado de falha.

O agendamento consulta a fila a cada cinco minutos. O GitHub pode atrasar execuções agendadas; o despacho manual oferece recuperação. Os limites estão na [documentação de eventos agendados do GitHub](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows).

## Geração e arquivos

Cada entrada de `files` contém `{path,sha256,size,encoding:"identity"}`. Limites: 20 mil arquivos por geração, 64 MB por arquivo e 8 MB no pedido de preparação. Os caminhos usam:

- `web/data/…`: JSON da interface, snapshots e entradas contábeis comprimidos, engine Python, geometria e exportáveis;
- `cache/bundled/…`: fontes originais que o próximo incremental deve restaurar;
- `cache/runtime/…`: checkpoints e fontes brutas necessários à continuidade.

São aceitos `.json`, `.json.gz`, `.geojson`, `.parquet`, `.csv`, `.zip`, `.xlsx`, `.pptx`, `.py` e `.whl`. O único `.bin` permitido é `cache/runtime/financial_analysis_sources/{prefixo}/{sha256}.bin`, com nome e hash iguais aos bytes. Um recibo da execução registra os nomes originais e a origem desses arquivos.

Arquivos `.json.gz` mantêm seus bytes comprimidos e **não** recebem `Content-Encoding: gzip` na resposta. O cliente verifica o hash e realiza a descompressão. A engine de Balanço/DRE preserva os módulos Python originais e os pacotes remotos fixados em seu manifesto; uma roda local só é exigida quando declarada nesse manifesto.

`summary` deve incluir:

```json
{
  "validation": {"complete": true, "failures": 0},
  "generation": {
    "sourceCommit": "SHA de 40 caracteres igual ao claim sha do executor",
    "modelVersion": "statement-v6",
    "sourceFiles": [{"path": "cache/bundled/fonte/dados.parquet", "sha256": "…", "size": 123}]
  }
}
```

A preparação exige manifestos de instituições, fontes Parquet, históricos, entradas e snapshots contábeis, engine, crosswalk quando declarado, gráficos SFN e pagamentos, os 24 gráficos imobiliários e as 28 abrangências, `bank-network.json` e sua geometria `bank-network-ufs.geojson`. Os hashes e tamanhos declarados pelas dependências devem corresponder aos arquivos do candidato. BNDU fica excluído. Risco da Operação conserva a última competência publicada, conforme o catálogo BCB.

O executor restaura uma única geração em diretório privado, aplica os coletores existentes e materializa o JSON a partir das fontes resultantes dessa mesma geração. O exportador não pode continuar lendo um `data/bundled` antigo depois de atualizar apenas o cache de execução. A publicação inclui as fontes utilizadas, o commit, a versão do modelo, cobertura e recibo da atualização.

O leitor público fixa uma revisão antes de buscar catálogos, históricos, geometria, snapshots e módulos da engine. O fallback estático é utilizado antes da ativação compartilhada ou sem bindings configurados. Uma revisão compartilhada ativada que esteja inconsistente deve produzir erro visível e preservar o contexto; misturar arquivos estáticos de outra geração prejudicaria a reconciliação.

## Validação

```sh
node --test web/tests/shared.test.mjs
python -m unittest discover -s tests -p 'test_tomaconta_shared_runner.py'
```

Os testes do Worker usam SQLite real em memória, R2 com verificação de checksum e tokens RS256 assinados para a fixture. Cobrem escopo OIDC, isolamento das fotos, fila, deduplicação, reservas expiradas, hashes, dependências, preservação de bytes gzip, preparação e publicação condicionais.

O baseline real foi conferido antes da importação: 7.565 arquivos, 270.005.759 bytes, 30 Parquets e maior arquivo de 19.273.120 bytes. `validateFiles` e `validateDependencies` aceitaram o inventário completo; somente o README documental da malha foi omitido. A conferência local leu dez catálogos, 7.684.249 bytes, em cerca de 43 ms de Node. Isso verifica o contrato dos artefatos; latência e limites do ambiente Worker ainda precisam ser medidos na implantação.

Na publicação, conferir pela interface: importação inicial; pedido imobiliário e seu progresso; data/abrangência e fonte por gráfico; atualização compartilhada observável em nova sessão; download de PPTX e Balanço/DRE do contexto selecionado; falha controlada preservando revisão anterior; e restauração condicional. Registrar a revisão ativa junto dos resultados.
