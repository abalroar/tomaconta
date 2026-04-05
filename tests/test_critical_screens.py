from pathlib import Path

import pandas as pd

from utils.ifdata_cache.base import CacheResult
from utils.ifdata_cache.critical_screens import (
    CriticalScreensCache,
    CRITICAL_SCREENS_SCHEMA_VERSION,
    _load_bloprud_sources,
    build_critical_screens_dataframe,
    critical_screens_needs_refresh,
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
            },
            {
                "Instituição": "ITAU - PRUDENCIAL",
                "Período": "1/2025",
                "Ativo Total": 1900.0,
                "Patrimônio Líquido": 220.0,
                "Lucro Líquido Acumulado YTD": 10.0,
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

    row = result[result["Período"] == "1/2025"].iloc[0]
    assert row["Instituição"] == "ITAU - PRUDENCIAL"
    assert row["Ativo Total"] == 1900.0
    assert row["Patrimônio Líquido"] == 220.0
    assert row["Lucro Líquido Acumulado YTD"] == 10.0
    assert round(row["ROE Ac. Anualizado (%)"], 6) == round((10.0 * 4.0) / ((220.0 + 200.0) / 2.0), 6)
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
    def __init__(self, blop_df: pd.DataFrame | None = None, cache_stamp: str = "2026-04-05T12:00:00"):
        self._blop_df = blop_df
        self._cache = _FakeBlopCache(blop_df is not None, cache_stamp)

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
                "principal": None,
                "capital": None,
                "ativo": None,
                "passivo": None,
                "dre": None,
                "carteira_pf": None,
                "carteira_pj": None,
                "carteira_instrumentos": None,
                "bloprudencial": {
                    "timestamp_salvamento": "2026-04-05T12:00:00",
                    "total_registros": 2,
                    "total_periodos": 2,
                    "fonte": "cache_local",
                },
                "_bloprud_local_periods": [],
            }
        },
    )

    manager_igual = _FakeManager(blop_df=pd.DataFrame([{"DATA_BASE": "202503"}]), cache_stamp="2026-04-05T12:00:00")
    manager_diferente = _FakeManager(blop_df=pd.DataFrame([{"DATA_BASE": "202503"}]), cache_stamp="2026-04-06T12:00:00")

    assert not critical_screens_needs_refresh(base_dir=tmp_path, manager=manager_igual)
    assert critical_screens_needs_refresh(base_dir=tmp_path, manager=manager_diferente)
