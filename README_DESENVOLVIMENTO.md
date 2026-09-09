# README de Desenvolvimento

## Checks rápidos antes de merge

Execute o check de unicidade dos rótulos do dispatcher de menu:

```bash
python scripts/check_menu_dispatch_uniqueness.py
```

O comando falha (`exit 1`) quando encontrar rótulos principais duplicados nas branches de nível superior do dispatcher (incluindo `"DRE (Ind. e Congl.)"` e `"Carteira 4.966"`). Seletores auxiliares anteriores ao dispatcher não entram nessa contagem.

## Refresh completo de caches via backend (com snapshot/rollback)

Para reprocessar a janela dos caches preservando o histórico fora dela e criar um snapshot anterior:

```bash
python tools/refresh_cache_backend.py \
  --snapshot-label pre-demo-diretor \
  --reason "refresh completo antes da apresentação" \
  --ano-inicial 2021 --mes-inicial 03 \
  --ano-final 2025 --mes-final 12 \
  --mensal-inicio 202101 --mensal-fim 202512 \
  --batch-size 4 \
  --retry-max 3
```

- O estado anterior é salvo em `data/cache_versions/<timestamp>_<label>` com `manifest.json`.
- O cache novo aprovado também é salvo em `data/cache_versions/<timestamp>_post-<label>`.
- O resumo da execução fica em `data/cache_versions/last_refresh_manifest.json`.
- Cada execução ganha um manifesto próprio em `data/cache_versions/runs/<run_id>.json`.
- `data/cache_versions/` é operacional e local: snapshots e manifestos de execução não devem ser versionados no Git.
- Em caso de falha, o comando sugere automaticamente o `--restore-snapshot` da versão anterior.

Listar snapshots disponíveis:

```bash
python tools/refresh_cache_backend.py --list-snapshots
```

Rollback para uma versão específica:

```bash
python tools/refresh_cache_backend.py --restore-snapshot 20260330-220000_pre-demo-diretor
```

> Dica: rode esse refresh fora da janela após 22h para reduzir incidência de instituições com nome "IF <código>".

## Estado e validação de Atualizar Base

A UI e os dois CLIs usam a mesma trava administrativa. O manager confirma somente períodos persistidos; uma extração parcial retorna insucesso com `persisted_periods`, `pending_periods`, `failed_periods` e estado explícito. O resultado agregado por cache bloqueia uma republicação posterior enquanto houver pendências.

Nos relatórios IFData trimestrais, `incremental` e `overwrite` preservam os períodos fora da janela selecionada; `rebuild` é a reconstrução integral explícita. Adaptadores de outras fontes conservam seus contratos específicos. O snapshot do backend cobre `data/cache`; a restauração não desfaz assets remotos nem arquivos versionados de `data/bundled`.

Testes direcionados, sem credenciais ou serviços reais:

```bash
.venv/bin/python -m pytest -q tests/test_update_state.py tests/test_update_manager.py tests/test_update_catalog.py tests/test_atualizar_base_ui.py tests/test_publication_preflight.py tests/test_update_cli_contract.py tests/test_runtime_diagnostics.py tests/test_release_ops.py tests/test_refresh_cache_backend.py
```

O procedimento operacional está em [docs/runbook_cache_release.md](docs/runbook_cache_release.md). A publicação de um pacote e sua ativação nas telas devem ser verificadas separadamente.
