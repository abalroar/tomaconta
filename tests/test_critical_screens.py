from pathlib import Path

import pandas as pd

from utils.ifdata_cache.critical_screens import build_critical_screens_dataframe


def test_build_critical_screens_dataframe_materializes_expected_metrics(tmp_path: Path):
    (tmp_path / "conglomerados.csv").write_text(
        "Conglomerado CDIGO 80099 NOME ITAU - PRUDENCIAL TIPO TESTE "
        "CNPJ 12345678000100 Itau Unibanco LIDER",
        encoding="utf-8",
    )

    principal = pd.DataFrame(
        [
            {"Instituição": "ITAU - PRUDENCIAL", "Período": "1/2025"},
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
            {"Instituição": "Itau Unibanco", "Período": "1/2025", "C4": 10.0, "C5": 5.0},
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
        df_carteira_pf=carteira_pf,
        df_carteira_pj=carteira_pj,
        df_carteira_instrumentos=carteira_instr,
        df_bloprudencial=bloprud,
        base_dir=tmp_path,
    )

    assert len(result) == 1
    row = result.iloc[0]
    assert row["Instituição"] == "ITAU - PRUDENCIAL"
    assert row["Ativos Líquidos"] == 600.0
    assert row["Depósitos Totais"] == 106.0
    assert row["Core Funding*"] == 550.0
    assert row["Carteira de Crédito Bruta"] == 1900.0
    assert row["Perda Esperada"] == 100.0
    assert round(row["Perda Esperada / Carteira de Crédito*"], 6) == round(100.0 / 1900.0, 6)
    assert row["Carteira de Crédito Classificada"] == 300.0
    assert row["Carteira de Créd. Class. C4+C5"] == 15.0
    assert round(row["Perda Esperada / Estágio 3"], 6) == 0.2
    assert round(row["Índice de Capital Principal (CET1)"], 6) == 0.12
    assert round(row["Índice de Basileia Total (%)"], 6) == 0.17
    assert bool(row["CapitalDisponivel"])
    assert bool(row["BloprudencialDisponivel"])
    assert bool(row["QualidadeCarteiraDisponivel"])
