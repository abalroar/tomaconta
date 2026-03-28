# toma.conta

**análise de instituições financeiras brasileiras**

Plataforma web que consolida dados oficiais do Banco Central do Brasil para análise comparativa de instituições financeiras, com foco em leitura rápida, filtros reproduzíveis e exportação.

> Desenvolvido por Matheus Prates, CFA

---

## Sumário

- [Visão Geral](#visão-geral)
- [Módulos de Análise](#módulos-de-análise)
- [Indicadores e Métricas](#indicadores-e-métricas)
- [Recursos Operacionais](#recursos-operacionais)
- [Como Usar](#como-usar)
- [Instalação e Execução](#instalação-e-execução)
- [Arquitetura de Dados](#arquitetura-de-dados)
- [Sistema de Cache](#sistema-de-cache)
- [Stack Tecnológica](#stack-tecnológica)
- [Estrutura do Projeto](#estrutura-do-projeto)
- [Bot Telegram — URA](#bot-telegram--ura)

---

## Visão Geral

O **toma.conta** centraliza em uma única interface os dados do [IF.data (BCB)](https://www3.bcb.gov.br/ifdata/) e de relatórios oficiais do Banco Central, permitindo:

- Comparar indicadores entre múltiplas instituições financeiras
- Acompanhar a evolução temporal de métricas regulatórias e de resultado
- Criar métricas personalizadas a partir de variáveis brutas
- Exportar análises em Excel, CSV e PowerPoint

Os dados são sempre originados de fontes oficiais do BCB (API Olinda, IFData, BLOPRUDENCIAL).

---

## Módulos de Análise

### Menu Principal

| Módulo | Tipo | Descrição |
|---|---|---|
| **Snapshot** | Briefing | Painel executivo por instituição, design mobile-first. Leitura rápida dos principais indicadores em uma tela. |
| **Rankings** | Ranking | Ordene qualquer indicador entre todas as instituições em um período selecionado. Exibe variação e comparação imediata. |
| **Peers (Tabela)** | Comparativo | Compare até múltiplos bancos em até 3 períodos simultâneos, com variação anual calculada automaticamente. |
| **Conselho e Diretoria** | Cadastro | Consulta de composição de conselho e diretoria por conglomerado prudencial, via BLOPRUDENCIAL. |
| **Evolução** | Tendência | Séries temporais para identificar aceleração, desaceleração ou estabilidade em qualquer indicador. |
| **Scatter Plot** | Relação X/Y | Visualize a relação entre dois indicadores, com tamanho de bolha configurável por uma terceira variável. |
| **DRE** | Resultado | Demonstração do Resultado na visão de Conglomerado Prudencial — receitas, despesas e margens. |
| **DRE Individual** | Resultado | DRE na visão de instituição individual (banco isolado, sem conglomerado). |
| **DRE (Ind. e Congl.)** | Resultado | Painel alternável entre DRE Individual e DRE Conglomerado Prudencial para facilitar a comparação de visões. |
| **Carteira 4.966** | Risco | Qualidade da carteira de crédito por classe de risco (AA a H), com foco em classes críticas (D–H). Baseado na Resolução CMN 4.966. |
| **Taxas de Juros por Produto** | Juros | Taxas médias por modalidade de crédito (PF e PJ) e evolução temporal. |
| **Crie sua métrica!** | Custom | Construtor de métricas: combine variáveis brutas com operações aritméticas para criar indicadores personalizados. |
| **Contribuições FGC/FGCoop** | Contribuições | Análise de contribuições ao FGC e FGCoop por período e instituição. |

### Menu Secundário (Utilitários)

| Módulo | Descrição |
|---|---|
| **Sobre** | Apresentação da plataforma, módulos e stack tecnológica. |
| **Atualizar Base** | Interface para atualização do cache local e publicação via GitHub Releases. |
| **Glossário** | Documentação técnica completa de todas as métricas: fórmulas, fontes e conceitos. |

---

## Indicadores e Métricas

### Estrutura Patrimonial
- Ativo Total
- Ativos Líquidos
- Carteira de Crédito Classificada e Líquida
- Títulos e Valores Mobiliários
- Depósitos e Captações / Core Funding
- Patrimônio Líquido
- Lucro Líquido Acumulado (YTD)

### Capital e Prudencial
- Capital Principal (Tier 1 / CET1)
- Capital Complementar e Capital Nível II
- Patrimônio de Referência
- RWA Total, de Crédito, de Mercado, Operacional e Outros
- Exposição Total
- Índice de Capital Principal (CET1)
- Índice de Basileia
- Razão de Alavancagem

### Métricas Derivadas
- ROE Acumulado Anualizado (%)
- Ativo / PL
- Crédito / PL (%)
- Crédito / Captações (%)
- Perda Esperada / Carteira
- PDD Total e Índices de Cobertura

### Outros Blocos
- Carteira 4.966 por classe de risco (AA, A, B, C, D, E, F, G, H)
- Taxas de Juros por Produto (PF e PJ)
- Composição do Conselho e Diretoria por Conglomerado

> **Nota:** O ROE é anualizado por competência (Mar × 4, Jun × 2, Set × 1,33, Dez × 1). Consulte o **Glossário** no app para ver todas as fórmulas.

---

## Recursos Operacionais

| Recurso | Descrição |
|---|---|
| **Filtros inteligentes** | Seleção por lista customizada, recorte por período e universo configurável. |
| **Nomenclatura personalizada** | Sistema de aliases: normalize nomes e defina cores por instituição para manter consistência visual entre análises. |
| **Exportação** | Excel (multi-aba), CSV e PowerPoint nas visões tabulares e gráficas. |
| **Dados oficiais** | Fontes exclusivamente oficiais do BCB: IF.data (Rel. 1–16), Relatório 5 (Capital Prudencial), COSIF/Cadoc 4060, BLOPRUDENCIAL. |
| **Modo diagnóstico** | Exibe uso de memória, tamanho do recorte do cache derivado e tempos de execução por tela. |

---

## Como Usar

```
1. Selecione o módulo com foco no objetivo
   → Rankings, Peers, Evolução, Scatter, DRE,
     Carteira 4.966, Taxas, Conselho ou Métrica Customizada

2. Defina período e instituições
   → Ajuste o recorte comparativo com período e lista de bancos

3. Aplique filtros e aliases
   → Padronize nomes e cores para consistência visual

4. Consulte o Glossário
   → Valide fórmulas e conceitos antes de concluir

5. Exporte os resultados
   → Excel/CSV para compartilhar ou incluir em relatórios
```

---

## Instalação e Execução

### Pré-requisitos

- Python 3.10 ou superior
- pip

### Instalação

```bash
git clone https://github.com/abalroar/tomaconta.git
cd tomaconta
pip install -r requirements.txt
```

### Executar o app

```bash
streamlit run app1.py
```

O app abre automaticamente em `http://localhost:8501`.

### Executar o bot Telegram (URA)

Consulte a seção [Bot Telegram — URA](#bot-telegram--ura).

---

## Arquitetura de Dados

### Fontes

| Fonte | Dados |
|---|---|
| **API Olinda / BCB** | Dados cadastrais e indicadores gerais das IFs |
| **IFData Relatório 1** | Principal — dados gerais, patrimônio, ativos |
| **IFData Relatório 2** | Composição do Ativo |
| **IFData Relatório 3** | Composição do Passivo |
| **IFData Relatório 4** | DRE (Demonstração do Resultado) |
| **IFData Relatório 5** | Capital Regulatório e Prudencial |
| **IFData Relatório 11** | Carteira de Crédito PF |
| **IFData Relatório 13** | Carteira de Crédito PJ |
| **IFData Relatório 16** | Carteira Instrumento (Resolução 4.966) |
| **Cadoc 4060** | Demonstrativo de Contabilidade (COSIF) |
| **BLOPRUDENCIAL** | Conselho e Diretoria |

### Pipeline

```
Ingestão (API BCB/IFData)
    ↓
Staging (cache local — parquet + JSON de metadados)
    ↓
Curadoria (métricas derivadas em formato longo)
    ↓
Consumo (telas/tabs do Streamlit)
    ↓
Exportação (Excel / CSV / PowerPoint)
```

---

## Sistema de Cache

O cache é fundamental para a performance do app. Os dados são armazenados localmente em arquivos **Parquet** com metadados em JSON.

### Tipos de cache

| Tipo | Conteúdo |
|---|---|
| `principal` | Dados gerais das IFs (Rel. 1) |
| `capital` | Capital regulatório (Rel. 5) |
| `ativo` | Composição do ativo (Rel. 2) |
| `passivo` | Composição do passivo (Rel. 3) |
| `dre` | Demonstração do resultado (Rel. 4) |
| `carteira_pf` | Carteira PF (Rel. 11) |
| `carteira_pj` | Carteira PJ (Rel. 13) |
| `carteira_instrumentos` | Carteira 4.966 (Rel. 16) |
| `taxas_juros` | Taxas por produto |

### Atualização do cache

Use o menu **Atualizar Base** dentro do app para:
- Disparar a atualização incremental dos caches locais
- Publicar os arquivos atualizados via **GitHub Releases**

Os caches também podem ser gerenciados via CLI:

```bash
python tools/update_caches_cli.py
```

---

## Stack Tecnológica

| Componente | Versão | Função |
|---|---|---|
| **Python** | 3.10+ | Linguagem base |
| **Streamlit** | 1.53.1 | Interface web interativa |
| **Pandas** | 2.3.3 | Processamento e análise de dados |
| **NumPy** | 2.4.1 | Computação numérica e vetorização |
| **Plotly** | 6.5.2 | Visualizações dinâmicas e interativas |
| **Altair** | 6.0.0 | Visualizações estatísticas |
| **Matplotlib** | 3.10.1 | Gráficos auxiliares e exportações |
| **PyArrow** | ≥14.0 | Leitura/escrita de arquivos Parquet |
| **OpenPyXL** | 3.1.5 | Leitura de Excel |
| **XlsxWriter** | ≥3.1 | Exportação avançada para Excel |
| **python-pptx** | 0.6.23 | Geração de apresentações PowerPoint |
| **Pillow** | 12.1.0 | Tratamento de imagens e assets |
| **Requests** | 2.32.5 | Integrações HTTP e consumo de APIs |
| **GitPython** | 3.1.46 | Operações Git para publicação do cache |
| **API BCB Olinda** | — | Fonte oficial de dados |

---

## Estrutura do Projeto

```
tomaconta/
├── app1.py                        # Aplicação principal (Streamlit)
├── requirements.txt               # Dependências Python
├── telegram_ura.py                # Bot Telegram — URA interativa
├── .streamlit/
│   └── config.toml                # Configuração visual do Streamlit
├── data/
│   ├── Aliases.xlsx               # Aliases de nomes de instituições
│   ├── dre_mapping.json           # Mapeamento de contas DRE
│   ├── dre_cosif_mapping.json     # Mapeamento DRE → COSIF
│   ├── instituicoes_fallback.json # Base estática de nomes de IFs
│   ├── balanco_4060_schema_table.csv
│   ├── logo.jpg / logo.png
│   └── cache/                     # Caches parquet (gerados em runtime)
├── data_sources/
│   └── cosif_metadata.py          # Metadados de códigos COSIF
├── utils/
│   ├── formatting.py              # Formatadores de número (BR)
│   ├── cosif_pdf_mapping.py       # Mapeamento COSIF → PDF
│   ├── capital_extractor.py       # Extração de dados de capital
│   ├── ifdata_extractor.py        # Extração via API IFData
│   └── ifdata_cache/              # Sistema de cache unificado
│       ├── manager.py             # CacheManager (API principal)
│       ├── metric_registry.py     # Registro central de métricas
│       ├── principal.py           # Cache de dados gerais
│       ├── capital.py             # Cache de capital regulatório
│       ├── ativo.py               # Cache de composição do ativo
│       ├── passivo.py             # Cache de composição do passivo
│       ├── dre.py                 # Cache de DRE
│       ├── carteira_pf.py         # Cache de carteira PF
│       ├── carteira_pj.py         # Cache de carteira PJ
│       ├── carteira_instrumentos.py # Cache de carteira 4.966
│       ├── taxas_juros.py         # Cache de taxas de juros
│       └── derived_metrics.py     # Métricas derivadas/calculadas
├── tools/
│   ├── update_caches_cli.py       # CLI para atualização de caches
│   └── benchmark_critical_screens.py
├── tests/
│   ├── test_metric_registry.py
│   ├── test_cache.py
│   └── check_derived_metrics.py
└── docs/
    ├── data_pipeline.md
    ├── metric_registry.md
    └── baseline_critical_screens.md
```

---

## Bot Telegram — URA

O arquivo `telegram_ura.py` implementa uma **URA interativa** (menu navegável via teclado inline) no Telegram que disponibiliza o conteúdo de **Como Usar** e a documentação dos módulos diretamente no chat.

### Funcionalidades

- Menu principal navegável com botões inline
- Seção **Como Usar** (passo a passo)
- Descrição detalhada de cada módulo
- Lista de indicadores disponíveis por categoria
- Acesso ao Glossário resumido
- Recursos operacionais (exportação, aliases, etc.)

### Configuração

1. Crie um bot no [@BotFather](https://t.me/BotFather) e obtenha o token
2. Defina a variável de ambiente:

```bash
export TELEGRAM_BOT_TOKEN="seu_token_aqui"
```

3. Instale a dependência adicional:

```bash
pip install python-telegram-bot==20.7
```

4. Execute o bot:

```bash
python telegram_ura.py
```

### Comandos disponíveis

| Comando | Descrição |
|---|---|
| `/start` | Abre o menu principal da URA |
| `/help` | Exibe ajuda rápida e lista de comandos |
| `/como_usar` | Passo a passo de uso da plataforma |
| `/modulos` | Lista todos os módulos de análise |
| `/indicadores` | Indicadores e métricas disponíveis |
| `/stack` | Stack tecnológica do projeto |

---

*Ferramenta open-source para análise de instituições financeiras brasileiras.*
