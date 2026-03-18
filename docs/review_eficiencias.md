# Revisão de Eficiências — tomaconta.streamlit.app

> **Objetivo:** Mapear ineficiências de baixo custo de correção e alto benefício nas dimensões de código/implementação, experiência do usuário (UX) e uso de dados/cache.
> **Metodologia:** Análise estática do repositório com priorização por impacto × esforço.
> **Data:** Março 2026

---

## Sumário Executivo

O repositório apresenta uma arquitetura de cache sofisticada e uma camada de visualização rica. Os ganhos mais imediatos estão concentrados em três frentes:

| Frente | Maior problema hoje | Benefício estimado |
|--------|--------------------|--------------------|
| Código | `app1.py` com 15 576 linhas | Manutenibilidade crítica |
| Segurança | Senha admin no código-fonte | Risco imediato |
| UX | Feedback de carregamento inconsistente | Percepção de lentidão |
| Cache/Dados | TTLs e nomes mágicos espalhados | Bugs silenciosos |

---

## 1. Segurança — Custo Baixo, Benefício Imediato

### 1.1 Senha hardcoded no código-fonte

**Arquivo:** `app1.py:735`

```python
# ATUAL — expõe credencial no repositório
SENHA_ADMIN = "m4th3u$987"
```

**Correção:**
```python
# CORRIGIDO — lê do ambiente ou de st.secrets
import os
SENHA_ADMIN = os.environ.get("ADMIN_PASSWORD") or st.secrets.get("ADMIN_PASSWORD", "")
```

**Impacto:** Qualquer pessoa com acesso ao repositório pode atualizar o cache de produção.
**Esforço:** 5 minutos + adicionar variável no Streamlit Cloud Secrets.

---

## 2. Arquitetura — Custo Médio, Benefício Alto

### 2.1 Arquivo único com 15 576 linhas (`app1.py`)

**Problema:** 185 funções top-level, 277 definições de `def` no mesmo arquivo. Isso torna:
- Navegação e revisões de código lentas
- Diffs de PR ilegíveis
- Testes unitários difíceis de isolar

**Proposta de divisão mínima viável:**

```
app1.py (orquestrador — ~500 linhas)
tabs/
  home.py          # pagina_home()
  snapshot.py      # pagina_snapshot()
  evolucao.py      # pagina_evolucao()
  peers.py         # pagina_peers() + helpers _montar_tabela_peers, _render_peers_table_html
  brincar.py       # playground/scatter
  cosif.py         # aba 4060
  admin.py         # aba admin + upload_cache_github
utils/
  formatters.py    # _formatar_valor_peers, formatar_valor, _formatar_percentual, etc.
  periodo.py       # ordenar_periodos, periodo_para_exibicao, _parse_periodo, etc.
  alias.py         # carregar_aliases, aplicar_aliases_em_periodos, etc.
  roe.py           # _fator_anualizacao, _calcular_roe_anualizado, etc.
```

**Critério de corte:** começar pelos módulos com menor acoplamento (`formatters.py` e `periodo.py` são quase sem dependências internas).

**Esforço:** 2–3 dias de refatoração incremental com testes de regressão visuais.

---

## 3. Performance — Custo Baixo, Benefício Visível

### 3.1 `@st.cache_data` com TTLs mágicos e inconsistentes

**Ocorrências:** 30+ decoradores com valores 300, 900, 1800, 3600, 86400.

```python
# ATUAL — valor mágico sem significado semântico
@st.cache_data(ttl=900, show_spinner=False)
def carregar_dados_periodos():
    ...
```

**Correção:**
```python
# constants.py
TTL_CURTO   = 5  * 60   # 5 min  — dados de UI auxiliares
TTL_MEDIO   = 15 * 60   # 15 min — dados de sessão
TTL_PADRAO  = 60 * 60   # 1 h    — dados de cache principal
TTL_DIARIO  = 24 * 60 * 60  # 24 h — dados estáticos

@st.cache_data(ttl=TTL_MEDIO, show_spinner=False)
def carregar_dados_periodos():
    ...
```

**Benefício:** Facilita ajuste de performance sem grep global; semântica auto-documentada.
**Esforço:** 30 minutos.

### 3.2 Variáveis globais não thread-safe

**Arquivo:** `app1.py` — variáveis `_cache_nomes_instituicoes` e `_cache_lucros`

```python
# ATUAL — estado global compartilhado entre sessões concorrentes
_cache_nomes_instituicoes: Dict[str, str] = {}
_cache_lucros: Dict = {}
```

Streamlit executa cada sessão de usuário em threads separadas. Writes simultâneos a dicts globais causam race conditions silenciosos.

**Correção mínima:**
```python
# Mover para session_state (por sessão) ou st.cache_resource com lock
@st.cache_resource
def _get_nomes_cache():
    return {}  # instância compartilhada, mas gerenciada pelo Streamlit
```

**Esforço:** 1–2 horas por variável global afetada.

### 3.3 `@st.cache_data` dentro de funções aninhadas

**Arquivo:** `app1.py:10721–10816` e `12080–12156`

Decoradores `@st.cache_data` declarados dentro de outros escopos impedem o Streamlit de otimizar o hash da função entre reruns, podendo criar entradas de cache duplicadas.

**Correção:** Mover todas as funções `@st.cache_data` para o escopo de módulo (top-level).

**Esforço:** 2–3 horas.

---

## 4. Qualidade de Dados — Custo Baixo, Benefício Alto

### 4.1 Lógica de resolução de nome de instituição em 3 camadas sem cache de falhas

**Arquivo:** `utils/ifdata_extractor.py`

A função de resolução de nomes tenta 3 variantes por instituição a cada chamada, mas não armazena o resultado de lookups que falharam em todas as camadas. Isso provoca repetição de trabalho em reruns.

**Correção:**
```python
# Adicionar entrada sentinela para falhas confirmadas
_NOME_NAO_ENCONTRADO = object()

def resolver_nome(cod):
    if cod in _cache:
        val = _cache[cod]
        return None if val is _NOME_NAO_ENCONTRADO else val
    resultado = _tentar_resolver(cod)
    _cache[cod] = resultado if resultado else _NOME_NAO_ENCONTRADO
    return resultado
```

**Benefício:** Elimina triple-lookup repetido para instituições sem alias.

### 4.2 Ausência de validação de schema na escrita do cache

**Arquivo:** `utils/ifdata_cache/base.py`

O cache salva qualquer DataFrame sem verificar colunas obrigatórias. Uma extração parcial com schema diferente silenciosamente substitui dados válidos.

**Correção mínima:**
```python
SCHEMA_OBRIGATORIO = {
    "principal": ["Instituição", "Período", "CodInst"],
    "dre":       ["Instituição", "Período"],
    # ...
}

def _validar_schema(df: pd.DataFrame, tipo: str) -> None:
    colunas_req = SCHEMA_OBRIGATORIO.get(tipo, [])
    faltando = [c for c in colunas_req if c not in df.columns]
    if faltando:
        raise ValueError(f"Cache '{tipo}' faltando colunas: {faltando}")
```

**Esforço:** 2–3 horas.

### 4.3 Conversão de período duplicada em vários módulos

**Ocorrências:** `periodo_para_exibicao`, `_yyyymm_para_periodo_exibicao`, `_periodo_exibicao_para_api_local`, `_prox_periodo_api` — todas fazem parsing de "YYYYMM" ↔ "M/YYYY" de formas ligeiramente diferentes.

**Correção:** Consolidar em `utils/periodo.py` com um único par `to_display(periodo) / to_api(periodo)` e substituir as chamadas espalhadas.

**Esforço:** 3–4 horas.

---

## 5. UX — Custo Baixo, Benefício Perceptível

### 5.1 Mensagens de erro genéricas ao usuário

**Padrão atual:**
```python
st.error("Erro ao carregar dados. Tente novamente.")
```

**Proposta:**
```python
st.error(
    "Não foi possível carregar os dados de capital. "
    "Verifique sua conexão ou atualize o cache na aba **Admin**."
)
```

**Benefício:** Reduz tickets de suporte e orienta ação corretiva sem abrir o código.
**Esforço:** 1–2 horas de revisão das mensagens de erro principais.

### 5.2 Spinner ausente em operações longas de exportação

As funções `_gerar_excel_peers_tabela` (`app1.py:5864`) e `_gerar_pptx_evolucao` (`app1.py:6180`) podem demorar vários segundos sem feedback visual.

**Correção:**
```python
with st.spinner("Gerando Excel..."):
    dados_excel = _gerar_excel_peers_tabela(...)
st.download_button(...)
```

**Esforço:** 30 minutos.

### 5.3 Seleção de instituição reseta ao trocar de aba

A seleção de banco/instituição não é persistida no `st.session_state` com chave estável quando o usuário navega entre abas, causando resets inesperados.

**Correção:**
```python
# Usar chave estável globalmente
st.selectbox("Instituição", opcoes, key="instituicao_selecionada_global")
```

**Esforço:** 1–2 horas para identificar e padronizar as chaves de session_state das seleções principais.

### 5.4 Feedback de cache desatualizado insuficiente

O usuário não sabe visualmente se os dados são recentes ou velhos. A informação de data do cache existe (`ler_info_cache`, `app1.py:1405`) mas aparece apenas na aba Admin.

**Proposta:** Exibir badge de "dados de MM/YYYY" discretamente no topo de cada aba usando `st.caption`.

```python
st.caption(f"Dados atualizados em {ultima_atualizacao} · {n_periodos} períodos disponíveis")
```

**Esforço:** 1–2 horas.

---

## 6. Manutenibilidade — Custo Baixo, Benefício de Longo Prazo

### 6.1 Números de relatório como literais espalhados

**Ocorrências em `utils/ifdata_cache/`:**
```python
report_id=1   # principal
report_id=2   # ativo
report_id=4   # dre
report_id=5   # capital
```

**Correção:**
```python
# utils/ifdata_cache/constants.py
class RelatorioIFData(IntEnum):
    PRINCIPAL = 1
    ATIVO     = 2
    PASSIVO   = 3
    DRE       = 4
    CAPITAL   = 5
    CARTEIRA_PF         = 11
    CARTEIRA_PJ         = 13
    CARTEIRA_INSTRUMENTOS = 16
```

**Esforço:** 1 hora.

### 6.2 Definições de métricas fragmentadas

Existem pelo menos 3 estruturas separadas definindo as mesmas métricas:
- `DERIVED_METRICS` (lista de nomes)
- `DERIVED_METRICS_FORMAT` (dicionário de formato)
- `DERIVED_METRICS_FORMULAS` (dicionário de fórmulas)

Estas já coexistem com o `metric_registry.py` mais completo. O caminho de curto prazo é migrar os dicionários legados para o registry.

**Benefício:** Uma fonte de verdade por métrica; facilita adicionar/remover métricas sem atualizar 3 lugares.
**Esforço:** 4–6 horas.

### 6.3 Teste de cobertura mínima

Existem apenas 2 arquivos de teste (`test_cache.py` e `test_metric_registry.py`) sem testes de integração para o fluxo crítico de carregamento de dados.

**Adições prioritárias de baixo custo:**
1. `tests/test_periodo.py` — validar todas as funções de conversão de período
2. `tests/test_alias.py` — validar resolução de aliases com fixtures
3. `tests/test_cache_schema.py` — validar que saves de cache rejeitam schemas inválidos

**Esforço:** 3–4 horas para os 3 arquivos.

---

## 7. Dependências — Custo Baixo, Benefício de Estabilidade

### 7.1 Versões não pinadas de forma reproduzível

`requirements.txt` usa `>=` para `pyarrow` e `XlsxWriter`:
```
pyarrow>=14.0.0
XlsxWriter>=3.1,<4
```

Em ambiente de produção (Streamlit Cloud), uma nova versão minor pode quebrar compatibilidade silenciosamente.

**Correção:** Após validação local, pinar versões exatas:
```
pyarrow==14.0.2
XlsxWriter==3.2.0
```

**Esforço:** 30 minutos de teste + pin.

---

## 8. Mapa de Priorização

| # | Item | Custo | Benefício | Dimensão |
|---|------|-------|-----------|----------|
| 1 | Mover senha para env/secrets | Baixíssimo | Segurança crítica | Segurança |
| 2 | Constantes de TTL semânticas | Baixíssimo | Manutenibilidade | Código |
| 3 | Spinners em exportações | Baixíssimo | UX | UX |
| 4 | Mensagens de erro contextuais | Baixo | UX + Suporte | UX |
| 5 | Badge de atualização de dados | Baixo | UX | UX |
| 6 | Enum para IDs de relatório | Baixo | Manutenibilidade | Código |
| 7 | Cache de falhas de nome inst. | Baixo | Performance | Cache |
| 8 | Validação de schema no cache | Médio | Qualidade de dados | Cache |
| 9 | Consolidar funções de período | Médio | Manutenibilidade | Código |
| 10 | Migrar métricas para registry | Médio | Manutenibilidade | Código |
| 11 | Mover `@cache_data` para top-level | Médio | Performance | Código |
| 12 | Corrigir variáveis globais | Médio | Estabilidade | Código |
| 13 | Testes de integração (3 arquivos) | Médio | Qualidade | Testes |
| 14 | Split de `app1.py` em módulos | Alto | Manutenibilidade | Arquitetura |
| 15 | Pinagem de dependências | Baixíssimo | Estabilidade | Deps |

---

## 9. Prompt Reutilizável para Revisões Futuras

O prompt abaixo pode ser usado como base para futuras revisões incrementais do repositório:

```
Analise o repositório tomaconta com foco em melhorias de baixo custo e alto benefício.
Para cada arquivo ou módulo indicado, identifique:

1. SEGURANÇA
   - Credenciais, tokens ou senhas no código-fonte ou em arquivos versionados
   - Inputs de usuário sem sanitização
   - Dependências com CVEs conhecidos

2. PERFORMANCE
   - Funções chamadas repetidamente que poderiam ser cacheadas
   - Operações síncronas que bloqueiam a UI sem feedback
   - Variáveis globais mutáveis compartilhadas entre sessões Streamlit
   - @st.cache_data ou @st.cache_resource declarados em escopos aninhados

3. QUALIDADE DE CÓDIGO
   - Funções ou constantes duplicadas que poderiam ser consolidadas
   - Números mágicos (TTLs, IDs de relatório, índices de coluna)
   - Funções com mais de 100 linhas que poderiam ser divididas
   - Módulos com mais de 500 linhas sem separação clara de responsabilidades

4. QUALIDADE DE DADOS
   - Ausência de validação de schema em leitura/escrita de cache
   - Conversões de formato de dado (período, moeda, %) duplicadas
   - Lookups sem cache de resultados negativos

5. UX
   - Operações longas sem spinner ou barra de progresso
   - Mensagens de erro genéricas sem orientação de ação
   - Estado de seleção do usuário que se perde ao mudar de aba
   - Dados sem indicação de "última atualização"

6. MANUTENIBILIDADE
   - Definições de métricas ou mappings em mais de um lugar
   - Ausência de testes para funções utilitárias críticas
   - Dependências com versões não pinadas

Para cada item encontrado: indique o arquivo e linha, descreva o problema em 1–2 frases,
e forneça a correção mínima com exemplo de código. Ordene por impacto × facilidade de
implementação, do maior para o menor.
```

---

*Documento gerado por análise estática do repositório — Março 2026.*
