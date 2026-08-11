"""Testes do indicador Custo de Crédito (%) — registro, escala e regras de N/D."""

import math

import pandas as pd
import pytest

from utils.ifdata_cache.critical_screens import resolve_carteira_credito_bruta_value
from utils.ifdata_cache.derived_metrics import (
    DERIVED_METRICS,
    METRIC_CUSTO_CREDITO,
    _resolve_carteira_credito_bruta_series,
    build_derived_metrics,
)
from utils.ifdata_cache.metric_registry import (
    DERIVED_METRIC_KEYS,
    METRIC_REGISTRY,
    get_derived_metric_formula_map,
)


# `Valor` é persistido em float32 no cache derivado; a tolerância acompanha isso.
TOL = 1e-6

PERIODOS = ["1/2025", "2/2025", "3/2025", "4/2025"]
# Fator de anualização esperado sobre o YTD reconstruído.
FATOR_ANUALIZACAO = {"1/2025": 4.0, "2/2025": 2.0, "3/2025": 12 / 9, "4/2025": 1.0}


def _df_dre(instituicao="Banco A", periodos=None, f3=None, **overrides):
    periodos = list(periodos or PERIODOS)
    f3 = list(f3 if f3 is not None else [-1.0] * len(periodos))
    dados = {
        "Instituição": [instituicao] * len(periodos),
        "Período": periodos,
        "Resultado com Perda Esperada (f)": [-1.0] * len(periodos),
        "Resultado com Perda Esperada de Operações de Crédito (f3)": f3,
        "Rendas de Operações de Crédito (c)": [10.0] * len(periodos),
        "Rendas de Arrendamento Financeiro (d)": [10.0] * len(periodos),
        "Rendas de Outras Operações com Características de Concessão de Crédito (e)": [10.0] * len(periodos),
        "Rendas de Aplicações Interfinanceiras de Liquidez (a)": [5.0] * len(periodos),
        "Rendas de Títulos e Valores Mobiliários (b)": [5.0] * len(periodos),
        "Despesas de Captações (g)": [1.0] * len(periodos),
    }
    dados.update(overrides)
    return pd.DataFrame(dados)


def _df_principal(instituicao="Banco A", periodos=None, captacoes=100.0, carteira=None):
    periodos = list(periodos or PERIODOS)
    dados = {
        "Instituição": [instituicao] * len(periodos),
        "Período": periodos,
        "Captações": [captacoes] * len(periodos),
    }
    if carteira is not None:
        dados["Carteira de Crédito"] = list(carteira)
    return pd.DataFrame(dados)


def _df_ativo(instituicao="Banco A", periodos=None, vcb=None):
    """Relatório 2 no layout 2025+ (Valor Contábil Bruto e1+f1+g1+h1)."""
    periodos = list(periodos or PERIODOS)
    vcb = list(vcb if vcb is not None else [100.0] * len(periodos))
    return pd.DataFrame(
        {
            "Instituição": [instituicao] * len(periodos),
            "Período": periodos,
            "Valor Contábil Bruto (e1)": vcb,
            "Valor Contábil Bruto (f1)": [0.0] * len(periodos),
            "Valor Contábil Bruto (g1)": [0.0] * len(periodos),
            "Valor Contábil Bruto (h1)": [0.0] * len(periodos),
        }
    )


def _custo_credito(df_resultado):
    recorte = df_resultado[df_resultado["Métrica"].astype(str) == METRIC_CUSTO_CREDITO]
    return {str(row["Período"]): row["Valor"] for _, row in recorte.iterrows()}


# ---------------------------------------------------------------- registro


def test_metrica_registrada_no_registry():
    definicao = METRIC_REGISTRY["custo_credito"]
    assert definicao.display_name == METRIC_CUSTO_CREDITO
    assert definicao.unit == "%"
    assert definicao.internal_scale == "decimal_0_1"
    assert definicao.display_format == "pct"
    assert definicao.annualization is not None
    assert definicao.annualization.formula == "Mar=4, Jun=2, Set=12/9, Dez=1"
    assert "Resultado com Perda Esperada de Operações de Crédito (f3)" in definicao.dependencies
    assert "Carteira de Crédito*" in definicao.dependencies


def test_metrica_propagada_para_derived_metrics():
    assert "custo_credito" in DERIVED_METRIC_KEYS
    assert METRIC_CUSTO_CREDITO in DERIVED_METRICS
    assert METRIC_CUSTO_CREDITO in get_derived_metric_formula_map()


# ------------------------------------------------------------ escala/cálculo


def test_escala_interna_decimal_0_1():
    # f3 = -2 por trimestre, carteira 100 -> 1T: |−2| × 4 / 100 = 8% = 0,08 decimal.
    df_resultado, stats = build_derived_metrics(
        _df_dre(f3=[-2.0, -4.0, -2.0, -4.0]),
        _df_principal(),
        df_ativo=_df_ativo(),
    )
    valores = _custo_credito(df_resultado)
    assert stats.carteira_fonte == "relatorio_2_carteira_credito_bruta"
    assert math.isclose(float(valores["1/2025"]), 0.08, rel_tol=TOL)
    assert 0.0 < float(valores["1/2025"]) < 1.0


@pytest.mark.parametrize("periodo", PERIODOS)
def test_regra_de_anualizacao_por_trimestre(periodo):
    """Set/Dez são Jul-Set e Jul-Dez: o YTD soma junho antes de anualizar."""
    f3 = {"1/2025": -3.0, "2/2025": -7.0, "3/2025": -4.0, "4/2025": -9.0}
    ytd_esperado = {
        "1/2025": 3.0,
        "2/2025": 7.0,
        "3/2025": 4.0 + 7.0,
        "4/2025": 9.0 + 7.0,
    }
    df_resultado, _ = build_derived_metrics(
        _df_dre(f3=[f3[p] for p in PERIODOS]),
        _df_principal(),
        df_ativo=_df_ativo(),
    )
    valores = _custo_credito(df_resultado)
    esperado = ytd_esperado[periodo] * FATOR_ANUALIZACAO[periodo] / 100.0
    assert math.isclose(float(valores[periodo]), esperado, rel_tol=TOL)


def test_numerador_usa_valor_absoluto():
    """PDD publicada como negativa e como positiva devem gerar o mesmo custo."""
    negativa, _ = build_derived_metrics(
        _df_dre(f3=[-2.0] * 4), _df_principal(), df_ativo=_df_ativo()
    )
    positiva, _ = build_derived_metrics(
        _df_dre(f3=[2.0] * 4), _df_principal(), df_ativo=_df_ativo()
    )
    assert math.isclose(
        float(_custo_credito(negativa)["1/2025"]),
        float(_custo_credito(positiva)["1/2025"]),
        rel_tol=TOL,
    )


# --------------------------------------------------------------- regras N/D


def test_nd_quando_junho_ausente():
    """Sem junho publicado o YTD de Set/Dez não é reconstruível — nunca imputar zero."""
    periodos = ["1/2025", "3/2025", "4/2025"]
    df_resultado, _ = build_derived_metrics(
        _df_dre(periodos=periodos, f3=[-3.0, -4.0, -9.0]),
        _df_principal(periodos=periodos),
        df_ativo=_df_ativo(periodos=periodos),
    )
    valores = _custo_credito(df_resultado)
    assert not pd.isna(valores["1/2025"])
    assert pd.isna(valores["3/2025"])
    assert pd.isna(valores["4/2025"])


@pytest.mark.parametrize("carteira", [0.0, float("nan")])
def test_nd_quando_carteira_zero_ou_ausente(carteira):
    df_resultado, _ = build_derived_metrics(
        _df_dre(f3=[-2.0] * 4),
        _df_principal(),
        df_ativo=_df_ativo(vcb=[carteira] * 4),
    )
    valores = _custo_credito(df_resultado)
    assert all(pd.isna(v) for v in valores.values())


def test_nd_no_layout_anterior_a_2025():
    """Layout antigo do Rel. 4 não abre PDD por tipo de ativo: sem f3, sem métrica."""
    periodos = ["1/2024", "2/2024"]
    df_dre = _df_dre(periodos=periodos).drop(
        columns=["Resultado com Perda Esperada de Operações de Crédito (f3)"]
    )
    df_resultado, _ = build_derived_metrics(
        df_dre,
        _df_principal(periodos=periodos),
        df_ativo=_df_ativo(periodos=periodos),
    )
    valores = _custo_credito(df_resultado)
    assert set(valores) == set(periodos)
    assert all(pd.isna(v) for v in valores.values())


def test_nd_quando_instituicao_nao_tem_carteira_no_relatorio_2():
    df_resultado, _ = build_derived_metrics(
        _df_dre(f3=[-2.0] * 4),
        _df_principal(),
        df_ativo=_df_ativo(instituicao="Outro Banco"),
    )
    assert all(pd.isna(v) for v in _custo_credito(df_resultado).values())


# ------------------------------------------------------------ denominador


def test_fallback_para_carteira_do_principal_sem_relatorio_2():
    df_resultado, stats = build_derived_metrics(
        _df_dre(f3=[-2.0] * 4),
        _df_principal(carteira=[200.0] * 4),
        df_ativo=None,
    )
    assert stats.carteira_fonte == "fallback_principal:Carteira de Crédito"
    assert math.isclose(float(_custo_credito(df_resultado)["1/2025"]), 0.04, rel_tol=TOL)


def test_sem_carteira_em_nenhuma_fonte_resulta_em_nd():
    df_resultado, stats = build_derived_metrics(
        _df_dre(f3=[-2.0] * 4), _df_principal(), df_ativo=None
    )
    assert stats.carteira_fonte == "indisponivel"
    assert all(pd.isna(v) for v in _custo_credito(df_resultado).values())


CENARIOS_CARTEIRA = [
    # (período, colunas do Rel. 2) -> cobre legado completo, legado incompleto,
    # VCB completo, VCB incompleto e ausência total de componentes.
    (
        "1/2024",
        {
            "Operações de Crédito (d1)": 100.0,
            "Arrendamento Mercantil a Receber (e1)": 10.0,
            "Outros Créditos - Líquido de Provisão (f)": 5.0,
        },
    ),
    (
        "1/2024",
        {
            "Operações de Crédito (d1)": 100.0,
            "Arrendamento Mercantil a Receber (e1)": None,
            "Outros Créditos - Líquido de Provisão (f)": 5.0,
            "Operações de Crédito (e)": 90.0,
            "Operações de Arrendamento Financeiro (f)": 1.0,
            "Outras Operações com Características de Concessão de Crédito (g)": 2.0,
            "Valores a Receber de Transações de Pagamentos - Usuários Finais (Pós-pago) (h)": 3.0,
        },
    ),
    (
        "1/2026",
        {
            "Valor Contábil Bruto (e1)": 70.0,
            "Valor Contábil Bruto (f1)": 5.0,
            "Valor Contábil Bruto (g1)": 3.0,
            "Valor Contábil Bruto (h1)": 2.0,
        },
    ),
    (
        "1/2026",
        {
            "Valor Contábil Bruto (e1)": 70.0,
            "Valor Contábil Bruto (f1)": None,
            "Valor Contábil Bruto (g1)": 3.0,
            "Valor Contábil Bruto (h1)": 2.0,
            "Operações de Crédito (e)": 60.0,
            "Operações de Arrendamento Financeiro (f)": 1.0,
            "Outras Operações com Características de Concessão de Crédito (g)": 1.0,
            "Valores a Receber de Transações de Pagamentos - Usuários Finais (Pós-pago) (h)": 1.0,
        },
    ),
    ("1/2026", {"Valor Contábil Bruto (e1)": 70.0}),
]


def test_carteira_vetorizada_equivale_a_regra_canonica():
    """A versão vetorizada deve reproduzir `resolve_carteira_credito_bruta_value`."""
    colunas = sorted({col for _, campos in CENARIOS_CARTEIRA for col in campos})
    linhas = []
    for periodo, campos in CENARIOS_CARTEIRA:
        linha = {"Instituição": "Banco A", "Período": periodo}
        linha.update({col: campos.get(col) for col in colunas})
        linhas.append(linha)
    df_ativo = pd.DataFrame(linhas)

    serie = _resolve_carteira_credito_bruta_series(df_ativo)

    for pos, (periodo, campos) in enumerate(CENARIOS_CARTEIRA):
        esperado = resolve_carteira_credito_bruta_value(
            year_ref=int(periodo.split("/")[1]),
            legacy_credito_value=campos.get("Operações de Crédito (d1)"),
            legacy_arrendamento_value=campos.get("Arrendamento Mercantil a Receber (e1)"),
            legacy_outros_value=campos.get("Outros Créditos - Líquido de Provisão (f)"),
            vcb_credito_value=campos.get("Valor Contábil Bruto (e1)"),
            vcb_arrendamento_value=campos.get("Valor Contábil Bruto (f1)"),
            vcb_outras_ops_value=campos.get("Valor Contábil Bruto (g1)"),
            vcb_pagamentos_value=campos.get("Valor Contábil Bruto (h1)"),
            net_credito_value=campos.get("Operações de Crédito (e)"),
            net_arrendamento_value=campos.get("Operações de Arrendamento Financeiro (f)"),
            net_outras_ops_value=campos.get(
                "Outras Operações com Características de Concessão de Crédito (g)"
            ),
            net_pagamentos_value=campos.get(
                "Valores a Receber de Transações de Pagamentos - Usuários Finais (Pós-pago) (h)"
            ),
        )["value"]
        obtido = serie.iloc[pos]
        if esperado is None:
            assert pd.isna(obtido), f"cenário {pos} ({periodo}) deveria ser N/D"
        else:
            assert math.isclose(float(obtido), float(esperado), rel_tol=1e-9), f"cenário {pos}"
