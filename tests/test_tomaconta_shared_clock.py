"""Clock behavior with fake queue/Actions APIs; no live requests or credentials."""
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("shared_clock", ROOT / "scripts/tomaconta_shared_clock.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def context(**updates):
    return {"GITHUB_REPOSITORY": c.REPOSITORY, "GITHUB_REPOSITORY_ID": c.REPOSITORY_ID,
            "GITHUB_REPOSITORY_OWNER_ID": c.OWNER_ID, "GITHUB_REF": "refs/heads/main",
            "GITHUB_WORKFLOW_REF": c.CLOCK_WORKFLOW, "GITHUB_EVENT_NAME": "schedule",
            "GITHUB_SERVER_URL": "https://github.com", "GITHUB_API_URL": "https://api.github.com",
            "GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "12345", "GITHUB_TOKEN": "ephemeral-test-token",
            "TOMACONTA_SHARED_ENABLED": "true", "TOMACONTA_REPOSITORY_PRIVATE": "false", **updates}


class API:
    def __init__(self, jobs=None, *, active=None, failure=None, packet=None):
        self.jobs = jobs or []
        self.active = active
        self.failure = failure
        self.packet = packet
        self.calls = []

    def request(self, method, url, *, data=None):
        self.calls.append((method, url, data))
        if self.failure and self.failure(method, url):
            raise c.ClockError("API do relógio respondeu HTTP 403")
        if url == c.JOBS_URL:
            return self.packet if self.packet is not None else {"jobs": self.jobs}
        if method == "GET":
            query = parse_qs(urlsplit(url).query)
            assert query["branch"] == ["main"] and query["per_page"] == ["1"]
            status = query["status"][0]
            runs = ([{"id": 99, "workflow_id": c.EXECUTOR_WORKFLOW_ID, "head_branch": "main", "status": status}]
                    if self.active == status else [])
            return {"total_count": len(runs), "workflow_runs": runs}
        assert url == c.DISPATCH_URL
        return None


def execute(api, **kwargs):
    return c.run_clock(env=context(), client_factory=lambda token: api,
                       now=datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc), **kwargs)


def test_queued_dispatches_only_original_main_once_and_logs_parent_run():
    api = API([{"id": "b" * 32, "status": "queued"}])
    result = execute(api)
    assert result == {"clockRunId": "12345", "clockEvent": "schedule", "utc": "2026-11-07T12:00:00+00:00",
                      "queuedJobIds": ["b" * 32], "runningJobIds": [], "outcome": "dispatched",
                      "executorEvent": "workflow_dispatch"}
    mutations = [call for call in api.calls if call[0] != "GET"]
    assert mutations == [("POST", c.DISPATCH_URL, {"ref": "main"})]
    assert len(api.calls) == 7
    assert "ephemeral-test-token" not in json.dumps(result)


def test_empty_queue_avoids_github_entirely():
    api = API([{"id": "a" * 32, "status": "succeeded"}])
    assert execute(api)["outcome"] == "empty"
    assert api.calls == [("GET", c.JOBS_URL, None)]


@pytest.mark.parametrize("status", c.ACTIVE_RUN_STATUSES)
def test_active_executor_blocks_dispatch_for_every_active_state(status):
    api = API([{"id": "b" * 32, "status": "queued"}], active=status)
    result = execute(api)
    assert result["outcome"] == "executor_active" and result["executorRunId"] == "99"
    assert all(method == "GET" for method, *_ in api.calls)


def test_running_job_without_active_executor_can_recover_via_original_lease_check():
    # The public endpoint deliberately does not disclose the lease. No guessed
    # clock-side timeout may strand a job after a runner has died.
    api = API([{"id": "c" * 32, "status": "running"}])
    result = execute(api)
    assert result["runningJobIds"] == ["c" * 32] and result["outcome"] == "dispatched"
    assert sum(method == "POST" for method, *_ in api.calls) == 1


@pytest.mark.parametrize("stage", ["jobs", "runs", "dispatch"])
def test_api_failure_stops_without_retry(stage):
    api = API([{"id": "b" * 32, "status": "queued"}], failure=lambda method, url:
              (stage == "jobs" and url == c.JOBS_URL) or
              (stage == "runs" and method == "GET" and url != c.JOBS_URL) or
              (stage == "dispatch" and method == "POST"))
    with pytest.raises(c.ClockError, match="HTTP 403"):
        execute(api)
    assert sum(method == "POST" for method, *_ in api.calls) == (1 if stage == "dispatch" else 0)
    assert len(api.calls) == {"jobs": 1, "runs": 2, "dispatch": 7}[stage]


@pytest.mark.parametrize("updates", [
    {"GITHUB_TOKEN": ""}, {"GITHUB_REPOSITORY": "other/repo"}, {"GITHUB_REPOSITORY_ID": "1"},
    {"GITHUB_REPOSITORY_OWNER_ID": "1"}, {"GITHUB_REF": "refs/heads/other"},
    {"GITHUB_EVENT_NAME": "workflow_dispatch"}, {"TOMACONTA_REPOSITORY_PRIVATE": "true"},
    {"TOMACONTA_SHARED_ENABLED": "false"}, {"GITHUB_WORKFLOW_REF": "other/workflow@main"},
])
def test_missing_token_or_wrong_context_never_contacts_an_api(updates):
    def forbidden(_token):
        pytest.fail("An invalid context must not construct an API client")
    with pytest.raises(c.ClockError):
        c.run_clock(env=context(**updates), client_factory=forbidden)


@pytest.mark.parametrize("packet", [
    {}, {"jobs": "not-list"}, {"jobs": [{"id": "bad", "status": "queued"}]},
    {"jobs": [{"id": int("1" * 32), "status": "queued"}]},
    {"jobs": [{"id": "a" * 32, "status": "unknown"}]},
    {"jobs": [{"id": "a" * 32, "status": "queued"}] * 2},
    {"jobs": [{"id": f"{i:032x}", "status": "queued"} for i in range(5)]},
    {"jobs": [{"id": f"{i:032x}", "status": "succeeded"} for i in range(41)]},
])
def test_malformed_or_excessive_queue_fails_closed(packet):
    api = API(packet=packet)
    with pytest.raises(c.ClockError):
        execute(api)
    assert api.calls == [("GET", c.JOBS_URL, None)]


def test_incomplete_github_response_cannot_be_treated_as_no_active_runs():
    api = API([{"id": "a" * 32, "status": "queued"}])
    original = api.request
    def incomplete(method, url, **kwargs):
        if url != c.JOBS_URL:
            return {"total_count": 1, "workflow_runs": []}
        return original(method, url, **kwargs)
    api.request = incomplete
    with pytest.raises(c.ClockError, match="execuções"):
        execute(api)


def test_filtered_active_history_blocks_even_with_many_matching_runs():
    packet = {"total_count": 250, "workflow_runs": [{"id": 99, "workflow_id": c.EXECUTOR_WORKFLOW_ID,
                                                    "head_branch": "main", "status": "queued"}]}
    assert c.active_run(packet, "queued") == "99"


class Response:
    def __init__(self, payload=b'{}', *, status=200, content_type="application/json"):
        self.payload, self.status = payload, status
        self.headers = {"Content-Type": content_type}
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def read(self, size):
        return self.payload[:size]


class Opener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
    def open(self, request, *, timeout):
        self.calls.append((request, timeout))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def test_http_auth_only_goes_to_github_and_dispatch_has_no_bootstrap_input():
    opener = Opener([Response(b'{"jobs":[]}'), Response(b"", status=204)])
    api = c.Client("ephemeral-test-token", opener=opener)
    api.request("GET", c.JOBS_URL)
    api.request("POST", c.DISPATCH_URL, data={"ref": "main"})
    public, dispatch = [item[0] for item in opener.calls]
    assert public.get_header("Authorization") is None
    assert public.get_header("User-agent") == c.USER_AGENT
    assert dispatch.get_header("Authorization") == "Bearer ephemeral-test-token"
    assert json.loads(dispatch.data) == {"ref": "main"}
    assert all(timeout == 15 for _, timeout in opener.calls)
    with pytest.raises(c.ClockError, match="Destino"):
        api.request("POST", "https://example.invalid/dispatch", data={"ref": "main"})
    assert len(opener.calls) == 2


@pytest.mark.parametrize("response", [
    HTTPError(c.JOBS_URL, 403, "body contains ephemeral-test-token", {}, io.BytesIO(b"ephemeral-test-token")),
    HTTPError(c.DISPATCH_URL, 302, "redirect with ephemeral-test-token", {}, None),
    URLError("ephemeral-test-token"), TimeoutError("ephemeral-test-token"),
    Response(b"ephemeral-test-token", content_type="text/html"), Response(b"not JSON"),
])
def test_http_failures_are_sanitized_and_never_retried(response):
    opener = Opener([response])
    with pytest.raises(c.ClockError) as error:
        c.Client("ephemeral-test-token", opener=opener).request("GET", c.JOBS_URL)
    assert "ephemeral-test-token" not in str(error.value)
    assert len(opener.calls) == 1


def test_main_does_not_print_unexpected_exception_or_credential(monkeypatch, capsys):
    def failure():
        raise RuntimeError("ephemeral-test-token")
    monkeypatch.setattr(c, "run_clock", failure)
    assert c.main() == 1
    captured = capsys.readouterr()
    assert "ephemeral-test-token" not in captured.out + captured.err
    assert json.loads(captured.err)["outcome"] == "failed"
