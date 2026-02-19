import math

import pandas as pd

from utils.ifdata_cache.derived_metrics import build_derived_metrics


def _assert_close(actual, expected, tol=1e-6):
    if pd.isna(expected):
        assert pd.isna(actual)
        return
    assert actual is not None
    assert math.isclose(float(actual), float(expected), rel_tol=tol, abs_tol=tol)


def test_metricas_derivadas_basico():
    df_dre = pd.DataFrame(
        {
            "Instituição": ["Banco A", "Banco A"],
            "Período": ["1/2025", "2/2025"],
            "Resultado com Perda Esperada (f)": [10.0, 12.0],
            "Rendas de Operações de Crédito (c)": [50.0, 60.0],
            "Rendas de Arrendamento Financeiro (d)": [25.0, 30.0],
            "Rendas de Outras Operações com Características de Concessão de Crédito (e)": [25.0, 30.0],
            "Rendas de Aplicações Interfinanceiras de Liquidez (a)": [20.0, 24.0],
            "Rendas de Títulos e Valores Mobiliários (b)": [30.0, 36.0],
            "Despesas de Captações (g)": [12.0, 12.0],
        }
    )
    df_principal = pd.DataFrame(
        {
            "Instituição": ["Banco A", "Banco A"],
            "Período": ["1/2025", "2/2025"],
            "Captações": [240.0, 240.0],
        }
    )

    df_resultado, stats = build_derived_metrics(df_dre, df_principal)
    assert stats.total_registros == 6

    df_p1 = df_resultado[df_resultado["Período"] == "1/2025"]
    df_p2 = df_resultado[df_resultado["Período"] == "2/2025"]

    p1_nim = df_p1.loc[df_p1["Métrica"] == "Desp PDD / NIM bruta", "Valor"].iloc[0]
    p1_intermed = df_p1.loc[df_p1["Métrica"] == "Desp PDD / Resultado Intermediação Fin. Bruto", "Valor"].iloc[0]
    _assert_close(p1_nim, 0.10)
    _assert_close(p1_intermed, 10.0 / 150.0)

    p2_desp_capt = df_p2.loc[df_p2["Métrica"] == "Desp Captação / Captação", "Valor"].iloc[0]
    _assert_close(p2_desp_capt, 0.2)


def test_anualizacao_desp_captacao():
    df_dre = pd.DataFrame(
        {
            "Instituição": ["Banco A"] * 4,
            "Período": ["1/2025", "2/2025", "3/2025", "4/2025"],
            "Resultado com Perda Esperada (f)": [1.0, 1.0, 1.0, 1.0],
            "Rendas de Operações de Crédito (c)": [10.0, 10.0, 10.0, 10.0],
            "Rendas de Arrendamento Financeiro (d)": [10.0, 10.0, 10.0, 10.0],
            "Rendas de Outras Operações com Características de Concessão de Crédito (e)": [10.0, 10.0, 10.0, 10.0],
            "Rendas de Aplicações Interfinanceiras de Liquidez (a)": [5.0, 5.0, 5.0, 5.0],
            "Rendas de Títulos e Valores Mobiliários (b)": [5.0, 5.0, 5.0, 5.0],
            "Despesas de Captações (g)": [12.0, 12.0, 12.0, 12.0],
        }
    )
    df_principal = pd.DataFrame(
        {
            "Instituição": ["Banco A"] * 4,
            "Período": ["1/2025", "2/2025", "3/2025", "4/2025"],
            "Captações": [120.0, 120.0, 120.0, 120.0],
        }
    )

    df_resultado, _ = build_derived_metrics(df_dre, df_principal)
    # Set/Dez no DRE são semestrais (2º semestre) e devem ser acumulados com Jun antes da anualização.
    esperado = {
        "1/2025": 0.4,
        "2/2025": 0.2,
        "3/2025": (12.0 + 12.0) * (12 / 9) / 120.0,
        "4/2025": (12.0 + 12.0) * (12 / 12) / 120.0,
    }
    for periodo, valor in esperado.items():
        atual = df_resultado.loc[
            (df_resultado["Período"] == periodo)
            & (df_resultado["Métrica"] == "Desp Captação / Captação"),
            "Valor",
        ].iloc[0]
        _assert_close(atual, valor)


def test_pdd_set_dez_acumulado_e_anualizado_nas_metricas():
    df_dre = pd.DataFrame(
        {
            "Instituição": ["Banco A"] * 4,
            "Período": ["1/2025", "2/2025", "3/2025", "4/2025"],
            "Resultado com Perda Esperada (f)": [3.0, 6.0, 9.0, 12.0],
            "Rendas de Operações de Crédito (c)": [20.0, 20.0, 20.0, 20.0],
            "Rendas de Arrendamento Financeiro (d)": [10.0, 10.0, 10.0, 10.0],
            "Rendas de Outras Operações com Características de Concessão de Crédito (e)": [10.0, 10.0, 10.0, 10.0],
            "Rendas de Aplicações Interfinanceiras de Liquidez (a)": [8.0, 8.0, 8.0, 8.0],
            "Rendas de Títulos e Valores Mobiliários (b)": [12.0, 12.0, 12.0, 12.0],
            "Despesas de Captações (g)": [1.0, 1.0, 1.0, 1.0],
        }
    )
    df_principal = pd.DataFrame(
        {
            "Instituição": ["Banco A"] * 4,
            "Período": ["1/2025", "2/2025", "3/2025", "4/2025"],
            "Captações": [100.0, 100.0, 100.0, 100.0],
        }
    )

    df_resultado, _ = build_derived_metrics(df_dre, df_principal)

    # NIM bruta = 40 em todos os períodos. Para Set/Dez:
    # desp_pdd_ytd = jun + periodo; anualização = ytd * (12/mes)
    esperado_nim = {
        "1/2025": 3.0 * (12 / 3) / 40.0,
        "2/2025": 6.0 * (12 / 6) / 40.0,
        "3/2025": (6.0 + 9.0) * (12 / 9) / 40.0,
        "4/2025": (6.0 + 12.0) * (12 / 12) / 40.0,
    }

    for periodo, valor in esperado_nim.items():
        atual = df_resultado.loc[
            (df_resultado["Período"] == periodo)
            & (df_resultado["Métrica"] == "Desp PDD / NIM bruta"),
            "Valor",
        ].iloc[0]
        _assert_close(atual, valor)


def test_denominador_zero_nan():
    df_dre = pd.DataFrame(
        {
            "Instituição": ["Banco A", "Banco A"],
            "Período": ["1/2025", "2/2025"],
            "Resultado com Perda Esperada (f)": [10.0, 10.0],
            "Rendas de Operações de Crédito (c)": [0.0, 10.0],
            "Rendas de Arrendamento Financeiro (d)": [0.0, 10.0],
            "Rendas de Outras Operações com Características de Concessão de Crédito (e)": [0.0, 10.0],
            "Rendas de Aplicações Interfinanceiras de Liquidez (a)": [0.0, 10.0],
            "Rendas de Títulos e Valores Mobiliários (b)": [0.0, 10.0],
            "Despesas de Captações (g)": [10.0, 10.0],
        }
    )
    df_principal = pd.DataFrame(
        {
            "Instituição": ["Banco A", "Banco A"],
            "Período": ["1/2025", "2/2025"],
            "Captações": [0.0, 100.0],
        }
    )

    df_resultado, stats = build_derived_metrics(df_dre, df_principal)
    valor_nim = df_resultado.loc[
        (df_resultado["Período"] == "1/2025")
        & (df_resultado["Métrica"] == "Desp PDD / NIM bruta"),
        "Valor",
    ].iloc[0]
    assert pd.isna(valor_nim)
    valor_capt = df_resultado.loc[
        (df_resultado["Período"] == "1/2025")
        & (df_resultado["Métrica"] == "Desp Captação / Captação"),
        "Valor",
    ].iloc[0]
    assert pd.isna(valor_capt)
    assert stats.denominador_zero_ou_nan["Desp PDD / NIM bruta"] == 1
    assert stats.denominador_zero_ou_nan["Desp Captação / Captação"] == 1


if __name__ == "__main__":
    test_metricas_derivadas_basico()
    test_anualizacao_desp_captacao()
    test_pdd_set_dez_acumulado_e_anualizado_nas_metricas()
    test_denominador_zero_nan()
    print("OK")
