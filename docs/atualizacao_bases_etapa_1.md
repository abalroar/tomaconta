# Atualização das bases — primeira etapa

A atualização conserva o histórico fora da janela escolhida, registra o que foi salvo e permite retomar os períodos pendentes. Os controles das telas e as fórmulas financeiras foram preservados. A migração para AWS fica para uma etapa posterior.

## Para quem usa a ferramenta

- Use os mesmos controles de período e de extração que já existem na tela **Atualizar Base**.
- Uma atualização incremental ou em `overwrite` substitui os períodos consultados e conserva o restante do histórico. A reconstrução integral exige `rebuild`, disponível nos comandos administrativos.
- Nas bases trimestrais, **retomar extração** continua a execução com os períodos e o modo originais. Alterar os campos da tela durante a retomada não altera esse plano.
- **Reiniciar extração** encerra o plano pendente e permite criar outro. O comprovante anterior permanece guardado.
- Uma execução parcial conserva os dados confirmados e registra os períodos que faltam. A publicação fica bloqueada até resolver as pendências.
- Apenas uma atualização pode gravar neste ambiente de cada vez. Recarregar a página ou limpar um registro de status não libera uma atualização ainda em execução.
- Os adapters históricos continuam usando seus próprios arquivos de staging e controles de janelas. Seus comprovantes registram a consulta e a conclusão; o botão genérico de retomada permanece reservado às bases trimestrais.

O background continua usando uma thread do processo atual. Após uma queda do servidor, a execução precisa ser retomada. Os comprovantes sobrevivem enquanto o diretório de dados for preservado.

## Organização do código e dos arquivos

| Componente | Responsabilidade |
| --- | --- |
| `utils/ifdata_cache/update_state.py` | Trava compartilhada, plano imutável e gravação dos comprovantes |
| `utils/ifdata_cache/update_service.py` | Execução dos lotes, retomada e confirmação dos adapters |
| `utils/ifdata_cache/manager.py` | Extração por competência e merge do histórico |
| `utils/ifdata_cache/base.py` | Validação, gravação recuperável de dados e metadata |
| `utils/ifdata_cache/release_ops.py` | Dependências, validação do pacote e publicação |
| `data/cache/update_runs/<run_id>/run.json` | Histórico de cada execução, sem credenciais |
| `data/cache/update_results/<cache>.json` | Último resultado agregado de cada base |
| `data/cache/.update.lock` | Exclusão de operações concorrentes no mesmo diretório |

As pastas e os formatos existentes das bases permanecem compatíveis. A organização comum concentra as regras de execução e publicação, sem juntar fontes com períodos ou perímetros diferentes numa tabela financeira única.

## Proteções de gravação

O candidato é gravado num diretório exclusivo e validado antes da promoção. Dados, metadata e marcador de integridade possuem identidade e checksum. Um diário de recuperação guarda a versão anterior durante a substituição; após uma interrupção, a próxima leitura ou gravação recupera essa versão.

Os parquets grandes podem ser promovidos em batches, sem carregar todo o histórico num DataFrame adicional. Os adapters registram os auxiliares obrigatórios no mesmo contrato de persistência. Arquivos brutos de staging continuam separados da base consolidada.

Um histórico existente ilegível interrompe a atualização. Uma competência extraída com erro, vazia ou diferente da solicitada não avança o checkpoint. Falhas de disco, de confirmação ou de callback impedem que a execução seja marcada como concluída.

Leitores de bundles publicados continuam protegidos contra runtime antigo. Uma geração local atualizada e compatível com a publicação vigente passa a ser elegível para os leitores existentes.

O autosserviço materializa os derivados no diretório de dados do ambiente. A cópia de um derivado para `data/bundled`, usada na preparação offline do projeto, permanece uma operação administrativa explícita.

No primeiro uso, as dependências podem utilizar as cópias válidas que acompanham o projeto, sem baixar novamente essas bases do GitHub. A base escolhida para atualização precisa estar efetivamente salva no runtime. O progresso informa quando os dados já foram salvos e o recálculo ou a publicação continuam em andamento.

## Publicação no GitHub

Antes do envio, o fluxo verifica as bases selecionadas, suas fontes e seus derivados obrigatórios, a cobertura de períodos, a qualidade e os arquivos auxiliares. Os hashes dos dados e da metadata vinculam o pacote aos arquivos validados. O manifesto remoto é lido e mesclado para conservar as entradas de outras bases.

Uma fonte de apoio com dados locais diferentes dos já publicados exige atualização e publicação explícita dessa fonte. O fluxo informa qual base divergiu e bloqueia o envio, evitando substituir uma retificação remota por uma cópia local antiga. Metadata regenerada pode ser enviada com os consumidores obrigatórios quando os bytes dos dados continuam iguais.

O envio usa os bytes preparados, confirma os arquivos remotos e envia o manifesto por último. Se um arquivo mudar durante a operação ou uma fonte estiver incompleta, a publicação falha com diagnóstico. A confirmação do upload comprova os arquivos no GitHub; o processo já aberto da aplicação ainda pode precisar de recarga.

O GitHub continua recebendo arquivos sequencialmente. Uma falha durante o envio pode deixar parte dos assets substituída; o diagnóstico informa os arquivos enviados e permite repetir o pacote completo. A publicação de versões imutáveis com ativação atômica fica para a próxima etapa.

O token GitHub e os Secrets atuais continuam necessários para publicar. A operação sem acesso ao repositório, o login institucional e os serviços de armazenamento/execução externos ficam para a etapa de internalização.

## Operação administrativa

Os dois CLIs usam a mesma trava e o mesmo serviço de materialização/publicação. Argumentos inválidos são recusados antes de gravar ou extrair dados.

```bash
python tools/update_caches_cli.py --tipo principal --periodos 202603,202606 --modo incremental
python tools/refresh_cache_backend.py --ano-inicial 2026 --mes-inicial 03 --ano-final 2026 --mes-final 06 --modo overwrite --dry-run
```

`rebuild` deve ser reservado à reconstrução deliberada da base. O snapshot de restauração mantém a trava e os comprovantes históricos; a publicação sempre revalida os arquivos presentes após a restauração.

## Validação da entrega

As verificações incluem falhas de gravação e interrupção, recuperação, concorrência entre threads/processos, histórico vindo de runtime ou bundle, períodos inválidos, retomada por plano, respostas truncadas e publicações incompletas. As APIs externas são bloqueadas durante os testes.

A comparação estrutural com `8ed36f5435e203d267acdefb9e69cb52bc6f70db` confirmou os mesmos 51 controles da tela Atualizar Base e código idêntico no restante de `app1.py`. Os resultados finais da suíte e da revisão ficam registrados em `docs/atualizacao_bases_etapa_1_validacao.md`.
