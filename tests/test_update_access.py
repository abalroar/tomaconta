import json

import pytest

from utils.ifdata_cache import update_access
from utils.ifdata_cache.update_access import (
    PermissionDenied, Principal, TokenIdentityVerifier, validate_action,
)


def test_server_defined_principal_ignores_request_actor_and_roles():
    verifier = TokenIdentityVerifier({
        "explicit-test-credential": {"subject": "credit-analyst", "permissions": ["read", "update"]},
    })
    principal = verifier.authenticate({
        "authorization": "Bearer explicit-test-credential",
        "X-Actor": "repository-owner", "X-Role": "admin", "X-Permissions": "publish,restore",
    })
    assert principal == Principal("credit-analyst", frozenset({"read", "update"}))
    validate_action(principal, "read")
    validate_action(principal, "update")
    with pytest.raises(PermissionDenied):
        validate_action(principal, "publish")
    with pytest.raises(PermissionDenied):
        validate_action(principal, "restore")


@pytest.mark.parametrize("action", ["read", "update", "publish", "restore"])
def test_actions_require_their_own_permission(action):
    principal = Principal("service-user", frozenset({action}))
    validate_action(principal, action)
    for other in update_access.UPDATE_PERMISSIONS - {action}:
        with pytest.raises(PermissionDenied):
            validate_action(principal, other)


@pytest.mark.parametrize("headers", [
    {}, {"X-Actor": "admin"}, {"Authorization": "Bearer unknown-credential"},
    {"Authorization": "Basic explicit-test-credential"}, {"Authorization": "Bearer"},
    {"Authorization": "Bearer explicit-test-credential extra"}, {"Authorization": None},
    {"Authorization": "Bearer explicit-test-credential\n"}, {"Authorization": "Bearer \ud800"},
    {"Authorization": "Bearer explicit-test-credential", "authorization": "Bearer explicit-test-credential"},
    None,
])
def test_missing_unknown_or_ambiguous_credential_is_denied(headers):
    verifier = TokenIdentityVerifier({"explicit-test-credential": {"subject": "analyst", "permissions": ["read"]}})
    with pytest.raises(PermissionDenied) as error:
        verifier.authenticate(headers)
    assert "explicit-test-credential" not in str(error.value)
    assert "unknown-credential" not in str(error.value)


def test_verifier_discards_raw_tokens_and_compares_every_hash(monkeypatch):
    tokens = ["first-test-credential", "second-test-credential", "third-test-credential"]
    verifier = TokenIdentityVerifier({token: {"subject": str(i), "permissions": ["read"]}
                                      for i, token in enumerate(tokens)})
    assert all(token not in repr(verifier) for token in tokens)
    assert all(token not in repr(verifier._identities) for token in tokens)
    calls = []
    original = update_access.hmac.compare_digest

    def observed(left, right):
        calls.append((len(left), len(right)))
        return original(left, right)

    monkeypatch.setattr(update_access.hmac, "compare_digest", observed)
    assert verifier.authenticate({"Authorization": f"bEaReR {tokens[0]}"}).subject == "0"
    assert calls == [(32, 32)] * 3
    calls.clear()
    with pytest.raises(PermissionDenied):
        verifier.authenticate({"Authorization": "Bearer unknown-credential"})
    assert calls == [(32, 32)] * 3


def test_configuration_snapshot_is_immutable():
    configured = {"explicit-test-credential": {"subject": "analyst", "permissions": ["read"]}}
    verifier = TokenIdentityVerifier(configured)
    configured["explicit-test-credential"]["permissions"].append("publish")
    configured["explicit-test-credential"]["subject"] = "admin"
    configured["extra-credential"] = {"subject": "admin", "permissions": ["publish"]}
    principal = verifier.authenticate({"Authorization": "Bearer explicit-test-credential"})
    assert principal == Principal("analyst", frozenset({"read"}))
    with pytest.raises(PermissionDenied):
        verifier.authenticate({"Authorization": "Bearer extra-credential"})


@pytest.mark.parametrize("configured", [
    {}, None, [], {"": {"subject": "analyst", "permissions": ["read"]}},
    {"credential with whitespace": {"subject": "analyst", "permissions": ["read"]}},
    {"\ud800": {"subject": "analyst", "permissions": ["read"]}},
    {"explicit-test-credential": {"subject": "", "permissions": ["read"]}},
    {"explicit-test-credential": {"subject": "analyst", "permissions": []}},
    {"explicit-test-credential": {"subject": "analyst", "permissions": "read"}},
    {"explicit-test-credential": {"subject": "analyst", "permissions": ["admin"]}},
    {"explicit-test-credential": {"subject": "analyst", "permissions": ["read", None]}},
    {"explicit-test-credential": {"subject": "analyst"}},
    {"explicit-test-credential": {"subject": "analyst", "permissions": ["read"], "role": "admin"}},
])
def test_empty_or_invalid_configuration_fails_closed_without_tokens(configured):
    with pytest.raises(ValueError) as error:
        TokenIdentityVerifier(configured)
    assert "explicit-test-credential" not in str(error.value)
    assert "credential with whitespace" not in str(error.value)


def test_explicit_environment_configuration_authenticates():
    verifier = TokenIdentityVerifier.from_env({
        update_access.IDENTITIES_ENV: json.dumps({
            "explicit-test-credential": {"subject": "publisher", "permissions": ["read", "publish"]},
        }),
    })
    principal = verifier.authenticate({"Authorization": "Bearer explicit-test-credential"})
    assert principal.subject == "publisher"
    validate_action(principal, "publish")
    with pytest.raises(PermissionDenied):
        validate_action(principal, "update")


@pytest.mark.parametrize("value", [None, "", " ", "{}", "[]", "invalid-json", '{"explicit-test-credential": {',
    '{"explicit-test-credential":{"subject":"analyst","permissions":["read"]},"explicit-test-credential":{"subject":"admin","permissions":["publish"]}}',
    '{"explicit-test-credential":{"subject":"analyst","subject":"admin","permissions":["read"]}}',
])
def test_environment_has_no_default_identity_and_rejects_ambiguous_json(value):
    environ = {} if value is None else {update_access.IDENTITIES_ENV: value}
    with pytest.raises(ValueError) as error:
        TokenIdentityVerifier.from_env(environ)
    assert "explicit-test-credential" not in str(error.value)


def test_principal_permissions_are_frozen_and_unknown_action_is_denied():
    principal = Principal(" analyst ", ["read", "read"])
    assert principal.subject == "analyst"
    assert principal.permissions == frozenset({"read"})
    with pytest.raises(AttributeError):
        principal.permissions.add("publish")
    with pytest.raises(PermissionDenied):
        validate_action(principal, "delete")
    with pytest.raises(PermissionDenied):
        validate_action(None, "read")
    with pytest.raises(PermissionDenied):
        validate_action(principal, ["read"])
    assert update_access.require_permission is validate_action


def test_from_env_uses_configured_process_environment(monkeypatch):
    monkeypatch.setenv(update_access.IDENTITIES_ENV, json.dumps({
        "explicit-test-credential": {"subject": "operator", "permissions": ["update"]},
    }))
    verifier = TokenIdentityVerifier.from_env()
    assert verifier.authenticate({"Authorization": "Bearer explicit-test-credential"}).subject == "operator"


def test_institutional_verifier_can_supply_a_principal_without_token_dependency():
    class InstitutionalVerifier:
        def authenticate(self, headers):
            return Principal("institution:user:42", frozenset({"read", "update"}))

    verifier: update_access.IdentityVerifier = InstitutionalVerifier()
    principal = verifier.authenticate({})
    validate_action(principal, "update")
    with pytest.raises(PermissionDenied):
        validate_action(principal, "publish")
