# Toma Conta — piloto web independente

Aplicação React estática, publicada em `https://matheusprat.es/tomaconta/` pelo Worker Cloudflare já usado no domínio. O navegador consulta JSON versionado e um proxy restrito às APIs públicas SGS e Olinda. O site funciona sem servidor Streamlit, sem login e sem credenciais de terceiros no cliente. Supabase não é necessária para este primeiro piloto.

## Funcionalidade

- Landing em Hanken Grotesk, com crédito do SFN, relação entre porte e ROE, corrida histórica dos dez maiores por ativos e busca em todo o catálogo. A seleção é refeita pela competência publicada; a animação usa os valores de ROE existentes, sem recalculá-los. Busca e links para a análise conservam a identidade e o perímetro. A URL `?view=institutions&bank=<id>` permite reabrir a instituição selecionada.

- 3.163 instituições históricas, 46 trimestres, 63.379 observações da base curada IF.data. Análise por competência, histórico, ranking e comparação por perímetro. Ausência é `null`/N/D e zero permanece zero. Este catálogo não representa um agregado do SFN sem sobreposições.
- Balanço/DRE: 1.938 identidades individuais COSIF 4010 e 205 conglomerados prudenciais COSIF 4060/4066. Na competência jun/26 são 1.771 e 168, respectivamente. O histórico disponível começa em mar/23. As demonstrações usam R$ milhões e percentuais em fração; o catálogo IF.data usa R$ e percentuais 0–100. O vínculo com a análise usa código oficial e nome original exato na mesma competência, registrado em `statements/crosswalk.json`.
- 42 gráficos SGS, 9 SCR.data, 24 Mercado Imobiliário e 29 SPB. Cada gráfico preserva unidade, competência e origem; eixos secundários são explícitos. Brasil e UFs no bloco imobiliário. BNDU excluído e risco AA–D ou mais encerrado em dezembro/2024.
- Filtros por janela/intervalo, tabelas, CSV e PPTX com gráficos Office editáveis em Calibri, branco, laranja, cinza e preto. Exportação da visão, dos 24 gráficos imobiliários e deck SFN completo de 75 gráficos. Dados monetários no PPTX seguem a unidade da tela; percentuais 0–100 são divididos por 100 uma vez para Office.
- Atualizar Base consulta publicações BCB, séries SGS ao vivo e atualiza a cópia imobiliária local, com validação e substituição mensal completa. Falhas preservam a cópia anterior. O usuário pode restaurar a versão publicada. O serviço compartilhado de jobs do projeto Python ainda não está conectado ao piloto; as atualizações locais não alteram a publicação para os demais visitantes.

## Preparar e verificar

```sh
# Na raiz Toma Conta: usa as mesmas transformações/catálogos Python já existentes.
.venv/bin/python web/tools/export_institutions.py
.venv/bin/python web/tools/export_extra.py
.venv/bin/python web/tools/export_charts.py
# Publica todas as identidades e competências dos bundles do checkout atual.
.venv/bin/python web/tools/export_statements.py --output web/public/data
cd web
npm ci
npm test
npm run build
npm run dev -- --port 5175
```

O gerador SCR requer o cache oficial já disponível ou seu download pelo módulo existente. Os dados de instituições são carregados por histórico sob demanda. Os arquivos publicados são dados públicos do BCB; nenhum arquivo de configuração privada, credencial ou cache administrativo integra o build.

As demonstrações publicam snapshot da seleção padrão e fontes completas por identidade em `.json.gz`, com gzip determinístico (`mtime=0`). O índice registra tamanho e SHA-256 de cada asset; índice, crosswalk e manifesto do engine são JSON normal. A geração padrão cobre todas as fontes. Para uma amostra, use `--codes C0080099 60701190 --output /tmp/tomaconta-statements-probe`, preservando o destino da publicação completa.

O engine distribui os módulos Python originais e seus hashes. O snapshot padrão abre sem Python. Seleções de 1–8 competências e downloads XLSX/PPTX executam os mesmos modelos e renderizadores no navegador, em Worker, com Pyodide 0.29.3 e dependências fixadas no manifesto. A primeira preparação carrega cerca de 22 MB de runtime/dependências sob demanda; conexão e dispositivo determinam o tempo. Cada recorte recompõe fórmulas, crescimento entre datas e contexto de junho/dezembro. O Excel mantém todas as competências selecionadas; o PPTX original apresenta as últimas três. O menu explicita esse limite quando a seleção ultrapassa três competências.

```sh
# CI web: apenas arquivos versionados; não requer Parquet nem Python.
cd web
node --test tests/statements-data.test.mjs
npm test
npm run build

# Local, na raiz, com a .venv do projeto e os bundles Parquet disponíveis:
cd ..
.venv/bin/python -m unittest discover -s web/tests -p test_statements_bridge.py
```

Os testes publicados percorrem os 4.286 assets comprimidos sequencialmente, conferem identidade, competência, unidades, SHA-256 e módulos originais. Conferem também ativo/PL/lucro do Itaú individual, PL/lucro/CET1/Basileia prudenciais e preservam o resíduo observado de R$ 105,56 entre os ativos COSIF prudenciais e o IF.data curado. Crédito e provisão têm definições próprias nas fontes. Os testes locais com Parquet comparam o modelo original em seleções de 1/2/8 competências; essas verificações delimitadas não substituem a leitura das validações contábeis de cada análise.

## Publicar no domínio existente

```sh
# Após build, com checkout isolado e atualizado do repo abalroar/matheusprat.es:
node tools/package_site.mjs /caminho/checkout-isolado-do-site
```

O domínio precisa manter a importação de `bcbProxy` de `worker/tomaconta.js`, a rota GET `/tomaconta/api/bcb` e `run_worker_first: ["/tomaconta/api/*"]` junto das rotas existentes. O helper copia apenas os assets do piloto e seu módulo de proxy. Não modifica galeria, banco de fotos, autenticação, DNS ou domínio. O push na `main` do site dispara Cloudflare Workers Builds; o comando `npm run deploy:cloudflare` é a alternativa manual já existente.

`build.json` distingue a versão dos dados (`sourceData`, `builtAt`) da versão da interface (`frontendCommit`, `frontendBuiltAt`). A Hanken Grotesk é servida pelo próprio site; sua licença está em `fonts/Hanken-Grotesk-OFL.txt`.

## Conferência de aceitação

Conferir busca Afinz/Prudencial, escolha de competência, pares, ranking e unidade/escala. No Mercado Imobiliário conferir Brasil/SP, os cinco blocos, risco até 2024 e intervalo sem dados. Baixar CSV/PPTX da visão, 24 gráficos e deck geral; verificar fontes, períodos, dois eixos e gráficos editáveis. Em Atualizar Base consultar as publicações e reconsultar Olinda, sem interromper a base anterior em caso de erro. Conferir também a página inicial e o painel de fotos do domínio, que usam o mesmo Worker.
