"""Cache do SCR.data (Sistema de Informações de Créditos) do BCB.

O SCR.data não possui API: o BCB publica ZIPs anuais contendo um CSV por
data-base em ``https://www.bcb.gov.br/pda/desig/scrdata_{ANO}.zip``. Este módulo
faz a ingestão offline desses arquivos, agrega no grão de interesse da aba de
inadimplência e materializa artefatos parquet publicáveis no release do GitHub.

Grão do fato anual (``staging/annual/{ano}.parquet``)::

    data_base x uf x segmento x cliente x porte x modalidade x submodalidade

Descartados na agregação, por decisão de escopo: ``cnae_ocupacao`` (CNAE PJ /
natureza da ocupação PF), ``origem`` (origem/destinação de recursos) e
``indexador``. Também são descartados os seis baldes ``a_vencer_*`` e as duas
colunas derivadas (``carteira_a_vencer`` e ``carteira_vencida``), reconstruíveis
a partir de ``carteira_ativa`` e dos dois baldes de vencidos.

O artefato principal (``dados.parquet``) é um resumo por região, sem UF e sem
segmento, que cobre a série completa desde jul/2012 num arquivo leve. O grão
completo fica nos slices anuais, carregados sob demanda pela UI.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
import requests

from .base import BaseCache, CacheConfig, CacheResult
from .release_config import get_release_config

logger = logging.getLogger("ifdata_cache")


# =============================================================================
# FONTE
# =============================================================================

SCR_ZIP_URL_TEMPLATE = "https://www.bcb.gov.br/pda/desig/scrdata_{ano}.zip"
SCR_METODOLOGIA_URL = "https://www.bcb.gov.br/pda/desig/metodologia_versao2.pdf"
SCR_PAGINA_URL = "https://www.bcb.gov.br/estabilidadefinanceira/scrdata"
SCR_DOC3040_URL = "https://www.bcb.gov.br/estabilidadefinanceira/scrdoc3040"

# A série do SCR.data v2 começa em jul/2012.
PRIMEIRO_ANO = 2012
PRIMEIRA_DATA_BASE = "2012-07"

# O WAF do BCB rejeita o User-Agent padrão do requests em alguns caminhos.
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TomaConta/1.0)"}
REQUEST_TIMEOUT = 180
DOWNLOAD_CHUNK = 1 << 20


# =============================================================================
# SCHEMA
# =============================================================================

# Colunas lidas do CSV bruto. `modalidade` entra só para alimentar dim_produto.
CSV_USECOLS = [
    "data_base",
    "uf",
    "segmento",
    "cliente",
    "porte",
    "modalidade",
    "submodalidade",
    "numero_de_operacoes",
    "vencido_de_15_ate_90_dias",
    "vencido_acima_de_90_dias",
    "carteira_ativa",
    "carteira_inadimplencia",
    "ativo_problematico",
]

# `modalidade` fica no grão, e não numa dimensão de lookup, porque a
# submodalidade NÃO é filha estrita da modalidade: em jun/2026, cinco
# submodalidades aparecem sob mais de uma modalidade (`Financiamento de projeto`
# sob seis delas; `Microcrédito` dividido entre Empréstimos e Financiamentos).
# Um rollup por lookup atribuiria errado ~R$ 430 bi de carteira.
FACT_DIM_COLUMNS = [
    "data_base",
    "uf",
    "segmento",
    "cliente",
    "porte",
    "modalidade",
    "submodalidade",
]

RESUMO_DIM_COLUMNS = [
    "data_base",
    "regiao",
    "cliente",
    "porte",
    "modalidade",
    "submodalidade",
]

# Somatórias monetárias, gravadas em R$ mil (float32).
# `carteira_suprimida` é a fatia de `carteira_ativa` que vinha em linhas com
# contagem de operações sigilosa. Sem ela não dá para dizer honestamente quanto
# da carteira do recorte tem contagem subestimada: depois da agregação uma linha
# do fato reúne várias linhas-fonte, e a maioria delas acaba tocando alguma
# supressão.
METRIC_MONETARIAS = [
    "carteira_ativa",
    "vencido_de_15_ate_90_dias",
    "vencido_acima_de_90_dias",
    "carteira_inadimplencia",
    "ativo_problematico",
    "carteira_suprimida",
]

# Contagens inteiras.
METRIC_CONTAGENS = ["numero_de_operacoes", "ops_suprimidas"]

METRIC_COLUMNS = METRIC_CONTAGENS + METRIC_MONETARIAS

FACT_COLUMNS = FACT_DIM_COLUMNS + METRIC_COLUMNS
RESUMO_COLUMNS = RESUMO_DIM_COLUMNS + METRIC_COLUMNS

FACT_REQUIRED_COLUMNS = list(FACT_COLUMNS)
RESUMO_REQUIRED_COLUMNS = list(RESUMO_COLUMNS)

# Fator aplicado às colunas monetárias: o CSV vem em R$, gravamos em R$ mil.
ESCALA_MONETARIA = 1000.0


# =============================================================================
# DIMENSÕES ESTÁVEIS
# =============================================================================

REGIAO_POR_UF: Dict[str, str] = {
    "AC": "Norte", "AP": "Norte", "AM": "Norte", "PA": "Norte",
    "RO": "Norte", "RR": "Norte", "TO": "Norte",
    "AL": "Nordeste", "BA": "Nordeste", "CE": "Nordeste", "MA": "Nordeste",
    "PB": "Nordeste", "PE": "Nordeste", "PI": "Nordeste", "RN": "Nordeste",
    "SE": "Nordeste",
    "DF": "Centro-Oeste", "GO": "Centro-Oeste", "MT": "Centro-Oeste",
    "MS": "Centro-Oeste",
    "ES": "Sudeste", "MG": "Sudeste", "RJ": "Sudeste", "SP": "Sudeste",
    "PR": "Sul", "RS": "Sul", "SC": "Sul",
}

ORDEM_REGIOES = ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"]

UF_NOME: Dict[str, str] = {
    "AC": "Acre", "AL": "Alagoas", "AM": "Amazonas", "AP": "Amapá",
    "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal",
    "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão",
    "MG": "Minas Gerais", "MS": "Mato Grosso do Sul", "MT": "Mato Grosso",
    "PA": "Pará", "PB": "Paraíba", "PE": "Pernambuco", "PI": "Piauí",
    "PR": "Paraná", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RO": "Rondônia", "RR": "Roraima", "RS": "Rio Grande do Sul",
    "SC": "Santa Catarina", "SE": "Sergipe", "SP": "São Paulo",
    "TO": "Tocantins",
}

UF_IBGE: Dict[str, int] = {
    "RO": 11, "AC": 12, "AM": 13, "RR": 14, "PA": 15, "AP": 16, "TO": 17,
    "MA": 21, "PI": 22, "CE": 23, "RN": 24, "PB": 25, "PE": 26, "AL": 27,
    "SE": 28, "BA": 29, "MG": 31, "ES": 32, "RJ": 33, "SP": 35,
    "PR": 41, "SC": 42, "RS": 43,
    "MS": 50, "MT": 51, "GO": 52, "DF": 53,
}

# Faixas de renda PF, na ordem natural da renda (não do valor da métrica).
PORTE_PF_ORDEM = [
    "Sem rendimento",
    "Até 1 salário mínimo",
    "Mais de 1 a 2 salários mínimos",
    "Mais de 2 a 3 salários mínimos",
    "Mais de 3 a 5 salários mínimos",
    "Mais de 5 a 10 salários mínimos",
    "Mais de 10 a 20 salários mínimos",
    "Acima de 20 salários mínimos",
]

# Portes PJ, na ordem natural do faturamento.
PORTE_PJ_ORDEM = ["Micro", "Pequeno", "Médio", "Grande"]

PORTE_INDISPONIVEL = "Indisponível"

# Limites em salários mínimos de cada faixa PF, para converter em R$ usando o
# salário mínimo vigente na data-base (SGS 1619).
PORTE_PF_LIMITES: Dict[str, Tuple[Optional[float], Optional[float]]] = {
    "Sem rendimento": (0.0, 0.0),
    "Até 1 salário mínimo": (0.0, 1.0),
    "Mais de 1 a 2 salários mínimos": (1.0, 2.0),
    "Mais de 2 a 3 salários mínimos": (2.0, 3.0),
    "Mais de 3 a 5 salários mínimos": (3.0, 5.0),
    "Mais de 5 a 10 salários mínimos": (5.0, 10.0),
    "Mais de 10 a 20 salários mínimos": (10.0, 20.0),
    "Acima de 20 salários mínimos": (20.0, None),
}

PORTE_PF_ROTULO_CURTO: Dict[str, str] = {
    "Sem rendimento": "sem renda",
    "Até 1 salário mínimo": "até 1 SM",
    "Mais de 1 a 2 salários mínimos": "1–2 SM",
    "Mais de 2 a 3 salários mínimos": "2–3 SM",
    "Mais de 3 a 5 salários mínimos": "3–5 SM",
    "Mais de 5 a 10 salários mínimos": "5–10 SM",
    "Mais de 10 a 20 salários mínimos": "10–20 SM",
    "Acima de 20 salários mínimos": "> 20 SM",
}

# Critérios de porte PJ conforme Anexos 24/25 do leiaute do doc 3040. Os limites
# são nominais e nunca foram corrigidos por inflação — ver nota na aba.
PORTE_PJ_CRITERIO: Dict[str, str] = {
    "Micro": "receita bruta anual ≤ R$ 360 mil (LC 123/2006, art. 3º, I)",
    "Pequeno": (
        "receita bruta anual > R$ 360 mil e ≤ R$ 4,8 mi "
        "(LC 123/2006, art. 3º, II, redação da LC 155/2016)"
    ),
    "Médio": (
        "receita bruta anual > R$ 4,8 mi e ≤ R$ 300 mi, "
        "desde que o ativo total não seja superior a R$ 240 mi"
    ),
    "Grande": (
        "receita bruta anual > R$ 300 mi OU ativo total > R$ 240 mi "
        "(Lei 11.638/2007, art. 3º, parágrafo único)"
    ),
}

PORTE_PJ_FATURAMENTO_LIMITES: Dict[str, Tuple[Optional[float], Optional[float]]] = {
    "Micro": (0.0, 360_000.0),
    "Pequeno": (360_000.0, 4_800_000.0),
    "Médio": (4_800_000.0, 300_000_000.0),
    "Grande": (300_000_000.0, None),
}

# Agrupamento de segmentos declarado na metodologia v2.
SEGMENTO_TIPOS: Dict[str, List[str]] = {
    "Arrendamento": ["Sociedade de Arrendamento Mercantil"],
    "Banco": [
        "Banco Múltiplo",
        "Caixa Econômica Federal",
        "Banco do Brasil",
        "Banco Comercial",
        "Banco Múltiplo Cooperativo",
        "Banco de Investimento",
        "Banco Comercial Estrangeiro",
        "Banco de Câmbio",
    ],
    "Cooperativa": ["Cooperativa de Crédito"],
    "Desenvolvimento/Fomento": [
        "BNDES",
        "Banco de Desenvolvimento",
        "Agência de Fomento",
    ],
    "Financeira": ["Sociedade de Crédito, Financiamento e Investimento"],
    "Fintech": [
        "Sociedade de Empréstimo entre Pessoas (SEP)",
        "Sociedade de Crédito Direto (SCD)",
    ],
    "Instituição de pagamento": ["Instituição de Pagamento"],
    "Outros": [
        "Associação de Poupança e Empréstimo",
        "Companhia Hipotecária",
        "Sociedade de Crédito ao Microempreendedor",
        "Sociedade Corretora de TVM",
        "Sociedade Distribuidora de TVM",
    ],
}

ORDEM_SEGMENTOS = [
    "Banco",
    "Cooperativa",
    "Financeira",
    "Fintech",
    "Instituição de pagamento",
    "Desenvolvimento/Fomento",
    "Arrendamento",
    "Outros",
]

# Submodalidades residuais de migração de leiaute. Não são produto comercial:
# `Cartão de crédito - não migrado` tinha 77% de inadimplência sobre R$ 69 bi em
# jun/2026. Ficam visíveis (o total continua batendo com o SCR), mas são
# excluídas por padrão dos rankings de "produto mais inadimplente".
SUBMODALIDADES_LEGADO = frozenset({"Cartão de crédito - não migrado"})

# Quebras metodológicas que precisam de marcador nos gráficos.
QUEBRAS_DE_SERIE: List[Dict[str, str]] = [
    {
        "data_base": "2016-06",
        "titulo": "limiar de registro cai para R$ 200",
        "descricao": (
            "Até mai/2016 o SCR registrava operações acima de R$ 1.000; "
            "a partir de jun/2016, acima de R$ 200. Afeta principalmente a "
            "contagem de operações e as faixas de renda mais baixas."
        ),
        "metricas": "numero_de_operacoes",
    },
    {
        "data_base": "2025-01",
        "titulo": "novo critério de ativo problemático",
        "descricao": (
            "Até dez/2024 entravam as operações classificadas nos níveis de "
            "risco E a H. A partir de jan/2025 entram apenas as marcadas pelas "
            "instituições como ativo problemático (característica especial 19)."
        ),
        "metricas": "ativo_problematico",
    },
]


# =============================================================================
# NORMALIZAÇÃO
# =============================================================================

# Bytes CP1252 que sobraram na origem e foram gravados como controles C1.
_SUBSTITUICOES_CP1252 = {
    "\x91": "'",
    "\x92": "'",
    "\x93": '"',
    "\x94": '"',
    "\x96": "-",
    "\x97": "-",
    "\x85": "...",
}


def normalizar_rotulo(valor: Any) -> Any:
    """Limpa rótulos textuais do CSV do SCR.

    O arquivo traz resíduos de CP1252 (por exemplo ``"Financiamento
    habitacional \\x96 exceto SFH"``) e espaços à direita em algumas
    submodalidades (``"Comercialização "``). Sem essa limpeza as categorias se
    duplicam entre data-bases.
    """
    if not isinstance(valor, str):
        return valor
    texto = valor
    for origem, destino in _SUBSTITUICOES_CP1252.items():
        if origem in texto:
            texto = texto.replace(origem, destino)
    return " ".join(texto.split())


def data_base_para_periodo(valor: Any) -> Any:
    """Converte ``2026-06-30`` (último dia do mês) em ``2026-06``."""
    if not isinstance(valor, str):
        return valor
    return valor.strip()[:7]


def ler_csv_scr(fonte: Any) -> pd.DataFrame:
    """Lê um CSV mensal do SCR.data já com os tipos corretos.

    O arquivo é ``;``-separado, decimal com vírgula e UTF-8 **com BOM**.
    """
    return pd.read_csv(
        fonte,
        sep=";",
        decimal=",",
        encoding="utf-8-sig",
        usecols=CSV_USECOLS,
    )


def normalizar_csv_scr(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza um CSV mensal bruto antes da agregação.

    Trata a supressão de ``numero_de_operacoes``: o BCB grava ``-1`` quando o
    número de operações do recorte é sigiloso. Em jun/2026 isso atingia 26% das
    linhas, cobrindo 6,7% da carteira. Somar ``-1`` produziria lixo, então o
    valor vira zero e a contagem de linhas suprimidas vai para
    ``ops_suprimidas``, que a UI usa para avisar que o total está subestimado.
    """
    out = df.copy()

    for coluna in ("uf", "segmento", "cliente", "porte", "modalidade", "submodalidade"):
        if coluna in out.columns:
            out[coluna] = out[coluna].map(normalizar_rotulo)

    out["data_base"] = out["data_base"].map(data_base_para_periodo)

    for coluna in METRIC_MONETARIAS:
        if coluna in out.columns:
            out[coluna] = pd.to_numeric(out[coluna], errors="coerce").fillna(0.0)

    suprimidas = out["numero_de_operacoes"] == -1
    out["ops_suprimidas"] = suprimidas.astype("int32")
    out["carteira_suprimida"] = out["carteira_ativa"].where(suprimidas, 0.0)
    out.loc[suprimidas, "numero_de_operacoes"] = 0
    out["numero_de_operacoes"] = out["numero_de_operacoes"].astype("int64")

    return out


def _tipar_saida(df: pd.DataFrame, dimensoes: Sequence[str]) -> pd.DataFrame:
    """Aplica os tipos finais: dimensões como categoria, valores em R$ mil."""
    out = df.copy()
    for coluna in dimensoes:
        out[coluna] = out[coluna].astype("category")
    for coluna in METRIC_MONETARIAS:
        out[coluna] = (out[coluna] / ESCALA_MONETARIA).astype("float32")
    for coluna in METRIC_CONTAGENS:
        out[coluna] = out[coluna].astype("int32")
    return out


def agregar_fato(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega um CSV normalizado no grão do fato anual.

    Descarta CNAE/ocupação, origem de recursos e indexador — o CSV já foi lido
    sem essas colunas, então a agregação apenas colapsa as linhas restantes.
    """
    agregado = (
        df.groupby(FACT_DIM_COLUMNS, as_index=False, observed=True)[METRIC_COLUMNS]
        .sum()
    )
    agregado = agregado.sort_values(FACT_DIM_COLUMNS, kind="stable").reset_index(drop=True)
    return _tipar_saida(agregado, FACT_DIM_COLUMNS)


def agregar_resumo(df_fato: pd.DataFrame) -> pd.DataFrame:
    """Colapsa o fato no resumo por região (sem UF e sem segmento)."""
    out = df_fato.copy()
    for coluna in FACT_DIM_COLUMNS:
        if isinstance(out[coluna].dtype, pd.CategoricalDtype):
            out[coluna] = out[coluna].astype(str)
    out["regiao"] = out["uf"].map(REGIAO_POR_UF)

    # Reverte a escala para somar em R$ e reaplicar `_tipar_saida` uma só vez.
    for coluna in METRIC_MONETARIAS:
        out[coluna] = out[coluna].astype("float64") * ESCALA_MONETARIA

    agregado = (
        out.groupby(RESUMO_DIM_COLUMNS, as_index=False, observed=True)[METRIC_COLUMNS]
        .sum()
    )
    agregado = agregado.sort_values(RESUMO_DIM_COLUMNS, kind="stable").reset_index(drop=True)
    return _tipar_saida(agregado, RESUMO_DIM_COLUMNS)


def concatenar_fatos(frames: Sequence[pd.DataFrame]) -> pd.DataFrame:
    """Concatena slices anuais reconciliando as categorias de cada arquivo.

    Slices de anos diferentes têm conjuntos de categorias distintos (Fintech e
    Instituição de pagamento não existem em 2012, as submodalidades passam de 48
    para 55). Concatenar categóricos divergentes degrada para ``object``, então
    a reconciliação é explícita.
    """
    uteis = [frame for frame in frames if frame is not None and not frame.empty]
    if not uteis:
        return pd.DataFrame(columns=FACT_COLUMNS)

    dimensoes = [col for col in FACT_DIM_COLUMNS if col in uteis[0].columns]
    normalizados = []
    for frame in uteis:
        copia = frame.copy()
        for coluna in dimensoes:
            if isinstance(copia[coluna].dtype, pd.CategoricalDtype):
                copia[coluna] = copia[coluna].astype(str)
        normalizados.append(copia)

    juntos = pd.concat(normalizados, ignore_index=True)
    for coluna in dimensoes:
        juntos[coluna] = juntos[coluna].astype("category")
    return juntos


# =============================================================================
# DIMENSÕES DERIVADAS
# =============================================================================

def construir_dim_geo() -> pd.DataFrame:
    """UF -> região, nome e código IBGE."""
    linhas = [
        {
            "uf": uf,
            "uf_nome": UF_NOME[uf],
            "regiao": REGIAO_POR_UF[uf],
            "codigo_ibge": UF_IBGE[uf],
            "ordem_regiao": ORDEM_REGIOES.index(REGIAO_POR_UF[uf]),
        }
        for uf in sorted(UF_NOME)
    ]
    return pd.DataFrame(linhas)


def construir_dim_porte() -> pd.DataFrame:
    """Porte -> cliente, tipo de critério, ordem e descrição do critério.

    PF e PJ compartilham a mesma coluna ``porte`` no CSV, então o consumidor
    precisa desta dimensão para nunca colocar faixa de renda e porte de empresa
    no mesmo eixo.
    """
    linhas: List[Dict[str, Any]] = []

    for ordem, porte in enumerate(PORTE_PF_ORDEM):
        minimo, maximo = PORTE_PF_LIMITES[porte]
        linhas.append({
            "porte": porte,
            "cliente": "PF",
            "tipo_criterio": "renda_salarios_minimos",
            "ordem": ordem,
            "rotulo_curto": PORTE_PF_ROTULO_CURTO[porte],
            "limite_inferior_sm": minimo,
            "limite_superior_sm": maximo,
            "limite_inferior_faturamento": None,
            "limite_superior_faturamento": None,
            "criterio": (
                "renda mensal bruta individual em salários mínimos vigentes na "
                "data-base; admite-se renda presumida ou estimada"
            ),
        })

    for ordem, porte in enumerate(PORTE_PJ_ORDEM):
        minimo, maximo = PORTE_PJ_FATURAMENTO_LIMITES[porte]
        linhas.append({
            "porte": porte,
            "cliente": "PJ",
            "tipo_criterio": "faturamento_anual",
            "ordem": ordem,
            "rotulo_curto": porte.lower(),
            "limite_inferior_sm": None,
            "limite_superior_sm": None,
            "limite_inferior_faturamento": minimo,
            "limite_superior_faturamento": maximo,
            "criterio": PORTE_PJ_CRITERIO[porte],
        })

    # "Indisponível" existe para os dois tipos de cliente.
    for cliente in ("PF", "PJ"):
        linhas.append({
            "porte": PORTE_INDISPONIVEL,
            "cliente": cliente,
            "tipo_criterio": "indisponivel",
            "ordem": 99,
            "rotulo_curto": "indisponível",
            "limite_inferior_sm": None,
            "limite_superior_sm": None,
            "limite_inferior_faturamento": None,
            "limite_superior_faturamento": None,
            "criterio": (
                "porte/renda não informado; só permitido quando o campo "
                "FatAnual do doc 3040 é menor ou igual a R$ 1,00"
            ),
        })

    return pd.DataFrame(linhas)


def construir_dim_produto(pares: pd.DataFrame) -> pd.DataFrame:
    """Pares modalidade/submodalidade observados, com vigência e flag de legado.

    Não é um mapa de rollup: a mesma submodalidade aparece sob modalidades
    diferentes (ver nota em ``FACT_DIM_COLUMNS``), por isso ambas ficam no grão
    do fato e o rollup é um ``groupby`` comum. Esta dimensão serve para rótulos,
    ordenação e para saber em que data-base cada categoria surgiu.

    ``pares`` deve conter as colunas ``modalidade``, ``submodalidade`` e
    ``data_base`` observadas em toda a série.
    """
    if pares.empty:
        return pd.DataFrame(
            columns=[
                "submodalidade",
                "modalidade",
                "primeira_data_base",
                "ultima_data_base",
                "legado",
            ]
        )

    agrupado = (
        pares.groupby(["submodalidade", "modalidade"], as_index=False, observed=True)
        .agg(
            primeira_data_base=("data_base", "min"),
            ultima_data_base=("data_base", "max"),
        )
    )
    agrupado["legado"] = agrupado["submodalidade"].isin(SUBMODALIDADES_LEGADO)
    agrupado = agrupado.sort_values(["modalidade", "submodalidade"], kind="stable")
    return agrupado.reset_index(drop=True)


def construir_dim_segmento(observados: pd.DataFrame) -> pd.DataFrame:
    """Segmento -> tipos cadastrados no BCB, ordem e primeira data-base.

    Fintech (SCD/SEP) e Instituição de pagamento não existem no início da série;
    a primeira data-base observada evita zero-fill enganoso nos gráficos.
    """
    if observados.empty:
        primeiras: Dict[str, Optional[str]] = {}
        ultimas: Dict[str, Optional[str]] = {}
    else:
        agrupado = observados.groupby("segmento", observed=True)["data_base"]
        primeiras = agrupado.min().to_dict()
        ultimas = agrupado.max().to_dict()

    linhas = []
    for segmento, tipos in SEGMENTO_TIPOS.items():
        linhas.append({
            "segmento": segmento,
            "ordem": ORDEM_SEGMENTOS.index(segmento) if segmento in ORDEM_SEGMENTOS else 99,
            "tipos_cadastrados": "; ".join(tipos),
            "primeira_data_base": primeiras.get(segmento),
            "ultima_data_base": ultimas.get(segmento),
        })
    return pd.DataFrame(linhas).sort_values("ordem").reset_index(drop=True)


# =============================================================================
# VALIDAÇÃO
# =============================================================================

class SCRQualityError(RuntimeError):
    """Falha de qualidade que impede a materialização de um slice anual."""


def validar_fato_anual(
    df: pd.DataFrame,
    *,
    ano: str,
    variacao_maxima_mensal: float = 0.10,
) -> Dict[str, Any]:
    """Checa sanidade de um slice anual antes de gravá-lo.

    Levanta ``SCRQualityError`` quando o arquivo claramente não presta; devolve
    avisos quando algo é apenas suspeito.
    """
    if df.empty:
        raise SCRQualityError(f"{ano}: slice vazio")

    faltantes = [col for col in FACT_COLUMNS if col not in df.columns]
    if faltantes:
        raise SCRQualityError(f"{ano}: colunas ausentes: {', '.join(faltantes)}")

    if (df["carteira_ativa"] < 0).any():
        raise SCRQualityError(f"{ano}: carteira_ativa negativa")

    if (df["numero_de_operacoes"] < 0).any():
        raise SCRQualityError(f"{ano}: numero_de_operacoes negativo após normalização")

    ufs = set(df["uf"].astype(str).unique())
    desconhecidas = ufs - set(REGIAO_POR_UF)
    if desconhecidas:
        raise SCRQualityError(f"{ano}: UF fora do domínio: {sorted(desconhecidas)}")

    portes_validos = set(PORTE_PF_ORDEM) | set(PORTE_PJ_ORDEM) | {PORTE_INDISPONIVEL}
    portes_desconhecidos = set(df["porte"].astype(str).unique()) - portes_validos
    if portes_desconhecidos:
        raise SCRQualityError(f"{ano}: porte fora do domínio: {sorted(portes_desconhecidos)}")

    clientes = set(df["cliente"].astype(str).unique()) - {"PF", "PJ"}
    if clientes:
        raise SCRQualityError(f"{ano}: cliente fora do domínio: {sorted(clientes)}")

    avisos: List[str] = []

    por_data = (
        df.groupby("data_base", observed=True)["carteira_ativa"].sum().sort_index()
    )
    variacao = por_data.pct_change().abs()
    suspeitas = variacao[variacao > variacao_maxima_mensal]
    for data_base, valor in suspeitas.items():
        avisos.append(
            f"{data_base}: carteira ativa variou {valor:.1%} contra o mês anterior"
        )

    ufs_faltantes = set(REGIAO_POR_UF) - ufs
    if ufs_faltantes:
        avisos.append(f"UFs sem dados no ano: {sorted(ufs_faltantes)}")

    return {
        "ano": ano,
        "linhas": int(len(df)),
        "data_bases": [str(item) for item in por_data.index.tolist()],
        "carteira_ativa_por_data_base_rs_mil": {
            str(k): float(v) for k, v in por_data.items()
        },
        "avisos": avisos,
    }


# =============================================================================
# CACHE
# =============================================================================

SCR_DATA_CONFIG = CacheConfig(
    nome="scr_data",
    descricao="SCR.data — carteira, inadimplência e ativo problemático (BCB)",
    subdir="scr_data",
    arquivo_dados="dados.parquet",
    arquivo_metadata="metadata.json",
    github_url_base=None,
    max_idade_horas=24.0 * 7,
    colunas_obrigatorias=RESUMO_REQUIRED_COLUMNS,
    api_url=None,
)


class SCRDataCache(BaseCache):
    """Cache do SCR.data com ingestão anual resumível.

    O artefato principal (``dados.parquet``) é o resumo por região com a série
    completa. Os slices anuais em ``staging/annual/`` guardam o grão completo e
    são publicados como assets independentes no release, para que a UI baixe só
    o intervalo que o usuário pediu.
    """

    def __init__(self, base_dir: Path):
        super().__init__(SCR_DATA_CONFIG, base_dir)
        release_config = get_release_config()
        self.release_repo = release_config.repo
        self.release_tag = release_config.tag
        self.release_base_url = release_config.release_base_url
        self.github_release_parquet_url = (
            f"{self.release_base_url}/{self.config.nome}_dados.parquet"
        )
        self.github_release_metadata_url = (
            f"{self.release_base_url}/{self.config.nome}_metadata.json"
        )
        self.github_release_manifest_url = (
            f"{self.release_base_url}/{self.config.nome}_manifest.json"
        )

    # -- caminhos ----------------------------------------------------------

    @property
    def staging_dir(self) -> Path:
        return self.cache_dir / "staging"

    @property
    def annual_dir(self) -> Path:
        return self.staging_dir / "annual"

    @property
    def checkpoint_path(self) -> Path:
        return self.staging_dir / "checkpoint.json"

    @property
    def manifest_path(self) -> Path:
        return self.cache_dir / "historico_manifest.json"

    def dimension_paths(self) -> Dict[str, Path]:
        return {
            "produto": self.cache_dir / "dim_produto.parquet",
            "porte": self.cache_dir / "dim_porte.parquet",
            "geo": self.cache_dir / "dim_geo.parquet",
            "segmento": self.cache_dir / "dim_segmento.parquet",
        }

    def annual_path(self, ano: Any) -> Path:
        return self.annual_dir / f"{ano}.parquet"

    def annual_asset_name(self, ano: Any) -> str:
        return f"{self.config.nome}_ano_{ano}.parquet"

    def annual_release_url(self, ano: Any) -> str:
        return f"{self.release_base_url}/{self.annual_asset_name(ano)}"

    def anos_locais(self) -> List[int]:
        if not self.annual_dir.exists():
            return []
        anos = []
        for path in self.annual_dir.glob("*.parquet"):
            try:
                anos.append(int(path.stem))
            except ValueError:
                continue
        return sorted(anos)

    def extra_release_assets(self) -> List[Tuple[Path, str]]:
        extras: List[Tuple[Path, str]] = []
        asset_names = {
            "produto": f"{self.config.nome}_dim_produto.parquet",
            "porte": f"{self.config.nome}_dim_porte.parquet",
            "geo": f"{self.config.nome}_dim_geo.parquet",
            "segmento": f"{self.config.nome}_dim_segmento.parquet",
        }
        for chave, path in self.dimension_paths().items():
            if path.exists():
                extras.append((path, asset_names[chave]))
        if self.manifest_path.exists():
            extras.append((self.manifest_path, f"{self.config.nome}_manifest.json"))
        for ano in self.anos_locais():
            extras.append((self.annual_path(ano), self.annual_asset_name(ano)))
        return extras

    # -- utilidades --------------------------------------------------------

    def _garantir_estrutura(self) -> None:
        self._garantir_diretorio()
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.annual_dir.mkdir(parents=True, exist_ok=True)

    def _log_local(
        self,
        nivel: str,
        mensagem: str,
        callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        if callback:
            callback(mensagem)
        self._log(nivel, mensagem)

    @staticmethod
    def _save_json(path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @staticmethod
    def _load_json(path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    # -- ingestão ----------------------------------------------------------

    def anos_disponiveis(self, ano_final: Optional[int] = None) -> List[int]:
        """Anos que o BCB publica, de 2012 até o ano corrente."""
        limite = ano_final or datetime.now().year
        return list(range(PRIMEIRO_ANO, limite + 1))

    def inspecionar_ano(self, ano: int, *, session: Optional[requests.Session] = None) -> Dict[str, Any]:
        """HEAD no ZIP anual, para decidir se vale rebaixar.

        O BCB reescreve o ZIP inteiro a cada publicação — inclusive de anos
        passados. Comparar ``Last-Modified``/``Content-Length`` com o manifesto
        evita rebaixar 2 GB todo mês.
        """
        url = SCR_ZIP_URL_TEMPLATE.format(ano=ano)
        http = session or requests
        resposta = http.head(
            url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True
        )
        return {
            "ano": ano,
            "url": url,
            "status_code": resposta.status_code,
            "disponivel": resposta.status_code == 200,
            "last_modified": resposta.headers.get("Last-Modified"),
            "content_length": resposta.headers.get("Content-Length"),
            "etag": resposta.headers.get("ETag"),
        }

    def _baixar_zip_ano(
        self,
        ano: int,
        destino: Path,
        *,
        session: Optional[requests.Session] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Baixa o ZIP anual em streaming e devolve o sha256."""
        url = SCR_ZIP_URL_TEMPLATE.format(ano=ano)
        http = session or requests
        digest = hashlib.sha256()
        destino.parent.mkdir(parents=True, exist_ok=True)

        with http.get(
            url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT, stream=True
        ) as resposta:
            resposta.raise_for_status()
            baixado = 0
            with open(destino, "wb") as arquivo:
                for bloco in resposta.iter_content(chunk_size=DOWNLOAD_CHUNK):
                    if not bloco:
                        continue
                    arquivo.write(bloco)
                    digest.update(bloco)
                    baixado += len(bloco)

        self._log_local(
            "info", f"{ano}: ZIP baixado ({baixado / 1e6:.0f} MB)", log_callback
        )
        return digest.hexdigest()

    def _processar_zip_ano(
        self,
        zip_path: Path,
        *,
        ano: int,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Agrega todos os CSVs mensais de um ZIP anual.

        Devolve ``(fato, pares_produto)``, onde ``pares_produto`` alimenta a
        dimensão de produto (o par modalidade/submodalidade não entra no fato).
        """
        fatos: List[pd.DataFrame] = []
        pares: List[pd.DataFrame] = []

        with zipfile.ZipFile(zip_path) as arquivo_zip:
            nomes = sorted(
                nome for nome in arquivo_zip.namelist() if nome.lower().endswith(".csv")
            )
            if not nomes:
                raise SCRQualityError(f"{ano}: ZIP sem CSVs")

            for nome in nomes:
                with arquivo_zip.open(nome) as fluxo:
                    bruto = ler_csv_scr(io.BytesIO(fluxo.read()))
                normalizado = normalizar_csv_scr(bruto)
                fatos.append(agregar_fato(normalizado))
                pares.append(
                    normalizado[["modalidade", "submodalidade", "data_base"]]
                    .drop_duplicates()
                )
                self._log_local(
                    "info",
                    f"{ano}: {nome} agregado ({len(normalizado)} -> {len(fatos[-1])} linhas)",
                    log_callback,
                )

        fato = concatenar_fatos(fatos)
        fato = fato.sort_values(FACT_DIM_COLUMNS, kind="stable").reset_index(drop=True)
        pares_produto = pd.concat(pares, ignore_index=True).drop_duplicates()
        return fato, pares_produto

    def materializar_ano(
        self,
        ano: int,
        *,
        session: Optional[requests.Session] = None,
        manter_zip: bool = False,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """Baixa, agrega, valida e grava o slice anual de um ano."""
        self._garantir_estrutura()
        zip_path = self.staging_dir / f"scrdata_{ano}.zip"

        cabecalho = self.inspecionar_ano(ano, session=session)
        if not cabecalho["disponivel"]:
            raise SCRQualityError(
                f"{ano}: ZIP indisponível (HTTP {cabecalho['status_code']})"
            )

        sha256 = self._baixar_zip_ano(
            ano, zip_path, session=session, log_callback=log_callback
        )
        try:
            fato, pares_produto = self._processar_zip_ano(
                zip_path, ano=ano, log_callback=log_callback
            )
            relatorio = validar_fato_anual(fato, ano=str(ano))

            destino = self.annual_path(ano)
            temporario = destino.with_suffix(".parquet.tmp")
            fato.to_parquet(temporario, compression="zstd", index=False)
            temporario.replace(destino)

            pares_path = self.staging_dir / f"pares_produto_{ano}.parquet"
            pares_produto.to_parquet(pares_path, index=False)
        finally:
            if not manter_zip and zip_path.exists():
                zip_path.unlink()

        registro = {
            **relatorio,
            "sha256_zip": sha256,
            "last_modified": cabecalho["last_modified"],
            "content_length": cabecalho["content_length"],
            "bytes_parquet": destino.stat().st_size,
            "materializado_em": datetime.now(timezone.utc).isoformat(),
        }
        for aviso in relatorio["avisos"]:
            self._log_local("warning", f"{ano}: {aviso}", log_callback)
        self._log_local(
            "info",
            f"{ano}: slice gravado ({registro['linhas']} linhas, "
            f"{registro['bytes_parquet'] / 1e6:.1f} MB)",
            log_callback,
        )
        return registro

    def materialize_history(
        self,
        *,
        ano_inicial: int = PRIMEIRO_ANO,
        ano_final: Optional[int] = None,
        overwrite: bool = False,
        manter_zip: bool = False,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> CacheResult:
        """Reconstrói a série do SCR.data, ano a ano, de forma resumível.

        Sem ``overwrite``, anos já materializados cujo ZIP não mudou no servidor
        são pulados — o rebuild mensal baixa só o ano corrente.
        """
        self._garantir_estrutura()
        ano_final = ano_final or datetime.now().year
        anos = list(range(max(ano_inicial, PRIMEIRO_ANO), ano_final + 1))

        checkpoint = self._load_json(self.checkpoint_path)
        registros: Dict[str, Any] = dict(checkpoint.get("anos", {}))
        falhas: Dict[str, str] = {}

        with requests.Session() as session:
            for ano in anos:
                chave = str(ano)
                anterior = registros.get(chave)
                if anterior and not overwrite and self.annual_path(ano).exists():
                    cabecalho = self.inspecionar_ano(ano, session=session)
                    inalterado = (
                        cabecalho.get("last_modified") == anterior.get("last_modified")
                        and cabecalho.get("content_length") == anterior.get("content_length")
                    )
                    if inalterado:
                        self._log_local(
                            "info", f"{ano}: inalterado no servidor, pulando", log_callback
                        )
                        continue

                try:
                    registros[chave] = self.materializar_ano(
                        ano,
                        session=session,
                        manter_zip=manter_zip,
                        log_callback=log_callback,
                    )
                except Exception as exc:  # noqa: BLE001 - o ano falho não derruba os demais
                    falhas[chave] = str(exc)
                    self._log_local("error", f"{ano}: falha — {exc}", log_callback)

                self._save_json(
                    self.checkpoint_path,
                    {
                        "atualizado_em": datetime.now(timezone.utc).isoformat(),
                        "anos": registros,
                        "falhas": falhas,
                    },
                )

        if not self.anos_locais():
            return CacheResult(
                sucesso=False,
                mensagem=f"Nenhum slice anual materializado. Falhas: {falhas}",
                fonte="nenhum",
            )

        metadata = self._materializar_artefatos(
            registros=registros, falhas=falhas, log_callback=log_callback
        )
        mensagem = (
            f"SCR.data materializado: {metadata['total_registros']} linhas no resumo, "
            f"{len(self.anos_locais())} anos"
        )
        if falhas:
            mensagem += f"; anos com falha: {sorted(falhas)}"
        return CacheResult(
            sucesso=True, mensagem=mensagem, metadata=metadata, fonte="api"
        )

    # -- materialização dos artefatos --------------------------------------

    def _materializar_artefatos(
        self,
        *,
        registros: Dict[str, Any],
        falhas: Dict[str, str],
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """Constrói ``dados.parquet``, as dimensões e os manifestos."""
        anos = self.anos_locais()
        self._log_local("info", "Consolidando resumo por região...", log_callback)

        resumos: List[pd.DataFrame] = []
        segmentos_observados: List[pd.DataFrame] = []
        for ano in anos:
            fato = pd.read_parquet(self.annual_path(ano))
            resumos.append(agregar_resumo(fato))
            segmentos_observados.append(
                fato[["segmento", "data_base"]].astype(str).drop_duplicates()
            )

        resumo = pd.concat(
            [frame.astype({col: str for col in RESUMO_DIM_COLUMNS}) for frame in resumos],
            ignore_index=True,
        )
        resumo = resumo.sort_values(RESUMO_DIM_COLUMNS, kind="stable").reset_index(drop=True)
        for coluna in RESUMO_DIM_COLUMNS:
            resumo[coluna] = resumo[coluna].astype("category")

        temporario = self.cache_dir / "dados.parquet.tmp"
        resumo.to_parquet(temporario, compression="zstd", index=False)
        temporario.replace(self.arquivo_dados)

        self._log_local("info", "Construindo dimensões...", log_callback)
        pares = [
            pd.read_parquet(path)
            for path in sorted(self.staging_dir.glob("pares_produto_*.parquet"))
        ]
        dim_produto = construir_dim_produto(
            pd.concat(pares, ignore_index=True).drop_duplicates()
            if pares
            else pd.DataFrame(columns=["modalidade", "submodalidade", "data_base"])
        )
        dim_segmento = construir_dim_segmento(
            pd.concat(segmentos_observados, ignore_index=True).drop_duplicates()
            if segmentos_observados
            else pd.DataFrame(columns=["segmento", "data_base"])
        )

        caminhos = self.dimension_paths()
        dim_produto.to_parquet(caminhos["produto"], index=False)
        construir_dim_porte().to_parquet(caminhos["porte"], index=False)
        construir_dim_geo().to_parquet(caminhos["geo"], index=False)
        dim_segmento.to_parquet(caminhos["segmento"], index=False)

        data_bases = sorted(resumo["data_base"].astype(str).unique().tolist())
        finalizado_em = datetime.now().isoformat()

        metadata = {
            "timestamp_salvamento": finalizado_em,
            "fonte": "bcb_pda_scrdata_zip",
            "total_registros": int(len(resumo)),
            "total_periodos": len(data_bases),
            "periodos": data_bases,
            "periodo_inicial": data_bases[0] if data_bases else None,
            "periodo_final": data_bases[-1] if data_bases else None,
            "anos_materializados": [str(ano) for ano in anos],
            "grao_resumo": RESUMO_DIM_COLUMNS,
            "grao_detalhe": FACT_DIM_COLUMNS,
            "unidade_monetaria": "R$ mil",
            "schema_version": 1,
        }
        self._save_json(self.arquivo_metadata, metadata)
        self._save_json(
            self.manifest_path,
            {
                "finalizado_em": finalizado_em,
                "fonte": SCR_PAGINA_URL,
                "metodologia": SCR_METODOLOGIA_URL,
                "linhas_resumo": int(len(resumo)),
                "bytes_resumo": self.arquivo_dados.stat().st_size,
                "anos": registros,
                "falhas": falhas,
                "quebras_de_serie": QUEBRAS_DE_SERIE,
            },
        )
        return metadata

    # -- consumo -----------------------------------------------------------

    def _baixar_asset(self, url: str, destino: Path) -> bool:
        try:
            resposta = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            self._log("warning", f"Falha de rede ao baixar {url}: {exc}")
            return False
        if resposta.status_code != 200:
            self._log("warning", f"Asset indisponível ({resposta.status_code}): {url}")
            return False
        destino.parent.mkdir(parents=True, exist_ok=True)
        if destino.suffix == ".json":
            destino.write_text(resposta.text, encoding="utf-8")
        else:
            destino.write_bytes(resposta.content)
        return True

    def bootstrap_local_assets(self, *, force: bool = False) -> CacheResult:
        """Garante resumo, metadata, manifesto e dimensões localmente."""
        caminhos = self.dimension_paths()
        if (
            not force
            and self.arquivo_dados.exists()
            and self.arquivo_metadata.exists()
            and all(path.exists() for path in caminhos.values())
        ):
            return CacheResult(
                sucesso=True,
                mensagem="Assets do SCR.data já disponíveis localmente.",
                fonte="cache_local",
            )

        self._garantir_diretorio()

        if not self._baixar_asset(self.github_release_parquet_url, self.arquivo_dados):
            return CacheResult(
                sucesso=False,
                mensagem=(
                    "Resumo do SCR.data não encontrado no release. "
                    "Rode `python tools/update_caches_cli.py --tipo scr_data` para materializá-lo."
                ),
                fonte="nenhum",
            )

        self._baixar_asset(self.github_release_metadata_url, self.arquivo_metadata)
        self._baixar_asset(self.github_release_manifest_url, self.manifest_path)
        for chave, path in caminhos.items():
            self._baixar_asset(
                f"{self.release_base_url}/{self.config.nome}_dim_{chave}.parquet", path
            )

        return CacheResult(
            sucesso=True,
            mensagem="Assets do SCR.data baixados do release.",
            fonte="github_releases",
        )

    def carregar_detalhe(
        self,
        *,
        anos: Optional[Iterable[int]] = None,
        baixar_ausentes: bool = True,
    ) -> pd.DataFrame:
        """Carrega o grão completo dos anos pedidos.

        Slices ausentes localmente são baixados do release. Anos indisponíveis
        são ignorados — cabe ao chamador comparar o intervalo pedido com as
        data-bases devolvidas.
        """
        alvo = sorted(set(anos)) if anos is not None else self.anos_locais()
        if not alvo:
            return pd.DataFrame(columns=FACT_COLUMNS)

        frames: List[pd.DataFrame] = []
        for ano in alvo:
            caminho = self.annual_path(ano)
            if not caminho.exists() and baixar_ausentes:
                self.annual_dir.mkdir(parents=True, exist_ok=True)
                self._baixar_asset(self.annual_release_url(ano), caminho)
            if caminho.exists():
                frames.append(pd.read_parquet(caminho))

        return concatenar_fatos(frames)

    def carregar_dimensoes(self) -> Dict[str, pd.DataFrame]:
        """Devolve as quatro dimensões, reconstruindo as estáticas se faltarem."""
        caminhos = self.dimension_paths()
        dimensoes: Dict[str, pd.DataFrame] = {}
        for chave, path in caminhos.items():
            if path.exists():
                dimensoes[chave] = pd.read_parquet(path)
            elif chave == "porte":
                dimensoes[chave] = construir_dim_porte()
            elif chave == "geo":
                dimensoes[chave] = construir_dim_geo()
            else:
                dimensoes[chave] = pd.DataFrame()
        return dimensoes

    # -- contrato BaseCache ------------------------------------------------

    def baixar_remoto(self) -> CacheResult:
        bootstrap = self.bootstrap_local_assets(force=True)
        if not bootstrap.sucesso:
            return bootstrap
        try:
            import pyarrow.parquet as pq

            total = int(pq.ParquetFile(self.arquivo_dados).metadata.num_rows)
        except Exception as exc:  # noqa: BLE001
            return CacheResult(
                sucesso=False,
                mensagem=f"Resumo baixado, mas o parquet é inválido: {exc}",
                fonte="nenhum",
            )
        return CacheResult(
            sucesso=True,
            mensagem=f"Baixado resumo do SCR.data: {total} registros",
            metadata={"total_registros": total},
            fonte="github_releases",
        )

    def carregar(self, forcar_remoto: bool = False) -> CacheResult:
        if not forcar_remoto:
            valido, _ = self.cache_valido()
            if valido:
                resultado = self.carregar_local()
                if resultado.sucesso:
                    return resultado

        resultado = self.baixar_remoto()
        if not resultado.sucesso:
            # O resumo local, mesmo expirado, é melhor que nada.
            if self.existe():
                return self.carregar_local()
            return resultado
        return self.carregar_local()

    def extrair_periodo(self, periodo: str, **kwargs) -> CacheResult:
        """Materializa o ano de uma data-base ``YYYY-MM`` ou ``YYYY``.

        O SCR.data só é publicado em pacotes anuais, então não existe extração
        de um mês isolado.
        """
        texto = str(periodo).strip()
        try:
            ano = int(texto[:4])
        except ValueError:
            return CacheResult(
                sucesso=False,
                mensagem=f"Período inválido para o SCR.data: {periodo!r}",
                fonte="nenhum",
            )
        try:
            registro = self.materializar_ano(
                ano,
                manter_zip=bool(kwargs.get("manter_zip", False)),
                log_callback=kwargs.get("log_callback"),
            )
        except Exception as exc:  # noqa: BLE001
            return CacheResult(sucesso=False, mensagem=str(exc), fonte="nenhum")
        return CacheResult(
            sucesso=True,
            mensagem=f"Ano {ano} materializado ({registro['linhas']} linhas)",
            metadata=registro,
            fonte="api",
        )

    def _validar_dados(self, dados: Any) -> Tuple[bool, str]:
        if dados is None:
            return False, "Dados são None"
        if not isinstance(dados, pd.DataFrame):
            return False, f"Esperado DataFrame, recebido {type(dados)}"
        if dados.empty:
            return False, "DataFrame vazio"
        for coluna in RESUMO_REQUIRED_COLUMNS:
            if coluna not in dados.columns:
                return False, f"Coluna obrigatória ausente: {coluna}"
        return True, "OK"

    def limpar_local(self) -> CacheResult:
        resultado = super().limpar_local()
        removidos: List[str] = []
        for path in [*self.dimension_paths().values(), self.manifest_path]:
            if path.exists():
                path.unlink()
                removidos.append(path.name)
        if self.staging_dir.exists():
            shutil.rmtree(self.staging_dir, ignore_errors=True)
            removidos.append("staging/")
        if removidos:
            return CacheResult(
                sucesso=True,
                mensagem=f"{resultado.mensagem}; extras removidos: {', '.join(removidos)}",
                fonte="nenhum",
            )
        return resultado
