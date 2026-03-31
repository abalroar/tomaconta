# Runbook — cache local e publicação em GitHub Releases

## 1) Diagnóstico: por que o app pode continuar funcionando mesmo após apagar cache local

O app não depende apenas dos arquivos `data/cache/*` para renderizar abas:

1. **Dados em memória (sessão Streamlit)**: `st.session_state['dados_periodos']` mantém o conteúdo carregado até reinício da sessão/processo.  
2. **Memoização com `@st.cache_data`**: funções de leitura continuam servindo dados em cache in-memory/disk do Streamlit até expirar/invalidar.  
3. **Fallback remoto**: quando o cache local não está disponível, o fluxo orienta uso/publicação via GitHub Releases para restaurar dados.

Conclusão prática: apagar somente `data/cache/*` **não garante** tela vazia imediata; é necessário limpar sessão e cache do Streamlit.

## 2) Matriz de rastreabilidade por aba

| Aba | Cache(s) usados | Pasta/arquivo local principal | Função/carregador principal |
|---|---|---|---|
| Snapshot | `principal`, `ativo`, `capital`, `bloprudencial`, `metricas_derivadas` | `data/cache/principal/*`, `data/cache/ativo/*`, `data/cache/capital/*`, `data/cache/bloprudencial/*`, `data/cache/metricas_derivadas/*` | `_garantir_dados_principais()`, `get_analise_base_df()`, `_carregar_cache_relatorio_slice()`, `carregar_metricas_derivadas_slice()` |
| Rankings | `principal` + `capital` | `data/cache/principal/*`, `data/cache/capital/*` | `_garantir_dados_principais()`, `_get_rankings_base_df()`, `_construir_indices_capital_unificados()` |
| Peers (Tabela) | `principal`, `ativo`, `passivo`, `carteira_pf`, `carteira_pj`, `carteira_instrumentos`, `dre`, `capital`, `bloprudencial` | `data/cache/<tipo>/*` | `_garantir_dados_principais()`, `get_analise_base_df()`, `_carregar_cache_relatorio_slice()` |
| Evolução | `principal` + slices `passivo`/`ativo` | `data/cache/principal/*`, `data/cache/passivo/*`, `data/cache/ativo/*` | `_garantir_dados_principais()`, `get_dados_concatenados()`, `_carregar_cache_relatorio_slice()` |
| Scatter Plot | `principal` + `capital` (via merge) | `data/cache/principal/*`, `data/cache/capital/*` | `_garantir_dados_principais()`, `carregar_dados_capital()`, `mesclar_dados_capital()` |
| DRE (congl.) | `dre`, `principal` (captações) | `data/cache/dre/*`, `data/cache/principal/*` | `load_dre_data()`, `load_principal_captacoes_data()` |
| DRE (ind.) | `dre_individual`, `principal_individual` | `data/cache/dre_individual/*`, `data/cache/principal_individual/*` | `load_dre_individual_data()`, `load_principal_individual_data()` |
| Carteira 4.966 | `carteira_instrumentos` | `data/cache/carteira_instrumentos/*` | `load_carteira_4966_data()` |
| Taxas de Juros por Produto | sem cache IFData local obrigatório (consulta API BCB em runtime) | n/a | `buscar_taxas_bcb_historico()` |
| Contribuições FGC/FGCoop | `bloprudencial` | `data/cache/bloprudencial/*` e `data/cache/bcb_bloprudencial/*` | `_listar_periodos_bloprudencial_disponiveis()`, `_carregar_fgc_8118500009_por_periodos()` |
| Atualizar Base | todos os tipos registrados no `CacheManager` | `data/cache/<tipo>/*` + metadata | `CacheManager.extrair_periodos_com_salvamento()`, `upload_cache_github()`, `verificar_caches_github()` |

## 3) Operação segura — clean local + update + publish

### 3.1 Limpeza local com segurança

1. Parar o app Streamlit (evita recriação simultânea de cache).  
2. Backup opcional: copiar `data/cache/` para diretório temporário.  
3. Remover cache local: `rm -rf data/cache/*`.  
4. Reabrir app e usar **Settings → Clear cache** do Streamlit (ou reiniciar processo) para limpar `st.cache_data`.  
5. Fazer hard refresh no browser.

### 3.2 Garantir repositório clean no GitHub (evitar arquivo morto)

1. Verificar regras de ignore: `.gitignore` deve conter `data/cache/` e `data/cache/bcb_bloprudencial/`.  
2. Validar se há lixo versionado: `git status --short` não deve listar arquivos de `data/cache/*`.  
3. Se algum arquivo já foi versionado no passado: `git rm --cached <arquivo>` e commit de remoção.  
4. Nunca commitar assets de cache; publicar apenas em Release assets.

### 3.3 Publicação correta no release/tag

1. Definir destino explícito:
   - `TOMACONTA_RELEASE_REPO` (ex.: `abalroar/tomaconta-dev`)
   - `TOMACONTA_RELEASE_TAG` (default: `v1.0-cache`)
2. Garantir token em ordem de busca: `GITHUB_TOKEN` → `GH_TOKEN` → `GITHUB_PAT` (secrets/env).  
3. Na aba **Atualizar Base**, confirmar:
   - repo/tag efetivos exibidos na UI,
   - origem do token,
   - pré-validação de upload com status **OK**.
4. Executar extração e upload.
5. Validar assets no release via API:
   - `GET /repos/{repo}/releases/tags/{tag}` deve retornar 200.
   - Conferir presença de `{tipo}_dados.parquet` e `{tipo}_metadata.json`.

### 3.4 Rollback rápido se upload falhar

1. Fazer download imediato do cache local (botão de download da aba).  
2. Corrigir causa da falha (token/repo/tag/rede).  
3. Repetir apenas a etapa de publicação manual sem nova extração.  
4. Se necessário, restaurar release anterior reaplicando os assets de backup com os mesmos nomes (`--clobber`).

## 4) Falhas comuns e ação imediata

- **Token inválido/expirado (401)** → gerar novo token e atualizar secret.  
- **Token sem escopo/permissão (403)** → incluir `repo`/`contents:write` e acesso ao repo alvo.  
- **Repo incorreto/sem acesso (404 em `/repos/{repo}`)** → corrigir `TOMACONTA_RELEASE_REPO`.  
- **Tag inexistente (404 em `/releases/tags/{tag}`)** → criar tag/release `v1.0-cache` (ou a definida).  
- **Erro de rede/timeout** → repetir operação; manter backup local até confirmação da publicação.
