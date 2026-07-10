import pandas as pd

from utils.ifdata_extractor import parece_codigo_instituicao
from utils.ifdata_cache.institutions import (
    canonicalize_institution_dataframe,
    stabilize_institution_names_by_code,
)


def test_official_institution_name_may_start_with_digits():
    assert parece_codigo_instituicao("321 SOCIEDADE DE CRÉDITO DIRETO S.A.") is False
    assert parece_codigo_instituicao("321_0001") is True


def test_canonicalize_institution_dataframe_uses_same_dataframe_code_map():
    df = pd.DataFrame(
        {
            "CodInst": [123, 123, 456],
            "Instituição": ["Banco Exemplo", "[IF 123]", "[IF 456]"],
        }
    )

    out = canonicalize_institution_dataframe(
        df,
        catalog_map={"BANCO EXEMPLO": "Banco Exemplo"},
    )

    assert out["Instituição"].tolist()[:2] == ["Banco Exemplo", "Banco Exemplo"]


def test_canonicalize_institution_dataframe_falls_back_to_resolver(monkeypatch):
    monkeypatch.setattr(
        "utils.ifdata_cache.institutions.resolver_nome_instituicao",
        lambda codinst, nome_atual=None: "Banco Fallback" if str(codinst) == "789" else str(nome_atual),
    )

    df = pd.DataFrame(
        {
            "CodInst": [789],
            "Instituição": ["[IF 789]"],
        }
    )

    out = canonicalize_institution_dataframe(
        df,
        catalog_map={"BANCO FALLBACK": "Banco Fallback"},
    )

    assert out["Instituição"].tolist() == ["Banco Fallback"]


def test_stabilize_institution_names_uses_latest_official_name_by_codinst():
    df = pd.DataFrame(
        {
            "CodInst": ["C001", "C001", "C001", "00042"],
            "Instituição": ["Banco Antigo", "[IF C001]", "Banco Atual", "Banco 42"],
            "Período": ["1/2024", "1/2025", "1/2026", "1/2026"],
        }
    )

    out = stabilize_institution_names_by_code(df)

    assert out.loc[out["CodInst"].eq("C001"), "Instituição"].tolist() == [
        "Banco Atual",
        "Banco Atual",
        "Banco Atual",
    ]
    assert out.loc[out["CodInst"].eq("00042"), "Instituição"].tolist() == ["Banco 42"]
