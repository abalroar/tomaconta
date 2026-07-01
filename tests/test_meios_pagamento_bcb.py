import pandas as pd

from utils.meios_pagamento_bcb import (
    compute_share,
    format_monthly_axis_label,
    format_quarterly_axis_label,
    normalize_meios_pagamento,
    parse_monthly_period,
    parse_quarterly_period,
)


def test_normalize_monthly_payment_methods_preserves_units_and_modalities():
    raw = pd.DataFrame(
        [
            {
                "AnoMes": "202605",
                "quantidadePix": 7855110.08,
                "valorPix": 3478183.09,
                "quantidadeTED": 65540.90,
                "valorTED": 3828233.22,
                "quantidadeTEC": 0.0,
                "valorTEC": 0.0,
                "quantidadeCheque": 6299.28,
                "valorCheque": 28997.49,
                "quantidadeBoleto": 321873.66,
                "valorBoleto": 541107.26,
                "quantidadeDOC": 0.0,
                "valorDOC": 0.0,
            }
        ]
    )

    result = normalize_meios_pagamento(raw, periodicidade="mensal")

    assert set(result["modalidade"]) == {"Pix", "TED", "TEC", "Cheque", "Boleto", "DOC"}
    assert set(result["metrica"]) == {"Quantidade", "Valor"}
    assert set(result["unidade"]) == {"mil transações", "R$ milhão"}
    assert result.loc[result["modalidade"].eq("Pix") & result["metrica"].eq("Valor"), "valor"].iloc[0] == 3478183.09
    assert result["periodo_label"].unique().tolist() == ["05-2026"]


def test_normalize_quarterly_payment_methods_formats_closing_month_label():
    raw = pd.DataFrame(
        [
            {
                "datatrimestre": "2025-03-31",
                "valorPix": 10.0,
                "valorTED": 20.0,
                "valorTEC": 0.0,
                "valorCheque": 1.0,
                "valorBoleto": 3.0,
                "valorDOC": 0.0,
                "valorCartaoCredito": 7.0,
                "valorCartaoDebito": 5.0,
                "valorCartaoPrePago": 2.0,
                "valorTransIntrabancaria": 8.0,
                "valorConvenios": 4.0,
                "valorDebitoDireto": 6.0,
                "valorSaques": 9.0,
                "quantidadePix": 100.0,
                "quantidadeTED": 20.0,
                "quantidadeTEC": 0.0,
                "quantidadeCheque": 1.0,
                "quantidadeBoleto": 3.0,
                "quantidadeDOC": 0.0,
                "quantidadeCartaoCredito": 7.0,
                "quantidadeCartaoDebito": 5.0,
                "quantidadeCartaoPrePago": 2.0,
                "quantidadeTransIntrabancaria": 8.0,
                "quantidadeConvenios": 4.0,
                "quantidadeDebitoDireto": 6.0,
                "quantidadeSaques": 9.0,
            }
        ]
    )

    result = normalize_meios_pagamento(raw, periodicidade="trimestral")

    assert "Cartão de Crédito" in set(result["modalidade"])
    assert "Transferência Intrabancária" in set(result["modalidade"])
    assert result["periodo_label"].unique().tolist() == ["mar-25"]


def test_period_label_helpers_match_dashboard_requirements():
    assert parse_monthly_period("202605") == pd.Timestamp("2026-05-01")
    assert parse_quarterly_period("20251") == pd.Timestamp("2025-03-31")
    assert format_monthly_axis_label(pd.Timestamp("2026-05-01")) == "05-2026"
    assert format_quarterly_axis_label(pd.Timestamp("2025-09-30")) == "set-25"


def test_compute_share_uses_selected_modalities_only():
    df = pd.DataFrame(
        [
            {"periodo": pd.Timestamp("2026-01-01"), "periodo_label": "01-2026", "modalidade": "Pix", "metrica": "Valor", "valor": 80.0},
            {"periodo": pd.Timestamp("2026-01-01"), "periodo_label": "01-2026", "modalidade": "TED", "metrica": "Valor", "valor": 20.0},
            {"periodo": pd.Timestamp("2026-01-01"), "periodo_label": "01-2026", "modalidade": "Boleto", "metrica": "Valor", "valor": 50.0},
        ]
    )

    share = compute_share(df, metric="Valor", modalities=["Pix", "TED"])

    assert share.loc[share["modalidade"].eq("Pix"), "participacao"].iloc[0] == 0.8
    assert share.loc[share["modalidade"].eq("TED"), "participacao"].iloc[0] == 0.2
    assert "Boleto" not in set(share["modalidade"])
