from io import BytesIO

from openpyxl import load_workbook

import app1


def _find_row_by_label(ws, label: str) -> int:
    for row_idx in range(1, ws.max_row + 1):
        if ws.cell(row=row_idx, column=1).value == label:
            return row_idx
    raise AssertionError(f"label not found: {label}")


def test_peers_raw_export_writes_numeric_values_without_visual_arrows():
    bancos = ["TEST BANK - PRUDENCIAL"]
    periodos = ["4/2025"]
    valores = {
        ("Ativo Total", "TEST BANK - PRUDENCIAL", "4/2025"): 1_500_000_000.0,
        ("ROE Acumulado YTD (%)", "TEST BANK - PRUDENCIAL", "4/2025"): 0.125,
    }
    colunas_usadas = {
        "Ativo Total": "Ativo Total",
        "ROE Acumulado YTD (%)": "ROE Ac. Anualizado (%)",
    }
    delta_flags = {
        ("Ativo Total", "TEST BANK - PRUDENCIAL", "4/2025"): "up",
        ("ROE Acumulado YTD (%)", "TEST BANK - PRUDENCIAL", "4/2025"): "down",
    }

    output = app1._gerar_excel_peers_dados_puros(
        bancos=bancos,
        periodos=periodos,
        valores=valores,
        colunas_usadas=colunas_usadas,
        delta_flags=delta_flags,
    )

    wb = load_workbook(BytesIO(output.getvalue()), data_only=True)
    ws = wb["dados_numericos"]

    ativo_row = _find_row_by_label(ws, "Ativo Total")
    roe_row = _find_row_by_label(ws, "ROE Acumulado YTD (%)")

    ativo_val = ws.cell(row=ativo_row, column=2).value
    roe_val = ws.cell(row=roe_row, column=2).value

    assert isinstance(ativo_val, (int, float))
    assert isinstance(roe_val, (int, float))
    assert ativo_val == 1_500_000_000.0
    assert round(float(roe_val), 6) == 0.125
