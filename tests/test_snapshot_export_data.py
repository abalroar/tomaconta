"""Contracts for closing a Snapshot export without changing source or perimeter."""
from pathlib import Path
from types import SimpleNamespace
import json
import sys

import pandas as pd
import pytest

from utils import snapshot_export_data as subject
from utils.ifdata_cache.institutions import normalize_institution_code
from tabs.carteira_4966 import EXPECTED_LOSS_COLUMNS, comparison_source_periods


BANK = "ITAU - PRUDENCIAL"
OTHER_BANK = "BRADESCO - PRUDENCIAL"


def portfolio_frame(periods, bank=BANK, code="P100"):
    return pd.DataFrame([
        {
            "Instituição": bank, "CodInst": code, "Período": period,
            "Total Geral": 1_000.0 + i * 100,
            "C1": 200.0 + i * 100, "C2": 300.0, "C3": 100.0,
            "C4": 200.0, "C5": 150.0,
            "Total não Individualizado": 40.0,
            "Carteira não Informada ou não se Aplica": 10.0,
            "Total Exterior": 0.0, "Inadimplência": 30.0,
        }
        for i, period in enumerate(periods)
    ])


def loss_frame(periods, bank=BANK, code="P100", amounts=(-4.0, -3.0, -2.0, -1.0)):
    return pd.DataFrame([
        {"Instituição": bank, "CodInst": code, "Período": period,
         **dict(zip(EXPECTED_LOSS_COLUMNS, amounts))}
        for period in periods
    ])


def carteira_api(portfolio, loss=None, *, portfolio_status=None, loss_status=None):
    calls = []
    manifest = {"generated_at": "2026-10-10", "caches": {"ativo": {"sha256": "digest-rel2"}}, "nome": "Fonte válida"}

    def load_manifest(url, tag):
        calls.append(("manifest", url, tag))
        return manifest

    def token(value):
        assert value is manifest
        return "same-release-token"

    def load_portfolio(release_token, payload):
        calls.append(("portfolio", release_token, payload))
        return portfolio.copy() if portfolio is not None else None, portfolio_status or {"valid": True}

    def load_loss(release_token, payload, periods):
        calls.append(("loss", release_token, payload, periods))
        return loss.copy() if loss is not None else pd.DataFrame(), loss_status or {"valid": True}

    def canonicalize(frame, *, base_dir):
        calls.append(("canonicalize", base_dir))
        return frame.copy().replace({"Instituição": {"Nome antigo oficial": BANK}})

    api = {
        "_carregar_manifest_release_cache": load_manifest,
        "_CARTEIRA_4966_RELEASE_MANIFEST_URL": "https://source.test/manifest.json",
        "_EXPECTED_CACHE_RELEASE_TAG": "release-fixed",
        "_carteira_4966_release_token": token,
        "load_carteira_4966_data": load_portfolio,
        "load_carteira_4966_ativo_periods": load_loss,
        "canonicalize_institution_history": canonicalize,
        "normalize_institution_code": normalize_institution_code,
        "APP_DIR": Path("/synthetic/project"),
    }
    return api, calls, manifest


def test_latest_periods_uses_quarter_order_and_excludes_future_duplicates_and_nulls():
    periods = ["1/2026", "4/2025", None, "3/2025", "2/2026", "2/2026", "3/2026", float("nan"), "4/2024"]
    assert subject.latest_periods(periods, "2/2026") == ["4/2025", "1/2026", "2/2026"]
    assert subject.latest_periods(periods, "4/2025", 2) == ["3/2025", "4/2025"]
    assert subject.latest_periods(["1/2025"], "4/2024") == []
    assert subject.latest_periods([], "2/2026") == []


def test_institution_slice_requires_exact_canonical_name_or_official_code():
    frame = pd.DataFrame([
        {"Instituição": BANK, "CodInst": "P100", "value": 1},
        {"Instituição": "Nome antigo", "CodInst": " P100 ", "value": 2},
        {"Instituição": "ITAU UNIBANCO S.A.", "CodInst": "100", "value": 3},
        {"Instituição": "ITAU - PRUDENCIAL FINANCEIRA", "CodInst": "P200", "value": 4},
    ])
    selected = subject.institution_slice(frame, BANK, {"P100"}, normalize_institution_code)
    assert selected["value"].tolist() == [1, 2]
    assert subject.institution_slice(frame, "ITAU", set(), normalize_institution_code).empty
    assert subject.institution_slice(None, BANK, set(), normalize_institution_code).empty


def test_carteira_history_reuses_manifest_and_hidden_references_after_canonical_matching():
    source_periods = ["3/2025", "4/2025", "1/2026", "2/2026", "3/2026"]
    portfolio = portfolio_frame(source_periods)
    losses = pd.concat([
        loss_frame(source_periods, bank="Nome antigo oficial", code="changed-name-code"),
        loss_frame(source_periods, bank="Outro nome por código", code="P100"),
        loss_frame(source_periods, bank="ITAU UNIBANCO S.A.", code="100", amounts=(-400, -300, -200, -100)),
    ], ignore_index=True)
    api, calls, manifest = carteira_api(portfolio, losses)

    model, reason, warnings = subject.carteira_history(BANK, "2/2026", api)

    assert reason == ""
    assert warnings == []
    assert model.periods == ("4/2025", "1/2026", "2/2026")
    assert model.base_period == "4/2025"
    assert "3/2026" not in model.periods
    assert model.cells["provision"]["2/2026"].primary == 10
    assert model.reference_cells["provision"]["3/2025"].primary == 10
    portfolio_call = next(call for call in calls if call[0] == "portfolio")
    loss_call = next(call for call in calls if call[0] == "loss")
    assert portfolio_call[1:3] == loss_call[1:3]
    assert json.loads(portfolio_call[2]) == manifest
    assert loss_call[3] == comparison_source_periods(model.periods)
    assert ("canonicalize", api["APP_DIR"]) in calls


@pytest.mark.parametrize("periods", [["1/2026"], ["4/2025", "1/2026"]])
def test_carteira_history_preserves_one_or_two_periods_with_clear_coverage_note(periods):
    api, _, _ = carteira_api(portfolio_frame(periods), loss_frame(periods))
    model, reason, warnings = subject.carteira_history(BANK, "2/2026", api)
    assert model.periods == tuple(periods)
    assert reason == ""
    assert any(f"somente {len(periods)} competência" in warning for warning in warnings)


@pytest.mark.parametrize("cutoff", ["4/2024", "3/2025"])
def test_carteira_history_never_fills_pre_source_or_future_cutoff_with_another_period(cutoff):
    api, calls, _ = carteira_api(portfolio_frame(["4/2025", "1/2026"]), loss_frame(["4/2025", "1/2026"]))
    model, reason, warnings = subject.carteira_history(BANK, cutoff, api)
    assert model is None
    assert "até a data-base" in reason
    assert warnings == []
    assert not any(call[0] == "loss" for call in calls)


def test_carteira_history_does_not_substitute_individual_or_similar_institution():
    source = portfolio_frame(["4/2025", "1/2026"], bank="ITAU UNIBANCO S.A.", code="100")
    api, calls, _ = carteira_api(source)
    model, reason, warnings = subject.carteira_history(BANK, "1/2026", api)
    assert model is None
    assert "instituição e o perímetro" in reason
    assert warnings == []
    assert not any(call[0] == "loss" for call in calls)


def test_unvalidated_portfolio_cannot_produce_a_model_even_with_numeric_rows():
    api, calls, _ = carteira_api(portfolio_frame(["1/2026"]), portfolio_status={"valid": False})
    model, reason, warnings = subject.carteira_history(BANK, "1/2026", api)
    assert model is None
    assert "cobertura validada" in reason
    assert warnings == []
    assert not any(call[0] == "loss" for call in calls)


def test_unvalidated_rel2_values_are_ignored_and_provision_remains_missing():
    periods = ["4/2025", "1/2026", "2/2026"]
    api, _, _ = carteira_api(portfolio_frame(periods), loss_frame(periods), loss_status={"valid": False})
    model, reason, warnings = subject.carteira_history(BANK, "2/2026", api)
    assert reason == ""
    assert model.cells["total_portfolio"]["2/2026"].primary == 1_200
    for key in ("provision", "provision_over_portfolio", "provision_over_delinquency"):
        assert all(model.cells[key][period].primary is None for period in periods)
    assert any("permanecem N/D" in warning for warning in warnings)


def test_rel2_exception_preserves_portfolio_and_publishes_limitation():
    periods = ["4/2025", "1/2026", "2/2026"]
    api, _, _ = carteira_api(portfolio_frame(periods))
    def unavailable(*args):
        raise OSError("source offline")
    api["load_carteira_4966_ativo_periods"] = unavailable
    model, reason, warnings = subject.carteira_history(BANK, "2/2026", api)
    assert model.periods == tuple(periods)
    assert reason == ""
    assert model.missing_provision_periods == tuple(periods)
    assert any("Rel. 2 indisponível" in warning for warning in warnings)


def test_carteira_source_integrity_and_collision_warnings_reach_the_export():
    periods = ["4/2025", "1/2026", "2/2026"]
    api, _, _ = carteira_api(portfolio_frame(periods), loss_frame(periods),
        portfolio_status={"valid": True, "warning": "Rel. 16 sem digest publicado", "identity_collision_count": 2},
        loss_status={"valid": True, "warning": "Rel. 2 sem digest publicado"})
    _, _, warnings = subject.carteira_history(BANK, "2/2026", api)
    assert "Rel. 16 sem digest publicado" in warnings
    assert "Rel. 2 sem digest publicado" in warnings
    assert any("Sobreposições de identidade" in warning for warning in warnings)


def test_peers_history_reuses_query_pipeline_and_includes_ytd_and_qoq_inputs(monkeypatch):
    all_periods = ["2/2024", "4/2024", "2/2025", "3/2025", "4/2025", "1/2026", "2/2026", "3/2026"]
    frame = pd.DataFrame({"Instituição": BANK, "Período": all_periods, "Ativo Total": range(len(all_periods))})
    calls = {}
    extra = {"shared": "prepared"}
    values, columns, statuses = {"values": 1}, {"columns": 1}, {"statuses": 1}
    def prepare(selected, banks, extended):
        calls["prepare"] = (selected.copy(), banks, extended)
        return extra
    def assemble(selected, banks, extended, **kwargs):
        calls["assemble"] = (selected.copy(), banks, extended, kwargs)
        return values, columns, None, None, None, None
    def status(**kwargs):
        calls["status"] = kwargs
        return statuses
    def close_query(selected, banks, periods, metrics, got_values, got_statuses, **kwargs):
        calls["query"] = (selected.copy(), banks, periods, metrics, got_values, got_statuses, kwargs)
        return {"closed": True}
    monkeypatch.setattr(subject, "build_query", close_query)
    api = {"_preparar_metricas_extra_peers_from_slice": prepare, "_montar_tabela_peers": assemble,
           "_build_peers_status_lookup": status, "_cache_version_token": lambda source: f"token-{source}"}

    assert subject.peers_history(frame, BANK, "2/2026", api, "10/10/2026") == {"closed": True}
    displayed = ["4/2025", "1/2026", "2/2026"]
    extended = subject.required_periods(displayed, "quarter")
    assert set(calls["prepare"][0]["Período"]) == set(extended)
    assert {"3/2025", "4/2024", "2/2025"}.issubset(extended)
    assert "3/2026" not in calls["prepare"][0]["Período"].tolist()
    assert calls["prepare"][1:] == ([BANK], extended)
    assert calls["assemble"][3] == {"extra_values_precomputed": extra, "allow_capital_fallback": False}
    assert calls["status"]["periodos"] == displayed
    query = calls["query"]
    assert query[1:6] == ([BANK], displayed, list(subject.DEFAULT_METRICS), values, statuses)
    assert query[6] == {"base": subject.BASE, "cache_token": "token-critical_screens", "scale": "R$ bilhões", "mode": "quarter", "queried_at": "10/10/2026"}


def test_peers_period_selection_and_data_are_limited_to_selected_institution(monkeypatch):
    frame = pd.DataFrame([
        {"Instituição": bank, "Período": period}
        for bank, periods in [(BANK, ["3/2025", "4/2025", "1/2026"]),
                              (OTHER_BANK, ["1/2026", "2/2026", "3/2026"])]
        for period in periods
    ])
    monkeypatch.setattr(subject, "build_query", lambda selected, banks, periods, *args, **kwargs: (selected, periods))
    api = {
        "_preparar_metricas_extra_peers_from_slice": lambda *args: {},
        "_montar_tabela_peers": lambda *args, **kwargs: ({}, {}, None, None, None, None),
        "_build_peers_status_lookup": lambda **kwargs: {},
        "_cache_version_token": lambda cache: "source-token",
    }
    selected, displayed = subject.peers_history(frame, BANK, "2/2026", api, "10/10/2026")
    assert displayed == ["3/2025", "4/2025", "1/2026"]
    assert set(selected["Instituição"]) == {BANK}


def test_real_peers_pipeline_preserves_missing_capital_without_global_reconstruction(monkeypatch):
    import app1
    bank = "ATTRUS IP - PRUDENCIAL"
    periods = ["3/2025", "4/2025", "1/2026", "2/2026"]
    frame = pd.DataFrame({
        "Instituição": [bank] * len(periods), "Período": periods,
        "Ativo Total": [100e6, 110e6, 120e6, 130e6],
        "Patrimônio Líquido": [20e6] * len(periods),
        "Índice de Capital Principal (CET1)": [None] * len(periods),
        "Índice de Basileia Total (%)": [None] * len(periods),
        "CapitalDisponivel": [False] * len(periods),
    })
    def prohibited_reconstruction(*args, **kwargs):
        raise AssertionError("Snapshot export must use the closed slice without reconstructing global capital")
    monkeypatch.setattr(app1, "_construir_indices_capital_unificados", prohibited_reconstruction)
    api = {**vars(app1), "_cache_version_token": lambda source: "frozen-source-token"}

    query = subject.peers_history(frame, bank, "2/2026", api, "10/10/2026")

    assert query["periods"] == ["4/2025", "1/2026", "2/2026"]
    capital = [cell for cell in query["cells"] if cell["metric"] in
               {"Índice de Capital Principal (CET1)", "Índice de Basileia Total (%)"}]
    assert len(capital) == 6
    assert all(cell["value"] is None and cell["status"] == "missing" for cell in capital)
    assert all(cell["display"] == "N/D" for cell in capital)
    assert [cell["value"] for cell in query["cells"] if cell["metric"] == "Ativo Total"] == [110e6, 120e6, 130e6]


def payload_api(calls):
    def presentation(current, old, label, **kwargs):
        calls.append((current, old, label, kwargs))
        return {"display": "delta from card", "tone": "neutral", "raw": (current, old)}
    api = {
        "_snap_metric_delta_meta": lambda cfg: ("bps" if cfg.get("is_pct") else "pct", "dec" if cfg.get("is_pct") else "pct"),
        "_snapshot_comparison_labels": lambda cfg: ("QoQ trimestral", "YoY YTD" if cfg.get("comparison") == "yoy" else "YoY trimestral"),
        "_snap_metric_favorable_direction": lambda cfg: cfg.get("favorable_direction"),
        "_snap_delta_presentation": presentation,
        "_formatar_valor_snapshot": lambda cfg, current: "N/D" if current is None else f"card:{current}",
        "get_help_text": lambda key: f"definition:{key}",
        "periodo_para_exibicao": lambda period: f"label:{period}",
    }
    def card_delta(cfg, current_period, reference_period, label):
        kind, scale = api["_snap_metric_delta_meta"](cfg)
        series = cfg.get("serie", {})
        return presentation(series.get(current_period), series.get(reference_period), label,
            higher_is_better=cfg.get("higher_is_better", True), delta_kind=kind,
            scale=scale, favorable_direction=api["_snap_metric_favorable_direction"](cfg))
    api["_snapshot_card_delta"] = card_delta
    return api


def test_snapshot_payload_preserves_card_format_precision_and_comparison_metadata():
    cfg = {"label": "Índice de Basileia", "format_key": "Capital", "is_pct": True,
           "serie": {"2/2026": .15351632203113585, "1/2026": .14769709, "2/2025": .15},
           "higher_is_better": True, "favorable_direction": "up", "source": "IFData Rel. 5"}
    calls = []
    history = {"Índice de Basileia": {"periods": ["1/2026", "2/2026"], "values": [.14769709, .15351632203113585]}}
    payload = subject.snapshot_payload(BANK, "2/2026", "1/2026", "2/2025", [("Capital", [cfg])], history, payload_api(calls))
    card = payload["cards"][0]
    assert card["value"] == "card:0.15351632203113585"
    assert card["raw_value"] == cfg["serie"]["2/2026"]
    assert card["history"] == {**history[cfg["label"]], "tone": "neutral", "direction": None}
    assert card["group"] == "Capital"
    assert card["source"] == "IFData Rel. 5"
    assert card["notes"] == "definition:Capital"
    assert card["qoq"]["reference_period"] == "1/2026"
    assert card["yoy"]["reference_period"] == "2/2025"
    assert calls[0][3] == {"higher_is_better": True, "delta_kind": "bps", "scale": "dec", "favorable_direction": "up"}
    assert payload["base"] == subject.BASE
    assert payload["period_label"] == "label:2/2026"
    assert "e2 + f2 + g2 + h2" in payload["source_notes"]
    assert "hedge" in payload["source_notes"]


def test_snapshot_payload_uses_yoy_for_ytd_and_keeps_missing_value_status():
    configs = [
        {"label": "Lucro acumulado", "comparison": "yoy", "serie": {"2/2026": 30.12345, "1/2026": 10, "2/2025": 20}},
        {"label": "CET1", "serie": {}, "status_marker": "†", "status_note": "Sem fonte para a instituição."},
    ]
    payload = subject.snapshot_payload(BANK, "2/2026", "1/2026", "2/2025", [("Resumo", configs)], {}, payload_api([]))
    ytd, missing = payload["cards"]
    assert ytd["qoq"]["display"] == "—"
    assert ytd["qoq"]["tone"] == "neutral"
    assert "mesmos meses" in ytd["qoq"]["reason"]
    assert ytd["yoy"]["display"] == "delta from card"
    assert missing["raw_value"] is None
    assert missing["value"] == "N/D†"
    assert missing["status"] == "Sem fonte para a instituição."


@pytest.mark.parametrize("missing", [None, float("nan")])
def test_real_snapshot_payload_distinguishes_zero_funding_from_missing_data(missing):
    import app1
    zero = {"label": "Crédito / Captações", "format_key": "Carteira de Crédito/Core Funding (%)",
            "is_pct": True, "serie": {"2/2026": 0.0}}
    absent = {"label": "Desp. Anualizada Captação / Volume Captação", "format_key": "Desp Captação / Captação",
              "is_pct": True, "serie": {"2/2026": missing}, "status_marker": "†", "status_note": "Fonte indisponível."}
    histories = {zero["label"]: {"periods": ["Jun/26"], "values": [0.0]},
                 absent["label"]: {"periods": ["Jun/26"], "values": [missing]}}
    payload = subject.snapshot_payload(BANK, "2/2026", None, None,
        [("support", [zero, absent])], histories, vars(app1))
    zero_card, missing_card = payload["cards"]
    assert zero_card["value"] == "0,00%"
    assert zero_card["raw_value"] == 0.0
    assert missing_card["value"] == "N/D†"
    assert pd.isna(missing_card["raw_value"])
    assert missing_card["status"] == "Fonte indisponível."
    assert zero_card["history"]["values"] is histories[zero["label"]]["values"]
    assert missing_card["history"]["values"] is histories[absent["label"]]["values"]
    assert all(card[key]["display"] == "—" for card in payload["cards"] for key in ("qoq", "yoy"))


def test_snapshot_payload_no_reference_keeps_reference_unavailable():
    payload = subject.snapshot_payload(BANK, "1/2025", None, None,
        [("Resumo", [{"label": "Ativo", "serie": {"1/2025": 100}}])], {}, payload_api([]))
    assert payload["qoq_period_label"] == "N/D"
    assert payload["yoy_period_label"] == "N/D"
    assert payload["cards"][0]["qoq"]["reference_period"] is None
    assert payload["cards"][0]["yoy"]["reference_period"] is None


@pytest.mark.parametrize("cfg,previous,yoy,expected_tone,expected_display", [
    ({"label": "Carteira de Crédito", "format_key": "Carteira de Crédito Bruta", "serie": {"4/2025": 120, "3/2025": 110, "4/2024": 100}}, "3/2025", "4/2024", "neutral", "Quebra em 2025"),
    ({"label": "Índice de Basileia", "format_key": "Índice de Basileia", "is_pct": True, "status_marker": "†", "variation_reliable": False, "serie": {"4/2025": .152, "3/2025": .15, "4/2024": .14}}, "3/2025", "4/2024", "neutral", "↑ +120 bps"),
    ({"label": "Perda Esperada / Estágio 3", "is_pct": True, "serie": {"4/2025": 1.935, "3/2025": 1.931, "4/2024": 1.931}}, "3/2025", "4/2024", "favorable", "↑ +0,40 p.p."),
    ({"label": "Desp. Anualizada Captação / Volume Captação", "format_key": "Desp Captação / Captação", "is_pct": True, "higher_is_better": False, "serie": {"4/2025": -.06, "3/2025": -.05, "4/2024": -.05}}, "3/2025", "4/2024", "attention", "↓ −100 bps"),
    ({"label": "Ativo Total", "format_key": "Ativo Total", "serie": {"4/2025": 120, "3/2025": 100, "4/2024": 100}}, "3/2025", "4/2024", "neutral", "↑ +20,00%"),
])
def test_real_card_and_export_have_identical_delta_text_color_and_methodology_guard(cfg, previous, yoy, expected_tone, expected_display):
    import app1
    payload = subject.snapshot_payload(BANK, "4/2025", previous, yoy,
        [("Resumo", [cfg])], {}, vars(app1))
    card = payload["cards"][0]
    for key, reference, label in (("qoq", previous, "QoQ trimestral"), ("yoy", yoy, "YoY trimestral")):
        expected = app1._snapshot_card_delta(cfg, "4/2025", reference, label)
        assert card[key]["display"] == expected["display"]
        assert card[key]["tone"] == expected["tone"]
        assert card[key]["reason"] == expected["reason"]
    assert card["yoy"]["tone"] == expected_tone
    assert card["yoy"]["display"] == expected_display
    assert card["value"] == app1._formatar_valor_snapshot(cfg, cfg["serie"]["4/2025"]) + cfg.get("status_marker", "")


@pytest.mark.parametrize("fail_carteira", [False, True])
def test_package_source_failure_preserves_other_slides_and_discloses_the_gap(monkeypatch, fail_carteira):
    captured = {}
    def export(snapshot, peers, carteira, **kwargs):
        captured.update(snapshot=snapshot, peers=peers, carteira=carteira, **kwargs)
        return b"native-deck"
    monkeypatch.setitem(sys.modules, "utils.snapshot_pptx_export", SimpleNamespace(export_snapshot_powerpoint=export))
    def peer_failure(*args, **kwargs):
        raise ValueError("incomplete source")
    monkeypatch.setattr(subject, "peers_history", peer_failure)
    if fail_carteira:
        def carteira_failure(*args, **kwargs):
            raise ValueError("manifest unavailable")
        monkeypatch.setattr(subject, "carteira_history", carteira_failure)
    else:
        monkeypatch.setattr(subject, "carteira_history", lambda *args, **kwargs: ("usable model", "", ["provisão sem digest"]))
    snapshot = {"bank": BANK, "period": "2/2026", "queried_at": "10/10/2026", "source_notes": "source explanation"}
    assert subject.export_snapshot_package(snapshot, pd.DataFrame(), {}) == b"native-deck"
    assert captured["peers"] is None
    assert "Histórico da Tabela de Peers indisponível" in captured["peers_unavailable_reason"]
    if fail_carteira:
        assert captured["carteira"] is None
        assert "Fonte da Carteira 4.966 indisponível" in captured["carteira_unavailable_reason"]
    else:
        assert captured["carteira"] == "usable model"
        assert "provisão sem digest" in captured["snapshot"]["carteira_notes"]
    assert snapshot["source_notes"] == "source explanation"


def test_individual_payload_declares_each_card_scope_and_uses_configured_source_note():
    cfg = {"label": "ROE Ac. Anualizado", "format_key": "ROE Ac. YTD an. (%)", "is_pct": True,
           "comparison": "yoy", "serie": {"2/2026": .12, "2/2025": .10},
           "source": "IFData Rel. 1 individual", "source_label": "Rel. 1 · Individual",
           "scope": "Individual", "notes": "Lucro YTD anualizado / PL atual"}
    api = payload_api([])
    api["_snapshot_card_delta"] = lambda *args: {"display": "↑ +2,0 p.p.", "tone": "favorable", "direction": "up"}
    result = subject.snapshot_payload("BANCO A S.A.", "2/2026", "1/2026", "2/2025",
                                      [("profit", [cfg])], {}, api, base="Individual")
    assert result["base"] == "Individual"
    assert "entidade jurídica" in result["notes"]
    assert "patrimônio líquido atual" in result["source_notes"]
    card = result["cards"][0]
    assert card["scope"] == "Individual"
    assert card["source_label"] == "Rel. 1 · Individual"
    assert card["notes"] == cfg["notes"]
    assert card["history"]["tone"] == "neutral"
    assert card["history"]["direction"] is None


def test_individual_carteira_unavailable_never_calls_a_consolidated_source():
    model, reason, warnings = subject.carteira_history("ITAU - PRUDENCIAL", "2/2026", {}, base="Individual")
    assert model is None and warnings == []
    assert "N/D na base Individual" in reason
    assert "mesmo perímetro" in reason


def test_individual_peer_history_uses_individual_metrics_and_never_capital_fallback():
    import app1
    bank = "BANCO A S.A."
    frame = pd.DataFrame({
        "Instituição": [bank] * 4, "CodInst": ["1234"] * 4,
        "Período": ["3/2025", "4/2025", "1/2026", "2/2026"],
        "Ativo Total": [100e6, 110e6, 120e6, None],
        "Carteira de Crédito": [50e6, 60e6, 70e6, None],
        "Patrimônio Líquido": [10e6, 11e6, 12e6, None],
        "Captações": [80e6, 90e6, 100e6, None],
        "Lucro Líquido": [1e6, 2e6, 3e6, None],
    })
    api = {**vars(app1), "_cache_version_token": lambda source: "token-" + source}
    query = subject.peers_history(frame, bank, "2/2026", api, "10/10/2026", base="Individual")
    assert query["base"] == "Individual"
    assert query["cache_token"] == "token-principal_individual"
    assert query["metrics"] == list(subject.INDIVIDUAL_METRICS)
    assert query["periods"] == ["4/2025", "1/2026", "2/2026"]
    jun = [cell for cell in query["cells"] if cell["period"] == "2/2026"]
    assert len(jun) == 6
    assert all(cell["value"] is None and cell["display"] == "N/D" for cell in jun)
    assert all("individual" in cell["source"] for cell in query["cells"])


def test_individual_package_routes_both_sources_with_selected_base(monkeypatch):
    calls = []
    def peers(*args, **kwargs):
        calls.append(("peers", kwargs))
        return {"base": kwargs["base"]}
    monkeypatch.setattr(subject, "peers_history", peers)
    monkeypatch.setitem(sys.modules, "utils.snapshot_pptx_export", SimpleNamespace(
        export_snapshot_powerpoint=lambda snap, peers, carteira, **kwargs: (snap, peers, carteira, kwargs)))
    snapshot = {"base": "Individual", "bank": "BANCO A S.A.", "period": "2/2026", "queried_at": "10/10/2026"}
    snap, query, portfolio, reasons = subject.export_snapshot_package(snapshot, pd.DataFrame(), {})
    assert calls == [("peers", {"base": "Individual"})]
    assert query["base"] == "Individual"
    assert portfolio is None
    assert "N/D na base Individual" in reasons["carteira_unavailable_reason"]
