"""Estado de atualizações e exclusão de mutações administrativas no mesmo runtime.

A trava do SO é a autoridade sobre execução ativa. Os arquivos JSON são um
comprovante recuperável e não autorizam liberar uma operação ainda em andamento.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timezone
import fcntl
from functools import wraps
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any, Iterator, Mapping
from uuid import uuid4


SCHEMA_VERSION = 1
RUN_STATUSES = frozenset({
    "prepared", "extracting", "partial", "failed", "saved", "validating",
    "ready_to_publish", "publishing", "publish_failed", "published", "superseded",
})
_IMMUTABLE_FIELDS = ("schema_version", "run_id", "cache_type", "periods", "mode", "options", "created_at")
_THREAD_LOCKS = threading.local()
_SENSITIVE_KEYS = re.compile(r"(?:token|password|secret|senha|authorization|credential)", re.I)
_RUN_ID = re.compile(r"^[a-f0-9]{32}$")


class UpdateBusyError(RuntimeError):
    """Uma atualização administrativa já possui a trava deste runtime."""


class UpdateStateError(RuntimeError):
    """O comprovante não pôde ser validado ou persistido com segurança."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if _SENSITIVE_KEYS.search(str(key)):
                raise UpdateStateError("Credenciais não podem ser gravadas no comprovante da atualização.")
            result[str(key)] = _safe_json(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_json(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise UpdateStateError(f"Valor não serializável no comprovante: {type(value).__name__}")


def _lock_path(base_dir: Path | str) -> Path:
    return Path(base_dir).resolve() / "data" / "cache" / ".update.lock"


def _owned_locks() -> dict:
    if not hasattr(_THREAD_LOCKS, "owned"):
        _THREAD_LOCKS.owned = {}
    return _THREAD_LOCKS.owned


@contextmanager
def mutation_lock(base_dir: Path | str, *, owner: Mapping | None = None) -> Iterator[None]:
    """Serializa leitura/merge/save, materialização e publicação administrativas.

    Reentrante na mesma thread, compartilhada entre sessões e processos Linux/
    macOS que usam o mesmo diretório. A aquisição falha imediatamente se ocupada.
    O arquivo da trava permanece no disco: removê-lo criaria uma segunda trava.
    """
    path = _lock_path(base_dir)
    key = (os.getpid(), str(path))
    owned = _owned_locks()
    if key in owned:
        yield
        return
    safe_owner = {k: v for k, v in dict(owner or {}).items() if k in {"run_id", "cache_type", "label"}}
    safe_owner = _safe_json(safe_owner)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise UpdateBusyError("Já existe uma atualização em andamento neste ambiente. Aguarde sua conclusão.") from exc
        owned[key] = handle
        try:
            payload = {**safe_owner, "pid": os.getpid(), "thread_id": threading.get_ident(), "started_at": _now()}
            handle.seek(0)
            handle.truncate()
            json.dump(payload, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
            yield
        finally:
            owned.pop(key, None)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)



def locked_cache_update(operation):
    """Protege o ciclo de leitura, merge e persistência dos adaptadores nativos."""
    @wraps(operation)
    def wrapped(self, *args, **kwargs):
        from .base import CacheResult

        try:
            with mutation_lock(self.base_dir, owner={"cache_type": self.config.nome}):
                if hasattr(self, "_recover_local_transaction"):
                    self._recover_local_transaction()
                return operation(self, *args, **kwargs)
        except UpdateBusyError as exc:
            return CacheResult(sucesso=False, mensagem=str(exc), fonte="nenhum")
    return wrapped


def is_update_running(base_dir: Path | str) -> bool:
    """Consulta a trava real; um registro antigo não significa processo vivo."""
    path = _lock_path(base_dir)
    if (os.getpid(), str(path)) in _owned_locks():
        return True
    try:
        handle = path.open("r", encoding="utf-8")
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise UpdateStateError("Não foi possível verificar a execução ativa.") from exc
    with handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return False


def get_update_lock_info(base_dir: Path | str) -> dict:
    if not is_update_running(base_dir):
        return {}
    try:
        payload = json.loads(_lock_path(base_dir).read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {"active": True}
    except (OSError, ValueError):
        return {"active": True}


def _write_json_atomic(path: Path, record: dict) -> None:
    safe_record = _safe_json(record)
    encoded = json.dumps(safe_record, ensure_ascii=False, indent=2, allow_nan=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def _cache_result_path(base_dir: Path | str, cache_name: str) -> Path:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", str(cache_name)):
        raise UpdateStateError("Fonte de atualização inválida.")
    return Path(base_dir).resolve() / "data" / "cache" / "update_results" / f"{cache_name}.json"


def load_cache_update_result(base_dir: Path | str, cache_name: str) -> dict:
    """Último resultado consolidado do manager, inclusive para publish-only CLI."""
    path = _cache_result_path(base_dir, cache_name)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (ValueError, OSError) as exc:
        raise UpdateStateError(f"Resultado de atualização de {cache_name} ilegível; publicação bloqueada.") from exc
    if not isinstance(payload, dict) or payload.get("cache_type") != cache_name:
        raise UpdateStateError(f"Resultado de atualização de {cache_name} inválido; publicação bloqueada.")
    _validate_cache_result(payload)
    return payload


def _validate_cache_result(payload: dict) -> None:
    requested = payload.get("requested_periods")
    persisted = payload.get("persisted_periods")
    pending = payload.get("pending_periods")
    failed = payload.get("failed_periods")
    if not all(isinstance(items, list) and all(isinstance(p, str) for p in items)
               and len(items) == len(set(items)) for items in (requested, persisted, pending)):
        raise UpdateStateError("Unidades do resultado inválidas; publicação bloqueada.")
    if (set(persisted) - set(requested) or pending != [p for p in requested if p not in persisted]
            or not isinstance(failed, dict) or set(failed) - set(pending)):
        raise UpdateStateError("Pendências do resultado inconsistentes; publicação bloqueada.")
    if payload.get("status") not in RUN_STATUSES:
        raise UpdateStateError("Etapa do resultado inválida; publicação bloqueada.")
    if payload["status"] == "saved" and (pending or failed or payload.get("checkpoint_error")
                                         or payload.get("persistence_error") or payload.get("callback_error")):
        raise UpdateStateError("Resultado possui falhas e não pode ser confirmado como concluído.")


def write_cache_update_result(base_dir: Path | str, cache_name: str, metadata: Mapping) -> dict:
    """Persiste o resultado agregado pelo manager sem inferir conclusão."""
    result = {**dict(metadata), "cache_type": cache_name, "updated_at": _now()}
    _validate_cache_result(result)
    with mutation_lock(base_dir, owner={"cache_type": cache_name}):
        try:
            _write_json_atomic(_cache_result_path(base_dir, cache_name), result)
        except (ValueError, OSError) as exc:
            raise UpdateStateError(f"Falha ao confirmar o resultado de {cache_name}; publicação bloqueada.") from exc
    return result


class UpdateRunStore:
    """Comprovantes locais por execução, sem depender de session_state."""

    def __init__(self, base_dir: Path | str):
        self.base_dir = Path(base_dir).resolve()
        self.root = self.base_dir / "data" / "cache" / "update_runs"

    def _path(self, run_id: str) -> Path:
        if not _RUN_ID.fullmatch(str(run_id)):
            raise UpdateStateError("Identificador de execução inválido.")
        return self.root / str(run_id) / "run.json"

    def create(self, cache_type: str, periods=None, mode: str = "incremental", options=None) -> dict:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", str(cache_type)):
            raise UpdateStateError("Fonte de atualização inválida.")
        if mode not in {"incremental", "overwrite", "rebuild"}:
            raise UpdateStateError("Modo de atualização inválido.")
        if periods is not None and (not isinstance(periods, (list, tuple)) or any(
            p is None or not str(p).strip() for p in periods
        )):
            raise UpdateStateError("Unidades da execução inválidas.")
        units = list(dict.fromkeys(str(p).strip() for p in (periods or [])))
        now = _now()
        record = {
            "schema_version": SCHEMA_VERSION, "run_id": uuid4().hex,
            "cache_type": cache_type, "periods": units, "mode": mode,
            "options": _safe_json(options or {}), "status": "prepared",
            "created_at": now, "updated_at": now, "requested_periods": units,
            "extracted_periods": [], "persisted_periods": [], "failed_periods": {},
            "pending_periods": units, "error": None, "publication": None,
        }
        return self.save(record)

    def load(self, run_id: str) -> dict:
        path = self._path(run_id)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise UpdateStateError(f"Comprovante da execução {run_id} ilegível; o arquivo foi preservado.") from exc
        self._validate(record)
        if record["run_id"] != run_id:
            raise UpdateStateError("Identidade do comprovante divergente do diretório.")
        return record

    def latest(self, cache_type: str | None = None) -> dict:
        records = []
        for path in self.root.glob("*/run.json"):
            record = self.load(path.parent.name)
            if record and (cache_type is None or record["cache_type"] == cache_type):
                records.append(record)
        return max(records, key=lambda r: (r["updated_at"], r["created_at"])) if records else {}

    @staticmethod
    def _validate(record: dict) -> None:
        if not isinstance(record, dict) or record.get("schema_version") != SCHEMA_VERSION:
            raise UpdateStateError("Versão do comprovante incompatível; retomada automática indisponível.")
        if any(field not in record for field in _IMMUTABLE_FIELDS):
            raise UpdateStateError("Comprovante incompleto; retomada automática indisponível.")
        if not _RUN_ID.fullmatch(str(record.get("run_id", ""))):
            raise UpdateStateError("Identificador de execução inválido.")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", str(record.get("cache_type", ""))):
            raise UpdateStateError("Fonte de atualização inválida.")
        if record.get("mode") not in {"incremental", "overwrite", "rebuild"}:
            raise UpdateStateError("Modo de atualização inválido.")
        if not isinstance(record.get("options"), dict):
            raise UpdateStateError("Opções da execução inválidas.")
        if record.get("status") not in RUN_STATUSES:
            raise UpdateStateError("Etapa da execução inválida.")
        periods = record.get("periods")
        persisted = record.get("persisted_periods")
        pending = record.get("pending_periods")
        extracted = record.get("extracted_periods")
        if not all(isinstance(items, list) and all(isinstance(p, str) and p for p in items)
                   and len(items) == len(set(items)) for items in (periods, persisted, pending, extracted)):
            raise UpdateStateError("Unidades da execução inválidas.")
        if (set(persisted) - set(periods) or set(extracted) - set(periods)
                or pending != [p for p in periods if p not in persisted]
                or record.get("requested_periods") != periods):
            raise UpdateStateError("Pendências divergem das unidades efetivamente persistidas.")
        failures = record.get("failed_periods")
        if not isinstance(failures, dict) or set(failures) - set(pending):
            raise UpdateStateError("Falhas da execução divergem das unidades pendentes.")
        terminal = record["status"] in {"saved", "ready_to_publish", "publishing", "published"}
        if pending and terminal:
            raise UpdateStateError("A execução possui pendências e ainda não pode ser concluída/publicada.")
        if terminal and (failures or record.get("error")):
            raise UpdateStateError("A execução possui falhas e ainda não pode ser concluída/publicada.")

    def save(self, record: dict) -> dict:
        candidate = _safe_json(deepcopy(record))
        self._validate(candidate)
        path = self._path(candidate["run_id"])
        with mutation_lock(self.base_dir, owner={"run_id": candidate["run_id"], "cache_type": candidate["cache_type"]}):
            previous = self.load(candidate["run_id"])
            if previous and any(candidate[k] != previous[k] for k in _IMMUTABLE_FIELDS):
                raise UpdateStateError("A configuração original é imutável. Inicie uma nova execução para alterá-la.")
            if previous and set(previous["persisted_periods"]) - set(candidate["persisted_periods"]):
                raise UpdateStateError("O comprovante mudou; recarregue a execução para preservar as unidades confirmadas.")
            candidate["updated_at"] = _now()
            try:
                _write_json_atomic(path, candidate)
            except (OSError, ValueError) as exc:
                raise UpdateStateError("Falha ao gravar o comprovante; a conclusão não foi confirmada.") from exc
        return candidate

    def record_result(self, record: dict, result_metadata: Mapping | None) -> dict:
        metadata = dict(result_metadata or {})
        if metadata.get("run_id") is not None and metadata["run_id"] != record["run_id"]:
            raise UpdateStateError("O resultado pertence a outra execução.")
        if metadata.get("cache_type") is not None and metadata["cache_type"] != record["cache_type"]:
            raise UpdateStateError("O resultado pertence a outra fonte.")
        if metadata.get("execution_periods") is not None and metadata["execution_periods"] != record["periods"]:
            raise UpdateStateError("O resultado diverge do plano imutável da execução.")
        if metadata.get("status") is not None and metadata["status"] not in RUN_STATUSES:
            raise UpdateStateError("Etapa do resultado inválida.")
        updated = deepcopy(record)
        units = updated["periods"]
        confirmed = set(updated.get("persisted_periods") or []) | set(metadata.get("persisted_periods") or [])
        if confirmed - set(units):
            raise UpdateStateError("O resultado contém unidades fora da execução original.")
        failures = dict(updated.get("failed_periods") or {})
        incoming_failures = metadata.get("failed_periods") or {}
        if not isinstance(incoming_failures, Mapping):
            raise UpdateStateError("Falhas da execução devem indicar unidade e motivo.")
        if set(incoming_failures) - set(units):
            raise UpdateStateError("O resultado contém falhas fora da execução original.")
        failures.update(incoming_failures)
        updated["persisted_periods"] = [p for p in units if p in confirmed]
        updated["pending_periods"] = [p for p in units if p not in confirmed]
        updated["failed_periods"] = {p: reason for p, reason in failures.items() if p not in confirmed}
        extracted = set(updated.get("extracted_periods") or []) | set(metadata.get("extracted_periods") or [])
        updated["extracted_periods"] = [p for p in units if p in extracted]
        if set(metadata.get("extracted_periods") or []) - set(units):
            raise UpdateStateError("O resultado contém extrações fora da execução original.")
        if updated["pending_periods"]:
            updated["status"] = "partial" if confirmed else "failed"
        else:
            updated["status"] = "saved" if metadata.get("status") != "failed" else "failed"
        updated["error"] = metadata.get("persistence_error") or metadata.get("checkpoint_error") or metadata.get("callback_error")
        if updated["error"]:
            updated["status"] = "failed"
        return self.save(updated)

    def finish(self, record: dict, status: str, error=None, publication=None) -> dict:
        if status in {"saved", "ready_to_publish", "publishing", "published"} and record.get("error"):
            raise UpdateStateError("A execução possui falhas e ainda não pode ser concluída/publicada.")
        updated = deepcopy(record)
        updated["status"] = status
        updated["error"] = str(error) if error is not None else None
        if publication is not None:
            updated["publication"] = publication
        return self.save(updated)
