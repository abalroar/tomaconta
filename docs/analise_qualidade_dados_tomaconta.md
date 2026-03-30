# Análise de Qualidade de Dados — TomaConta
**Data:** 2026-03-30
**Autor:** Análise automatizada (Claude)
**Status:** Pendente de validação manual

---

## Resumo Executivo

Análise ampla e relacional de inconsistências nos dados apresentados e calculados no TomaConta, cobrindo o pipeline inteiro: **extração** (`extractor.py`) → **recálculo** (`app1.py` / `recalcular_metricas_derivadas`) → **exibição por aba** (Snapshot, Rankings, Peers, Evolução, Scatter).

Foram encontradas **7 inconsistências cross-tab confirmadas** e **4 problemas menores**.

---

## INCONSISTÊNCIAS CRÍTICAS (cross-tab)

### 1. ROE: fórmula diferente no extrator vs app principal
**Severidade: 🔴 ALTA**

| Local | Fórmula | Arquivo:Linha |
|-------|---------|---------------|
| Extrator (extração inicial) | `LL / PL × fator` (PL corrente, sem média) | `extractor.py:480-484` |
| App (recálculo) | `(LL × fator) / ((PL_t + PL_dez_anterior) / 2)` (PL médio) | `app1.py:1067-1081` |

O extrator calcula ROE usando apenas o PL corrente. O `recalcular_metricas_derivadas` sobrescreve com PL médio. Se por qualquer razão o recálculo não rodar (ex: faltar PL de dezembro anterior), o valor do extrator fica exposto — e está errado.

**Impacto**: Rankings, Evolução e Scatter podem mostrar ROE sem PL médio se dados de dezembro não estiverem disponíveis.

---

### 2. ROE Trimestral em escala 0-100, ROE Acumulado em escala 0-1
**Severidade: 🔴 ALTA**

| Métrica | Escala interna | Arquivo:Linha |
|---------|---------------|---------------|
| ROE Ac. Anualizado (%) | 0-1 (decimal) | `app1.py:1081` |
| ROE trimestral anualizado (%) | 0-100 (percentual) | `app1.py:3795` |

`_recalcular_roe_trimestral_df` (linha 3795) faz:
```python
roe_tri = ll_anualizado / pl_medio.where(pl_medio > 0, np.nan) * 100
```

Já `_calcular_roe_anualizado` (linha 1081) retorna decimal puro. Ambos estão em `VARS_PERCENTUAL` (que multiplica por 100 para display). **Resultado: ROE trimestral pode aparecer como 2000% em vez de 20%.**

---

### 3. Crédito/PL usa bases de crédito diferentes across tabs
**Severidade: 🔴 ALTA**

| Local | Numerador | Fonte | Arquivo:Linha |
|-------|-----------|-------|---------------|
| Extrator | "Carteira de Crédito" | Rel. 1 (classificada, líquida) | `extractor.py:506-512` |
| Recálculo app | "Carteira de Crédito Bruta" c/ fallback | Rel. 2 → Rel. 1 | `app1.py:1180-1186` |
| Snapshot | Soma e1+f1+g1+h1 | Rel. 2 (bruta) | `app1.py:6134-6160` |
| Peers | "Carteira de Crédito Bruta / PL" c/ fallback | Merged | `app1.py:883` |

**"Carteira de Crédito" (Rel. 1) ≠ "Carteira de Crédito Bruta" (Rel. 2)**. A bruta inclui provisões. Os valores divergem significativamente para bancos com alta inadimplência.

---

### 4. Basileia: tripla normalização causa instabilidade de escala
**Severidade: 🔴 ALTA**

O Índice de Basileia passa por até **3 camadas** de normalização:

1. **Extrator** (`extractor.py:517-522`): `if abs(valor) > 1 → /100`
2. **Recálculo** (`app1.py:1210-1218`): `_normalizar_indice_para_decimal` (mesma lógica)
3. **Scatter** (`app1.py:3061-3098`): `_ajustar_basileia_para_scatter` — hack para detectar dupla divisão

A existência do hack no Scatter (`if q95 < 0.03 and med < 0.02 → ×100`) **confirma que a dupla divisão aconteceu em produção**. Isso é um sintoma, não uma correção robusta.

---

### 5. Core Funding ≠ Captações — rename semântico incorreto
**Severidade: 🟡 MÉDIA**

```python
# app1.py:1115
'Crédito/Captações (%)': 'Carteira de Crédito/Core Funding (%)'
```

O rename trata "Captações" e "Core Funding" como sinônimos, mas:
- **Captações** = Depósitos + letras (Rel. 1)
- **Core Funding** = Captações + Dívida Subordinada (Rel. 3, a partir de 2025)

O recálculo (linha 1189) usa "Core Funding" como denominador. Mas se "Core Funding" não existir no DataFrame, a coluna herdada de "Crédito/Captações (%)" do extrator usa "Captações" do Rel. 1 — denominadores diferentes silenciosamente.

---

### 6. Snapshot vs demais abas: fontes de dados diferentes
**Severidade: 🟡 MÉDIA**

| Métrica | Snapshot | Peers/Rankings/Evolução/Scatter |
|---------|----------|---------------------------------|
| Carteira de Crédito Bruta | Rel. 2 (componentes e1+f1+g1+h1) | Rel. 1 "Carteira de Crédito" ou merged Rel. 2 |
| Índice de Basileia | Rel. 5 (Capital) direto | Rel. 1 (Principal) merged com Rel. 5 |
| CET1 | Rel. 5 (Capital) direto | Merge capital → principal |

Quando o merge de capital falha (nome de instituição não match), Peers/Rankings mostram Basileia do Rel. 1, enquanto Snapshot mostra do Rel. 5. Estes podem diferir.

---

### 7. Proliferação de aliases de colunas
**Severidade: 🟡 MÉDIA**

| Conceito | Nomes usados no código |
|----------|------------------------|
| ROE | `ROE An. (%)`, `ROE Ac. YTD an. (%)`, `ROE Ac. Anualizado (%)`, `ROE trimestral anualizado (%)` |
| Crédito/PL | `Crédito/PL`, `Crédito/PL (%)`, `Carteira de Crédito Bruta / PL`, `Carteira de Crédito / PL`, `Carteira de Crédito* / PL` |
| Crédito/Captações | `Crédito/Captações (%)`, `Carteira de Crédito/Core Funding (%)` |
| Basileia | `Índice de Basileia`, `Índice de Basileia Total`, `Índice de Basileia (n) = (e)/(j)` |

A cada ponto de fallback (`data_keys` arrays), há risco de pegar o valor errado ou um valor stale.

---

## PROBLEMAS MENORES

### 8. Senha admin hardcoded
**Severidade: 🔴 SEGURANÇA**

`app1.py:742`: `SENHA_ADMIN = "m4th3u$987"` — senha em texto plano no código-fonte.

### 9. Fallback silencioso quando mês é None
**Severidade: 🟢 BAIXA**

`app1.py:1143-1144`: Se `_extrair_mes_periodo` retorna None, assume `mes = 12`. Correto apenas para dezembro; para qualquer outro período com formato malformado, o ROE fica errado silenciosamente.

### 10. "Índice de Basileia Total" no Peers com data_keys vazio
**Severidade: 🟢 BAIXA**

`app1.py:892-894`: A linha "Índice de Basileia Total" no Peers tem `data_keys: []`. O nome no DataFrame é "Índice de Basileia" (sem "Total"). Pode não encontrar valor.

### 11. "Ativo Total / PL" marcado como TODO
**Severidade: 🟢 BAIXA**

`app1.py:879`: `"todo": "TODO: Integrar Ativo/PL a partir das fontes do projeto"` — métrica declarada mas sem implementação.

---

## CHECKLIST DE VALIDAÇÃO MANUAL

Antes de implementar correções, verifique manualmente:

- [ ] **ROE divergente cross-tab**: Compare ROE do Itaú em Q1/2024 entre Snapshot, Rankings e Scatter. Se divergirem → confirma #1
- [ ] **ROE trimestral escala errada**: Na Evolução, compare "ROE trimestral anualizado (%)" com "ROE Ac. Anualizado (%)". Se o trimestral estiver ~100x maior → confirma #2
- [ ] **Carteira de Crédito Bruta divergente**: Compare "Carteira de Crédito\*" no Snapshot (Rel. 2) com "Carteira de Crédito" nos Rankings (Rel. 1) para o BB. Deve haver diferença material → confirma #3
- [ ] **Basileia no Scatter**: Se pontos mostram ~0.16 (16%) → OK. Se ~0.0016 → confirma #4
- [ ] **Core Funding vs Captações**: Para Nubank, compare denominador de "Crédito/Captações" nos Rankings com "Crédito/Core Funding" no Peers → confirma #5
- [ ] **Basileia Peers vs Snapshot**: Escolha IF onde merge pode falhar (cooperativa). Se Peers e Snapshot divergem → confirma #6
- [ ] **Senha**: Confirme se `SENHA_ADMIN` no repo é intencional → confirma #8

---

## PROMPT CODEX

Cole este prompt no Codex para implementar as correções após validação:

```
Corrija as seguintes inconsistências no TomaConta, na ordem de prioridade.
O projeto é um app Streamlit em /home/user/tomaconta/.

### A. Unificar escala do ROE trimestral (CRÍTICO)
Em `app1.py`, função `_recalcular_roe_trimestral_df` (~linha 3795):
- Remover o `* 100` do cálculo:
  `roe_tri = ll_anualizado / pl_medio.where(pl_medio > 0, np.nan) * 100`
  deve virar:
  `roe_tri = ll_anualizado / pl_medio.where(pl_medio > 0, np.nan)`
- O resultado deve ficar em escala decimal (0-1), consistente com `_calcular_roe_anualizado`

### B. Unificar fórmula do ROE no extrator (CRÍTICO)
Em `utils/ifdata_cache/extractor.py`, função `_calcular_metricas_derivadas` (~linha 472-485):
- Remover o cálculo de ROE do extrator. Manter apenas a coluna "Lucro Líquido Acumulado YTD".
- NÃO calcular "ROE Ac. YTD an. (%)" no extrator — deixar o recálculo em
  `recalcular_metricas_derivadas` do app1.py, que usa PL médio corretamente.

### C. Unificar base de Crédito para Crédito/PL (CRÍTICO)
Em `utils/ifdata_cache/extractor.py`, função `_calcular_metricas_derivadas` (~linha 505-512):
- Remover o cálculo de "Crédito/PL (%)" do extrator.
- Deixar o recálculo centralizado em `recalcular_metricas_derivadas` que já tem a
  lógica correta com fallback para "Carteira de Crédito Bruta" → "Carteira de Crédito".

### D. Eliminar dupla normalização de Basileia
1. Manter normalização no extrator (`extractor.py:517-522`)
2. Em `app1.py`, `recalcular_metricas_derivadas` (~linha 1210-1218):
   substituir a normalização per-value (abs > 1) por verificação baseada na
   mediana da série (se mediana > 1 → dividir por 100; senão manter).
   Isso torna a operação idempotente.
3. Remover `_ajustar_basileia_para_scatter` (`app1.py:3061-3098`) e todas as
   chamadas a essa função — se as camadas anteriores estiverem corretas, o hack
   não é necessário.

### E. Corrigir semântica Core Funding vs Captações
Em `app1.py` (~linha 1115):
- Remover o rename `'Crédito/Captações (%)': 'Carteira de Crédito/Core Funding (%)'`
- Se "Core Funding" não existir no DataFrame, NÃO preencher
  "Carteira de Crédito/Core Funding (%)" com dados de "Captações"
- Adicionar log.warning quando o fallback ocorrer

### F. Mover senha para variável de ambiente
Em `app1.py` (~linha 742):
- Substituir `SENHA_ADMIN = "m4th3u$987"` por:
  `SENHA_ADMIN = os.environ.get("TOMACONTA_ADMIN_PASSWORD", "")`

### Verificação pós-correção
1. Rodar `python -m pytest tests/`
2. Comparar ROE do Itaú (60701190) em 4/2024 entre Snapshot, Rankings e Scatter — devem ser idênticos
3. Verificar que Basileia no Scatter não mostra valores absurdos (entre 5-30%)
4. Confirmar que ROE trimestral na Evolução está na mesma escala que ROE acumulado
```

---

## Arquivos Críticos

| Arquivo | Linhas | Mudança |
|---------|--------|---------|
| `app1.py` | 742 | Senha → env var |
| `app1.py` | 1067-1098 | ROE reference (não alterar) |
| `app1.py` | 1100-1225 | Recálculo de métricas |
| `app1.py` | 1210-1218 | Normalização Basileia |
| `app1.py` | 3061-3098 | Remover hack Scatter |
| `app1.py` | 3795 | ROE trimestral escala |
| `utils/ifdata_cache/extractor.py` | 460-524 | Métricas derivadas do extrator |
| `utils/ifdata_cache/metric_registry.py` | — | Documentação de escala |
