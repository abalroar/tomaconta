"""Limites de paginação da atualização completa de taxas."""

from utils.ifdata_cache.taxas_juros import TaxasJurosCache


def row():
    return {
        "InicioPeriodo": "2026-01-05", "FimPeriodo": "2026-01-09",
        "Segmento": "PESSOA FÍSICA", "Modalidade": "Crédito pessoal",
        "Posicao": 1, "InstituicaoFinanceira": "Banco A",
        "TaxaJurosAoMes": 1.0, "TaxaJurosAoAno": 12.0, "cnpj8": "12345678",
    }


class Response:
    status_code = 200

    def __init__(self, values):
        self.values = values

    def json(self):
        return {"value": self.values}


def test_full_page_at_limit_is_incomplete_and_never_marked_success(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("utils.ifdata_cache.taxas_juros.MAX_RECORDS", 1)

    def request(url, **kwargs):
        calls.append(kwargs["params"]["$skip"])
        return Response([row()])

    monkeypatch.setattr("utils.ifdata_cache.taxas_juros.requests.get", request)
    cache = TaxasJurosCache(tmp_path)
    result = cache.extrair_completo("2026-01-01", "2026-01-31")
    assert not result.sucesso
    assert result.metadata["truncado"] is True
    assert result.metadata["paginas_processadas"] == 50
    assert calls == list(range(50))
    assert "incompleta" in result.mensagem
    assert not cache.existe()


def test_empty_next_page_confirms_end_of_pagination(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("utils.ifdata_cache.taxas_juros.MAX_RECORDS", 1)

    def request(url, **kwargs):
        calls.append(kwargs["params"]["$skip"])
        return Response([row()] if len(calls) == 1 else [])

    monkeypatch.setattr("utils.ifdata_cache.taxas_juros.requests.get", request)
    result = TaxasJurosCache(tmp_path).extrair_completo("2026-01-01", "2026-01-31")
    assert result.sucesso
    assert result.metadata["truncado"] is False
    assert result.metadata["paginas_processadas"] == 2
    assert len(result.dados) == 1
