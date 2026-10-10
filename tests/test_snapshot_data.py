"""Identity, source gaps and accounting windows of the Individual Snapshot."""
import pandas as pd
import pytest

from utils.snapshot_data import individual_snapshot_frame, snapshot_risk_maps, UNAVAILABLE_INDIVIDUAL_COLUMNS
from utils.peers_table_model import arrasto_lookup
from tabs.carteira_4966 import EXPECTED_LOSS_COLUMNS


BANK = "BANCO A S.A."


def individual_frame(periods=("1/2025", "2/2025", "3/2025", "4/2025"), profits=(10, 25, 12, 30)):
    return pd.DataFrame({"CodInst": "12345678", "Instituição": BANK, "Período": list(periods),
                         "Ativo Total": 1000.0, "Carteira de Crédito": 500.0,
                         "Carteira de Crédito Classificada": 490.0, "Captações": 600.0,
                         "Patrimônio Líquido": 100.0, "Lucro Líquido": list(profits),
                         "Lucro Líquido Acumulado YTD": list(profits),
                         "ROE Ac. YTD an. (%)": .123})


def test_individual_profit_is_normalized_once_with_current_equity_roe():
    source = individual_frame()
    frame = individual_snapshot_frame(source, BANK)
    assert frame["Lucro Líquido Acumulado YTD"].tolist() == [10, 25, 37, 55]
    assert frame["Lucro Líquido Trimestral"].tolist() == [10, 15, 12, 18]
    assert frame["ROE Ac. Anualizado (%)"].tolist() == pytest.approx([.4, .5, 37 * 4 / 3 / 100, .55])
    assert frame["ROE trimestral anualizado (%)"].tolist() == pytest.approx([.4, .6, .48, .72])
    assert frame["ROE Ac. YTD an. (%)"].equals(frame["ROE Ac. Anualizado (%)"])
    pd.testing.assert_frame_equal(individual_snapshot_frame(frame, BANK), frame)
    assert source["Lucro Líquido Acumulado YTD"].tolist() == [10, 25, 12, 30]


def test_individual_profit_windows_remain_missing_without_the_required_quarter():
    frame = individual_snapshot_frame(individual_frame(("2/2025", "3/2025", "4/2026"), (25, 12, 30)), BANK)
    values = frame.set_index("Período")
    assert pd.isna(values.loc["2/2025", "Lucro Líquido Trimestral"])
    assert values.loc["3/2025", "Lucro Líquido Acumulado YTD"] == 37
    assert pd.isna(values.loc["4/2026", "Lucro Líquido Acumulado YTD"])
    assert pd.isna(values.loc["4/2026", "Lucro Líquido Trimestral"])
    assert pd.isna(values.loc["4/2026", "ROE Ac. Anualizado (%)"])
    assert "base de junho" in values.loc["4/2026", "Trace::Lucro YTD::Observação"]
    assert "base de março" in values.loc["2/2025", "Trace::Lucro Trimestral::Observação"]


def test_individual_preserves_zero_and_absence_and_requires_positive_denominators():
    source = individual_frame(("1/2025", "2/2025", "3/2025"), (0, None, 12))
    source["Carteira de Crédito"] = [0, None, 500]
    source["Carteira de Crédito Classificada"] = [490, None, 490]
    source["Captações"] = [600, 0, -10]
    source["Patrimônio Líquido"] = [100, 0, -10]
    frame = individual_snapshot_frame(source, BANK)
    assert frame["Carteira de Crédito Bruta"].iloc[0] == 0
    assert frame["Crédito / Captações"].iloc[0] == 0
    assert frame["ROE Ac. Anualizado (%)"].iloc[0] == 0
    assert frame["ROE trimestral anualizado (%)"].iloc[0] == 0
    assert pd.isna(frame["Carteira de Crédito Bruta"].iloc[1])
    assert frame["Crédito / Captações"].iloc[1:].isna().all()
    assert frame["ROE Ac. Anualizado (%)"].iloc[1:].isna().all()


def test_individual_scope_cannot_inherit_contaminated_capital_loss_or_risk_values():
    source = individual_frame()
    for column in UNAVAILABLE_INDIVIDUAL_COLUMNS:
        source[column] = .99
    source["Trace::Perda Esperada::Perda Esperada (e2)"] = -10
    source["CapitalDisponivel"] = True
    frame = individual_snapshot_frame(source, BANK)
    assert frame[list(UNAVAILABLE_INDIVIDUAL_COLUMNS)].isna().all().all()
    assert frame["Trace::Perda Esperada::Perda Esperada (e2)"].isna().all()
    assert not frame["CapitalDisponivel"].any()
    assert set(frame["Trace::Snapshot::Base"]) == {"Individual"}


def test_individual_identity_is_exact_and_code_handles_official_name_change():
    selected = individual_frame()
    other = selected.assign(Instituição="BANCO A - PRUDENCIAL", CodInst="P123", **{"Ativo Total": 9000})
    combined = pd.concat([selected, other], ignore_index=True)
    assert individual_snapshot_frame(combined, "BANCO A").empty
    frame = individual_snapshot_frame(combined, "Nome atual (CodInst 12345678)", codes=("12345678",))
    assert len(frame) == 4
    assert set(frame["CodInst"]) == {"12345678"}
    assert set(frame["Ativo Total"]) == {1000}
    with pytest.raises(ValueError, match="única entidade"):
        individual_snapshot_frame(combined, BANK, codes=("12345678", "P123"))


def test_ambiguous_same_name_or_duplicate_period_does_not_choose_a_row():
    combined = pd.concat([individual_frame(), individual_frame().assign(CodInst="87654321")], ignore_index=True)
    with pytest.raises(ValueError, match="única entidade"):
        individual_snapshot_frame(combined, BANK)
    with pytest.raises(ValueError, match="mais de um registro"):
        individual_snapshot_frame(pd.concat([individual_frame()] * 2, ignore_index=True), BANK)


def test_individual_credit_fallback_is_classified_only_when_direct_credit_is_missing():
    source = individual_frame(("1/2024", "2/2024"), (10, 25))
    source["Carteira de Crédito"] = [None, 0]
    frame = individual_snapshot_frame(source, BANK)
    assert frame["Carteira de Crédito Bruta"].tolist() == [490, 0]
    assert frame["Trace::Carteira::Status"].tolist() == ["official_individual_classified", "official_individual_credit"]


def test_individual_derived_expense_joins_exact_identity_and_keeps_zero_or_absence():
    source = individual_frame()
    derived = pd.DataFrame([
        {"Instituição": name, "Período": period, "Métrica": "Desp Captação / Captação", "Valor": value}
        for name, period, value in [(BANK, "1/2025", 0), (BANK, "2/2025", -.06),
                                     ("BANCO A - PRUDENCIAL", "3/2025", -.15), ("BANCO A", "4/2025", -.18)]
    ])
    frame = individual_snapshot_frame(source, BANK, derived)
    assert frame["Desp Captação / Captação"].iloc[0] == 0
    assert frame["Desp Captação / Captação"].iloc[1] == -.06
    assert frame["Desp Captação / Captação"].iloc[2:].isna().all()
    duplicate = pd.concat([derived, derived.iloc[:1]], ignore_index=True)
    assert individual_snapshot_frame(source, BANK, duplicate)["Desp Captação / Captação"].isna().all()


def risk_frame():
    return pd.DataFrame({"Instituição": BANK, "Período": ["4/2025", "1/2026"],
                         "Carteira Total 4.966": [1000, 1200], "Inadimplência 4.966": [20, 30],
                         **{f"Trace::Perda Esperada::{column}": [-10, -15] for column in EXPECTED_LOSS_COLUMNS}})


def test_snapshot_risk_uses_exact_shared_4966_provision_components():
    source = risk_frame()
    maps = snapshot_risk_maps(source, BANK, ["4/2025", "1/2026"])
    lookup = arrasto_lookup(source)
    assert maps["npl90"] == {"4/2025": .02, "1/2026": .025}
    assert maps["coverage90"] == {"4/2025": 2, "1/2026": 2}
    for name, key in (("npl90", "Inadimplência / Carteira Total"), ("coverage90", "PDD / Inadimplência (arrasto)")):
        for period in maps[name]:
            assert maps[name][period] == lookup[key, BANK, period]["value"]


def test_snapshot_risk_never_fills_individual_or_pre2025_from_conglomerate_or_another_period():
    source = risk_frame()
    result = snapshot_risk_maps(source, BANK, ["4/2024", "1/2026"], "Individual")
    assert all(value is None for key in ("npl90", "coverage90") for value in result[key].values())
    assert all("base Individual" in value["reason"] for statuses in result["status"].values() for value in statuses.values())
    result = snapshot_risk_maps(source, BANK, ["4/2024", "1/2026"])
    assert result["npl90"]["4/2024"] is None
    assert "desde mar/2025" in result["status"]["npl90"]["4/2024"]["reason"]
    assert snapshot_risk_maps(source, "BANCO A", ["1/2026"])["npl90"]["1/2026"] is None


def test_missing_pdd_component_leaves_coverage_missing_but_preserves_npl():
    source = risk_frame().drop(columns=f"Trace::Perda Esperada::{EXPECTED_LOSS_COLUMNS[-1]}")
    result = snapshot_risk_maps(source, BANK, ["4/2025", "1/2026"])
    assert result["npl90"]["1/2026"] == .025
    assert result["coverage90"]["1/2026"] is None
    assert "faltam colunas obrigatórias" in result["status"]["coverage90"]["1/2026"]["reason"]
