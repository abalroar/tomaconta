import json
from types import SimpleNamespace

import pandas as pd
import pytest

from utils.ifdata_cache import institution_registry as registry
from utils.ifdata_cache.base import BaseCache, CacheConfig, CacheResult
from utils.ifdata_cache.manager import CacheManager
from utils.ifdata_cache.release_ops import validate_cache_quality


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "_root", lambda base_dir=None: tmp_path)
    monkeypatch.delenv("TOMACONTA_IFDATA_SOURCE", raising=False)
    monkeypatch.delenv("TOMACONTA_IFDATA_REGISTRY_DIR", raising=False)
    def offline_web(periodo):
        raise ValueError("fonte indisponível no teste")
    monkeypatch.setattr(registry, "_web_registry", offline_web)


def _names():
    return pd.DataFrame({
        "CodInst": ["C0080099", "00080099"],
        "NomeInstituicao": ["ITAU - PRUDENCIAL", "Instituição individual distinta"],
    })


def test_registry_joins_exact_codes_without_mixing_perimeters():
    source = pd.DataFrame({"CodInst": ["00080099", "C0080099"], "Valor": [10., 20.]})
    before = source.copy(deep=True)
    result = registry.attach_institution_names(source, _names(), "202512")
    assert result["Instituição"].tolist() == ["Instituição individual distinta", "ITAU - PRUDENCIAL"]
    pd.testing.assert_frame_equal(source, before)
    assert result["Valor"].tolist() == [10., 20.]


def test_registry_rejects_conflicting_names_for_same_code():
    names = pd.concat([_names(), pd.DataFrame({"CodInst": ["C0080099"], "NomeInstituicao": ["Outro"]})])
    with pytest.raises(ValueError, match="conflitantes.*C0080099"):
        registry.registry_name_map(names)


@pytest.mark.parametrize("name", ["BS2", "N26", "C6 BANK", "321 SOCIEDADE DE CRÉDITO DIRETO S.A."])
def test_official_names_with_digits_are_not_mistaken_for_ids(name):
    assert not registry.unresolved_name(name)


@pytest.mark.parametrize("name,valid", [("BS2", True), ("[IF C0080099]", False), (None, False)])
def test_name_validation_supports_single_category_and_missing_names(name, valid):
    frame = pd.DataFrame({"Instituição": pd.Categorical([name])})
    assert registry.validate_institution_names(frame)[0] is valid


def test_failed_api_recovers_same_period_validated_registry(tmp_path):
    path = registry.save_registry(_names(), "202512", source="official")
    original_bytes = path.read_bytes()
    recovered = registry.extract_registry("202512", lambda *args, **kwargs: None)
    assert recovered["NomeInstituicao"].tolist() == _names()["NomeInstituicao"].tolist()[::-1]
    assert path.read_bytes() == original_bytes
    assert str(path) == recovered.attrs["institution_registry_source"]


def test_corrupt_runtime_registry_recovers_bundled_copy(tmp_path):
    runtime = registry.save_registry(_names(), "202512", source="official")
    bundled = tmp_path / "data/bundled/institution_registry/202512.json"
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(runtime.read_bytes())
    runtime.write_text('{"periodo":"202512","records":[]}')
    recovered = registry.load_persisted_registry("202512")
    assert len(recovered) == 2
    assert recovered.attrs["institution_registry_source"] == str(bundled)


def test_registry_does_not_reuse_another_period():
    registry.save_registry(_names(), "202512", source="official")
    assert registry.load_persisted_registry("202509").empty


def test_partial_pagination_never_becomes_valid_registry():
    rows = [{"CodInst": f"{i:08}", "NomeInstituicao": f"Banco {i}", "Data": "202412"} for i in range(5000)]
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        return {"value": rows} if len(calls) == 1 else None
    with pytest.raises(ValueError, match="incompleto.*página 2"):
        registry.extract_registry("202412", fetch)
    assert len(calls) == 2
    assert registry.load_persisted_registry("202412").empty


def test_repeated_api_page_aborts_without_infinite_pagination():
    rows = [{"CodInst": f"{i:08}", "NomeInstituicao": f"Banco {i}"} for i in range(5000)]
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        return {"value": rows}
    with pytest.raises(ValueError, match="página repetida"):
        registry.extract_registry("202412", fetch)
    assert len(calls) == 2
    assert registry.load_persisted_registry("202412").empty


def test_code_only_registry_does_not_overwrite_good_copy():
    path = registry.save_registry(_names(), "202512", source="official")
    content = path.read_bytes()
    bad = {"value": [{"CodInst": "C0080099", "NomeInstituicao": "[IF C0080099]"}]}
    out = registry.extract_registry("202512", lambda *a, **k: bad)
    assert len(out) == 2
    assert path.read_bytes() == content


def test_uncovered_code_aborts_instead_of_inventing_name():
    with pytest.raises(ValueError, match="não cobre.*C0009999"):
        registry.attach_institution_names(pd.DataFrame({"CodInst": ["C0009999"]}), _names(), "202512")


def test_official_web_covers_code_missing_from_olinda_and_survives_next_refresh(monkeypatch):
    supplemental = pd.DataFrame({"CodInst": ["C0084930"], "NomeInstituicao": ["LISTO SCD - PRUDENCIAL"]})
    monkeypatch.setattr(registry, "_web_registry", lambda _: supplemental)
    result = registry.attach_institution_names(pd.DataFrame({"CodInst": ["C0084930"]}), _names(), "202512")
    assert result["Instituição"].item() == "LISTO SCD - PRUDENCIAL"
    refreshed = registry.extract_registry("202512", lambda *a, **k: {"value": _names().to_dict("records")})
    assert "C0084930" in refreshed["CodInst"].tolist()


@pytest.mark.parametrize("name", sorted(registry.INSTITUTION_NAMED_CACHE_NAMES))
def test_all_ifdata_cache_writes_preserve_previous_data_when_names_disappear(tmp_path, name):
    class TestCache(BaseCache):
        def baixar_remoto(self):
            raise NotImplementedError
        def extrair_periodo(self, *args, **kwargs):
            raise NotImplementedError
    cache = TestCache(CacheConfig(nome=name, descricao=name, subdir=name,
                                 colunas_obrigatorias=["Instituição", "Período"]), tmp_path)
    valid = pd.DataFrame({"Instituição": ["ITAU - PRUDENCIAL"], "Período": ["4/2025"],
                          "CodInst": ["C0080099"], "Valor": [123.]})
    assert cache.salvar_local(valid, "api").sucesso
    data_before, meta_before = cache.arquivo_dados.read_bytes(), cache.arquivo_metadata.read_bytes()
    invalid = valid.assign(Instituição="[IF C0080099]")
    result = cache.salvar_local(invalid, "api")
    assert not result.sucesso
    assert "não resolvido" in result.mensagem
    assert cache.arquivo_dados.read_bytes() == data_before
    assert cache.arquivo_metadata.read_bytes() == meta_before


@pytest.mark.parametrize("save_interval", [1, 4])
def test_manager_reports_failed_save_and_preserves_cache(tmp_path, monkeypatch, save_interval):
    monkeypatch.setattr("utils.ifdata_cache.manager.time.sleep", lambda _: None)
    manager = CacheManager(tmp_path)
    cache = manager.get_cache("passivo")
    frame = pd.DataFrame({"Instituição": ["ITAU - PRUDENCIAL"], "Período": ["4/2025"],
                          "CodInst": ["C0080099"], "Valor": [123.]})
    assert cache.salvar_local(frame, "api").sucesso
    original = cache.arquivo_dados.read_bytes()
    monkeypatch.setattr(cache, "extrair_periodo", lambda *a, **k: CacheResult(
        sucesso=True, mensagem="API", dados=frame.assign(Instituição="C0080099"),
    ))
    saved_messages = []
    result = manager.extrair_periodos_com_salvamento("passivo", ["202512"],
                                                  intervalo_salvamento=save_interval,
                                                  callback_salvamento=saved_messages.append)
    assert not result.sucesso
    assert cache.arquivo_dados.read_bytes() == original
    assert saved_messages == []


def test_remote_refresh_cannot_return_id_only_frame_as_success(tmp_path, monkeypatch):
    cache = CacheManager(tmp_path).get_cache("passivo")
    frame = pd.DataFrame({"Instituição": ["ITAU - PRUDENCIAL"], "Período": ["4/2025"],
                          "CodInst": ["C0080099"], "Valor": [123.]})
    assert cache.salvar_local(frame, "api").sucesso
    monkeypatch.setattr(cache, "baixar_remoto", lambda: CacheResult(
        sucesso=True, mensagem="remoto", dados=frame.assign(Instituição="[IF C0080099]"),
    ))
    result = cache.carregar(forcar_remoto=True)
    assert result.sucesso
    assert result.dados["Instituição"].item() == "ITAU - PRUDENCIAL"


def test_publication_gate_rejects_code_only_passivo():
    frame = pd.DataFrame({"Instituição": ["C0080099"], "Período": ["4/2025"], "CodInst": ["C0080099"]})
    manager = SimpleNamespace(get_cache=lambda _: SimpleNamespace(carregar_local=lambda: CacheResult(
        sucesso=True, mensagem="ok", dados=frame,
    )))
    result = validate_cache_quality(manager, ["passivo"])
    assert not result["passivo"]["success"]


def test_app_download_fallback_rejects_id_only_frame(monkeypatch):
    import io
    import app1
    content = io.BytesIO()
    pd.DataFrame({"Instituição": ["C0080099"], "Período": ["4/2025"]}).to_parquet(content)
    monkeypatch.setattr(app1.requests, "get", lambda *a, **k: SimpleNamespace(
        status_code=200, content=content.getvalue(),
    ))
    result = app1._baixar_cache_release_base_cache("passivo", "https://example.test/release")
    assert not result.sucesso
    assert result.dados is None


def test_app_fallback_does_not_report_failed_save_as_success():
    import app1
    failure = CacheResult(sucesso=False, mensagem="cache preservado")
    cache = SimpleNamespace(salvar_local=lambda *a, **k: failure)
    manager = SimpleNamespace(get_cache=lambda _: cache)
    source = CacheResult(sucesso=True, mensagem="download", dados=_names())
    assert app1._salvar_cache_fallback_local(manager, "passivo", source) is failure


@pytest.mark.parametrize("name", sorted(registry.IFDATA_CACHE_NAMES))
def test_every_report_recovers_names_when_olinda_cadastro_fails(tmp_path, monkeypatch, name):
    from utils.ifdata_cache import extractor
    registry.save_registry(_names(), "202512", source="official")
    monkeypatch.setattr(extractor, "_fetch_json", lambda *a, **k: None)
    def values(*args, **kwargs):
        return pd.DataFrame([
            {"CodInst": "C0080099", "NomeColuna": column, "Saldo": value}
            for column, value in [
                ("Ativo Total", 123.),
                ("Capital Principal para Comparação com RWA (a)", 10.),
                ("Ativos Ponderados pelo Risco (RWA) (i) = (f) + (g) + (h)", 100.),
            ]
        ])
    monkeypatch.setattr(extractor, "extrair_valores", values)
    result = CacheManager(tmp_path).get_cache(name).extrair_periodo("202512")
    assert result.sucesso, result.mensagem
    assert result.dados["Instituição"].item() == "ITAU - PRUDENCIAL"
    assert result.dados["CodInst"].item() == "C0080099"


def test_legacy_and_unified_extractors_preserve_digit_names(monkeypatch):
    from utils import ifdata_extractor as legacy
    from utils.ifdata_cache import unified_extractor as unified
    names = pd.DataFrame({"CodInst": ["00000042"], "NomeInstituicao": ["BS2"]})
    values = pd.DataFrame({"CodInst": ["00000042"], "NomeColuna": ["Ativo Total"], "Saldo": [123.]})
    for module in (legacy, unified):
        monkeypatch.setattr(module, "extrair_cadastro", lambda _: names.copy())
        monkeypatch.setattr(module, "extrair_valores", lambda *a: values.copy())
    monkeypatch.setattr(legacy, "extrair_lucro_periodo", lambda _: pd.DataFrame(
        columns=["CodInst", "Lucro Líquido Acumulado YTD"],
    ))
    assert legacy.processar_periodo("202512", {})["Instituição"].item() == "BS2"
    result = unified.processar_periodo("202512", 1)
    assert result.sucesso, result.mensagem
    assert result.dados["NomeInstituicao"].item() == "BS2"


def test_identity_repair_preserves_values_other_periods_and_is_idempotent(tmp_path):
    from tools.audit_ifdata_identity import repair
    path = tmp_path / "data/bundled/passivo/dados.parquet"
    path.parent.mkdir(parents=True)
    frame = pd.DataFrame({
        "CodInst": ["C0080099", "C0080099"], "Período": ["3/2025", "4/2025"],
        "Instituição": ["ITAU - PRUDENCIAL", "[IF C0080099]"], "Valor": [10., float("nan")],
    })
    frame.to_parquet(path, index=False)
    path.with_name("metadata.json").write_text('{"publication_id":"release-v1"}')
    official = registry.save_registry(_names(), "202512", source="official")
    proof = repair(tmp_path, official)
    corrected = pd.read_parquet(path)
    pd.testing.assert_frame_equal(corrected.drop(columns="Instituição"), frame.drop(columns="Instituição"))
    assert corrected["Instituição"].tolist() == ["ITAU - PRUDENCIAL"] * 2
    assert path.with_name("metadata.json").exists()
    assert len(proof) == 1
    assert (tmp_path / "data/cache_versions").exists()
    content = path.read_bytes()
    assert repair(tmp_path, official) == []
    assert content == path.read_bytes()


def test_identity_repair_rejects_tampered_registry_before_changing_data(tmp_path):
    from tools.audit_ifdata_identity import repair
    official = registry.save_registry(_names(), "202512", source="official")
    payload = json.loads(official.read_text())
    payload["records"][0]["NomeInstituicao"] = "Outra instituição"
    official.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="Checksum"):
        repair(tmp_path, official)


def test_identity_repair_uses_each_period_and_preserves_categorical_derived_values(tmp_path):
    from tools.audit_ifdata_identity import repair
    old = pd.DataFrame({"CodInst": ["C0080099"], "NomeInstituicao": ["Nome de setembro"]})
    registry.save_registry(old, "202509", source="official")
    official = registry.save_registry(_names(), "202512", source="official")
    path = tmp_path / "data/cache/derived_metrics_individual/dados.parquet"
    path.parent.mkdir(parents=True)
    frame = pd.DataFrame({"Instituição": pd.Categorical(["[IF C0080099]"] * 2),
                          "Período": ["3/2025", "4/2025"], "Valor": [1., 2.]})
    frame.to_parquet(path, index=False)
    proof = repair(tmp_path, official.parent)
    corrected = pd.read_parquet(path)
    assert corrected["Instituição"].tolist() == ["Nome de setembro", "ITAU - PRUDENCIAL"]
    assert isinstance(corrected["Instituição"].dtype, pd.CategoricalDtype)
    pd.testing.assert_frame_equal(corrected.drop(columns="Instituição"), frame.drop(columns="Instituição"))
    assert "CodInst" not in corrected
    assert proof[0]["periodos"] == ["202509", "202512"]


def test_identity_repair_checks_all_periods_before_first_mutation(tmp_path):
    from tools.audit_ifdata_identity import repair
    paths = []
    for name, period in (("ativo", "4/2025"), ("passivo", "3/2025")):
        path = tmp_path / f"data/cache/{name}/dados.parquet"
        path.parent.mkdir(parents=True)
        pd.DataFrame({"CodInst": ["C0080099"], "Período": [period],
                      "Instituição": ["[IF C0080099]"]}).to_parquet(path, index=False)
        paths.append((path, path.read_bytes()))
    official = registry.save_registry(_names(), "202512", source="official")
    with pytest.raises(ValueError, match="não cobre os períodos"):
        repair(tmp_path, official)
    assert all(path.read_bytes() == content for path, content in paths)
