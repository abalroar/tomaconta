from rating.data_mapping import map_rating_inputs
from rating.engine import calculate_rating, get_starting_score


def test_get_starting_score_uses_size_buckets():
    assert get_starting_score(250_000_000_000.0) == ("above_200bn", 22)
    assert get_starting_score(50_000_000_000.0) == ("between_20bn_200bn", 19)
    assert get_starting_score(5_000_000_000.0) == ("below_20bn", 16)


def test_calculate_rating_uses_visible_weights_and_caps_at_25():
    mapped = {
        "institution_id": "80099",
        "institution_name": "TEST BANK - PRUDENCIAL",
        "period": "4/2025",
        "previous_period": "4/2024",
        "raw_inputs": {},
        "mapped_inputs": {
            "total_assets": {"value": 250_000_000_000.0},
            "cet1": {"value": 0.17},
            "roe": {"value": 0.19},
            "npl_creation": {"value": 0.01},
            "funding_delta": {"value": 1.0},
            "funding_structural_ratio": {"value": 1.10},
        },
        "replacements": [],
    }
    answers = {"q1": "A", "q2": "A", "q3": "A", "q4": "A", "q5": "A", "q6": "A"}
    result = calculate_rating(mapped, answers)

    assert result["status"] == "ok"
    assert round(result["raw_final_score"], 2) == 25.39
    assert result["final_numeric_rating"] == 25


def test_calculate_rating_marks_incomplete_when_inputs_are_missing():
    mapped = {
        "institution_id": "123",
        "institution_name": "MISSING BANK - PRUDENCIAL",
        "period": "4/2025",
        "raw_inputs": {},
        "mapped_inputs": {
            "total_assets": {"value": 25_000_000_000.0},
            "cet1": {"value": None},
            "roe": {"value": 0.12},
            "npl_creation": {"value": 0.01},
            "funding_delta": {"value": 1.0},
            "funding_structural_ratio": {"value": 0.90},
        },
        "replacements": [],
    }
    answers = {"q1": "A", "q2": "A", "q3": "A", "q4": "A", "q5": "A", "q6": "A"}
    result = calculate_rating(mapped, answers)

    assert result["status"] == "incomplete"
    assert result["final_numeric_rating"] is None
    assert result["missing_quantitative_inputs"] == ["cet1"]


def test_map_rating_inputs_uses_documented_fallbacks():
    record = {
        "Instituição": "ABC-BRASIL - PRUDENCIAL",
        "ConglomeradoId": "80312",
        "Período": "4/2025",
        "Período Anterior": "4/2024",
        "Ativo Total": 66_000_000_000.0,
        "Índice de Capital Principal (CET1)": None,
        "Índice de Basileia Total (%)": 0.16,
        "ROE Ac. Anualizado (%)": 0.15,
        "Core Funding": 100.0,
        "Core Funding (prev)": 90.0,
        "Crédito / Captações": 0.80,
        "Perda Esperada / Carteira de Crédito Bruta": 0.025,
        "Perda Esperada / Carteira de Crédito Bruta (prev)": 0.010,
        "Ativos Estágio 3": None,
        "Ativos Estágio 3 (prev)": None,
        "Carteira de Crédito Bruta": 50.0,
        "Carteira de Crédito Bruta (prev)": 45.0,
        "Perda Esperada": 1.0,
        "Perda Esperada (prev)": 0.5,
    }

    mapped = map_rating_inputs(record)

    assert mapped["mapped_inputs"]["cet1"]["source_kind"] == "fallback"
    assert mapped["mapped_inputs"]["cet1"]["value"] == 0.16
    assert mapped["mapped_inputs"]["npl_creation"]["source_kind"] == "current_level"
    assert round(mapped["mapped_inputs"]["npl_creation"]["value"], 6) == 0.025
