# Análise prudencial em Excel

Acesso: **DRE (Ind. e Congl.) → Balanço, DRE e Carteira (Congl.)**. Escolher o conglomerado e até oito competências; gerar e baixar. O produto pertence ao perímetro prudencial, identificado por `COD_CONGL`, sem misturar a instituição individual.

O arquivo contém Balanço, DRE, Carteira 4.966, Mapa COSIF, Dados COSIF, Dados IFData e Validações. As três primeiras abas seguem a referência visual fornecida, com Tahoma, faixas pretas, subtotais cinza, negativos vermelhos, períodos lado a lado e linhas técnicas ocultas. A referência recebida foi uma fotografia de Balanço e DRE; não havia modelo XLSX nem referência visual específica da carteira.

## Fontes e cálculos

- Balanço: 4066 quando presente. No 4060, PL = grupo 6 + grupos 7 e 8.
- DRE: 4060, acumulado no semestre civil. Dezembro representa julho–dezembro. O ROE anualiza pelo número de meses transcorridos e usa PL de fechamento, conforme a referência.
- Carteira: IFData Relatórios 16 e 2; estágio 3 no COSIF. Baixas e renegociações permanecem N/D quando não há fluxos disponíveis. Coberturas entre universos diferentes recebem identificação explícita.
- Capital: IFData Relatório 5, com PR do Relatório 1 quando necessário. CET1, Nível I e Basileia são calculados e confrontados com índices reportados.
- Mapeamento: código exato, sintética do prefixo e fronteira de contas-filhas. Respeita os níveis COSIF 1/2/3/5/7/9, sem somar simultaneamente uma sintética e seus descendentes. Descrições originais e seleção ficam no Mapa COSIF.
- Fórmulas: chaves por instituição, competência, documento e código/campo; ÍNDICE + CORRESP, com teste de unicidade. Valores brutos em reais, apresentação em milhões. Ausência fica N/D; zero informado permanece zero.
- Subcontas: conferência das filhas imediatas de todas as sintéticas publicadas, dos grupos apresentados, da composição de carteira, do resultado e da ponte 4060–4066. Diferenças são expostas; o sistema não cria ajustes compensatórios.

## Ingestão e guarda

`utils/ifdata_cache/bloprudencial_ingest.py` lê CSV estritamente, valida linhas, saldos e chaves, arquiva os bytes originais e seu SHA-256, substitui a competência inteira e verifica a releitura após a gravação transacional. Assim, contas removidas numa retificação não sobrevivem à atualização.

Exemplo:

```bash
python tools/build_prudential_workbook.py \
  --import-csv /caminho/202606BLOPRUDENCIAL.CSV \
  --code C0083539 --periods 202512 202606 --output /caminho/Afinz.xlsx
```

Foram substituídos somente dezembro/2025 e junho/2026 no bundle BLOPRUDENCIAL. O primeiro CSV foi baixado do BCB; o segundo foi fornecido pelo usuário. Ambos foram gerados pelo BCB em 19/10/2026. Os ZIPs originais e manifestos estão em `data/bundled/bloprudencial/sources/`. A publicação `tomaconta-prudencial-retificacoes-20261030-v1` precede runtimes baseados na versão antiga, inclusive após reinício. Nenhum outro cache ou tela curada foi rematerializado; a nova análise usa diretamente as fontes identificadas em seu arquivo.

O histórico fora dessas duas competências foi preservado, inclusive 4.852 chaves repetidas já existentes. A geração recusa duplicidades no recorte selecionado. A ingestão desta entrega não declara saneamento de todo o histórico.

## Validação de 30/10/2026

17 testes automatizados passaram, incluindo sete instituições reais, fallback 4060, ausência versus zero, duplicidades, hierarquia, fórmulas e persistência. Uma leitura com runtime vazio confirmou o bundle e os hashes dos dois arquivos originais.

A varredura dos 173 conglomerados existentes na união dos dois períodos encontrou fechamento patrimonial em todos os recortes disponíveis. A composição de DRE ficou dentro de R$ 0,02 em 172 conglomerados; Porto Seguro apresentou R$ 0,06 de diferença, preservada e sinalizada. Períodos ou ramos ausentes ficam N/D. Esta varredura contábil não substitui revisão semântica individual de cada instituição.

Na Afinz, 378 conferências: 375 OK e três diferenças entre fontes. Resultado 4060 versus Relatório 4 em dezembro: R$ 1.918.803,95. Carteira Relatório 2 versus Relatório 16: R$ 10.095.996,49 em dezembro e R$ -3.209.851,18 em junho. Balanço, resultado COSIF, subcontas, conciliação 4060–4066 e índices prudenciais fecharam.

O arquivo foi aberto no Microsoft Excel sem reparo. A recalculação independente em LibreOffice não encontrou erros de fórmula nem diferenças numéricas. Há normalização de maiúscula/minúscula em quatro escapes XML de um caractere de controle presente na descrição original; o arquivo fonte está preservado integralmente. O download real pelo aplicativo local foi exercitado.

Evidências contábeis: `analise_prudencial_excel_validacao.json`.
