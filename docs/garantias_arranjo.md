# Garantias de Arranjo

Menu **Garantias de Arranjo**: uma linha por conglomerado prudencial, com obrigações em
arranjos de pagamento, títulos dados em garantia e a razão Garantia / Obrigações, mês a mês.

## Fórmula

| Papel | Conta COSIF | Nome |
|---|---|---|
| Obrigações | 4.4.1.60 | Transações de pagamento (relações interfinanceiras) |
| Obrigações | 4.9.9.01 | Obrigações por transações de pagamento |
| Obrigações | 4.9.9.03 | Obrigações por serviços de instituidores de arranjo |
| Garantia | 1.3.6.16 | Títulos dados em garantia em arranjo de pagamento |
| Garantia opcional | 1.3.6.15 | Títulos dados em garantia em câmaras de liquidação |
| Memória, fora da razão | 3.0.9.77 | Garantias em arranjos de pagamento (conta de controle) |

`Garantia / Obrigações = 1.3.6.16 (+ 1.3.6.15, se marcado) ÷ (4.4.1.60 + 4.9.9.01 + 4.9.9.03)`

- Fonte: balancete prudencial, documento 4060, mensal.
- A razão não é calculada com obrigações abaixo de R$ 1 milhão.
- 1.3.6.15 é opcional porque há quem registrasse ali o colateral do arranjo antes de migrar
  para 1.3.6.16 (Afinz, até jan/2026). Em bancos com operações em bolsa, ela é margem de câmara.
- 3.0.9.77 existe desde fev/2026 e poucas instituições a preenchem; fica como conferência.

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

Para mudar a fórmula, edite `COMPONENTS` em `utils/arranjo_garantias.py`. O teste
`test_bundled_base_has_every_account_of_the_formula_and_reproduces_afinz` falha se uma conta
da fórmula sumir do mês mais recente, o que sinaliza renumeração do COSIF.

## Limites de leitura

- O balancete não identifica a bandeira beneficiária da garantia.
- Fiança ou carta de crédito emitida por outro banco não aparece no balanço de quem a contrata.
- A visão prudencial elimina saldos entre empresas do grupo. A obrigação de uma instituição
  isolada (documento 4010) pode ser bem maior; na Afinz IP, quase três vezes.
