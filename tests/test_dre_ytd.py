import math

import pandas as pd

import app1


def test_compute_ytd_irregular_ifdata_frame_requires_june_for_sep_and_dec():
    df = pd.DataFrame(
        [
            {"Instituicao": "Banco A", "Label": "Lucro", "Periodo": "1/2025", "valor": 10.0},
            {"Instituicao": "Banco A", "Label": "Lucro", "Periodo": "3/2025", "valor": 7.0},
            {"Instituicao": "Banco A", "Label": "Lucro", "Periodo": "4/2025", "valor": 9.0},
        ]
    )

    result = app1._compute_ytd_irregular_ifdata_frame(df)
    lookup = {str(row["Periodo"]): row["ytd"] for _, row in result.iterrows()}

    assert lookup["1/2025"] == 10.0
    assert math.isnan(lookup["3/2025"])
    assert math.isnan(lookup["4/2025"])


def test_compute_ytd_irregular_ifdata_frame_accumulates_with_june_when_available():
    df = pd.DataFrame(
        [
            {"Instituicao": "Banco A", "Label": "Lucro", "Periodo": "1/2025", "valor": 10.0},
            {"Instituicao": "Banco A", "Label": "Lucro", "Periodo": "2/2025", "valor": 20.0},
            {"Instituicao": "Banco A", "Label": "Lucro", "Periodo": "3/2025", "valor": 7.0},
            {"Instituicao": "Banco A", "Label": "Lucro", "Periodo": "4/2025", "valor": 9.0},
        ]
    )

    result = app1._compute_ytd_irregular_ifdata_frame(df)
    lookup = {str(row["Periodo"]): row["ytd"] for _, row in result.iterrows()}

    assert lookup["1/2025"] == 10.0
    assert lookup["2/2025"] == 20.0
    assert lookup["3/2025"] == 27.0
    assert lookup["4/2025"] == 29.0


def test_compute_ytd_irregular_ifdata_frame_handles_unsorted_multi_label_input():
    df = pd.DataFrame(
        [
            {"Instituicao": "Banco A", "Label": "Lucro", "Periodo": "3/2025", "valor": 7.0},
            {"Instituicao": "Banco B", "Label": "Lucro", "Periodo": "2/2025", "valor": 30.0},
            {"Instituicao": "Banco A", "Label": "Receita", "Periodo": "2/2025", "valor": 100.0},
            {"Instituicao": "Banco A", "Label": "Lucro", "Periodo": "2/2025", "valor": 20.0},
            {"Instituicao": "Banco B", "Label": "Lucro", "Periodo": "3/2025", "valor": 9.0},
            {"Instituicao": "Banco A", "Label": "Receita", "Periodo": "3/2025", "valor": 40.0},
        ]
    )

    result = app1._compute_ytd_irregular_ifdata_frame(df)
    lookup = {
        (str(row["Instituicao"]), str(row["Label"]), str(row["Periodo"])): row["ytd"]
        for _, row in result.iterrows()
    }

    assert lookup[("Banco A", "Lucro", "3/2025")] == 27.0
    assert lookup[("Banco B", "Lucro", "3/2025")] == 39.0
    assert lookup[("Banco A", "Receita", "3/2025")] == 140.0


def test_normalizar_lucro_liquido_accumulates_semester_for_rankings():
    df = pd.DataFrame(
        [
            {"Instituição": "Banco A", "Período": "1/2025", "Lucro Líquido Acumulado YTD": 10.0},
            {"Instituição": "Banco A", "Período": "2/2025", "Lucro Líquido Acumulado YTD": 20.0},
            {"Instituição": "Banco A", "Período": "3/2025", "Lucro Líquido Acumulado YTD": 7.0},
            {"Instituição": "Banco A", "Período": "4/2025", "Lucro Líquido Acumulado YTD": 9.0},
        ]
    )

    result = app1._normalizar_lucro_liquido(df)
    lookup = {row["Período"]: row for _, row in result.iterrows()}

    assert lookup["1/2025"]["Lucro Líquido Acumulado YTD"] == 10.0
    assert lookup["2/2025"]["Lucro Líquido Acumulado YTD"] == 20.0
    assert lookup["3/2025"]["Lucro Líquido Acumulado YTD"] == 27.0
    assert lookup["4/2025"]["Lucro Líquido Acumulado YTD"] == 29.0

    assert lookup["1/2025"]["Lucro Líquido Trimestral"] == 10.0
    assert lookup["2/2025"]["Lucro Líquido Trimestral"] == 10.0
    assert lookup["3/2025"]["Lucro Líquido Trimestral"] == 7.0
    assert lookup["4/2025"]["Lucro Líquido Trimestral"] == 2.0


def test_normalizar_lucro_liquido_does_not_keep_raw_sep_dec_without_june():
    df = pd.DataFrame(
        [
            {"Instituição": "Banco A", "Período": "1/2025", "Lucro Líquido Acumulado YTD": 10.0},
            {"Instituição": "Banco A", "Período": "3/2025", "Lucro Líquido Acumulado YTD": 7.0},
            {"Instituição": "Banco A", "Período": "4/2025", "Lucro Líquido Acumulado YTD": 9.0},
        ]
    )

    result = app1._normalizar_lucro_liquido(df)
    lookup = {row["Período"]: row["Lucro Líquido Acumulado YTD"] for _, row in result.iterrows()}

    assert lookup["1/2025"] == 10.0
    assert math.isnan(lookup["3/2025"])
    assert math.isnan(lookup["4/2025"])


def test_rankings_accumulated_metrics_request_ytd_dependencies():
    result = app1._resolve_rankings_source_request(
        "Resumo",
        "Lucro Líquido Acumulado YTD",
        ["4/2025"],
    )

    assert result["source_kind"] == "analytical_principal"
    assert set(result["periodos_filter"]) == {"2/2025", "4/2025"}


def test_rankings_accumulated_table_requests_ytd_and_roe_dependencies():
    result = app1._resolve_rankings_source_request(
        "Tabela",
        "Ativo Total",
        [],
        periodo_tabela="4/2025",
        modo_tabela="Acumulado",
    )

    assert result["source_kind"] == "analytical_with_capital"
    assert set(result["periodos_filter"]) == {"4/2024", "2/2025", "4/2025"}


def test_periodo_default_helpers_select_latest_available_quarter_or_month():
    assert app1._periodo_mais_recente(["3/2025", "1/2025", "4/2025", "2/2025"]) == "4/2025"
    assert app1._indice_periodo_mais_recente(["3/2025", "4/2025", "2/2025"]) == 1
    assert app1._periodos_mais_recentes(["2/2025", "4/2025", "3/2025"], 2) == ["4/2025", "3/2025"]

    assert app1._periodo_mais_recente(["202509", "202512", "202506"]) == "202512"
    assert app1._indice_periodo_mais_recente(["202509", "202512", "202506"]) == 1
