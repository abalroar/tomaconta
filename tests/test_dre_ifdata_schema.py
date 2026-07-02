import pandas as pd

from tabs.dre_ifdata_schema import (
    STATUS_AMBIGUOUS,
    STATUS_OK,
    build_mapping_candidates,
    calculate_dre,
    load_mapping_config,
    parse_period_metadata,
    resolve_canonical_value,
    validate_dre_identities,
)


def _config_and_mapping(df):
    config = load_mapping_config()
    return config, build_mapping_candidates(df, config)


def test_calculate_dre_closes_core_2025_identities():
    df = pd.DataFrame(
        [
            {
                "Instituição": "BANCO TESTE",
                "Período": "1/2025",
                "Ativo Total": 1000.0,
                "Rendas de Aplicações Interfinanceiras de Liquidez (a)": 10.0,
                "Rendas de Títulos e Valores Mobiliários (b)": 20.0,
                "Rendas de Operações de Crédito (c)": 100.0,
                "Rendas de Arrendamento Financeiro (d)": 0.0,
                "Rendas de Outras Operações com Características de Concessão de Crédito (e)": 5.0,
                "Resultado com Perda Esperada (f)": -15.0,
                "Despesas de Captações (g)": -30.0,
                "Despesas de Instrumentos de Dívida Elegíveis a Capital (h)": -2.0,
                "Resultado com Derivativos (i)": 3.0,
                "Outros Resultados de Intermediação Financeira (j)": 4.0,
                "Resultado de Intermediação Financeira (k) = (a) + (b) + (c) + (d) + (e) + (f) + (g) + (h) + (i) + (j)": 95.0,
                "Resultado com Serviços por Transações de Pagamento (l1)": 2.0,
                "Resultados de Perda Esperada com Transações de Pagamento (l2)": -1.0,
                "Outros Resultados com Transações de Pagamento (l3)": 0.0,
                "Resultado com Transações de Pagamento (l)": 1.0,
                "Rendas de Tarifas Bancárias (m)": 8.0,
                "Outras Rendas de Prestação de Serviços (n)": 7.0,
                "Despesas de Pessoal (o)": -20.0,
                "Despesas Administrativas (p)": -10.0,
                "Resultado com Perdas Esperadas de Outras Operações (q)": -1.0,
                "Despesas de Juros Sobre Capital Próprio de Cooperativas (r)": 0.0,
                "Despesas Tributárias (s)": -2.0,
                "Resultado de Participações (t)": 3.0,
                "Outras Receitas (u)": 5.0,
                "Outras Despesas (v)": -4.0,
                "Outras Receitas / Despesas (w)= (m) + (n) + (o) + (p) + (q) + (r) + (s) + (t) + (u) + (v)": -14.0,
                "Resultado antes da Tributação e Participações (x) = (k) + (l) + (w)": 82.0,
                "Imposto de Renda e Contribuição Social (y)": -20.0,
                "Participações no Lucro (z)": -2.0,
                "Lucro Líquido (aa) = (x) + (y) + (z)": 60.0,
            }
        ]
    )
    config, mapping = _config_and_mapping(df)

    dre_df, validation_df, _ = calculate_dre(df.iloc[0], mapping, config)
    lookup = {row["nome_canônico"]: row for _, row in dre_df.iterrows()}
    validations = {row["target"]: row["status"] for _, row in validation_df.iterrows()}

    assert lookup["net_income"]["valor_r_mil"] == 60.0
    assert lookup["intermediation_result"]["status_validacao"] == STATUS_OK
    assert validations["intermediation_result"] == STATUS_OK
    assert validations["operating_other_result"] == STATUS_OK
    assert validations["pretax_result"] == STATUS_OK
    assert validations["net_income"] == STATUS_OK


def test_partial_dre_keeps_missing_lines_without_failing():
    df = pd.DataFrame(
        [
            {
                "Instituição": "BANCO PARCIAL",
                "Período": "1/2024",
                "Lucro Líquido": 123.0,
            }
        ]
    )
    config, mapping = _config_and_mapping(df)

    dre_df, validation_df, alerts_df = calculate_dre(df.iloc[0], mapping, config)
    lookup = {row["nome_canônico"]: row for _, row in dre_df.iterrows() if row["nome_canônico"]}

    assert lookup["net_income"]["valor_r_mil"] == 123.0
    assert (dre_df["tipo_linha"] == "manual sem fonte").any()
    assert not validation_df.empty
    assert not alerts_df.empty


def test_conflicting_candidate_sources_are_marked_ambiguous():
    df = pd.DataFrame(
        [
            {
                "Instituição": "BANCO AMBIGUO",
                "Período": "sem periodo parseavel",
                "Juros Sobre Capital Próprio (k)": 100.0,
                "Despesas de Juros Sobre Capital Próprio de Cooperativas (r)": -10.0,
            }
        ]
    )
    config, mapping = _config_and_mapping(df)

    resolved = resolve_canonical_value(
        df.iloc[0],
        "jcp_info",
        mapping,
        parse_period_metadata("sem periodo parseavel"),
    )

    assert resolved.status == STATUS_AMBIGUOUS
    assert resolved.value is None


def test_q4_2025_jscp_aa_stays_informative_not_operating_component():
    df = pd.DataFrame(
        [
            {
                "Instituição": "BANCO Q4",
                "Período": "4/2025",
                "Rendas de Tarifas Bancárias (m)": 1.0,
                "Outras Rendas de Prestação de Serviços (n)": 2.0,
                "Despesas de Pessoal (o)": -3.0,
                "Despesas Administrativas (p)": -4.0,
                "Resultado com Perdas Esperadas de Outras Operações (q)": 0.0,
                "Despesas Tributárias (r)": -5.0,
                "Resultado de Participações (s)": 6.0,
                "Outras Receitas (t)": 7.0,
                "Outras Despesas (u)": -8.0,
                "Outras Receitas / Despesas (v)= (m) + (n) + (o) + (p) + (q) + (r) + (s) + (t) + (u)": -4.0,
                "Juros Sobre Capital Próprio de Cooperativas (aa)": -100.0,
            }
        ]
    )
    config, mapping = _config_and_mapping(df)
    period_meta = parse_period_metadata("4/2025")
    resolved = {
        entry["canonical_name"]: resolve_canonical_value(df.iloc[0], entry["canonical_name"], mapping, period_meta)
        for entry in config["rubrics"]
    }

    validation_df = validate_dre_identities(resolved, config)
    operating_status = validation_df.set_index("target").loc["operating_other_result", "status"]

    assert operating_status == STATUS_OK
    assert resolved["jscp_coop_expense"].value is None
    assert resolved["jcp_info"].value == -100.0


def test_validate_dre_identities_flags_broken_closing():
    df = pd.DataFrame(
        [
            {
                "Instituição": "BANCO TESTE",
                "Período": "1/2025",
                "Rendas de Aplicações Interfinanceiras de Liquidez (a)": 10.0,
                "Rendas de Títulos e Valores Mobiliários (b)": 20.0,
                "Rendas de Operações de Crédito (c)": 100.0,
                "Rendas de Arrendamento Financeiro (d)": 0.0,
                "Resultado com Perda Esperada (f)": -15.0,
                "Despesas de Captações (g)": -30.0,
                "Resultado com Derivativos (i)": 3.0,
                "Outros Resultados de Intermediação Financeira (j)": 4.0,
                "Resultado de Intermediação Financeira (k) = (a) + (b) + (c) + (d) + (e) + (f) + (g) + (h) + (i) + (j)": 999.0,
            }
        ]
    )
    config, mapping = _config_and_mapping(df)
    period_meta = parse_period_metadata("1/2025")
    resolved = {
        entry["canonical_name"]: resolve_canonical_value(df.iloc[0], entry["canonical_name"], mapping, period_meta)
        for entry in config["rubrics"]
    }

    validation_df = validate_dre_identities(resolved, config)
    status = validation_df.set_index("target").loc["intermediation_result", "status"]

    assert status in {"erro", "atenção"}
