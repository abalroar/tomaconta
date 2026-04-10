import json

from utils.pessoas_juridicas_api import consultar_pessoas_juridicas


class _Response:
    def __init__(self, status_code, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {})

    def json(self):
        if self._payload is None:
            raise ValueError("sem json")
        return self._payload


def test_consultar_pessoas_juridicas_success(monkeypatch):
    def _request(method, url, **kwargs):
        assert method == "GET"
        assert kwargs["params"]["cnpj"] == "12345678000199"
        return _Response(200, payload={"orgaos": []})

    monkeypatch.setattr("utils.pessoas_juridicas_api.requests.request", _request)

    result = consultar_pessoas_juridicas("12.345.678/0001-99")

    assert result.sucesso is True
    assert result.status == "ok"
    assert result.payload == {"orgaos": []}


def test_consultar_pessoas_juridicas_detects_contract_change_after_get_and_post(monkeypatch):
    calls = []

    def _request(method, url, **kwargs):
        calls.append(method)
        if method == "GET":
            return _Response(400, payload={"erro": "bad request"})
        return _Response(405, payload={"erro": "method not allowed"})

    monkeypatch.setattr("utils.pessoas_juridicas_api.requests.request", _request)

    result = consultar_pessoas_juridicas("12345678000199")

    assert calls == ["GET", "POST"]
    assert result.sucesso is False
    assert result.status == "contract_changed"
    assert "contrato" in result.mensagem.lower()


def test_consultar_pessoas_juridicas_stops_on_forbidden(monkeypatch):
    def _request(method, url, **kwargs):
        return _Response(403, payload={"erro": "forbidden"})

    monkeypatch.setattr("utils.pessoas_juridicas_api.requests.request", _request)

    result = consultar_pessoas_juridicas("12345678000199")

    assert result.sucesso is False
    assert result.status == "forbidden"
    assert result.method == "GET"
