# Investigação técnica — Perda Esperada / Estágio 3 (BB, Set/25)

## Escopo
Investigar **somente** a origem e unidade do numerador/denominador no cálculo de `Perda Esperada / Estágio 3`, sem aplicar correção funcional nesta etapa.

## Resultado principal (causa provável)
- O cálculo da razão é feito em `app1.py` por `_calcular_ratio_peers(perda_esperada, estagio3_mes)`.
- **Não existe conversão de escala de exibição** (`/1000`, `/1e6`, `*1000`) aplicada ao denominador antes da divisão nesse fluxo.
- O denominador é lido de `SALDO/VALOR` do cache BLOPRUDENCIAL e usado como `float` bruto.
- Portanto, o sintoma `-546,39%` **não** é explicado por “usar 174,6 formatado no lugar do bruto” dentro dessa função.
- A divergência é mais compatível com seleção incorreta da linha/fonte do Estágio 3 (matching de instituição no BLOPRUDENCIAL), com inconsistência da base carregada, **ou** com eventual diferença de unidade nativa (R$ unidade vs R$ mil) entre fontes.

## Evidências no código

### 1) Onde a razão é calculada
- Função `_preparar_metricas_extra_peers`:
  - Numerador: `perda_esperada = _somar_valores(perda_vals)`.
  - Denominador: `estagio3_mes = _blop_get_sum_periodo_conta(..., "3313000000")`.
  - Razão: `extra["Perda Esperada / Estágio 3"] = _calcular_ratio_peers(perda_esperada, estagio3_mes)`.

### 2) Como o denominador é extraído
- `_blop_get_sum_periodo_conta` retorna `float(val_cod)`/`float(val)` diretamente de `blop_lookup`/`blop_lookup_cod`.
- `blop_lookup` é preenchido com `_saldo` (`pd.to_numeric` da coluna `SALDO/VALOR`) sem escala adicional.

### 3) Como a razão é usada no Snapshot
- Snapshot chama a mesma função `_preparar_metricas_extra_peers` e usa `extra_snapshot["Perda Esperada / Estágio 3"]`.
- Ou seja, Snapshot e Peers compartilham a mesma fonte de cálculo para essa métrica.

### 4) Sobre unidades
- O pipeline de extração IFData documenta moedas “em reais” no extrator.
- O loader BLOPRUDENCIAL carrega `SALDO` bruto e converte para numérico sem escala adicional no app.
- **Ponto em aberto para V1**: confirmar na fonte oficial Cadoc 4060 se o `SALDO` deve ser interpretado como R$ unidade ou R$ mil para a conta `3313000000`.

## Respostas objetivas solicitadas

a) Unidade nativa de **Perda Esperada** no ponto da divisão:
- Valor monetário bruto (reais), vindo do cache de Ativo (Rel. 2), sem escala de exibição aplicada no cálculo.

b) Unidade nativa de **Estágio 3** no ponto da divisão:
- Valor monetário bruto (como carregado de `SALDO/VALOR` do BLOPRUDENCIAL, conta `3313000000`), sem escala de exibição aplicada no cálculo.

c) Vêm da mesma fonte?
- Não. São fontes diferentes:
  - Numerador: cache de Ativo (Rel. 2 / IFData).
  - Denominador: cache BLOPRUDENCIAL (Cadoc 4060).

d) Há conversão de escala aplicada só a um deles antes da divisão?
- No trecho investigado, não.

e) O Estágio 3 do Snapshot e da aba Peers vêm do mesmo campo usado como denominador?
- Sim. Ambos vêm do `extra["Ativos Estágio 3"]` preenchido por `_blop_get_sum_periodo_conta(..., "3313000000")` dentro de `_preparar_metricas_extra_peers`.

## Observação crítica
Como não há escala de exibição entrando no cálculo, a hipótese mais forte segue sendo de **matching de instituição/linha BLOPRUDENCIAL** (ou base inconsistente no cache), especialmente pelo fallback textual em `_blop_get_sum_periodo_conta` quando falha o match por código estável. Em paralelo, deve-se eliminar a dúvida de unidade nativa do Cadoc 4060 para a conta analisada.

## Próximo passo V1 (obrigatório antes de fix)
1. Logar, para `BB` e `Set/25`, qual caminho resolveu o denominador em `_blop_get_sum_periodo_conta`:
   - match por `COD_CONGL`,
   - match por nome,
   - ou fallback textual.
2. Logar a entidade efetivamente selecionada (`inst_key`/`COD_CONGL`) e o `SALDO` bruto usado na conta `3313000000`.
3. Confirmar documentalmente a unidade nativa do Cadoc 4060 para esse `SALDO` (R$ unidade ou R$ mil).
4. Só então comparar unidade do numerador e denominador no mesmo período para fechar causa-raiz.

## Prompt recomendado para o Codex (fix)
> Investigue o bug de `Perda Esperada / Estágio 3` (BB, Set/25) com dois objetivos simultâneos, antes de alterar regra de negócio:
>
> 1. **Matching/entidade escolhida**
>    - Instrumente `_blop_get_sum_periodo_conta` para logar, no caso BB Set/25 conta `3313000000`, se o valor veio de `COD_CONGL`, nome exato ou fallback textual.
>    - Logue também qual entidade foi escolhida (`COD_CONGL`, `inst_key`) e o `SALDO` bruto retornado.
>
> 2. **Unidade nativa do Cadoc 4060**
>    - Confirme na documentação/fonte oficial do Cadoc 4060 se o `SALDO` dessa conta está em **R$ unidades** ou **R$ mil**.
>    - Conclua explicitamente se há ou não mismatch de 1.000× com o numerador (Rel. 2).
>
> Entregue o diagnóstico final respondendo:
> - valor bruto exato usado no denominador;
> - entidade que originou esse valor;
> - unidade nativa confirmada do Cadoc 4060;
> - se o erro é de matching, unidade, ou ambos.
