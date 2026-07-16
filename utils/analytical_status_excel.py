"""Escrita compartilhada da aba de status analítico em exports Excel."""

from collections.abc import Callable, Mapping
from typing import Any

import pandas as pd
import xlsxwriter


def write_analytical_status_sheet(
    workbook: xlsxwriter.Workbook,
    *,
    rows: list[dict],
    sheet_name: str = "status_analitico",
    coerce_numeric: Callable[[Any], Any],
    is_percentage: Callable[[str], bool],
    percent_decimals: Mapping[str, int],
) -> None:
    """Adiciona a aba padronizada sem assumir a propriedade do workbook."""
    if not rows:
        return

    border = {"border": 1, "border_color": "#dddddd"}
    header = workbook.add_format(
        {"bold": True, "align": "center", "valign": "vcenter", "bg_color": "#111111", "font_color": "white", **border}
    )
    text_fmt = workbook.add_format({"align": "left", "valign": "top", "text_wrap": True, **border})
    num_fmt = workbook.add_format({"align": "right", "valign": "top", "num_format": "#,##0.00", **border})
    pct1_fmt = workbook.add_format({"align": "right", "valign": "top", "num_format": "0.0%", **border})
    pct2_fmt = workbook.add_format({"align": "right", "valign": "top", "num_format": "0.00%", **border})
    mult_fmt = workbook.add_format({"align": "right", "valign": "top", "num_format": "0.00x", **border})

    status_ws = workbook.add_worksheet(sheet_name)
    headers = [
        "Instituição",
        "Período",
        "Indicador",
        "Valor",
        "Status analítico",
        "Fonte analítica",
        "Observação",
    ]
    for col_idx, label in enumerate(headers):
        status_ws.write(0, col_idx, label, header)

    status_ws.set_column(0, 0, 28)
    status_ws.set_column(1, 1, 14)
    status_ws.set_column(2, 2, 32)
    status_ws.set_column(3, 3, 16)
    status_ws.set_column(4, 4, 24)
    status_ws.set_column(5, 5, 42)
    status_ws.set_column(6, 6, 72)

    for row_idx, row in enumerate(rows, start=1):
        status_ws.write(row_idx, 0, row.get("Instituição"), text_fmt)
        status_ws.write(row_idx, 1, row.get("Período"), text_fmt)
        status_ws.write(row_idx, 2, row.get("Indicador"), text_fmt)

        valor_num = coerce_numeric(row.get("Valor"))
        format_key = str(row.get("Format key") or "")
        if valor_num is None or pd.isna(valor_num):
            status_ws.write_blank(row_idx, 3, None, text_fmt)
        elif format_key in percent_decimals:
            dec = percent_decimals[format_key]
            status_ws.write_number(row_idx, 3, float(valor_num), pct1_fmt if dec == 1 else pct2_fmt)
        elif is_percentage(format_key):
            status_ws.write_number(row_idx, 3, float(valor_num), pct2_fmt)
        elif format_key in {"percent", "percent_1"}:
            status_ws.write_number(row_idx, 3, float(valor_num), pct1_fmt)
        elif format_key == "percent_2":
            status_ws.write_number(row_idx, 3, float(valor_num), pct2_fmt)
        elif format_key in {"Ativo/PL", "Crédito/PL (%)", "Carteira de Crédito Bruta / PL", "multiple"}:
            status_ws.write_number(row_idx, 3, float(valor_num), mult_fmt)
        else:
            status_ws.write_number(row_idx, 3, float(valor_num), num_fmt)

        status_ws.write(row_idx, 4, row.get("Status analítico"), text_fmt)
        status_ws.write(row_idx, 5, row.get("Fonte analítica"), text_fmt)
        status_ws.write(row_idx, 6, row.get("Observação"), text_fmt)

    status_ws.freeze_panes(1, 0)
