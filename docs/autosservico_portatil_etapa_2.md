# Atualização portátil das bases — etapa 2

A aplicação passa a ter uma opção de armazenamento oficial versionado e um serviço de atualização independente do Streamlit. O modo atual continua sendo o padrão, com GitHub Releases e os controles existentes. Nenhuma variável de configuração nova é necessária para manter o site atual.

No modo portátil, o analista seleciona a base, o período e o modo na tela Atualizar Base. O servidor registra o pedido em uma fila persistente. Outro processo executa os extratores existentes, salva o progresso, recalcula os consumidores e valida o pacote. A promoção troca um único ponteiro para a revisão completa. Fechar o navegador não cancela o trabalho. Uma falha conserva a revisão anterior e permite retomar o job.

## Componentes e responsabilidades

| Componente | Responsabilidade |
| --- | --- |
| `official_store.py` | Revisões imutáveis, hashes, ponteiro ativo, versão anterior, restauração e exportação |
| `durable_jobs.py` | Fila SQLite, intenção imutável, idempotência por identidade, reserva com prazo e confirmação do executor |
| `update_backend.py` | Autorização, workspace privado por job, extratores existentes, dependências e promoção |
| `update_api.py` | API HTTP e cliente; identidade verificada no servidor |
| `update_access.py` | Contrato para o login institucional e adaptador inicial de tokens |
| `update_app_bridge.py` | Envio e acompanhamento pela aplicação; nenhum worker é iniciado pelo navegador |
| `tools/update_service_cli.py` | Entrada para executar API, worker, importar a base inicial e exportar backup |

Os arquivos de cada revisão usam os mesmos formatos parquet/JSON e os mesmos nomes de colunas. As fórmulas e os extratores financeiros permanecem nos módulos atuais. Uma revisão inclui todas as bases presentes, dimensões, arquivos auxiliares dos adaptadores e cadastros de instituição. A fila, os arquivos temporários, os comprovantes de execução e as credenciais ficam no volume do serviço.

## Instalação inicial em um servidor Linux

Esta implementação funciona em um único host Linux/macOS, com disco persistente e sem serviços exclusivos da AWS. API, worker e aplicação devem usar o mesmo armazenamento oficial. A aplicação pode receber esse volume somente para leitura. A fila e os workspaces precisam ser graváveis apenas pelo serviço.

1. Instalar as dependências atuais do projeto. Não há biblioteca adicional nesta etapa.
2. Reservar dois diretórios persistentes: `/srv/tomaconta/service` para a fila/workspaces e `/srv/tomaconta/official` para as revisões. Mantê-los fora do checkout e do armazenamento efêmero do Streamlit.
3. Preparar uma cópia completa e validada dos caches atuais. O importador escolhe a geração efetiva de cada cache pelo contrato existente; não consulta a API nem baixa dependências. Pacotes nativos incompletos e metadata divergente impedem a importação.
4. Importar uma vez:

```sh
python tools/update_service_cli.py \
  --data-dir /srv/tomaconta/service \
  --store-dir /srv/tomaconta/official \
  import-legacy --source-dir /srv/tomaconta/seed
```

5. Configurar `TOMACONTA_UPDATE_IDENTITIES_JSON` no gerenciador de segredos do serviço. O formato é um objeto cujas chaves são tokens privados, e cada valor contém `subject` e `permissions`. As permissões possíveis são `read`, `update`, `publish` e `restore`. Não existe credencial padrão. Use uma identidade própria para cada pessoa ou integração. O servidor nunca confia em usuário, papel ou permissões enviados no corpo do pedido.
6. Iniciar dois processos supervisionados, com reinício automático:

```sh
python tools/update_service_cli.py \
  --data-dir /srv/tomaconta/service \
  --store-dir /srv/tomaconta/official \
  serve --host 127.0.0.1 --port 8787
```

```sh
python tools/update_service_cli.py \
  --data-dir /srv/tomaconta/service \
  --store-dir /srv/tomaconta/official \
  worker
```

7. Disponibilizar a API por HTTPS no proxy institucional. HTTP no cliente é aceito somente no endereço de loopback, para desenvolvimento. A API não recebe arquivos de dados nem credenciais do GitHub. Tokens ficam no cabeçalho de autenticação e não são gravados nos jobs.
8. Configurar a aplicação:

| Variável | Valor |
| --- | --- |
| `TOMACONTA_OFFICIAL_STORE_DIR` | `/srv/tomaconta/official` ou caminho do mesmo volume montado na aplicação |
| `TOMACONTA_UPDATE_API_URL` | URL HTTPS da API |
| `TOMACONTA_UPDATE_API_TOKEN` | Token da identidade autorizada para a integração |

A tela mantém a seleção de bases e períodos. Os controles de execução passam a registrar e acompanhar jobs, com publicação da revisão validada. Se a API estiver indisponível ou a configuração estiver incompleta, o aplicativo informa o erro; a atualização não é transferida silenciosamente para o fluxo antigo. Um armazenamento oficial configurado sem versão válida também bloqueia a leitura. Cada render usa uma revisão global fixa; uma nova visita ou atualização da página adota a revisão nova.

## Identidade institucional

`IdentityVerifier.authenticate(headers)` é o ponto de integração com o login do banco. O adaptador de tokens permite instalar e testar o serviço antes de escolher o provedor corporativo. A aplicação Streamlit configurada com um token único registra as operações sob essa identidade de integração; a atribuição individual exige que o login institucional forneça a identidade verificada de cada analista. Essa ligação com o provedor corporativo fica para a etapa de implantação. O serviço já separa as permissões de consultar, atualizar, publicar e restaurar.

## Recuperação e operação

- A chave de idempotência evita duplicar um pedido quando a conexão cai após o servidor aceitá-lo.
- O worker mantém a reserva viva durante consultas longas. Os escritores usam a mesma trava de processo antes de reservar um job e até confirmá-lo. Um segundo worker no mesmo host espera essa trava. Após uma queda, aguarda a reserva anterior expirar e retoma esse job antes de iniciar pedidos mais novos.
- Depois de uma queda, a fila conserva o job e o comprovante conserva as competências confirmadas. O mesmo job usa o mesmo workspace e o mesmo plano. Uma falha após salvar os dados retoma a validação; uma falha após preparar a revisão reaproveita o candidato; uma queda após a promoção reconcilia a publicação pelo histórico.
- O modo incremental e o modo overwrite conservam competências fora da janela, conforme os serviços existentes. Uma reconstrução explícita segue o contrato de rebuild. Os chunks do histórico de taxas mantêm o checkpoint nativo até a conclusão; o worker avança os lotes internos.
- Uma atualização parcial, arquivo divergente, dimensão ausente ou dependência inválida impede promover o candidato. A versão oficial anterior continua disponível.
- A ativação exige a revisão usada como origem do job. Se outro operador publicou ou restaurou uma versão, o candidato antigo não substitui essa mudança. Inicie um pedido novo a partir da revisão atual.
- A publicação manual exige um job concluído e autorizado. A restauração exige a permissão `restore` e a identificação da revisão ativa esperada.
- `GET /jobs` mostra um resumo dos jobs da identidade autenticada. `GET /jobs/<id>` traz o comprovante completo de progresso, sem os dados financeiros nem credenciais.

Para exportar uma revisão completa e verificar os hashes durante a cópia:

```sh
python tools/update_service_cli.py \
  --data-dir /srv/tomaconta/service \
  --store-dir /srv/tomaconta/official \
  export --destination /backup/tomaconta/revisao-2026-10-10
```

O destino deve ser novo. O pacote contém `manifest.json` e `files/`; a cópia precisa entrar na política de backup da instituição. A restauração operacional de uma revisão conservada no store usa `POST /revisions/restore`, com `revision_id` e `expected_parent`. Esta etapa conserva as revisões anteriores; ainda não aplica uma política de retenção ou exclusão automática. Workspaces e revisões devem ter espaço monitorado pelo operador.

## Migração futura para AWS

O código desta etapa não cria recursos na AWS. A equipe pode instalar inicialmente os mesmos processos em um servidor Linux com volume persistente. Para distribuir a execução por vários hosts, substituir a fila/trava local por um serviço central e implementar `ProtocolDataStore` com armazenamento de objetos e promoção condicional de versão. S3 exige esse adaptador; um bucket não deve ser tratado como um diretório POSIX. Os consumidores continuam recebendo parquet/JSON e uma revisão fixa.

O login corporativo, o provedor de armazenamento, a fila central, a supervisão dos processos e a política de backup serão escolhidos na implantação institucional. A estrutura já separa esses pontos dos extratores e dos cálculos. O site público atual permanece no modo legado até existir uma instalação configurada do serviço.

O aviso herdado da DRE individual está documentado em `autosservico_portatil_dre_diagnostico.md`. Esta etapa não converte ausência em zero nem altera a regra financeira.
