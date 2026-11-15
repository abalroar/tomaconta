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


def public_claims(now=1000, **updates):
    return {"iss": "https://token.actions.githubusercontent.com", "aud": r.AUDIENCE,
            "repository": "abalroar/tomaconta", "repository_owner": "abalroar",
            "repository_id": "1141557164", "repository_owner_id": "255978345",
            "ref": "refs/heads/main", "workflow_ref": r.WORKFLOW,
            "repository_visibility": "public", "runner_environment": "github-hosted",
            "event_name": "workflow_dispatch", "sha": "a" * 40, "workflow_sha": "a" * 40,
            "run_id": "123", "run_attempt": "1", "iat": now, "nbf": now - 1,
            "exp": now + 600, **updates}


def source(tmp_path):
    root = tmp_path / "source"
    for folder in ("utils", "tabs", "data/bundled/demo", "web/public/data"):
        (root / folder).mkdir(parents=True)
    (root / "data/bundled/demo/dados.parquet").write_bytes(b"original source")
    (root / "web/public/data/example.json").write_text('{"value":0}')
    return root


def atlas_dataset(root, *, numerator=10):
    """A complete tiny PF/PJ generation with independently hashed assets."""
    data = root / "web/public/data"; data.mkdir(parents=True, exist_ok=True)
    persons = []
    for person in ("PF", "PJ"):
        rows = [[0, index, 0, 0, numerator, 100] for index in range(27)]
        checks = {"observedCells": 27, "expectedCells": 27, "absentCells": 0,
                  "zeroNumeratorCells": 0, "zeroDenominatorCells": 0,
                  "originalQuery": [{"cuts": 27, "maxRateDifferencePP": 0}],
                  "latest": {"numerator": numerator * 27, "denominator": 2700}}
        document = {"schemaVersion": 1, "person": person, "unit": "R$ mil",
                    "periodStart": "2026-07", "periodEnd": "2026-07",
                    "dims": {"person": person, "segmentKind": "income" if person == "PF" else "size",
                             "months": ["2026-07"], "ufs": [{"uf": uf} for uf in sorted(r.ATLAS_UFS)],
                             "segments": ["Uma faixa"], "products": ["Uma modalidade"]},
                    "rows": rows, "checks": checks, "sourceRevision": "a" * 64,
                    "sourceFiles": [{"asset": "scr_data_ano_2026.parquet", "bytes": 6,
                                     "sha256": r.hashlib.sha256(b"annual").hexdigest()}]}
        name = "atlas-" + person.lower() + ".json"
        (data / name).write_text(json.dumps(document))
        persons.append({"person": person, "checks": checks,
                        "asset": {"path": "data/" + name, "bytes": (data / name).stat().st_size,
                                  "sha256": r.digest(data / name)}})
    validation = {"schemaVersion": 1, "periodStart": "2026-07", "periodEnd": "2026-07",
                  "months": 1, "ufs": 27, "persons": persons}
    (data / "atlas-validation.json").write_text(json.dumps(validation))
    return data


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


def test_legacy_generation_gets_explicit_atlas_baseline_without_scr_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "f" * 40)
    src = source(tmp_path); atlas_dataset(src)
    target = tmp_path / "candidate"; target.mkdir()
    content = b'{"active":true}'
    sha = r.hashlib.sha256(content).hexdigest()
    item = {"path": "web/data/active.json", "size": len(content), "sha256": sha}
    class Progress:
        def check(self): pass
    r.seed_workspace(target, {"files": [item]}, API(blobs={sha: content}), Progress(), src)
    assert not (target / "web/public/data/example.json").exists()
    assert not (target / "data/cache/scr_data").exists()
    for name in r.ATLAS_FILES:
        assert (target / "web/public/data" / name).read_bytes() == (src / "web/public/data" / name).read_bytes()
    origin = json.loads((target / "web/public/data/atlas-origin.json").read_text())
    assert origin["mode"] == "versioned-baseline" and origin["sourceCommit"] == "f" * 40
    assert origin["source"] == "versioned-web-dataset"
    assert r.validate_atlas_artifacts(target)["origin"] == "versioned-baseline"


def test_atlas_baseline_never_replaces_existing_revision_or_repairs_partial_trio(tmp_path):
    src = tmp_path / "source"; atlas_dataset(src, numerator=10)
    target = tmp_path / "candidate"; active = atlas_dataset(target, numerator=20)
    hashes = {name: r.digest(active / name) for name in r.ATLAS_FILES}
    r.seed_atlas_baseline(target, src)
    assert {name: r.digest(active / name) for name in r.ATLAS_FILES} == hashes
    assert not (active / "atlas-origin.json").exists()
    (active / "atlas-pj.json").unlink()
    with pytest.raises(r.RunnerError, match="Atlas incompleta"):
        r.seed_atlas_baseline(target, src)
    assert not (active / "atlas-pj.json").exists()


def test_atlas_validation_is_optional_but_rejects_hash_or_source_divergence(tmp_path):
    assert r.validate_atlas_artifacts(tmp_path) is None
    data = atlas_dataset(tmp_path)
    assert set(r.validate_atlas_artifacts(tmp_path)["persons"]) == {"PF", "PJ"}
    original = (data / "atlas-pf.json").read_bytes()
    (data / "atlas-pf.json").write_bytes(original + b" ")
    with pytest.raises(r.RunnerError, match="validação/hash"):
        r.validate_atlas_artifacts(tmp_path)
    (data / "atlas-pf.json").write_bytes(original)
    r.atlas_origin(tmp_path, "candidate-scr")
    with pytest.raises(r.RunnerError, match="anuais SCR desta geração"):
        r.validate_atlas_artifacts(tmp_path)
    annual = tmp_path / "data/cache/scr_data/staging/annual/2026.parquet"
    annual.parent.mkdir(parents=True); annual.write_bytes(b"annual")
    assert r.validate_atlas_artifacts(tmp_path)["origin"] == "candidate-scr"


def test_atlas_export_failure_never_uploads_or_promotes_partial_generation(tmp_path, monkeypatch):
    src = source(tmp_path); baseline = atlas_dataset(src)
    hashes = {name: r.digest(baseline / name) for name in r.ATLAS_FILES}
    monkeypatch.setattr(r, "refresh_sources", lambda *args: (["scr_data"], {}))
    def generator(name, root, out, *args):
        if name == "export_atlas.py":
            (out / "atlas-pf.json").write_text('{"partial":true}')
            raise r.RunnerError("SCR sem classificação completa")
    monkeypatch.setattr(r, "run_generator", generator)
    api = API()
    with pytest.raises(r.RunnerError, match="classificação completa"):
        r.execute_claim(api, claim("scr_data"), source_root=src, heartbeat_interval=100)
    assert [call[1] for call in api.calls] == ["fail"]
    assert {name: r.digest(baseline / name) for name in r.ATLAS_FILES} == hashes


@pytest.mark.parametrize("kind", ["scr_data", "tudo", "bootstrap"])
def test_scr_and_bootstrap_regenerate_atlas_using_candidate_cache(tmp_path, monkeypatch, kind):
    output = tmp_path / "web/public/data"; output.mkdir(parents=True)
    cache = tmp_path / "data/cache/scr_data"
    annual = cache / "staging/annual/2026.parquet"; annual.parent.mkdir(parents=True)
    annual.write_bytes(b"annual"); (cache / "metadata.json").write_text('{}')
    calls = []
    monkeypatch.setattr(r, "refresh_sources", lambda *args: (["scr_data"] if kind != "bootstrap" else [], {}))
    def generator(name, root, out, *args):
        calls.append((name, root, out, args))
        if name == "export_atlas.py": atlas_dataset(root)
        if name == "export_network.py":
            (out / "bank-network.json").write_text(json.dumps({"position": "2026-11-05", "checks": {"reconciled": True}}))
    monkeypatch.setattr(r, "run_generator", generator)
    monkeypatch.setattr(r, "validate_artifacts", lambda root: {"atlas": r.validate_atlas_artifacts(root)})
    class Progress:
        def update(self, *args): pass
    result = r.materialize_generation(tmp_path, {"kind": kind}, Progress())
    names = [call[0] for call in calls]
    assert names.count("export_atlas.py") == 1
    assert names.index("export_atlas.py") < names.index("export_charts.py")
    call = next(call for call in calls if call[0] == "export_atlas.py")
    assert call[1] == tmp_path and call[2] == output and call[3] == ()
    assert result["reports"]["atlas"]["status"] == "updated"
    assert result["coverage"]["atlas"]["origin"] == "candidate-scr"


@pytest.mark.parametrize("kind", ["financeiro", "mercado_imobiliario", "rede_agencias", "bootstrap"])
def test_unrelated_generation_preserves_atlas_and_bootstrap_without_scr_uses_identified_baseline(tmp_path, monkeypatch, kind):
    src = tmp_path / "baseline"; atlas_dataset(src)
    root = tmp_path / "candidate"
    r.seed_atlas_baseline(root, src)
    data = root / "web/public/data"
    hashes = {name: r.digest(data / name) for name in (*r.ATLAS_FILES, "atlas-origin.json")}
    changed = ["principal"] if kind == "financeiro" else []
    calls = []
    monkeypatch.setattr(r, "refresh_sources", lambda *args: (changed.copy(), {}))
    def generator(name, candidate, out, *args):
        calls.append(name)
        if name == "export_network.py":
            (out / "bank-network.json").write_text(json.dumps({"position": "2026-11-05", "checks": {"reconciled": True}}))
    monkeypatch.setattr(r, "run_generator", generator)
    monkeypatch.setattr(r, "validate_artifacts", lambda candidate: {"atlas": r.validate_atlas_artifacts(candidate)})
    class Progress:
        def update(self, *args): pass
    result = r.materialize_generation(root, {"kind": kind}, Progress())
    assert "export_atlas.py" not in calls
    assert {name: r.digest(data / name) for name in hashes} == hashes
    assert result["reports"]["atlas"]["status"] == "preserved"
    assert result["coverage"]["atlas"]["origin"] == "versioned-baseline"


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
        payload = base64.urlsafe_b64encode(json.dumps(public_claims(now[0])).encode()).rstrip(b"=").decode()
        return io.BytesIO(json.dumps({"value": "header." + payload + ".signature"}).encode())
    identity = r.OidcIdentity(env={"ACTIONS_ID_TOKEN_REQUEST_URL": "https://run.actions.githubusercontent.com/id?x=1",
                                   "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "oidc-request-only"}, opener=opener, clock=lambda: now[0])
    first = identity.bearer(); assert identity.bearer() == first; assert len(calls) == 1
    now[0] = 1550
    assert identity.bearer() != first; assert len(calls) == 2
    assert "audience=https%3A%2F%2Fmatheusprat.es%2Ftomaconta%2Fapi%2Fshared%2Frunner" in calls[0].full_url
    assert calls[0].get_header("User-agent") == r.RUNNER_USER_AGENT


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
    assert "cron: '2,7,12,17,22,27,32,37,42,47,52,57 * * * *'" in text
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
        if name == "export_atlas.py":
            atlas_dataset(root)
        if name == "export_network.py":
            (out / "bank-network.json").write_text(json.dumps({"position": "2026-11-05", "checks": {"reconciled": True, "selectedRecords": 12818}}))
    monkeypatch.setattr(r, "run_generator", generator)
    monkeypatch.setattr(r, "validate_artifacts", lambda root: {"charts": 104})
    class Progress:
        def update(self, *args): pass
    result = r.materialize_generation(tmp_path, {"kind": kind}, Progress())
    expected = (["export_atlas.py"] if kind == "tudo" else []) + ["export_charts.py", "export_network.py"]
    assert [c[0] for c in calls] == expected
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
    assert all(call[2]["headers"]["User-agent"] == r.RUNNER_USER_AGENT for call in calls)
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


@pytest.mark.parametrize("key", ["iss", "aud", "repository", "repository_owner", "repository_id", "repository_owner_id", "ref", "workflow_ref", "event_name", "runner_environment", "repository_visibility", "sha", "workflow_sha", "run_id", "run_attempt", "exp", "nbf", "iat"])
def test_identity_diagnostics_report_only_divergent_claim_names(key):
    claims = public_claims(**{key: "SENSITIVE-SUPPLIED-VALUE"})
    with pytest.raises(r.RunnerError) as error:
        r.diagnose_identity_claims(claims, env={}, now=1000)
    assert str(error.value) == "Claims OIDC divergentes: " + key
    assert "SENSITIVE" not in str(error.value)


def test_identity_receipt_is_boolean_and_explicitly_not_signature_verification():
    receipt = r.diagnose_identity_claims(public_claims(), env={}, now=1000)
    assert receipt["diagnosticOnly"] is True and receipt["signatureVerifiedLocally"] is False
    assert receipt["publicMetadataMatches"] is True
    assert all(value is True for value in receipt["claimSentinels"].values())
    serialized = json.dumps(receipt)
    assert "abalroar" not in serialized and "token.actions" not in serialized


def test_identity_only_never_creates_api_client_or_outputs_token(monkeypatch, capsys):
    calls = []
    class Identity:
        def bearer(self): calls.append("identity");return "NEVER-PRINT-THIS-TOKEN"
    monkeypatch.setattr(r, "check_github_context", lambda: None)
    monkeypatch.setattr(r, "OidcIdentity", Identity)
    monkeypatch.setattr(r, "SharedAPI", lambda: pytest.fail("identity-only cannot create an API client"))
    assert r.main(["--identity-only"]) == 0
    output = capsys.readouterr().out
    assert "NEVER-PRINT" not in output
    assert json.loads(output) == {"status": "identity_only", "apiCalled": False}
    assert calls == ["identity"]
    with pytest.raises(r.RunnerError): r.main(["--identity-only", "--seed"])


def test_http_diagnostics_whitelist_headers_and_never_read_error_body():
    headers = {"X-TomaConta-Service": "shared-v1", "Content-Type": "application/json; charset=utf-8",
               "CF-Ray": "0123456789abcdef-GRU", "Authorization": "NEVER-LOG", "Set-Cookie": "NEVER-LOG"}
    safe = r.safe_http_diagnostics(headers)
    assert safe == {"workerMarker": True, "contentType": "application/json; charset=utf-8", "cfRay": "0123456789abcdef-GRU", "cfMitigated": "absent"}
    assert r.safe_http_diagnostics({"cf-mitigated": "challenge"})["cfMitigated"] == "challenge"
    assert r.safe_http_diagnostics({"cf-mitigated": "NEVER-LOG"})["cfMitigated"] == "unavailable"
    assert "NEVER" not in json.dumps(safe)
    assert r.safe_http_diagnostics({"CF-Ray": "Bearer-NEVER-LOG", "Content-Type": "NEVER-LOG"})["cfRay"] == "unavailable"
    class Identity:
        def bearer(self): return "private-token"
    def opener(request, **kwargs):
        raise HTTPError(request.full_url, 403, "", headers, io.BytesIO(b"NEVER-READ-BODY"))
    api = r.SharedAPI(identity=Identity(), opener=opener)
    with pytest.raises(r.RunnerError) as error: api.request("GET", "/runner/pending")
    assert '"workerMarker":true' in str(error.value)
    assert "0123456789abcdef-GRU" in str(error.value)
    assert "NEVER" not in str(error.value) and "private-token" not in str(error.value)


def test_schedule_requires_activation_and_manual_diagnostic_has_priority():
    text = (ROOT / ".github/workflows/tomaconta-shared.yml").read_text()
    assert "(github.event_name == 'workflow_dispatch' || vars.TOMACONTA_SHARED_ENABLED == 'true')" in text
    assert text.index("--identity-only") < text.index("--seed --pending-only")
    assert "diagnostic:" in text
    assert "if: needs.pending.outputs.pending == 'true'" in text


def test_pooled_http_error_preserves_only_diagnostic_headers(monkeypatch):
    import requests
    class Response:
        status_code = 403
        headers = {"X-TomaConta-Service": "shared-v1", "Content-Type": "application/json", "CF-Ray": "0123456789abcdef-GRU", "Authorization": "NEVER-LOG"}
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def json(self): pytest.fail("error bodies cannot be read")
    class Session:
        def request(self, *args, **kwargs): return Response()
        def close(self): pass
    class Identity:
        def bearer(self): return "private-token"
    monkeypatch.setattr(requests, "Session", Session)
    api = r.SharedAPI(identity=Identity());api.enable_pool()
    with pytest.raises(r.RunnerError) as error: api.request("GET", "/runner/pending")
    assert '"workerMarker":true' in str(error.value)
    assert "NEVER" not in str(error.value)
    assert api.denied is True
    api.close_pool()


def test_runner_identifies_itself_with_fixed_application_user_agent(monkeypatch):
    monkeypatch.setenv("USER_AGENT", "invalid-environment-value")
    monkeypatch.setenv("RUNNER_USER_AGENT", "invalid-environment-override")
    calls = []
    class Identity:
        def bearer(self): return "fixture-identity"
    def opener(request, **kwargs):
        calls.append(request)
        return io.BytesIO(b'{"pending":false}')
    api = r.SharedAPI(identity=Identity(), opener=opener)
    assert api.request("GET", "/runner/pending", headers={"User-Agent": "invalid-request-override", "user-agent": "invalid-lowercase-override"}) == {"pending": False}
    assert calls[0].get_header("User-agent") == "TomaContaSharedRunner/1.0 (+https://github.com/abalroar/tomaconta)"
    assert r.API_ROOT == "https://matheusprat.es/tomaconta/api/shared"
    assert r.AUDIENCE == "https://matheusprat.es/tomaconta/api/shared/runner"
