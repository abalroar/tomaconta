# Atualizar Base — implementação do pacote inicial

Implementação local na branch `codex/atualizar-base-seguro`, baseada no commit
`5720d278127e099870b04fa9b73aa5a6b4012ea0`. O checkout original foi preservado.

## Comportamento entregue

- Atualizações IFData preservam o histórico fora da janela selecionada. Falhas
  de gravação e checkpoint chegam ao resultado e impedem publicação.
- Execuções têm plano persistido e comprovante. Retomar usa os parâmetros
  originais e processa somente períodos pendentes. O controle por fonte mantém
  pendências de lotes anteriores visíveis mesmo após outra execução.
- Uma trava comum protege as mutações da UI, do manager e dos dois CLIs.
- A preparação de publicação verifica o conjunto prometido, suas dependências,
  metadados, competências e hashes. A existência de um asset remoto tem status
  distinto da correspondência com a versão local.
- A tela mantém o comprovante e o acesso ao backup após reruns. A publicação
  automática fica desmarcada por padrão; validação de credencial e diagnóstico
  completo dependem de ação explícita.
- Os formulários respeitam as capacidades das 15 fontes. Intervalos trimestrais
  invertidos retornam uma janela vazia e mensagem de erro, eliminando o laço
  infinito encontrado durante a validação.

## Validação em 09/09/2026

- Testes focados: **156 passaram** em 4,56 segundos; pico RSS observado de 307 MiB.
- Suíte geral: **855 passaram** em 17,56 segundos, com 14 avisos de depreciação
  de Pyparsing/Matplotlib. Executada em cópia descartável com conexões de rede
  bloqueadas; pico RSS observado de 758 MiB.
- As duas execuções finais rodaram sequencialmente, monitoradas a cada 0,2 s,
  com interrupção acima de 768 MiB ou 180 segundos.
- A cobertura da interface usa Streamlit AppTest sobre a rota real, com
  dependências de leitura simuladas, incluindo os 15 formulários e a retomada.
- `git diff --check` e o check de unicidade do dispatcher passaram.

## Limites e estado de entrega

A validação descrita neste relatório foi concluída antes do commit e da
integração à branch principal. Os testes não fizeram extração com fontes
reais, publicação de assets nem validação da aplicação pública. O estado
da integração deve ser consultado no histórico Git e no PR correspondente.

A gravação conjunta de parquet e metadata e a substituição remota dos assets
continuam sem transação atômica. A publicação remota continua sequencial e
pode exigir recuperação após falha de rede. Essas alterações estruturais
permanecem fora do pacote inicial. O snapshot do backend cobre `data/cache`.

O procedimento operacional está em [runbook_cache_release.md](runbook_cache_release.md).
