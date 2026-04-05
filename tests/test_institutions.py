from utils.ifdata_cache.institutions import canonicalize_institution_name


def test_canonicalize_institution_name_accepts_unique_official_variants():
    catalog_map = {
        "ITAU PRUDENCIAL": "ITAU - PRUDENCIAL",
        "ITAU UNIBANCO HOLDING S A": "ITAU - PRUDENCIAL",
        "BANCO AFINZ BM PRUDENCIAL": "BANCO AFINZ BM - PRUDENCIAL",
        "BCO AFINZ SA BM": "BANCO AFINZ BM - PRUDENCIAL",
        "BANK OF CHINA BRASIL PRUDENCIAL": "BANK OF CHINA (BRASIL) - PRUDENCIAL",
        "BOC BRASIL": "BANK OF CHINA (BRASIL) - PRUDENCIAL",
    }

    assert canonicalize_institution_name("Itau Unibanco", catalog_map=catalog_map) == "ITAU - PRUDENCIAL"
    assert canonicalize_institution_name("ITAU UNIBANCO HOLDING S.A.", catalog_map=catalog_map) == "ITAU - PRUDENCIAL"
    assert canonicalize_institution_name("BANCO AFINZ S.A. - BANCO MÚLTIPLO", catalog_map=catalog_map) == "BANCO AFINZ BM - PRUDENCIAL"
    assert canonicalize_institution_name("BCO DA CHINA BRASIL S.A. - PRUDENCIAL", catalog_map=catalog_map) == "BANK OF CHINA (BRASIL) - PRUDENCIAL"


def test_canonicalize_institution_name_keeps_raw_name_when_match_is_ambiguous():
    catalog_map = {
        "BANCO XP HOLDING": "XP - PRUDENCIAL",
        "BANCO XP INVESTIMENTOS": "XP INVESTIMENTOS - PRUDENCIAL",
    }

    assert canonicalize_institution_name("BANCO XP", catalog_map=catalog_map) == "BANCO XP"
