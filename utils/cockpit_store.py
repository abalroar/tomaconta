"""Carteiras do Cockpit: um JSON versionado no GitHub, ou em disco sem credencial.

Cada banco é guardado pelo código oficial; o nome só serve para exibição. O branch próprio
evita que um salvamento altere o `main` ou reinicie o site.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import requests

PATH = "data/cockpit_carteiras.json"
BRANCH = "dados-carteiras"
DEFAULT_REPO = "abalroar/tomaconta"
MAX_PORTFOLIOS = 200
MAX_MEMBERS = 150
MAX_NAME = 60
API = "https://api.github.com/repos"


def empty():
    return {"schema_version": 1, "carteiras": []}


def repo_name():
    return os.getenv("TOMACONTA_CARTEIRAS_REPO", DEFAULT_REPO)


def clean_name(value):
    return " ".join(str(value or "").split())


def validate(payload):
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("carteiras"), list):
        raise ValueError("Formato de carteiras inválido.")
    if len(payload["carteiras"]) > MAX_PORTFOLIOS:
        raise ValueError(f"Limite de {MAX_PORTFOLIOS} carteiras atingido.")
    seen = set()
    for portfolio in payload["carteiras"]:
        name = clean_name(portfolio.get("nome"))
        if not name or len(name) > MAX_NAME:
            raise ValueError(f"O nome deve ter de 1 a {MAX_NAME} caracteres.")
        if name.casefold() in seen:
            raise ValueError(f"Carteira duplicada: {name}")
        seen.add(name.casefold())
        members = portfolio.get("membros")
        if not isinstance(members, list) or len(members) > MAX_MEMBERS:
            raise ValueError(f"A carteira aceita até {MAX_MEMBERS} instituições.")
        if any(not str(item.get("id") or "").strip() or not str(item.get("label") or "").strip() for item in members):
            raise ValueError("Instituição sem identidade.")
    return payload


def find(payload, name):
    key = clean_name(name).casefold()
    return next((item for item in payload["carteiras"] if clean_name(item["nome"]).casefold() == key), None)


def upsert(payload, name, banks, identities):
    """Cria ou substitui pelo nome, sem diferenciar maiúsculas."""
    name = clean_name(name)
    missing = [bank for bank in banks if not identities.get(bank)]
    if missing:
        raise ValueError("Instituição sem código oficial: " + ", ".join(missing))
    entry = {"nome": name, "membros": [{"id": identities[bank], "label": bank} for bank in banks],
             "atualizado_em": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    others = [item for item in payload["carteiras"] if clean_name(item["nome"]).casefold() != name.casefold()]
    return validate({**payload, "carteiras": sorted([*others, entry], key=lambda item: item["nome"].casefold())})


def remove(payload, name):
    key = clean_name(name).casefold()
    return validate({**payload, "carteiras": [item for item in payload["carteiras"] if clean_name(item["nome"]).casefold() != key]})


def resolve(portfolio, identities):
    """Bancos encontrados pelo código na base atual e os que saíram dela."""
    by_code = {code: name for name, code in identities.items()}
    found, missing = [], []
    for member in portfolio["membros"]:
        name = by_code.get(member["id"])
        found.append(name) if name else missing.append(member["label"])
    return found, missing


class LocalStore:
    """Sem credencial, como em um servidor próprio: o volume persistente guarda o arquivo."""

    def __init__(self, root):
        self.path = Path(root) / "data/cache/cockpit/carteiras.json"

    def read(self):
        if not self.path.exists():
            return empty(), None
        return validate(json.loads(self.path.read_text(encoding="utf-8"))), None

    def write(self, payload, version, message):
        validate(payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)


class GitHubStore:
    def __init__(self, token, repo=None, *, client=requests):
        self.token, self.repo, self.client = token, repo or repo_name(), client
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

    def _ensure_branch(self):
        base = f"{API}/{self.repo}/git"
        if self.client.get(f"{base}/ref/heads/{BRANCH}", headers=self.headers, timeout=30).status_code != 404:
            return
        head = self.client.get(f"{base}/ref/heads/main", headers=self.headers, timeout=30)
        head.raise_for_status()
        created = self.client.post(f"{base}/refs", headers=self.headers, timeout=30,
                                   json={"ref": f"refs/heads/{BRANCH}", "sha": head.json()["object"]["sha"]})
        if created.status_code not in {201, 422}:
            created.raise_for_status()

    def read(self):
        response = self.client.get(f"{API}/{self.repo}/contents/{PATH}", params={"ref": BRANCH}, headers=self.headers, timeout=30)
        if response.status_code == 404:
            return empty(), None
        response.raise_for_status()
        data = response.json()
        return validate(json.loads(base64.b64decode(data["content"]).decode("utf-8"))), data["sha"]

    def write(self, payload, version, message):
        """Só confirma depois de reler; o histórico de commits permite recuperar qualquer versão."""
        validate(payload)
        self._ensure_branch()
        body = {"message": message, "branch": BRANCH,
                "content": base64.b64encode(json.dumps(payload, ensure_ascii=False, indent=2).encode()).decode()}
        if version:
            body["sha"] = version
        response = self.client.put(f"{API}/{self.repo}/contents/{PATH}", headers=self.headers, json=body, timeout=30)
        if response.status_code in {409, 422}:
            raise ConflictError("Outra pessoa salvou ao mesmo tempo.")
        response.raise_for_status()
        checked, _ = self.read()
        if checked != payload:
            raise RuntimeError("O GitHub recebeu a gravação, mas a confirmação de leitura falhou.")


class ConflictError(ValueError):
    pass


def save(store, change, message):
    """Aplica a mudança sobre a versão mais recente; repete uma vez se outra pessoa salvou antes."""
    for attempt in (1, 2):
        payload, version = store.read()
        updated = change(payload)
        try:
            store.write(updated, version, message)
            return updated
        except ConflictError:
            if attempt == 2:
                raise
