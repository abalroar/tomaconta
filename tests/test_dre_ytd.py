import math

import pandas as pd

import app1


def test_compute_ytd_irregular_ifdata_frame_requires_june_for_sep_and_dec():
    df = pd.DataFrame(
        [
            {"Instituicao": "Banco A", "Label": "Lucro", "Periodo": "1/2025", "valor": 10.0},
            {"Instituicao": "Banco A", "Label": "Lucro", "Periodo": "3/2025", "valor": 7.0},
            {"Instituicao": "Banco A", "Label": "Lucro", "Periodo": "4/2025", "valor": 9.0},
        ]
    )

    result = app1._compute_ytd_irregular_ifdata_frame(df)
    lookup = {str(row["Periodo"]): row["ytd"] for _, row in result.iterrows()}

    assert lookup["1/2025"] == 10.0
    assert math.isnan(lookup["3/2025"])
    assert math.isnan(lookup["4/2025"])


def test_compute_ytd_irregular_ifdata_frame_accumulates_with_june_when_available():
    df = pd.DataFrame(
        [
            {"Instituicao": "Banco A", "Label": "Lucro", "Periodo": "1/2025", "valor": 10.0},
            {"Instituicao": "Banco A", "Label": "Lucro", "Periodo": "2/2025", "valor": 20.0},
            {"Instituicao": "Banco A", "Label": "Lucro", "Periodo": "3/2025", "valor": 7.0},
            {"Instituicao": "Banco A", "Label": "Lucro", "Periodo": "4/2025", "valor": 9.0},
        ]
    )

    result = app1._compute_ytd_irregular_ifdata_frame(df)
    lookup = {str(row["Periodo"]): row["ytd"] for _, row in result.iterrows()}

    assert lookup["1/2025"] == 10.0
    assert lookup["2/2025"] == 20.0
    assert lookup["3/2025"] == 27.0
    assert lookup["4/2025"] == 29.0


def test_compute_ytd_irregular_ifdata_frame_handles_unsorted_multi_label_input():
    df = pd.DataFrame(
        [
            {"Instituicao": "Banco A", "Label": "Lucro", "Periodo": "3/2025", "valor": 7.0},
            {"Instituicao": "Banco B", "Label": "Lucro", "Periodo": "2/2025", "valor": 30.0},
            {"Instituicao": "Banco A", "Label": "Receita", "Periodo": "2/2025", "valor": 100.0},
            {"Instituicao": "Banco A", "Label": "Lucro", "Periodo": "2/2025", "valor": 20.0},
            {"Instituicao": "Banco B", "Label": "Lucro", "Periodo": "3/2025", "valor": 9.0},
            {"Instituicao": "Banco A", "Label": "Receita", "Periodo": "3/2025", "valor": 40.0},
        ]
    )

    result = app1._compute_ytd_irregular_ifdata_frame(df)
    lookup = {
        (str(row["Instituicao"]), str(row["Label"]), str(row["Periodo"])): row["ytd"]
        for _, row in result.iterrows()
    }

    assert lookup[("Banco A", "Lucro", "3/2025")] == 27.0
    assert lookup[("Banco B", "Lucro", "3/2025")] == 39.0
    assert lookup[("Banco A", "Receita", "3/2025")] == 140.0


def test_dre_ytd_frame_keeps_banco_gm_mar_2026_unannualized_and_reconciled():
    df = pd.DataFrame(
        [
            {
                "Instituicao": "BANCO GM S.A.",
                "Label": "Resultado de Intermediação Financeira Bruto",
                "Periodo": "1/2026",
                "valor": 694_729_682.0,
            },
            {
                "Instituicao": "BANCO GM S.A.",
                "Label": "Rec. Aplicações Interfinanceiras Liquidez",
                "Periodo": "1/2026",
                "valor": 16_168_127.0,
            },
            {
                "Instituicao": "BANCO GM S.A.",
                "Label": "Rec. TVMs",
                "Periodo": "1/2026",
                "valor": 858_797.0,
            },
            {
                "Instituicao": "BANCO GM S.A.",
                "Label": "Rec. Crédito",
                "Periodo": "1/2026",
                "valor": 673_936_534.0,
            },
            {
                "Instituicao": "BANCO GM S.A.",
                "Label": "Rec. Arrendamento Financeiro",
                "Periodo": "1/2026",
                "valor": 3_766_224.0,
            },
            {
                "Instituicao": "BANCO GM S.A.",
                "Label": "Rec. Outras Operações c/ Características de Crédito",
                "Periodo": "1/2026",
                "valor": 0.0,
            },
        ]
    )

    result = app1._build_dre_ytd_ifdata_frame(df)
    gross = result[result["Label"].eq("Resultado de Intermediação Financeira Bruto")].iloc[0]

    assert gross["valor_raw_ifdata"] == 694_729_682.0
    assert gross["valor_ytd"] == 694_729_682.0
    assert gross["ytd"] == 694_729_682.0
    assert math.isnan(gross["valor_anualizado"])

    validation = app1._validate_dre_ytd_identities(result)
    assert set(validation["status"]) == {"OK"}
    identity = validation[validation["regra"].eq("resultado_bruto_igual_soma_componentes_ytd")].iloc[0]
    assert identity["valor_esperado"] == 694_729_682.0
    assert identity["diferenca"] == 0.0


def test_dre_ytd_frame_accumulates_banco_gm_dec_2025_with_june_once():
    df = pd.DataFrame(
        [
            {
                "Instituicao": "BANCO GM S.A.",
                "Label": "Resultado de Intermediação Financeira Bruto",
                "Periodo": "2/2025",
                "valor": 1_309_428_132.0,
            },
            {
                "Instituicao": "BANCO GM S.A.",
                "Label": "Resultado de Intermediação Financeira Bruto",
                "Periodo": "4/2025",
                "valor": 1_358_440_384.0,
            },
        ]
    )

    result = app1._build_dre_ytd_ifdata_frame(df)
    lookup = {str(row["Periodo"]): row for _, row in result.iterrows()}

    assert lookup["2/2025"]["valor_ytd"] == 1_309_428_132.0
    assert lookup["4/2025"]["valor_raw_ifdata"] == 1_358_440_384.0
    assert lookup["4/2025"]["valor_ytd"] == 2_667_868_516.0
    assert lookup["4/2025"]["regra_ytd"] == "raw_ifdata_set_ou_dez_mais_jun"


def test_normalizar_lucro_liquido_accumulates_semester_for_rankings():
    df = pd.DataFrame(
        [
            {"Instituição": "Banco A", "Período": "1/2025", "Lucro Líquido Acumulado YTD": 10.0},
            {"Instituição": "Banco A", "Período": "2/2025", "Lucro Líquido Acumulado YTD": 20.0},
            {"Instituição": "Banco A", "Período": "3/2025", "Lucro Líquido Acumulado YTD": 7.0},
            {"Instituição": "Banco A", "Período": "4/2025", "Lucro Líquido Acumulado YTD": 9.0},
        ]
    )

    result = app1._normalizar_lucro_liquido(df)
    lookup = {row["Período"]: row for _, row in result.iterrows()}

    assert lookup["1/2025"]["Lucro Líquido Acumulado YTD"] == 10.0
    assert lookup["2/2025"]["Lucro Líquido Acumulado YTD"] == 20.0
    assert lookup["3/2025"]["Lucro Líquido Acumulado YTD"] == 27.0
    assert lookup["4/2025"]["Lucro Líquido Acumulado YTD"] == 29.0

    assert lookup["1/2025"]["Lucro Líquido Trimestral"] == 10.0
    assert lookup["2/2025"]["Lucro Líquido Trimestral"] == 10.0
    assert lookup["3/2025"]["Lucro Líquido Trimestral"] == 7.0
    assert lookup["4/2025"]["Lucro Líquido Trimestral"] == 2.0


def test_normalizar_lucro_liquido_does_not_keep_raw_sep_dec_without_june():
    df = pd.DataFrame(
        [
            {"Instituição": "Banco A", "Período": "1/2025", "Lucro Líquido Acumulado YTD": 10.0},
            {"Instituição": "Banco A", "Período": "3/2025", "Lucro Líquido Acumulado YTD": 7.0},
            {"Instituição": "Banco A", "Período": "4/2025", "Lucro Líquido Acumulado YTD": 9.0},
        ]
    )

    result = app1._normalizar_lucro_liquido(df)
    lookup = {row["Período"]: row["Lucro Líquido Acumulado YTD"] for _, row in result.iterrows()}

    assert lookup["1/2025"] == 10.0
    assert math.isnan(lookup["3/2025"])
    assert math.isnan(lookup["4/2025"])


def test_rankings_accumulated_metrics_request_ytd_dependencies():
    result = app1._resolve_rankings_source_request(
        "Resumo",
        "Lucro Líquido Acumulado YTD",
        ["4/2025"],
    )

    assert result["source_kind"] == "lucro_ytd_fast"
    assert set(result["periodos_filter"]) == {"2/2025", "4/2025"}


def test_rankings_direct_simple_metric_uses_light_principal_slice():
    result = app1._resolve_rankings_source_request(
        "Resumo",
        "Ativo Total",
        ["4/2025"],
    )

    assert result["source_kind"] == "principal_light"
    assert result["periodos_filter"] == ("4/2025",)


def test_rankings_lucro_ytd_fast_source_accumulates_without_roe_recalc(monkeypatch):
    df_slice = pd.DataFrame(
        [
            {"Instituição": "Banco A", "Período": "2/2025", "Lucro Líquido Acumulado YTD": 20.0},
            {"Instituição": "Banco A", "Período": "4/2025", "Lucro Líquido Acumulado YTD": 9.0},
        ]
    )
    monkeypatch.setattr(app1, "_get_rankings_principal_slice_df", lambda *_args: df_slice)

    result = app1._get_rankings_lucro_ytd_df(
        "principal:test_rankings_lucro_ytd_fast_source",
        (),
        periodos_filter=("2/2025", "4/2025"),
    )
    lookup = {row["Período"]: row for _, row in result.iterrows()}

    assert lookup["2/2025"]["Lucro Líquido Acumulado YTD"] == 20.0
    assert lookup["4/2025"]["Lucro Líquido Acumulado YTD"] == 29.0
    assert "ROE Ac. Anualizado (%)" not in result.columns


def test_rankings_filters_context_uses_metadata_without_full_principal_load(monkeypatch):
    class _DummyManager:
        def get_cache(self, _name):
            return object()

    def _fail_full_load(*_args, **_kwargs):
        raise AssertionError("Rankings should not materialize the full principal cache for filters")

    monkeypatch.setattr(app1, "get_cache_manager", lambda: _DummyManager())
    monkeypatch.setattr(app1, "_load_cache_metadata", lambda _cache: {"periodos": ["4/2025", "2/2025"]})
    monkeypatch.setattr(app1, "_carregar_dados_periodos_preparados", _fail_full_load)

    result = app1._get_rankings_filters_context(
        "principal:test_rankings_filters_context_metadata",
        (),
    )

    assert result["periodos_disponiveis"] == ("2/2025", "4/2025")


def test_rankings_accumulated_table_requests_ytd_and_roe_dependencies():
    result = app1._resolve_rankings_source_request(
        "Tabela",
        "Ativo Total",
        [],
        periodo_tabela="4/2025",
        modo_tabela="Acumulado",
    )

    assert result["source_kind"] == "analytical_with_capital"
    assert set(result["periodos_filter"]) == {"4/2024", "2/2025", "4/2025"}


def test_periodo_default_helpers_select_latest_available_quarter_or_month():
    assert app1._periodo_mais_recente(["3/2025", "1/2025", "4/2025", "2/2025"]) == "4/2025"
    assert app1._indice_periodo_mais_recente(["3/2025", "4/2025", "2/2025"]) == 1
    assert app1._periodos_mais_recentes(["2/2025", "4/2025", "3/2025"], 2) == ["4/2025", "3/2025"]

    assert app1._periodo_mais_recente(["202509", "202512", "202506"]) == "202512"
    assert app1._indice_periodo_mais_recente(["202509", "202512", "202506"]) == 1
