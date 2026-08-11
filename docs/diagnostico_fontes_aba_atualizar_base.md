# Diagnóstico — Fontes de dados por aba e relação com “Atualizar Base”

## 1) Por que o app continua funcionando após “limpar cache”

O TomaConta não depende só do cache local. Para vários caches, o carregamento tenta nesta ordem:
1. cache local em `data/cache/<tipo>/dados.parquet`;
2. fallback remoto em GitHub (`raw` do repo + GitHub Releases `v1.1-cache`);
3. em alguns fluxos, dados já em memória (`st.session_state`).

Por isso, apagar apenas o cache local não derruba automaticamente a aplicação quando o fallback remoto está acessível.

## 2) Mapa por aba (UI) → cache(s) usados → pasta/arquivo

| Aba | Cache(s) principal(is) | Pasta/arquivo local | Observações |
|---|---|---|---|
| Snapshot | `principal` (+ `capital` mesclado quando disponível) | `data/cache/principal/` e `data/cache/capital/` | `principal` é obrigatório para a aba abrir. |
| Rankings | `critical_screens` (carteira/funding), `principal` (+ `capital`), `derived_metrics` (Custo de Crédito) | `data/bundled/*` com fallback em `data/cache/*` | Indicadores de carteira e funding leem a camada curada; o resto sai do principal/capital. |
| Peers (Tabela) | `principal` (+ `capital`) | `data/cache/principal/` e `data/cache/capital/` | Usa os períodos preparados em memória. |
| Evolução | `principal` (+ `capital`) | `data/cache/principal/` e `data/cache/capital/` | Séries históricas por período. |
| Scatter Plot | `principal` (+ `capital`) | `data/cache/principal/` e `data/cache/capital/` | Seleção de eixos depende de colunas do cache principal. |
| Conselho e Diretoria | API externa BCB (não cache IFData principal) | sem pasta fixa do `CacheManager` | Não depende da atualização de cache IFData para funcionar. |
| DRE (Ind. e Congl.) — Conglomerado | `dre` + `principal` | `data/cache/dre/` e `data/cache/principal/` | Renderiza a DRE consolidada. |
| DRE (Ind. e Congl.) — Individual | `dre_individual` + `principal_individual` | `data/cache/dre_individual/` e `data/cache/principal_individual/` | Exige ambos atualizados para UX completa. |
| Carteira 4.966 | `carteira_instrumentos` | `data/cache/carteira_instrumentos/` | Fluxo dedicado do Relatório 16. |
| Taxas de Juros por Produto | `taxas_juros` | `data/cache/taxas_juros/` | Cache próprio, periodicidade diária. |
| Contribuições FGC/FGCoop | `bloprudencial` | `data/cache/bcb_bloprudencial/` + `data/cache/bloprudencial/` | Usa arquivo BLOPRUDENCIAL mensal do BCB e persistência no manager. |
| Atualizar Base | gerencia todos os caches acima | `data/cache/*` | É a aba de extração + publicação no GitHub Releases. |

## 3) O que a aba “Atualizar Base” realmente atualiza

Na prática, ela executa:
- extração (por período/tipo de cache);
- persistência local (`dados.parquet` + `metadata.json`);
- publicação opcional no GitHub Release `v1.1-cache` do repositório de release.

Se a publicação falhar, o app pode continuar “aparentemente normal” quando:
- ainda existe cache local válido; **ou**
- o fallback remoto do release antigo continua disponível.

## 3.1) Separação runtime × versionado (desde 2026-08-11)

| Diretório | Papel | Git |
|---|---|---|
| `data/bundled/<cache>/` | artefato publicado, **somente-leitura** em runtime | versionado |
| `data/cache/<cache>/` | downloads e extrações do processo em execução | ignorado |

`BaseCache.arquivo_dados` resolve runtime primeiro e cai para o bundled quando
não há cópia local; toda escrita (`salvar_local`, `limpar_local`) usa
`arquivo_dados_runtime`. Assim uma execução do app não degrada mais o dado
publicado no repositório.

Hoje estão em `data/bundled/`: `principal`, `capital`, `bloprudencial`,
`critical_screens` e `derived_metrics`.

> Exceção: `taxas_juros_historico` continua em `data/cache/` porque suas
> dimensões (`dim_*.parquet`), o manifesto e o diretório de staging são
> resolvidos direto por `cache_dir` em pontos de leitura e escrita misturados.
> Movê-lo exige separar esses caminhos antes.

## 4) Checklist objetivo para ficar “clean” no GitHub

1. **Limpar artefatos locais não versionados**
   - `git status --short` deve ficar vazio.
2. **Garantir ignorados corretos**
   - manter `data/cache/` no `.gitignore` (já existe no projeto).
3. **Confirmar branch e remote corretos antes de push**
   - `git remote -v`
   - `git branch --show-current`
4. **Publicar caches via release assets ou via `data/bundled/`**
   - nunca commitar `data/cache/*`; para versionar um artefato, promovê-lo a
     `data/bundled/<cache>/`.
5. **Validar release final**
   - checar se assets `*_dados.parquet` e `*_metadata.json` estão na tag `v1.1-cache`.

## 5) Causas mais comuns de erro “atualizar via backend” e “upload para GitHub”

1. token sem escopo suficiente para Releases;
2. token válido, mas para outro repositório (ex.: publicar em `tomaconta`, código em `tomaconta-dev`);
3. release/tag `v1.1-cache` inexistente no repo de destino;
4. `gh` CLI autenticado em conta sem permissão;
5. inconsistência entre cache local atualizado e publicação remota falha.

## 6) Configuração recomendada para 31/03

- Definir `TOMACONTA_RELEASE_REPO` explicitamente para o repo onde os assets devem ficar.
- Definir preferencialmente `GITHUB_PAT` (ou `GH_TOKEN`) com permissão de escrita em releases/assets.
  - Fine-grained PAT: `Contents: Read and write` no repo de destino.
  - PAT clássico: escopo `repo`.
- Rodar atualização dos caches críticos:
  - `principal`, `capital`, `dre`, `principal_individual`, `dre_individual`, `carteira_instrumentos`, `bloprudencial`, `taxas_juros`.
- Habilitar “publicar automaticamente no GitHub ao concluir”.
- Confirmar, ao final, a presença dos assets no release `v1.1-cache`.
