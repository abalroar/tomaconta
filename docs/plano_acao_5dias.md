# Plano de Ação — 5 dias × 2h/dia
## tomaconta · Sprint de Eficiências

> **Ritmo:** 2 horas por dia, preferencialmente em bloco contínuo.
> **Critério de corte:** cada dia termina com código funcionando e testável — sem WIP aberto.
> **Referência:** `docs/review_eficiencias.md`

---

## Visão Geral da Semana

```
Dia 1 ── Segurança + Constantes          (itens 1, 2, 15 da review)
Dia 2 ── UX rápida                       (itens 3, 4, 5)
Dia 3 ── Qualidade de Dados              (itens 7, 8, 9)
Dia 4 ── Manutenibilidade do Código      (itens 6, 10, 11)
Dia 5 ── Testes + Variáveis Globais      (itens 12, 13)
```

Ao final dos 5 dias o `app1.py` ainda existirá como monolito (o split completo exige uma sprint própria), mas estará mais seguro, mais rápido para o usuário e com fundações para o refactor maior.

---

## Dia 1 — Segurança + Constantes `(~2h)`

**Meta:** zero credenciais no código; zero números mágicos de TTL.

### Bloco A — 30 min · Senha para secrets

1. Abrir `app1.py:735`
2. Substituir:
   ```python
   # ANTES
   SENHA_ADMIN = "m4th3u$987"

   # DEPOIS
   import os
   SENHA_ADMIN = st.secrets.get("ADMIN_PASSWORD", os.environ.get("ADMIN_PASSWORD", ""))
   ```
3. No Streamlit Cloud → **Secrets** → adicionar:
   ```toml
   ADMIN_PASSWORD = "m4th3u$987"
   ```
4. Testar localmente com variável de ambiente: `ADMIN_PASSWORD=m4th3u$987 streamlit run app1.py`

### Bloco B — 60 min · Arquivo `utils/constants.py`

Criar `utils/constants.py` com:

```python
# TTLs de cache Streamlit (segundos)
TTL_CURTO   = 5  * 60    # dados auxiliares de UI
TTL_MEDIO   = 15 * 60    # dados de sessão
TTL_PADRAO  = 60 * 60    # dados de cache principal (padrão)
TTL_DIARIO  = 24 * 60 * 60  # dados estáticos

# Delay entre chamadas de API (segundos)
API_RATE_LIMIT_S = 1.5

# Expiração de cache local (dias)
CACHE_EXPIRACAO_DIAS = 7
```

Substituir em `app1.py` todos os `ttl=300`, `ttl=900`, `ttl=1800`, `ttl=3600`, `ttl=86400` pelos nomes semânticos.
Substituir `1.5` de rate limit pelo `API_RATE_LIMIT_S`.

### Bloco C — 30 min · Pinar dependências

1. Rodar `pip freeze | grep -E "pyarrow|XlsxWriter"` para obter versões exatas do ambiente atual
2. Atualizar `requirements.txt` de `>=` para `==` nessas duas linhas
3. Commit + push

**Entrega do dia:** app roda igual, sem credencial no código, sem número mágico de TTL.

---

## Dia 2 — UX Rápida `(~2h)`

**Meta:** usuário percebe que o app responde e o orienta quando algo falha.

### Bloco A — 30 min · Spinners nas exportações

Localizar em `app1.py` os botões de download que chamam as funções de geração e envolvê-los:

```python
# Padrão a aplicar em todos os download_button de Excel/PPTX
if st.button("Exportar Excel", ...):
    with st.spinner("Gerando planilha..."):
        dados = _gerar_excel_peers_tabela(...)
    st.download_button("Baixar", dados, ...)
```

Funções alvo: `_gerar_excel_peers_tabela` (l. 5864), `_gerar_pptx_evolucao` (l. 6180),
`_gerar_excel_evolucao_tabela_visual` (l. 6055), `_gerar_excel_peers_dados_puros` (l. 5969).

### Bloco B — 45 min · Mensagens de erro contextuais

Buscar no arquivo: `st.error(` e `st.warning(` com mensagens genéricas.
Substituir seguindo o padrão: **o quê falhou + o que fazer**.

Exemplos de substituição:

| Antes | Depois |
|-------|--------|
| `"Erro ao carregar dados."` | `"Não foi possível carregar os dados principais. Atualize o cache na aba **Admin**."` |
| `"Dados indisponíveis."` | `"Dados de capital não encontrados para o período selecionado."` |
| `"Erro inesperado."` | `"Erro interno ao processar métricas derivadas. Verifique o log na aba Admin."` |

### Bloco C — 45 min · Badge de atualização no topo das abas

1. Extrair a lógica de `ler_info_cache()` (l. 1405) para retornar data e contagem de períodos
2. Criar helper:
   ```python
   def _caption_cache_status(tipo: str) -> None:
       info = ler_info_cache()
       data = info.get(tipo, {}).get("ultima_atualizacao", "desconhecida")
       n    = info.get(tipo, {}).get("n_periodos", "?")
       st.caption(f"Dados de **{tipo}** · última extração: {data} · {n} períodos")
   ```
3. Chamar `_caption_cache_status("principal")` no início de cada aba principal (Snapshot, Evolução, Peers)

**Entrega do dia:** exportações com spinner, erros com instrução, abas com data dos dados.

---

## Dia 3 — Qualidade de Dados `(~2h)`

**Meta:** cache mais seguro contra dados corrompidos; lookup de nomes sem repetição.

### Bloco A — 45 min · Cache de falhas de lookup de nome

Em `utils/ifdata_extractor.py`, localizar a função principal de resolução de nome de instituição e adicionar sentinela:

```python
_NOME_NAO_ENCONTRADO = object()  # sentinela — distingue "não buscado" de "buscado e vazio"

def _buscar_nome_instituicao(cod: str) -> Optional[str]:
    if cod in _cache_nomes_instituicoes:
        val = _cache_nomes_instituicoes[cod]
        return None if val is _NOME_NAO_ENCONTRADO else val

    resultado = _tentar_tres_variantes(cod)  # lógica atual
    _cache_nomes_instituicoes[cod] = resultado if resultado else _NOME_NAO_ENCONTRADO
    return resultado
```

### Bloco B — 45 min · Validação de schema no cache

Em `utils/ifdata_cache/base.py`, adicionar antes de qualquer `to_parquet`:

```python
# No topo do arquivo
_SCHEMA_MINIMO: dict[str, list[str]] = {
    "principal":   ["Instituição", "Período", "CodInst"],
    "capital":     ["Instituição", "Período"],
    "dre":         ["Instituição", "Período"],
    "ativo":       ["Instituição", "Período"],
    "passivo":     ["Instituição", "Período"],
    "bloprudencial": ["Conglomerado", "Período"],
}

def _validar_schema(df: pd.DataFrame, tipo_cache: str) -> None:
    colunas_req = _SCHEMA_MINIMO.get(tipo_cache, [])
    faltando = [c for c in colunas_req if c not in df.columns]
    if faltando:
        raise ValueError(
            f"[Cache '{tipo_cache}'] Schema inválido — colunas faltando: {faltando}. "
            f"Colunas presentes: {list(df.columns[:10])}"
        )
```

Chamar `_validar_schema(df, self.tipo_cache)` antes de cada `df.to_parquet(...)`.

### Bloco C — 30 min · Criar `utils/periodo.py` com funções canônicas

Criar o arquivo com as duas funções de conversão que eliminam as 4 variantes atuais:

```python
"""Conversões canônicas de período YYYYMM ↔ M/YYYY."""

def to_display(periodo: str) -> str:
    """'202312' → '12/2023'"""
    ano, mes = periodo[:4], periodo[4:6]
    return f"{int(mes)}/{ano}"

def to_api(periodo_display: str) -> str:
    """'12/2023' → '202312'"""
    mes, ano = periodo_display.split("/")
    return f"{ano}{int(mes):02d}"
```

Deixar as funções originais em `app1.py` chamando as canônicas (não excluir ainda — evita risco de regressão).

**Entrega do dia:** cache rejeita dados corrompidos em tempo de salvamento; lookups de nome não repetem trabalho.

---

## Dia 4 — Manutenibilidade do Código `(~2h)`

**Meta:** uma fonte de verdade para IDs de relatório e métricas derivadas; `@cache_data` fora de escopos aninhados.

### Bloco A — 45 min · Enum de relatórios IFData

Em `utils/constants.py` (criado no Dia 1), adicionar:

```python
from enum import IntEnum

class RelatorioIFData(IntEnum):
    PRINCIPAL              = 1
    ATIVO                  = 2
    PASSIVO                = 3
    DRE                    = 4
    CAPITAL                = 5
    CARTEIRA_PF            = 11
    CARTEIRA_PJ            = 13
    CARTEIRA_INSTRUMENTOS  = 16
```

Substituir literais `report_id=1`, `report_id=4`, etc. em `utils/ifdata_cache/` pelos enum values.

### Bloco B — 45 min · Mover `@cache_data` de escopos aninhados

Localizar e mover para top-level as funções com `@st.cache_data` declaradas dentro de outras funções
(linhas 10721–10816 e 12080–12156 de `app1.py`). O padrão é:

```python
# ANTES — dentro de outra função
def pagina_brincar():
    @st.cache_data(ttl=3600)
    def _get_dados_scatter(periodo):
        ...

# DEPOIS — top-level
@st.cache_data(ttl=TTL_PADRAO)
def _get_dados_scatter(periodo):
    ...

def pagina_brincar():
    ...  # usa _get_dados_scatter diretamente
```

### Bloco C — 30 min · Iniciar migração de métricas fragmentadas

Identificar as 3 estruturas duplicadas em `app1.py`:
- `DERIVED_METRICS` (lista)
- `DERIVED_METRICS_FORMAT` (dict)
- `DERIVED_METRICS_FORMULAS` (dict)

Para cada métrica ausente no `metric_registry.py`, adicionar entrada seguindo o padrão já existente no registry.
Não deletar as estruturas legadas ainda — apenas garantir que o registry as contenha.

**Entrega do dia:** IDs de relatório legíveis; cache sem escopos aninhados; registry com cobertura completa das métricas.

---

## Dia 5 — Testes + Variáveis Globais `(~2h)`

**Meta:** os 3 módulos utilitários críticos com testes; variáveis globais com proteção mínima.

### Bloco A — 30 min · Corrigir variáveis globais

Em `app1.py`, localizar `_cache_nomes_instituicoes` e `_cache_lucros` (dicts globais mutáveis).
Envolvê-los em `st.cache_resource` para que o Streamlit gerencie o ciclo de vida:

```python
@st.cache_resource
def _get_cache_nomes() -> dict:
    return {}

@st.cache_resource
def _get_cache_lucros() -> dict:
    return {}

# Substituir todas as referências diretas:
# _cache_nomes_instituicoes[k] → _get_cache_nomes()[k]
```

### Bloco B — 90 min · Três arquivos de teste

**`tests/test_periodo.py`** (~20 min)
```python
from utils.periodo import to_display, to_api
import pytest

@pytest.mark.parametrize("api,display", [
    ("202312", "12/2023"),
    ("202403", "3/2024"),
    ("202001", "1/2020"),
])
def test_to_display(api, display):
    assert to_display(api) == display

def test_roundtrip(api="202312"):
    assert to_api(to_display(api)) == api
```

**`tests/test_alias.py`** (~35 min)
```python
import pandas as pd
from app1 import construir_dict_aliases_normalizado, aplicar_aliases_em_periodos

def test_alias_simples():
    df_aliases = pd.DataFrame({
        "CodInst": ["1"],
        "Alias": ["Banco Teste"],
    })
    # Verificar que o dict é construído e aplicado corretamente
    ...

def test_alias_sem_dados_nao_quebra():
    result = aplicar_aliases_em_periodos({}, {})
    assert result == {}
```

**`tests/test_cache_schema.py`** (~35 min)
```python
import pandas as pd
import pytest
from utils.ifdata_cache.base import _validar_schema

def test_schema_valido():
    df = pd.DataFrame({"Instituição": ["A"], "Período": ["202312"], "CodInst": ["1"]})
    _validar_schema(df, "principal")  # não deve levantar

def test_schema_faltando_coluna():
    df = pd.DataFrame({"Instituição": ["A"], "Período": ["202312"]})
    with pytest.raises(ValueError, match="CodInst"):
        _validar_schema(df, "principal")

def test_schema_tipo_desconhecido_passa():
    df = pd.DataFrame({"qualquer": [1]})
    _validar_schema(df, "tipo_novo")  # schema não definido → não bloqueia
```

Rodar `pytest tests/ -v` e garantir verde antes de commitar.

**Entrega do dia:** variáveis globais thread-safer; 3 suítes de teste cobrindo período, alias e schema.

---

## Checklist de Encerramento da Sprint

```
[ ] Dia 1 — Senha em secrets, constants.py criado, deps pinadas
[ ] Dia 2 — Spinners, erros contextuais, badges de data
[ ] Dia 3 — Sentinela de lookup, validação de schema, utils/periodo.py
[ ] Dia 4 — Enum de relatórios, cache fora de escopos aninhados, registry completo
[ ] Dia 5 — Variáveis globais com cache_resource, 3 arquivos de teste passando
```

**O que NÃO entra nesta sprint:**
- Split de `app1.py` em módulos (requer sprint própria de 3–5 dias)
- Refactor completo de session_state
- Migração de exportação para worker assíncrono

---

*Plano de ação gerado a partir de `docs/review_eficiencias.md` — Março 2026.*
