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
