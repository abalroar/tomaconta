# Atlas SFN — aplicação web

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Analistas de crédito de instituições financeiras. A primeira pergunta é “Como está uma instituição específica?”. A pessoa pode estar chegando pela primeira vez; a navegação deve permitir encontrar e analisar uma instituição com autonomia.

## Product Purpose

Explorar dados públicos do Banco Central, comparar instituições no perímetro e competência corretos e produzir exportações Office que preservem os números e as fontes.

## Operating Context

Landing geográfica de crédito PF/PJ e agências; análise institucional; Balanço e DRE; comparação e ranking; séries do SFN, mercado imobiliário e pagamentos; atualização da base. Publicação em matheusprat.es/atlas-sfn (entrada anterior /tomaconta preservada), com assets estáticos e Worker Cloudflare. Cálculos contábeis e renderizadores nativos são os módulos Python existentes, executados sob demanda no navegador.

## Capabilities and Constraints

- Preservar cálculo, identidade, perímetro, competência, unidades, sinais, zero e N/D.
- Valores de diferentes perímetros não podem ser reunidos por semelhança de nome.
- Informações geográficas de agências usam um cadastro separado do IF.data. A agregação por município precisa estar visível. Presença física e cobertura financeira têm datas e universos próprios.
- Os exportáveis mantêm Calibri, fundo branco e a paleta Itaú BBA existente. O Excel recebe até oito competências; o PowerPoint contábil original apresenta as últimas três.
- Atualizações precisam preservar a última versão válida quando houver falha e identificar claramente seu alcance local ou compartilhado.

## Brand Commitments

Hanken Grotesk, licença aberta e hospedagem local da fonte; fundos branco e gelo; azul-petróleo. Cores próprias dos bancos nas comparações e na exploração por instituição. O usuário rejeitou roxo e mostarda nas categorias genéricas dos gráficos. Referências de ritmo e exploração: Kontinentalist e A Hidden Infrastructure, SPUN. Texto curto, humano e factual, sem slogans ou estruturas de oposição narrativa.

## Evidence on Hand

Datasets públicos versionados em public/data, com fontes e competências. Módulos e exportadores financeiros existentes. Cadastro oficial de agências Olinda e geografia municipal/UF do IBGE, com proveniência e validações próprias no pipeline de rede.

## Product Principles

- A instituição e seu perímetro orientam a análise.
- A fonte fica perto do dado que sustenta.
- A interação deve responder à exploração e conduzir à análise.
- O acabamento visual preserva a precisão financeira.
