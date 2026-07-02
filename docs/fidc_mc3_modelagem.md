# Relatorio executivo - Modelagem FIDC MC3

Data da rodada: 2026-06-21
Workspace: `/Users/matheusjprates/tomaconta`

## 1. Diagnostico

O workspace atual nao contem o motor FIDC identificado no diagnostico anterior (`services/fidc_model`, `model_data.json`, aba Modelo FIDC etc.). A base local e um app Streamlit monolitico (`app1.py`) com modulos de IF.data, caches, rating, DRE/COSIF e estudos de capital/PL/LL.

Referencias a "Mercado Credito" aparecem apenas em metadados cacheados (`data/bundled/critical_screens/metadata.json`). Nao havia arquivo de premissas oficiais, planilha baseline ou output historico especifico de FIDC MC3 para preservar.

Por isso, a melhoria foi implementada como uma camada nova, isolada e auditavel de modelagem FIDC MC3, sem alterar o app existente, sem tocar nos dados originais e sem sobrescrever os outputs que ja estavam modificados no inicio da rodada.

## 2. Mudancas realizadas

1. `pytest.ini`
   - Explicitou `pythonpath = .`.
   - Fixou os caminhos de teste ja coletados no baseline: `tests` e `utils/ifdata_cache/test_cache.py`.

2. `fidc_mc3/`
   - Criado pacote puro de modelagem:
     - `contracts.py`: dataclasses de premissas, tranches, periodos e resultado.
     - `rates.py`: conversao de taxas anuais/mensais e IRR mensal anualizada.
     - `engine.py`: projecao mensal com coortes de recebiveis, perdas, recuperacao, caixa, fees, juros, reinvestimento, amortizacao e residual SUB.
     - `validation.py`: validacoes de premissas e outputs.
     - `io.py`: carga de cenario JSON e exportacao CSV/JSON.

3. `data/fidc_mc3/mc3_base_case.json`
   - Cenario MC3 base para fixture tecnico.
   - O arquivo declara que nao substitui premissas aprovadas por comite nem baseline economico externo.

4. `tools/run_fidc_mc3_model.py`
   - Runner CLI para executar a projecao, validar e gerar artefatos.

5. `tests/test_fidc_mc3_model.py`
   - Testes de invariantes economicos e auditabilidade.

6. `outputs/fidc_mc3/latest/`
   - Artefatos gerados localmente pelo runner:
     - `projection.csv`
     - `summary.json`
     - `tranche_cashflows.json`
     - `validation.json`

## 3. Mecanica implementada

O motor mensal segue a ordem:

1. coleta de principal, juros dos recebiveis, recuperacoes e rendimento de caixa;
2. pagamento de despesas;
3. pagamento de juros SEN/MEZZ por senioridade;
4. reinvestimento durante a revolvencia, limitado por caixa disponivel e alvo de carteira;
5. amortizacao de principal das cotas de passivo apos a revolvencia, por senioridade;
6. distribuicao residual para SUB quando as cotas de passivo estiverem quitadas.

O modelo reconcilia:

- principal adquirido inicial + reinvestimentos;
- principal programado recebido/defaultado;
- carteira final;
- caixa disponivel vs. usos do waterfall;
- saldo de cotas SEN/MEZZ e NAV residual SUB;
- subordinação minima;
- perda liquida = principal defaultado x (1 - recuperacao).

## 4. Resultado do cenario tecnico MC3

Runner:

```bash
.venv/bin/python tools/run_fidc_mc3_model.py --output-dir outputs/fidc_mc3/latest
```

Resumo do output:

- Funding inicial: R$ 98,5 mi.
- Preco de aquisicao inicial: R$ 96,5 mi.
- Reserva inicial de caixa: R$ 2,0 mi.
- Principal total adquirido, incluindo reinvestimento: R$ 560,1 mi.
- Gap de reconciliacao de principal: R$ 0,00.
- Principal defaultado total: R$ 10,1 mi.
- Recuperacoes totais: R$ 2,0 mi.
- Perda liquida total: R$ 8,1 mi.
- Receita de juros dos recebiveis: R$ 45,4 mi.
- Menor subordinação: 20,23%.
- Brechas de subordinação: 0.
- IRR anual estimada:
  - SEN: 12,6417%.
  - MEZZ: 15,62925%.
  - SUB: 189,1167%.

Observacao: a IRR alta de SUB e consequencia do fixture tecnico, do desconto/yield e da alavancagem adotados para exercitar o motor. Nao deve ser interpretada como recomendacao economica sem premissas oficiais do FIDC MC3.

## 5. Testes e checks

Baseline antes das mudancas:

```bash
.venv/bin/python -m pytest -q
```

Resultado: 167 passed, 19 warnings existentes.

Depois de `pytest.ini`:

```bash
.venv/bin/python -m pytest -q
```

Resultado: 167 passed, mesmos warnings.

Testes novos:

```bash
.venv/bin/python -m pytest -q tests/test_fidc_mc3_model.py
```

Resultado: 7 passed.

Suite completa apos a camada FIDC MC3:

```bash
.venv/bin/python -m pytest -q
```

Resultado: 174 passed, 19 warnings antigos.

Validacao do runner:

```bash
.venv/bin/python tools/run_fidc_mc3_model.py --output-dir outputs/fidc_mc3/latest
```

Resultado: exit code 0 e `outputs/fidc_mc3/latest/validation.json` vazio (`[]`).

## 6. Impacto nos resultados existentes

Nao houve mudanca no `app1.py`, nos modulos de rating/IF.data, nos dados brutos existentes ou nos outputs materiais ja presentes no repo.

No inicio da rodada ja existiam alteracoes em:

- `outputs/pl_ll_simple_2026/excel/estudo_pl_ll_simplificado_dez25_mar26.xlsx`
- `outputs/pl_ll_simple_2026/presentations/simple-study/output/estudo_pl_ll_simplificado_dez25_mar26.pptx`

Esses arquivos foram preservados sem reversao.

Durante a execucao da suite apareceram side effects em cache (`data/cache/capital/*` e `data/dev_hours_cache.json`). Eles foram restaurados para evitar misturar efeitos de teste com a modelagem FIDC MC3.

## 7. Riscos remanescentes

- Ainda nao ha baseline economico oficial do FIDC MC3 neste workspace.
- O cenario JSON atual e fixture tecnico, nao premissa aprovada por comite.
- A estrutura de waterfall e limpa e limitada por caixa, mas ainda e uma aproximacao mensal deterministica; nao substitui analise contrato-a-contrato.
- Nao ha integracao visual no Streamlit para a nova camada FIDC MC3.
- A suite existente possui warnings antigos em `utils/ifdata_cache/test_cache.py` porque alguns testes retornam `bool` em vez de usar `assert`.

## 8. Proximas recomendacoes

1. Adicionar premissas oficiais do FIDC MC3 como novo JSON baseline, preservando o fixture tecnico.
2. Comparar a saida do motor com a planilha ou memoria de calculo oficial assim que ela for adicionada.
3. Criar cenarios de stress: menor yield, maior default, recuperacao atrasada, stop de revolvencia e quebra de subordinação.
4. Integrar a camada `fidc_mc3` em uma aba Streamlit apenas depois de fechar a reconciliacao com o baseline oficial.
5. Corrigir warnings antigos da suite de cache em uma rodada separada.
