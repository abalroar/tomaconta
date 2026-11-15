"""Identidade e permissões do serviço de atualização, com verificador substituível."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from typing import Protocol


UPDATE_PERMISSIONS = frozenset({"read", "update", "publish", "restore"})
IDENTITIES_ENV = "TOMACONTA_UPDATE_IDENTITIES_JSON"


class PermissionDenied(RuntimeError):
    """Credencial não reconhecida ou ação não autorizada."""


def _permissions(value) -> frozenset[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise ValueError("Permissões de atualização inválidas.")
    if not value or any(not isinstance(item, str) or item not in UPDATE_PERMISSIONS for item in value):
        raise ValueError("Permissões de atualização inválidas.")
    return frozenset(value)


@dataclass(frozen=True)
class Principal:
    """Identidade pública e permissões estabelecidas pelo servidor."""

    subject: str
    permissions: frozenset[str]

    def __post_init__(self):
        if not isinstance(self.subject, str) or not self.subject.strip():
            raise ValueError("Identidade de atualização inválida.")
        object.__setattr__(self, "subject", self.subject.strip())
        object.__setattr__(self, "permissions", _permissions(self.permissions))


class IdentityVerifier(Protocol):
    """Porta para credenciais locais ou um verificador institucional futuro."""

    def authenticate(self, headers: Mapping[str, str]) -> Principal:
        ...


def validate_action(principal: Principal, action: str) -> None:
    """Exige a permissão específica, sem hierarquia implícita entre ações."""
    if (not isinstance(principal, Principal) or not isinstance(action, str)
            or action not in UPDATE_PERMISSIONS
            or action not in principal.permissions):
        raise PermissionDenied("Ação de atualização não autorizada.")


require_permission = validate_action


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Configuração de identidades inválida.")
        result[key] = value
    return result


class TokenIdentityVerifier:
    """Autentica Bearer tokens explícitos e conserva apenas seus hashes."""

    __slots__ = ("_identities",)

    def __init__(self, identities: Mapping[str, Mapping | Principal]):
        if not isinstance(identities, Mapping) or not identities:
            raise ValueError("Configure identidades explícitas para o serviço de atualização.")
        records = []
        for token, definition in identities.items():
            if (not isinstance(token, str) or not token
                    or any(character.isspace() for character in token)):
                raise ValueError("Credencial configurada inválida.")
            if isinstance(definition, Principal):
                principal = definition
            elif isinstance(definition, Mapping) and set(definition) == {"subject", "permissions"}:
                principal = Principal(definition["subject"], definition["permissions"])
            else:
                raise ValueError("Configuração de identidades inválida.")
            try:
                digest = hashlib.sha256(token.encode("utf-8")).digest()
            except UnicodeError:
                raise ValueError("Credencial configurada inválida.") from None
            records.append((digest, principal))
        self._identities = tuple(records)

    def __repr__(self) -> str:
        return f"TokenIdentityVerifier(identities={len(self._identities)})"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> TokenIdentityVerifier:
        configured = (os.environ if environ is None else environ).get(IDENTITIES_ENV)
        if not isinstance(configured, str) or not configured.strip():
            raise ValueError("Configure identidades explícitas para o serviço de atualização.")
        try:
            identities = json.loads(configured, object_pairs_hook=_unique_json_object)
        except (ValueError, TypeError):
            raise ValueError("Configuração de identidades inválida.") from None
        return cls(identities)

    def authenticate(self, headers: Mapping[str, str]) -> Principal:
        if not isinstance(headers, Mapping):
            raise PermissionDenied("Credencial de atualização não reconhecida.")
        authorizations = [value for key, value in headers.items()
                          if isinstance(key, str) and key.lower() == "authorization"]
        if len(authorizations) != 1 or not isinstance(authorizations[0], str):
            raise PermissionDenied("Credencial de atualização não reconhecida.")
        if any(character in authorizations[0] for character in ("\r", "\n", "\x00")):
            raise PermissionDenied("Credencial de atualização não reconhecida.")
        parts = authorizations[0].split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise PermissionDenied("Credencial de atualização não reconhecida.")
        try:
            digest = hashlib.sha256(parts[1].encode("utf-8")).digest()
        except UnicodeError:
            raise PermissionDenied("Credencial de atualização não reconhecida.") from None
        principal = None
        for expected, candidate in self._identities:
            if hmac.compare_digest(digest, expected):
                principal = candidate
        if principal is None:
            raise PermissionDenied("Credencial de atualização não reconhecida.")
        return principal
