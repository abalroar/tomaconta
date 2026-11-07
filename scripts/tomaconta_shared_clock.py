#!/usr/bin/env python3
"""Wake the existing executor using the clock job's ephemeral GITHUB_TOKEN.

This independent native schedule only reads the public queue and the executor's
active workflow runs before at most one workflow_dispatch. The original runner
retains OIDC, lease decisions, collection, validation and publication. No token
or response body is printed or persisted. There are no network retries.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPOSITORY = "abalroar/tomaconta"
REPOSITORY_ID = "1141557164"
OWNER_ID = "255978345"
CLOCK_WORKFLOW = REPOSITORY + "/.github/workflows/tomaconta-shared-clock.yml@refs/heads/main"
EXECUTOR_WORKFLOW_ID = 410128602
GH_ROOT = "https://api.github.com/repos/" + REPOSITORY
JOBS_URL = "https://matheusprat.es/tomaconta/api/shared/jobs"
RUNS_URL = GH_ROOT + f"/actions/workflows/{EXECUTOR_WORKFLOW_ID}/runs"
DISPATCH_URL = GH_ROOT + "/actions/workflows/tomaconta-shared.yml/dispatches"
USER_AGENT = "TomaContaSharedRunner/1.0 (+https://github.com/abalroar/tomaconta)"
ACTIVE_RUN_STATUSES = ("queued", "in_progress", "waiting", "requested", "pending")
JOB_STATUSES = {"queued", "running", "succeeded", "failed", "needs_review"}
MAX_JOBS = 40  # GET /jobs server limit.
MAX_PENDING_JOBS = 4  # Server MAX_PENDING includes queued and running jobs.
MAX_RESPONSE_BYTES = 4_000_000
TIMEOUT_SECONDS = 15


class ClockError(RuntimeError):
    """A sanitized failure that must not trigger a dispatch or a retry."""


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def check_context(env):
    required = {
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REPOSITORY_ID": REPOSITORY_ID,
        "GITHUB_REPOSITORY_OWNER_ID": OWNER_ID,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_WORKFLOW_REF": CLOCK_WORKFLOW,
        "GITHUB_EVENT_NAME": "schedule",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_API_URL": "https://api.github.com",
        "TOMACONTA_SHARED_ENABLED": "true",
        "TOMACONTA_REPOSITORY_PRIVATE": "false",
    }
    if any(env.get(key) != value for key, value in required.items()):
        raise ClockError("Contexto do relógio não autorizado")
    if not re.fullmatch(r"[a-f0-9]{40}", env.get("GITHUB_SHA", "")):
        raise ClockError("Commit do relógio ausente")
    run_id = env.get("GITHUB_RUN_ID", "")
    if not re.fullmatch(r"\d{1,25}", run_id):
        raise ClockError("Execução do relógio ausente")
    token = env.get("GITHUB_TOKEN", "")
    if not token or len(token) > 4096 or any(ord(char) < 33 or ord(char) > 126 for char in token):
        raise ClockError("GITHUB_TOKEN efêmero indisponível")
    return run_id, token


class Client:
    def __init__(self, token, *, opener=None):
        self._token = token
        self._opener = opener or build_opener(NoRedirects())

    def request(self, method, url, *, data=None):
        is_github = url.startswith(GH_ROOT + "/")
        if not is_github and (url != JOBS_URL or method != "GET"):
            raise ClockError("Destino do relógio não autorizado")
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if is_github:
            headers.update({"Authorization": "Bearer " + self._token,
                            "Accept": "application/vnd.github+json",
                            "X-GitHub-Api-Version": "2022-11-28"})
        encoded = None
        if data is not None:
            encoded = json.dumps(data, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=encoded, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                status = response.status
                if status not in ({200, 204} if method == "POST" else {200}):
                    raise ClockError("Status HTTP inesperado no relógio")
                payload = response.read(MAX_RESPONSE_BYTES + 1)
                if len(payload) > MAX_RESPONSE_BYTES:
                    raise ClockError("Resposta excedeu o limite do relógio")
                if status == 204:
                    if payload:
                        raise ClockError("Resposta HTTP 204 inválida")
                    return None
                if not response.headers.get("Content-Type", "").lower().startswith("application/json"):
                    raise ClockError("Resposta do relógio não é JSON")
                value = json.loads(payload)
                if not isinstance(value, dict):
                    raise ClockError("Resposta JSON inválida no relógio")
                return value
        except HTTPError as error:
            # Never print the URL, token, response body, or server error text.
            raise ClockError(f"API do relógio respondeu HTTP {error.code}") from None
        except (URLError, OSError, ValueError, UnicodeError):
            raise ClockError("Falha de transporte ou JSON no relógio") from None


def pending_jobs(packet):
    jobs = packet.get("jobs") if isinstance(packet, dict) else None
    if not isinstance(jobs, list) or len(jobs) > MAX_JOBS:
        raise ClockError("Lista pública de pedidos inválida")
    ids, queued, running = set(), [], []
    for job in jobs:
        if (not isinstance(job, dict) or not isinstance(job.get("id"), str)
                or not re.fullmatch(r"[a-f0-9]{32}", job["id"])):
            raise ClockError("Identificação pública de pedido inválida")
        job_id, status = job["id"], job.get("status")
        if job_id in ids or not isinstance(status, str) or status not in JOB_STATUSES:
            raise ClockError("Estado público de pedido inválido")
        ids.add(job_id)
        if status == "queued":
            queued.append(job_id)
        elif status == "running":
            running.append(job_id)
    if len(queued) + len(running) > MAX_PENDING_JOBS or len(running) > 1:
        raise ClockError("Fila pública excedeu os limites do servidor")
    return queued, running


def active_run(packet, status):
    runs = packet.get("workflow_runs") if isinstance(packet, dict) else None
    total = packet.get("total_count") if isinstance(packet, dict) else None
    if type(total) is not int or total < 0 or not isinstance(runs, list) or len(runs) != min(total, 1):
        raise ClockError("Lista de execuções do GitHub inválida")
    if not runs:
        return None
    run = runs[0]
    if (not isinstance(run, dict) or run.get("workflow_id") != EXECUTOR_WORKFLOW_ID
            or run.get("head_branch") != "main" or run.get("status") != status
            or not re.fullmatch(r"\d{1,25}", str(run.get("id", "")))):
        raise ClockError("Execução do GitHub fora do contexto esperado")
    return str(run["id"])


def run_clock(*, env=None, client_factory=Client, now=None):
    env = os.environ if env is None else env
    clock_run_id, token = check_context(env)
    api = client_factory(token)
    queued, running = pending_jobs(api.request("GET", JOBS_URL))
    receipt = {"clockRunId": clock_run_id, "clockEvent": "schedule",
               "utc": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
               "queuedJobIds": queued, "runningJobIds": running}
    if not queued and not running:
        return {**receipt, "outcome": "empty"}
    # Filter each active state server-side: a long completed history cannot
    # conceal an older active run. No arbitrary age or lease inference is used.
    for status in ACTIVE_RUN_STATUSES:
        url = RUNS_URL + "?" + urlencode({"branch": "main", "status": status, "per_page": 1})
        run_id = active_run(api.request("GET", url), status)
        if run_id is not None:
            return {**receipt, "outcome": "executor_active", "executorRunId": run_id, "executorStatus": status}
    # A running public job may have an expired lease. The original executor's
    # authenticated /runner/pending and /claim decide whether it can resume.
    # One attempt only; a timeout here can have an unknown dispatch outcome.
    api.request("POST", DISPATCH_URL, data={"ref": "main"})
    return {**receipt, "outcome": "dispatched", "executorEvent": "workflow_dispatch"}


def main():
    try:
        print(json.dumps(run_clock(), ensure_ascii=False, sort_keys=True))
        return 0
    except ClockError as error:
        print(json.dumps({"outcome": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except Exception:
        # Unexpected exceptions must not leak a credential-bearing request.
        print('{"outcome":"failed","error":"Falha inesperada no relógio"}', file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
