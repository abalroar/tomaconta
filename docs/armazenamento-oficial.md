# Armazenamento oficial portátil

O autosserviço prepara uma revisão completa em uma área privada. Após validar arquivos, cobertura e cálculos existentes, o worker publica um único ponteiro. As telas leem a revisão escolhida no início de cada render. Uma atualização concluída aparece no próximo render; os arquivos usados pelo render atual permanecem disponíveis.

`TOMACONTA_OFFICIAL_STORE_DIR` habilita esse contrato. A variável deve apontar para um armazenamento já inicializado com uma revisão completa e validada. Sem a variável, as regras atuais de runtime, bundle e GitHub permanecem em uso. Com a variável, uma revisão ausente ou inválida gera erro, sem baixar dados ou substituir silenciosamente a fonte.

## Contrato e arquivos

`ProtocolDataStore` define `stage`, `get_revision`, `activate`, `current`, `find_publication`, `rollback`, `export` e `materialize_workspace`. Um adaptador futuro para armazenamento institucional deve fornecer as mesmas garantias de versões imutáveis e troca condicional do ponteiro. Os assets mutáveis de um release GitHub não oferecem essas garantias como um conjunto; eles continuam sendo uma origem compatível para importar dados antes da validação e da publicação.

`LocalRevisionStore` usa esta estrutura:

```text
official/
  active.json
  last_valid.json
  .activation.lock
  activations/<sequência>-<revisão>.json
  revisions/<revisão>/
    manifest.json
    files/
      data/cache/<cache>/<arquivo>
      data/cache/institution_registry/<competência>.json
      conglomerados.csv
      <arquivos locais de catálogo declarados>
```

O manifesto contém ID, revisão anterior, data, metadata da execução e tamanho/SHA-256 de cada arquivo. Os dados principais, dimensões, históricos anuais, datasets SPB, manifestos nativos e recursos de cadastro precisam entrar juntos no mapeamento de arquivos. A validação de completude e qualidade do domínio ocorre no preflight compartilhado do worker; o store valida identidade e integridade dos bytes.

`stage` copia arquivos para uma pasta temporária exclusiva, confere os hashes e sincroniza arquivos e diretórios antes de promover a pasta para um ID imutável. Nenhuma revisão existente é sobrescrita. `get_revision` distingue um ID ausente (`RevisionNotFound`) de uma revisão corrompida (`RevisionCorrupt`), permitindo retomar um candidato preparado antes de uma interrupção.

`activate(expected_parent=...)` exige que a revisão ativa ainda seja aquela usada para preparar o candidato. Uma segunda atualização concorrente recebe `RevisionConflict`. O ponteiro anterior é preservado, e a troca usa substituição atômica do JSON. `rollback` realiza outra troca condicional para uma revisão existente e íntegra. `find_publication(job_id)` procura somente ativações comprovadas, permitindo conciliar uma interrupção após publicação e antes da conclusão do comprovante do job.

Se a revisão ativa ou o ponteiro estiverem ilegíveis, `current` tenta somente a referência íntegra comprovada em `last_valid`. Se ela também falhar, a leitura é interrompida. Candidatos preparados sem ativação não tornam o armazenamento inicializado. Não há remoção automática de revisões, pois renders e jobs podem continuar usando IDs anteriores.

## Leitura e atualização

`begin_official_read()` é chamado no início do rerun e mantém um snapshot no `ContextVar` do render. `CacheManager()` e os helpers de compatibilidade usam esse snapshot. Os caminhos de leitura incluem os extras de SCR, taxas e SPB, além do catálogo e dos cadastros. Os leitores verificam o hash de um arquivo se sua assinatura física mudou; `current` reutiliza a validação completa quando as assinaturas dos arquivos imutáveis permanecem iguais.

`revision_cache_data` conserva as opções e a assinatura pública de `st.cache_data` e inclui o ID da revisão nas chaves do modo oficial. Renders concorrentes de revisões distintas têm entradas separadas, inclusive quando uma sessão anterior termina de preencher seu cache depois da publicação nova. Os parâmetros iniciados em `_` continuam excluídos do hash. O cache em `session_state` precisa ser renovado ao trocar a revisão: os dados principal/capital, seus campos de fonte/erro, o indicador de capital mesclado e os artefatos derivados da sessão. O leitor legado de BLOPRUDENCIAL passa a recortar o parquet oficial e não baixa ZIP nessa modalidade.

As operações de leitura não adquirem a trava de atualização e não criam arquivos na revisão. Extração, download, salvamento ou limpeza de um cache oficial recebem `OfficialReadOnlyError`. A validade temporal do cache legado não provoca download em uma revisão oficial.

`materialize_workspace(snapshot, novo_destino)` fornece uma cópia independente para o worker. `CacheManager(base_dir=workspace)` continua gravável e usa as rotinas atuais. A publicação não altera essa cópia depois de validada. `export` cria um pacote independente com `manifest.json` e `files/`, adequado a transferência e verificação. Ambos exigem um destino novo e verificam os bytes copiados.

Um `CacheManager` explícito apontando para o projeto configurado ou para a própria raiz de revisão permanece somente leitura. A importação inicial de dados legados no projeto exige um contexto gravável explícito; a execução normal usa a cópia privada do worker.

## Limite desta implementação

O adaptador local usa `fcntl`, `fsync` e renomeação atômica em um único volume durável de filesystem local compatível com POSIX. O processo da aplicação e o worker precisam enxergar esse mesmo volume. Estas garantias não foram projetadas para NFS, Windows ou múltiplos hosts independentes. A AWS e a identidade institucional poderão adotar adaptadores específicos posteriormente. Os dados oficiais permanecem fora do repositório de código; os cálculos financeiros e as telas de análise continuam usando seus formatos existentes.
