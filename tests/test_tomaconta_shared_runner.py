"""Shared runner contracts; no live HTTP, credentials, collectors or publication."""
import base64
import gzip
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.error import HTTPError

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("shared_runner", ROOT / "scripts/tomaconta_shared_runner.py")
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def source(tmp_path):
    root = tmp_path / "source"
    for folder in ("utils", "tabs", "data/bundled/demo", "web/public/data"):
        (root / folder).mkdir(parents=True)
    (root / "data/bundled/demo/dados.parquet").write_bytes(b"original source")
    (root / "web/public/data/example.json").write_text('{"value":0}')
    return root


def claim(kind="mercado_imobiliario", base=None):
    return {"job": {"id": "a" * 32, "lease_id": "b" * 32, "base_revision": None if base is None else "c" * 32,
                    "kind": kind, "params": {"kind": kind, "mode": "incremental"}}, "base": base}


class API:
    denied = False
    def __init__(self, *, publish_error=False, blobs=None):
        self.calls, self.blobs, self.publish_error = [], blobs or {}, publish_error
    def request(self, method, path, data=None, **kwargs):
        self.calls.append((method, path, data, kwargs))
        if method == "GET":
            return self.blobs[path.rsplit("/", 1)[-1]]
        return {"stored": True}
    def action(self, job, action, **values):
        self.calls.append(("POST", action, values, {}))
        if action == "prepare":
            return {"revision": "d" * 32}
        if action == "publish":
            if self.publish_error:
                raise r.RunnerError("CAS mudou; revisão anterior preservada")
            return {"revision": "d" * 32, "published": True}
        return {"ok": True}


def process(root, plan, progress):
    (root / "web/public/data/example.json").write_text('{"value":12}')
    return {"coverage": {"charts": 1}, "changed": [plan["kind"]]}


def test_executes_only_validated_generation_then_prepare_and_publish(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "f" * 40)
    api = API()
    result = r.execute_claim(api, claim(), processor=process, source_root=source(tmp_path), heartbeat_interval=100)
    assert result["status"] == "published"
    actions = [c[1] for c in api.calls]
    assert actions[-2:] == ["prepare", "publish"]
    prepared = api.calls[-2][2]
    assert prepared["parent"] is None
    assert prepared["summary"]["validation"] == {"complete": True, "failures": 0}
    assert prepared["summary"]["generation"]["sourceCommit"] == "f" * 40
    assert prepared["summary"]["generation"]["sourceFiles"][0]["path"] == "cache/bundled/demo/dados.parquet"
    assert all(c[0] != "PUT" or c[2] for c in api.calls)


def test_needs_review_does_not_upload_prepare_or_publish(tmp_path):
    api = API()
    def review(*_):
        raise r.NeedsReview({"pending_review": [{"account": "123"}]})
    with pytest.raises(r.NeedsReview):
        r.execute_claim(api, claim(), processor=review, source_root=source(tmp_path), heartbeat_interval=100)
    assert [c[1] for c in api.calls] == ["fail"]
    assert api.calls[0][2]["needsReview"] is True


def test_collection_failure_never_promotes(tmp_path):
    api = API()
    def failure(*_):
        raise r.RunnerError("Coleta incompleta")
    with pytest.raises(r.RunnerError, match="incompleta"):
        r.execute_claim(api, claim(), processor=failure, source_root=source(tmp_path), heartbeat_interval=100)
    assert [c[1] for c in api.calls] == ["fail"]


def test_cas_conflict_is_reported_without_republication(tmp_path):
    api = API(publish_error=True)
    with pytest.raises(r.RunnerError, match="CAS"):
        r.execute_claim(api, claim(), processor=process, source_root=source(tmp_path), heartbeat_interval=100)
    assert [c[1] for c in api.calls if c[1] in {"publish", "fail"}] == ["publish", "fail"]


def test_active_manifest_is_exclusive_and_hash_verified(tmp_path):
    src = source(tmp_path)
    target = tmp_path / "candidate"; target.mkdir()
    content = b'{"generation":"active"}'
    sha = r.hashlib.sha256(content).hexdigest()
    base = {"files": [{"path": "web/data/active.json", "size": len(content), "sha256": sha, "encoding": "identity"}]}
    class Progress:
        def check(self): pass
    r.seed_workspace(target, base, API(blobs={sha: content}), Progress(), src)
    assert not (target / "web/public/data/example.json").exists(), "unlisted stale checkout content must not leak"
    assert (target / "web/public/data/active.json").read_bytes() == content
    bad = tmp_path / "bad"; bad.mkdir()
    with pytest.raises(r.RunnerError, match="Hash"):
        r.seed_workspace(bad, base, API(blobs={sha: b"wrong"}), Progress(), src)


def test_identical_checkout_blob_can_be_reused_but_never_overrides_manifest(tmp_path):
    src = source(tmp_path); target = tmp_path / "candidate"; target.mkdir()
    original = src / "web/public/data/example.json"
    item = {"path": "web/data/example.json", "size": original.stat().st_size, "sha256": r.digest(original)}
    class Progress:
        def check(self): pass
    api = API()
    r.seed_workspace(target, {"files": [item]}, api, Progress(), src)
    assert api.calls == []
    assert r.digest(target / "web/public/data/example.json") == item["sha256"]


@pytest.mark.parametrize("path", ["../secret", "/web/data/x.json", "web/data/../../x", "web/data//x", "cache/source/x", "web/data/./x"])
def test_rejects_path_escape(tmp_path, path):
    with pytest.raises(r.RunnerError):
        r.logical_path(tmp_path, path)


def test_gzip_transport_retains_compressed_identity(tmp_path):
    src = source(tmp_path)
    path = src / "web/public/data/data.json.gz"
    path.write_bytes(gzip.compress(b'{"value":0}', mtime=0))
    files, paths = r.inventory(src)
    item = next(f for f in files if f["path"].endswith("data.json.gz"))
    assert item["encoding"] == "identity"
    assert item["sha256"] == r.digest(path)
    assert gzip.decompress(paths[item["path"]].read_bytes()) == b'{"value":0}'


def test_plan_limits_and_no_arbitrary_commands():
    assert r.validate_plan({"kind": "mercado_imobiliario", "start": "2025-01", "end": "2026-12"})["end"] == "2026-12"
    for plan in ({"kind": "mercado_imobiliario", "start": "2024-12", "end": "2026-12"},
                 {"kind": "individual", "period": "2026-08"}, {"kind": "individual", "command": "echo x"},
                 {"kind": "mercado_credito_sgs", "start": "2026-01"}):
        with pytest.raises(r.RunnerError): r.validate_plan(plan)


def test_original_cache_incomplete_receipts_are_rejected():
    class Result:
        sucesso = True
        mensagem = "Parcial"
        metadata = {"finalized": False}
    with pytest.raises(r.RunnerError): r.checked_result(Result())
    Result.metadata = {"falhas": ["BCB timeout"]}
    with pytest.raises(r.RunnerError): r.checked_result(Result())


def test_context_restricts_repository_workflow_main_and_events():
    env = {"GITHUB_REPOSITORY_ID": "1141557164", "GITHUB_REPOSITORY_OWNER_ID": "255978345", "GITHUB_REF": "refs/heads/main",
           "GITHUB_WORKFLOW_REF": r.WORKFLOW, "GITHUB_EVENT_NAME": "schedule", "GITHUB_SHA": "a" * 40}
    r.check_github_context(env)
    for key, value in (("GITHUB_REF", "refs/pull/1/merge"), ("GITHUB_EVENT_NAME", "pull_request"),
                       ("GITHUB_REPOSITORY_ID", "9"), ("GITHUB_REPOSITORY_OWNER_ID", "8"), ("GITHUB_WORKFLOW_REF", "other")):
        with pytest.raises(r.RunnerError): r.check_github_context({**env, key: value})


def test_oidc_is_cached_renewed_and_requested_for_exact_audience():
    now = [1000]
    calls = []
    def opener(request, **_):
        calls.append(request)
        payload = base64.urlsafe_b64encode(json.dumps({"exp": now[0] + 600}).encode()).rstrip(b"=").decode()
        return io.BytesIO(json.dumps({"value": "header." + payload + ".signature"}).encode())
    identity = r.OidcIdentity(env={"ACTIONS_ID_TOKEN_REQUEST_URL": "https://run.actions.githubusercontent.com/id?x=1",
                                   "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "oidc-request-only"}, opener=opener, clock=lambda: now[0])
    first = identity.bearer(); assert identity.bearer() == first; assert len(calls) == 1
    now[0] = 1550
    assert identity.bearer() != first; assert len(calls) == 2
    assert "audience=https%3A%2F%2Fmatheusprat.es%2Ftomaconta%2Fapi%2Fshared%2Frunner" in calls[0].full_url


def test_access_denial_stops_http_and_never_leaks_identity():
    class Identity:
        def bearer(self): return "TOP-SECRET-JWT"
    calls = []
    def opener(request, **_):
        calls.append(request)
        raise HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(b"private diagnostic"))
    api = r.SharedAPI(identity=Identity(), opener=opener)
    with pytest.raises(r.RunnerError) as error: api.request("GET", "/runner/pending")
    assert "TOP-SECRET" not in str(error.value) and "private" not in str(error.value)
    with pytest.raises(r.RunnerError): api.request("GET", "/runner/pending")
    assert len(calls) == 1


def test_idle_claim_never_runs_a_collector(monkeypatch, capsys):
    class Idle:
        def request(self, *args, **kwargs): return {"job": None}
        def enable_pool(self): pass
        def close_pool(self): pass
    monkeypatch.setattr(r, "check_github_context", lambda: None)
    monkeypatch.setattr(r, "SharedAPI", Idle)
    monkeypatch.setattr(r, "execute_claim", lambda *_: pytest.fail("idle queue must not collect"))
    assert r.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "idle"


def test_workflow_probes_before_installing_and_claims_after_setup():
    text = (ROOT / ".github/workflows/tomaconta-shared.yml").read_text()
    assert "cron: '*/5 * * * *'" in text
    assert "id-token: write" in text and "contents: read" in text
    assert "contents: write" not in text and "secrets." not in text
    assert "github.event.repository.private == false" in text
    assert "if: needs.pending.outputs.pending == 'true'" in text
    assert text.index("--pending-only") < text.index("pip install") < text.rindex("python scripts/tomaconta_shared_runner.py")


def test_chart_export_uses_explicit_candidate_parquet_and_output(tmp_path):
    import pandas as pd
    root = tmp_path / "candidate"
    out = tmp_path / "output"
    for name in ("mercado_credito_sgs", "mercado_imobiliario"):
        target = root / "data/bundled" / name; target.mkdir(parents=True)
        shutil.copyfile(ROOT / "data/bundled" / name / "dados.parquet", target / "dados.parquet")
    parquet = root / "data/bundled/mercado_imobiliario/dados.parquet"
    sgs_path = root / "data/bundled/mercado_credito_sgs/dados.parquet"
    sgs = pd.read_parquet(sgs_path)
    sgs["valor"] = sgs["valor"] * 2
    sgs.to_parquet(sgs_path, index=False)
    frame = pd.read_parquet(parquet)
    row = frame[(frame.uf == "br") & (frame.grafico == "contratacao_valor_pf") & (frame.linha == "")].iloc[-1]
    index = row.name
    frame.loc[index, "valor"] = float(row.valor) + 1234567
    frame.to_parquet(parquet, index=False)
    subprocess.run([sys.executable, str(ROOT / "web/tools/export_charts.py"), "--root", str(root), "--output", str(out)],
                   check=True, cwd=tmp_path, capture_output=True)
    charts = json.loads((out / "imob-br.json").read_text())
    chart = next(c for c in charts if c["id"] == row.grafico)
    series = next(s for s in chart["series"] if s["category"] == row.categoria)
    point = next(p for p in series["data"] if p[0] == row.data.strftime("%Y-%m-%d"))
    sys.path.insert(0, str(ROOT))
    from utils.mercado_imobiliario import CHARTS
    scale = next(spec.scale for spec in CHARTS if spec.key == row.grafico)
    assert point[1] == frame.loc[index, "valor"] * scale
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["sourceInputs"]["mercado_imobiliario"] == r.digest(parquet)
    assert manifest["sourceInputs"]["mercado_credito_sgs"] == r.digest(sgs_path)
    assert r.digest(parquet) != r.digest(ROOT / "data/bundled/mercado_imobiliario/dados.parquet")
    original_sfn = json.loads((ROOT / "web/public/data/sfn.json").read_text())
    candidate_sfn = json.loads((out / "sfn.json").read_text())
    original_series = original_sfn[0]["series"][0]["data"]
    candidate_series = candidate_sfn[0]["series"][0]["data"]
    for before, after in zip(original_series, candidate_series):
        assert before[0] == after[0]
        assert after[1] == (None if before[1] is None else before[1] * 2)


def test_spb_refresh_forces_official_download_and_uses_candidate_root(tmp_path, monkeypatch):
    import utils.ifdata_cache
    calls = []
    class Result:
        sucesso = True; metadata = {"datasets": {"nucleo_trimestral": 3}}; mensagem = "OK"
    class Cache:
        def materialize_history(self, **kwargs):
            calls.append(kwargs); return Result()
    class Manager:
        def __init__(self, root): assert root == tmp_path
        def get_cache(self, name): assert name == "spb_meios_pagamento"; return Cache()
    class Progress:
        def update(self, *args): pass
    monkeypatch.setattr(utils.ifdata_cache, "CacheManager", Manager)
    monkeypatch.setattr(r, "promote_bundles", lambda manager, names: calls.append(tuple(names)))
    changed, _ = r.refresh_sources(tmp_path, {"kind": "spb_meios_pagamento", "mode": "incremental"}, Progress())
    assert changed == ["spb_meios_pagamento"]
    assert calls[0]["overwrite"] is True
    assert calls[-1] == ("spb_meios_pagamento",)


def test_publish_can_retry_lost_response_but_claim_is_not_retried():
    from urllib.error import URLError
    class Identity:
        def bearer(self): return "identity"
    calls = []
    def publish(request, **_):
        calls.append(request)
        if len(calls) == 1: raise URLError("connection lost")
        return io.BytesIO(b'{"published":true,"revision":"same"}')
    api = r.SharedAPI(identity=Identity(), opener=publish)
    assert api.request("POST", "/runner/jobs/abc/publish", {"revision": "same"})["published"] is True
    assert len(calls) == 2
    calls.clear()
    def unavailable(request, **_):
        calls.append(request); raise URLError("connection lost")
    api = r.SharedAPI(identity=Identity(), opener=unavailable)
    with pytest.raises(r.RunnerError): api.request("POST", "/runner/claim", {})
    assert len(calls) == 1


def test_individual_uses_approved_mappings_preserves_receipts_and_refreshes_ifdata_dependencies(tmp_path, monkeypatch):
    import utils.ifdata_cache.financial_analysis_update as financial
    import utils.ifdata_cache.financial_analysis_review as review
    import utils.ifdata_cache.bloprudencial_cache as mappings
    import utils.ifdata_cache.release_ops as release
    captured = []
    rows = object()
    class Result:
        sucesso = True; dados = rows; mensagem = "OK"
        metadata = {"fontes": [{"url": "https://www.bcb.gov.br/source.zip", "sha256": "d" * 64}]}
    class Cache:
        def extrair_periodo(self, period, **kwargs):
            assert period == "202606" and kwargs["force_refresh"] is True
            return Result()
        def add_period(self, frame): assert frame is rows
        def cosif_decisions(self): return [{"id": "approved"}]
    class Manager:
        def get_cache(self, name): return Cache()
        def extrair_periodos_com_salvamento(self, name, periods, **kwargs):
            captured.append(name);assert periods == ["202606"] and kwargs["modo"] == "overwrite"
            return Result()
    class Progress:
        def update(self, *args): pass
    monkeypatch.setattr(mappings, "row_overrides", lambda decisions: {"existing": "approved-row"})
    def check(cache, period, overrides):
        assert overrides == {"existing": "approved-row"};return []
    monkeypatch.setattr(financial, "individual_review", check)
    def pending(items, approved):
        assert approved == {"approved"};return []
    monkeypatch.setattr(review, "pending_items", pending)
    monkeypatch.setattr(release, "materialize_for_publication", lambda *args, **kwargs: [{"cache": "derived_metrics_individual", "status": "ok"}])
    for key in ("TOMACONTA_IFDATA_SOURCE", "TOMACONTA_IFDATA_WEB_DIR", "TOMACONTA_IFDATA_REGISTRY_DIR"):
        monkeypatch.setenv(key, "test-before")
    names = r.update_individual(tmp_path, Manager(), "202606", Progress())
    assert captured == ["principal_individual", "dre_individual"]
    assert names == ["balancete_individual", "principal_individual", "dre_individual", "derived_metrics_individual"]
    receipt = json.loads((tmp_path / "data/cache/bcb_cosif_4010/202606-receipt.json").read_text())
    assert receipt == Result.metadata


@pytest.mark.parametrize("kind", ["rede_agencias", "tudo"])
def test_registry_refresh_uses_pinned_candidate_catalog_without_fixed_financial_period(tmp_path, monkeypatch, kind):
    output = tmp_path / "web/public/data"; output.mkdir(parents=True)
    calls = []
    monkeypatch.setattr(r, "refresh_sources", lambda *args: ([], {}))
    def generator(name, root, out, *args):
        calls.append((name, root, out, args))
        if name == "export_network.py":
            (out / "bank-network.json").write_text(json.dumps({"position": "2026-11-05", "checks": {"reconciled": True, "selectedRecords": 12818}}))
    monkeypatch.setattr(r, "run_generator", generator)
    monkeypatch.setattr(r, "validate_artifacts", lambda root: {"charts": 104})
    class Progress:
        def update(self, *args): pass
    result = r.materialize_generation(tmp_path, {"kind": kind}, Progress())
    assert [c[0] for c in calls] == ["export_charts.py", "export_network.py"]
    args = calls[-1][3]
    assert args[args.index("--catalog-dir") + 1] == str(output)
    assert "--refresh" in args
    assert "--period" not in args and "--link-period" not in args
    assert result["changed"] == ["rede_agencias"]
    assert result["reports"]["rede_agencias"]["position"] == "2026-11-05"


def test_registry_plan_is_current_position_without_financial_or_historical_parameters():
    assert r.validate_plan({"kind": "rede_agencias"}) == {"kind": "rede_agencias"}
    for extra in ({"start": "2026-01", "end": "2026-02"}, {"period": "2026-06"}, {"uf": "sp"}):
        with pytest.raises(r.RunnerError): r.validate_plan({"kind": "rede_agencias", **extra})


def test_execute_transport_reuses_sessions_without_redirects_or_content_decoding(monkeypatch):
    import requests
    sessions, calls = [], []
    class Response:
        status_code = 200
        raw = io.BytesIO(b'original-gzip-bytes')
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def json(self): return {"pending": True}
    class Session:
        closed = False
        def __init__(self): sessions.append(self)
        def request(self, method, url, **kwargs): calls.append((method, url, kwargs));return Response()
        def close(self): self.closed = True
    class Identity:
        def bearer(self): return "private-identity"
    monkeypatch.setattr(requests, "Session", Session)
    api = r.SharedAPI(identity=Identity())
    api.enable_pool()
    assert api.request("GET", "/runner/pending") == {"pending": True}
    assert api.request("POST", "/runner/claim", {}) == {"pending": True}
    assert len(sessions) == 1
    assert all(call[2]["allow_redirects"] is False for call in calls)
    assert all(call[2]["headers"]["Accept-encoding"] == "identity" for call in calls)
    assert api.request("GET", "/runner/blobs/" + "a" * 64, binary=True) == b'original-gzip-bytes'
    api.close_pool();assert sessions[0].closed


def test_registry_sources_and_geometry_are_published_with_original_hashes(tmp_path):
    src = source(tmp_path)
    raw = src / "data/cache/bank-network";raw.mkdir(parents=True)
    (raw / "agencies-page-000000.json").write_text('{"value":[{"Posicao":"2026-11-05"}]}')
    (raw / "municipalities.geojson").write_text('{"type":"FeatureCollection","features":[]}')
    (raw / "README.md").write_text('Documentation only')
    files, paths = r.inventory(src)
    selected = [f for f in files if f["path"].startswith("cache/runtime/bank-network/")]
    assert {f["path"] for f in selected} == {"cache/runtime/bank-network/agencies-page-000000.json", "cache/runtime/bank-network/municipalities.geojson"}
    for item in selected:
        assert item["sha256"] == r.digest(paths[item["path"]])
        assert r.logical_path(src, item["path"]) == paths[item["path"]]


def test_duplicate_content_is_uploaded_once_while_both_logical_files_remain(tmp_path):
    api = API()
    def duplicate(root, plan, progress):
        report = process(root, plan, progress)
        shutil.copyfile(root / "web/public/data/example.json", root / "web/public/data/example-copy.json")
        return report
    result = r.execute_claim(api, claim(), processor=duplicate, source_root=source(tmp_path), heartbeat_interval=100)
    puts = [call for call in api.calls if call[0] == "PUT"]
    assert sum(call[2] == b'{"value":12}' for call in puts) == 1
    assert result["files"] == 4 and result["uploaded"] == 3
    prepared = next(call[2] for call in api.calls if call[1] == "prepare")
    web = [file for file in prepared["files"] if file["path"].startswith("web/data/example")]
    assert len(web) == 2 and web[0]["sha256"] == web[1]["sha256"]
