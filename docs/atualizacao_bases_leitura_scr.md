# Leitura do SCR.data durante uma atualização — 10/10/2026

A validação pública após o PR #331 encontrou o aviso de cache indisponível na
subaba de inadimplência por faixa de renda. O diagnóstico identificou um caminho
de concorrência introduzido no bootstrap: a leitura tentava obter a trava antes
de verificar a geração local. Uma atualização de outra fonte podia ocupar essa
trava; a recusa virava uma lista vazia de competências, memorizada pela tela por
uma hora.

O comportamento foi demonstrado pelo código e pelos testes de falha. A tela
anterior ocultava a mensagem específica do bootstrap; não há log dessa recusa
individual que confirme a causa exata da sessão pública observada.

## Conferência dos arquivos publicados

O SCR continua usando o release próprio `abalroar/tomaconta@v1.2-scr-cache`.
Essa escolha é igual à do commit anterior à entrega. A API do GitHub confirmou
os 22 assets, incluindo resumo, metadata, manifesto, quatro dimensões e slices
anuais. Metadata e manifesto responderam HTTP 200; seus hashes coincidem com os
digests da API. O manifesto informa 594.299 linhas, 16.956.909 bytes e nenhuma
falha, com competências até jul/26.

A metadata publicada usa schema 2 e não contém `integridade`, `sha256` ou
`colunas`. O novo leitor aceita esse formato legado. O preflight de publicação
não participa da abertura dessa subaba. A investigação consultou apenas a
listagem e os dois JSONs pequenos; não baixou o resumo nem executou extração.

## Correção

O bootstrap pode ler uma geração local completa durante outra atualização. Ele
resolve dados e metadata pelos caminhos coerentes do cache, inclusive o
snapshot anterior se houver promoção em andamento. O manifesto e as quatro
dimensões precisam existir na mesma geração. Schema, contagens e identidade
continuam conferidos. Arquivos ausentes, corrompidos ou alterados durante a
leitura exigem nova tentativa.

O download e a atualização forçada continuam sujeitos à trava e à validação
remota. Em início sem arquivos locais, uma trava ocupada pode causar
indisponibilidade temporária. A consulta de competências passa a lançar uma
exceção nesse caso; `st.cache_data` não memoriza a falha. O próximo rerun pode
tentar novamente. A mensagem existente da tela e os rótulos dos controles foram
preservados.

## Validação

Passaram 156 testes, executados em um grupo com rede externa bloqueada e limite
de 768 MiB. O pico observado foi 199,4 MiB. Dez casos novos cobrem leitura de
gerações legadas e gerenciadas sob trava de outra fonte, retry do início sem
runtime, dimensões/manifesto/identidade inválidos, atualização forçada, snapshot
anterior durante promoção e falhas temporárias que deixam de ser memorizadas
pelo Streamlit.

A comparação estrutural com `fd83fd48c5e91a16e4955e77c66522508be5c823` confirmou
que a visão SCR permaneceu idêntica fora da consulta de disponibilidade e seu
tratamento de erro. No cache SCR, as diferenças deste ajuste se limitam ao
bootstrap e ao novo helper de leitura. Builders, parsers, queries e cálculos
financeiros permaneceram iguais.

Os registros estão no diretório local
`outputs/publicacao-atualizacao-bases-2026-10-10/`:
`scr-indisponibilidade-diagnostico.json`, `scr-preservacao-codigo.json` e os
relatórios `testes-locais/tomaconta-scr-leitura-concorrente.*`.

A revisão, publicação do código e conferência pública após novo reboot ficam
com o fluxo de entrega. Infraestrutura AWS e execução externa permanecem fora
deste ajuste.

## Custo do recálculo e equivalência numérica

O recálculo continua usando todo o histórico e as mesmas fórmulas. Valores que
já são números passam diretamente para `float`, evitando a criação repetida
de uma `Series` por célula. Strings, datas, Decimal e outros tipos seguem o
caminho anterior; inteiros fora da faixa de `float` também mantêm o fallback.

Passaram 184 testes do conversor e das telas críticas, além de 77 execuções do
fluxo de atualização, em grupos sequenciais sob o mesmo teto de memória. O
pico máximo foi 302,6 MiB. Os 158 casos novos incluem equivalência escalar e
comparação exata de DataFrames completos. O recorte real de Itaú e Bradesco
abrange oito trimestres, 16 linhas e 93 colunas, incluindo valores, traces e
tipos. A condição original de valores ausentes permanece preservada.

Os relatórios correspondentes são `tomaconta-numeric-equivalence.*` e
`tomaconta-numeric-flow.*`, no mesmo diretório de evidências. Os grupos se
sobrepõem às verificações anteriores; suas execuções não foram somadas como
casos únicos adicionais da suíte geral.
