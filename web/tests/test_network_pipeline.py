"""Network adapter tests; install web/tools/requirements-network.txt first.

No network, Parquet, ignored cache or previous QA artifacts are required.
"""
import json
import gzip
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import export_network as network


class NetworkPipeline(unittest.TestCase):
    def test_packaged_geography_reproduces_official_bytes_without_network(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(network.requests, "get", side_effect=AssertionError("IBGE must not be queried during BCB refresh")):
            for name in ("localities.json", "municipalities.geojson", "ufs.geojson"):
                metadata = json.loads((network.GEOGRAPHY_BASELINE / (name + ".source.json")).read_text())
                path = Path(directory) / name
                value, provenance = network.geography_json(metadata["url"], path)
                self.assertTrue(value)
                self.assertEqual(provenance, metadata)
                self.assertEqual(path.stat().st_size, metadata["bytes"])
                self.assertEqual(network.sha(path.read_bytes()), metadata["sha256"])
                self.assertEqual(network.geography_json(metadata["url"], path), (value, provenance))

    def test_corrupt_geography_does_not_query_network_or_repair_silently(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(network.requests, "get") as fetch:
            baseline = Path(directory) / "baseline"
            baseline.mkdir()
            (baseline / "localities.json.gz").write_bytes(gzip.compress(b"[]", mtime=0))
            (baseline / "localities.json.source.json").write_text(json.dumps({"url": network.LOCALITIES_URL, "sha256": "a" * 64, "bytes": 2}))
            path = Path(directory) / "cache/localities.json"
            with self.assertRaisesRegex(ValueError, "inconsistente"):
                network.geography_json(network.LOCALITIES_URL, path, baseline=baseline)
            self.assertFalse(path.exists())
            fetch.assert_not_called()

    def test_explicit_geography_refresh_failure_keeps_original_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "localities.json"
            url = json.loads((network.GEOGRAPHY_BASELINE / "localities.json.source.json").read_text())["url"]
            network.geography_json(url, path)
            old = path.read_bytes()
            receipt = path.with_suffix(".json.source.json").read_bytes()
            with patch.object(network.requests, "get", side_effect=network.requests.ConnectTimeout("IBGE unavailable")):
                with self.assertRaises(network.requests.ConnectTimeout):
                    network.geography_json(url, path, refresh=True)
            self.assertEqual(path.read_bytes(), old)
            self.assertEqual(path.with_suffix(".json.source.json").read_bytes(), receipt)

    def test_membership_date_comes_from_candidate_catalog_not_wall_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "web/public/data/institutions.json"
            catalog.parent.mkdir(parents=True)
            catalog.write_text(json.dumps({"latestPeriod": "2026-Q3"}))
            self.assertEqual(network.membership_period(root), "202609")
            self.assertEqual(network.membership_period(root, "2026-09"), "202609")
            with self.assertRaisesRegex(ValueError, "última competência real"):
                network.membership_period(root, "202606")
            staged = root / "staging/web/data"
            staged.mkdir(parents=True)
            (staged / "institutions.json").write_text(json.dumps({"latestPeriod": "2026-Q4"}))
            self.assertEqual(network.membership_period(root, catalog_dir=staged), "202612")
            catalog.write_text(json.dumps({"latestPeriod": "invalid"}))
            with self.assertRaisesRegex(ValueError, "competência trimestral"):
                network.membership_period(root)

    def test_official_code_exact_prefix_and_ambiguity_preserve_identity(self):
        ids = {"3550308", "3304557"}
        self.assertEqual(network.municipality_code("3550308", ids), ("3550308", "exact-7-digit"))
        self.assertEqual(network.municipality_code("355030", ids), ("3550308", "unique-6-digit-prefix"))
        self.assertEqual(network.municipality_code("355030", ids | {"3550309"}), (None, "unmatched-or-ambiguous"))
        self.assertIsNone(network.municipality_code("3550309", ids)[0])
        self.assertIsNone(network.municipality_code("São Paulo", ids)[0])

    def test_collection_pages_until_final_page_and_reuses_only_verified_cache(self):
        first = [{"CnpjBase": "00000000", "CnpjSequencial": f"{i:04d}", "CnpjDv": "00"} for i in range(1000)]
        last = [{"CnpjBase": "00000000", "CnpjSequencial": "1000", "CnpjDv": "00"}]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            with patch.object(network, "fetch_json", side_effect=[({"value": first}, {"sha256": "a" * 64}), ({"value": last}, {"sha256": "b" * 64})]) as fetch:
                rows, provenance = network.collect_agencies(source)
            self.assertEqual(len(rows), 1001)
            self.assertEqual([page["rows"] for page in provenance["pages"]], [1000, 1])
            queries = [parse_qs(urlsplit(call.args[0]).query) for call in fetch.call_args_list]
            self.assertEqual([query["$skip"] for query in queries], [["0"], ["1000"]])
            self.assertTrue(all(query["$orderby"] == ["CnpjBase,CnpjSequencial,CnpjDv"] for query in queries))
            with patch.object(network, "fetch_json") as fetch:
                self.assertEqual(network.collect_agencies(source)[0], rows)
                fetch.assert_not_called()
            (source / "agencies.json").write_text("[]")
            with self.assertRaisesRegex(ValueError, "inconsistente"):
                network.collect_agencies(source)

    def test_duplicate_cnpj_aborts_before_replacing_publication(self):
        row = {"CnpjBase": "00000000", "CnpjSequencial": "0001", "CnpjDv": "91"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            published = root / "bank-network.json"
            published.write_text("previous")
            with patch.object(network, "membership_period", return_value="202606"), patch.object(network, "collect_agencies", return_value=([row, row], {})):
                with self.assertRaisesRegex(ValueError, "Duplicidade"):
                    network.export(root, root, root / "cache")
            self.assertEqual(published.read_text(), "previous")

    def test_positive_missing_geometry_aborts_before_replacing_publication(self):
        row = {"CnpjBase": "00000000", "CnpjSequencial": "0001", "CnpjDv": "91", "NomeIf": "Banco fonte",
               "Segmento": "Banco Múltiplo", "MunicipioIbge": "3550308", "Municipio": "SAO PAULO", "UF": "SP", "Posicao": "05/11/2026"}
        locality = {"id": 3550308, "nome": "São Paulo", "microrregiao": {"mesorregiao": {"UF": {"id": 35, "sigla": "SP", "nome": "São Paulo"}}}}
        # Self-intersecting polygon: no point is invented for a positive record.
        invalid = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"codarea": "3550308"},
                    "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            published = root / "bank-network.json"
            published.write_text("previous")
            with patch.object(network, "membership_period", return_value="202606"), patch.object(network, "collect_agencies", return_value=([row], {})) as agencies, patch.object(network, "geography_json", side_effect=[([locality], {}), (invalid, {}), ({}, {})]) as geography, patch.object(network, "official_links") as links:
                with self.assertRaisesRegex(ValueError, "sem município/ponto oficial"):
                    network.export(root, root, root / "cache", refresh=True)
                self.assertTrue(agencies.call_args.kwargs["refresh"])
                self.assertEqual([call.kwargs["refresh"] for call in geography.call_args_list], [False, False, False])
                links.assert_not_called()
            self.assertEqual(published.read_text(), "previous")

    def test_membership_uses_cnpj_and_group_code_only_and_does_not_choose_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "web/public/data"
            (output / "statements").mkdir(parents=True)
            (output / "institutions.json").write_text(json.dumps({"institutions": [
                {"id": "a", "name": "Grupo A", "perimeter": "Prudencial"}, {"id": "b", "name": "Alias B", "perimeter": "Prudencial"}, {"id": "c", "name": "Alias C", "perimeter": "Prudencial"}]}))
            def link(code):
                return {"statementId": "prudential-" + code, "scope": "prudential", "code": code, "effectivePeriod": "202606"}
            (output / "statements/crosswalk.json").write_text(json.dumps({"links": {"a": link("C0080099"), "b": link("C0080329"), "c": link("C0080329")}}))
            reports = [{"dt": "202606", "files": [{"f": "cadastro202606_1006.json"}, {"f": "info202606.json"}]}]
            individuals = [{"c33": "60701190", "c15": "C0080099", "c1": "202606", "c2": "mesmo nome"},
                           {"c33": "00000000", "c15": "C0080329", "c1": "202606", "c2": "mesmo nome"}]
            info = [{"td": 1, "lid": 15, "d": "Código do Conglomerado Prudencial"}]
            metadata = {"sha256": "e" * 64}
            with patch.object(network, "fetch_json", side_effect=[(reports, metadata), (individuals, metadata), (info, metadata)]):
                links, statuses, _ = network.official_links(root, root, "202606", ["60701190", "00000000", "12345678"])
            self.assertEqual(set(links), {"60701190"})
            self.assertEqual(links["60701190"]["analysisId"], "a")
            self.assertEqual(statuses, {"00000000": "ambiguous-crosswalk", "12345678": "individual-not-found", "60701190": "linked"})


if __name__ == "__main__":
    unittest.main()
