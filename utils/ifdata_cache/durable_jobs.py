"""Persistent job queue and a worker run explicitly outside the Streamlit process.

SQLite owns queue transitions. The shared execution lock owns data mutation;
callers must use the same lock for every worker targeting the same working root.
Authentication belongs to the backend that submits jobs, never to job payloads.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import socket
import sqlite3
import threading
import time
from typing import Callable, Mapping
from uuid import uuid4

from .update_state import UpdateBusyError, UpdateStateError, _safe_json, mutation_lock


JOB_STATUSES = frozenset({"queued", "running", "succeeded", "partial", "failed", "cancelled"})
RESULT_STATUSES = frozenset({"succeeded", "partial", "failed"})
_JOB_ID = re.compile(r"^[a-f0-9]{32}$")
_PERIOD = re.compile(r"^(?:19|20)\d{2}(?:0[1-9]|1[012])$")
_SPEC_FIELDS = frozenset({"cache_type", "periods", "mode", "options", "publish", "materialize", "label"})
_CACHE_TYPES = frozenset({
    "principal", "principal_individual", "ativo", "passivo", "capital", "dre", "dre_individual",
    "carteira_pf", "carteira_pj", "carteira_instrumentos", "bloprudencial", "balancetes",
    "cosif_4010", "mercado_credito_sgs", "scr_data", "taxas_juros", "taxas_juros_historico",
    "spb_meios_pagamento",
})
_QUARTERLY = frozenset({
    "principal", "principal_individual", "ativo", "passivo", "capital", "dre", "dre_individual",
    "carteira_pf", "carteira_pj", "carteira_instrumentos", "balancetes",
})
_MONTHLY = frozenset({"cosif_4010", "bloprudencial"})
_DATE_WINDOWS = frozenset({"taxas_juros", "taxas_juros_historico", "mercado_credito_sgs"})
_SOURCE_OPTIONS = {
    **{name: frozenset({"batch_size", "intervalo_save"}) for name in _QUARTERLY},
    "bloprudencial": frozenset({"batch_size", "intervalo_save", "force_refresh"}),
    "cosif_4010": frozenset(),
    "taxas_juros": frozenset({"start", "end"}),
    "taxas_juros_historico": frozenset({"start", "end", "max_windows", "reprocess_tail"}),
    "mercado_credito_sgs": frozenset({"start", "end"}),
    "spb_meios_pagamento": frozenset({"datasets"}),
    "scr_data": frozenset({"years"}),
}


class JobValidationError(ValueError):
    pass


class JobStateError(RuntimeError):
    pass


class JobLeaseError(JobStateError):
    """The claim expired or another worker now owns the job."""


def _json(value) -> str:
    try:
        return json.dumps(_safe_json(value), ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, UpdateStateError) as exc:
        raise JobValidationError("O trabalho deve conter somente dados JSON e nenhuma credencial.") from exc


def _identity(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 200 or any(ord(c) < 32 for c in value):
        raise JobValidationError(f"{label} inválido.")
    return value.strip()


def validate_job_spec(spec: Mapping) -> dict:
    if not isinstance(spec, Mapping) or set(spec) - _SPEC_FIELDS:
        raise JobValidationError("Campos do plano de atualização inválidos.")
    cache_type = spec.get("cache_type")
    if not isinstance(cache_type, str) or cache_type not in _CACHE_TYPES:
        raise JobValidationError("Fonte de atualização inválida.")
    mode = spec.get("mode", "incremental")
    if not isinstance(mode, str) or mode not in {"incremental", "overwrite", "rebuild"}:
        raise JobValidationError("Modo de atualização inválido.")
    periods = spec.get("periods", [])
    if (not isinstance(periods, (list, tuple)) or len(periods) > 2000
            or any(not isinstance(p, str) or not _PERIOD.fullmatch(p) for p in periods)
            or len(set(periods)) != len(periods)):
        raise JobValidationError("Competências devem ser únicas e usar YYYYMM.")
    if cache_type in _QUARTERLY and (not periods or any(p[-2:] not in {"03", "06", "09", "12"} for p in periods)):
        raise JobValidationError("A fonte trimestral exige competências de março, junho, setembro ou dezembro.")
    if cache_type in _MONTHLY and not periods:
        raise JobValidationError("A fonte mensal exige ao menos uma competência YYYYMM.")
    if cache_type not in _QUARTERLY | _MONTHLY and periods:
        raise JobValidationError("Esta fonte usa uma janela, anos ou datasets; não informe competências.")
    options = spec.get("options", {})
    if not isinstance(options, Mapping) or set(options) - _SOURCE_OPTIONS[cache_type]:
        raise JobValidationError("Opções incompatíveis com a fonte de atualização.")
    options = json.loads(_json(options))
    for key in ("batch_size", "intervalo_save", "max_windows", "reprocess_tail"):
        if key in options:
            value = options[key]
            lower = 0 if key == "reprocess_tail" else 1
            upper = 10000 if key == "max_windows" else 1000
            if type(value) is not int or not lower <= value <= upper:
                raise JobValidationError(f"Opção {key} inválida.")
    if cache_type in _DATE_WINDOWS and not all(options.get(key) for key in ("start", "end")):
        raise JobValidationError("Informe início e fim da janela para congelar o plano.")
    for key in ("start", "end"):
        if key in options and options[key] is not None:
            try:
                value = options[key]
                if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                    raise ValueError
            except ValueError as exc:
                raise JobValidationError(f"Data {key} inválida; use YYYY-MM-DD.") from exc
    if options.get("start") and options.get("end") and options["start"] > options["end"]:
        raise JobValidationError("O início da janela deve anteceder o fim.")
    if cache_type == "spb_meios_pagamento":
        from .spb_meios_pagamento import DATASETS
        available = [dataset.key for dataset in DATASETS]
        selection = options.get("datasets")
        if selection is None or selection == []:
            options["datasets"] = list(available)
        elif (not isinstance(selection, list) or len(selection) > 30
              or any(not isinstance(item, str) or item not in available for item in selection)
              or len(set(selection)) != len(selection)):
            raise JobValidationError("Seleção datasets inválida.")
    if cache_type == "scr_data" and not options.get("years"):
        raise JobValidationError("Informe os anos do SCR.data para congelar o plano.")
    if "years" in options and (not isinstance(options["years"], list) or not options["years"]
                                or any(type(year) is not int or not 2010 <= year <= 2100 for year in options["years"])
                                or len(set(options["years"])) != len(options["years"])):
        raise JobValidationError("Seleção de anos inválida.")
    for key in ("publish", "materialize"):
        if key in spec and type(spec[key]) is not bool:
            raise JobValidationError(f"Opção {key} inválida.")
    if "force_refresh" in options and type(options["force_refresh"]) is not bool:
        raise JobValidationError("Opção force_refresh inválida.")
    normalized = {"cache_type": cache_type, "periods": list(periods), "mode": mode,
                  "options": options, "publish": spec.get("publish", True),
                  "materialize": spec.get("materialize", True)}
    if "label" in spec:
        normalized["label"] = _identity(spec["label"], "Rótulo")
    _json(normalized)
    return normalized


def _error_text(error):
    if error is None:
        return None
    text = str(error)[:4000]
    return re.sub(r"(?i)(token|password|secret|senha|authorization|credential)\s*[:=]\s*\S+",
                  r"\1=<redacted>", text)


class DurableJobQueue:
    def __init__(self, base_dir: Path | str, *, lease_seconds: float = 90, clock: Callable | None = None):
        if (type(lease_seconds) not in (int, float) or not math.isfinite(lease_seconds)
                or not 1 <= lease_seconds <= 3600):
            raise JobValidationError("Lease deve ficar entre 1 e 3600 segundos.")
        self.base_dir = Path(base_dir).resolve()
        self.path = self.base_dir / "data" / "cache" / "update_jobs.sqlite3"
        self.lease_seconds = float(lease_seconds)
        self.clock = clock or time.time
        if not callable(self.clock):
            raise JobValidationError("Relógio da fila inválido.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise JobStateError("Versão da fila incompatível; arquivo preservado.")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY, execution_run_id TEXT NOT NULL UNIQUE,
                subject TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                spec TEXT NOT NULL, spec_sha256 TEXT NOT NULL,
                status TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, lease_owner TEXT, claim_token TEXT,
                lease_expires_at REAL, heartbeat_at REAL, result TEXT, error TEXT,
                context TEXT NOT NULL DEFAULT '{}', UNIQUE(subject, idempotency_key)
            )""")
            connection.execute("PRAGMA user_version=1")

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA synchronous=FULL")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self):
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise

    @staticmethod
    def _job(row, *, include_claim=False):
        if row is None:
            return None
        job = dict(row)
        for field in ("spec", "result", "context"):
            job[field] = json.loads(job[field]) if job[field] is not None else None
        if job["status"] not in JOB_STATUSES or hashlib.sha256(_json(job["spec"]).encode()).hexdigest() != job["spec_sha256"]:
            raise JobStateError("Plano da fila ilegível ou divergente; arquivo preservado.")
        if not include_claim:
            job.pop("claim_token", None)
        job["schema_version"] = 1
        return job

    @staticmethod
    def _job_id(job_id):
        if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
            raise JobValidationError("Identificador de trabalho inválido.")
        return job_id

    def submit(self, spec, subject: str, idempotency_key: str) -> dict:
        subject = _identity(subject, "Identidade")
        idempotency_key = _identity(idempotency_key, "Chave de idempotência")
        normalized = validate_job_spec(spec)
        serialized = _json(normalized)
        digest = hashlib.sha256(serialized.encode()).hexdigest()
        with self._transaction() as connection:
            previous = connection.execute("SELECT * FROM jobs WHERE subject=? AND idempotency_key=?",
                                          (subject, idempotency_key)).fetchone()
            if previous:
                if previous["spec_sha256"] != digest:
                    raise JobStateError("A chave de idempotência já pertence a outro plano.")
                return self._job(previous)
            job_id, run_id, now = uuid4().hex, uuid4().hex, self.clock()
            connection.execute("""INSERT INTO jobs
                (job_id,execution_run_id,subject,idempotency_key,spec,spec_sha256,status,created_at,updated_at)
                VALUES (?,?,?,?,?,?,'queued',?,?)""",
                (job_id, run_id, subject, idempotency_key, serialized, digest, now, now))
            return self._job(connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone())

    def get(self, job_id: str) -> dict | None:
        with self._connection() as connection:
            return self._job(connection.execute("SELECT * FROM jobs WHERE job_id=?", (self._job_id(job_id),)).fetchone())

    def list(self, *, subject: str | None = None, limit: int = 100) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise JobValidationError("Limite da consulta inválido.")
        with self._connection() as connection:
            if subject is not None:
                rows = connection.execute("SELECT * FROM jobs WHERE subject=? ORDER BY created_at DESC,rowid DESC LIMIT ?",
                                          (_identity(subject, "Identidade"), limit))
            else:
                rows = connection.execute("SELECT * FROM jobs ORDER BY created_at DESC,rowid DESC LIMIT ?", (limit,))
            return [self._job(row) for row in rows]

    def claim(self, worker_id: str, *, wait_for_running: bool = False) -> dict | None:
        worker_id = _identity(worker_id, "Executor")
        if type(wait_for_running) is not bool:
            raise JobValidationError("Opção de execução serial inválida.")
        with self._transaction() as connection:
            now = self.clock()
            if wait_for_running and connection.execute("""SELECT 1 FROM jobs
                    WHERE status='running' AND lease_expires_at>? LIMIT 1""", (now,)).fetchone():
                # The serial worker waits for an interrupted job's claim before
                # processing later intentions against another official parent.
                return None
            row = connection.execute("""SELECT * FROM jobs
                WHERE status='queued' OR (status='running' AND lease_expires_at<=?)
                ORDER BY created_at,rowid LIMIT 1""", (now,)).fetchone()
            if not row:
                return None
            self._job(row)
            token = uuid4().hex
            connection.execute("""UPDATE jobs SET status='running',attempts=attempts+1,
                lease_owner=?,claim_token=?,lease_expires_at=?,heartbeat_at=?,updated_at=?,result=NULL,error=NULL
                WHERE job_id=?""", (worker_id, token, now + self.lease_seconds, now, now, row["job_id"]))
            return self._job(connection.execute("SELECT * FROM jobs WHERE job_id=?", (row["job_id"],)).fetchone(), include_claim=True)

    def _assert_claim(self, row, worker_id, claim_token, now):
        if (row is None or row["status"] != "running" or row["lease_owner"] != worker_id
                or row["claim_token"] != claim_token or row["lease_expires_at"] <= now):
            raise JobLeaseError("A reserva do trabalho expirou ou pertence a outro executor.")

    def ensure_claim(self, job_id, worker_id, claim_token) -> None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (self._job_id(job_id),)).fetchone()
            self._assert_claim(row, worker_id, claim_token, self.clock())

    def heartbeat(self, job_id, worker_id, claim_token) -> bool:
        with self._transaction() as connection:
            now = self.clock()
            cursor = connection.execute("""UPDATE jobs SET heartbeat_at=?,lease_expires_at=?,updated_at=?
                WHERE job_id=? AND status='running' AND lease_owner=? AND claim_token=? AND lease_expires_at>?""",
                (now, now + self.lease_seconds, now, self._job_id(job_id), worker_id, claim_token, now))
            return cursor.rowcount == 1

    def update_context(self, job_id, worker_id, claim_token, context: Mapping) -> dict:
        if not isinstance(context, Mapping):
            raise JobValidationError("Contexto do trabalho inválido.")
        incoming = json.loads(_json(context))
        with self._transaction() as connection:
            now = self.clock()
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (self._job_id(job_id),)).fetchone()
            self._assert_claim(row, worker_id, claim_token, now)
            current = json.loads(row["context"])
            current.update(incoming)
            connection.execute("UPDATE jobs SET context=?,updated_at=? WHERE job_id=?", (_json(current), now, job_id))
            return self._job(connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone())

    def finish(self, job_id, worker_id, claim_token, status, result=None, error=None) -> dict:
        if not isinstance(status, str) or status not in RESULT_STATUSES:
            raise JobValidationError("Resultado do trabalho inválido.")
        serialized = _json(result) if result is not None else None
        if serialized is not None and len(serialized) > 1024 * 1024:
            raise JobValidationError("Resultado muito grande; grave apenas o comprovante, sem os dados da base.")
        with self._transaction() as connection:
            now = self.clock()
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (self._job_id(job_id),)).fetchone()
            self._assert_claim(row, worker_id, claim_token, now)
            connection.execute("""UPDATE jobs SET status=?,result=?,error=?,updated_at=?,
                claim_token=NULL,lease_owner=NULL,lease_expires_at=NULL WHERE job_id=?""",
                (status, serialized, _error_text(error), now, job_id))
            return self._job(connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone())

    def retry(self, job_id, *, subject=None) -> dict:
        with self._transaction() as connection:
            now = self.clock()
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (self._job_id(job_id),)).fetchone()
            if row is None or (subject is not None and row["subject"] != subject):
                raise JobStateError("Trabalho inexistente para esta identidade.")
            if row["status"] == "queued":
                return self._job(row)
            if row["status"] not in {"partial", "failed", "cancelled"} and not (
                    row["status"] == "running" and row["lease_expires_at"] <= now):
                raise JobStateError("O trabalho concluído ou em execução não pode ser reenfileirado.")
            connection.execute("""UPDATE jobs SET status='queued',updated_at=?,claim_token=NULL,
                lease_owner=NULL,lease_expires_at=NULL,error=NULL WHERE job_id=?""", (now, job_id))
            return self._job(connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone())

    def cancel(self, job_id, *, subject=None) -> dict:
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (self._job_id(job_id),)).fetchone()
            if row is None or (subject is not None and row["subject"] != subject):
                raise JobStateError("Trabalho inexistente para esta identidade.")
            if row["status"] == "cancelled":
                return self._job(row)
            if row["status"] != "queued":
                raise JobStateError("Somente um trabalho aguardando execução pode ser cancelado.")
            connection.execute("UPDATE jobs SET status='cancelled',updated_at=? WHERE job_id=?", (self.clock(), job_id))
            return self._job(connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone())


def run_worker(queue: DurableJobQueue, executor: Callable, *, worker_id=None, once=False,
               poll_interval=2.0, execution_lock: Callable | None = None, stop_event=None):
    """Run from an external process; the app only submits/reads queue entries.

    The executor returns {status, result, error}. Every filesystem worker must
    use the same execution_lock factory. Heartbeat is independent of long HTTP
    requests/calculations and runs only inside this explicitly started worker.
    """
    worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex}"
    _identity(worker_id, "Executor")
    if not 0.01 <= poll_interval <= 60:
        raise JobValidationError("Intervalo de consulta inválido.")
    stop = stop_event or threading.Event()
    lock = execution_lock or (lambda: mutation_lock(queue.base_dir, owner={"worker_id": worker_id}))
    while not stop.is_set():
        try:
            with lock():
                job = queue.claim(worker_id, wait_for_running=True)
                if job is not None:
                    heartbeat_stop = threading.Event()
                    lease_lost = threading.Event()

                    def renew():
                        while not heartbeat_stop.wait(max(.1, queue.lease_seconds / 3)):
                            try:
                                if not queue.heartbeat(job["job_id"], worker_id, job["claim_token"]):
                                    lease_lost.set()
                                    return
                            except Exception:
                                lease_lost.set()
                                return

                    heartbeat = threading.Thread(target=renew, name="update-worker-heartbeat", daemon=True)
                    heartbeat.start()
                    try:
                        outcome = executor(job)
                        if not isinstance(outcome, Mapping):
                            raise JobValidationError("Executor não retornou um comprovante estruturado.")
                        if lease_lost.is_set():
                            raise JobLeaseError("Executor perdeu sua reserva antes da confirmação final.")
                        finished = queue.finish(job["job_id"], worker_id, job["claim_token"],
                                                outcome.get("status"), result=outcome.get("result"),
                                                error=outcome.get("error"))
                    except JobLeaseError:
                        finished = queue.get(job["job_id"])
                    except Exception as exc:
                        try:
                            finished = queue.finish(job["job_id"], worker_id, job["claim_token"], "failed", error=exc)
                        except JobLeaseError:
                            finished = queue.get(job["job_id"])
                    finally:
                        heartbeat_stop.set()
                        heartbeat.join(timeout=6)
                    if once:
                        return finished
                elif once:
                    return None
        except UpdateBusyError:
            if once:
                return None
        stop.wait(poll_interval)
    return None
