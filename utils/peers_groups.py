"""Grupos com identidade explícita e publicação GitHub com controle de revisão."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
from pathlib import Path

import requests

GROUP_PATH = "data/peer_groups_v2.json"


def validate(payload):
    if not isinstance(payload, dict) or payload.get("schema_version") != 2 or not isinstance(payload.get("groups"), list):
        raise ValueError("Formato de grupos inválido (esperado schema 2).")
    names = set()
    for group in payload["groups"]:
        if not isinstance(group, dict) or not isinstance(group.get("name"), str) or not group["name"].strip() or group.get("base") not in ("Consolidada / Prudencial", "Individual"):
            raise ValueError("Nome ou base do grupo inválido.")
        identity = (group["base"], group["name"].casefold())
        if identity in names:
            raise ValueError("Grupo duplicado na mesma base.")
        names.add(identity)
        members = group.get("members")
        if not isinstance(members, list) or not members:
            raise ValueError("Grupo sem integrantes.")
        ids = set()
        for member in members:
            if not isinstance(member, dict) or any(not isinstance(member.get(k), str) or not member[k].strip() for k in ("id", "label")):
                raise ValueError("Integrante sem identidade ou nome.")
            if member["id"] in ids:
                raise ValueError("Integrante duplicado.")
            ids.add(member["id"])
    return payload


def read_local(root):
    return validate(json.loads((Path(root) / GROUP_PATH).read_text(encoding="utf-8")))


def read_remote(repo="abalroar/tomaconta", branch="main", *, client=requests, token=None):
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = client.get(f"https://api.github.com/repos/{repo}/contents/{GROUP_PATH}", params={"ref": branch}, headers=headers, timeout=15)
    if response.status_code == 404:
        return None, None
    response.raise_for_status()
    data = response.json()
    payload = validate(json.loads(base64.b64decode(data["content"]).decode("utf-8")))
    return payload, data["sha"]


def resolve(group, identities):
    reverse = {code: name for name, code in identities.items()}
    found, missing = [], []
    for member in group["members"]:
        name = reverse.get(member["id"])
        if name:
            found.append(name)
        else:
            missing.append(member["label"])
    return found, missing


def upsert(payload, name, base, banks, identities, *, replace=False):
    name = str(name).strip()
    if not name:
        raise ValueError("Informe o nome do grupo.")
    missing = [bank for bank in banks if not identities.get(bank)]
    if missing:
        raise ValueError("Identidade estável indisponível: " + ", ".join(missing))
    result = json.loads(json.dumps(payload))
    existing = [g for g in result["groups"] if g["name"].casefold() == name.casefold() and g["base"] == base]
    if existing and not replace:
        raise ValueError("Já existe um grupo com esse nome. Marque substituir para atualizá-lo.")
    result["groups"] = [g for g in result["groups"] if g not in existing]
    result["groups"].append({"name": name, "base": base, "members": [{"id": identities[bank], "label": bank} for bank in banks], "updated_at": datetime.now(timezone.utc).isoformat()})
    return validate(result)


def publish(payload, repo, branch, token, expected_sha, *, client=requests):
    """Não atualiza disco nem informa sucesso antes do readback remoto."""
    validate(payload)
    body = {"message": "Atualiza grupos da nova tabela de peers", "branch": branch,
            "content": base64.b64encode(json.dumps(payload, ensure_ascii=False, indent=2).encode()).decode()}
    if expected_sha:
        body["sha"] = expected_sha
    response = client.put(f"https://api.github.com/repos/{repo}/contents/{GROUP_PATH}", headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, json=body, timeout=20)
    if response.status_code in {409, 422}:
        raise ValueError("O arquivo mudou no GitHub. Recarregue os grupos e tente novamente.")
    response.raise_for_status()
    written = response.json()["content"]["sha"]
    checked, sha = read_remote(repo, branch, client=client, token=token)
    if sha != written or checked != payload:
        raise RuntimeError("O GitHub recebeu a gravação, mas a confirmação de leitura falhou. Recarregue antes de tentar novamente.")
    return sha
