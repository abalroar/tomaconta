# Carteira 4.966: variações e leitura de crédito

A tabela passa a mostrar QoQ em cada componente, usando o trimestre imediatamente anterior, inclusive quando ele não está selecionado. A fonte de PDD (IFData Rel. 2) é carregada também para essas referências. A classificação e seus percentuais mantêm a base comum escolhida entre os períodos exibidos; a referência usa esse mesmo denominador.

| Componente | Operação | Exibição | Leitura da cor |
|---|---|---|---|
| Saldos de carteira, categorias, vencidos e PDD | `(atual − referência) / referência × 100`; base positiva | % com duas casas | Neutra |
| Percentuais da classificação sobre a base comum | Percentual atual − percentual de referência | p.p. com uma casa | Neutra |
| Vencidos >90 dias (arrasto) / carteira total | Diferença dos percentuais × 100 | bps inteiros | Alta vermelha; queda verde |
| PDD / carteira total | Diferença dos percentuais × 100 | bps inteiros | Neutra: aumento pode refletir reforço de provisões ou piora de risco |
| PDD / C5 e PDD / vencidos >90 dias | Percentual atual − percentual de referência | p.p. com uma casa | Alta verde; queda vermelha |

Níveis percentuais mantêm duas casas. Cálculos preservam a precisão dos insumos. Movimentos que arredondariam a zero conservam direção com `<1 bp`, `<0,1 p.p.` ou `<0,01%`. Ausência de dados, referência monetária não positiva e a transição anterior a mar/2025 bloqueiam o delta. A referência é o trimestre anterior exato; lacunas não são preenchidas com o último período disponível.

A PDD soma e2 + f2 + g2 + h2 do Rel. 2, sem hedge e ajustes de valor justo. O denominador dos vencidos é o saldo integral das operações em arrasto do Rel. 16. As coberturas usam PDD total e são aproximações; a cor indica a direção usual do indicador e deve ser lida com seus componentes. Alertas na data atual ou na referência mantêm os valores auditáveis e neutralizam a cor, com marca e diagnóstico.

Os dois downloads Excel usam o mesmo cálculo e a mesma paleta. O modelo visual mantém níveis como números nativos e inclui uma linha de variação por indicador. A folha **Variações**, presente em ambos os arquivos, conserva valores atuais, referências, delta numérico completo, unidade, exibição, cálculo e status. Os dados brutos incluem os períodos de referência.

## Acabamento visual

| Before | After | Why |
|---|---|---|
| Barras cinzas de 2px entre bancos em Peers | Espaço branco de 5px e linhas internas mais leves | Mantém os grupos reconhecíveis com menor peso visual |
| Cabeçalhos contíguos e retos | Cantos superiores discretamente arredondados por banco | Facilita reconhecer os grupos no cabeçalho |
| Cabeçalho da Carteira 4.966 fora da tela ao ler coberturas | Cabeçalho fixo, data acima da referência QoQ e área com rolagem | Conserva datas e unidades junto aos indicadores |

## Conferência

Conferência independente com Decimal sobre os insumos publicados: Itaú, Bradesco e Santander; 13 linhas, seis competências de mar/2025 a jun/2026; 396 componentes comparados, 322 deltas calculáveis, 66 bloqueios na transição de 2025 e oito referências monetárias não positivas. Nenhuma divergência de cálculo, unidade ou sinal.

No Itaú, Mar/26 contra Dez/25: vencidos/carteira 2,18% → 2,25%, **+7 bps**; PDD/vencidos 197,11% → 193,54%, **−3,6 p.p.**. A conferência valida os deltas sobre os insumos e não representa uma nova validação de toda a informação reportada ao BCB.

Validação automatizada: 958 testes passaram, incluindo regressões de escala, referências não exibidas, lacunas trimestrais, zero versus N/D, alertas na referência e consistência entre HTML e os dois arquivos Excel. Avisos de Matplotlib/Pyparsing já existentes.
