# Runbook — Atualizar Base sem quebrar o app

## 1) Regra de ouro

Atualize **bases primeiro**, derive/publice **só no fim**.

Se `principal`, `capital`, `dre`, `critical_screens` e os derivados não terminarem no **mesmo período-alvo**, a atualização ainda não acabou.

## 2) Ritmo recomendado

| Evento | Frequência | O que atualizar |
|---|---|---|
| Saiu IFData trimestral novo | 1x por trimestre | `principal`, `capital`, `ativo`, `passivo`, `dre`, `carteira_pf`, `carteira_pj`, `carteira_instrumentos`, `principal_individual`, `dre_individual`, `bloprudencial` do mês final, depois derivados + `critical_screens` |
| Saiu BLOPRUDENCIAL mensal novo | mensal, se necessário | `bloprudencial`; se quiser refletir isso em telas curadas do trimestre corrente, rematerializar `critical_screens` |
| Falhou só a publicação | sob demanda | não reextrair; repetir apenas a publicação após validar os gates |
| Precisa corrigir período antigo | sob demanda | usar janela focada; evitar `overwrite` amplo sem necessidade |

## 3) Ordem operacional segura

### 3.1 Fechamento trimestral completo

1. Atualizar bases trimestrais:
   - `principal`
   - `capital`
   - `ativo`
   - `passivo`
   - `dre`
2. Atualizar carteiras:
   - `carteira_pf`
   - `carteira_pj`
   - `carteira_instrumentos`
3. Atualizar base individual:
   - `principal_individual`
   - `dre_individual`
4. Atualizar `bloprudencial` para o **mês final do trimestre**.
5. Materializar:
   - `derived_metrics`
   - `derived_metrics_individual`
   - `critical_screens`
6. Validar os gates na aba **Atualizar Base**.
7. Publicar no release/tag corretos.

### 3.2 Atualização apenas FGC/FGCoop

1. Atualizar `bloprudencial`.
2. Se a atualização for apenas da aba FGC, parar aqui.
3. Se precisar refletir a base prudencial nas telas curadas do trimestre corrente, rematerializar `critical_screens`.

## 4) Janela de suporte que costuma quebrar

Os caches abaixo **não** devem ser extraídos desde 2015:

| Cache | Início suportado |
|---|---|
| `carteira_pf` | `202503` (`1/2025`) |
| `carteira_pj` | `202503` (`1/2025`) |
| `carteira_instrumentos` | `202503` (`1/2025`) |

Se a janela começar antes disso, use:
- `incremental`; ou
- `overwrite` começando em `202503`.

## 5) Por que “atualizei tudo e não funcionou”

Os problemas históricos mais comuns foram:

1. **Fontes em períodos diferentes**
   - Ex.: `principal` em `202512` e `capital` em `202412`.
   - Resultado: Rankings, Scatter, DRE e `critical_screens` ficam inconsistentes.

2. **Derivados não rematerializados**
   - Atualizar `principal`/`dre` não atualiza sozinho `derived_metrics`.
   - Atualizar bases não atualiza sozinho `critical_screens`.

3. **Mistura de local novo com remoto antigo**
   - Se a materialização buscar dependência remota desatualizada, o bundle curado volta a andar para trás.
   - O fluxo foi corrigido para preferir fontes locais existentes.

4. **BLOPRUDENCIAL só no bruto**
   - Ter CSV/ZIP em `data/cache/bcb_bloprudencial/` não basta.
   - É preciso persistir também o cache `bloprudencial` usado pelo `CacheManager`.

5. **Publicação com gate vermelho**
   - O upload pode até acontecer, mas a produção continua quebrada porque o conjunto publicado não fecha no mesmo período.

## 6) Crashes comuns e resposta rápida

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `critical_screens` não materializa | base local faltando ou `bloprudencial` não persistido | salvar as bases localmente, persistir `bloprudencial` e materializar novamente |
| Snapshot/Peers continuam no trimestre antigo | `critical_screens` não foi regenerado | rerodar a materialização final |
| Rankings/Scatter mostram números quebrados | `principal` e `capital` desalinhados | alinhar os dois no mesmo período antes de publicar |
| DRE individual fica vazia | `principal_individual` ou `dre_individual` ausentes | atualizar ambos e deixar o derivado individual recalcular |
| FGC funciona localmente e some após restart | cache só local/bruto | persistir `bloprudencial` e publicar |
| Publish falha | token, repo, tag ou permissão | validar secrets, repo/tag e repetir apenas o upload |

## 7) Definição de pronto

A atualização só está pronta quando:

1. Os gates críticos estão `OK` no mesmo período-alvo.
2. `critical_screens` foi materializado **depois** das bases e do `bloprudencial`.
3. Não há cache crítico em estado “somente local” antes do publish final.
4. O release/tag corretos estão acessíveis.
5. O `manifest.json` publicado reflete o período esperado.

## 8) Publicação segura

### 8.1 Antes do upload

1. Confirmar `repo`, `tag` e token.
2. Conferir se os gates estão verdes.
3. Fazer download local de backup do cache, se necessário.

### 8.2 Depois do upload

1. Verificar se os assets corretos subiram.
2. Confirmar presença de `manifest.json`.
3. Reabrir a aplicação e conferir o período máximo no diagnóstico operacional.

## 9) Resumo curto

- Use `incremental` por padrão.
- Atualize bases antes de derivados.
- Não publique com gate vermelho.
- Para Snapshot/Peers, o que vale no final é `critical_screens`.
- Para FGC/FGCoop, o que vale é `bloprudencial` persistido.
