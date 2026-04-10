import pandas as pd

from utils.ifdata_cache.institutions import canonicalize_institution_dataframe


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
