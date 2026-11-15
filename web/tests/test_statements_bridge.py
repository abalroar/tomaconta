"""Focused parity checks against the actual Python loader and bundled sources.

Run: .venv/bin/python -m unittest discover -s web/tests -p test_statements_bridge.py
"""
from dataclasses import asdict
from io import BytesIO
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "web/tools")]
from export_statements import (Sources, analysis_crosswalk, frame_packet,
                               publish_engine, dump, compress_publication)
from statements_bridge import build_from_payload, analyze, export_native, _frame, serialize_cell
from tabs.prudential_analysis import load_analysis
from utils.prudential_analysis import Cell


class StatementParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = Sources(ROOT)
        cls.payloads = {}
        for key, scope, code in [("individual", "individual", "60701190"),
                ("prudential", "prudential", "C0080099"),
                ("afinz", "prudential", "C0083539"), ("nu", "prudential", "C0084693")]:
            records = cls.sources.catalog(scope)
            cls.payloads[key] = cls.sources.payload(scope, code, records[records.code.eq(code)])

    def manager(self, payload):
        source = self.sources
        code = payload["code"]

        def get_cache(kind):
            def load_institution(identity, periods):
                frame = source.entity("balancete_individual", identity)
                return frame[frame.DATA_BASE.isin(periods)].copy()
            return SimpleNamespace(arquivo_dados=ROOT / f"data/bundled/{kind}/dados.parquet",
                row_overrides=lambda: payload["overrides"], load_institution=load_institution)

        def carregar(kind):
            return SimpleNamespace(sucesso=True, dados=source.entity(kind, code))
        return SimpleNamespace(get_cache=get_cache, carregar=carregar)

    def test_arbitrary_selections_have_full_original_model_parity(self):
        # Nonadjacent columns, prior Dec in/out of selection, June YTD context,
        # and 1/2/8 periods exercise every selection-dependent model path.
        selections = [["202606"], ["202403", "202606"],
            ["202512", "202606"],
            ["202303", "202306", "202309", "202312", "202403", "202409", "202512", "202606"]]
        for scope, payload in self.payloads.items():
            for selected in selections:
                with self.subTest(scope=scope, selected=selected):
                    actual = build_from_payload(payload, selected)
                    expected = load_analysis(self.manager(payload), payload["code"], selected,
                                             individual=scope == "individual")
                    self.assertEqual(asdict(actual), asdict(expected))

    def test_growth_rebuilds_for_the_requested_predecessor(self):
        payload = self.payloads["prudential"]
        single = build_from_payload(payload, ["202606"])
        pair = build_from_payload(payload, ["202503", "202606"])
        row = pair.rows["Carteira 4.966"]["growth"]
        self.assertEqual(single.sheets["Carteira 4.966"].cells[f"C{row}"].value, "N/D")
        current = pair.sheets["Carteira 4.966"].cells[f"E{row}"]
        self.assertIsInstance(current.value, float)
        self.assertIn(f"C{pair.rows['Carteira 4.966']['total']}", current.formula)

    def test_null_zero_identity_period_and_scope_validation(self):
        payload = self.payloads["individual"]
        parsed = json.loads(analyze(json.dumps(payload), '["202606"]'))
        balance = next(table for table in parsed["tables"] if table["name"] == "Balanço")
        capital = next(row for row in balance["rows"] if row["id"] == "cet1")
        self.assertIsNone(capital["cells"]["202606"]["amount"]["value"])
        for selected in [[], ["202606"] * 2, ["201912"], ["202606"] * 9]:
            with self.assertRaises(ValueError):
                build_from_payload(payload, selected)
        with self.assertRaises(ValueError):
            build_from_payload({**payload, "code": "C0080099"}, ["202606"])
        other = json.loads(json.dumps(payload))
        other["cosif"]["constants"]["COD_CONGL"] = "other"
        with self.assertRaises(ValueError):
            build_from_payload(other, ["202606"])

    def test_native_formats_are_real_and_have_selected_periods_and_formulas(self):
        from openpyxl import load_workbook
        payload, periods = self.payloads["prudential"], ["202403", "202606"]
        workbook = load_workbook(BytesIO(export_native(payload, periods, "xlsx")), data_only=False)
        self.assertIn("Dados COSIF", workbook.sheetnames)
        expected = build_from_payload(payload, periods)
        sheet = workbook["Carteira 4.966"]
        row = expected.rows["Carteira 4.966"]["growth"]
        # Native visible sheets paginate; the technical model retains formulas.
        self.assertTrue(any(isinstance(cell.value, str) and cell.value.startswith("=")
                            for ws in workbook for line in ws for cell in line))
        data = export_native(payload, periods, "pptx")
        with zipfile.ZipFile(BytesIO(data)) as archive:
            slides = [archive.read(name).decode() for name in archive.namelist()
                      if name.startswith("ppt/slides/slide") and name.endswith(".xml")]
            xml = "".join(slides)
            self.assertIn("mar/24", xml)
            self.assertIn("jun/26", xml)
            self.assertIn("<a:tbl>", xml)
        with self.assertRaises(ValueError):
            export_native(payload, periods, "pdf")

    def test_crosswalk_uses_official_code_and_exact_source_names(self):
        institutions = [{"id": p["id"], "scope": p["scope"], "periods": p["periods"]}
                        for p in self.payloads.values()]
        links = analysis_crosswalk(self.sources, institutions)["links"]
        self.assertEqual(links["5f6d3c0745685d8f"]["statementId"], "prudential-C0080099")
        self.assertTrue(all(item["scope"] == "prudential" for item in links.values()))
        self.assertTrue(all(item["code"] != "60701190" for item in links.values()))

    def test_compact_transport_keeps_null_zero_and_original_column_order(self):
        import pandas as pd
        frame = pd.DataFrame({"code": ["001", "001"], "missing": [None, None],
                              "value": [0.0, 2.5], "period": ["202503", "202606"]})
        packet = frame_packet(frame)
        self.assertEqual(packet["constants"], {"code": "001", "missing": None})
        pd.testing.assert_frame_equal(frame, _frame(packet))
        self.assertEqual(serialize_cell(Cell(0))["value"], 0)
        self.assertEqual(serialize_cell(Cell("N/D"))["value"], None)

    def test_engine_manifest_hashes_the_original_modules_without_edits(self):
        import hashlib
        import tempfile
        with tempfile.TemporaryDirectory() as output:
            manifest = publish_engine(ROOT, Path(output))
            for module in manifest["modules"]:
                exported = Path(output, "statements/engine", module["path"]).read_bytes()
                self.assertEqual(hashlib.sha256(exported).hexdigest(), module["sha256"])
                if module["path"].startswith("utils/"):
                    self.assertEqual(exported, (ROOT / module["path"]).read_bytes())

    def test_gzip_transport_is_deterministic_and_preserves_every_cell(self):
        import gzip
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            ident = "individual-60701190"
            path = f"data/statements/{ident}.json"
            input_path = f"data/statements/inputs/{ident}.json"
            value = {"value": 0, "missing": None, "formula": '=IF(COUNT(A1)>0,A1,"N/D")',
                     "inputPath": input_path, "style": "ratio", "format": "0.00%"}
            inputs = {"id": ident, "source": {"sha256": "exact-source"}, "data": [0, None, 2.5]}
            dump(output / path.removeprefix("data/"), value)
            dump(output / input_path.removeprefix("data/"), inputs)
            dump(output / "statements/index.json", {"institutions": [{"id": ident,
                "scope": "individual", "code": "60701190", "path": path, "inputPath": input_path}]})
            index = compress_publication(output)
            snapshot = output / (path + ".gz").removeprefix("data/")
            encoded = snapshot.read_bytes()
            self.assertEqual(encoded[4:8], b"\0\0\0\0")
            expected = {**value, "inputPath": input_path + ".gz"}
            self.assertEqual(json.loads(gzip.decompress(encoded)), expected)
            second = output / "second.json.gz"
            dump(second, expected)
            self.assertEqual(encoded, second.read_bytes())
            self.assertEqual(index["institutions"][0]["path"], path + ".gz")
            self.assertFalse((output / path.removeprefix("data/")).exists())
            self.assertEqual(json.loads(gzip.decompress((output / (input_path + ".gz").removeprefix("data/")).read_bytes())), inputs)


if __name__ == "__main__":
    unittest.main()
