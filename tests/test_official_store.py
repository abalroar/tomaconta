"""Persistência de revisões oficiais: fronteiras de ativação e leitores pinados."""
from __future__ import annotations

import json
from pathlib import Path
import threading

import pytest

from utils.ifdata_cache import official_store as S


DATA = "data/cache/principal/dados.parquet"
META = "data/cache/principal/metadata.json"


def _stage(store, tmp_path, content, *, parent=None, job=None):
    source = tmp_path / f"source-{content}.bin"
    source.write_bytes(content.encode())
    metadata = tmp_path / f"meta-{content}.json"
    metadata.write_text(json.dumps({"generation": content}))
    return store.stage({DATA: source, META: metadata}, parent_revision=parent,
                       metadata={"job_id": job} if job else {})


def test_stage_is_not_activation_and_snapshot_base_dir_preserves_logical_paths(tmp_path):
    store = S.LocalRevisionStore(tmp_path / "official")
    staged = _stage(store, tmp_path, "first")
    assert store.current() is None
    assert staged.resolve(DATA) == staged.root / DATA
    assert staged.resolve(DATA).read_bytes() == b"first"
    assert not store.active_path.exists()
    active = store.activate(staged.revision_id, expected_parent=None)
    assert store.current().revision_id == active.revision_id
    assert active.manifest["files"][DATA]["sha256"] == S._digest(active.resolve(DATA))


def test_stage_failure_preserves_active_multifile_revision(tmp_path):
    store = S.LocalRevisionStore(tmp_path / "official")
    first = _stage(store, tmp_path, "first")
    store.activate(first.revision_id, expected_parent=None)
    candidate = tmp_path / "new.bin"
    candidate.write_bytes(b"new")
    with pytest.raises(OSError):
        store.stage({DATA: candidate, META: tmp_path / "missing.json"}, parent_revision=first.revision_id)
    assert store.current().revision_id == first.revision_id
    assert first.resolve(META).read_text() == '{"generation": "first"}'
    assert not list(store.revisions_dir.glob(".stage-*"))


def test_existing_revision_cannot_be_overwritten(tmp_path):
    store = S.LocalRevisionStore(tmp_path / "official")
    first = _stage(store, tmp_path, "first")
    with pytest.raises(S.RevisionConflict):
        store.stage({DATA: first.resolve(DATA)}, revision_id=first.revision_id)
    assert first.resolve(DATA).read_bytes() == b"first"


@pytest.mark.parametrize("after_replace", [False, True])
def test_process_interruption_at_activation_keeps_a_complete_generation(tmp_path, monkeypatch, after_replace):
    store = S.LocalRevisionStore(tmp_path / "official")
    first = _stage(store, tmp_path, "first")
    store.activate(first.revision_id, expected_parent=None)
    second = _stage(store, tmp_path, "second", parent=first.revision_id, job="job-2")
    original = S.os.replace

    def interrupted(source, destination):
        if Path(destination) == store.active_path:
            if after_replace:
                original(source, destination)
            raise KeyboardInterrupt("process terminated")
        return original(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(S.os, "replace", interrupted)
        with pytest.raises(KeyboardInterrupt):
            store.activate(second.revision_id, expected_parent=first.revision_id)
    restarted = S.LocalRevisionStore(store.root)
    chosen = restarted.current()
    assert chosen.revision_id == (second if after_replace else first).revision_id
    assert chosen.resolve(DATA).read_bytes() == (b"second" if after_replace else b"first")
    if after_replace:
        assert restarted.find_publication("job-2").revision_id == second.revision_id
        assert restarted.activate(second.revision_id, expected_parent=first.revision_id).revision_id == second.revision_id
    else:
        assert restarted.find_publication("job-2") is None


def test_concurrent_activation_has_one_cas_winner(tmp_path):
    store = S.LocalRevisionStore(tmp_path / "official")
    first = _stage(store, tmp_path, "first")
    store.activate(first.revision_id, expected_parent=None)
    candidates = [_stage(store, tmp_path, name, parent=first.revision_id) for name in ["second", "third"]]
    barrier = threading.Barrier(2)
    results = []

    def activate(candidate):
        barrier.wait(timeout=5)
        try:
            results.append(store.activate(candidate.revision_id, expected_parent=first.revision_id))
        except S.RevisionConflict as exc:
            results.append(exc)

    threads = [threading.Thread(target=activate, args=(candidate,)) for candidate in candidates]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive()
    winners = [item for item in results if isinstance(item, S.RevisionSnapshot)]
    assert len(winners) == 1
    assert sum(isinstance(item, S.RevisionConflict) for item in results) == 1
    assert store.current().revision_id == winners[0].revision_id


def test_corrupt_active_uses_previous_valid_revision_and_both_corrupt_fail_closed(tmp_path):
    store = S.LocalRevisionStore(tmp_path / "official")
    first = _stage(store, tmp_path, "first")
    store.activate(first.revision_id, expected_parent=None)
    second = _stage(store, tmp_path, "second", parent=first.revision_id)
    store.activate(second.revision_id, expected_parent=first.revision_id)
    second.resolve(DATA).write_bytes(b"CORRUPT")
    assert store.current().revision_id == first.revision_id
    first.resolve(DATA).write_bytes(b"BAD")
    with pytest.raises(S.RevisionCorrupt):
        store.current()


def test_corrupt_active_pointer_uses_durable_last_valid_backup(tmp_path):
    store = S.LocalRevisionStore(tmp_path / "official")
    first = _stage(store, tmp_path, "first")
    store.activate(first.revision_id, expected_parent=None)
    second = _stage(store, tmp_path, "second", parent=first.revision_id)
    store.activate(second.revision_id, expected_parent=first.revision_id)
    store.active_path.write_text("{truncated")
    assert S.LocalRevisionStore(store.root).current().revision_id == first.revision_id
    third = _stage(store, tmp_path, "third", parent=first.revision_id)
    assert store.activate(third.revision_id, expected_parent=first.revision_id).revision_id == third.revision_id


def test_deleted_active_pointer_recovers_previous_committed_revision(tmp_path):
    store = S.LocalRevisionStore(tmp_path / "official")
    first = _stage(store, tmp_path, "first")
    store.activate(first.revision_id, expected_parent=None)
    second = _stage(store, tmp_path, "second", parent=first.revision_id)
    store.activate(second.revision_id, expected_parent=first.revision_id)
    store.active_path.unlink()
    assert S.LocalRevisionStore(store.root).current().revision_id == first.revision_id


def test_deleted_pointer_without_backup_fails_closed_after_publication(tmp_path):
    store = S.LocalRevisionStore(tmp_path / "official")
    first = _stage(store, tmp_path, "first")
    store.activate(first.revision_id, expected_parent=None)
    store.active_path.unlink()
    store.last_valid_path.unlink()
    with pytest.raises(S.RevisionCorrupt):
        store.current()


def test_public_revision_lookup_distinguishes_missing_from_corruption(tmp_path):
    store = S.LocalRevisionStore(tmp_path / "official")
    with pytest.raises(S.RevisionNotFound):
        store.get_revision("missing")
    revision = _stage(store, tmp_path, "first")
    assert store.get_revision(revision.revision_id).revision_id == revision.revision_id
    revision.resolve(DATA).write_bytes(b"bad")
    with pytest.raises(S.RevisionCorrupt):
        store.get_revision(revision.revision_id)


def test_pinned_snapshot_does_not_move_and_rollback_is_a_new_activation(tmp_path):
    store = S.LocalRevisionStore(tmp_path / "official")
    first = _stage(store, tmp_path, "first", job="job-1")
    store.activate(first.revision_id, expected_parent=None)
    pinned = store.current()
    second = _stage(store, tmp_path, "second", parent=first.revision_id, job="job-2")
    store.activate(second.revision_id, expected_parent=first.revision_id)
    assert pinned.resolve(DATA).read_bytes() == b"first"
    assert store.current().resolve(DATA).read_bytes() == b"second"
    assert store.find_publication("job-1").revision_id == first.revision_id
    store.rollback(first.revision_id, expected_parent=second.revision_id)
    assert store.current().revision_id == first.revision_id
    assert json.loads(store.active_path.read_text())["action"] == "rollback"
    with pytest.raises(S.RevisionConflict):
        store.rollback(second.revision_id, expected_parent=second.revision_id)


def test_unchanged_current_reuses_validation_but_tamper_invalidates_cache(tmp_path, monkeypatch):
    store = S.LocalRevisionStore(tmp_path / "official")
    first = _stage(store, tmp_path, "first")
    store.activate(first.revision_id, expected_parent=None)
    real_digest = S._digest
    calls = []
    monkeypatch.setattr(S, "_digest", lambda path: (calls.append(path), real_digest(path))[1])
    assert store.current().revision_id == first.revision_id
    assert calls == []
    first.resolve(DATA).write_bytes(b"other")
    with pytest.raises(S.RevisionCorrupt):
        store.current()
    assert calls


@pytest.mark.parametrize("logical", ["../outside", "/absolute", "data/../outside", "data//x", "data/./x", "data\\x"])
def test_path_escape_is_rejected_before_stage(tmp_path, logical):
    source = tmp_path / "input"
    source.write_bytes(b"safe")
    store = S.LocalRevisionStore(tmp_path / "official")
    with pytest.raises(S.OfficialStoreError):
        store.stage({logical: source})
    assert store.current() is None


def test_symlink_asset_in_revision_is_rejected(tmp_path):
    store = S.LocalRevisionStore(tmp_path / "official")
    first = _stage(store, tmp_path, "first")
    store.activate(first.revision_id, expected_parent=None)
    original = first.resolve(DATA)
    outside = tmp_path / "outside"
    outside.write_bytes(original.read_bytes())
    original.unlink()
    original.symlink_to(outside)
    with pytest.raises(S.RevisionCorrupt):
        store.current()


def test_export_and_worker_workspace_preserve_bytes_and_cannot_mutate_revision(tmp_path):
    store = S.LocalRevisionStore(tmp_path / "official")
    first = _stage(store, tmp_path, "first")
    exported = store.export(first, tmp_path / "export")
    assert S._digest(exported / "files" / DATA) == first.manifest["files"][DATA]["sha256"]
    assert S._digest(exported / "manifest.json") == first.manifest_sha256
    workspace = store.materialize_workspace(first, tmp_path / "workspace")
    (workspace / DATA).write_bytes(b"worker changed this")
    assert first.resolve(DATA).read_bytes() == b"first"
    with pytest.raises(S.RevisionConflict):
        store.materialize_workspace(first, workspace)


def test_env_is_opt_in_and_configured_empty_store_does_not_choose_legacy(tmp_path, monkeypatch):
    monkeypatch.delenv("TOMACONTA_OFFICIAL_STORE_DIR", raising=False)
    assert S.store_from_env(tmp_path) is None
    assert S.resolve_official_path(DATA, base_dir=tmp_path) is None
    monkeypatch.setenv("TOMACONTA_OFFICIAL_STORE_DIR", "official")
    assert S.store_from_env(tmp_path).root == tmp_path / "official"
    with pytest.raises(S.StoreNotInitialized):
        S.resolve_official_path(DATA, base_dir=tmp_path)
