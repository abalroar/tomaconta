from utils.institution_search import search_institutions


OPTIONS = [
    "COOPERATIVA DE CRÉDITO DE LIVRE ADMISSÃO DA REGIÃO DE ITAÚNA LTDA. - SICOOB CREDIUNA",
    "COOPERATIVA DE ECONOMIA E CRÉDITO MÚTUO DOS FUNCIONÁRIOS DAS EMPRESAS ITAÚ",
    "ITAU - PRUDENCIAL",
    "VOLVO - PRUDENCIAL",
    "BANCO VOLKSWAGEN - PRUDENCIAL",
    "COOPERATIVA CENTRAL DE CRÉDITO - AILOS",
    "CRESOL CONFEDERAÇÃO - PRUDENCIAL",
    "COOPERATIVA DE CRÉDITO CRESOL NORTE PARANAENSE",
    "BANCO C6 - PRUDENCIAL",
]


def test_volvo_prioritizes_direct_match():
    assert search_institutions(OPTIONS, "Volvo", limit=3)[0] == "VOLVO - PRUDENCIAL"


def test_cressol_tolerates_spelling_and_avoids_generic_credit_noise():
    results = search_institutions(OPTIONS, "Cressol", limit=3)

    assert results
    assert all("CRESOL" in item for item in results)
    assert "COOPERATIVA CENTRAL DE CRÉDITO - AILOS" not in results


def test_itau_does_not_promote_itauna_noise():
    results = search_institutions(OPTIONS, "itaú", limit=3)

    assert results[0] == "ITAU - PRUDENCIAL"
    assert "ITAÚNA" not in " ".join(results)
    assert not any(item.startswith("COOPERATIVA") for item in results)
