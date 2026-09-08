# Project Understanding Summary

O app é um dashboard Streamlit que combina múltiplos caches (IFData Rel. 1/2/3/4/5, BLOPRUDENCIAL, métricas derivadas) para renderizar abas analíticas, com foco aqui em **Snapshot** e **Atualizar Base**. A leitura de cache passa por `CacheManager`/`BaseCache` (priorizando local válido, depois remoto), enquanto partes do app usam funções com `@st.cache_data` para recortes por período/instituição. A persistência remota depende de GitHub Releases (repo/tag resolvidos por env/secrets), mas há caminhos com tags hardcoded em módulos de cache. O diagnóstico do Snapshot é construído localmente na própria função `pagina_snapshot()`, enquanto a aba Atualizar Base monta um painel de status com verificação separada no GitHub.

# How to Answer

Use uma tag por resposta:

- `verified`: comportamento confirmado no código e alinhado ao esperado
- `bug`: comportamento confirmado no código e incompatível com o esperado
- `approved improvement`: não é bug inequívoco, mas melhoria aprovada de robustez/clareza
- `deferred`: depende de decisão de produto/operação antes de mudar
- `out-of-scope`: fora do escopo desta fase

Formato sugerido por resposta:

- **Tag:** `verified|bug|approved improvement|deferred|out-of-scope`
- **Evidence:** arquivo/função + trecho lógico
- **Decision/Answer:** resposta objetiva da dúvida

# 1) Cache Loading & Resolution

1. **Where:** `app1.py` (`pagina_snapshot`, `_carregar_cache_relatorio_slice`, `_aplicar_aliases_df`)
   **Why this matters:** Snapshot filtra cache por instituição *antes* de aplicar aliases; se o `banco` selecionado estiver em alias e o cache vier com nome original, o slice pode retornar vazio falso.
   **Question:** A instituição selecionada no Snapshot deve ser resolvida por alias/codinst **antes** do filtro de slice (`instituicoes=(banco,)`) ou o comportamento esperado é exigir igualdade literal de nome já no parquet?

2. **Where:** `app1.py` (`_carregar_cache_relatorio_slice`)
   **Why this matters:** O caminho rápido com `pyarrow.dataset` sempre tenta filtrar por coluna `Período`; para caches sem essa coluna (caso BLOPRUDENCIAL cru), cai em exceção silenciosa e muda para fallback em `manager.carregar`.
   **Question:** Esse fallback silencioso é intencional para BLOPRUDENCIAL, ou o cache BLOPRUDENCIAL deveria sempre persistir com coluna `Período` para evitar divergência de caminho de leitura?

3. **Where:** `utils/ifdata_cache/base.py` (`BaseCache.carregar`)
   **Why this matters:** A validade local expira por `max_idade_horas`; após expirar, o código tenta remoto e só depois usa local expirado. Isso altera fonte lida sem mudança de UI explícita.
   **Question:** Para Snapshot, o comportamento esperado é sempre tentar remoto após expiração (com possível latência/falha), ou deve haver opção de “sempre local” para evitar inconsistência operacional?

4. **Where:** `app1.py` (`_cache_version_token`, `_carregar_cache_relatorio_slice` com `@st.cache_data(ttl=3600)`)
   **Why this matters:** O token de versão depende de `mtime+size` local; uploads remotos não invalidam automaticamente cache de função caso arquivo local não mude.
   **Question:** Após publicação no GitHub, o app deve continuar 100% local até novo download, ou há expectativa de refresh imediato do conteúdo remoto na mesma sessão?

5. **Where:** `app1.py` (`pagina_snapshot`, `get_analise_base_df`, `_preparar_metricas_extra_peers`)
   **Why this matters:** Cartões do Snapshot misturam fontes: base principal (`df_base`), recortes de caches e métricas derivadas; divergências de período/instituição entre fontes podem parecer “cache vazio”.
   **Question:** Qual é a regra canônica de precedência quando a mesma métrica pode ser derivada de mais de uma fonte (ex.: principal vs ativo/passivo/capital)?

# 2) Diagnóstico / Guardrails operacionais

1. **Where:** `app1.py` (`pagina_snapshot`, bloco `diagnostico_snapshot`)
   **Why this matters:** O diagnóstico marca vazio por `DataFrame.empty` após recorte por banco/período; isso não distingue “cache inexistente” de “mismatch de chave (nome/alias/período)”.
   **Question:** O diagnóstico deve separar explicitamente os casos: (a) arquivo ausente, (b) arquivo presente mas sem período, (c) período presente mas sem instituição correspondente?

2. **Where:** `app1.py` (`pagina_snapshot`, expander “Como corrigir definitivamente”)
   **Why this matters:** O passo a passo é texto fixo e sugere atualizar `capital/ativo/passivo/bloprudencial` mesmo quando a causa pode ser alias/período/tag release.
   **Question:** A seção “Como corrigir” deve ser dinâmica por causa detectada (período, alias, release tag, ausência local), ou permanecer orientação genérica?

3. **Where:** `app1.py` (`verificar_caches_github`, tela “Atualizar Base”)
   **Why this matters:** Status GitHub é `@st.cache_data(ttl=300)` e pode ficar defasado por até 5 minutos após upload.
   **Question:** O owner considera aceitável esse atraso de consistência no painel “Status dos Caches” ou deseja invalidação imediata após publicação?

4. **Where:** `app1.py` (`verificar_caches_github` + tabela de status)
   **Why this matters:** A verificação de GitHub inclui apenas alguns tipos (`principal`, `capital`, `ativo`, `passivo`, `dre`, `carteira_pf`, `carteira_pj`, `carteira_instrumentos`), omitindo `bloprudencial` e `derived_metrics`.
   **Question:** O status “Publicado / Somente local” deve cobrir **todos** os caches registrados em `CacheManager`, inclusive BLOPRUDENCIAL e métricas derivadas?

5. **Where:** `app1.py` (`pagina_snapshot`)
   **Why this matters:** Diagnóstico e renderização usam caminhos parcialmente diferentes (ex.: `_preparar_metricas_extra_peers` tem fallback próprio para BLOPRUDENCIAL), o que pode gerar aviso de dependência incompleta com cartão preenchido (ou vice-versa).
   **Question:** O diagnóstico do Snapshot deve validar exatamente o mesmo dataset intermediário usado pelos cartões, em vez de validar caches separadamente?

# 3) GitHub Release como mecanismo de persistência

1. **Where:** `app1.py` (`_resolver_release_tag`) vs `utils/ifdata_cache/*.py` (URLs com `v1.0-cache` hardcoded)
   **Why this matters:** Existe resolução dinâmica de tag no app, mas classes de cache usam `v1.0-cache` fixo para download remoto; isso pode divergir de releases reais (ex.: `v2.0`).
   **Question:** Qual tag é canônica hoje para leitura remota: `v1.0-cache`, `v2.0` ou valor configurável? Devemos padronizar um único resolvedor para todo o pipeline?

2. **Where:** `app1.py` (`upload_cache_github`)
   **Why this matters:** Upload substitui assets no release, mas não atualiza manifest/índice local além do próprio arquivo e metadata do cache.
   **Question:** Existe requisito de manter um manifesto global de versão (ex.: hash por cache) para sincronizar tela de status, invalidação de cache Streamlit e seleção de fonte?

3. **Where:** `utils/ifdata_cache/base.py` (`BaseCache.carregar`) e `app1.py` (`_cache_version_token`)
   **Why this matters:** Após upload, leitura padrão continua local enquanto o token local não muda; publicação não implica re-download.
   **Question:** O comportamento esperado pós-upload é “publicar para persistência externa apenas” ou “publicar e imediatamente reidratar leitura remota/local sincronizada”?

4. **Where:** `app1.py` (`verificar_caches_github`)
   **Why this matters:** A inferência de existência de cache no release depende de `asset.name.startswith(f'{tipo}_dados')`.
   **Question:** Há convenção oficial de nomenclatura dos assets que garanta compatibilidade futura, ou precisamos de mapeamento explícito por tipo de cache?

5. **Where:** `app1.py` (`upload_cache_github`)
   **Why this matters:** Fluxo tenta `gh` CLI e depois API; não há registro explícito de “release alvo efetivamente usado” em metadata local do cache.
   **Question:** Devemos registrar em `metadata.json` o `repo/tag/asset` de publicação para auditoria e troubleshooting de divergência local vs GitHub?

# 4) Métricas Derivadas

1. **Where:** `app1.py` (`ensure_derived_metrics_cache`)
   **Why this matters:** Recalcula derivadas apenas quando mtime de `dre` ou `principal` supera mtime de `derived_metrics`; não considera alterações de alias.
   **Question:** Mudanças de alias devem invalidar/recalcular `derived_metrics`, ou alias é apenas camada de apresentação e não deve tocar cache derivado?

2. **Where:** `app1.py` (`ensure_derived_metrics_cache`, `carregar_metricas_derivadas_slice`)
   **Why this matters:** Em falha de carga de DRE/principal, a função retorna erro e o slice vira DataFrame vazio sem erro explícito no Snapshot.
   **Question:** Para a aba Snapshot, ausência de métricas derivadas deve gerar warning específico (com causa) em vez de silêncio/valor vazio?

3. **Where:** `utils/ifdata_cache/derived_metrics.py` (`build_derived_metrics`)
   **Why this matters:** As derivadas implementadas atualmente são focadas em DRE+principal; sintomas reportados misturam métricas também dependentes de capital/bloprudencial.
   **Question:** Quais métricas são oficialmente “derived_metrics” vs “métricas extras calculadas em tempo de render” para evitar expectativa de recálculo errado?

4. **Where:** `app1.py` (`ensure_derived_metrics_cache`) + UI “Atualizar Base”
   **Why this matters:** Não há botão explícito “recalcular derivadas agora”; o recálculo é implícito por mtime.
   **Question:** O fluxo operacional desejado inclui trigger manual de recálculo de derivadas na aba Atualizar Base (com log/resultado), ou recálculo automático é suficiente?

5. **Where:** `utils/ifdata_cache/derived_metrics.py` (`_prepare_base_principal`)
   **Why this matters:** A métrica `Desp Captação / Captação` depende de coluna canônica `Captações`; variações de nome podem quebrar cálculo.
   **Question:** A coluna de captações no principal está contratualmente estável em todos os períodos, ou é necessário contrato explícito de schema/versionamento para derivadas?

# 5) Possíveis Bugs

1. **Where:** `app1.py` (`pagina_snapshot` + `_preparar_metricas_extra_peers`)
   **Why this matters:** `_preparar_metricas_extra_peers` possui fallback interno para BLOPRUDENCIAL vazio, mas `diagnostico_snapshot` continua avaliando `cache_bloprud` original; isso pode produzir falso negativo no diagnóstico.
   **Question:** Confirmar se é esperado o diagnóstico acusar BLOPRUDENCIAL vazio mesmo quando as métricas de qualidade são obtidas via fallback interno?

2. **Where:** `app1.py` (`verificar_caches_github`, painel “Atualizar Base”)
   **Why this matters:** Caches “Publicado / Não local” (ex.: carteira_pj) aparecem como disponíveis no GitHub, mas o carregamento efetivo depende do fluxo de `manager.carregar` em cada aba e da tag correta.
   **Question:** Quando local está ausente e GitHub presente, o app deve baixar automaticamente em background na primeira leitura e persistir localmente sem intervenção do usuário?

3. **Where:** `app1.py` (`pagina_snapshot`, seleção de períodos)
   **Why this matters:** Snapshot usa períodos trimestrais do `df_base`; BLOPRUDENCIAL no estado informado está apenas em 2025 (mensal), e o filtro converte trimestre para `YYYYMM` (03/06/09/12).
   **Question:** Para instituição/período atual no Snapshot, o período trimestral selecionado está garantidamente dentro da janela BLOPRUDENCIAL disponível (01/2025–12/2025), inclusive para comparação YoY?

4. **Where:** `app1.py` (`_resolver_release_tag`, `verificar_caches_github`) e `utils/ifdata_cache/capital.py`, `relatorios_completos.py`, `bloprudencial_cache.py`
   **Why this matters:** Divergência de tag entre leitura de status e leitura de dados pode explicar “arquivo existe no release” mas “cache vazio” no app.
   **Question:** Confirmar se a instância em produção está com `TOMACONTA_RELEASE_TAG` definido e se todos os módulos de cache usam a mesma tag efetiva no runtime.

5. **Where:** `app1.py` (`_carregar_cache_relatorio_slice`, decorado com `@st.cache_data(ttl=3600)`)
   **Why this matters:** Slice pode permanecer em memória por até 1h; se upload/extração ocorreu na mesma sessão sem mudança de token local percebida, pode haver leitura stale.
   **Question:** Existe evidência de invalidação manual/automática dos caches de função após atualização/publicação, ou é necessário fluxo explícito de “recarregar caches da sessão” para Snapshot?
