# README de Desenvolvimento

## Checks rápidos antes de merge

Execute o check de unicidade dos rótulos do dispatcher de menu:

```bash
python scripts/check_menu_dispatch_uniqueness.py
```

O comando falha (`exit 1`) quando encontrar duplicidade em `elif menu == "..."` (incluindo os rótulos críticos `"DRE (Ind. e Congl.)"` e `"Carteira 4.966"`).
