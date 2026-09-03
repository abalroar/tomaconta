"""Camada de consulta do SCR.data.

Funções puras sobre os DataFrames materializados por
``utils.ifdata_cache.scr_data``. Nenhuma dependência de Streamlit: a aba, os
testes e eventuais exportações usam exatamente as mesmas funções.

Regra que atravessa o módulo inteiro: **toda taxa é razão de somas**
(``Σ numerador / Σ denominador`` depois do filtro), nunca média de razões.
Agregar percentuais já calculados de UFs ou de produtos com carteiras de
tamanhos diferentes produz número sem significado.

Unidade das colunas monetárias: **R$ mil** (definida na materialização).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import pandas as pd
import requests

from utils.ifdata_cache.scr_data import (
    ORDEM_REGIOES,
    ORDEM_SEGMENTOS,
    PORTE_INDISPONIVEL,
    PORTE_PF_LIMITES,
    PORTE_PF_ORDEM,
    PORTE_PF_ROTULO_CURTO,
    PORTE_PJ_ORDEM,
    QUEBRAS_DE_SERIE,
    REGIAO_POR_UF,
    SUBMODALIDADES_LEGADO,
)

logger = logging.getLogger("scr_data_query")

ESCALA_MONETARIA = 1000.0  # o parquet guarda R$ mil


# =============================================================================
# MÉTRICAS
# =============================================================================

@dataclass(frozen=True)
class Metrica:
    """Definição de uma métrica exibível.

    ``numerador``/``denominador`` são nomes de colunas do fato. Quando
    ``denominador`` é ``None`` a métrica é de nível (soma simples).
    """

    chave: str
    rotulo: str
    numerador: str
    denominador: Optional[str]
    formato: str  # "percentual" | "monetario" | "contagem"
    descricao: str


METRICAS: Dict[str, Metrica] = {
    "inadimplencia": Metrica(
        chave="inadimplencia",
        rotulo="Inadimplência",
        numerador="carteira_inadimplencia",
        denominador="carteira_ativa",
        formato="percentual",
        descricao=(
            "Saldo total das operações com alguma parcela vencida há mais de 90 "
            "dias, dividido pela carteira ativa. O numerador é o saldo inteiro "
            "da operação contaminada, não só a parcela vencida."
        ),
    ),
    "ativo_problematico": Metrica(
        chave="ativo_problematico",
        rotulo="Ativo problemático",
        numerador="ativo_problematico",
        denominador="carteira_ativa",
        formato="percentual",
        descricao=(
            "Operações em atraso acima de 90 dias somadas às que têm indício de "
            "não pagamento integral. Até dez/2024 usava a régua de risco E–H; "
            "a partir de jan/2025 vale a marcação da própria instituição."
        ),
    ),
    "atraso_15_90": Metrica(
        chave="atraso_15_90",
        rotulo="Atraso 15–90 dias",
        numerador="vencido_de_15_ate_90_dias",
        denominador="carteira_ativa",
        formato="percentual",
        descricao=(
            "Parcela vencida entre 15 e 90 dias sobre a carteira ativa. "
            "Indicador antecedente da inadimplência."
        ),
    ),
    "vencido_90": Metrica(
        chave="vencido_90",
        rotulo="Vencido acima de 90 dias",
        numerador="vencido_acima_de_90_dias",
        denominador="carteira_ativa",
        formato="percentual",
        descricao=(
            "Apenas a parcela efetivamente vencida há mais de 90 dias. Sempre "
            "menor que a inadimplência, que carrega o saldo inteiro da operação."
        ),
    ),
    "carteira_ativa": Metrica(
        chave="carteira_ativa",
        rotulo="Carteira ativa",
        numerador="carteira_ativa",
        denominador=None,
        formato="monetario",
        descricao="Soma dos valores a vencer e vencidos.",
    ),
    "numero_de_operacoes": Metrica(
        chave="numero_de_operacoes",
        rotulo="Número de operações",
        numerador="numero_de_operacoes",
        denominador=None,
        formato="contagem",
        descricao=(
            "Subestimado: o BCB grava -1 quando a contagem do recorte é "
            "sigilosa, e essas linhas entram como zero."
        ),
    ),
}

METRICAS_PERCENTUAIS = [
    chave for chave, m in METRICAS.items() if m.formato == "percentual"
]

METRICA_PADRAO = "inadimplencia"


def obter_metrica(metrica: Any) -> Metrica:
    """Aceita a chave, o rótulo ou a própria ``Metrica``."""
    if isinstance(metrica, Metrica):
        return metrica
    chave = str(metrica)
    if chave in METRICAS:
        return METRICAS[chave]
    for definicao in METRICAS.values():
        if definicao.rotulo == chave:
            return definicao
    raise KeyError(f"Métrica desconhecida: {metrica!r}")


# =============================================================================
# ORDENS CATEGÓRICAS
# =============================================================================

def ordem_portes(cliente: str) -> List[str]:
    """Ordem natural das faixas de porte, com "Indisponível" no fim.

    A ordem é a da renda/faturamento, nunca a do valor da métrica: é justamente
    a monotonia (ou a quebra dela) que se quer ler no gráfico.
    """
    if str(cliente).upper() == "PF":
        return [*PORTE_PF_ORDEM, PORTE_INDISPONIVEL]
    if str(cliente).upper() == "PJ":
        return [*PORTE_PJ_ORDEM, PORTE_INDISPONIVEL]
    raise ValueError(f"cliente deve ser 'PF' ou 'PJ', recebido {cliente!r}")


def ordenar_categorico(
    df: pd.DataFrame, coluna: str, ordem: Sequence[str]
) -> pd.DataFrame:
    """Reordena ``df`` por uma ordem categórica explícita.

    Categorias fora de ``ordem`` são mantidas no fim, em ordem alfabética — um
    valor novo do BCB não pode sumir da tela silenciosamente.
    """
    if coluna not in df.columns:
        return df
    presentes = [str(v) for v in df[coluna].astype(str).unique()]
    extras = sorted(v for v in presentes if v not in ordem)
    categorias = [v for v in ordem if v in presentes] + extras
    out = df.copy()
    out[coluna] = pd.Categorical(out[coluna].astype(str), categories=categorias, ordered=True)
    return out.sort_values(coluna, kind="stable")


ORDENS_PADRAO: Dict[str, Sequence[str]] = {
    "regiao": ORDEM_REGIOES,
    "segmento": ORDEM_SEGMENTOS,
}


# =============================================================================
# FILTRO
# =============================================================================

def adicionar_regiao(df: pd.DataFrame) -> pd.DataFrame:
    """Deriva ``regiao`` a partir de ``uf`` quando o fato tem grão de UF."""
    if "regiao" in df.columns or "uf" not in df.columns:
        return df
    out = df.copy()
    out["regiao"] = out["uf"].astype(str).map(REGIAO_POR_UF)
    return out


def filtrar(
    df: pd.DataFrame,
    *,
    cliente: Optional[Any] = None,
    porte: Optional[Any] = None,
    uf: Optional[Any] = None,
    regiao: Optional[Any] = None,
    segmento: Optional[Any] = None,
    modalidade: Optional[Any] = None,
    submodalidade: Optional[Any] = None,
    modalidade_bcb: Optional[Any] = None,
    data_base_inicial: Optional[str] = None,
    data_base_final: Optional[str] = None,
    excluir_legado: bool = False,
) -> pd.DataFrame:
    """Aplica os filtros da barra de contexto.

    ``None`` significa "não filtrar". Valores escalares e iteráveis são
    aceitos. ``excluir_legado`` remove as submodalidades residuais de migração
    de leiaute (ver ``SUBMODALIDADES_LEGADO``).
    """
    out = df
    if regiao is not None and "regiao" not in out.columns:
        out = adicionar_regiao(out)

    condicoes = {
        "cliente": cliente,
        "porte": porte,
        "uf": uf,
        "regiao": regiao,
        "segmento": segmento,
        "modalidade": modalidade,
        "submodalidade": submodalidade,
        "modalidade_bcb": modalidade_bcb,
    }
    for coluna, valor in condicoes.items():
        if valor is None or coluna not in out.columns:
            continue
        alvo = _como_lista(valor)
        if not alvo:
            continue
        out = out[out[coluna].astype(str).isin(alvo)]

    if data_base_inicial is not None and "data_base" in out.columns:
        out = out[out["data_base"].astype(str) >= str(data_base_inicial)]
    if data_base_final is not None and "data_base" in out.columns:
        out = out[out["data_base"].astype(str) <= str(data_base_final)]

    if excluir_legado and "submodalidade" in out.columns:
        out = out[~out["submodalidade"].astype(str).isin(SUBMODALIDADES_LEGADO)]

    return out


def _como_lista(valor: Any) -> List[str]:
    if isinstance(valor, str):
        return [valor]
    if isinstance(valor, Iterable):
        return [str(item) for item in valor]
    return [str(valor)]


# =============================================================================
# AGREGAÇÃO
# =============================================================================

def agregar(
    df: pd.DataFrame,
    metrica: Any = METRICA_PADRAO,
    *,
    by: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """Agrega ``metrica`` por ``by``, sempre como razão de somas.

    Devolve as colunas de ``by`` mais ``numerador``, ``denominador`` e
    ``valor``. Manter o denominador ao lado é intencional: nenhuma taxa deve ser
    lida sem o tamanho da carteira que a produziu.
    """
    definicao = obter_metrica(metrica)
    chaves = list(by or [])

    colunas_soma = [definicao.numerador]
    if definicao.denominador and definicao.denominador != definicao.numerador:
        colunas_soma.append(definicao.denominador)

    faltantes = [c for c in [*chaves, *colunas_soma] if c not in df.columns]
    if faltantes:
        raise KeyError(f"Colunas ausentes para a agregação: {', '.join(faltantes)}")

    if df.empty:
        return pd.DataFrame(columns=[*chaves, "numerador", "denominador", "valor"])

    if chaves:
        agregado = df.groupby(chaves, as_index=False, observed=True)[colunas_soma].sum()
    else:
        agregado = df[colunas_soma].sum().to_frame().T

    agregado["numerador"] = agregado[definicao.numerador].astype("float64")
    if definicao.denominador:
        agregado["denominador"] = agregado[definicao.denominador].astype("float64")
        agregado["valor"] = agregado["numerador"].div(agregado["denominador"]).where(
            agregado["denominador"] > 0
        )
    else:
        agregado["denominador"] = pd.NA
        agregado["valor"] = agregado["numerador"]

    colunas_finais = [*chaves, "numerador", "denominador", "valor"]
    resultado = agregado[colunas_finais]

    for coluna in chaves:
        ordem = ORDENS_PADRAO.get(coluna)
        if ordem:
            resultado = ordenar_categorico(resultado, coluna, ordem)
    return resultado.reset_index(drop=True)


def serie_temporal(
    df: pd.DataFrame,
    metrica: Any = METRICA_PADRAO,
    *,
    by: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """Série mensal da métrica, opcionalmente quebrada por outras dimensões."""
    chaves = ["data_base", *(by or [])]
    resultado = agregar(df, metrica, by=chaves)
    return resultado.sort_values(chaves, kind="stable").reset_index(drop=True)


def ranking(
    df: pd.DataFrame,
    dimensao: str,
    metrica: Any = METRICA_PADRAO,
    *,
    carteira_minima_rs_mil: float = 0.0,
    excluir_legado: bool = True,
    ascendente: bool = False,
    limite: Optional[int] = None,
) -> pd.DataFrame:
    """Ranking por dimensão, com filtro de materialidade.

    Sem ``carteira_minima_rs_mil`` a cauda longa domina: recortes com carteira
    irrisória produzem taxas extremas e enganosas. ``excluir_legado`` é ``True``
    por padrão porque as submodalidades residuais de migração ocupariam o topo
    de qualquer ranking de inadimplência sem serem produto comercial.
    """
    base = df
    if excluir_legado and "submodalidade" in base.columns:
        base = base[~base["submodalidade"].astype(str).isin(SUBMODALIDADES_LEGADO)]

    resultado = agregar(base, metrica, by=[dimensao])
    if resultado.empty:
        return resultado

    if carteira_minima_rs_mil > 0:
        coluna_corte = "denominador" if resultado["denominador"].notna().any() else "numerador"
        resultado = resultado[resultado[coluna_corte] >= carteira_minima_rs_mil]

    resultado = resultado.sort_values("valor", ascending=ascendente, kind="stable")
    if limite:
        resultado = resultado.head(limite)
    return resultado.reset_index(drop=True)


def matriz(
    df: pd.DataFrame,
    linhas: str,
    colunas: str,
    metrica: Any = METRICA_PADRAO,
    *,
    ordem_linhas: Optional[Sequence[str]] = None,
    ordem_colunas: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """Tabela cruzada da métrica (para heatmaps), como razão de somas."""
    agregado = agregar(df, metrica, by=[linhas, colunas])
    if agregado.empty:
        return pd.DataFrame()

    tabela = agregado.pivot(index=linhas, columns=colunas, values="valor")

    ordem_l = ordem_linhas or ORDENS_PADRAO.get(linhas)
    if ordem_l:
        presentes = [v for v in ordem_l if v in tabela.index]
        extras = sorted(v for v in tabela.index if v not in (ordem_l or []))
        tabela = tabela.reindex([*presentes, *extras])

    ordem_c = ordem_colunas or ORDENS_PADRAO.get(colunas)
    if ordem_c:
        presentes = [v for v in ordem_c if v in tabela.columns]
        extras = sorted(v for v in tabela.columns if v not in (ordem_c or []))
        tabela = tabela[[*presentes, *extras]]

    return tabela


def kpis(
    df: pd.DataFrame,
    *,
    data_base: Optional[str] = None,
    metricas: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """Valor da data-base e variações contra o mês anterior e 12 meses atrás."""
    chaves = list(metricas or ["carteira_ativa", *METRICAS_PERCENTUAIS])
    if df.empty or "data_base" not in df.columns:
        return pd.DataFrame(columns=["metrica", "rotulo", "formato", "valor", "delta_mm", "delta_12m"])

    datas = sorted(df["data_base"].astype(str).unique())
    referencia = str(data_base) if data_base else datas[-1]
    anterior = _deslocar_data_base(referencia, -1)
    ano_atras = _deslocar_data_base(referencia, -12)

    linhas = []
    for chave in chaves:
        definicao = obter_metrica(chave)
        valores = {}
        for rotulo, alvo in (("atual", referencia), ("mm", anterior), ("12m", ano_atras)):
            recorte = df[df["data_base"].astype(str) == alvo]
            agregado = agregar(recorte, definicao)
            valores[rotulo] = (
                float(agregado["valor"].iloc[0])
                if not agregado.empty and pd.notna(agregado["valor"].iloc[0])
                else None
            )
        linhas.append({
            "metrica": definicao.chave,
            "rotulo": definicao.rotulo,
            "formato": definicao.formato,
            "data_base": referencia,
            "valor": valores["atual"],
            "delta_mm": _delta(valores["atual"], valores["mm"], definicao.formato),
            "delta_12m": _delta(valores["atual"], valores["12m"], definicao.formato),
        })
    return pd.DataFrame(linhas)


def _delta(atual: Optional[float], base: Optional[float], formato: str) -> Optional[float]:
    """Diferença em p.p. para percentuais; variação relativa para níveis."""
    if atual is None or base is None:
        return None
    if formato == "percentual":
        return atual - base
    if base == 0:
        return None
    return atual / base - 1.0


def _deslocar_data_base(data_base: str, meses: int) -> str:
    periodo = pd.Period(str(data_base), freq="M") + meses
    return str(periodo)


# =============================================================================
# JANELA DE CARREGAMENTO
# =============================================================================

def janela_de_data_bases(data_base_final: str, meses: int) -> tuple[str, str]:
    """Intervalo ``(inicial, final)`` de uma janela de ``meses`` data-bases."""
    if meses < 1:
        raise ValueError("meses deve ser >= 1")
    inicial = _deslocar_data_base(data_base_final, -(meses - 1))
    return inicial, str(data_base_final)


def anos_da_janela(data_base_final: str, meses: int) -> List[int]:
    """Anos cujos slices precisam ser carregados para cobrir a janela."""
    inicial, final = janela_de_data_bases(data_base_final, meses)
    return list(range(int(inicial[:4]), int(final[:4]) + 1))


# =============================================================================
# FAIXAS DE RENDA EM REAIS
# =============================================================================

SGS_SALARIO_MINIMO_URL = (
    "https://api.bcb.gov.br/dados/serie/bcdata.sgs.1619/dados?formato=json"
)


def buscar_salario_minimo(
    *, timeout: int = 30, session: Optional[requests.Session] = None
) -> pd.Series:
    """Série mensal do salário mínimo (SGS 1619), indexada por ``YYYY-MM``.

    Devolve série vazia se a API falhar — a conversão das faixas para reais é
    um enriquecimento, não pode derrubar a aba.
    """
    http = session or requests
    try:
        resposta = http.get(SGS_SALARIO_MINIMO_URL, timeout=timeout)
        resposta.raise_for_status()
        registros = resposta.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Falha ao buscar salário mínimo (SGS 1619): %s", exc)
        return pd.Series(dtype="float64")

    df = pd.DataFrame(registros)
    if df.empty or "data" not in df.columns:
        return pd.Series(dtype="float64")
    datas = pd.to_datetime(df["data"], dayfirst=True, errors="coerce")
    valores = pd.to_numeric(df["valor"], errors="coerce")
    serie = pd.Series(valores.values, index=datas.dt.to_period("M").astype(str))
    return serie.dropna()


def rotular_faixas_em_reais(
    salario_minimo: Optional[float],
) -> Dict[str, str]:
    """Rótulo de cada faixa PF em reais, para o valor de SM informado.

    Sem salário mínimo disponível, devolve os rótulos curtos em SM.
    """
    if not salario_minimo or salario_minimo <= 0:
        return dict(PORTE_PF_ROTULO_CURTO)

    rotulos: Dict[str, str] = {}
    for porte, (minimo, maximo) in PORTE_PF_LIMITES.items():
        if porte == "Sem rendimento":
            rotulos[porte] = "sem renda"
            continue
        if maximo is None:
            rotulos[porte] = f"acima de {_reais(minimo * salario_minimo)}"
        elif minimo in (None, 0.0):
            rotulos[porte] = f"até {_reais(maximo * salario_minimo)}"
        else:
            rotulos[porte] = (
                f"{_reais(minimo * salario_minimo)} a {_reais(maximo * salario_minimo)}"
            )
    return rotulos


def _reais(valor: float) -> str:
    inteiro = f"{valor:,.0f}".replace(",", ".")
    return f"R$ {inteiro}"


# =============================================================================
# AVISOS DE QUALIDADE
# =============================================================================

def quebras_no_intervalo(
    data_base_inicial: str, data_base_final: str, metrica: Any = None
) -> List[Dict[str, str]]:
    """Quebras metodológicas que caem dentro da janela exibida.

    Filtra pela métrica quando informada — a quebra de jan/2025 só afeta ativo
    problemático, a de jun/2016 só a contagem de operações.
    """
    chave = obter_metrica(metrica).chave if metrica is not None else None
    selecionadas = []
    for quebra in QUEBRAS_DE_SERIE:
        if not (str(data_base_inicial) <= quebra["data_base"] <= str(data_base_final)):
            continue
        if chave is not None and quebra["metricas"] != chave:
            continue
        selecionadas.append(dict(quebra))
    return selecionadas


def resumo_supressao(df: pd.DataFrame) -> Dict[str, Any]:
    """Quanto do recorte tem contagem de operações suprimida pelo BCB.

    ``ops_suprimidas`` conta as linhas do CSV original em que
    ``numero_de_operacoes`` vinha como -1 e foi zerada; ``carteira_suprimida``
    é a carteira dessas mesmas linhas-fonte. Só o segundo permite dizer "X% da
    carteira do recorte": olhar a carteira das linhas do fato que *tocam*
    alguma supressão superestimaria muito, porque cada linha do fato reúne
    dezenas de linhas-fonte.
    """
    vazio = {
        "linhas_suprimidas": 0,
        "operacoes": 0,
        "carteira_suprimida_rs_mil": 0.0,
        "carteira_total_rs_mil": 0.0,
        "share_carteira": None,
    }
    if df.empty or "ops_suprimidas" not in df.columns:
        return vazio

    total = float(df["carteira_ativa"].astype("float64").sum())
    suprimida = (
        float(df["carteira_suprimida"].astype("float64").sum())
        if "carteira_suprimida" in df.columns
        else 0.0
    )
    return {
        "linhas_suprimidas": int(df["ops_suprimidas"].sum()),
        "operacoes": int(df["numero_de_operacoes"].sum()),
        "carteira_suprimida_rs_mil": suprimida,
        "carteira_total_rs_mil": total,
        "share_carteira": (suprimida / total) if total > 0 else None,
    }


# =============================================================================
# FORMATAÇÃO
# =============================================================================

def formatar_valor(valor: Optional[float], formato: str, *, casas: int = 2) -> str:
    """Formata um valor conforme o tipo da métrica (R$ mil na origem)."""
    if valor is None or pd.isna(valor):
        return "—"
    if formato == "percentual":
        return f"{valor * 100:.{casas}f}%".replace(".", ",")
    if formato == "monetario":
        return formatar_reais_de_mil(valor)
    return f"{valor:,.0f}".replace(",", ".")


def formatar_reais_de_mil(valor_em_mil: float, *, casas: int = 1) -> str:
    """Converte R$ mil na escala legível (mil / mi / bi / tri)."""
    reais = float(valor_em_mil) * ESCALA_MONETARIA
    for limite, sufixo in ((1e12, "tri"), (1e9, "bi"), (1e6, "mi"), (1e3, "mil")):
        if abs(reais) >= limite:
            return f"R$ {reais / limite:.{casas}f} {sufixo}".replace(".", ",")
    return f"R$ {reais:.0f}"
