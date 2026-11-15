"""Prevent repeated official cells from inflating balances or income."""
import pandas as pd
import pytest

from utils.ifdata_cache import extractor
from utils.ifdata_cache.derived_metrics import build_individual_derived_metrics
from utils.ifdata_cache.release_ops import DERIVED_TARGET_SPECS


def rows():
    return [dict(TipoInstituicao=3, CodInst="60701190", AnoMes="202509", NomeRelatorio="Resumo",
                 NumeroRelatorio="1", Grupo=None, Conta=account, NomeColuna=name,
                 DescricaoColuna="[conta]", Saldo=value)
            for account, name, value in [("140220", "Ativo Total", 2_058_293_253_947.9),
                                          ("141870", "Lucro Líquido", 8_596_937_887.19),
                                          ("140246", "Patrimônio Líquido", 165_298_612_044.47)]]


def test_raw_api_identical_triplication_is_deduplicated_before_any_report_pivot(monkeypatch):
    monkeypatch.delenv("TOMACONTA_IFDATA_SOURCE", raising=False)
    monkeypatch.setattr(extractor, "_fetch_json", lambda *args, **kwargs: {"value": rows() * 3})
    result = extractor.extrair_valores("202509", 1, 3)
    assert len(result) == 3
    assert result["Saldo"].sum() == sum(r["Saldo"] for r in rows())
    assert not result.duplicated(["CodInst", "Conta", "NomeColuna"]).any()


def test_summary_triplication_preserves_official_value_and_decimal_ratio(monkeypatch):
    monkeypatch.setattr(extractor, "extrair_valores", lambda *args, **kwargs: pd.DataFrame(rows() * 3))
    monkeypatch.setattr(extractor, "extrair_cadastro", lambda *args: pd.DataFrame({
        "CodInst": ["60701190"], "NomeInstituicao": ["ITAÚ UNIBANCO S.A."]}))
    result = extractor.extrair_resumo("202509", tipo_instituicao=3, manter_codinst=True)
    assert len(result) == 1
    assert result.iloc[0]["Ativo Total"] == rows()[0]["Saldo"]
    assert result.iloc[0]["Lucro Líquido"] == rows()[1]["Saldo"]
    assert result.iloc[0]["ROE Ac. YTD an. (%)"] == pytest.approx(rows()[1]["Saldo"] / rows()[2]["Saldo"] * 4 / 3)


def test_same_official_cell_with_conflicting_value_is_not_aggregated_or_chosen():
    conflict = [*rows(), {**rows()[0], "Saldo": rows()[0]["Saldo"] + 1}]
    with pytest.raises(ValueError, match="valores conflitantes"):
        extractor._deduplicate_reported_values(pd.DataFrame(conflict))


def test_different_official_accounts_with_same_summary_label_are_rejected(monkeypatch):
    conflicting_labels = [*rows(), {**rows()[0], "Conta": "OTHER", "Saldo": 100.0}]
    monkeypatch.setattr(extractor, "extrair_valores", lambda *args, **kwargs: pd.DataFrame(conflicting_labels))
    monkeypatch.setattr(extractor, "extrair_cadastro", lambda *args: pd.DataFrame({
        "CodInst": ["60701190"], "NomeInstituicao": ["ITAÚ UNIBANCO S.A."]}))
    with pytest.raises(ValueError, match="mais de uma conta"):
        extractor.extrair_resumo("202509", tipo_instituicao=3)


def test_zero_missing_and_distinct_institutions_are_preserved():
    source = pd.DataFrame([*rows(), {**rows()[0], "CodInst": "00000001", "Saldo": 0},
                           {**rows()[0], "CodInst": "00000002", "Saldo": None}])
    result = extractor._deduplicate_reported_values(source)
    assert result[result.CodInst.eq("00000001")].iloc[0].Saldo == 0
    assert pd.isna(result[result.CodInst.eq("00000002")].iloc[0].Saldo)


def test_individual_derived_metrics_do_not_mix_homonymous_entities_or_prudential_inputs():
    dre = pd.DataFrame({"CodInst": ["11111111", "22222222"], "Instituição": ["Nome igual"] * 2,
                        "Período": ["1/2025"] * 2,
                        "Resultado com Perda Esperada (f)": [-10, -20],
                        "Resultado com Perda Esperada de Operações de Crédito (f3)": [-10, -20],
                        "Rendas de Operações de Crédito (c)": [100, 200],
                        "Rendas de Aplicações Interfinanceiras de Liquidez (a)": [0, 0],
                        "Rendas de Títulos e Valores Mobiliários (b)": [0, 0],
                        "Rendas de Arrendamento Financeiro (d)": [0, 0],
                        "Rendas de Outras Operações com Características de Concessão de Crédito (e)": [0, 0],
                        "Despesas de Captações (g)": [-10, -20]})
    principal = pd.DataFrame({"CodInst": ["11111111", "22222222"], "Instituição": ["Nome igual"] * 2,
                              "Período": ["1/2025"] * 2, "Captações": [100, 1000], "Carteira de Crédito": [50, 500]})
    prudential = pd.DataFrame({"Instituição": ["Nome igual"], "Período": ["1/2025"],
                                **{f"Valor Contábil Bruto ({k}1)": [9000] for k in "efgh"},
                                "Total Geral": [1000], "Ativos Problemáticos": [100]})
    result, stats = build_individual_derived_metrics(dre, principal, prudential, prudential)
    assert len(result) == 10
    assert set(result["CodInst"]) == {"11111111", "22222222"}
    expenses = result[result["Métrica"].eq("Desp Captação / Captação")].set_index("CodInst")
    assert expenses.loc["11111111", "Valor"] == pytest.approx(-.4)
    assert expenses.loc["22222222", "Valor"] == pytest.approx(-.08)
    problems = result[result["Métrica"].eq("Ativos Problemáticos / Carteira Total")]
    assert problems["Valor"].isna().all()
    costs = result[result["Métrica"].eq("Custo de Crédito (%)")].set_index("CodInst")
    assert costs.loc["11111111", "Valor"] == pytest.approx(.8)
    assert costs.loc["22222222", "Valor"] == pytest.approx(.16)
    assert stats.carteira_fonte == "fallback_principal:Carteira de Crédito"
    kwargs = DERIVED_TARGET_SPECS["derived_metrics_individual"]["kwargs"]
    assert kwargs["ativo_cache_name"] is None
    assert kwargs["carteira_instrumentos_cache_name"] is None
