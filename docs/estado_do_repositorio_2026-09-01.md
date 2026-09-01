# Estado do repositório — briefing para o Codex

Levantado em **2026-09-01**. Todos os números abaixo foram verificados por comando,
e cada seção traz como reconferir. Se você estiver lendo isto dias depois, **reconfira
antes de decidir** — o repositório se move.

Objetivo deste documento: dar contexto suficiente para você decidir sozinho o que
fazer, **sem perder nenhum trabalho já feito**, incluindo a aba do SCR.data.

---

## 1. O resumo em cinco linhas

1. O branch em que a árvore de trabalho está (`codex/cleanup-unused-safe`) **já está
   inteiramente contido no `origin/main`**. Não há nada a preservar nele.
2. O `main` **local** está 23 commits atrás do `origin/main`. Toda base nova tirada dele
   nasce velha.
3. Existe **trabalho não-commitado de Taxas de Juros na árvore, sem cópia em lugar
   nenhum**, parado há seis semanas. É a única coisa em risco real.
4. A aba do SCR.data está pronta, testada e **já commitada no PR #274**; os 22 assets de
   cache já estão publicados no release. Falta apenas **mergear o PR** — é por isso que
   ela ainda não aparece no site publicado.
5. O `app1.py` da árvore de trabalho contém, misturados no mesmo arquivo, o WIP de Taxas
   de Juros **e** as alterações do SCR. Separar os dois é o passo delicado.

---

## 2. Fatos verificados

### Git

| Fato | Valor |
|---|---|
| `origin/main` | `a2fddbe` |
| `main` local | `59a31c2` — **23 commits atrás**, 0 à frente |
| Branch da árvore de trabalho | `codex/cleanup-unused-safe` (`5660350`) |
| Branches remotos | **254** |
| PRs abertos | **13** — 10 marcados como conflitantes pelo GitHub, idade mediana **159 dias**, o mais antigo com 216 |
| Worktrees | 5, sendo **2 `prunable`** (branches abandonados de agosto) |

```bash
git fetch origin --prune
git rev-list --count main..origin/main      # quanto o main local está atrás
git worktree list                            # veja os prunable
gh pr list --state open --limit 100
```

### O branch atual está contido no main

```bash
git diff origin/main codex/cleanup-unused-safe --stat | tail -1
# 65 files changed, 809 insertions(+), 9829 deletions(-)
```

Leia esse número com atenção: **9.829 deleções contra 809 inserções**. O branch não está
à frente do main — está atrás. Arquivos inteiros existem no main e não nele
(`carteira_4966_quality.py`, `metric_registry.py`, `artifact_identity.py`,
`analytical_status_excel.py`).

### Cuidado com `git cherry`: ele mente aqui

```bash
git cherry -v origin/main codex/cleanup-unused-safe
# marca os 6 commits com '+', sugerindo que não estão no main
```

**Isso é falso negativo.** O PR #266 foi *squash-merged* em 14/07 como `9b69ab2`, que está
no `origin/main`. O squash reescreve o conteúdo num commit só, mudando os patch-ids, e o
`git cherry` compara justamente por patch-id.

Conferido por conteúdo, os três commits de carregamento estão no main:

- `Fix Streamlit OOM on data-heavy pages`
- `Avoid GitHub calls during Streamlit startup`
- `Avoid materializing critical cache during bootstrap`

E os dois commits posteriores ao squash (`a3252a9` aprimora modelo de carteira 4966,
`5660350` alertas de qualidade ao PDD 4966) também já foram absorvidos, pelos PRs
#269–#271: 12 de 12 e 10 de 12 linhas características deles já existem no `origin/main`.

**Regra:** neste repositório, para saber se um commit já está no main, **compare por
conteúdo**, nunca por patch-id.

### O main carrega bem — melhor que o branch atual

Rodado em 2026-09-01, `origin/main` + a aba do SCR, com uma cópia do cache local:

| Aba | Tempo |
|---|---|
| Snapshot | 0,16 s |
| Peers (Tabela) | 1,21 s |
| Rankings | 1,54 s |
| Inadimplência (SCR) | 7,78 s |

Sem erros. O main ainda tem `Reduz em 3 segundos a montagem dos rankings derivados`, que o
branch atual não tem. **Sincronizar com o main não degrada o carregamento; melhora.**

Ruído conhecido e pré-existente: a tabela do Glossário dispara
`ArrowInvalid: Could not convert 'N/D' ... column Schema` no log. O Streamlit conserta
sozinho e renderiza. É cosmético e é do main — não introduza correção às pressas.

---

## 3. Onde está cada trabalho

| Trabalho | Onde vive | Situação |
|---|---|---|
| Correções de carregamento (OOM, startup, bootstrap) | `origin/main`, via squash `9b69ab2` (PR #266) | ✅ preservado |
| Carteira 4.966 (modelo + alertas de PDD) | `origin/main`, via PRs #269–#271 | ✅ preservado |
| 23 commits de Rankings, Custo de Crédito, cache versionado | `origin/main` | ✅ preservado |
| **Aba SCR.data** | branch `feat/scr-inadimplencia`, **PR #274**, e release `v1.1-cache` | ⚠️ pronto, **falta mergear** |
| **WIP de Taxas de Juros** | **só na árvore de trabalho, não-commitado** | 🔴 **em risco** |

---

## 4. O trabalho do SCR.data — o que já está feito

**Não refaça nada disso.** Está tudo em `feat/scr-inadimplencia`, um único commit
(`83d0543`), aberto como PR #274 com base em `main`.

| Item | Estado |
|---|---|
| Código | 12 arquivos, +5.202/−2, só a feature |
| Testes | 132 novos; suíte completa **506 passed** sobre `origin/main` |
| Assets de cache | **22 assets publicados** no release `v1.1-cache` (147,5 MB) |
| Dependências novas | **nenhuma** — `requirements.txt` não foi tocado |
| `scripts/check_bundle.py` | não precisa registrar o `scr_data`; ele só valida `critical_screens` e `derived_metrics` |
| Cold start a partir do release | verificado: bootstrap 4,6 s, inadimplência 4,63% batendo entre resumo e detalhe |

### Por que ainda não está no site

Porque o **PR #274 não foi mergeado**. Não há nada quebrado, nada faltando e nada a
investigar. Os assets já estão no release, então **no momento em que o PR entrar no `main`,
a aba funciona no deploy sem nenhum passo extra**.

O PR aparece como `mergeable: MERGEABLE`, `mergeStateStatus: BLOCKED`,
`reviewDecision: REVIEW_REQUIRED`. Isso é o estado **normal** deste repositório: os PRs
#269, #270, #271, #272 e #273 foram todos mergeados exibindo exatamente o mesmo
`REVIEW_REQUIRED`. Não é um bloqueio novo nem um problema do SCR.

### Um FAIL que NÃO é bug

Rodar `python scripts/check_bundle.py` dentro do branch do SCR dá:

```
FAIL | deploy: HEAD 83d0543a ainda não integra origin/main a2fddbec
RESULT | passes=12 failures=1
```

O check pergunta se o `HEAD` é **ancestral do `origin/main`** — ou seja, "o que estou
rodando já está no main?". Num branch de feature não-mergeado a resposta é
necessariamente não. **É o portão de deploy funcionando como projetado.** Depois do merge
ele passa sozinho. Não "conserte".

---

## 5. O que está em risco: o WIP de Taxas de Juros

Estado da árvore de trabalho:

```
 M app1.py                        <- MISTURA WIP de Taxas de Juros + alterações do SCR
 M data/dev_hours_cache.json      <- artefato gerado pelo app, não é trabalho
 M tools/update_caches_cli.py     <- 100% SCR (já está no PR #274)
 M utils/ifdata_cache/manager.py  <- 100% SCR (já está no PR #274)
?? tests/test_taxas_juros_ui.py   <- WIP, não versionado
?? utils/ifdata_cache/scr_data.py, utils/scr_data_query.py,
   tabs/scr_inadimplencia.py, tests/test_scr_*.py,
   docs/scr_data_estudo_e_plano.md, data/bundled/geo/   <- todos já no PR #274
?? .claude/, tmp/                 <- config local e lixo
```

Fatos sobre o WIP:

- `tests/test_taxas_juros_ui.py` foi tocado pela última vez em **16/07/2026**. Seis semanas.
- O conteúdo **não bate com nenhum dos 254 branches remotos**. É cópia única.
- O parente mais próximo **não é** o branch em que a árvore está: é
  `codex/simplify-taxas-juros-ui`, a 556 linhas de diferença (contra 1.074 do
  `codex/cleanup-unused-safe`). Provável que seja um porte daquele trabalho.

**Esta é a única coisa que um `git checkout` errado destrói para sempre. Trate como
prioridade 1.**

### Como separar o WIP das alterações do SCR

As alterações do SCR no `app1.py` são delimitadas e conhecidas. O script abaixo produz um
`app1.py` **sem** o SCR, preservando o WIP:

```python
import pathlib
p = pathlib.Path('app1.py')
t = p.read_text(encoding='utf-8')

# 1) o bloco da rota inteira
INI = 'elif menu == "Inadimplência (SCR)":'
FIM = 'elif menu == "Taxas de Juros por Produto":'
i = t.index(INI); t = t[:i] + t[t.index(FIM, i):]

# 2) as edições pontuais
for a, b in [
    ('    "Inadimplência (SCR)",\n', ''),
    ('    "Inadimplência (SCR)": ["scr_data"],\n', ''),
    ('"spb_meios_pagamento", "scr_data", "derived', '"spb_meios_pagamento", "derived'),
    ('    if cache_nome == "scr_data":\n'
     '        return "SCR.data — ZIPs anuais do PDA/BCB agregados por UF, segmento, porte e produto"\n', ''),
]:
    t = t.replace(a, b, 1)

# 3) a seção 8 do glossário, renumerando a 9 de volta para 8
i = t.index('    _render_secao_glossario("8) Inadimplência do crédito (SCR.data)"')
f = t.index('    with st.expander("**9) Definições históricas')
t = t[:i] + t[f:].replace('**9) Definições', '**8) Definições', 1)

# 4) a linha da seção "Módulos recentes"
i = t.index('        - **Inadimplência (SCR):**')
t = t[:i] + t[t.index('        - **Meios de Pagamento (SPB):**'):]

p.write_text(t, encoding='utf-8')
```

Depois disso, devolva ao estado do branch os dois arquivos que são 100% SCR e já estão no
PR #274, e apague os arquivos novos do SCR da árvore:

```bash
git checkout -- tools/update_caches_cli.py utils/ifdata_cache/manager.py
rm -f utils/ifdata_cache/scr_data.py utils/scr_data_query.py tabs/scr_inadimplencia.py \
      tests/test_scr_data_cache.py tests/test_scr_data_query.py tests/test_scr_inadimplencia_ui.py \
      docs/scr_data_estudo_e_plano.md
rm -rf data/bundled/geo
```

Sobre o `data/dev_hours_cache.json`: é regenerado pelo app a cada execução. Não commite
junto com o WIP; use `git checkout -- data/dev_hours_cache.json`.

---

## 6. Por que tudo ficou incompatível

Quatro causas, em ordem de impacto. Entender isso importa mais que executar o plano,
porque o problema volta se as causas ficarem.

**1. `app1.py` tem 27.700 linhas e 1,3 MB.** Toda tarefa toca o mesmo arquivo, então todo
branch conflita com todo branch, independentemente de quem escreveu. Esta é a causa raiz,
e nenhum processo a resolve — só extração para módulos.

O PR do SCR mostra o contraste: 5.202 linhas no total, mas só **708 no `app1.py`**. O
resto está em `utils/ifdata_cache/scr_data.py`, `utils/scr_data_query.py` e
`tabs/scr_inadimplencia.py`. Um branch que mexa em Taxas de Juros não encosta em nenhum
deles.

**2. Branches envelhecem.** Idade mediana de 159 dias entre os PRs abertos, dez deles já
conflitantes. Um branch de cinco meses contra um main que andou dezenas de commits vai
conflitar sempre. Rebase de branch velho custa mais que reescrever.

**3. O `main` local nunca é atualizado.** Está 23 commits atrás. Todo branch novo tirado
dele já nasce conflitado — e cria a ilusão de que o main "não tem" trabalho que na verdade
tem.

**4. Vários agentes editam a mesma árvore de trabalho.** Foi assim que o WIP de Taxas de
Juros e as alterações do SCR acabaram misturados no mesmo `app1.py` não-commitado. Já
existem 5 worktrees, mas o hábito está pela metade: dois estão abandonados e a árvore
principal continua sendo usada como área de trabalho compartilhada.

---

## 7. Plano recomendado, na ordem

Cada passo é verificável e você pode parar entre eles.

**Passo 1 — resgatar o WIP (urgente, é o único item destrutível).**

```bash
git fetch origin --prune
git worktree add ../tc-taxas-juros -b codex/taxas-juros-wip origin/main
```

Leve para lá o `app1.py` sem o SCR (seção 5) e o `tests/test_taxas_juros_ui.py`, commite e
pushe. Espere conflito com o `origin/main`: o WIP saiu de uma base de julho. Resolva
mantendo o main em tudo que não for a aba de Taxas de Juros. Se o resultado ficar
irreconhecível, **commite o WIP cru primeiro** num commit "snapshot" e só depois reconcilie
— o importante é ter o trabalho versionado antes de mexer nele.

**Passo 2 — mergear o PR #274 (publica o SCR).**

```bash
gh pr merge 274 --squash    # ou pela UI
```

Os assets já estão no release, não há dependência nova, o `check_bundle.py` não precisa de
alteração. Depois do merge, o deploy passa a servir a aba.

**Passo 3 — sincronizar o main local.**

```bash
git switch main && git reset --hard origin/main
```

De agora em diante trate o `main` local como espelho somente-leitura. Nunca commite nele.

**Passo 4 — limpar o que está morto.**

```bash
git worktree prune
git branch -D codex/cleanup-unused-safe   # inteiramente contido no main
```

**Passo 5 — triar os 13 PRs abertos.** Abra um por um e pergunte se o problema ainda
existe no main de hoje. Muitos são de março, escritos contra um app que não existe mais.
Fechar é uma resposta legítima e frequentemente a certa.

**Passo 6 — daqui pra frente:** um worktree por tarefa, sempre a partir de `origin/main`
recém-buscado, e extraia lógica do `app1.py` para `tabs/` e `utils/` sempre que o escopo
permitir.

```bash
git fetch origin --prune
git worktree add ../tc-<tarefa> -b <tipo>/<tarefa> origin/main
```

---

## 8. Regras de decisão

**Faça:**

- Verifique se um commit está no main **por conteúdo**, nunca por `git cherry` ou patch-id.
- Trabalhe sempre num worktree próprio, a partir de `origin/main` recém-buscado.
- Ao mexer numa aba, pergunte se dá para extrair a lógica para um módulo em `tabs/` ou
  `utils/`, deixando no `app1.py` só a renderização. É o que reduz conflito futuro.
- Rode `python -m pytest -q` e `python scripts/check_menu_dispatch_uniqueness.py` antes de
  concluir qualquer coisa.

**Não faça:**

- Não commite o `app1.py` inteiro quando houver WIP alheio na árvore. Separe primeiro.
- Não refaça a aba do SCR.data: ela existe, está testada e está no PR #274.
- Não trate o `FAIL | deploy: HEAD ... ainda não integra origin/main` como bug num branch
  de feature.
- Não "corrija" o aviso de Arrow no Glossário sem pedido explícito — é pré-existente e
  cosmético.
- Não rebase branches de meses só porque estão abertos. Avalie se ainda fazem sentido.
- Não apague `codex/cleanup-unused-safe` **antes** de resgatar o WIP: a árvore de trabalho
  está apontada para ele.

---

## 9. Como verificar que nada se perdeu

Depois de executar o plano, estes quatro comandos devem dar o resultado indicado:

```bash
# 1) o WIP de Taxas de Juros está versionado em algum lugar
git log --oneline origin/codex/taxas-juros-wip -1

# 2) a aba do SCR está no main
git log --oneline origin/main --grep="SCR.data" -1

# 3) o main local espelha o remoto
git rev-list --count main..origin/main    # deve ser 0

# 4) a suíte passa
python -m pytest -q
```

E, no app rodando a partir do main: a aba **Inadimplência (SCR)** aparece no menu, abre com
inadimplência de **4,63%** sobre carteira de **R$ 7,6 tri** na data-base **jun/2026**, e o
rodapé informa **6,7%** da carteira com contagem de operações suprimida.
