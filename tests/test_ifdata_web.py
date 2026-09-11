import json

import pytest

from utils.ifdata_cache.ifdata_web import IFDataWeb


def source_files(tmp_path):
    root = tmp_path / "202606"
    root.mkdir()
    info = [
        {"id": 1, "n": "Ativo Total", "d": "[1]+[2]", "td": 3, "ty": 1, "a": 1, "lid": 140220},
        {"id": 2, "n": "Índice de Basileia", "d": "PR/RWA", "td": 3, "ty": 1, "a": 1, "lid": 79664},
        {"id": 3, "n": "Conglomerado Prudencial", "d": "nome", "td": 1, "ty": 1, "a": 1, "lid": 22},
    ]
    def entity(key, code, name, marker="1"):
        return {"c0": str(key), "c1": "202606", "c2": name, "c33": code, "c34": marker,
                "c22": "CONGLOMERADO"}
    payloads = {
        "info202606.json": info,
        "cadastro202606_1009.json": [entity(1000080075, "00080075", "GRUPO", "4"),
                                     entity(7, "00000007", "BANCO")],
        "cadastro202606_1006.json": [entity(7, "00000007", "BANCO")],
        "dados202606_1.json": {"id": 1, "values": [
            {"e": 1000080075, "v": [{"i": 140220, "v": 1234567890123.45}, {"i": 79664, "v": 0.175}]},
            {"e": 7, "v": [{"i": 140220, "v": 0}]},
        ]},
    }
    catalog = {"dt": 202606, "files": [{"f": f"202606/{name}"} for name in payloads]}
    for selector in (1009, 1006):
        catalog["files"].append({"f": f"202606/report_{selector}.json", "trel": {
            "id": selector, "n": "Resumo", "s": [{"id": selector}], "fx": "",
            "c": [{"ifd": 1, "sc": []}, {"ifd": 2, "sc": []}, {"ifd": 3, "sc": []}],
        }})
    payloads["relatorios2025a2030.json"] = [catalog]
    for name, payload in payloads.items():
        (root / name).write_text(json.dumps(payload))
    return root


def test_public_web_preserves_identity_units_zero_missing_and_perimeter(tmp_path, monkeypatch):
    root = source_files(tmp_path)
    monkeypatch.setattr("utils.ifdata_cache.ifdata_web.requests.get",
                        lambda *a, **k: pytest.fail("Fonte local auditada não deve baixar novamente"))
    source = IFDataWeb("202606", tmp_path)
    data = source.valores(1, 1)
    assert set(data.CodInst) == {"C0080075", "00000007"}
    assert data.loc[data.Conta.eq("140220"), "Saldo"].tolist() == [1234567890123.45, 0]
    assert data.loc[data.Conta.eq("79664"), "Saldo"].tolist() == [0.175]
    assert len(source.valores(1, 3)) == 1
    assert len(source.cadastro_frame()) == 2
    audit = json.loads((root / "sources.json").read_text())
    assert audit["source"] == "ifdata_web"
    assert all(len(item["sha256"]) == 64 for item in audit["files"].values())


def test_web_rejects_duplicate_cells(tmp_path):
    root = source_files(tmp_path)
    path = root / "dados202606_1.json"
    data = json.loads(path.read_text())
    data["values"][0]["v"].append(data["values"][0]["v"][0])
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="duplicada"):
        IFDataWeb("202606", tmp_path).valores(1, 1)


def test_web_rejects_missing_area_and_unknown_report_filters(tmp_path):
    root = source_files(tmp_path)
    path = root / "relatorios2025a2030.json"
    data = json.loads(path.read_text())
    data[0]["files"] = [f for f in data[0]["files"] if "dados" not in f["f"]]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="obrigatório"):
        IFDataWeb("202606", tmp_path).valores(1, 1)
    next(f["trel"] for f in data[0]["files"] if f.get("trel"))["fx"] = "return 1;"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="filtro"):
        IFDataWeb("202606", tmp_path).valores(1, 1)


def test_web_backend_requires_supported_period():
    with pytest.raises(ValueError, match="trimestres"):
        IFDataWeb("202607", None)


def test_extractor_web_backend_is_explicit(tmp_path, monkeypatch):
    source_files(tmp_path)
    from utils.ifdata_cache import extractor
    from utils.ifdata_cache.ifdata_web import get_web_source
    monkeypatch.setenv("TOMACONTA_IFDATA_SOURCE", "web")
    monkeypatch.setenv("TOMACONTA_IFDATA_WEB_DIR", str(tmp_path))
    get_web_source.cache_clear()
    monkeypatch.setattr(extractor, "_fetch_json", lambda *a, **k: pytest.fail("Olinda não deve ser chamada"))
    assert len(extractor.extrair_cadastro("202606")) == 2
    assert len(extractor.extrair_valores("202606", 1, 3)) == 1
    get_web_source.cache_clear()
