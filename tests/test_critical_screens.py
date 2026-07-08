import json
from pathlib import Path

import pandas as pd

from utils.ifdata_cache.base import CacheResult
from utils.ifdata_cache.manager import CacheManager
from utils.ifdata_cache.critical_screens import (
    CriticalScreensCache,
    CRITICAL_SCREENS_SCHEMA_VERSION,
    _build_selected_institution_code_map,
    _load_runtime_passivo_support,
    _supplement_runtime_missing_funding,
    _load_bloprud_sources,
    _validate_critical_screens_semantics,
    build_critical_screens_dataframe,
    critical_screens_needs_refresh,
    get_critical_screens_runtime_status,
    load_critical_screens_slice,
    materialize_critical_screens_cache,
    resolve_carteira_credito_bruta_value,
    resolve_core_funding_value,
)


def test_build_critical_screens_dataframe_materializes_expected_metrics(tmp_path: Path):
    (tmp_path / "conglomerados.csv").write_text(
        "Conglomerado CDIGO 80099 NOME ITAU - PRUDENCIAL TIPO TESTE "
        "CNPJ 12345678000100 Itau Unibanco LIDER",
        encoding="utf-8",
    )

    principal = pd.DataFrame(
        [
            {
                "Instituição": "ITAU - PRUDENCIAL",
                "Período": "4/2024",
                "Ativo Total": 1800.0,
                "Patrimônio Líquido": 200.0,
                "Lucro Líquido Acumulado YTD": 40.0,
                "Captações": 480.0,
            },
            {
                "Instituição": "ITAU - PRUDENCIAL",
                "Período": "1/2025",
                "Ativo Total": 1900.0,
                "Patrimônio Líquido": 220.0,
                "Lucro Líquido Acumulado YTD": 10.0,
                "Captações": 500.0,
            },
        ]
    )
    ativo = pd.DataFrame(
        [
            {
                "Instituição": "ITAU - PRUDENCIAL",
                "Período": "1/2025",
                "Disponibilidades (a)": 100.0,
                "Aplicações Interfinanceiras de Liquidez (b)": 200.0,
                "Títulos e Valores Mobiliários (c)": 300.0,
                "Valor Contábil Bruto (e1)": 1000.0,
                "Valor Contábil Bruto (f1)": 200.0,
                "Valor Contábil Bruto (g1)": 300.0,
                "Valor Contábil Bruto (h1)": 400.0,
                "Perda Esperada (e2)": 10.0,
                "Perda Esperada (f2)": 20.0,
                "Perda Esperada (g2)": 30.0,
                "Perda Esperada (h2)": 40.0,
            }
        ]
    )
    passivo = pd.DataFrame(
        [
            {
                "Instituição": "ITAU - PRUDENCIAL",
                "Período": "1/2025",
                "Captações (e) = (a) + (b) + (c) + (d)": 500.0,
                "Instrumentos de Dívida Elegíveis a Capital (h)": 50.0,
                "Depósitos à Vista (a1)": 10.0,
                "Depósitos de Poupança (a2)": 20.0,
                "Depósitos Interfinanceiros (a3)": 30.0,
                "Depósitos a Prazo (a4)": 40.0,
                "Outros Depósitos (a5)": 5.0,
                "Depósitos Outros (a6)": 1.0,
            }
        ]
    )
    dre = pd.DataFrame(
        [
            {
                "Instituição": "ITAU - PRUDENCIAL",
                "Período": "1/2025",
                "Resultado com Perda Esperada (f)": -12.0,
                "Rendas de Operações de Crédito (c)": 90.0,
                "Rendas de Arrendamento Financeiro (d)": 10.0,
                "Rendas de Outras Operações com Características de Concessão de Crédito (e)": 5.0,
                "Rendas de Aplicações Interfinanceiras de Liquidez (a)": 8.0,
                "Rendas de Títulos e Valores Mobiliários (b)": 7.0,
                "Despesas de Captações (g)": 11.0,
            }
        ]
    )
    capital = pd.DataFrame(
        [
            {
                "Instituição": "ITAU - PRUDENCIAL",
                "Período": "1/2025",
                "Capital Principal": 120.0,
                "Capital Complementar": 30.0,
                "Capital Nível II": 20.0,
                "RWA Total": 1000.0,
            }
        ]
    )
    carteira_pf = pd.DataFrame(
        [
            {"Instituição": "Itau Unibanco", "Período": "1/2025", "Total da Carteira PF": 100.0},
        ]
    )
    carteira_pj = pd.DataFrame(
        [
            {"Instituição": "Itau Unibanco", "Período": "1/2025", "Total da Carteira PJ": 200.0},
        ]
    )
    carteira_instr = pd.DataFrame(
        [
            {
                "Instituição": "Itau Unibanco",
                "Período": "1/2025",
                "C4": 10.0,
                "C5": 5.0,
                "Total Geral": 400.0,
                "Inadimplência": 12.0,
                "Ativos problemáticos": 24.0,
            },
        ]
    )
    bloprud = pd.DataFrame(
        [
            {
                "DATA_BASE": "202503",
                "DOCUMENTO": 4060,
                "NOME_INSTITUICAO": "ITAU UNIBANCO HOLDING S.A.",
                "COD_CONGL": "C0080099",
                "NOME_CONGL": "ITAU - PRUDENCIAL",
                "CONTA": "1490000004",
                "SALDO": 50.0,
            },
            {
                "DATA_BASE": "202503",
                "DOCUMENTO": 4060,
                "NOME_INSTITUICAO": "ITAU UNIBANCO HOLDING S.A.",
                "COD_CONGL": "C0080099",
                "NOME_CONGL": "ITAU - PRUDENCIAL",
                "CONTA": "1890000006",
                "SALDO": 10.0,
            },
            {
                "DATA_BASE": "202503",
                "DOCUMENTO": 4060,
                "NOME_INSTITUICAO": "ITAU UNIBANCO HOLDING S.A.",
                "COD_CONGL": "C0080099",
                "NOME_CONGL": "ITAU - PRUDENCIAL",
                "CONTA": "3311000002",
                "SALDO": 300.0,
            },
            {
                "DATA_BASE": "202503",
                "DOCUMENTO": 4060,
                "NOME_INSTITUICAO": "ITAU UNIBANCO HOLDING S.A.",
                "COD_CONGL": "C0080099",
                "NOME_CONGL": "ITAU - PRUDENCIAL",
                "CONTA": "3312000001",
                "SALDO": 400.0,
            },
            {
                "DATA_BASE": "202503",
                "DOCUMENTO": 4060,
                "NOME_INSTITUICAO": "ITAU UNIBANCO HOLDING S.A.",
                "COD_CONGL": "C0080099",
                "NOME_CONGL": "ITAU - PRUDENCIAL",
                "CONTA": "3313000000",
                "SALDO": 500.0,
            },
        ]
    )

    result = build_critical_screens_dataframe(
        df_principal=principal,
        df_ativo=ativo,
        df_passivo=passivo,
        df_capital=capital,
        df_dre=dre,
        df_carteira_pf=carteira_pf,
        df_carteira_pj=carteira_pj,
        df_carteira_instrumentos=carteira_instr,
        df_bloprudencial=bloprud,
        base_dir=tmp_path,
    )

    row = result[result["Período"] == "1/2025"].iloc[0]
    assert row["Instituição"] == "ITAU - PRUDENCIAL"
    assert row["Ativo Total"] == 1900.0
    assert row["Patrimônio Líquido"] == 220.0
    assert row["Lucro Líquido Acumulado YTD"] == 10.0
    assert row["Lucro Líquido Trimestral"] == 10.0
    assert round(row["ROE Ac. Anualizado (%)"], 6) == round((10.0 * 4.0) / ((220.0 + 200.0) / 2.0), 6)
    assert round(row["ROE trimestral anualizado (%)"], 6) == round((10.0 * 4.0) / ((220.0 + 200.0) / 2.0), 6)
    assert row["Ativos Líquidos"] == 600.0
    assert row["Depósitos Totais"] == 106.0
    assert row["Trace::Depósitos Totais::Status"] == "fallback_components"
    assert row["Trace::Depósitos Totais::Campo Selecionado"] is None
    assert row["Trace::Depósitos Totais::Soma Subtipos"] == 106.0
    assert row["Core Funding*"] == 550.0
    assert row["Trace::Carteira::Status"] == "official_vcb_components"
    assert row["Trace::Carteira::Campo Selecionado"] == "Valor Contábil Bruto (e1) + Valor Contábil Bruto (f1) + Valor Contábil Bruto (g1) + Valor Contábil Bruto (h1)"
    assert round(row["Crédito / Captações"], 6) == round(1900.0 / 550.0, 6)
    assert round(row["Desp Captação / Captação"], 6) == round((11.0 * 4.0) / 500.0, 6)
    assert row["Carteira de Crédito Bruta"] == 1900.0
    assert row["Perda Esperada"] == 100.0
    assert round(row["Perda Esperada / Carteira de Crédito*"], 6) == round(100.0 / 1900.0, 6)
    assert row["Carteira de Crédito Classificada"] == 300.0
    assert row["Carteira de Créd. Class. C4+C5"] == 15.0
    assert row["Carteira Total 4.966"] == 400.0
    assert row["Inadimplência 4.966"] == 12.0
    assert row["Inadimplência"] == 12.0
    assert row["Ativos Problemáticos 4.966"] == 24.0
    assert round(row["Inadimplência / Carteira Total"], 6) == round(12.0 / 400.0, 6)
    assert round(row["Inadimplência / Carteira de Crédito"], 6) == round(12.0 / 1900.0, 6)
    assert round(row["Ativos Problemáticos / Carteira Total"], 6) == round(24.0 / 400.0, 6)
    assert round(row["Ativos Estágio 3 / Carteira de Crédito"], 6) == round(500.0 / 1900.0, 6)
    assert round(row["Perda Esperada / Estágio 3"], 6) == 0.2
    assert round(row["Perda Esperada / Est2+3"], 6) == round(100.0 / (400.0 + 500.0), 6)
    assert round(row["Índice de Capital Principal (CET1)"], 6) == 0.12
    assert round(row["Índice de Basileia Total (%)"], 6) == 0.17
    assert row["Trace::Carteira 4.966::Total Geral"] == 400.0
    assert row["Trace::Carteira 4.966::Inadimplência"] == 12.0
    assert row["Trace::Carteira 4.966::Ativos Problemáticos"] == 24.0
    assert row["Trace::Ativos Líquidos::Disponibilidades (a)"] == 100.0
    assert row["Trace::Capital::Capital Principal"] == 120.0
    assert bool(row["CapitalDisponivel"])
    assert bool(row["BloprudencialDisponivel"])
    assert bool(row["QualidadeCarteiraDisponivel"])


def test_build_critical_screens_dataframe_prefers_row_level_official_deposit_aggregate():
    principal = pd.DataFrame(
        [
            {
                "Instituição": "TEST BANK - PRUDENCIAL",
                "Período": "4/2024",
                "Ativo Total": 1000.0,
                "Patrimônio Líquido": 100.0,
                "Lucro Líquido Acumulado YTD": 20.0,
            },
        ]
    )
    passivo = pd.DataFrame(
        [
            {
                "Instituição": "TEST BANK - PRUDENCIAL",
                "Período": "4/2024",
                "Depósitos (a)": None,
                "Depósito Total (a)": 120.0,
                "Depósitos à Vista (a1)": 10.0,
                "Depósitos de Poupança (a2)": 20.0,
                "Depósitos Interfinanceiros (a3)": 30.0,
                "Depósitos a Prazo (a4)": 40.0,
                "Outros Depósitos (a5)": 5.0,
                "Depósitos Outros (a6)": 1.0,
            }
        ]
    )

    result = build_critical_screens_dataframe(
        df_principal=principal,
        df_ativo=pd.DataFrame(),
        df_passivo=passivo,
        df_capital=pd.DataFrame(),
        df_dre=pd.DataFrame(),
        df_carteira_pf=pd.DataFrame(),
        df_carteira_pj=pd.DataFrame(),
        df_carteira_instrumentos=pd.DataFrame(),
        df_bloprudencial=pd.DataFrame(),
    )

    row = result.iloc[0]
    assert row["Depósitos Totais"] == 120.0
    assert row["Trace::Depósitos Totais::Status"] == "official_aggregate"
    assert row["Trace::Depósitos Totais::Campo Selecionado"] == "Depósito Total (a)"
    assert row["Trace::Depósitos Totais::Agregado Oficial"] == 120.0
    assert row["Trace::Depósitos Totais::Soma Subtipos"] == 106.0
    assert round(row["Trace::Depósitos Totais::Conflito vs Soma (%)"], 6) == round(abs(106.0 - 120.0) / 120.0, 6)


def test_build_critical_screens_dataframe_marks_structural_prudential_unavailability():
    principal = pd.DataFrame(
        [
            {
                "Instituição": "TEST BANK - PRUDENCIAL",
                "Período": "4/2024",
                "Ativo Total": 1000.0,
                "Patrimônio Líquido": 100.0,
                "Lucro Líquido Acumulado YTD": 20.0,
            },
        ]
    )
    ativo = pd.DataFrame(
        [
            {
                "Instituição": "TEST BANK - PRUDENCIAL",
                "Período": "4/2024",
                "Operações de Crédito (d1)": 500.0,
                "Arrendamento Mercantil a Receber (e1)": 50.0,
                "Outros Créditos - Líquido de Provisão (f)": 25.0,
                "Perda Esperada (e2)": 10.0,
            },
        ]
    )

    result = build_critical_screens_dataframe(
        df_principal=principal,
        df_ativo=ativo,
        df_passivo=pd.DataFrame(),
        df_capital=pd.DataFrame(),
        df_dre=pd.DataFrame(),
        df_carteira_pf=pd.DataFrame(),
        df_carteira_pj=pd.DataFrame(),
        df_carteira_instrumentos=pd.DataFrame(),
        df_bloprudencial=pd.DataFrame(),
    )

    row = result.iloc[0]
    assert row["Trace::Bloprudencial::Status"] == "source_structurally_unavailable"
    assert row["Trace::Qualidade Carteira::Status"] == "source_structurally_unavailable"
    assert pd.isna(row["Perda Esperada / Estágio 3"])


def test_build_critical_screens_dataframe_uses_loss_magnitude_for_stage3_coverage():
    principal = pd.DataFrame(
        [
            {
                "Instituição": "GM - PRUDENCIAL",
                "Período": "1/2026",
                "Ativo Total": 1000.0,
                "Patrimônio Líquido": 100.0,
                "Lucro Líquido Acumulado YTD": 10.0,
            }
        ]
    )
    ativo = pd.DataFrame(
        [
            {
                "Instituição": "GM - PRUDENCIAL",
                "Período": "1/2026",
                "Valor Contábil Bruto (e1)": 1000.0,
                "Valor Contábil Bruto (f1)": 0.0,
                "Valor Contábil Bruto (g1)": 0.0,
                "Valor Contábil Bruto (h1)": 0.0,
                "Perda Esperada (e2)": -399.13,
            }
        ]
    )
    bloprud = pd.DataFrame(
        [
            {
                "DATA_BASE": "202603",
                "DOCUMENTO": 4060,
                "NOME_INSTITUICAO": "BCO GM S.A.",
                "NOME_CONGL": "GM - PRUDENCIAL",
                "CONTA": "3313000000",
                "SALDO": 333.2,
            }
        ]
    )

    result = build_critical_screens_dataframe(
        df_principal=principal,
        df_ativo=ativo,
        df_passivo=pd.DataFrame(),
        df_capital=pd.DataFrame(),
        df_dre=pd.DataFrame(),
        df_carteira_pf=pd.DataFrame(),
        df_carteira_pj=pd.DataFrame(),
        df_carteira_instrumentos=pd.DataFrame(),
        df_bloprudencial=bloprud,
    )

    row = result.iloc[0]
    assert row["Perda Esperada"] == -399.13
    assert round(row["Perda Esperada / Estágio 3"], 6) == round(399.13 / 333.2, 6)
    assert round(row["Perda Esperada / Carteira de Crédito*"], 6) == round(399.13 / 1000.0, 6)


def test_resolve_core_funding_value_requires_all_components_post_2025():
    pre_2025 = resolve_core_funding_value(
        year_ref=2024,
        captacoes_value=120.0,
        instrumentos_value=None,
    )
    assert pre_2025["value"] == 120.0
    assert pre_2025["source_kind"] == "official_captacoes"

    post_2025_missing = resolve_core_funding_value(
        year_ref=2025,
        captacoes_value=120.0,
        instrumentos_value=None,
    )
    assert post_2025_missing["value"] is None
    assert post_2025_missing["source_kind"] == "missing_required_component"


def test_resolve_carteira_credito_bruta_value_prefers_canonical_components_and_marks_fallbacks():
    legacy = resolve_carteira_credito_bruta_value(
        year_ref=2024,
        legacy_credito_value=100.0,
        legacy_arrendamento_value=20.0,
        legacy_outros_value=5.0,
        vcb_credito_value=None,
        vcb_arrendamento_value=None,
        vcb_outras_ops_value=None,
        vcb_pagamentos_value=None,
        net_credito_value=90.0,
        net_arrendamento_value=10.0,
        net_outras_ops_value=5.0,
        net_pagamentos_value=3.0,
    )
    assert legacy["value"] == 125.0
    assert legacy["source_kind"] == "official_legacy_components"

    vcb = resolve_carteira_credito_bruta_value(
        year_ref=2025,
        legacy_credito_value=None,
        legacy_arrendamento_value=None,
        legacy_outros_value=None,
        vcb_credito_value=100.0,
        vcb_arrendamento_value=20.0,
        vcb_outras_ops_value=5.0,
        vcb_pagamentos_value=3.0,
        net_credito_value=90.0,
        net_arrendamento_value=10.0,
        net_outras_ops_value=5.0,
        net_pagamentos_value=3.0,
    )
    assert vcb["value"] == 128.0
    assert vcb["source_kind"] == "official_vcb_components"

    fallback = resolve_carteira_credito_bruta_value(
        year_ref=2025,
        legacy_credito_value=None,
        legacy_arrendamento_value=None,
        legacy_outros_value=None,
        vcb_credito_value=100.0,
        vcb_arrendamento_value=None,
        vcb_outras_ops_value=5.0,
        vcb_pagamentos_value=3.0,
        net_credito_value=90.0,
        net_arrendamento_value=10.0,
        net_outras_ops_value=5.0,
        net_pagamentos_value=3.0,
    )
    assert fallback["value"] == 108.0
    assert fallback["source_kind"] == "fallback_net_components"

    missing = resolve_carteira_credito_bruta_value(
        year_ref=2025,
        legacy_credito_value=None,
        legacy_arrendamento_value=None,
        legacy_outros_value=None,
        vcb_credito_value=100.0,
        vcb_arrendamento_value=None,
        vcb_outras_ops_value=None,
        vcb_pagamentos_value=None,
        net_credito_value=90.0,
        net_arrendamento_value=None,
        net_outras_ops_value=None,
        net_pagamentos_value=None,
    )
    assert missing["value"] is None
    assert missing["source_kind"] == "missing_required_component"


def test_supplement_runtime_missing_funding_creates_trace_columns_when_bundle_is_stale(monkeypatch, tmp_path: Path):
    base = pd.DataFrame(
        [
            {
                "Instituição": "TEST BANK - PRUDENCIAL",
                "Período": "4/2025",
                "Carteira de Crédito Bruta": 600.0,
                "Core Funding": None,
                "Core Funding*": None,
                "Crédito / Captações": None,
            }
        ]
    )
    support = pd.DataFrame(
        [
            {
                "Instituição": "TEST BANK - PRUDENCIAL",
                "Período": "4/2025",
                "Core Funding": 1000.0,
                "Trace::Core Funding::Captações (e)": 900.0,
                "Trace::Core Funding::Instrumentos de Dívida Elegíveis a Capital (h)": 100.0,
                "Trace::Core Funding::Status": "official_components",
                "Trace::Core Funding::Campo Selecionado": "Captações (e) + Instrumentos de Dívida Elegíveis a Capital (h)",
            }
        ]
    )

    monkeypatch.setattr(
        "utils.ifdata_cache.critical_screens._load_runtime_passivo_support",
        lambda **kwargs: support.copy(),
    )

    out = _supplement_runtime_missing_funding(base, base_dir=tmp_path)
    row = out.iloc[0]

    assert row["Core Funding"] == 1000.0
    assert row["Core Funding*"] == 1000.0
    assert row["Crédito / Captações"] == 0.6
    assert row["Trace::Core Funding::Captações (e)"] == 900.0
    assert row["Trace::Core Funding::Instrumentos de Dívida Elegíveis a Capital (h)"] == 100.0
    assert row["Trace::Core Funding::Status"] == "official_components"
    assert row["Trace::Core Funding::Campo Selecionado"] == "Captações (e) + Instrumentos de Dívida Elegíveis a Capital (h)"


def test_build_critical_screens_dataframe_marks_carteira_fallback_when_only_net_components_are_complete():
    principal = pd.DataFrame(
        [
            {
                "Instituição": "TEST BANK - PRUDENCIAL",
                "Período": "4/2025",
                "Ativo Total": 1000.0,
                "Patrimônio Líquido": 100.0,
                "Lucro Líquido Acumulado YTD": 20.0,
            },
        ]
    )
    ativo = pd.DataFrame(
        [
            {
                "Instituição": "TEST BANK - PRUDENCIAL",
                "Período": "4/2025",
                "Valor Contábil Bruto (e1)": 500.0,
                "Valor Contábil Bruto (f1)": None,
                "Valor Contábil Bruto (g1)": 100.0,
                "Valor Contábil Bruto (h1)": 50.0,
                "Operações de Crédito (e)": 480.0,
                "Operações de Arrendamento Financeiro (f)": 20.0,
                "Outras Operações com Características de Concessão de Crédito (g)": 10.0,
                "Valores a Receber de Transações de Pagamentos - Usuários Finais (Pós-pago) (h)": 5.0,
            },
        ]
    )

    result = build_critical_screens_dataframe(
        df_principal=principal,
        df_ativo=ativo,
        df_passivo=pd.DataFrame(),
        df_capital=pd.DataFrame(),
        df_dre=pd.DataFrame(),
        df_carteira_pf=pd.DataFrame(),
        df_carteira_pj=pd.DataFrame(),
        df_carteira_instrumentos=pd.DataFrame(),
        df_bloprudencial=pd.DataFrame(),
    )

    row = result.iloc[0]
    assert row["Carteira de Crédito Bruta"] == 515.0
    assert row["Trace::Carteira::Status"] == "fallback_net_components"
    assert row["Trace::Carteira::Campo Selecionado"] == "Operações de Crédito (e) + Operações de Arrendamento Financeiro (f) + Outras Operações com Características de Concessão de Crédito (g) + Valores a Receber de Transações de Pagamentos - Usuários Finais (Pós-pago) (h)"


def test_build_critical_screens_dataframe_marks_core_funding_missing_when_post_2025_component_is_missing():
    principal = pd.DataFrame(
        [
            {
                "Instituição": "TEST BANK - PRUDENCIAL",
                "Período": "4/2025",
                "Ativo Total": 1000.0,
                "Patrimônio Líquido": 100.0,
                "Lucro Líquido Acumulado YTD": 20.0,
            },
        ]
    )
    ativo = pd.DataFrame(
        [
            {
                "Instituição": "TEST BANK - PRUDENCIAL",
                "Período": "4/2025",
                "Valor Contábil Bruto (e1)": 500.0,
            },
        ]
    )
    passivo = pd.DataFrame(
        [
            {
                "Instituição": "TEST BANK - PRUDENCIAL",
                "Período": "4/2025",
                "Captações (e) = (a) + (b) + (c) + (d)": 210.0,
                "Instrumentos de Dívida Elegíveis a Capital (h)": None,
            }
        ]
    )

    result = build_critical_screens_dataframe(
        df_principal=principal,
        df_ativo=ativo,
        df_passivo=passivo,
        df_capital=pd.DataFrame(),
        df_dre=pd.DataFrame(),
        df_carteira_pf=pd.DataFrame(),
        df_carteira_pj=pd.DataFrame(),
        df_carteira_instrumentos=pd.DataFrame(),
        df_bloprudencial=pd.DataFrame(),
    )

    row = result.iloc[0]
    assert pd.isna(row["Core Funding"])
    assert pd.isna(row["Core Funding*"])
    assert row["Trace::Core Funding::Status"] == "missing_required_component"
    assert row["Trace::Core Funding::Campo Selecionado"] == "Captações (e) + Instrumentos de Dívida Elegíveis a Capital (h)"
    assert pd.isna(row["Crédito / Captações"])


def test_validate_critical_screens_semantics_flags_incomplete_post_2025_core_funding():
    df = pd.DataFrame(
        [
            {
                "Período": "4/2025",
                "Core Funding": 210.0,
                "Trace::Core Funding::Status": "official_components",
                "Trace::Core Funding::Captações (e)": 210.0,
                "Trace::Core Funding::Instrumentos de Dívida Elegíveis a Capital (h)": None,
            }
        ]
    )

    issues = _validate_critical_screens_semantics(df)

    assert issues["core_funding_post2025_without_all_components"] == 1


def test_build_critical_screens_dataframe_resolves_passivo_placeholder_via_principal_codinst():
    principal = pd.DataFrame(
        [
            {
                "Instituição": "ITAU - PRUDENCIAL",
                "Período": "4/2024",
                "Ativo Total": 1800.0,
                "Patrimônio Líquido": 200.0,
                "Lucro Líquido Acumulado YTD": 40.0,
            },
            {
                "Instituição": "ITAU - PRUDENCIAL",
                "Período": "4/2025",
                "CodInst": "C0080099",
                "Ativo Total": 1900.0,
                "Patrimônio Líquido": 220.0,
                "Lucro Líquido Acumulado YTD": 44.0,
            },
        ]
    )
    ativo = pd.DataFrame(
        [
            {
                "Instituição": "ITAU - PRUDENCIAL",
                "Período": "4/2025",
                "Valor Contábil Bruto (e1)": 1000.0,
                "Valor Contábil Bruto (f1)": 200.0,
                "Valor Contábil Bruto (g1)": 300.0,
                "Valor Contábil Bruto (h1)": 400.0,
            }
        ]
    )
    passivo = pd.DataFrame(
        [
            {
                "Instituição": "[IF C0080099]",
                "Período": "4/2025",
                "CodInst": "C0080099",
                "Captações (e) = (a) + (b) + (c) + (d)": 2100.0,
                "Instrumentos de Dívida Elegíveis a Capital (h)": 40.0,
            }
        ]
    )

    result = build_critical_screens_dataframe(
        df_principal=principal,
        df_ativo=ativo,
        df_passivo=passivo,
        df_capital=pd.DataFrame(),
        df_dre=pd.DataFrame(),
        df_carteira_pf=pd.DataFrame(),
        df_carteira_pj=pd.DataFrame(),
        df_carteira_instrumentos=pd.DataFrame(),
        df_bloprudencial=pd.DataFrame(),
    )

    row = result[result["Período"] == "4/2025"].iloc[0]
    assert row["Instituição"] == "ITAU - PRUDENCIAL"
    assert row["Core Funding"] == 2140.0
    assert row["Core Funding*"] == 2140.0
    assert row["Trace::Core Funding::Captações (e)"] == 2100.0
    assert row["Trace::Core Funding::Instrumentos de Dívida Elegíveis a Capital (h)"] == 40.0
    assert round(row["Crédito / Captações"], 6) == round(1900.0 / 2140.0, 6)


class _FakeBlopCache:
    def __init__(self, exists: bool, stamp: str = "2026-04-05T12:00:00"):
        self._exists = exists
        self._stamp = stamp

    def existe(self):
        return self._exists

    def get_info(self):
        return {
            "timestamp_salvamento": self._stamp,
            "total_registros": 2,
            "total_periodos": 2,
            "fonte": "cache_local",
        }


class _FakeManager:
    def __init__(
        self,
        blop_df: pd.DataFrame | None = None,
        cache_stamp: str = "2026-04-05T12:00:00",
        blop_exists: bool | None = None,
        all_sources_exist: bool = False,
    ):
        self._blop_df = blop_df
        exists = blop_df is not None if blop_exists is None else blop_exists
        self._cache = _FakeBlopCache(exists, cache_stamp)
        self._all_sources_exist = all_sources_exist

    def carregar(self, cache_name: str):
        if cache_name == "bloprudencial" and self._blop_df is not None:
            return CacheResult(
                sucesso=True,
                mensagem="ok",
                dados=self._blop_df.copy(),
                fonte="cache_local",
            )
        return CacheResult(sucesso=False, mensagem="ausente", fonte="nenhum")

    def get_cache(self, cache_name: str):
        if cache_name == "bloprudencial":
            return self._cache
        if self._all_sources_exist:
            return _FakeBlopCache(True)
        return _FakeBlopCache(False)


def test_load_bloprud_sources_uses_persisted_cache_when_available(tmp_path: Path):
    blop_persistido = pd.DataFrame(
        [
            {"DATA_BASE": "202503", "DOCUMENTO": 4060, "NOME_CONGL": "ITAU - PRUDENCIAL", "CONTA": "3312000001", "SALDO": 10.0},
            {"DATA_BASE": "202506", "DOCUMENTO": 4060, "NOME_CONGL": "ITAU - PRUDENCIAL", "CONTA": "3313000000", "SALDO": 20.0},
        ]
    )
    manager = _FakeManager(blop_df=blop_persistido)

    result = _load_bloprud_sources(
        manager=manager,
        base_dir=tmp_path,
        periodos_display=["1/2025", "2/2025"],
    )

    assert sorted(result["Período"].unique().tolist()) == ["1/2025", "2/2025"]
    assert len(result) == 2


def test_critical_screens_needs_refresh_detects_source_fingerprint_change(tmp_path: Path):
    cache = CriticalScreensCache(tmp_path)
    fingerprint_base = {
        "timestamp_salvamento": "2026-04-05T12:00:00",
        "total_registros": 2,
        "total_periodos": 2,
        "fonte": "cache_local",
    }
    dados = pd.DataFrame(
        [
            {
                "Instituição": "ITAU - PRUDENCIAL",
                "Período": "1/2025",
                "InstituiçãoKey": "ITAU PRUDENCIAL",
            }
        ]
    )
    cache.salvar_local(
        dados,
        fonte="materialized",
        info_extra={
            "schema_version": CRITICAL_SCREENS_SCHEMA_VERSION,
            "source_fingerprints": {
                "principal": fingerprint_base,
                "capital": fingerprint_base,
                "ativo": fingerprint_base,
                "passivo": fingerprint_base,
                "dre": fingerprint_base,
                "carteira_pf": fingerprint_base,
                "carteira_pj": fingerprint_base,
                "carteira_instrumentos": fingerprint_base,
                "bloprudencial": fingerprint_base,
                "_bloprud_local_periods": [],
            }
        },
    )

    manager_igual = _FakeManager(
        blop_df=pd.DataFrame([{"DATA_BASE": "202503"}]),
        cache_stamp="2026-04-05T12:00:00",
        all_sources_exist=True,
    )
    manager_diferente = _FakeManager(
        blop_df=pd.DataFrame([{"DATA_BASE": "202503"}]),
        cache_stamp="2026-04-06T12:00:00",
        all_sources_exist=True,
    )

    assert not critical_screens_needs_refresh(base_dir=tmp_path, manager=manager_igual)
    assert critical_screens_needs_refresh(base_dir=tmp_path, manager=manager_diferente)


def test_critical_screens_needs_refresh_ignores_missing_local_sources(tmp_path: Path):
    cache = CriticalScreensCache(tmp_path)
    dados = pd.DataFrame(
        [
            {
                "Instituição": "ITAU - PRUDENCIAL",
                "Período": "1/2025",
                "InstituiçãoKey": "ITAU PRUDENCIAL",
            }
        ]
    )
    cache.salvar_local(
        dados,
        fonte="materialized",
        info_extra={
            "schema_version": CRITICAL_SCREENS_SCHEMA_VERSION,
            "source_fingerprints": {
                "principal": {
                    "timestamp_salvamento": "2026-04-05T10:00:00",
                    "total_registros": 10,
                    "total_periodos": 2,
                    "fonte": "github_releases",
                },
                "bloprudencial": {
                    "timestamp_salvamento": "2026-04-05T12:00:00",
                    "total_registros": 2,
                    "total_periodos": 2,
                    "fonte": "cache_local",
                },
                "_bloprud_local_periods": ["202503", "202506"],
            }
        },
    )

    manager_sem_fontes = _FakeManager(blop_df=None, blop_exists=False)
    assert not critical_screens_needs_refresh(base_dir=tmp_path, manager=manager_sem_fontes)


def test_critical_screens_can_bootstrap_from_bundle(tmp_path: Path):
    cache = CriticalScreensCache(tmp_path)
    dados = pd.DataFrame(
        [
            {
                "Instituição": "ITAU - PRUDENCIAL",
                "Período": "1/2025",
                "InstituiçãoKey": "ITAU PRUDENCIAL",
            }
        ]
    )
    save_result = cache.salvar_local(
        dados,
        fonte="materialized",
        info_extra={"schema_version": CRITICAL_SCREENS_SCHEMA_VERSION},
    )
    assert save_result.sucesso

    bundle_result = cache.sync_bundle_from_local()
    assert bundle_result.sucesso

    cache.limpar_local()
    assert not cache.existe()

    bootstrap_result = cache.bootstrap_local_from_bundle()
    assert bootstrap_result.sucesso
    assert cache.existe()
    assert bootstrap_result.dados is not None
    assert bootstrap_result.dados.iloc[0]["Instituição"] == "ITAU - PRUDENCIAL"


def test_runtime_status_prefers_bundle_without_forcing_refresh(tmp_path: Path):
    cache = CriticalScreensCache(tmp_path)
    dados = pd.DataFrame(
        [
            {
                "Instituição": "ITAU - PRUDENCIAL",
                "Período": "1/2025",
                "InstituiçãoKey": "ITAU PRUDENCIAL",
            }
        ]
    )
    save_result = cache.salvar_local(
        dados,
        fonte="materialized",
        info_extra={
            "schema_version": CRITICAL_SCREENS_SCHEMA_VERSION,
            "source_fingerprints": {
                "principal": {
                    "timestamp_salvamento": "2026-04-05T10:00:00",
                    "total_registros": 10,
                    "total_periodos": 2,
                    "fonte": "github_releases",
                },
                "_bloprud_local_periods": ["202503", "202506"],
            },
        },
    )
    assert save_result.sucesso
    assert cache.sync_bundle_from_local().sucesso
    cache.limpar_local()

    status = get_critical_screens_runtime_status(base_dir=tmp_path, manager=_FakeManager(blop_df=None, blop_exists=False))
    assert status["bundle_ready"]
    assert not status["local_ready"]
    assert not status["can_materialize_from_local_sources"]
    assert status["mode"] == "bootstrap_bundle"


def test_runtime_status_prefers_newer_bundle_over_stale_local(tmp_path: Path):
    cache = CriticalScreensCache(tmp_path)
    stale_df = pd.DataFrame(
        [
            {
                "Instituição": "ITAU - PRUDENCIAL",
                "Período": "3/2025",
                "InstituiçãoKey": "ITAU PRUDENCIAL",
            }
        ]
    )
    fresh_df = pd.DataFrame(
        [
            {
                "Instituição": "ITAU - PRUDENCIAL",
                "Período": "4/2025",
                "InstituiçãoKey": "ITAU PRUDENCIAL",
            }
        ]
    )

    save_result = cache.salvar_local(
        stale_df,
        fonte="materialized",
        info_extra={"schema_version": CRITICAL_SCREENS_SCHEMA_VERSION},
    )
    assert save_result.sucesso

    stale_metadata = json.loads(cache.arquivo_metadata.read_text(encoding="utf-8"))
    stale_metadata["timestamp_salvamento"] = "2026-04-11T10:00:00"
    cache.arquivo_metadata.write_text(json.dumps(stale_metadata, ensure_ascii=False), encoding="utf-8")

    cache.bundled_dir.mkdir(parents=True, exist_ok=True)
    fresh_df.to_parquet(cache.bundled_data_file, index=False)
    bundled_metadata = {
        "timestamp_salvamento": "2026-04-11T11:00:00",
        "fonte": "materialized",
        "total_registros": len(fresh_df),
        "colunas": list(fresh_df.columns),
        "formato": "parquet",
        "periodos": ["4/2025"],
        "total_periodos": 1,
        "extra": {"schema_version": CRITICAL_SCREENS_SCHEMA_VERSION},
    }
    cache.bundled_metadata_file.write_text(json.dumps(bundled_metadata, ensure_ascii=False), encoding="utf-8")

    status = get_critical_screens_runtime_status(base_dir=tmp_path, manager=_FakeManager(blop_df=None, blop_exists=False))
    assert status["local_ready"]
    assert status["bundle_ready"]
    assert status["bundle_newer_than_local"]
    assert status["mode"] == "bootstrap_bundle"


def test_load_critical_screens_slice_replaces_stale_local_with_newer_bundle(tmp_path: Path):
    cache = CriticalScreensCache(tmp_path)
    stale_df = pd.DataFrame(
        [
            {
                "Instituição": "ITAU - PRUDENCIAL",
                "Período": "3/2025",
                "InstituiçãoKey": "ITAU PRUDENCIAL",
            }
        ]
    )
    fresh_df = pd.DataFrame(
        [
            {
                "Instituição": "ITAU - PRUDENCIAL",
                "Período": "4/2025",
                "InstituiçãoKey": "ITAU PRUDENCIAL",
            }
        ]
    )

    save_result = cache.salvar_local(
        stale_df,
        fonte="materialized",
        info_extra={"schema_version": CRITICAL_SCREENS_SCHEMA_VERSION},
    )
    assert save_result.sucesso

    stale_metadata = json.loads(cache.arquivo_metadata.read_text(encoding="utf-8"))
    stale_metadata["timestamp_salvamento"] = "2026-04-11T10:00:00"
    cache.arquivo_metadata.write_text(json.dumps(stale_metadata, ensure_ascii=False), encoding="utf-8")

    cache.bundled_dir.mkdir(parents=True, exist_ok=True)
    fresh_df.to_parquet(cache.bundled_data_file, index=False)
    bundled_metadata = {
        "timestamp_salvamento": "2026-04-11T11:00:00",
        "fonte": "materialized",
        "total_registros": len(fresh_df),
        "colunas": list(fresh_df.columns),
        "formato": "parquet",
        "periodos": ["4/2025"],
        "total_periodos": 1,
        "extra": {"schema_version": CRITICAL_SCREENS_SCHEMA_VERSION},
    }
    cache.bundled_metadata_file.write_text(json.dumps(bundled_metadata, ensure_ascii=False), encoding="utf-8")

    slice_df = load_critical_screens_slice(base_dir=tmp_path, periodos=["4/2025"])
    assert not slice_df.empty
    assert slice_df["Período"].tolist() == ["4/2025"]

    local_result = cache.carregar_local()
    assert local_result.sucesso
    assert local_result.dados is not None
    assert local_result.dados["Período"].tolist() == ["4/2025"]


def test_materialize_critical_screens_fails_fast_without_local_sources(tmp_path: Path):
    manager = CacheManager(base_dir=tmp_path)
    result = materialize_critical_screens_cache(
        base_dir=tmp_path,
        manager=manager,
        force=True,
        allow_remote_source_download=False,
    )
    assert not result.sucesso
    assert "fontes de critical_screens" in result.mensagem


def test_load_critical_screens_slice_supplements_missing_funding_from_passivo(tmp_path: Path):
    (tmp_path / "conglomerados.csv").write_text(
        "Conglomerado CDIGO 80099 NOME ITAU - PRUDENCIAL TIPO TESTE "
        "CNPJ 12345678000100 Itau Unibanco LIDER",
        encoding="utf-8",
    )

    manager = CacheManager(base_dir=tmp_path)
    principal_cache = manager.get_cache("principal")
    passivo_cache = manager.get_cache("passivo")
    critical_cache = CriticalScreensCache(tmp_path)

    principal_df = pd.DataFrame(
        [
            {"Instituição": "ITAU - PRUDENCIAL", "Período": "4/2025", "CodInst": "C0080099"},
            {"Instituição": "ITAU - PRUDENCIAL", "Período": "4/2024", "CodInst": "C0080099"},
        ]
    )
    passivo_df = pd.DataFrame(
        [
            {
                "Instituição": "[IF C0080099]",
                "Período": "4/2025",
                "CodInst": "C0080099",
                "Captações (e) = (a) + (b) + (c) + (d)": 120.0,
                "Instrumentos de Dívida Elegíveis a Capital (h)": 30.0,
            },
            {
                "Instituição": "[IF C0080099]",
                "Período": "4/2024",
                "CodInst": "C0080099",
                "Captações (e) = (a) + (b) + (c) + (d)": 100.0,
                "Instrumentos de Dívida Elegíveis a Capital (h)": None,
            },
        ]
    )
    stale_critical_df = pd.DataFrame(
        [
            {
                "Instituição": "ITAU - PRUDENCIAL",
                "InstituiçãoKey": "ITAU PRUDENCIAL",
                "Período": "4/2025",
                "Carteira de Crédito Bruta": 75.0,
                "Core Funding": None,
                "Core Funding*": None,
                "Crédito / Captações": None,
                "Trace::Core Funding::Captações (e)": None,
                "Trace::Core Funding::Instrumentos de Dívida Elegíveis a Capital (h)": None,
                "Trace::Core Funding::Status": "",
                "Trace::Core Funding::Campo Selecionado": "",
            }
        ]
    )

    assert principal_cache is not None
    assert passivo_cache is not None
    assert principal_cache.salvar_local(principal_df, fonte="test").sucesso
    assert passivo_cache.salvar_local(passivo_df, fonte="test").sucesso
    assert critical_cache.salvar_local(
        stale_critical_df,
        fonte="materialized",
        info_extra={"schema_version": CRITICAL_SCREENS_SCHEMA_VERSION},
    ).sucesso

    slice_df = load_critical_screens_slice(base_dir=tmp_path, periodos=["4/2025"], instituicoes=["ITAU - PRUDENCIAL"])

    assert len(slice_df) == 1
    row = slice_df.iloc[0]
    assert row["Instituição"] == "ITAU - PRUDENCIAL"
    assert row["Core Funding"] == 150.0
    assert row["Core Funding*"] == 150.0
    assert row["Crédito / Captações"] == 0.5
    assert row["Trace::Core Funding::Captações (e)"] == 120.0
    assert row["Trace::Core Funding::Instrumentos de Dívida Elegíveis a Capital (h)"] == 30.0
    assert row["Trace::Core Funding::Status"] == "official_components"


def test_build_selected_institution_code_map_prefers_direct_principal_names():
    principal = pd.DataFrame(
        [
            {"Instituição": "ITAU - PRUDENCIAL", "Período": "4/2025", "CodInst": "C0080099"},
            {"Instituição": "BB - PRUDENCIAL", "Período": "4/2025", "CodInst": "C0080100"},
        ]
    )

    canonicas, code_map = _build_selected_institution_code_map(
        principal,
        catalog_map={
            "ITAU PRUDENCIAL": "ITAU - PRUDENCIAL",
            "BB PRUDENCIAL": "BB - PRUDENCIAL",
        },
        instituicoes=["ITAU - PRUDENCIAL"],
    )

    assert canonicas == {"ITAU - PRUDENCIAL"}
    assert code_map == {"80099": "ITAU - PRUDENCIAL"}


def test_load_runtime_passivo_support_prefilters_selected_institutions_before_canonicalization(
    tmp_path: Path,
    monkeypatch,
):
    (tmp_path / "conglomerados.csv").write_text(
        "Conglomerado CDIGO 80099 NOME ITAU - PRUDENCIAL TIPO TESTE "
        "CNPJ 12345678000100 Itau Unibanco LIDER "
        "Conglomerado CDIGO 80100 NOME BB - PRUDENCIAL TIPO TESTE "
        "CNPJ 22345678000100 Banco do Brasil LIDER",
        encoding="utf-8",
    )

    manager = CacheManager(base_dir=tmp_path)
    principal_cache = manager.get_cache("principal")
    passivo_cache = manager.get_cache("passivo")

    principal_df = pd.DataFrame(
        [
            {"Instituição": "ITAU - PRUDENCIAL", "Período": "4/2025", "CodInst": "C0080099"},
            {"Instituição": "BB - PRUDENCIAL", "Período": "4/2025", "CodInst": "C0080100"},
        ]
    )
    passivo_df = pd.DataFrame(
        [
            {
                "Instituição": "[IF C0080099]",
                "Período": "4/2025",
                "CodInst": "C0080099",
                "Captações (e) = (a) + (b) + (c) + (d)": 120.0,
                "Instrumentos de Dívida Elegíveis a Capital (h)": 30.0,
            },
            {
                "Instituição": "[IF C0080100]",
                "Período": "4/2025",
                "CodInst": "C0080100",
                "Captações (e) = (a) + (b) + (c) + (d)": 200.0,
                "Instrumentos de Dívida Elegíveis a Capital (h)": 40.0,
            },
        ]
    )

    assert principal_cache is not None
    assert passivo_cache is not None
    assert principal_cache.salvar_local(principal_df, fonte="test").sucesso
    assert passivo_cache.salvar_local(passivo_df, fonte="test").sucesso

    import utils.ifdata_cache.critical_screens as critical_screens_module

    original = critical_screens_module.canonicalize_institution_dataframe
    seen = {"calls": 0}

    def wrapped(df, **kwargs):
        seen["calls"] += 1
        seen["rows_before_canonicalize"] = len(df)
        return original(df, **kwargs)

    monkeypatch.setattr(critical_screens_module, "canonicalize_institution_dataframe", wrapped)

    support = _load_runtime_passivo_support(
        base_dir=tmp_path,
        periodos=["4/2025"],
        instituicoes=["ITAU - PRUDENCIAL"],
    )

    assert seen["calls"] == 0
    assert len(support) == 1
    row = support.iloc[0]
    assert row["Instituição"] == "ITAU - PRUDENCIAL"
    assert row["Core Funding"] == 150.0
