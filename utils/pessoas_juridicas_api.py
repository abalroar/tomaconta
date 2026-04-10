"""Cliente resiliente para /informes/rest/pessoasJuridicas."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

import requests


PESSOAS_JURIDICAS_URL = "https://www3.bcb.gov.br/informes/rest/pessoasJuridicas"
DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": "Mozilla/5.0 (compatible; TomaConta/1.0)",
    "Referer": "https://www3.bcb.gov.br/informes/",
}


@dataclass(frozen=True)
class PessoasJuridicasApiResult:
    sucesso: bool
    status: str
    mensagem: str
    payload: dict[str, Any] | None = None
    status_code: int | None = None
    method: str | None = None
    url: str = PESSOAS_JURIDICAS_URL


def _digits_only(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _parse_json_response(response: requests.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except Exception:
        data = json.loads(response.text)
    if isinstance(data, dict):
        return data
    return {"content": data}


def _map_status_message(status_code: int, method: str) -> tuple[str, str]:
    if status_code == 400:
        return (
            "contract_changed",
            f"API de pessoas jurídicas rejeitou a requisição ({method} HTTP 400). "
            "O contrato do endpoint pode ter mudado para o app atual.",
        )
    if status_code == 401:
        return (
            "unauthorized",
            "API de pessoas jurídicas respondeu HTTP 401. A consulta exige autenticação não atendida.",
        )
    if status_code == 403:
        return (
            "forbidden",
            "API de pessoas jurídicas respondeu HTTP 403. A fonte bloqueou ou negou a consulta.",
        )
    if status_code == 404:
        return (
            "not_found",
            "Endpoint de pessoas jurídicas não encontrado (HTTP 404).",
        )
    if status_code == 405:
        return (
            "contract_changed",
            f"API de pessoas jurídicas não aceita {method} (HTTP 405). O contrato do endpoint mudou.",
        )
    if 500 <= status_code <= 599:
        return (
            "source_unavailable",
            f"API de pessoas jurídicas indisponível no momento (HTTP {status_code}).",
        )
    return (
        "source_unavailable",
        f"API de pessoas jurídicas falhou com HTTP {status_code}.",
    )


def consultar_pessoas_juridicas(
    cnpj: str,
    id_bacen: str = "",
    *,
    timeout: int = 40,
) -> PessoasJuridicasApiResult:
    params = {"cnpj": _digits_only(cnpj)}
    if id_bacen:
        params["idBacen"] = str(id_bacen).strip()

    tentativas = [
        ("GET", {"params": params}),
        ("POST", {"json": params}),
    ]
    respostas_falha: list[PessoasJuridicasApiResult] = []

    for method, extra in tentativas:
        try:
            response = requests.request(
                method,
                PESSOAS_JURIDICAS_URL,
                timeout=timeout,
                headers=DEFAULT_HEADERS,
                **extra,
            )
        except requests.exceptions.Timeout:
            respostas_falha.append(
                PessoasJuridicasApiResult(
                    sucesso=False,
                    status="network_timeout",
                    mensagem="Timeout ao consultar a API de pessoas jurídicas.",
                    method=method,
                )
            )
            continue
        except requests.exceptions.RequestException as exc:
            respostas_falha.append(
                PessoasJuridicasApiResult(
                    sucesso=False,
                    status="network_error",
                    mensagem=f"Erro de rede ao consultar a API de pessoas jurídicas: {exc}",
                    method=method,
                )
            )
            continue

        if response.status_code == 200:
            try:
                payload = _parse_json_response(response)
            except Exception as exc:
                return PessoasJuridicasApiResult(
                    sucesso=False,
                    status="invalid_payload",
                    mensagem=f"API de pessoas jurídicas retornou payload inválido: {exc}",
                    status_code=200,
                    method=method,
                )
            return PessoasJuridicasApiResult(
                sucesso=True,
                status="ok",
                mensagem="Consulta realizada com sucesso.",
                payload=payload,
                status_code=200,
                method=method,
            )

        status, mensagem = _map_status_message(response.status_code, method)
        resposta = PessoasJuridicasApiResult(
            sucesso=False,
            status=status,
            mensagem=mensagem,
            status_code=response.status_code,
            method=method,
        )
        respostas_falha.append(resposta)

        if response.status_code in {401, 403, 404}:
            return resposta
        if response.status_code not in {400, 405}:
            return resposta

    if respostas_falha:
        ultimo = respostas_falha[-1]
        if any(item.status == "contract_changed" for item in respostas_falha):
            return PessoasJuridicasApiResult(
                sucesso=False,
                status="contract_changed",
                mensagem=(
                    "A API de pessoas jurídicas não respondeu ao contrato esperado "
                    "após tentativas GET/POST. Trate como fonte indisponível/contrato alterado."
                ),
                status_code=ultimo.status_code,
                method=ultimo.method,
            )
        return ultimo

    return PessoasJuridicasApiResult(
        sucesso=False,
        status="source_unavailable",
        mensagem="API de pessoas jurídicas indisponível.",
    )
