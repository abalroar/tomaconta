# Revisão das variações — 10/10/2026

Os critérios de unidade, precisão e cor desta revisão foram atualizados na [revisão da leitura de Peers](revisao_leitura_peers_2026-10-10.md), com bps inteiros e coberturas em p.p.

As fórmulas de diferença em bps dos peers estavam corretas. A apresentação favorecia uma interpretação incorreta: a comparação padrão era YoY, o período de referência estava apenas no tooltip e os níveis percentuais eram arredondados para uma casa decimal.

## Reconciliação do Itaú prudencial

Fonte: cache curado `critical_screens`, componentes dos relatórios IFData 16 (arrasto e carteira total) e 5 (capital e RWA), competências Dez/25 e Mar/26. Os cálculos mantêm os valores sem arredondamento.

| Indicador | Dez/25 | Mar/26 | QoQ, diferença | YoY de Mar/26, referência Mar/25 |
|---|---:|---:|---:|---:|
| Vencidos >90 dias por arrasto / carteira total do Rel. 16 | 2,180346% | 2,253703% | +7,335709 bps | +3,650140 bps |
| Basileia total | 15,183844% | 14,769709% | −41,413550 bps | −87,440715 bps |

Com os níveis arredondados a duas casas, 2,25% − 2,18% = 0,07 p.p. = 7 bps; 14,77% − 15,18% = −0,41 p.p. = −41 bps. A diferença entre os resultados arredondados e os deltas publicados decorre exclusivamente da precisão dos insumos. Um bp equivale a 0,01 p.p.

## Regra por unidade e comparabilidade

| Tipo | Operação | Unidade e limites |
|---|---|---|
| Taxas e razões percentuais, inclusive cobertura acima de 100% | Atual − referência | Bps; se os valores internos são decimais, multiplicar a diferença por 10.000. Zero e taxas negativas permitem subtração. |
| Múltiplos de alavancagem | Atual − referência | x; preserva o sinal da diferença. |
| Montantes monetários | (Atual − referência) / referência × 100 | Crescimento relativo em %, com base positiva. Base zero ou negativa: N/D; diferença em valor disponível na memória. |
| Lucro YTD | Comparar janelas de igual duração | QoQ bloqueado; em Rankings, o acumulado exige o mesmo trimestre em anos distintos. |
| Ausência, componente inválido ou quebra de série já identificada | Sem delta numérico | Preservar N/D e a ressalva de comparabilidade. |

Pontos percentuais continuam adequados às séries macroeconômicas e SCR que os identificam explicitamente. A revisão mantém essa unidade nessas visões. Peers, Snapshot e os deltas de indicadores financeiros em Rankings usam bps para diferenças de taxas.

## Mudanças e revisão crítica

- Peers: duas casas nos níveis percentuais; QoQ como padrão das novas sessões; identificação QoQ/YoY e referência em cada cabeçalho. Seleções existentes de YoY permanecem identificadas.
- Memória de cálculo: valor atual, referência, operação, unidade e delta; JSON e Excel também conservam o delta numérico sem arredondamento.
- Excel, PowerPoint e PNG: referências de comparação nos cabeçalhos, coerentes com a interface.
- Snapshot: diferenças percentuais em bps; crescimento relativo com base positiva. A auditoria lê o texto efetivamente renderizado e verifica valor e unidade. Antes, recomputava a própria fórmula duas vezes, o que tornava a conferência ineficaz.
- Rankings: deltas de taxas em bps; rótulos distinguem crescimento relativo. Foram removidos percentuais infinitos representados por números artificiais e comparações YTD com janelas desiguais.
- Contas COSIF: saldo negativo preservado, diferença absoluta disponível e crescimento relativo N/D quando a referência é zero ou negativa. O quociente pela magnitude de uma base negativa foi removido.
- Carteira 4.966: o QoQ do total já media crescimento relativo do montante, com referência ao trimestre anterior e uma casa decimal. Essa operação é adequada ao saldo monetário; as participações são razões de nível, sem delta relativo sobre taxas.

## Evidência quantitativa

Uma conferência independente com `Decimal` cobriu os 26 indicadores do catálogo, 46 competências e Itaú, Bradesco e Santander no perímetro prudencial, nos modos QoQ e YoY: 7.176 células de comparação, 2.961 deltas calculáveis, nenhuma divergência numérica ou de sinal. As demais células ficaram bloqueadas: 3.981 por base N/D, 75 por quebra em 2025, 21 por base monetária ≤ 0 e 138 por janelas YTD diferentes.

O exercício valida as operações de variação sobre os insumos usados pela consulta nesses três bancos; a correção dos dados reportados e a qualidade de todas as instituições da base não foram reavaliadas nesse exercício. Testes de regressão cobrem todos os indicadores percentuais, as duas escalas de taxa, zero, sinais negativos, cobertura acima de 100%, múltiplos, referências QoQ/YoY e exports nativos.

Validação automatizada: 933 testes aprovados na suíte completa; 14 avisos preexistentes de depreciação de Matplotlib/Pyparsing. O dispatcher não apresentou rotas duplicadas. A tabela local confirmou a precisão dos níveis, a referência QoQ nos cabeçalhos e os resultados do Itaú acima.
