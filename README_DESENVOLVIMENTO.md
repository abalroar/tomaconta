# README de Desenvolvimento

## Checks rápidos antes de merge

Execute o check de unicidade dos rótulos do dispatcher de menu:

```bash
python scripts/check_menu_dispatch_uniqueness.py
```

O comando falha (`exit 1`) quando encontrar duplicidade em `elif menu == "..."` (incluindo os rótulos críticos `"DRE (Ind. e Congl.)"` e `"Carteira 4.966"`).

## Refresh completo de caches via backend (com snapshot/rollback)

Para reconstruir todos os caches em modo substituição (`overwrite`) sem perder a versão antiga:

```bash
python tools/refresh_cache_backend.py \
  --snapshot-label pre-demo-diretor \
  --reason "refresh completo antes da apresentação" \
  --ano-inicial 2021 --mes-inicial 03 \
  --ano-final 2025 --mes-final 12 \
  --mensal-inicio 202101 --mensal-fim 202512
```

- O estado anterior é salvo em `data/cache_versions/<timestamp>_<label>` com `manifest.json`.
- O resumo da execução fica em `data/cache_versions/last_refresh_manifest.json`.

Listar snapshots disponíveis:

```bash
python tools/refresh_cache_backend.py --list-snapshots
```

Rollback para uma versão específica:

```bash
python tools/refresh_cache_backend.py --restore-snapshot 20260330-220000_pre-demo-diretor
```

> Dica: rode esse refresh fora da janela após 22h para reduzir incidência de instituições com nome "IF <código>".
