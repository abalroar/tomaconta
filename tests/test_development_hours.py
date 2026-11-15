from datetime import datetime, timedelta, timezone
from threading import Event

import pytest

from utils.development_hours import (
    CACHE_TTL, DEFAULT_CONFIG, RETRY_INTERVAL, DevelopmentHoursError, EstimateCache,
    calculate_estimate, fetch_history, needs_refresh, normalize_config, parse_datetime,
    read_json, write_snapshot,
)


NOW = datetime(2026, 10, 9, 21, tzinfo=timezone.utc)


def commit(sha, date, message=None):
    return {"sha": sha, "data": parse_datetime(date), "mensagem": message or sha}


def estimate(now=NOW, config=None):
    return calculate_estimate([
        commit("a", "2026-01-26T12:00:00Z"),
        commit("b", "2026-01-26T13:30:00Z"),
        commit("c", "2026-01-26T15:01:00Z"),
        commit("d", "2026-02-09T12:00:00Z"),
    ], config or DEFAULT_CONFIG, now=now)


def test_session_boundary_overhead_and_zero_weeks():
    result = estimate()
    assert result["horas_base_commits"] == 1.5
    assert result["horas_overhead"] == 1
    assert result["total_horas"] == 2.5
    assert result["total_sessoes"] == 3
    assert result["sessao_media_horas"] == .83
    weeks = result["esforco_semanal"]
    assert [row["semana_inicio"] for row in weeks] == ["2026-01-26", "2026-02-02", "2026-02-09"]
    assert weeks[1]["total_horas"] == 0
    assert weeks[1]["label_semana"] == "02/fev"
    assert sum(row["total_horas"] for row in weeks) == pytest.approx(result["total_horas"], abs=.02)


def test_deduplication_uses_sha_and_author_time_in_utc_plus_message():
    result = calculate_estimate([
        commit("a", "2026-01-26T12:00:00Z", "Feature"),
        commit("a", "2026-01-26T13:00:00Z", "same SHA"),
        commit("b", "2026-01-26T09:00:00-03:00", " feature "),
        commit("c", "2026-01-26T12:30:00Z", "Next"),
    ], DEFAULT_CONFIG, now=NOW)
    assert result["total_commits"] == 2
    assert result["commits_duplicados"] == 2
    assert result["horas_base_commits"] == .5


def test_session_crossing_week_is_assigned_to_start_and_br_timezone():
    result = calculate_estimate([
        commit("a", "2026-02-02T02:45:00Z"),  # Domingo, 23:45 em Brasília
        commit("b", "2026-02-02T03:15:00Z"),
    ], DEFAULT_CONFIG, now=NOW)
    assert result["esforco_semanal"][0]["semana_inicio"] == "2026-01-26"
    assert result["esforco_semanal"][0]["horas_commits"] == .5
    assert result["esforco_semanal"][1]["total_horas"] == 0


def test_empty_history_and_sensitivity_above_one_hour_overhead():
    assert calculate_estimate([], DEFAULT_CONFIG, now=NOW)["esforco_semanal"] == []
    result = estimate(config={**DEFAULT_CONFIG, "overhead_sessao_min": 120})
    interval = result["faixa_estimativa_horas"]
    assert interval["min"] <= interval["central"] <= interval["max"]


@pytest.mark.parametrize("config", [
    {"repositorios": []}, {"repositorios": ["https://example.com"]},
    {"limiar_sessao_min": -1}, {"limiar_sessao_min": True},
    {"overhead_sessao_min": 121}, {"incluir_merges": "false"},
])
def test_invalid_parameters_are_rejected(config):
    with pytest.raises(ValueError):
        normalize_config(config)


class Response:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload


def raw_commit(sha, parents=1, message=None):
    return {"sha": sha, "parents": [{}] * parents,
            "commit": {"author": {"date": "2026-01-26T12:00:00Z"}, "message": message or sha}}


class Client:
    def __init__(self, batches, *, unauthorized=False):
        self.calls, self.batches, self.unauthorized = [], batches, unauthorized

    def get(self, url, *, headers, params, timeout):
        self.calls.append((url, dict(headers), dict(params or {})))
        if self.unauthorized and "Authorization" in headers:
            return Response({}, 401)
        if url.endswith("/commits"):
            return self.batches[params["page"] - 1]
        return Response({"full_name": "owner/project", "default_branch": "main"})


def test_github_aliases_pagination_pin_and_parent_based_merge_detection():
    batch = [raw_commit(f"sha{i}") for i in range(99)] + [raw_commit("merge", parents=2, message="custom release title")]
    client = Client([Response(batch), Response([raw_commit("last")])])
    config = {**DEFAULT_CONFIG, "repositorios": ["owner/project", "owner/old-name"]}
    commits, sources = fetch_history(config, client=client)
    assert len(commits) == 100
    assert len(sources) == 1
    assert sources[0]["nomes_consultados"] == ["owner/project", "owner/old-name"]
    assert sources[0]["merges_excluidos"] == 1
    calls = [params for url, _, params in client.calls if url.endswith("/commits")]
    assert len(calls) == 2
    assert calls[0]["sha"] == "main" and calls[1]["sha"] == "sha0"


def test_expired_token_falls_back_to_public_for_all_subsequent_requests():
    client = Client([Response([raw_commit("first")])], unauthorized=True)
    config = {**DEFAULT_CONFIG, "repositorios": ["owner/project"]}
    assert fetch_history(config, token="test-only-token", client=client)[0]
    assert "Authorization" in client.calls[0][1]
    assert all("Authorization" not in headers for _, headers, _ in client.calls[1:])


@pytest.mark.parametrize("payload,status", [({}, 200), ([{"sha": "missing-date"}], 200), ([], 403)])
def test_partial_or_failed_github_history_is_rejected(payload, status):
    client = Client([Response(payload, status)])
    with pytest.raises(DevelopmentHoursError):
        fetch_history({**DEFAULT_CONFIG, "repositorios": ["owner/project"]}, client=client)


def test_ttl_schema_and_parameter_changes_require_refresh():
    result = estimate()
    assert not needs_refresh(result, DEFAULT_CONFIG, NOW)
    assert needs_refresh(result, DEFAULT_CONFIG, NOW + CACHE_TTL)
    assert needs_refresh({**result, "schema_version": 1}, DEFAULT_CONFIG, NOW)
    assert needs_refresh(result, {**DEFAULT_CONFIG, "overhead_sessao_min": 30}, NOW)
    assert needs_refresh(result, DEFAULT_CONFIG, NOW - timedelta(seconds=1))


def test_invalid_write_preserves_previous_file(tmp_path):
    path = tmp_path / "snapshot.json"
    write_snapshot(path, estimate())
    previous = path.read_bytes()
    with pytest.raises(ValueError):
        write_snapshot(path, {"total_horas": 0})
    assert path.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [path]


def test_stale_estimate_is_immediate_refresh_is_shared_and_result_saved(tmp_path):
    bundle, runtime = tmp_path / "bundle.json", tmp_path / "runtime.json"
    old = estimate(NOW - CACHE_TTL)
    write_snapshot(bundle, old)
    started, release = Event(), Event()
    calls = []

    def fetcher(config, token):
        calls.append(config)
        started.set()
        assert release.wait(timeout=3)
        return estimate(datetime.now(timezone.utc))

    cache = EstimateCache(bundle, runtime, fetcher=fetcher)
    try:
        status = cache.status(DEFAULT_CONFIG, now=NOW)
        assert status.snapshot == old and status.refreshing
        assert started.wait(timeout=1)
        assert cache.status(DEFAULT_CONFIG, now=NOW).refreshing
        assert len(calls) == 1
        release.set()
        cache._future.result(timeout=2)
        status = cache.status(DEFAULT_CONFIG)
        assert not status.refreshing and not status.stale
        assert read_json(runtime) == status.snapshot
        assert read_json(bundle) == old
    finally:
        release.set()
        cache.close()


def test_failed_refresh_preserves_cache_and_retries_automatically(tmp_path):
    bundle, runtime = tmp_path / "bundle.json", tmp_path / "runtime.json"
    old = estimate(NOW - CACHE_TTL)
    write_snapshot(bundle, old)
    calls = []

    def fetcher(config, token):
        calls.append(1)
        raise DevelopmentHoursError("GitHub: limite de API (HTTP 403).")

    cache = EstimateCache(bundle, runtime, fetcher=fetcher)
    try:
        cache.status(DEFAULT_CONFIG, now=NOW)
        with pytest.raises(DevelopmentHoursError):
            cache._future.result(timeout=2)
        failed = cache.status(DEFAULT_CONFIG, now=NOW)
        assert failed.snapshot == old and failed.error and not failed.refreshing
        assert not runtime.exists()
        assert not cache.status(DEFAULT_CONFIG, now=NOW + RETRY_INTERVAL - timedelta(seconds=1)).refreshing
        assert cache.status(DEFAULT_CONFIG, now=NOW + RETRY_INTERVAL).refreshing
        with pytest.raises(DevelopmentHoursError):
            cache._future.result(timeout=2)
        assert len(calls) == 2
    finally:
        cache.close()


def test_newer_bundle_wins_over_old_runtime_and_corrupt_runtime(tmp_path):
    bundle, runtime = tmp_path / "bundle.json", tmp_path / "runtime.json"
    write_snapshot(bundle, estimate())
    write_snapshot(runtime, estimate(NOW - CACHE_TTL))
    cache = EstimateCache(bundle, runtime, fetcher=lambda *_: pytest.fail("Fresh bundle must not fetch"))
    try:
        assert cache.status(DEFAULT_CONFIG, now=NOW).snapshot["calculado_em"] == NOW.isoformat()
        runtime.write_text("{broken", encoding="utf-8")
        assert not cache.status(DEFAULT_CONFIG, now=NOW).refreshing
    finally:
        cache.close()
