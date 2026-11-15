# Revisão da leitura das variações em Peers — 10/10/2026

Revisão dos 26 indicadores da Tabela de Peers, no perímetro Consolidada / Prudencial, com as referências QoQ e YoY. Insumos: cache `critical_screens` até Jun/26, IFData e Cadoc 4060. Definições oficiais e recortes: [BCB IFData](https://www3.bcb.gov.br/ifdata/).

## Operação e apresentação

- Taxas de capital, retorno, custo de crédito e participações de risco: subtração em bps, exibidos sem casas decimais.
- Coberturas de PDD ou perdas sobre créditos vencidos/estágios e custo/receita: subtração em pontos percentuais, com uma casa decimal. Os níveis percentuais mantêm duas casas decimais para facilitar a conferência da subtração.
- Montantes: crescimento relativo `(atual − referência) / referência × 100`, com referência positiva. Múltiplos: diferença direta em x.
- Cálculos mantêm a precisão dos insumos. Movimentos que arredondariam para zero preservam a direção com `<1 bp` ou o limite de exibição da unidade. Igualdade exata recebe `= 0`.
- QoQ e YoY mantêm a referência explícita em cada coluna. Quebras em 2025, ausência de componentes e janelas YTD diferentes continuam bloqueando deltas.

## Exemplos do Itaú — Mar/26 contra Dez/25

| Indicador | Referência | Atual | Variação apresentada |
|---|---:|---:|---:|
| Custo de Crédito / Receita de Crédito (%) | 25,33% | 27,62% | ↑ +2,3 p.p. |
| Inadimplência / Carteira Total | 2,18% | 2,25% | ↑ +7 bps |
| PDD / Inadimplência (arrasto) | 197,11% | 193,54% | ↓ −3,6 p.p. |
| Índice de Basileia Total (%) | 15,18% | 14,77% | ↓ −41 bps |

No exemplo 193,1% → 193,5%, a diferença direta é +0,4 p.p. Na fonte usada para o Itaú em Dez/25 → Mar/26, os níveis são 197,11% → 193,54%, diferença de −3,5768 p.p., exibida como −3,6 p.p.

A cobertura PDD/vencidos soma somente as quatro perdas esperadas e2 + f2 + g2 + h2 do Rel. 2, em magnitude, e divide pelo saldo integral dos vencidos por arrasto do Rel. 16. O numerador abrange outros ativos além dos vencidos; a razão oferece uma aproximação de cobertura. Seu movimento precisa ser lido com a variação da PDD e dos vencidos.

## Política por indicador

| Indicador | Unidade da variação | Direção usualmente favorável |
|---|---|---|
| Ativo total | % | Contextual; cor neutra |
| Ativos líquidos | % | Contextual; cor neutra |
| Carteira de crédito ampliada | % | Contextual; cor neutra |
| Perdas e ajustes contábeis | % | Contextual; cor neutra |
| Depósitos totais | % | Contextual; cor neutra |
| Core funding | % | Contextual; cor neutra |
| Patrimônio líquido | % | Contextual; cor neutra |
| Custo de crédito | bps | Queda |
| Custo / receita de crédito | p.p. | Queda |
| Ativos problemáticos / carteira | bps | Queda |
| Vencidos >90 dias (arrasto) | % | Contextual; cor neutra |
| Vencidos >90 dias (arrasto) / carteira total | bps | Queda |
| PDD / vencidos >90 dias (arrasto) | p.p. | Alta |
| Ativos em estágio 2 | % | Contextual; cor neutra |
| Ativos em estágio 3 | % | Contextual; cor neutra |
| Estágio 3 / carteira ampliada | bps | Queda |
| Inadimplência / carteira ampliada | bps | Queda |
| Perdas e ajustes / estágio 3 | p.p. | Alta |
| Perdas e ajustes / estágios 2 e 3 | p.p. | Alta |
| Perdas e ajustes / carteira ampliada | bps | Contextual; cor neutra |
| Ativo / PL | x | Queda |
| Carteira ampliada / PL | x | Queda |
| Capital principal (CET1) | bps | Alta |
| Basileia total | bps | Alta |
| Lucro líquido acumulado | % | Contextual; cor neutra |
| ROE anualizado | bps | Alta |

A cor representa a leitura usual da direção desse indicador. Aumento de saldos permanece neutro. Aumento de custo de crédito ou inadimplência recebe vermelho; redução recebe verde. Queda de capital e cobertura recebe vermelho. Indicadores com alerta de qualidade ficam neutros. Setas mantêm o sentido matemático de alta ou queda.

A cobertura por perdas e ajustes/estágios é uma aproximação. A razão de perdas/carteira recebe cor neutra: aumento pode refletir reforço de provisões, piora de risco ou ajustes contábeis.

## Conferência

Conferência independente com Decimal: 26 indicadores, 46 competências, três bancos e dois modos de comparação; 7.176 células, 2.961 deltas calculáveis e nenhuma divergência de fórmula, unidade ou sinal.

Bloqueios preservados: 3.981 bases N/D, 75 quebras em 2025, 21 referências monetárias não positivas e 138 janelas YTD diferentes. A conferência verifica os deltas sobre os insumos curados; ela não representa nova validação de todos os dados reportados pelo BCB.

Interface, Excel, PowerPoint e PNG compartilham o mesmo cálculo, arredondamento e significado das cores. A memória de cálculo e a planilha Dados e status conservam os deltas numéricos sem arredondamento.

Snapshot: bps inteiros, cobertura sobre estágio 3 e crédito/captações em p.p.; auditoria ajustada à precisão de exibição. Rankings: rótulos e eixos de bps sem decimais.
