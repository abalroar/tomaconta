from __future__ import annotations

import csv
from pathlib import Path
from typing import List, Sequence
import zipfile
from xml.sax.saxutils import escape

CSV_INPUT_PATH = Path("data/dre_cosif_mapeamento_explicativo.csv")
XLSX_OUTPUT_PATH = Path("data/DRE_COSIF_mapeamento_explicativo.xlsx")


def _col_name(idx: int) -> str:
    out = ""
    n = idx
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def _sheet_xml(rows: Sequence[Sequence[str]]) -> str:
    body = []
    for r_idx, row in enumerate(rows, start=1):
        cells = []
        for c_idx, value in enumerate(row, start=1):
            ref = f"{_col_name(c_idx)}{r_idx}"
            txt = escape(str(value))
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{txt}</t></is></c>')
        body.append(f"<row r=\"{r_idx}\">{''.join(cells)}</row>")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(body)}</sheetData>"
        "</worksheet>"
    )


def _load_csv_rows() -> List[List[str]]:
    with CSV_INPUT_PATH.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        return [list(row) for row in reader]


def _write_xlsx(rows: List[List[str]]) -> None:
    content_types = """<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>
  <Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>
  <Default Extension='xml' ContentType='application/xml'/>
  <Override PartName='/xl/workbook.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'/>
  <Override PartName='/xl/worksheets/sheet1.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/>
</Types>"""
    rels = """<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>
  <Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='xl/workbook.xml'/>
</Relationships>"""
    workbook = """<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'>
  <sheets>
    <sheet name='DRE_COSIF' sheetId='1' r:id='rId1'/>
  </sheets>
</workbook>"""
    wb_rels = """<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>
  <Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet1.xml'/>
</Relationships>"""

    XLSX_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(XLSX_OUTPUT_PATH, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        zf.writestr("xl/worksheets/sheet1.xml", _sheet_xml(rows))


def main() -> None:
    rows = _load_csv_rows()
    _write_xlsx(rows)
    print(f"arquivo gerado: {XLSX_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
