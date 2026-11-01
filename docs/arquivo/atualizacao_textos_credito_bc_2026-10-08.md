# Comentários de crédito BC — atualização de 8 de outubro de 2026

Os 11 comentários de `data/comentarios_credito_bc.json` foram revistos para a
nota à imprensa de 29/09/2026. Nove comentários usam agosto/2026; Situação dos
Agentes e SCR.data preservam julho/2026. Os textos passam a citar os dados
oficiais desta rodada e os cálculos das séries que alimentam os gráficos.

## Fontes

- [Anúncio da publicação, 29/09/2026](https://www.bcb.gov.br/detalhenoticia/21275/nota).
- [Nota à imprensa, texto em PDF](https://www.bcb.gov.br/content/estatisticas/hist_estatisticasmonetariascredito/202609_Texto_de_estatisticas_monetarias_e_de_credito.pdf).
- [Tabelas oficiais em XLSX](https://www.bcb.gov.br/content/estatisticas/hist_estatisticasmonetariascredito/202609_Tabelas_de_estatisticas_monetarias_e_de_credito.xlsx).
- BCData/SGS: bundle publicado no PR #304, SHA-256
  `62696daafde87b051aa09e37b54c525d105b79ddcae6994c8a82dc5a91381dfd`.
- [Metodologia SCR.data v2](https://www.bcb.gov.br/pda/desig/metodologia_versao2.pdf).
- [Instruções do documento SCR 3040, faixas de renda](https://www.bcb.gov.br/content/estabilidadefinanceira/Leiaute_de_documentos/scrdoc3040/SCR_InstrucoesDePreenchimento_Doc3040.pdf).
- [Nota de 13/03/2025, seção 5: mudança das provisões](https://www.bcb.gov.br/content/estatisticas/hist_estatisticasmonetariascredito/202502_Texto_de_estatisticas_monetarias_e_de_credito.pdf).

## Valores e conceitos utilizados

| Comentário | Evidência usada |
| --- | --- |
| Concessões | Nota: total com ajuste sazonal +1,7% no mês; PJ +3,2%; PF +0,7%. |
| Estoque | Nota: SFN R$ 7,4 tri, +0,5% no mês e +9,2% em 12 meses; crédito ampliado R$ 22,0 tri, +11,3% em 12 meses. |
| Tomador | Nota: PF R$ 4,7 tri, +10,5% nominal em 12 meses; PJ R$ 2,7 tri, +7,1%. |
| Produto | Nota: avanço em veículos, cartão rotativo e consignado privado PF; recuo de capital de giro total e duplicatas/recebíveis PJ. |
| Porte | SGS 27701/27702: MPMe R$ 1.337,1 bi, +0,98% nominal no mês e +2,33% real em 12 meses; grandes R$ 1.416,7 bi, +0,07% e +2,41%, respectivamente. Participação MPMe: 48,6% da soma dessas duas séries. |
| Controle | SGS 2007/12106/12150: público 41,7%, privado nacional 44,9%, estrangeiro 13,4% da soma dos três grupos; crescimento real em 12 meses de 3,86%, 5,55% e 5,06%, respectivamente. |
| Situação | Nota, julho: endividamento 49,9%; comprometimento 28,7%. Junho foi revisado e também arredonda a 28,7%. |
| Pré-inadimplência e inadimplência | Nota: inadimplência total 5,0%, livre PF 8,0%, livre PJ 4,3%. SGS 21033/21007: atrasos de 15–90 dias em recursos livres, PF 4,53% → 4,52% e PJ 2,93% → 2,84% entre julho e agosto. |
| Cobertura | SGS 13645/21082: provisão 7,9% → 8,0%; inadimplência 4,88% → 5,04%; cobertura calculada 161,9% → 158,7%. |
| Faixa de renda | SCR.data até julho; nota e séries de crédito SGS até agosto. Comparações preservam competência, recorte e denominador. |
| Taxas | Nota: taxa média total 32,3% a.a.; spread 21,2 p.p.; livre PF 61,7% a.a. e livre PJ 24,2% a.a. |

Os percentuais da nota são reportados conforme a publicação, inclusive suas
variações em pontos percentuais. Níveis mais precisos do SGS são identificados
nos comentários de pré-inadimplência e cobertura. Por exemplo, a variação
mensal da inadimplência reportada na nota é 0,1 p.p.; a diferença entre os
níveis SGS 5,04% e 4,88% é 0,16 p.p. Cada informação mantém sua fonte e precisão.

## Cálculos e comparabilidade

- Variação nominal: `(saldo atual / saldo anterior - 1) × 100`.
- Variação real em 12 meses: desconta o índice acumulado do IPCA (SGS 433),
  usando a mesma função dos gráficos.
- Participações por porte e controle usam a soma das séries do respectivo
  recorte como denominador.
- Cobertura: `(provisão % / inadimplência %) × 100`; relaciona provisões totais
  a crédito inadimplente. A suficiência de provisões exige informação adicional
  sobre perdas esperadas, composição e garantias.
- A nota usa o total dessazonalizado SGS 24439 (R$ 738,771 bi em agosto), com
  alta de 1,7259% sobre julho. O gráfico existente soma quatro componentes
  dessazonalizados (SGS 24443, 24446, 24444 e 24447), totalizando R$ 740,694 bi.
  O comentário informa a diferença entre essas séries. Gráficos e bases
  permanecem como publicados no PR #304.
- Provisões têm mudança de critério em janeiro/2025, para perdas esperadas por
  estágios. Ativo problemático no SCR também tem mudança metodológica nessa
  competência. As faixas de renda variam com o salário mínimo.

As referências anteriores a calls de bancos, imprensa, Comef e PEF foram
substituídas nesta rodada por evidências da nota e das séries oficiais utilizadas.
As observações sobre porte, controle, atraso curto e cobertura são identificadas
como dados ou cálculos SGS, pois a nota não detalha todos esses recortes.

## Validação

A atualização preserva as 11 chaves, a estrutura dos comentários, as fontes e
as competências por página. O teste de aviso de defasagem usa uma competência
fixa de exemplo, mantendo o teste independente das futuras atualizações do texto.
Os testes existentes de comentários e do deck verificam carregamento,
serialização, layout e inclusão dos textos na exportação.
