"""Revisões oficiais imutáveis, independentes do destino de publicação.

Os extratores continuam gravando num workspace privado. A aplicação recebe um
snapshot fixo de leitura; somente activate altera a revisão oferecida a novos
leitores. Este módulo não consulta APIs nem interpreta fórmulas financeiras.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import threading
from typing import Any, Iterator, Mapping, Protocol
from uuid import uuid4

_VALIDATED: dict[tuple[str, str, str], tuple[tuple, "RevisionSnapshot"]] = {}
_CACHE_LOCK = threading.Lock()
_READ_CONTEXT: ContextVar[tuple[Path, "RevisionSnapshot"] | None] = ContextVar("official_read", default=None)
_WRITABLE_CONTEXT: ContextVar[bool] = ContextVar("official_workspace", default=False)


class OfficialStoreError(RuntimeError):
    """Uma revisão oficial não pôde ser utilizada com segurança."""


class RevisionCorrupt(OfficialStoreError):
    pass


class RevisionNotFound(OfficialStoreError):
    """A revisão solicitada ainda não foi preparada."""


class RevisionConflict(OfficialStoreError):
    """A revisão ativa mudou desde o início da atualização."""


class StoreNotInitialized(OfficialStoreError):
    pass


class OfficialReadOnlyError(OfficialStoreError):
    """Extrair ou gravar exige um workspace do worker."""


def _relative(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise OfficialStoreError("Caminho lógico inválido")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise OfficialStoreError("Caminho lógico deve ser relativo e permanecer no snapshot")
    return str(path)


def _revision_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise OfficialStoreError("Identificador de revisão inválido")
    return value


def _digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def _stamp(path: Path) -> tuple:
    value = path.stat()
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
            value.st_ctime_ns, value.st_mode)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _atomic_json(path: Path, payload: Mapping) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(_json_bytes(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_dir(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_child(root: Path, relative: str) -> Path:
    if root.is_symlink():
        raise RevisionCorrupt("Diretório do snapshot não pode ser link simbólico")
    path = root / _relative(relative)
    for parent in [path, *path.parents]:
        if parent == root:
            break
        if parent.is_symlink():
            raise RevisionCorrupt("Links simbólicos não pertencem ao snapshot")
    if not path.resolve().is_relative_to(root.resolve()):
        raise RevisionCorrupt("Arquivo fora do snapshot")
    return path


@dataclass(frozen=True)
class RevisionSnapshot:
    revision_id: str
    parent_revision: str | None
    manifest_sha256: str
    root: Path
    manifest: Mapping[str, Any]
    file_fingerprints: Mapping[str, tuple] = field(default_factory=dict, repr=False, compare=False)

    def resolve(self, logical_relative: str) -> Path:
        logical = _relative(logical_relative)
        if logical not in self.manifest["files"]:
            raise OfficialStoreError(f"Arquivo não declarado na revisão: {logical}")
        path = _safe_child(self.root, logical)
        if not path.is_file():
            raise RevisionCorrupt(f"Arquivo ausente na revisão: {logical}")
        before = _stamp(path)
        if self.file_fingerprints.get(logical) != before:
            if (_digest(path) != self.manifest["files"][logical]["sha256"]
                    or _stamp(path) != before):
                raise RevisionCorrupt(f"Arquivo alterado na revisão: {logical}")
        return path


class ProtocolDataStore(Protocol):
    def get_revision(self, revision_id: str) -> RevisionSnapshot: ...
    def stage(self, artifacts: Mapping[str, Path], *, parent_revision: str | None = None,
              metadata: Mapping[str, Any] | None = None,
              revision_id: str | None = None) -> RevisionSnapshot: ...
    def activate(self, revision_id: str, *, expected_parent: str | None,
                 actor: Mapping[str, Any] | None = None) -> RevisionSnapshot: ...
    def current(self) -> RevisionSnapshot | None: ...
    def find_publication(self, job_id: str) -> RevisionSnapshot | None: ...
    def rollback(self, revision_id: str, *, expected_parent: str | None,
                 actor: Mapping[str, Any] | None = None) -> RevisionSnapshot: ...
    def export(self, snapshot: RevisionSnapshot | str, destination: Path) -> Path: ...
    def materialize_workspace(self, snapshot: RevisionSnapshot | str,
                              destination: Path) -> Path: ...


class LocalRevisionStore:
    """Backend filesystem para um único volume com rename/fsync e flock.

    Stage não publica. A validação semântica e a completude dos caches pertencem
    ao preflight compartilhado do serviço, anterior a activate. Nenhuma revisão
    é removida automaticamente, preservando os caminhos dos leitores pinados.
    """
    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser().absolute()
        if self.root.is_symlink():
            raise OfficialStoreError("A raiz do armazenamento não pode ser um link")
        self.revisions_dir = self.root / "revisions"
        self.active_path = self.root / "active.json"
        self.last_valid_path = self.root / "last_valid.json"

    def _prepare(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.revisions_dir.mkdir(exist_ok=True)
        if self.revisions_dir.is_symlink():
            raise OfficialStoreError("Diretório de revisões inválido")

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self._prepare()
        path = self.root / ".activation.lock"
        if path.is_symlink():
            raise OfficialStoreError("Trava de ativação inválida")
        with path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _reference(snapshot: RevisionSnapshot) -> dict:
        return {"revision_id": snapshot.revision_id, "manifest_sha256": snapshot.manifest_sha256}

    def _load(self, revision_id: str, expected_digest: str | None = None) -> RevisionSnapshot:
        root = self.revisions_dir / _revision_id(revision_id)
        key = (str(self.root), revision_id, expected_digest or "")
        try:
            if not root.exists() and not root.is_symlink():
                raise RevisionNotFound(f"Revisão não encontrada: {revision_id}")
            if (self.root.is_symlink() or self.revisions_dir.is_symlink()
                    or root.is_symlink() or not root.is_dir()):
                raise RevisionCorrupt(f"Revisão ausente: {revision_id}")
            with _CACHE_LOCK:
                cached = _VALIDATED.get(key)
            if cached and self._fingerprint(cached[1]) == cached[0]:
                return cached[1]
            path = _safe_child(root, "manifest.json")
            digest = _digest(path)
            if expected_digest and digest != expected_digest:
                raise RevisionCorrupt("Hash do manifesto diverge do ponteiro")
            manifest = json.loads(path.read_bytes())
            if (not isinstance(manifest, dict) or manifest.get("schema_version") != 1
                    or manifest.get("revision_id") != revision_id
                    or not isinstance(manifest.get("files"), dict) or not manifest["files"]):
                raise RevisionCorrupt("Manifesto de revisão inválido")
            parent = manifest.get("parent_revision")
            if parent is not None:
                _revision_id(parent)
            files_root = root / "files"
            if files_root.is_symlink():
                raise RevisionCorrupt("Diretório de arquivos inválido")
            fingerprints = {}
            manifest_stamp = _stamp(path)
            for logical, entry in manifest["files"].items():
                if (not isinstance(entry, dict) or not re.fullmatch(r"[a-f0-9]{64}", str(entry.get("sha256", "")))
                        or type(entry.get("size_bytes")) is not int or entry["size_bytes"] < 0):
                    raise RevisionCorrupt("Entrada de arquivo inválida")
                source = _safe_child(files_root, logical)
                before = _stamp(source)
                if (not source.is_file() or source.stat().st_size != entry["size_bytes"]
                        or _digest(source) != entry["sha256"] or _stamp(source) != before):
                    raise RevisionCorrupt(f"Arquivo ausente/corrompido: {logical}")
                fingerprints[logical] = before
            if _stamp(path) != manifest_stamp or _digest(path) != digest:
                raise RevisionCorrupt("Manifesto mudou durante a validação")
            snapshot = RevisionSnapshot(revision_id, parent, digest, files_root, manifest, fingerprints)
            fingerprint = self._fingerprint(snapshot)
            if any(_stamp(snapshot.resolve(name)) != stamp for name, stamp in fingerprints.items()):
                raise RevisionCorrupt("Snapshot mudou durante a validação")
            with _CACHE_LOCK:
                if len(_VALIDATED) >= 64:
                    _VALIDATED.clear()
                _VALIDATED[key] = (fingerprint, snapshot)
                _VALIDATED[(str(self.root), revision_id, digest)] = (fingerprint, snapshot)
            return snapshot
        except OfficialStoreError:
            raise
        except (OSError, ValueError, TypeError) as exc:
            raise RevisionCorrupt(f"Revisão ilegível: {revision_id}") from exc

    @staticmethod
    def _fingerprint(snapshot: RevisionSnapshot) -> tuple:
        return (_stamp(snapshot.root.parent), _stamp(snapshot.root),
                _stamp(_safe_child(snapshot.root.parent, "manifest.json")),
                *(_stamp(_safe_child(snapshot.root, logical)) for logical in sorted(snapshot.manifest["files"])))

    def _from_ref(self, ref: Mapping) -> RevisionSnapshot:
        if (not isinstance(ref, Mapping) or not re.fullmatch(r"[a-f0-9]{64}", str(ref.get("manifest_sha256", "")))):
            raise RevisionCorrupt("Referência de revisão inválida")
        return self._load(ref.get("revision_id"), ref["manifest_sha256"])

    def get_revision(self, revision_id: str) -> RevisionSnapshot:
        return self._load(revision_id)

    def stage(self, artifacts: Mapping[str, Path], *, parent_revision: str | None = None,
              metadata: Mapping[str, Any] | None = None,
              revision_id: str | None = None) -> RevisionSnapshot:
        if not artifacts:
            raise OfficialStoreError("Revisão sem arquivos")
        names = {logical: _relative(logical) for logical in artifacts}
        if parent_revision is not None:
            _revision_id(parent_revision)
        revision_id = _revision_id(revision_id or uuid4().hex)
        self._prepare()
        target = self.revisions_dir / revision_id
        if target.exists() or target.is_symlink():
            raise RevisionConflict(f"Revisão já existe: {revision_id}")
        transaction = Path(tempfile.mkdtemp(prefix=".stage-", dir=self.revisions_dir))
        try:
            entries = {}
            for logical, normalized in sorted(names.items()):
                source = Path(artifacts[logical])
                destination = transaction / "files" / normalized
                destination.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                with source.open("rb") as reader, destination.open("xb") as writer:
                    before = os.fstat(reader.fileno())
                    for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                        digest.update(chunk)
                        writer.write(chunk)
                    writer.flush()
                    os.fsync(writer.fileno())
                    after = os.fstat(reader.fileno())
                if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                    raise RevisionConflict(f"Arquivo de origem mudou durante o snapshot: {logical}")
                if destination.stat().st_size != before.st_size or _digest(destination) != digest.hexdigest():
                    raise RevisionCorrupt(f"Cópia de arquivo inválida: {logical}")
                entries[normalized] = {"sha256": digest.hexdigest(), "size_bytes": before.st_size}
            manifest = {"schema_version": 1, "revision_id": revision_id,
                        "parent_revision": parent_revision,
                        "created_at_utc": datetime.now(timezone.utc).isoformat(),
                        "metadata": dict(metadata or {}), "files": entries}
            _atomic_json(transaction / "manifest.json", manifest)
            for directory in sorted((p for p in transaction.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
                _fsync_dir(directory)
            _fsync_dir(transaction)
            with self._lock():
                if target.exists() or target.is_symlink():
                    raise RevisionConflict(f"Revisão já existe: {revision_id}")
                os.rename(transaction, target)
                _fsync_dir(self.revisions_dir)
            return self._load(revision_id)
        finally:
            if transaction.exists():
                shutil.rmtree(transaction)

    def _read_head(self) -> dict | None:
        if not self.active_path.exists():
            if (self.last_valid_path.exists() or self.last_valid_path.is_symlink()
                    or (self.root / "activations").exists() and any((self.root / "activations").glob("*.json"))):
                raise RevisionCorrupt("Ponteiro ativo ausente em armazenamento inicializado")
            return None
        if self.active_path.is_symlink():
            raise RevisionCorrupt("Ponteiro ativo inválido")
        try:
            head = json.loads(self.active_path.read_bytes())
            if not isinstance(head, dict) or head.get("schema_version") != 1:
                raise RevisionCorrupt("Ponteiro ativo inválido")
            return head
        except (OSError, ValueError) as exc:
            raise RevisionCorrupt("Ponteiro ativo ilegível") from exc

    def current(self) -> RevisionSnapshot | None:
        """Valida a revisão inteira; corrupção usa somente um fallback comprovado."""
        errors = []
        try:
            head = self._read_head()
            if head is None:
                return None
            try:
                return self._from_ref(head.get("active"))
            except OfficialStoreError as exc:
                errors.append(exc)
            if head.get("last_valid"):
                try:
                    return self._from_ref(head["last_valid"])
                except OfficialStoreError as exc:
                    errors.append(exc)
        except OfficialStoreError as exc:
            errors.append(exc)
        try:
            if self.last_valid_path.is_symlink():
                raise RevisionCorrupt("Backup do ponteiro inválido")
            backup = json.loads(self.last_valid_path.read_bytes())
            return self._from_ref(backup["active"])
        except (OSError, ValueError, TypeError, KeyError, OfficialStoreError) as exc:
            raise RevisionCorrupt("Nenhuma revisão oficial válida disponível") from (errors[0] if errors else exc)

    def _activate(self, revision_id: str, expected_parent: str | None,
                  actor: Mapping[str, Any] | None, *, rollback: bool) -> RevisionSnapshot:
        candidate = self._load(revision_id)
        with self._lock():
            previous = self.current()
            if previous and previous.revision_id == revision_id:
                return previous
            actual = previous.revision_id if previous else None
            if actual != expected_parent:
                raise RevisionConflict(f"Revisão ativa mudou: esperada {expected_parent}, atual {actual}")
            if not rollback and candidate.parent_revision != expected_parent:
                raise RevisionConflict("Candidato foi preparado sobre outra revisão")
            try:
                previous_head = self._read_head()
            except OfficialStoreError:
                previous_head = None
            history = self.root / "activations"
            if history.is_symlink():
                raise OfficialStoreError("Histórico de ativações inválido")
            historical_sequences = [int(p.name.split("-", 1)[0]) for p in history.glob("*.json")
                                    if p.name.split("-", 1)[0].isdigit()]
            sequence = max([int((previous_head or {}).get("sequence", 0)), *historical_sequences]) + 1
            head = {"schema_version": 1, "sequence": sequence,
                    "active": self._reference(candidate),
                    "last_valid": self._reference(previous or candidate),
                    "activated_at_utc": datetime.now(timezone.utc).isoformat(),
                    "actor": dict(actor or {}), "action": "rollback" if rollback else "activate",
                    "job_id": candidate.manifest.get("metadata", {}).get("job_id")}
            history.mkdir(exist_ok=True)
            if previous:
                # O registro anterior já foi ativo, mesmo se um processo morreu
                # antes de persistir seu histórico de ativação.
                if previous_head:
                    _atomic_json(history / f"{sequence - 1:020d}-{previous.revision_id}.json", previous_head)
                _atomic_json(self.last_valid_path, {"active": self._reference(previous)})
            _atomic_json(self.active_path, head)
            if previous is None:
                _atomic_json(self.last_valid_path, {"active": self._reference(candidate)})
            _atomic_json(history / f"{sequence:020d}-{revision_id}.json", head)
        return candidate

    def activate(self, revision_id: str, *, expected_parent: str | None,
                 actor: Mapping[str, Any] | None = None) -> RevisionSnapshot:
        return self._activate(revision_id, expected_parent, actor, rollback=False)

    def rollback(self, revision_id: str, *, expected_parent: str | None,
                 actor: Mapping[str, Any] | None = None) -> RevisionSnapshot:
        return self._activate(revision_id, expected_parent, actor, rollback=True)

    def find_publication(self, job_id: str) -> RevisionSnapshot | None:
        """Reconcile publicação confirmada no head ou histórico, nunca só staged."""
        paths = [self.active_path, *sorted((self.root / "activations").glob("*.json"), reverse=True)]
        for path in paths:
            try:
                head = json.loads(path.read_bytes())
                if head.get("job_id") == job_id:
                    return self._from_ref(head["active"])
            except (OSError, ValueError, KeyError, TypeError, OfficialStoreError):
                continue
        return None

    def _snapshot(self, snapshot: RevisionSnapshot | str) -> RevisionSnapshot:
        if isinstance(snapshot, RevisionSnapshot):
            return self._load(snapshot.revision_id, snapshot.manifest_sha256)
        return self._load(snapshot)

    def _copy_snapshot(self, snapshot: RevisionSnapshot | str, destination: Path,
                       *, package: bool) -> Path:
        snapshot = self._snapshot(snapshot)
        target = Path(destination).absolute()
        if target.exists() or target.is_symlink():
            raise RevisionConflict("Destino deve ser novo para preservar arquivos existentes")
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
        try:
            for logical, entry in snapshot.manifest["files"].items():
                output = staging / ("files" if package else "") / logical
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(snapshot.resolve(logical), output)
                if _digest(output) != entry["sha256"]:
                    raise RevisionCorrupt("Cópia para exportação/workspace diverge da revisão")
                with output.open("rb") as handle:
                    os.fsync(handle.fileno())
            if package:
                shutil.copyfile(snapshot.root.parent / "manifest.json", staging / "manifest.json")
                if _digest(staging / "manifest.json") != snapshot.manifest_sha256:
                    raise RevisionCorrupt("Manifesto exportado diverge da revisão pinada")
                with (staging / "manifest.json").open("rb") as handle:
                    os.fsync(handle.fileno())
            for directory in sorted((p for p in staging.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
                _fsync_dir(directory)
            _fsync_dir(staging)
            # Destino exclusivo; evitar renomear sobre uma pasta criada por
            # outra operação durante a cópia.
            with self._lock():
                if target.exists() or target.is_symlink():
                    raise RevisionConflict("Destino passou a existir durante a cópia")
                os.rename(staging, target)
                _fsync_dir(target.parent)
            return target
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def export(self, snapshot: RevisionSnapshot | str, destination: Path) -> Path:
        return self._copy_snapshot(snapshot, destination, package=True)

    def materialize_workspace(self, snapshot: RevisionSnapshot | str, destination: Path) -> Path:
        return self._copy_snapshot(snapshot, destination, package=False)


def store_from_env(base_dir: Path | None = None) -> LocalRevisionStore | None:
    """Configuração explícita; construtor não cria arquivos durante a leitura."""
    value = os.getenv("TOMACONTA_OFFICIAL_STORE_DIR", "").strip()
    if not value:
        return None
    root = Path(value).expanduser()
    if not root.is_absolute():
        if base_dir is None:
            raise OfficialStoreError("Armazenamento relativo exige base_dir")
        root = Path(base_dir) / root
    return LocalRevisionStore(root)


def resolve_official_path(logical_relative: str, *, snapshot: RevisionSnapshot | None = None,
                          store: ProtocolDataStore | None = None,
                          base_dir: Path | None = None) -> Path | None:
    configured = store or store_from_env(base_dir)
    if snapshot is None and configured is None:
        return None
    pinned = snapshot or configured.current()
    if pinned is None:
        raise StoreNotInitialized("Armazenamento oficial configurado sem revisão ativa")
    return pinned.resolve(logical_relative)


def begin_official_read(base_dir: Path | None = None) -> RevisionSnapshot | None:
    """Pina uma revisão para o render atual; chamar uma vez no início do rerun."""
    origin = Path(base_dir or Path(__file__).resolve().parents[2]).resolve()
    _READ_CONTEXT.set(None)
    configured = store_from_env(origin)
    if configured is None:
        return None
    snapshot = configured.current()
    if snapshot is None:
        raise StoreNotInitialized("Armazenamento oficial configurado sem revisão ativa")
    _READ_CONTEXT.set((origin, snapshot))
    return snapshot


def get_official_read_snapshot(base_dir: Path | None = None) -> RevisionSnapshot | None:
    if _WRITABLE_CONTEXT.get():
        return None
    if not os.getenv("TOMACONTA_OFFICIAL_STORE_DIR", "").strip():
        _READ_CONTEXT.set(None)
        return None
    explicit_root = Path(base_dir).resolve() if base_dir is not None else None
    if explicit_root is not None:
        configured = store_from_env(Path(__file__).resolve().parents[2])
        try:
            parts = explicit_root.relative_to(configured.revisions_dir).parts
        except ValueError:
            parts = ()
        if len(parts) == 2 and parts[1] == "files":
            # Uma raiz imutável explícita jamais vira área gravável do worker.
            context = _READ_CONTEXT.get()
            if context is not None and explicit_root == context[1].root:
                return context[1]
            return configured.get_revision(parts[0])
    context = _READ_CONTEXT.get()
    if context is None:
        origin = Path(__file__).resolve().parents[2]
        if explicit_root is not None and explicit_root != origin:
            return None
        return begin_official_read()
    origin, snapshot = context
    if explicit_root is None or explicit_root in {origin, snapshot.root.resolve()}:
        return snapshot
    # Um workspace explícito de uma execução é independente do render.
    return None


@contextmanager
def writable_cache_context() -> Iterator[None]:
    token = _WRITABLE_CONTEXT.set(True)
    try:
        yield
    finally:
        _WRITABLE_CONTEXT.reset(token)
