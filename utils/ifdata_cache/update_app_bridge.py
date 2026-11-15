"""Opt-in external update client, preserving the app's existing status formats.

No worker is started here. Authentication tokens stay in the HTTP client and
never enter the immutable update plan, a checkpoint or Streamlit job state.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import os
import time
from typing import Mapping

from .durable_jobs import validate_job_spec


class ExternalUpdateConfigurationError(ValueError):
    pass


def build_external_spec(cache_type, periods, mode, options=None, *, publish=False):
    normalized = {}
    for key, value in dict(options or {}).items():
        if isinstance(value, datetime):
            value = value.date().isoformat()
        elif isinstance(value, date):
            value = value.isoformat()
        normalized[key] = value
    return validate_job_spec({"cache_type": cache_type, "periods": list(periods or []),
                              "mode": mode, "options": normalized,
                              "publish": publish, "materialize": True})


def _timestamp(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    return str(value or "")


def _period_label(period):
    text = str(period or "")
    return f"{text[4:6]}/{text[:4]}" if len(text) == 6 and text.isdigit() else text


def _units(job):
    periods = list(job["spec"].get("periods") or [])
    run = job.get("run") or {}
    if run:
        # Opaque native materialization units are not calendar competencies.
        if run.get("periods") == ["materialization"]:
            confirmed = "materialization" in set(run.get("persisted_periods") or [])
            return periods, list(periods) if confirmed else [], [] if confirmed else list(periods)
        persisted = [period for period in periods if period in set(run.get("persisted_periods") or [])]
        pending = [period for period in periods if period in set(run.get("pending_periods") or [])]
        if run.get("status") == "failed" and not pending:
            pending = list(periods)
        return periods, persisted, pending
    result = job.get("result") or {}
    if "pending_periods" in result:
        pending = [period for period in periods if period in set(result["pending_periods"])]
        persisted = [period for period in periods if period not in pending]
    elif job["status"] == "succeeded":
        persisted, pending = list(periods), []
    else:
        persisted, pending = [], list(periods)
    return periods, persisted, pending


def job_status_view(job, *, now=None):
    if not job:
        return {}
    run = job.get("run") or {}
    result = job.get("result") or {}
    phase = run.get("status")
    status = job["status"]
    periods, persisted, _ = _units(job)
    progress = len(persisted) / len(periods) if periods else 0.0
    if status == "queued":
        current = "aguardando executor"
    elif status == "running":
        expired = (job.get("lease_expires_at") is not None
                   and job["lease_expires_at"] <= (time.time() if now is None else now))
        if expired:
            current = "aguardando retomada pelo executor"
        elif phase in {"saved", "validating"}:
            current, progress = "dados salvos; recalculando dependências", 1.0
        elif phase in {"ready_to_publish", "publishing", "published"}:
            current, progress = "publicando pacote consistente", 1.0
        elif run.get("current_period"):
            current = "extraindo " + _period_label(run["current_period"])
        else:
            current = "executando atualização"
    elif status == "succeeded":
        current, progress = "concluído", 1.0
    elif status == "partial":
        error = job.get("error") or run.get("error")
        current = "parcial: " + str(error) if error else "parcial"
    elif status == "cancelled":
        current = "cancelado"
    else:
        current = "erro: " + str(job.get("error") or run.get("error") or "atualização incompleta")
    publication = run.get("publication") or {}
    publish_message = publication.get("message")
    if status == "succeeded" and result.get("revision_id"):
        publish_message = ("Revisão publicada." if result.get("activated")
                           else "Revisão validada e disponível para publicação.")
    return {"job_id": job["job_id"], "run_id": job["execution_run_id"],
            "running": status in {"queued", "running"}, "progress": progress,
            "current": current, "cache_tipo": job["spec"]["cache_type"],
            "last_update": _timestamp(job.get("updated_at")), "publish_message": publish_message,
            "status": status, "total": len(periods)}


def job_checkpoint_view(job):
    if not job or job["status"] not in {"partial", "failed"}:
        return {}
    periods, persisted, pending = _units(job)
    spec = job["spec"]
    return {"job_id": job["job_id"], "run_id": job["execution_run_id"],
            "cache_tipo": spec["cache_type"], "periodos": periods,
            "concluidos": persisted, "pendentes": pending, "modo": spec["mode"],
            "options": dict(spec.get("options") or {}), "timestamp": _timestamp(job.get("updated_at"))}


class ExternalUpdateBridge:
    def __init__(self, client):
        self.client = client

    def submit(self, cache_type, periods, mode, options=None, *, publish=False, idempotency_key):
        spec = build_external_spec(cache_type, periods, mode, options, publish=publish)
        return self.client.submit(spec, idempotency_key)

    def latest(self, cache_type=None):
        jobs = self.client.list()
        if not isinstance(jobs, list):
            raise ExternalUpdateConfigurationError("O serviço retornou uma lista de trabalhos inválida.")
        selected = [job for job in jobs if cache_type is None or job["spec"]["cache_type"] == cache_type]
        if not selected:
            return None
        latest = max(selected, key=lambda job: job.get("created_at", 0))
        return self.client.get(latest["job_id"]) if latest.get("summary") is True else latest

    def current_status(self, cache_type=None):
        return job_status_view(self.latest(cache_type))

    def checkpoint(self, cache_type=None):
        return job_checkpoint_view(self.latest(cache_type))

    def get(self, job_id):
        return self.client.get(job_id)

    def retry(self, job_id):
        return self.client.retry(job_id)

    def cancel(self, job_id):
        return self.client.cancel(job_id)

    def publish(self, job_id):
        return self.client.publish(job_id)


def external_bridge_from_env(environment: Mapping | None = None, *, client_factory=None):
    environment = os.environ if environment is None else environment
    url = str(environment.get("TOMACONTA_UPDATE_API_URL") or "").strip()
    token = str(environment.get("TOMACONTA_UPDATE_API_TOKEN") or "").strip()
    if not url and not token:
        return None
    if not url or not token:
        raise ExternalUpdateConfigurationError("Configure URL e token próprios do serviço de atualização externo.")
    if client_factory is None:
        from .update_api import UpdateAPIClient
        client_factory = UpdateAPIClient
    return ExternalUpdateBridge(client_factory(url, token, timeout=30))


bridge_from_env = external_bridge_from_env
