# Garantias de Arranjo

Menu **Garantias de Arranjo**: uma linha por conglomerado prudencial, com obrigações em
arranjos de pagamento, títulos dados em garantia e a razão Garantia / Obrigações, mês a mês.

## Fórmula

| Papel | Conta COSIF | Nome |
|---|---|---|
| Obrigações | 4.4.1.60 | Transações de pagamento (relações interfinanceiras) |
| Obrigações | 4.9.9.01 | Obrigações por transações de pagamento |
| Obrigações | 4.9.9.03 | Obrigações por serviços de instituidores de arranjo |
| Garantias - Arranjo de Pagamento (padrão) | 1.3.6.16 | Títulos dados em garantia em arranjo de pagamento |
| Garantia - Outros (opcional) | 1.3.6.20 | Títulos dados em garantia - outros |
| Garantia - Câmaras de Liquidação (opcional) | 1.3.6.15 | Títulos dados em garantia em câmaras de liquidação |
| Memória, fora da razão | 3.0.9.77 | Garantias em arranjos de pagamento (conta de controle) |

`Garantia / Obrigações = soma das fontes escolhidas ÷ (4.4.1.60 + 4.9.9.01 + 4.9.9.03)`

- Fonte: balancete prudencial, documento 4060, mensal.
- A razão não é calculada com obrigações abaixo de R$ 1 milhão.
- 1.3.6.15 é opcional porque há quem registrasse ali o colateral do arranjo antes de migrar
  para 1.3.6.16 (Afinz, até jan/2026). Em bancos com operações em bolsa, ela é margem de câmara.
- 1.3.6.20 é residual: pode incluir, ou não, a garantia do arranjo. A razão com ela é um teto.
  Em jun/2026, entre os 72 conglomerados com obrigações de ao menos R$ 1 milhão, 17 têm saldo em
  1.3.6.16 e 45 em 1.3.6.16 ou 1.3.6.20 (28 só em 1.3.6.20, como o PicPay).
- 3.0.9.77 é conta de compensação: a própria instituição informa o total de garantias prestadas
  em arranjos, fora do ativo e do passivo. Existe desde fev/2026 e 13 conglomerados a preenchem;
  zero significa sem registro. Onde há saldo em 1.3.6.16 ela costuma repetir o mesmo valor; onde só
  há 1.3.6.20 (Mercado Pago, C6), indica a parcela de "Outros" ligada ao arranjo. Fica fora da razão.
- O nome da fonte escolhida aparece no cabeçalho da coluna e na frase acima da tabela; o botão
  "i" ao lado do seletor descreve a conta, a origem e o cálculo.

## Exportação

"Exportar obrigações (Excel)" gera uma tabela nativa, uma linha por instituição da tela, em
R$ milhões: as três contas de obrigação, o total, as rubricas de garantia, a conta de controle e a
razão. Calibri, cabeçalho laranja com texto branco em negrito 14, linhas 12 sem preenchimento.

## Desde quando

Janeiro de 2025. O arquivo público do BCB só abre o quarto nível do COSIF a partir dessa
competência; antes, 4.4.1 e 1.3.6 vêm agregados e não isolam o arranjo.

## Onde os dados ficam

Não há cache próprio. A tela lê `data/bundled/bloprudencial/dados.parquet` (ou a revisão
oficial ativa), filtra as seis contas e calcula na hora; o resultado fica em memória,
com chave no conteúdo do parquet. Cerca de 3,4 mil linhas, menos de um segundo.

## Atualização

Atualizar o balancete prudencial em **Atualizar Base** basta: o mês novo aparece no painel
sem outra etapa, sem derivação e sem publicação adicional.

Para mudar a fórmula, edite `COMPONENTS` e `SOURCES` em `utils/arranjo_garantias.py`. O teste
`test_bundled_base_has_every_account_of_the_formula_and_reproduces_afinz` falha se uma conta
da fórmula sumir do mês mais recente, o que sinaliza renumeração do COSIF.

## Limites de leitura

- O balancete não identifica a bandeira beneficiária da garantia.
- Fiança ou carta de crédito emitida por outro banco não aparece no balanço de quem a contrata.
- A visão prudencial elimina saldos entre empresas do grupo. A obrigação de uma instituição
  isolada (documento 4010) pode ser bem maior; na Afinz IP, quase três vezes.
