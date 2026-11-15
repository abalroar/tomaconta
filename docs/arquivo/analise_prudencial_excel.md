# Análise prudencial em Excel

Acesso: **Contábil e crédito → DRE (Ind. e Congl.) → Análise financeira (conglomerado)**. Escolher o conglomerado e até oito competências; a tabela carrega automaticamente, com um único botão de Excel. O produto pertence ao perímetro prudencial, identificado por `COD_CONGL`, sem misturar a instituição individual.

O arquivo abre em **Comitê**, com Balanço e DRE lado a lado, seguindo a fotografia fornecida. Contém também Balanço, DRE, Carteira 4.966, Mapa COSIF, Dados COSIF, Dados IFData e Validações. As abas de apresentação usam Tahoma, faixas pretas, subtotais cinza, negativos vermelhos, períodos lado a lado e linhas técnicas ocultas. A referência recebida foi uma fotografia de Balanço e DRE; não havia modelo XLSX nem referência visual específica da carteira.

A tela usa uma tabela HTML com o padrão visual da Carteira 4.966: cabeçalho laranja, hierarquia por recuo e peso, percentuais discretos, subtotais cinza e negativos vermelhos. Cabeçalho e primeira coluna permanecem visíveis ao rolar. Fontes e validações ficam em uma única área recolhida. No celular, a tabela mantém rolagem horizontal.

## Fontes e cálculos

- Balanço: 4066 quando presente. No 4060, PL = grupo 6 + grupos 7 e 8.
- DRE: 4060, acumulado no semestre civil. Dezembro representa julho–dezembro. O ROE anualiza pelo número de meses transcorridos e usa PL de fechamento, conforme a referência.
- Carteira: IFData Relatórios 16 e 2; estágio 3 no COSIF. Baixas e renegociações permanecem N/D quando não há fluxos disponíveis. Coberturas entre universos diferentes recebem identificação explícita.
- Capital: IFData Relatório 5, com PR do Relatório 1 quando necessário. CET1, Nível I e Basileia são calculados e confrontados com índices reportados.
- Mapeamento: código exato, sintética do prefixo e fronteira de contas-filhas. Respeita os níveis COSIF 1/2/3/5/7/9, sem somar simultaneamente uma sintética e seus descendentes. Descrições originais e seleção ficam no Mapa COSIF.
- Fórmulas: chaves por instituição, competência, documento e código/campo; ÍNDICE + CORRESP, com teste de unicidade. Valores brutos em reais, apresentação em milhões. Ausência fica N/D; zero informado permanece zero.
- Totalizadores COSIF 3.9.9.99.99 e 9.9.9.99.99 permanecem na base, mas não entram como filhas de compensação 3/9. São totais gerais conforme [Críticas COSIF do BCB, regra G7](https://www.bcb.gov.br/content/estabilidadefinanceira/cosif/criticas-cosif/criticascosif.pdf).
- Subcontas: conferência das filhas imediatas de todas as sintéticas publicadas, dos grupos apresentados, da composição de carteira, do resultado e da ponte 4060–4066. Diferenças são expostas; o sistema não cria ajustes compensatórios.

## Ingestão e guarda

`utils/ifdata_cache/bloprudencial_ingest.py` lê CSV estritamente, valida linhas, saldos e chaves, arquiva os bytes originais e seu SHA-256, substitui a competência inteira e verifica a releitura após a gravação transacional. Assim, contas removidas numa retificação não sobrevivem à atualização.

Exemplo:

```bash
python tools/build_prudential_workbook.py \
  --import-csv /caminho/202606BLOPRUDENCIAL.CSV \
  --code C0083539 --periods 202512 202606 --output /caminho/Afinz.xlsx
```

Foram substituídos dezembro/2025 e junho/2026 na entrega inicial, e julho–outubro/2025 nesta revisão. As quatro fontes adicionais foram baixadas do BCB para corrigir 4.852 chaves repetidas: 4.836 repetições idênticas e 16 com saldos conflitantes. A competência foi substituída inteira, com os arquivos originais arquivados e verificados por SHA-256 em `data/bundled/bloprudencial/sources/`.

A base consumida tem 1.241.803 registros, 205 conglomerados, 34 competências de março/2023 a junho/2026 e 5.319 combinações de conglomerado/data. Zero duplicidades. As fontes oficiais atuais não contêm BK IP em setembro/2025 nem NIUM IP em outubro/2025; essas duas combinações antigas deixaram de aparecer. As demais competências foram preservadas.

Publicação: `tomaconta-prudencial-historico-20261030-v2`. SHA-256 do parquet: `f81fadba4ef1f01c6162da3a34fdf677ca4409a40a1e98975d1964f6f0099932`. A leitura com runtime vazio reproduziu os 1.241.803 registros e o mesmo hash. Os seis arquivos originais arquivados foram conferidos. A precedência do bundle protege a leitura contra runtime antigo.

## Validação de 30/10/2026 — revisão visual e cobertura

A auditoria reproduzível está em `tools/audit_prudential_coverage.py`. Ela gera e inspeciona o XLSX de cada combinação disponível e um comparativo de até oito datas por conglomerado, abrangendo a mudança do COSIF. A inspeção de cada XLSX verifica integridade ZIP e ausência de células de erro; a recalculação independente é feita em amostra, não nos milhares de arquivos.

Foram gerados e verificados **5.319 XLSX por instituição/data e 205 comparativos**, sem falhas de geração ou de integridade. 18 testes automatizados passaram. O fechamento patrimonial teve 5.318 conferências OK e uma indisponível por ausência de passivo na fonte (Transfero IP, setembro/2023). Os breakdowns verificáveis fecharam; ramos ausentes permanecem N/D. O resultado COSIF da DRE teve duas diferenças acima da tolerância de R$ 0,02: Porto Seguro em junho/2026, R$ 0,06; J17 SCD em maio/2026, R$ -0,20. As diferenças são preservadas.

Os controles de hierarquia tiveram 420 diferenças residuais de até aproximadamente R$ 1,00, incluindo precisão numérica em contas de compensação muito grandes. Há também 783 diferenças entre fontes e controles de resultado: 351 de carteira, 141 de Balanço versus IFData, 126 na ponte patrimonial 4060–4066, 84 de capital e 81 de DRE. Esses controles não geram ajustes artificiais.

Os índices prudenciais apresentados são calculados a partir dos valores absolutos de capital e RWA. Em alguns registros, o índice armazenado no cache difere; a normalização legada por magnitude pode afetar índices superiores a 100%. O valor armazenado permanece auditável e sua divergência é sinalizada. Nenhuma correção silenciosa é aplicada ao cache de capital.

Disponibilidade varia por instituição e data: fontes IFData são trimestrais, a carteira 4.966 tem histórico próprio e detalhes COSIF mudam em 2025. A geração em toda a base não significa disponibilidade de todas as rubricas; ausências permanecem N/D. O perímetro desta função é o conglomerado prudencial.

A amostra recalculada em LibreOffice contém Afinz (dois semestres), Itaú (cinco datas entre 2023 e 2026) e AF Paraná (capital acima de 100%). Foram conferidas 27.976 fórmulas, sem células de erro nem diferenças de valores. O arquivo Afinz abriu no Microsoft Excel sem reparo; a visualização nativa confirmou Tahoma e a aba Comitê. A tela foi verificada em desktop e em viewport de 390 px.

Na Afinz, permanecem as três diferenças entre fontes: resultado 4060 versus Relatório 4 em dezembro/2025, R$ 1.918.803,95; carteira Relatório 2 versus Relatório 16, R$ 10.095.996,49 em dezembro e R$ -3.209.851,18 em junho. Balanço, resultado COSIF, subcontas, ponte 4060–4066 e índices prudenciais fecharam.

Evidências: `analise_prudencial_cobertura.json` (cobertura integral e resumo dos controles); `analise_prudencial_excel_validacao.json` (detalhamento da Afinz na entrega inicial).
