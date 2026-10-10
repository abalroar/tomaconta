# Validação da primeira etapa de atualização das bases

Entrega local de 10/10/2026, na branch `codex/atualizacao-bases-confiavel`, a partir de `8ed36f5435e203d267acdefb9e69cb52bc6f70db`.

## Resultado

Os **1.418 casos coletados** estão cobertos por execuções aprovadas de todos os arquivos de testes, realizadas sequencialmente em grupos. Há 92 arquivos com casos coletados; o comando também incluiu `utils/ifdata_cache/test_cache.py`. Os grupos dos módulos alterados foram repetidos após os ajustes finais. As contagens dessas repetições se sobrepõem à suíte geral.

| Execução | Casos aprovados | Pico aproximado de RSS, MiB |
| --- | ---: | ---: |
| Grupo 1 | 137 | 350,2 |
| Grupo 2A | 111 | 753,7 |
| Grupo 2B | 72 | 257,6 |
| Grupo 3 | 74 | 403,5 |
| Grupo 4 | 171 | 403,5 |
| Grupo 5 | 185 | 526,0 |
| Grupo 6 | 257 | 397,9 |
| Grupo 7 | 198 | 431,7 |
| Grupo 8 | 147 | 475,0 |
| Deck de crédito BC, isolado | 38 | 297,0 |
| Ajustes finais de persistência, retomada e CLIs | 280 | 430,4 |
| Ajustes finais de publicação, individual e SPB | 180 | 317,4 |

O limite aplicado aos processos de testes foi 768 MiB. Os avisos remanescentes são de depreciação do `pyparsing` usado pelo `matplotlib`. As conexões externas foram bloqueadas por um plugin temporário de teste; algumas importações tentaram acesso remoto e receberam a falha controlada. Nenhuma extração do Banco Central ou upload real foi executado.

O registro estruturado com a lista de arquivos de cada grupo está em [atualizacao_bases_etapa_1_validacao.json](atualizacao_bases_etapa_1_validacao.json).

## Contratos verificados

- Histórico preservado fora da janela, tanto em runtime quanto vindo de bundle; extrações vazias, divergentes ou truncadas recusadas.
- Atualização trimestral real em lotes: falha num período, retomada com o plano original, preservação do histórico e uma única publicação ao concluir.
- Falhas de disco e de confirmação após o último checkpoint: execução permanece recuperável e exige nova confirmação.
- Plano por base e opções imutáveis, ausência de credenciais nos comprovantes e exclusão entre threads e processos.
- Promoção de dados, metadata e auxiliares com checksum, rollback e recuperação após interrupção.
- Release individual validado com os bytes originais; bundle protegido antigo deixa de prevalecer sobre uma revisão nova verificada e com cobertura completa.
- SPB em início sem runtime: atualização de um subset conserva e promove os datasets bundled declarados; falha parcial mantém a versão anterior.
- Publicação exige fontes, consumidores, períodos, qualidade, dimensões, arquivos anuais e datasets declarados. Fonte de apoio divergente do remoto bloqueia substituição implícita.
- Manifesto conserva as entradas alheias ao pacote. Falha HTTP, JSON inválido, hash divergente ou candidato alterado bloqueiam o envio ou sua confirmação.
- CLIs recusam argumentos inválidos antes de alterar arquivos e registram o modo efetivamente solicitado.

## Preservação das telas e dos cálculos

A comparação de AST com o commit de origem confirmou os mesmos **51 controles** da tela Atualizar Base, com rótulos e chaves preservados. Fora dos imports, helpers administrativos e do fluxo dessa tela, `app1.py` permaneceu estruturalmente idêntico.

Nos módulos `principal`, `derived_metrics` e `critical_screens`, as diferenças de funções se limitam aos caminhos de leitura, bootstrap e diagnóstico de disponibilidade. Builders, fórmulas, normalizações financeiras e filtros permaneceram idênticos. Os testes existentes de indicadores, rankings, pares, snapshots, DRE e exportações passaram.

`git diff --check` passou. O checkout principal e seus arquivos locais preexistentes foram preservados; a implementação está num worktree separado.

## Limites desta validação

A entrega foi validada localmente com fontes e respostas controladas. A branch ainda precisa passar pelo fluxo de revisão e publicação do projeto para chegar ao site.

O GitHub continua usando assets substituídos sequencialmente; uma falha remota pode exigir repetir o pacote completo. O background continua no processo da aplicação e a trava coordena instâncias que compartilham o mesmo diretório. Publicação sem credencial do repositório, execução durável fora da aplicação e infraestrutura AWS pertencem à próxima etapa.

As instruções de operação estão em [atualizacao_bases_etapa_1.md](atualizacao_bases_etapa_1.md).
