# Limpeza de arquivos — 2026-03-31

## Critério adotado
- Remover **somente** arquivos sem qualquer referência no código de runtime do app (`app1.py`) e sem impacto nas abas oficiais do Streamlit.
- Não remover arquivos de suporte operacional (cache, mapeamentos, aliases, ferramentas de atualização) para evitar regressões fora da UI.

## Arquivos removidos
1. `logo.jpg` (raiz do repositório)
   - Não há referência no app.
   - O app usa `data/logo.jpg` como fonte oficial de logo.
2. `data/newlogo.png`
   - Não há referência no app nem nos utilitários.
3. `data/logo.png`
   - Não há referência no app nem nos utilitários.

## Arquivos mantidos por segurança
- `data/logo.jpg` (logo carregado pelo app).
- `data/Aliases.xlsx`, `data/dre_mapping.json`, `data/dre_cosif_mapping.json`, `data/instituicoes_fallback.json` (dependências diretas de leitura de dados).
- `data/cache/**` (cache e metadados de operação).
- `tools/**`, `tests/**`, `docs/**` (não usados em abas de produção, mas úteis para manutenção/qualidade).

## Verificação pós-limpeza
- Busca textual por referências aos arquivos removidos: nenhuma ocorrência.
- Compilação sintática de `app1.py` sem erros.
