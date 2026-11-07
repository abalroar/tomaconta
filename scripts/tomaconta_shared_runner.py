#!/usr/bin/env python3
"""Execute only queued Toma Conta updates, pinning one validated generation.

GitHub Actions supplies a short-lived OIDC identity. Collection and all financial
calculations remain in the project's original Python modules. No GitHub token,
repository mutation, shell command from a plan, or client credential is used.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import base64
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = "https://matheusprat.es/tomaconta/api/shared"
AUDIENCE = API_ROOT + "/runner"
WORKFLOW = "abalroar/tomaconta/.github/workflows/tomaconta-shared.yml@refs/heads/main"
KINDS = {"bootstrap", "financeiro", "individual", "mercado_credito_sgs", "mercado_imobiliario", "scr_data", "spb_meios_pagamento", "rede_agencias", "tudo"}
HEX = re.compile(r"[a-f0-9]{64}\Z")
MAX_FILE = 64_000_000


class RunnerError(RuntimeError):
    pass


class NeedsReview(RunnerError):
    def __init__(self, report):
        super().__init__("Há contas ou divergências para revisão; a geração publicada foi preservada")
        self.report = report


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def check_github_context(env=os.environ):
    required = {"GITHUB_REPOSITORY_ID": "1141557164", "GITHUB_REPOSITORY_OWNER_ID": "255978345",
                "GITHUB_REF": "refs/heads/main", "GITHUB_WORKFLOW_REF": WORKFLOW}
    if any(env.get(key) != value for key, value in required.items()):
        raise RunnerError("A execução deve usar o workflow oficial da branch main")
    if env.get("GITHUB_EVENT_NAME") not in {"schedule", "workflow_dispatch"}:
        raise RunnerError("Evento não autorizado para atualização compartilhada")
    if not re.fullmatch(r"[a-f0-9]{40}", env.get("GITHUB_SHA", "")):
        raise RunnerError("Commit de origem ausente")


def diagnose_identity_claims(claims, *, audience=AUDIENCE, env=os.environ, now=None):
    """Inspect public metadata only; the server must still verify the signature.

    Errors identify claim names, never token bytes, supplied values, credentials,
    request URLs or response bodies. Successful diagnostics contain booleans.
    """
    if not isinstance(claims, dict):
        raise RunnerError("Claims OIDC divergentes: payload")
    now = time.time() if now is None else now
    expected = {"iss": "https://token.actions.githubusercontent.com", "aud": audience,
                "repository": "abalroar/tomaconta", "repository_owner": "abalroar",
                "repository_id": "1141557164", "repository_owner_id": "255978345",
                "ref": "refs/heads/main", "workflow_ref": WORKFLOW,
                "runner_environment": "github-hosted", "repository_visibility": "public"}
    checks = {key: (str(claims.get(key)) == value if key.endswith("_id") else claims.get(key) == value)
              for key, value in expected.items()}
    checks["event_name"] = (claims.get("event_name") in {"schedule", "workflow_dispatch"}
                            and (not env.get("GITHUB_EVENT_NAME") or claims.get("event_name") == env["GITHUB_EVENT_NAME"]))
    for key, variable in (("sha", "GITHUB_SHA"), ("workflow_sha", "GITHUB_WORKFLOW_SHA")):
        value = claims.get(key)
        checks[key] = (isinstance(value, str) and re.fullmatch(r"[a-f0-9]{40}", value) is not None
                       and (not env.get(variable) or value == env[variable]))
    for key, variable, limit in (("run_id", "GITHUB_RUN_ID", 25), ("run_attempt", "GITHUB_RUN_ATTEMPT", 8)):
        value = str(claims.get(key, ""))
        checks[key] = (re.fullmatch(r"\d{1," + str(limit) + r"}", value) is not None
                       and (not env.get(variable) or value == env[variable]))
    numeric = lambda value: type(value) in {int, float} and math.isfinite(value)
    checks["exp"] = numeric(claims.get("exp")) and claims["exp"] > now + 60
    checks["nbf"] = numeric(claims.get("nbf")) and claims["nbf"] <= now + 30
    checks["iat"] = numeric(claims.get("iat")) and now - 600 <= claims["iat"] <= now + 30
    invalid = sorted(key for key, matched in checks.items() if not matched)
    if invalid:
        raise RunnerError("Claims OIDC divergentes: " + ", ".join(invalid))
    return {"phase": "identity", "diagnosticOnly": True, "signatureVerifiedLocally": False,
            "publicMetadataMatches": True, "claimSentinels": checks}


def safe_http_diagnostics(headers):
    headers = headers or {}
    content_type = headers.get("Content-Type", "")
    ray = headers.get("CF-Ray", "")
    return {"workerMarker": headers.get("X-TomaConta-Service") == "shared-v1",
            "contentType": content_type if isinstance(content_type, str) and len(content_type) <= 120 and re.fullmatch(r"[A-Za-z0-9.+/-]+(?:;[A-Za-z0-9= ._-]+)*", content_type) else "unavailable",
            "cfRay": ray if isinstance(ray, str) and re.fullmatch(r"[A-Fa-f0-9]{16,32}(?:-[A-Za-z0-9]{2,10})?", ray) else "unavailable",
            "cfMitigated": "challenge" if headers.get("cf-mitigated") == "challenge" else "absent" if not headers.get("cf-mitigated") else "unavailable"}


class OidcIdentity:
    def __init__(self, audience=AUDIENCE, env=os.environ, opener=urlopen, clock=time.time):
        self.audience, self.env, self.opener, self.clock = audience, env, opener, clock
        self.token, self.until, self.lock = None, 0, threading.Lock()

    def bearer(self):
        with self.lock:
            if self.token and self.clock() < self.until:
                return self.token
            url = self.env.get("ACTIONS_ID_TOKEN_REQUEST_URL", "")
            credential = self.env.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".actions.githubusercontent.com") or not credential:
                raise RunnerError("Identidade OIDC do GitHub Actions indisponível")
            query = [(k, v) for k, v in parse_qsl(parsed.query) if k != "audience"] + [("audience", self.audience)]
            url = urlunsplit(parsed._replace(query=urlencode(query)))
            request = Request(url, headers={"Authorization": "Bearer " + credential})
            try:
                with self.opener(request, timeout=30) as response:
                    value = json.load(response)
            except (HTTPError, URLError, TimeoutError, ValueError):
                raise RunnerError("Não foi possível obter a identidade OIDC do GitHub Actions") from None
            token = value.get("value", "")
            try:
                payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "==="))
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise RunnerError("Resposta OIDC inválida") from exc
            receipt = diagnose_identity_claims(payload, audience=self.audience, env=self.env, now=self.clock())
            until = float(payload["exp"]) - 60
            print(json.dumps(receipt, separators=(",", ":")), flush=True)
            # Claims are cryptographically verified by the server; this local
            # decode merely schedules renewal and is never an authorization gate.
            self.token, self.until = token, until
            return token


class SharedAPI:
    def __init__(self, root=API_ROOT, identity=None, opener=urlopen):
        parsed = urlsplit(root)
        if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
            raise RunnerError("Endpoint compartilhado HTTPS inválido")
        self.root, self.identity, self.opener = root.rstrip("/"), identity or OidcIdentity(), opener
        self.denied = False
        self.pool, self.sessions, self.session_lock = None, [], threading.Lock()
        self.thread_session = threading.local()

    def enable_pool(self):
        # The idle probe has no third-party dependencies. Execution enables the
        # already-pinned requests library after setup, reusing TLS per thread.
        import requests
        self.pool = requests

    def close_pool(self):
        for session in self.sessions:
            session.close()

    def pooled_request(self, request, binary):
        if not hasattr(self.thread_session, "session"):
            self.thread_session.session = self.pool.Session()
            with self.session_lock:
                self.sessions.append(self.thread_session.session)
        try:
            with self.thread_session.session.request(request.get_method(), request.full_url,
                    data=request.data, headers=dict(request.header_items()),
                    timeout=(15, 120 if binary or request.get_method() == "PUT" else 45),
                    allow_redirects=False, stream=binary) as response:
                if not 200 <= response.status_code < 300:
                    safe_headers = {name: response.headers.get(name, "") for name in ("X-TomaConta-Service", "Content-Type", "CF-Ray", "cf-mitigated")}
                    raise HTTPError(request.full_url, response.status_code, "", safe_headers, None)
                return response.raw.read(MAX_FILE + 1) if binary else response.json()
        except self.pool.RequestException:
            raise URLError("Conexão com o serviço interrompida") from None

    def request(self, method, path, data=None, *, binary=False, headers=None):
        if self.denied:
            raise RunnerError("Acesso ao serviço negado; novas tentativas foram interrompidas")
        if not path.startswith("/runner/") or ".." in path:
            raise RunnerError("Operação do executor inválida")
        extra = {"Authorization": "Bearer " + self.identity.bearer(), "Accept-Encoding": "identity", **(headers or {})}
        if data is not None and not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
            extra["Content-Type"] = "application/json"
        request = Request(self.root + path, data=data, headers=extra, method=method)
        attempts = 2 if method in {"GET", "PUT"} or path.endswith("/publish") else 1
        for attempt in range(attempts):
            try:
                if self.pool:
                    result = self.pooled_request(request, binary)
                    if binary and len(result) > MAX_FILE:
                        raise RunnerError("Arquivo recebido excede o limite da geração")
                    return result
                with self.opener(request, timeout=120 if binary or method == "PUT" else 45) as response:
                    if binary:
                        content = response.read(MAX_FILE + 1)
                        if len(content) > MAX_FILE:
                            raise RunnerError("Arquivo recebido excede o limite da geração")
                        return content
                    return json.load(response)
            except HTTPError as exc:
                if exc.code in {401, 403, 429}:
                    self.denied = True
                # Never include response bodies, Authorization, identity URLs or JWTs.
                diagnostic = json.dumps(safe_http_diagnostics(exc.headers), separators=(",", ":"))
                raise RunnerError(f"Serviço compartilhado respondeu HTTP {exc.code}; geração anterior preservada; {diagnostic}") from None
            except (URLError, TimeoutError, ConnectionError):
                if attempt + 1 == attempts:
                    raise RunnerError("A conexão com o serviço foi interrompida; confira o estado da atualização") from None
                # Only reads, content-addressed writes and idempotent publication
                # can be retried after a lost response. Claims are never retried.

    def action(self, job, action, **values):
        return self.request("POST", f"/runner/jobs/{job['id']}/{action}", {"lease": job["lease_id"], **values})


class Heartbeat:
    def __init__(self, api, job, interval=30):
        self.api, self.job, self.interval = api, job, interval
        self.progress, self.message, self.error = 0.01, "Preparando a geração", None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join(timeout=46)

    def loop(self):
        while not self.stop.wait(self.interval):
            try:
                self.api.action(self.job, "heartbeat", progress=self.progress, message=self.message)
            except Exception as exc:
                self.error = exc
                self.stop.set()

    def update(self, progress, message):
        self.check()
        self.progress, self.message = min(.98, max(self.progress, float(progress))), str(message)[:300]

    def check(self):
        if self.error:
            raise RunnerError("A reserva de execução não pôde ser renovada; publicação interrompida") from self.error


def validate_plan(plan):
    if not isinstance(plan, dict) or set(plan) - {"kind", "mode", "start", "end", "period", "uf"}:
        raise RunnerError("Plano de atualização inválido")
    if plan.get("kind") not in KINDS or plan.get("mode", "incremental") not in {"incremental", "overwrite"}:
        raise RunnerError("Fonte ou modo inválido")
    for key in ("start", "end", "period"):
        if plan.get(key) is not None and not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", str(plan[key])):
            raise RunnerError("Competência mensal inválida")
    if bool(plan.get("start")) != bool(plan.get("end")):
        raise RunnerError("Informe os dois limites da janela")
    if plan.get("start"):
        a, b = (date.fromisoformat(plan[k] + "-01") for k in ("start", "end"))
        months = (b.year - a.year) * 12 + b.month - a.month
        if not 0 <= months <= 23:
            raise RunnerError("A janela precisa conter até 24 meses")
    if plan.get("kind") == "individual" and plan.get("period", "0000-03")[-2:] not in {"03", "06", "09", "12"}:
        raise RunnerError("A visão individual usa fim de trimestre")
    if plan.get("uf") is not None and (plan["kind"] != "mercado_imobiliario" or plan["uf"] not in {"br", "ac", "al", "ap", "am", "ba", "ce", "df", "es", "go", "ma", "mt", "ms", "mg", "pa", "pb", "pr", "pe", "pi", "rj", "rn", "rs", "ro", "rr", "sc", "sp", "se", "to"}):
        raise RunnerError("Abrangência imobiliária inválida")
    if plan["kind"] == "rede_agencias" and any(plan.get(key) is not None for key in ("start", "end", "period", "uf")):
        raise RunnerError("O cadastro de agências usa a posição atual, sem janela histórica")
    return {key: value for key, value in plan.items() if value is not None}


def logical_path(root, logical):
    parts = PurePosixPath(logical).parts
    if not parts or logical.startswith("/") or any(p in {"", ".", ".."} for p in logical.split("/")):
        raise RunnerError("Caminho de artefato inválido")
    if parts[:2] == ("web", "data"):
        result = root / "web/public/data" / Path(*parts[2:])
    elif parts[:2] == ("cache", "bundled"):
        result = root / "data/bundled" / Path(*parts[2:])
    elif parts[:2] == ("cache", "runtime"):
        result = root / "data/cache" / Path(*parts[2:])
        if re.fullmatch(r"cache/runtime/financial_analysis_sources/[a-f0-9]{2}/[a-f0-9]{64}\.bin", logical):
            result = result.with_suffix("")
    else:
        raise RunnerError("Artefato fora da geração")
    if not result.resolve().is_relative_to(root.resolve()):
        raise RunnerError("Caminho fora da geração")
    return result


def validate_file(item):
    if not isinstance(item, dict) or not HEX.fullmatch(item.get("sha256", "")) or type(item.get("size")) is not int or not 0 < item["size"] <= MAX_FILE:
        raise RunnerError("Identidade ou tamanho de artefato inválido")
    if item.get("encoding", "identity") != "identity":
        raise RunnerError("Os bytes das fontes devem preservar sua codificação original")


def seed_workspace(root, base, api, progress, source_root=ROOT):
    if base is None:
        for directory in ("data/bundled", "web/public/data"):
            source = source_root / directory
            if not source.is_dir():
                raise RunnerError("Baseline versionada incompleta")
            shutil.copytree(source, root / directory, dirs_exist_ok=True)
    else:
        files = base.get("files", [])
        if not files:
            raise RunnerError("Geração ativa sem arquivos")
        seen = set()
        def restore(item):
            validate_file(item)
            target = logical_path(root, item["path"])
            local = logical_path(source_root, item["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            if local.is_file() and local.stat().st_size == item["size"] and digest(local) == item["sha256"]:
                shutil.copyfile(local, target)
            else:
                content = api.request("GET", "/runner/blobs/" + item["sha256"], binary=True)
                if len(content) != item["size"] or hashlib.sha256(content).hexdigest() != item["sha256"]:
                    raise RunnerError("Hash da geração ativa divergente")
                target.write_bytes(content)
            progress.check()
        for item in files:
            if item["path"] in seen:
                raise RunnerError("Caminho duplicado no manifesto ativo")
            seen.add(item["path"])
            logical_path(root, item["path"])
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(restore, files))
    # Original model code is read-only and exactly identical to this workflow's
    # pinned commit. Exporter checks these bytes before publishing its engine.
    for name in ("utils", "tabs"):
        (root / name).symlink_to(source_root / name, target_is_directory=True)


def checked_result(result):
    meta = result.metadata or {}
    errors = ("falhas", "errors", "erros", "failures", "failed_windows", "remaining_windows", "pending_periods", "failed_periods")
    if not result.sucesso or any(meta.get(k) for k in errors) or meta.get("finalized") is False or meta.get("status") in {"partial", "failed"}:
        raise RunnerError(str(result.mensagem or "Coleta incompleta")[:1000])
    return meta


def monthly_window(plan, cache, *, months=12):
    import pandas as pd
    if plan.get("start"):
        return pd.Timestamp(plan["start"] + "-01"), pd.Period(plan["end"], freq="M").end_time.date()
    latest = pd.Timestamp(date.today())
    start = latest.to_period("M") - (months - 1)
    return start.start_time.date(), latest.date()


def promote_bundles(manager, names):
    for name in set(names):
        cache = manager.get_cache(name)
        if cache is None:
            raise RunnerError("Cache desconhecido na geração")
        if not cache.arquivo_dados_runtime.exists() or not cache.arquivo_metadata_runtime.exists():
            raise RunnerError(f"Fonte atualizada sem par dados/metadata: {name}")
        cache.bundled_dir.mkdir(parents=True, exist_ok=True)
        # Dataset sidecars (SPB/SCR) retain their original names and bytes.
        for path in cache.cache_dir.iterdir():
            if path.is_file() and path.suffix in {".parquet", ".json"} and not path.name.startswith("."):
                shutil.copyfile(path, cache.bundled_dir / path.name)


def run_generator(name, root, output, *args):
    subprocess.run([sys.executable, str(ROOT / "web/tools" / name), "--root", str(root), "--output", str(output), *args],
                   check=True, cwd=ROOT, env=os.environ.copy())


def latest_ifdata_quarter(root):
    import requests
    response = requests.get("https://www3.bcb.gov.br/ifdata/rest/relatorios2025a2030", timeout=(15, 45))
    response.raise_for_status()
    periods = [str(item["dt"]) for item in response.json() if re.fullmatch(r"20\d{2}(03|06|09|12)", str(item.get("dt", "")))]
    if not periods:
        raise RunnerError("Nenhuma competência trimestral publicada no IF.data")
    return max(periods)


def update_individual(root, manager, period, progress):
    from utils.ifdata_cache.financial_analysis_update import individual_review
    from utils.ifdata_cache.financial_analysis_review import pending_items
    from utils.ifdata_cache.ifdata_web import get_web_source
    from utils.ifdata_cache.bloprudencial_cache import row_overrides
    cache = manager.get_cache("balancete_individual")
    result = cache.extrair_periodo(period, cache_dir=root / "data/cache/bcb_cosif_4010", force_refresh=True)
    source_receipt = checked_result(result)
    receipt_path = root / "data/cache/bcb_cosif_4010" / (period + "-receipt.json")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(source_receipt, ensure_ascii=False, allow_nan=False, default=str), encoding="utf-8")
    cache.add_period(result.dados)
    decisions = manager.get_cache("bloprudencial").cosif_decisions()
    items = pending_items(individual_review(cache, period, row_overrides(decisions)), {item["id"] for item in decisions})
    if items:
        raise NeedsReview({"period": period, "pending_review": items[:40], "pending_count": len(items)})
    os.environ["TOMACONTA_IFDATA_SOURCE"] = "web"
    os.environ["TOMACONTA_IFDATA_WEB_DIR"] = str(root / "data/cache/bcb_ifdata_web")
    os.environ["TOMACONTA_IFDATA_REGISTRY_DIR"] = str(root / "data/cache/institution_registry")
    get_web_source.cache_clear()
    names = ["balancete_individual"]
    for name in ("principal_individual", "dre_individual"):
        progress.update(.35, f"Atualizando {name}")
        checked_result(manager.extrair_periodos_com_salvamento(name, [period], modo="overwrite", force_refresh=True))
        names.append(name)
    from utils.ifdata_cache.release_ops import materialize_for_publication
    details = materialize_for_publication(manager, cache_names=names, base_dir=root)
    if any(item["status"] != "ok" for item in details):
        raise RunnerError("Materialização individual incompleta")
    return names + [item["cache"] for item in details]


def refresh_sources(root, plan, progress):
    sys.path.insert(0, str(ROOT))
    from utils.ifdata_cache import CacheManager
    from utils.ifdata_cache.official_store import writable_cache_context
    manager = CacheManager(root)
    kind = plan["kind"]
    changed, reports = [], {}
    with writable_cache_context():
        if kind in {"financeiro", "tudo"}:
            from utils.ifdata_cache.financial_analysis_update import update
            report, _ = update(root, period=plan.get("period", "").replace("-", "") or None,
                               progress=lambda message: progress.update(.25, message))
            if report["status"] == "needs_review":
                raise NeedsReview({"period": report.get("period"), "pending_review": report.get("pending_review", [])[:40]})
            if report["status"] not in {"updated", "unchanged"}:
                raise RunnerError(report.get("error", "Atualização financeira não concluída"))
            changed.extend(report.get("promoted", []))
            reports["financeiro"] = {k: report.get(k) for k in ("status", "period", "ifdata_period", "changed", "validation", "source_quality", "sources")}
            quarter = report.get("ifdata_period")
            if quarter:
                changed.extend(update_individual(root, manager, quarter, progress))
        elif kind == "individual":
            period = plan.get("period", "").replace("-", "") or latest_ifdata_quarter(root)
            changed.extend(update_individual(root, manager, period, progress))
            reports["individual"] = {"period": period, "status": "updated"}
        for name in ("mercado_credito_sgs", "mercado_imobiliario", "spb_meios_pagamento", "scr_data"):
            if kind not in {name, "tudo"}:
                continue
            progress.update(.3, "Coletando " + name)
            cache = manager.get_cache(name)
            callback = lambda fraction, message: progress.update(.3 + .2 * float(fraction), message)
            if name in {"mercado_credito_sgs", "mercado_imobiliario"}:
                start, end = monthly_window(plan, cache)
                result = cache.materialize_history(start=start, end=end, overwrite=True, progress_callback=callback)
            elif name == "spb_meios_pagamento":
                result = cache.materialize_history(overwrite=True, progress_callback=callback)
            else:
                start, end = monthly_window(plan, cache, months=24)
                # Preserve annual slices already installed by the active version.
                result = cache.materialize_history(ano_inicial=start.year, ano_final=end.year,
                                                   overwrite=plan.get("mode") == "overwrite", manter_zip=False,
                                                   log_callback=lambda message: progress.update(.4, message))
            reports[name] = checked_result(result)
            changed.append(name)
        if changed:
            promote_bundles(manager, changed)
    return sorted(set(changed)), reports


def validate_artifacts(root):
    data = root / "web/public/data"
    required = ["manifest.json", "sfn.json", "extra.json", "imob-br.json", "imob-catalog.json", "institutions.json",
                "statements/index.json", "statements/crosswalk.json", "statements/engine/manifest.json", "bank-network.json", "bank-network-ufs.geojson"]
    for name in required:
        if not (data / name).is_file():
            raise RunnerError("Geração incompleta: " + name)
    manifest = json.loads((data / "manifest.json").read_text())
    counts = {}
    for name in ("sfn", "extra", "imob-br"):
        charts = json.loads((data / (name + ".json")).read_text())
        if not charts or len({c["id"] for c in charts}) != len(charts):
            raise RunnerError("Catálogo de gráficos vazio ou duplicado")
        if any(not c.get("series") for c in charts):
            raise RunnerError("Gráfico solicitado sem séries")
        counts[name] = len(charts)
    housing = json.loads((data / "imob-br.json").read_text())
    if counts["imob-br"] != 24 or any(re.search("bndu", c["id"] + c["title"], re.I) for c in housing):
        raise RunnerError("Escopo imobiliário divergente do aprovado")
    for uf in manifest.get("ufs", []):
        if not re.fullmatch(r"[a-z]{2}", uf) or not (data / f"imob-{uf}.json").is_file():
            raise RunnerError("Cobertura UF incompleta")
    index = json.loads((data / "statements/index.json").read_text())
    if index.get("coverage") != "all-source-identities" or index.get("modelVersion") != "statement-v6":
        raise RunnerError("A geração deve preservar o universo completo das demonstrações")
    for entity in index["institutions"]:
        for field, sha in (("path", "snapshotSha256"), ("inputPath", "inputSha256")):
            logical = "web/" + entity[field]
            path = logical_path(root, logical)
            if not path.is_file() or digest(path) != entity[sha]:
                raise RunnerError("Snapshot/input não corresponde à sua identidade/hash")
    engine = json.loads((data / "statements/engine/manifest.json").read_text())
    for module in engine["modules"]:
        path = data / "statements/engine" / module["path"]
        if not path.resolve().is_relative_to((data / "statements/engine").resolve()) or digest(path) != module["sha256"]:
            raise RunnerError("Módulo financeiro diferente do manifesto")
    network = json.loads((data / "bank-network.json").read_text())
    if network.get("checks", {}).get("reconciled") is not True:
        raise RunnerError("Cadastro de agências não reconciliado")
    return {"charts": counts, "statements": index.get("counts"), "modelVersion": index["modelVersion"],
            "network": {"position": network["position"], **{key: network["checks"].get(key) for key in ("sourceRecords", "selectedRecords", "bankCount", "analysisLinks")}}}


def materialize_generation(root, plan, progress):
    changed, reports = refresh_sources(root, plan, progress)
    output = root / "web/public/data"
    if set(changed) & {"scr_data", "spb_meios_pagamento"}:
        for kind, flag in (("scr_data", "scr"), ("spb_meios_pagamento", "spb")):
            if kind in changed:
                run_generator("export_extra.py", root, output / "extra.json", "--only", flag)
    # This renderer reads only the explicit candidate bundles, including on imob
    # updates. The resulting deck is later built from these very JSON datasets.
    progress.update(.58, "Gerando os gráficos a partir das fontes desta execução")
    run_generator("export_charts.py", root, output)
    financial = set(changed) - {"scr_data", "spb_meios_pagamento", "mercado_credito_sgs", "mercado_imobiliario", "rede_agencias"}
    if financial or plan["kind"] == "bootstrap":
        progress.update(.62, "Gerando o catálogo e as demonstrações com o modelo original")
        run_generator("export_institutions.py", root, output)
        run_generator("export_statements.py", root, output)
    if financial or plan["kind"] in {"bootstrap", "rede_agencias", "tudo"}:
        # The pipeline derives the last real financial period from these pinned
        # candidate catalogs, independently of the registry's current position.
        run_generator("export_network.py", root, output, "--source-dir", str(root / "data/cache/bank-network"), "--catalog-dir", str(output), "--refresh")
        changed.append("rede_agencias")
        network = json.loads((output / "bank-network.json").read_text())
        reports["rede_agencias"] = {"position": network["position"], "checks": network["checks"]}
    progress.update(.78, "Conferindo arquivos, cobertura e hashes")
    coverage = validate_artifacts(root)
    return {"changed": changed, "reports": reports, "coverage": coverage}


def inventory(root):
    files, paths = [], {}
    for directory, prefix in (("web/public/data", "web/data"), ("data/bundled", "cache/bundled")):
        for path in sorted((root / directory).rglob("*")):
            if not path.is_file() or path.name.startswith(".") or path.name.endswith(".tmp") or path.suffix == ".md":
                continue
            logical = prefix + "/" + path.relative_to(root / directory).as_posix()
            item = {"path": logical, "sha256": digest(path), "size": path.stat().st_size, "encoding": "identity"}
            validate_file(item)
            files.append(item); paths[logical] = path
    for folder in ("scr_data", "bank-network", "financial_analysis_sources", "financial_analysis_updates", "shared_runs", "bcb_cosif_4010", "bcb_ifdata_web", "institution_registry"):
        source = root / "data/cache" / folder
        for path in sorted(source.rglob("*")) if source.exists() else []:
            if not path.is_file() or path.name.startswith(".") or path.suffix == ".tmp" or "/pending/" in str(path):
                continue
            if folder != "financial_analysis_sources" and path.suffix not in {".json", ".geojson", ".parquet", ".zip", ".csv"}:
                continue
            logical = "cache/runtime/" + path.relative_to(root / "data/cache").as_posix()
            if folder == "financial_analysis_sources":
                logical += ".bin"
            item = {"path": logical, "sha256": digest(path), "size": path.stat().st_size, "encoding": "identity"}
            validate_file(item)
            files.append(item); paths[logical] = path
    if not files:
        raise RunnerError("Geração vazia")
    return files, paths


def execute_claim(api, claim, *, processor=materialize_generation, source_root=ROOT, heartbeat_interval=30):
    job, base = claim["job"], claim.get("base")
    plan = validate_plan(job["params"])
    if job["kind"] != plan["kind"] or not re.fullmatch(r"[a-f0-9]{32}", job["id"]) or not re.fullmatch(r"[a-f0-9]{32}", job["lease_id"]):
        raise RunnerError("Contexto da reserva inválido")
    started = time.monotonic()
    timings = {}
    with Heartbeat(api, job, heartbeat_interval) as progress:
        try:
            with tempfile.TemporaryDirectory(prefix="tomaconta-shared-") as temporary:
                root = Path(temporary)
                seed_workspace(root, base, api, progress, source_root)
                timings["restoreSeconds"] = round(time.monotonic() - started, 3)
                progress.update(.15, "Fontes da geração ativa verificadas")
                generation_started = time.monotonic()
                report = processor(root, plan, progress)
                timings["generationSeconds"] = round(time.monotonic() - generation_started, 3)
                receipt_path = root / "data/cache/shared_runs" / (job["id"] + ".json")
                # Prior receipts remain in prior immutable revisions. The current
                # manifest carries its own receipt instead of growing per run.
                if receipt_path.parent.exists():
                    shutil.rmtree(receipt_path.parent)
                receipt_path.parent.mkdir(parents=True, exist_ok=True)
                receipt = {"schemaVersion": 1, "jobId": job["id"], "parent": job.get("base_revision"), "requested": plan,
                           "sourceCommit": os.environ.get("GITHUB_SHA"), "completedAt": datetime.now(timezone.utc).isoformat(), **report}
                receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, allow_nan=False, default=str, separators=(",", ":")), encoding="utf-8")
                files, paths = inventory(root)
                old = {f["sha256"]: f["size"] for f in (base or {}).get("files", [])}
                pending = list({f["sha256"]: f for f in files if old.get(f["sha256"]) != f["size"]}.values())
                completed, upload_lock = 0, threading.Lock()
                def upload(item):
                    nonlocal completed
                    progress.check()
                    content = paths[item["path"]].read_bytes()
                    if hashlib.sha256(content).hexdigest() != item["sha256"]:
                        raise RunnerError("Artefato mudou durante o envio")
                    api.request("PUT", f"/runner/blobs/{item['sha256']}?job={job['id']}", content,
                                headers={"X-Lease-Id": job["lease_id"], "Content-Length": str(item["size"]), "Content-Type": "application/octet-stream"})
                    with upload_lock:
                        completed += 1
                        progress.update(.84 + .09 * completed / max(1, len(pending)), f"Enviando geração: {completed}/{len(pending)} arquivos")
                progress.update(.84, "Enviando a geração validada")
                upload_started = time.monotonic()
                print(json.dumps({"phase": "upload", "job": job["id"], "uniqueBlobs": len(pending), "bytes": sum(f["size"] for f in pending), "concurrency": 6}), flush=True)
                with ThreadPoolExecutor(max_workers=6) as pool:
                    list(pool.map(upload, pending))
                timings["uploadSeconds"] = round(time.monotonic() - upload_started, 3)
                progress.check()
                source_files = [{"path": f["path"], "sha256": f["sha256"]} for f in files if
                                (f["path"].startswith("cache/bundled/") and f["path"].endswith(".parquet")) or
                                f["path"].startswith("cache/runtime/bank-network/")]
                summary = {"validation": {"complete": True, "failures": 0},
                           "generation": {"sourceCommit": os.environ.get("GITHUB_SHA", ""), "modelVersion": "statement-v6", "sourceFiles": source_files},
                           "coverage": report["coverage"], "changed": report["changed"], "requested": plan,
                           "receipt": {"path": "cache/runtime/shared_runs/" + receipt_path.name, "sha256": digest(receipt_path)}}
                progress.update(.94, "Preparando a publicação atômica")
                prepare_started = time.monotonic()
                prepared = api.action(job, "prepare", parent=job.get("base_revision"), files=files, summary=summary)
                timings["prepareSeconds"] = round(time.monotonic() - prepare_started, 3)
                progress.check()
                publish_started = time.monotonic()
                published = api.action(job, "publish", revision=prepared["revision"])
                if not published.get("published"):
                    raise RunnerError("A revisão não foi ativada")
                timings["publishSeconds"] = round(time.monotonic() - publish_started, 3)
                timings["totalSeconds"] = round(time.monotonic() - started, 3)
                return {"status": "published", "job": job["id"], "revision": published["revision"], "files": len(files), "uploaded": len(pending), "coverage": report["coverage"], "timings": timings}
        except Exception as exc:
            report = exc.report if isinstance(exc, NeedsReview) else {}
            if not getattr(api, "denied", False):
                try:
                    api.action(job, "fail", error=str(exc)[:2000], needsReview=isinstance(exc, NeedsReview), result=report)
                except Exception:
                    pass  # Lease expiration still preserves the current generation.
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pending-only", action="store_true")
    parser.add_argument("--identity-only", action="store_true", help="Diagnóstico público das claims OIDC; não chama a API nem coleta dados")
    parser.add_argument("--seed", action="store_true", help="Bootstrap manual, aceito pelo servidor apenas sem revisão ativa")
    args = parser.parse_args(argv)
    check_github_context()
    if args.identity_only:
        if args.seed or args.pending_only:
            raise RunnerError("Use --identity-only sem operações de atualização")
        OidcIdentity().bearer()
        print(json.dumps({"status": "identity_only", "apiCalled": False}))
        return 0
    api = SharedAPI()
    if args.seed:
        if os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
            raise RunnerError("Bootstrap exige acionamento manual")
        api.request("POST", "/runner/seed", {"kind": "bootstrap"})
    if args.pending_only:
        pending = bool(api.request("GET", "/runner/pending").get("pending"))
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                output.write("pending=" + str(pending).lower() + "\n")
        print(json.dumps({"pending": pending}))
        return 0
    api.enable_pool()
    try:
        claim = api.request("POST", "/runner/claim", {})
        if not claim.get("job"):
            print(json.dumps({"status": "idle", "message": "Sem atualização solicitada"}))
            return 0
        result = execute_claim(api, claim)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    finally:
        api.close_pool()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)[:2000]}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
