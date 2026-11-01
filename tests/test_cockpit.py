"""Carteiras salvas e tendência do Cockpit."""
import base64
import json
from types import SimpleNamespace

import pytest

from tabs.cockpit import is_material, metric_configs, render_table, trend
from utils import cockpit_store as store


IDS = {"BANCO A": "C1", "BANCO B": "C2"}


def test_upsert_is_by_name_ignoring_case_and_keeps_others():
    data = store.upsert(store.empty(), " Mizael ", ["BANCO A"], IDS)
    data = store.upsert(data, "Natalia", ["BANCO B"], IDS)
    data = store.upsert(data, "mizael", ["BANCO A", "BANCO B"], IDS)
    assert [item["nome"] for item in data["carteiras"]] == ["mizael", "Natalia"]
    assert [m["id"] for m in store.find(data, "MIZAEL")["membros"]] == ["C1", "C2"]
    assert store.find(store.remove(data, "NATALIA"), "natalia") is None


def test_members_are_found_by_code_even_after_a_rename_and_gaps_are_reported():
    data = store.upsert(store.empty(), "Paulo", ["BANCO A", "BANCO B"], IDS)
    found, missing = store.resolve(store.find(data, "paulo"), {"BANCO A NOVO": "C1"})
    assert found == ["BANCO A NOVO"] and missing == ["BANCO B"]


@pytest.mark.parametrize("name", ["", "x" * 61])
def test_invalid_names_are_rejected(name):
    with pytest.raises(ValueError):
        store.upsert(store.empty(), name, ["BANCO A"], IDS)


def test_limits_and_missing_identity_are_rejected():
    with pytest.raises(ValueError, match="código oficial"):
        store.upsert(store.empty(), "A", ["SEM CODIGO"], IDS)
    many = {f"B{i}": f"C{i}" for i in range(151)}
    with pytest.raises(ValueError, match="até 150"):
        store.upsert(store.empty(), "A", list(many), many)


def test_local_store_round_trip(tmp_path):
    local = store.LocalStore(tmp_path)
    assert local.read()[0] == store.empty()
    store.save(local, lambda current: store.upsert(current, "Matheus", ["BANCO A"], IDS), "x")
    assert store.find(local.read()[0], "matheus")["membros"][0]["id"] == "C1"


class FakeGitHub:
    """Só o que a API de conteúdo faz: versão por sha e recusa de versão antiga."""

    def __init__(self):
        self.content, self.sha, self.branches, self.conflicts = None, None, {"main"}, 0

    def _ok(self, status=200, body=None):
        return SimpleNamespace(status_code=status, json=lambda: body or {}, raise_for_status=lambda: None)

    def get(self, url, **kwargs):
        if "/git/ref/heads/" in url:
            name = url.rsplit("/", 1)[1]
            return self._ok(200, {"object": {"sha": "abc"}}) if name in self.branches else self._ok(404)
        return self._ok(200, {"content": self.content, "sha": self.sha}) if self.content else self._ok(404)

    def post(self, url, **kwargs):
        self.branches.add(kwargs["json"]["ref"].rsplit("/", 1)[1])
        return self._ok(201)

    def put(self, url, **kwargs):
        body = kwargs["json"]
        assert body["branch"] == store.BRANCH
        if self.conflicts:
            self.conflicts -= 1
            return self._ok(409)
        if body.get("sha") != self.sha:
            return self._ok(409)
        self.content, self.sha = body["content"], (self.sha or "") + "x"
        return self._ok(200)


def test_github_store_uses_its_own_branch_and_keeps_a_concurrent_save():
    client = FakeGitHub()
    remote = store.GitHubStore("t", "o/r", client=client)
    store.save(remote, lambda current: store.upsert(current, "Mizael", ["BANCO A"], IDS), "x")
    assert store.BRANCH in client.branches
    client.conflicts = 1
    store.save(remote, lambda current: store.upsert(current, "Natalia", ["BANCO B"], IDS), "x")
    saved = json.loads(base64.b64decode(client.content))
    assert {item["nome"] for item in saved["carteiras"]} == {"Mizael", "Natalia"}


def votes(*tones):
    labels = ("CET1", "Índice de Basileia", "Patrimônio Líquido", "ROE Ac. Anualizado", "Inadimplência >90 dias", "Cobertura dos vencidos >90 dias")
    return {label: (tone, f"{100 + i} bps") for i, (label, tone) in enumerate(zip(labels, tones))}


@pytest.mark.parametrize("tones,state", [
    (("attention", "attention", "neutral", "neutral"), "down"),
    (("favorable", "favorable", "neutral"), "up"),
    (("favorable", "attention", "neutral"), "flat"),
    (("attention", "neutral", "favorable", "attention"), "flat"),
    (("attention", "attention"), "na"),
])
def test_trend_is_a_fixed_balance_of_signals(tones, state):
    assert trend(votes(*tones))["state"] == state


def test_trend_reason_names_the_metrics_behind_it():
    reason = trend(votes("attention", "attention", "neutral"))["reason"]
    assert reason == "Contra: CET1 100 bps; Índice de Basileia 101 bps"


def test_table_escapes_names_and_shows_gaps():
    row = {"bank": "<B>", "period": "2/2026", "spark": [None], "spark_kind": "line",
           "trend": {"state": "na", "reason": "x"},
           "cells": {cfg["label"]: {"value": "N/D", "delta": "—", "tone": "neutral", "reference": "QoQ", "annual": "—"} for cfg in metric_configs()}}
    api = {"_snap_sparkbars_svg": None, "_snap_sparkline_svg": None, "periodo_para_exibicao": str}
    html = render_table([row], "2/2026", api)
    assert "&lt;B&gt;" in html and "<B>" not in html and "Sem dados" in html


@pytest.mark.parametrize("text,expected", [("−885 bps", True), ("+12 bps", False), ("−27,59 p.p.", True), ("−1,78 p.p.", False),
                                           ("+7,45%", True), ("+1,20%", False), ("<1 bp", False), ("—", False), ("−1.075 bps", True)])
def test_small_moves_do_not_vote(text, expected):
    assert is_material(text) is expected


def test_small_moves_cannot_tip_the_trend():
    data = votes("attention", "attention", "neutral")
    data["CET1"] = ("attention", "−10 bps")
    assert trend(data)["state"] == "flat"


def test_a_read_only_token_gets_a_clear_message():
    client = FakeGitHub()
    client.branches.add(store.BRANCH)
    client.put = lambda url, **kwargs: client._ok(403)
    with pytest.raises(PermissionError, match="permissão de escrita"):
        store.save(store.GitHubStore("t", "o/r", client=client), lambda current: store.upsert(current, "A", ["BANCO A"], IDS), "x")
