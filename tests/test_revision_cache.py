"""Chaves Streamlit isoladas por revisão, incluindo dois renders concorrentes."""
from __future__ import annotations

import inspect
from pathlib import Path
import threading

import pytest

from utils.ifdata_cache import official_store as S
from utils.ifdata_cache.revision_cache import revision_cache_data


@pytest.fixture(autouse=True)
def isolated_context(monkeypatch):
    token = S._READ_CONTEXT.set(None)
    monkeypatch.delenv("TOMACONTA_OFFICIAL_STORE_DIR", raising=False)
    yield
    S._READ_CONTEXT.reset(token)


def _revisions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.write_text("data")
    store = S.LocalRevisionStore(tmp_path / "store")
    first = store.stage({"fixture.txt": source})
    store.activate(first.revision_id, expected_parent=None)
    second = store.stage({"fixture.txt": source}, parent_revision=first.revision_id)
    store.activate(second.revision_id, expected_parent=first.revision_id)
    monkeypatch.setenv("TOMACONTA_OFFICIAL_STORE_DIR", str(store.root))
    return first, second, tmp_path / "app"


def test_legacy_behavior_and_public_signature_are_preserved():
    calls = []
    def original(value, /, _opaque, *, multiplier=2, **kwargs):
        calls.append(value)
        return value * multiplier, sorted(kwargs.items())
    cached = revision_cache_data(show_spinner=False)(original)
    assert inspect.signature(cached) == inspect.signature(original)
    assert cached(3, object(), multiplier=4, label="x") == (12, [("label", "x")])
    assert cached(3, object(), multiplier=4, label="x") == (12, [("label", "x")])
    assert calls == [3]
    cached.clear()


def test_official_revision_changes_key_without_requiring_clear(monkeypatch, tmp_path):
    first, second, app = _revisions(tmp_path, monkeypatch)
    calls = []
    @revision_cache_data(ttl=3600, show_spinner=False)
    def read(value, _opaque):
        revision = S.get_official_read_snapshot().revision_id
        calls.append(revision)
        return value, revision
    S._READ_CONTEXT.set((app, first))
    assert read(1, object()) == (1, first.revision_id)
    assert read(1, object()) == (1, first.revision_id)
    S._READ_CONTEXT.set((app, second))
    assert read(1, object()) == (1, second.revision_id)
    assert calls == [first.revision_id, second.revision_id]
    S._READ_CONTEXT.set((app, first))
    assert read(1, object()) == (1, first.revision_id)
    assert len(calls) == 2
    read.clear()


def test_official_positional_only_underscored_and_variadic_kwargs_survive(monkeypatch, tmp_path):
    first, _, app = _revisions(tmp_path, monkeypatch)
    S._READ_CONTEXT.set((app, first))
    calls = []
    @revision_cache_data(show_spinner=False)
    def original(value, /, _connection, *items, factor=2, **kwargs):
        calls.append(value)
        return value * factor, items, kwargs
    hidden = original._revision_cache_parameter
    kwargs = {hidden: "caller data", "normal": 3, "_unhashable": object()}
    result = original(2, object(), 7, factor=4, **kwargs)
    assert result[0] == 8 and result[1] == (7,)
    assert result[2][hidden] == "caller data" and result[2]["normal"] == 3
    assert original(2, object(), 7, factor=4, **{hidden: "caller data", "normal": 3, "_unhashable": object()})[:2] == (8, (7,))
    assert calls == [2]
    original.clear()


def test_existing_parameter_with_internal_name_is_preserved(monkeypatch, tmp_path):
    first, _, app = _revisions(tmp_path, monkeypatch)
    S._READ_CONTEXT.set((app, first))
    @revision_cache_data(show_spinner=False)
    def original(tomaconta_official_revision_id):
        return tomaconta_official_revision_id
    assert original._revision_cache_parameter != "tomaconta_official_revision_id"
    assert original("caller data") == "caller data"
    original.clear()


def test_clear_with_arguments_clears_only_current_revision(monkeypatch, tmp_path):
    first, second, app = _revisions(tmp_path, monkeypatch)
    calls = []
    @revision_cache_data(show_spinner=False)
    def original(value):
        calls.append((value, S.get_official_read_snapshot().revision_id))
        return len(calls)
    S._READ_CONTEXT.set((app, first))
    assert original(1) == 1
    S._READ_CONTEXT.set((app, second))
    assert original(1) == 2
    original.clear(1)
    assert original(1) == 3
    S._READ_CONTEXT.set((app, first))
    assert original(1) == 1
    original.clear()
    assert original(1) == 4
    original.clear()


def test_clear_with_arguments_retains_legacy_contract():
    calls = []
    @revision_cache_data(show_spinner=False)
    def original(value):
        calls.append(value)
        return len(calls)
    assert original(1) == 1 and original(2) == 2
    original.clear(1)
    assert original(1) == 3 and original(2) == 2
    original.clear()


def test_old_session_cannot_repopulate_new_revision_cache(monkeypatch, tmp_path):
    first, second, app = _revisions(tmp_path, monkeypatch)
    entered = threading.Event()
    finish = threading.Event()
    results = []
    calls = []
    @revision_cache_data(show_spinner=False)
    def read(value, _block=False):
        revision = S.get_official_read_snapshot().revision_id
        calls.append(revision)
        if _block:
            entered.set()
            assert finish.wait(timeout=5)
        return value, revision
    def old_render():
        S._READ_CONTEXT.set((app, first))
        results.append(read(1, _block=True))
    thread = threading.Thread(target=old_render)
    thread.start()
    try:
        assert entered.wait(timeout=5)
        S._READ_CONTEXT.set((app, second))
        assert read(1) == (1, second.revision_id)
        finish.set()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert results == [(1, first.revision_id)]
        assert read(1) == (1, second.revision_id)
        assert calls == [first.revision_id, second.revision_id]
    finally:
        finish.set()
        thread.join(timeout=5)
        read.clear()


def test_bare_decorator_syntax_supports_default_options():
    @revision_cache_data
    def original(value):
        return value + 1
    assert original(2) == 3
    original.clear()


def test_scr_resource_factory_uses_current_official_revision(monkeypatch, tmp_path):
    from tabs.scr_inadimplencia_view import _scr_cache_for_render
    from utils.ifdata_cache import get_manager
    first, second, app = _revisions(tmp_path, monkeypatch)
    def legacy():
        raise AssertionError("Recurso SCR legado não pode fornecer uma revisão oficial")
    S._READ_CONTEXT.set((app, first))
    old = _scr_cache_for_render(get_manager, legacy)
    assert old._official_snapshot.revision_id == first.revision_id
    S._READ_CONTEXT.set((app, second))
    new = _scr_cache_for_render(get_manager, legacy)
    assert new is not old
    assert new._official_snapshot.revision_id == second.revision_id


def test_scr_resource_factory_preserves_legacy_without_configured_store():
    from tabs.scr_inadimplencia_view import _scr_cache_for_render
    cache = object()
    def forbidden():
        raise AssertionError("Modo legado deve reutilizar o recurso existente")
    assert _scr_cache_for_render(forbidden, lambda: cache) is cache
