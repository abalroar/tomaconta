# Crédito BC — revisão editorial de 30/10/2026

Os 11 comentários de `data/comentarios_credito_bc.json` passam a apresentar
uma conclusão setorial, a evidência que a sustenta e suas implicações. As
competências e os dados permanecem os da publicação de 29/10/2026. A mudança
abrange os textos consumidos pela tela e pelas exportações.

## Fontes e escopo

- [BC, Estatísticas monetárias e de crédito, 29/10/2026](https://www.bcb.gov.br/content/estatisticas/hist_estatisticasmonetariascredito/202610_Texto_de_estatisticas_monetarias_e_de_credito.pdf): concessões com ajuste sazonal e explicação da sazonalidade de recebíveis.
- BCData/SGS, consulta de 30/10/2026: bundle `data/bundled/mercado_credito_sgs/dados.parquet`, registro de séries em `utils/sgs_credit_registry.py` e cálculos em `utils/sgs_credit_analytics.py`. Crédito e atrasos: setembro; situação das famílias: agosto.
- [Valor Econômico, “Endividamento renova recorde e pressiona mais a inadimplência”, 30/10/2026](https://valor.globo.com/financas/noticia/2026/10/30/endividamento-renova-recorde-e-pressiona-mais-a-inadimplencia.ghtml): texto integral fornecido pelo usuário. Complementa a interpretação com relatos sobre renda, inadimplência no consignado privado e discussão regulatória. Os argumentos são apresentados sem apelos a cargos ou autoridade pessoal.
- SCR.data: recorte da página por renda em julho/2026, sem atualização nesta revisão. Relatos de outubro não são apresentados como observação do SCR de setembro.
- BC, nota de 13/03/2025, já referenciada pelo comentário anterior: mudança contábil de janeiro/2025 na série de provisões.

A análise é de agregados setoriais, sem comparação de instituições ou
conglomerados individuais. Estoques em R$ milhões no arquivo; percentuais em
escala 0–100. O inventário da skill apontou ausência de caches IFData no
worktree; a análise usa exclusivamente o bundle SGS validado e as fontes
acima, sem dependência dessas métricas institucionais.

## Evidências materiais e classificação

| Página | Evidência | Status e interpretação |
|---|---|---|
| Concessões | Total -1,3%, PJ -3,4%, PF +0,6% no mês, dessazonalizados | Reportado pelo BC; perda de força da originação e pressão sobre retorno após perdas são inferências. Refinanciamento é uma composição possível, sem participação estimada. |
| Estoque | R$ 7,444 tri; crescimento nominal anual 8,63% versus 9,42% em agosto; livre PJ 1,22%; direcionado 11,53% | Calculado das séries de saldo. Estoque SFN soma PF e PJ; não equivale a crédito ampliado. A necessidade de melhora de renda e preço é interpretação do ciclo. |
| Tomador | PF +0,09% no mês e +5,09% real anual; PJ +1,01% e +1,89% | Calculado. Inflação pelo IPCA e mesma função dos gráficos. A concentração da pressão de perdas em PF é inferência sustentada pelos atrasos livres. |
| Produto | NPL cartão total 10,04%, pessoal sem consignação 11,06%, veículos 6,76%; giro PJ 6,01%, duplicatas 0,80%; saldos consignado privado +1,57%, duplicatas +10,43% | SGS e cálculos mensais. NPL consignado privado 10,8% vem da reportagem fornecida, explicitamente atribuído a ela; não equivale aos 3,84% do consignado agregado no SGS. Diferenças entre produtos não isolam causalmente o efeito das garantias. |
| Porte | MPMe -0,405% no mês e +0,74% real anual; grandes +1,460% e +1,85%; MPMe R$ 1.326,428 bi, 47,9% | Calculado. Participação usa a soma dos dois portes, que tem perímetro próprio. Restrição de oferta e fraqueza da demanda são explicações alternativas. |
| Controle | Variação mensal: privadas nacionais +0,980%, públicas +0,012%, estrangeiras -0,120%; real anual 4,87%, 3,08%, 3,04%; participações 45,2%, 41,4%, 13,3% | Calculado com denominador igual à soma dos controles. Sustentação futura por bancos públicos é cenário, não aceleração observada em setembro. |
| Famílias | Endividamento 50,11% da renda anual; serviço 28,99% da renda mensal; juros 10,92% | SGS; serviço calculado como juros 10,92 + amortização 18,07. Recordes também reportados pela notícia fornecida. Não somar endividamento e serviço. Transmissão de enfraquecimento do emprego para atrasos é cenário condicionado. |
| Atrasos | Total 5,05→4,98%; livre PF 8,03→8,09%, ante 6,89% em set/25; livre PJ 4,34→4,16%; 15–90 dias PF 4,49→4,72%, PJ 2,80→2,59% | Reportado no SGS e diferença anual calculada de 1,20 p.p. O arredondamento da notícia para 5,0% não elimina a pequena queda do total. Atrasos curtos não comprovam migração das mesmas operações. |
| Provisões | Provisões/carteira 8,1→7,9%; cobertura 160,4→158,6% | Cobertura = provisão% / inadimplência% × 100: 8,1/5,05 e 7,9/4,98. Estoque não é despesa. Menor proteção relativa não demonstra insuficiência ou antecipa valor de provisões futuras. |
| Renda | Relatos de pressão na baixa renda e sinais na renda média | Reportado pela notícia; evidência qualitativa, sem extrapolar para distribuição setorial comprovada de setembro. Jul/26 continua sendo a competência SCR da página. |
| Taxas | PF livre 61,76→62,35% a.a.; spread 47,58→48,48 p.p.; rotativo 451,71% a.a.; PJ livre 24,37% a.a. | SGS. Selic média 13,94→13,78% a.a. no mesmo intervalo. Movimento das médias também reflete mix; nenhum efeito causal quantitativo foi estimado. |

Variação mensal = saldo(t)/saldo(t−1)−1; anual nominal =
saldo(t)/saldo(t−12)−1; anual real = variação da razão entre saldo e índice
IPCA em 12 meses. A memória numérica da atualização permanece em
`outputs/credito-sfn-2026-10-30/indicators.json` e `revisions.csv`.

## Decisões editoriais e limites

- Cada comentário tem dois parágrafos: tese e evidência, seguidos da consequência setorial e dos condicionantes materiais.
- Metodologia permanece apenas quando evita uma conclusão errada: datas distintas no recorte de renda, mix nas taxas e diferença entre estoque de provisões e despesa.
- Desaceleração futura, emprego e novas exigências prudenciais aparecem como cenários. A discussão de FPR para cartões não é tratada como norma aprovada; não se afirma obrigação, vigência ou requisito regulatório específico.
- A reportagem informa restrições anunciadas à oferta ativa. O comentário usa essa informação contextual, sem emitir conclusão jurídica ou extrapolar seu alcance operacional.
- Não são incorporadas projeções de Selic, recomendações sobre ações, comparações de bancos com perímetros distintos ou explicações político-partidárias.
- O arrefecimento em PJ, a expansão por privadas nacionais e o peso do mix nas taxas constituem contrapontos factuais à tese de deterioração uniforme.

## Validação

A revisão usa os testes existentes de comentários, dados, legibilidade e
exportação. A conferência pública deve comparar os 11 textos do JSON
baixado pela aplicação com o arquivo versionado, além de inspecionar a
renderização dos parágrafos na tela.
