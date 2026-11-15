# Mercado Imobiliário — Olinda/BCB

Implementação de 5 de novembro de 2026. Fonte oficial:
<https://www.bcb.gov.br/estatisticas/mercadoimobiliario>.

## Escopo e conceitos

24 gráficos na seção **Estatísticas Crédito BC > Mercado Imobiliário**:

- Contratação PF: valor contratado, indexadores, taxa anual e LTV.
- Contratação PJ: valor contratado, indexadores e taxa anual.
- Estoque PF: carteira, indexadores, risco da operação, inadimplência, ativos problemáticos e próxima parcela.
- Estoque PJ: carteira, indexadores, risco da operação, inadimplência e ativos problemáticos.
- Imóveis: tipo, dormitórios, área, implantação, valor e garantia.

BNDU está excluído da coleta normalizada, dos gráficos e dos exportáveis por decisão do usuário. Risco da Operação é histórico AA–D ou mais, com última competência encontrada em dezembro/2024; não é convertido em estágios da Resolução 4.966. A unidade de ativos problemáticos é R$, enquanto inadimplência é percentual. LTV, próxima parcela, área, avaliação e compra são medianas. O agregado nacional usa o código `br` publicado pelo BCB. `NA` da fonte é preservado como geografia não informada e não integra a lista de estados.

No primeiro bundle, crédito alcança agosto/2026 e imóveis julho/2026. O BCB informa defasagens de 60 e 90 dias, respectivamente. A janela móvel termina na última observação de cada gráfico, inclusive nos históricos; o intervalo explícito respeita as datas escolhidas e informa ausência quando não há interseção. Taxas, medianas e categorias ausentes não são preenchidas com zero nem agregadas entre UFs.

## Coleta e persistência

Entidade única:
`https://olinda.bcb.gov.br/olinda/servico/MercadoImobiliario/versao/v1/odata/mercadoimobiliario`.
Schema: `Data` (string ISO), `Info` (código da série) e `Valor` (decimal).

`utils/mercado_imobiliario.py` contém o catálogo versionado e a classificação inequívoca dos códigos, inclusive `home_equity`, `d_mais` e `alienacao_fiduciaria`. Os gráficos reutilizam os builders de linhas e colunas empilhadas da seção SGS. `utils/ifdata_cache/mercado_imobiliario.py` herda `BaseCache` e reutiliza `_build_odata_url`, `_request_json`, travas e promoção de dados/metadados.

Cada consulta usa `Data eq 'AAAA-MM-DD'`, ordenação `Info asc`, seleção `Data,Info,Valor` e JSON. Se uma página atingir o limite, a seguinte acrescenta `Info gt 'ULTIMO_CODIGO'`. `$skip` falhou no serviço durante o estudo e não é usado. A ordenação textual da fonte difere da ordem Unicode para códigos como `NA`; as páginas mantêm a ordem fornecida pelo BCB e são conferidas por unicidade, competência e avanço do cursor.

A coleta inicial começa em abril/2014; as seguintes revisam os últimos 12 meses. Janela e reconstrução integral podem ser solicitadas explicitamente. Revisões anteriores à cauda incremental exigem reprocessar o período correspondente. Competências posteriores à última publicação são excluídas da execução, com a competência disponível registrada nos metadados.

Cada mês confirmado tem checkpoint privado em `data/cache/mercado_imobiliario/staging/`, com hash do parquet e da resposta. A retomada do mesmo plano reaproveita meses confirmados. Uma execução posterior a uma promoção reconsulta a janela, permitindo capturar revisões. A substituição é mensal completa, inclusive para remover observações retraídas pela fonte. Falhas de rede, categoria nova, duplicidade, cobertura ativa incompleta ou erro de gravação impedem promover o candidato. O pacote anterior é preservado.

O arquivo público mantém `data`, `info`, `valor`, `grafico`, `categoria`, `linha` e `uf`. Os metadados registram consulta, competências, catálogo, cobertura por gráfico, proveniência e integridade. Os checkpoints não entram na publicação.

## Atualizar Base e AWS

A fonte **Mercado Imobiliário (Olinda/BCB)** está registrada no CacheManager, na tela Atualizar Base, no CLI, no refresh, em Atualizar Tudo, nos manifestos, na validação de publicação e no serviço portátil. O contrato de jobs aceita uma janela congelada `start`/`end`; o worker aplica o mesmo coletor e prepara uma revisão consistente. Fechar o navegador no serviço portátil não interrompe a execução do worker. No modo legado, permanecem as características de execução e recuperação já existentes na aplicação.

Os assets de release são `mercado_imobiliario_dados.parquet` e `mercado_imobiliario_metadata.json`. O bundle versionado permite iniciar o app sem consulta Olinda; uma revisão oficial configurada utiliza exclusivamente seus próprios arquivos.

A integração preserva o modelo atual de AWS: um host com volume POSIX persistente, como EC2/EBS. Não cria recursos ou credenciais. A fila e as travas locais não fornecem coordenação distribuída; S3 como armazenamento oficial requer o adaptador previsto em `docs/aws.md` e `docs/autosservico_portatil_etapa_2.md`. Backups em S3 seguem a configuração existente.

```sh
# Revisar a janela recente, com retomada dos checkpoints em caso de falha.
.venv/bin/python tools/update_caches_cli.py --tipo mercado_imobiliario

# Reprocessar uma janela determinada, preservando competências externas.
.venv/bin/python tools/update_caches_cli.py --tipo mercado_imobiliario \
  --mensal-inicio 202601 --mensal-fim 202608 --modo overwrite

# Reconstruir desde o começo; os modos preservam competências fora da janela explícita.
.venv/bin/python tools/update_caches_cli.py --tipo mercado_imobiliario --modo rebuild

# Conferir a presença da fonte no plano geral, sem executar consultas.
.venv/bin/python tools/update_all.py --plan
```

## PowerPoint e conferência

O popover Exportar oferece a visão aberta, os 24 gráficos de Mercado Imobiliário e o deck geral. Este último inclui as cinco visões sem exigir visita prévia a cada uma. A cobertura por gráfico identifica exportações parciais. O recorte imobiliário selecionado participa da assinatura do deck geral, junto com a identidade de seus metadados.

Os arquivos reutilizam os exportadores existentes, em 16:9, com até quatro gráficos Office editáveis por slide, planilhas embutidas, Calibri, fundo branco e paleta Itaú. Cada gráfico registra fonte, abrangência e período efetivo. Percentuais 0–100 da fonte são convertidos em frações somente para a representação percentual do Office. Os dados monetários são escalados explicitamente para milhões/bilhões; medianas são preservadas.

```sh
.venv/bin/python -m pytest -q tests/test_mercado_imobiliario.py \
  tests/test_deck_credito_bc.py tests/test_scr_pptx_export.py \
  tests/test_update_backend_contracts.py tests/test_update_end_to_end.py \
  tests/test_update_all.py tests/test_release_ops.py
```

Conferir também as cinco visões na aplicação, os recortes Brasil/UF, intervalo sem dados, fonte Olinda no popover, execução e retomada na atualização e os arquivos realmente baixados. Abrir os PPTX no PowerPoint, confirmar ausência de reparo, edição dos gráficos, Calibri, limites das caixas, legendas e rótulos. Renderizar os slides e inspecionar todas as lâminas novas e seus equivalentes no deck geral. Validação local, merge e validação pública são etapas distintas.
