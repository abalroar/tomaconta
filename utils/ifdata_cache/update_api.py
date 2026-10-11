"""API HTTP portátil do autosserviço; execução e autorização ficam no backend."""
from __future__ import annotations

from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler
import json
import re
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from .durable_jobs import JobStateError
from .official_store import RevisionConflict
from .update_access import IdentityVerifier, PermissionDenied, Principal
from .update_state import UpdateBusyError, UpdateStateError


MAX_REQUEST_JSON_BYTES = 64 * 1024
MAX_RESPONSE_JSON_BYTES = 2 * 1024 * 1024
# Compatibilidade com os consumidores que nomeavam o limite das solicitações.
MAX_JSON_BYTES = MAX_REQUEST_JSON_BYTES
_UUID = re.compile(r"^(?:[a-fA-F0-9]{32}|[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12})$")


class UpdateAPIError(RuntimeError):
    """Falha HTTP ou de transporte, sem conteúdo de credenciais na mensagem."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class _RequestError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class _ResponseError(RuntimeError):
    pass


def _uuid(value) -> str:
    if not isinstance(value, str) or not _UUID.fullmatch(value):
        raise _RequestError(400, "Identificador inválido.")
    return UUID(value).hex


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Campo JSON duplicado.")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("Valor JSON inválido.")


def _decode_json(data: bytes):
    return json.loads(data.decode("utf-8"), object_pairs_hook=_json_object, parse_constant=_invalid_constant)


def handler_factory(backend, verifier: IdentityVerifier):
    """Cria um handler para ThreadingHTTPServer com identidade injetada."""

    class UpdateHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "TomaContaUpdate"
        sys_version = ""

        def log_message(self, format, *args):
            # A URL ou mensagens recebidas não entram em logs do servidor.
            pass

        def _send(self, status: int, payload):
            try:
                data = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
            except (TypeError, ValueError, UnicodeError):
                raise _ResponseError("Resposta do serviço inválida.") from None
            if len(data) > MAX_RESPONSE_JSON_BYTES:
                raise _ResponseError("Resposta excede o limite.")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if status == 401:
                self.send_header("WWW-Authenticate", "Bearer")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            self.wfile.write(data)

        def _error(self, status: int, message: str):
            self._send(status, {"error": message})

        def _body(self) -> dict:
            if self.headers.get("Transfer-Encoding") is not None:
                raise _RequestError(400, "Formato de corpo não suportado.")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not re.fullmatch(r"[0-9]+", lengths[0]):
                raise _RequestError(400, "Tamanho do corpo inválido.")
            length = int(lengths[0])
            if length > MAX_REQUEST_JSON_BYTES:
                raise _RequestError(413, "Corpo da solicitação excede o limite.")
            if self.headers.get_content_type() != "application/json":
                raise _RequestError(415, "Envie um corpo JSON.")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise _RequestError(400, "Corpo da solicitação incompleto.")
            try:
                payload = _decode_json(raw)
            except (ValueError, UnicodeError):
                raise _RequestError(400, "Corpo JSON inválido.") from None
            if not isinstance(payload, dict):
                raise _RequestError(400, "O corpo deve ser um objeto JSON.")
            return payload

        def _authenticate(self) -> Principal:
            # Mantém a possibilidade de rejeitar Authorization duplicado.
            authorizations = self.headers.get_all("Authorization", [])
            if len(authorizations) > 1:
                raise PermissionDenied("Credencial de atualização não reconhecida.")
            principal = verifier.authenticate(dict(self.headers.items()))
            if not isinstance(principal, Principal):
                raise PermissionDenied("Credencial de atualização não reconhecida.")
            return principal

        def _dispatch(self, method: str):
            self.connection.settimeout(30)
            try:
                principal = self._authenticate()
            except PermissionDenied:
                self._error(401, "Credencial de atualização não reconhecida.")
                return
            except Exception:
                self._error(500, "Falha interna do serviço de atualização.")
                return

            job_lookup = False
            try:
                target = urlsplit(self.path)
                if target.scheme or target.netloc or "?" in self.path or "#" in self.path:
                    raise _RequestError(400, "Rota inválida.")
                path = target.path
                if method == "GET":
                    lengths = self.headers.get_all("Content-Length", [])
                    if (self.headers.get("Transfer-Encoding") is not None or len(lengths) > 1
                            or (lengths and lengths[0] != "0")):
                        raise _RequestError(400, "Esta consulta não aceita corpo.")
                    if path == "/jobs":
                        result = backend.list(principal)
                    elif path == "/revisions/current":
                        result = backend.current(principal)
                    elif path.startswith("/jobs/") and path.count("/") == 2:
                        job_id = _uuid(path.rsplit("/", 1)[1])
                        job_lookup = True
                        result = backend.get(job_id, principal)
                    else:
                        raise _RequestError(404, "Rota não encontrada.")
                    self._send(200, result)
                    return

                if path == "/jobs":
                    payload = self._body()
                    keys = self.headers.get_all("Idempotency-Key", [])
                    if (len(keys) != 1 or not keys[0] or len(keys[0]) > 200
                            or any(character.isspace() for character in keys[0])):
                        raise _RequestError(400, "Chave de idempotência inválida.")
                    self._send(202, backend.submit(payload, principal, keys[0]))
                    return
                if path == "/revisions/restore":
                    payload = self._body()
                    if set(payload) != {"revision_id", "expected_parent"}:
                        raise _RequestError(400, "Campos de restauração inválidos.")
                    revision_id = _uuid(payload["revision_id"])
                    parent = None if payload["expected_parent"] is None else _uuid(payload["expected_parent"])
                    self._send(200, backend.restore(revision_id, parent, principal))
                    return
                match = re.fullmatch(r"/jobs/([^/]+)/(retry|cancel|publish)", path)
                if match:
                    job_id = _uuid(match.group(1))
                    if self._body():
                        raise _RequestError(400, "Esta ação não aceita opções adicionais.")
                    action = match.group(2)
                    result = getattr(backend, action)(job_id, principal)
                    self._send(200 if action == "cancel" else 202, result)
                    return
                raise _RequestError(404, "Rota não encontrada.")
            except _RequestError as exc:
                self._error(exc.status, str(exc))
            except PermissionDenied:
                self._error(403, "Ação de atualização não autorizada.")
            except (JobStateError, RevisionConflict, UpdateBusyError, UpdateStateError):
                self._error(409, "O estado mudou ou há uma operação em andamento; recarregue antes de tentar novamente.")
            except KeyError:
                self._error(404, "Registro não encontrado.")
            except ValueError:
                self._error(404 if job_lookup else 400, "Registro não encontrado." if job_lookup else "Solicitação inválida.")
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
            except Exception:
                self._error(500, "Falha interna do serviço de atualização.")

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def _method_not_allowed(self):
            self._error(405, "Método não permitido.")

        do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = _method_not_allowed

    return UpdateHandler


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UpdateAPIClient:
    """Cliente sem redirects, com HTTPS obrigatório fora do loopback local."""

    __slots__ = ("url", "timeout", "_token", "_opener")

    def __init__(self, url: str, token: str, *, timeout: float = 30):
        if not isinstance(url, str):
            raise ValueError("URL do serviço de atualização inválida.")
        try:
            parsed = urlsplit(url)
            port = parsed.port
            local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            invalid = (not isinstance(url, str) or any(character.isspace() for character in url)
                       or not parsed.hostname or parsed.username is not None or parsed.password is not None
                       or "?" in url or "#" in url or (port is not None and not 0 < port <= 65535)
                       or not (parsed.scheme == "https" or (parsed.scheme == "http" and local)))
        except (TypeError, ValueError):
            raise ValueError("URL do serviço de atualização inválida.") from None
        if invalid:
            raise ValueError("Use HTTPS para o serviço de atualização, ou HTTP no loopback local.")
        if (not isinstance(token, str) or not token or not token.isascii()
                or any(character.isspace() or ord(character) < 32 for character in token)):
            raise ValueError("Configure uma credencial explícita para o serviço de atualização.")
        if type(timeout) not in {int, float} or not 0 < timeout <= 30:
            raise ValueError("Timeout deve ser maior que zero e de até 30 segundos.")
        self.url = url.rstrip("/")
        self.timeout = timeout
        self._token = token
        self._opener = build_opener(_NoRedirect())

    def __repr__(self):
        return "UpdateAPIClient(credential=configured)"

    def _request(self, method: str, path: str, payload=None, *, idempotency_key=None):
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        data = None
        if method == "POST":
            try:
                data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            except (TypeError, ValueError, UnicodeError):
                raise ValueError("Solicitação JSON inválida.") from None
            if len(data) > MAX_REQUEST_JSON_BYTES:
                raise ValueError("Corpo da solicitação excede o limite.")
            headers["Content-Type"] = "application/json"
        if idempotency_key is not None:
            if (not isinstance(idempotency_key, str) or not idempotency_key or len(idempotency_key) > 200
                    or any(character.isspace() or ord(character) < 32 for character in idempotency_key)):
                raise ValueError("Chave de idempotência inválida.")
            headers["Idempotency-Key"] = idempotency_key
        request = Request(self.url + path, data=data, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                if response.headers.get_content_type() != "application/json":
                    raise UpdateAPIError("Resposta do serviço não é JSON.")
                raw = response.read(MAX_RESPONSE_JSON_BYTES + 1)
                if len(raw) > MAX_RESPONSE_JSON_BYTES:
                    raise UpdateAPIError("Resposta do serviço excede o limite.")
                try:
                    return _decode_json(raw)
                except (ValueError, UnicodeError):
                    raise UpdateAPIError("Resposta JSON do serviço inválida.") from None
        except HTTPError as exc:
            status = exc.code
            exc.close()
            raise UpdateAPIError(f"Serviço de atualização recusou a solicitação (HTTP {status}).", status) from None
        except UpdateAPIError:
            raise
        except Exception:
            raise UpdateAPIError("Não foi possível consultar o serviço de atualização.") from None

    def submit(self, spec: Mapping, idempotency_key: str):
        if not isinstance(spec, Mapping):
            raise ValueError("O plano deve ser um objeto JSON.")
        return self._request("POST", "/jobs", dict(spec), idempotency_key=idempotency_key)

    def get(self, job_id: str):
        return self._request("GET", f"/jobs/{_uuid(job_id)}")

    def list(self):
        return self._request("GET", "/jobs")

    def retry(self, job_id: str):
        return self._request("POST", f"/jobs/{_uuid(job_id)}/retry", {})

    def cancel(self, job_id: str):
        return self._request("POST", f"/jobs/{_uuid(job_id)}/cancel", {})

    def publish(self, job_id: str):
        return self._request("POST", f"/jobs/{_uuid(job_id)}/publish", {})

    def current(self):
        return self._request("GET", "/revisions/current")

    def restore(self, revision_id: str, expected_parent: str | None):
        return self._request("POST", "/revisions/restore", {
            "revision_id": _uuid(revision_id),
            "expected_parent": None if expected_parent is None else _uuid(expected_parent),
        })
