from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest

from utils.ifdata_cache.durable_jobs import JobStateError, validate_job_spec
from utils.ifdata_cache.official_store import RevisionConflict
from utils.ifdata_cache.update_access import PermissionDenied, Principal, TokenIdentityVerifier, validate_action
from utils.ifdata_cache.update_api import (
    MAX_JSON_BYTES, MAX_REQUEST_JSON_BYTES, MAX_RESPONSE_JSON_BYTES,
    UpdateAPIClient, UpdateAPIError, handler_factory,
)
from utils.ifdata_cache.update_state import UpdateBusyError, UpdateStateError


TOKEN = "explicit-api-test-credential"


class Backend:
    def __init__(self):
        self.jobs = {}
        self.submitted = []
        self.revision = None
        self.idempotency = {}

    def submit(self, spec, principal, idempotency_key):
        validate_action(principal, "update")
        normalized = validate_job_spec(spec)
        if idempotency_key in self.idempotency:
            return self.jobs[self.idempotency[idempotency_key]]
        job = {"job_id": uuid4().hex, "status": "queued", "subject": principal.subject, "spec": normalized}
        self.jobs[job["job_id"]] = job
        self.idempotency[idempotency_key] = job["job_id"]
        self.submitted.append((spec, principal, idempotency_key))
        return job

    def get(self, job_id, principal):
        validate_action(principal, "read")
        job = self.jobs[job_id]
        if job["subject"] != principal.subject:
            raise PermissionDenied("Ownership differs")
        return job

    def list(self, principal):
        validate_action(principal, "read")
        return [job for job in self.jobs.values() if job["subject"] == principal.subject]

    def _action(self, job_id, principal, permission, status):
        validate_action(principal, permission)
        job = self.get(job_id, principal)
        job["status"] = status
        return job

    def retry(self, job_id, principal):
        return self._action(job_id, principal, "update", "queued")

    def cancel(self, job_id, principal):
        return self._action(job_id, principal, "update", "cancelled")

    def publish(self, job_id, principal):
        return self._action(job_id, principal, "publish", "published")

    def current(self, principal):
        validate_action(principal, "read")
        return {"revision_id": self.revision}

    def restore(self, revision_id, expected_parent, principal):
        validate_action(principal, "restore")
        if expected_parent != self.revision:
            raise RevisionConflict("Active revision changed")
        self.revision = revision_id
        return {"revision_id": revision_id, "subject": principal.subject}


@pytest.fixture
def running_server():
    servers = []

    def start(backend=None, verifier=None, handler=None):
        backend = Backend() if backend is None else backend
        verifier = verifier or TokenIdentityVerifier({
            TOKEN: {"subject": "analyst", "permissions": ["read", "update", "publish", "restore"]},
            "observer-test-credential": {"subject": "observer", "permissions": ["read"]},
            "updater-test-credential": {"subject": "updater", "permissions": ["read", "update"]},
        })
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler or handler_factory(backend, verifier))
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        thread.start()
        servers.append((server, thread))
        return f"http://127.0.0.1:{server.server_port}", backend

    yield start
    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def raw_request(url, method, path, *, body=None, token=TOKEN, headers=None):
    parsed = urlsplit(url)
    request_headers = {"Content-Type": "application/json"}
    if token is not None:
        request_headers["Authorization"] = f"Bearer {token}"
    request_headers.update(headers or {})
    if body is None and method == "POST":
        body = b"{}"
    if isinstance(body, dict):
        body = json.dumps(body).encode()
    connection = HTTPConnection(parsed.hostname, parsed.port, timeout=2)
    try:
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        data = response.read()
        return response.status, dict(response.getheaders()), json.loads(data)
    finally:
        connection.close()


def spec():
    return {"cache_type": "principal", "periods": ["202606"], "mode": "incremental"}


def test_real_http_client_submits_queries_actions_and_restores(running_server):
    url, backend = running_server()
    client = UpdateAPIClient(url, TOKEN, timeout=2)
    job = client.submit(spec(), "repeatable-request")
    assert job["status"] == "queued"
    assert backend.submitted[0][1].subject == "analyst"
    assert client.submit(spec(), "repeatable-request")["job_id"] == job["job_id"]
    assert len(backend.submitted) == 1
    assert client.get(job["job_id"]) == job
    assert client.list() == [job]
    assert client.cancel(job["job_id"])["status"] == "cancelled"
    assert client.retry(job["job_id"])["status"] == "queued"
    assert client.publish(job["job_id"])["status"] == "published"
    assert client.current() == {"revision_id": None}
    revision = uuid4().hex
    assert client.restore(revision, None) == {"revision_id": revision, "subject": "analyst"}
    assert client.current() == {"revision_id": revision}
    assert client.get(str(UUID(job["job_id"]))) == backend.jobs[job["job_id"]]


def test_backend_enforces_permissions_and_job_ownership(running_server):
    url, _ = running_server()
    owner = UpdateAPIClient(url, TOKEN)
    job = owner.submit(spec(), "owned-job")
    observer = UpdateAPIClient(url, "observer-test-credential")
    assert observer.list() == []
    with pytest.raises(UpdateAPIError) as error:
        observer.get(job["job_id"])
    assert error.value.status_code == 403
    with pytest.raises(UpdateAPIError) as error:
        observer.submit(spec(), "denied-job")
    assert error.value.status_code == 403
    updater = UpdateAPIClient(url, "updater-test-credential")
    own_job = updater.submit(spec(), "updater-owned-job")
    with pytest.raises(UpdateAPIError) as error:
        updater.publish(own_job["job_id"])
    assert error.value.status_code == 403
    with pytest.raises(UpdateAPIError) as error:
        updater.restore(uuid4().hex, None)
    assert error.value.status_code == 403


def test_request_actor_headers_never_replace_authenticated_identity(running_server):
    url, backend = running_server()
    status, _, job = raw_request(url, "POST", "/jobs", body=spec(), headers={
        "Idempotency-Key": "spoofed-actor", "X-Actor": "owner", "X-Role": "admin", "X-Permissions": "restore",
    })
    assert status == 202
    assert job["subject"] == backend.submitted[0][1].subject == "analyst"
    status, _, _ = raw_request(url, "POST", "/jobs", body={**spec(), "actor": "owner"},
                               headers={"Idempotency-Key": "body-actor"})
    assert status == 400
    assert len(backend.submitted) == 1


def test_injectable_identity_verifier_supports_institutional_headers(running_server):
    class InstitutionalVerifier:
        def authenticate(self, headers):
            if headers.get("X-Corporate-Assertion") != "verified-test-assertion":
                raise PermissionDenied()
            return Principal("institution:analyst", frozenset({"read"}))

    url, _ = running_server(verifier=InstitutionalVerifier())
    status, _, payload = raw_request(url, "GET", "/jobs", token=None,
                                     headers={"X-Corporate-Assertion": "verified-test-assertion"})
    assert status == 200 and payload == []


@pytest.mark.parametrize("token", [None, "unrecognized-test-credential"])
def test_invalid_credentials_are_denied_without_echo_or_cors(running_server, capsys, token):
    url, _ = running_server()
    status, headers, payload = raw_request(url, "GET", "/jobs", token=token)
    assert status == 401
    assert headers["WWW-Authenticate"] == "Bearer"
    assert not any(key.lower().startswith("access-control-") for key in headers)
    assert TOKEN not in json.dumps(payload)
    assert "unrecognized-test-credential" not in json.dumps(payload)
    captured = capsys.readouterr()
    assert TOKEN not in captured.out + captured.err


@pytest.mark.parametrize("path", ["/jobs?actor=owner", "/jobs?", "/jobs#fragment", "/jobs/not-a-uuid"])
def test_query_fragment_and_invalid_job_ids_are_rejected(running_server, path):
    url, _ = running_server()
    status, _, _ = raw_request(url, "GET", path)
    assert status == 400


def test_unknown_job_and_route_have_json_404(running_server):
    url, _ = running_server()
    for path in (f"/jobs/{uuid4().hex}", "/unknown"):
        status, headers, payload = raw_request(url, "GET", path)
        assert status == 404
        assert headers["Content-Type"].startswith("application/json")
        assert set(payload) == {"error"}


@pytest.mark.parametrize("body", [b"not-json", b"[]", b'{"label":NaN}', b'{"a":1,"a":2}'])
def test_malformed_or_ambiguous_json_is_rejected(running_server, body):
    url, backend = running_server()
    status, _, _ = raw_request(url, "POST", "/jobs", body=body, headers={"Idempotency-Key": "invalid-body"})
    assert status == 400 and backend.submitted == []


def test_request_body_limit_and_wrong_content_type(running_server):
    assert MAX_JSON_BYTES == MAX_REQUEST_JSON_BYTES == 64 * 1024
    url, backend = running_server()
    status, _, _ = raw_request(url, "POST", "/jobs", body=b" " * (MAX_JSON_BYTES + 1),
                               headers={"Idempotency-Key": "too-large"})
    assert status == 413 and backend.submitted == []
    status, _, _ = raw_request(url, "POST", "/jobs", body=spec(), headers={"Content-Type": "text/plain"})
    assert status == 415


def test_restore_requires_explicit_parent_and_does_not_accept_actor(running_server):
    url, backend = running_server()
    for body in ({"revision_id": uuid4().hex}, {"revision_id": uuid4().hex, "expected_parent": None, "actor": "owner"}):
        status, _, _ = raw_request(url, "POST", "/revisions/restore", body=body)
        assert status == 400 and backend.revision is None
    backend.revision = uuid4().hex
    status, _, _ = raw_request(url, "POST", "/revisions/restore", body={
        "revision_id": uuid4().hex, "expected_parent": uuid4().hex,
    })
    assert status == 409


@pytest.mark.parametrize("error", [JobStateError("private"), RevisionConflict("private"),
                                   UpdateBusyError("private"), UpdateStateError("private")])
def test_backend_conflicts_are_json_409(running_server, error):
    class ConflictingBackend(Backend):
        def list(self, principal):
            raise error

    url, _ = running_server(backend=ConflictingBackend())
    status, _, payload = raw_request(url, "GET", "/jobs")
    assert status == 409 and "private" not in json.dumps(payload)


@pytest.mark.parametrize("failure", [RuntimeError("private-token-or-path"), object(), "x" * (MAX_RESPONSE_JSON_BYTES + 1)])
def test_internal_errors_and_invalid_responses_are_bounded_and_generic(running_server, capsys, failure):
    class BrokenBackend(Backend):
        def list(self, principal):
            if isinstance(failure, RuntimeError):
                raise failure
            return failure

    url, _ = running_server(backend=BrokenBackend())
    status, _, payload = raw_request(url, "GET", "/jobs")
    assert status == 500
    assert len(json.dumps(payload).encode()) < 1024
    assert "private-token-or-path" not in json.dumps(payload)
    captured = capsys.readouterr()
    assert "private-token-or-path" not in captured.out + captured.err


def test_job_list_larger_than_request_limit_still_reaches_client(running_server):
    jobs = [{"job_id": uuid4().hex, "status": "succeeded", "result": {"summary": "x" * 900}}
            for _ in range(100)]
    encoded = json.dumps(jobs).encode("utf-8")
    assert MAX_REQUEST_JSON_BYTES < len(encoded) < MAX_RESPONSE_JSON_BYTES

    class LargeBackend(Backend):
        def list(self, principal):
            validate_action(principal, "read")
            return jobs

    url, _ = running_server(backend=LargeBackend())
    assert UpdateAPIClient(url, TOKEN).list() == jobs


def test_client_reads_no_more_than_response_limit():
    from email.message import Message

    reads = []

    class Response:
        headers = Message()
        headers["Content-Type"] = "application/json"

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, count):
            reads.append(count)
            return b" " * count

    class Opener:
        def open(self, *_args, **_kwargs):
            return Response()

    client = UpdateAPIClient("https://bank.example", TOKEN)
    client._opener = Opener()
    with pytest.raises(UpdateAPIError, match="excede o limite"):
        client.list()
    assert reads == [MAX_RESPONSE_JSON_BYTES + 1]


@pytest.mark.parametrize("url", ["http://institution.example", "ftp://127.0.0.1", "https://user:secret@bank.example",
    "https://bank.example?query=1", "https://bank.example#fragment", "https://bank.example?", "https://bank.example#",
    "https://bank.example:invalid", "https://bank.example:70000", "https://bank.example/\n", None, 42,
])
def test_client_requires_safe_service_url(url):
    with pytest.raises(ValueError):
        UpdateAPIClient(url, TOKEN)


@pytest.mark.parametrize("url", ["https://bank.example/update", "http://localhost:8080", "http://127.0.0.1", "http://[::1]:8080"])
def test_client_accepts_https_or_loopback_only(url):
    assert UpdateAPIClient(url, TOKEN).url == url


@pytest.mark.parametrize("timeout", [0, -1, 30.1, True, None, float("inf"), float("nan")])
def test_client_timeout_is_bounded(timeout):
    with pytest.raises(ValueError):
        UpdateAPIClient("https://bank.example", TOKEN, timeout=timeout)


def test_client_never_follows_a_redirect_with_its_credential(running_server):
    visits = []

    class Target(BaseHTTPRequestHandler):
        def do_GET(self):
            visits.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()

        def log_message(self, format, *args):
            pass

    target_url, _ = running_server(handler=Target)

    class Redirect(Target):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", target_url + "/jobs")
            self.end_headers()

    url, _ = running_server(handler=Redirect)
    with pytest.raises(UpdateAPIError) as error:
        UpdateAPIClient(url, TOKEN).list()
    assert error.value.status_code == 302 and visits == []
    assert TOKEN not in str(error.value)


def test_transport_error_and_client_repr_never_echo_token():
    class BrokenOpener:
        def open(self, *args, **kwargs):
            raise OSError(f"debug included {TOKEN}")

    client = UpdateAPIClient("https://bank.example", TOKEN)
    client._opener = BrokenOpener()
    assert TOKEN not in repr(client)
    with pytest.raises(UpdateAPIError) as error:
        client.list()
    assert TOKEN not in str(error.value)


def test_client_rejects_oversized_body_before_network():
    client = UpdateAPIClient("https://bank.example", TOKEN)
    with pytest.raises(ValueError):
        client.submit({"label": "x" * (MAX_JSON_BYTES + 1)}, "bounded")
