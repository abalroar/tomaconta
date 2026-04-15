from rating.audit import build_audit_trail_markdown
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
            "asset_quality": {"value": 0.01, "rule_set": "inad_ratio_exact"},
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
            "asset_quality": {"value": 0.01, "rule_set": "inad_ratio_exact"},
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


def test_map_rating_inputs_uses_exact_rel16_inad_ratio_when_available():
    record = {
        "Instituição": "ABC-BRASIL - PRUDENCIAL",
        "ConglomeradoId": "80312",
        "Período": "4/2025",
        "Período Anterior": "4/2024",
        "Ativo Total": 66_000_000_000.0,
        "Índice de Capital Principal (CET1)": None,
        "Índice de Basileia Total (%)": 0.16,
        "ROE Ac. Anualizado (%)": 0.15,
        "ROE Ac. Anualizado (%) (prev)": 0.12,
        "Core Funding": 100.0,
        "Core Funding (prev)": 90.0,
        "Crédito / Captações": 0.80,
        "Perda Esperada / Carteira de Crédito Bruta": 0.025,
        "Perda Esperada / Carteira de Crédito Bruta (prev)": 0.010,
        "Inadimplência / Carteira Total": 0.031,
        "Ativos Problemáticos / Carteira Total": 0.061,
        "Carteira de Crédito Bruta": 50.0,
    }

    mapped = map_rating_inputs(record)

    assert mapped["mapped_inputs"]["cet1"]["source_kind"] == "fallback"
    assert mapped["mapped_inputs"]["cet1"]["value"] == 0.16
    assert round(mapped["mapped_inputs"]["funding_delta"]["value"], 6) == round((100.0 / 90.0) - 1.0, 6)
    assert mapped["mapped_inputs"]["asset_quality"]["source_kind"] == "exact"
    assert mapped["mapped_inputs"]["asset_quality"]["rule_set"] == "inad_ratio_exact"
    assert mapped["mapped_inputs"]["asset_quality"]["value"] == 0.031
    assert "Carteira 4.966" in mapped["mapped_inputs"]["asset_quality"]["note"]


def test_map_rating_inputs_uses_proxy_for_transition_periods():
    record = {
        "Instituição": "ABC-BRASIL - PRUDENCIAL",
        "ConglomeradoId": "80312",
        "Período": "3/2025",
        "Período Anterior": "3/2024",
        "Ativo Total": 66_000_000_000.0,
        "Índice de Capital Principal (CET1)": 0.16,
        "Índice de Basileia Total (%)": 0.18,
        "ROE Ac. Anualizado (%)": 0.15,
        "ROE Ac. Anualizado (%) (prev)": 0.12,
        "Core Funding": 100.0,
        "Core Funding (prev)": 90.0,
        "Crédito / Captações": 0.80,
        "Perda Esperada / Carteira de Crédito Bruta": -0.061,
        "Carteira de Crédito Bruta": 50.0,
    }

    mapped = map_rating_inputs(record)

    assert mapped["mapped_inputs"]["asset_quality"]["source_kind"] == "proxy"
    assert mapped["mapped_inputs"]["asset_quality"]["rule_set"] == "proxy_loss_ratio"
    assert mapped["mapped_inputs"]["asset_quality"]["value"] == 0.061
    assert "mar/25, jun/25 e set/25" in mapped["mapped_inputs"]["asset_quality"]["note"]


def test_map_rating_inputs_marks_up_to_2024_as_missing_when_exact_legacy_is_absent():
    record = {
        "Instituição": "ABC-BRASIL - PRUDENCIAL",
        "ConglomeradoId": "80312",
        "Período": "4/2024",
        "Período Anterior": "4/2023",
        "Ativo Total": 66_000_000_000.0,
        "Índice de Capital Principal (CET1)": 0.16,
        "ROE Ac. Anualizado (%)": 0.15,
        "ROE Ac. Anualizado (%) (prev)": 0.12,
        "Core Funding": 100.0,
        "Core Funding (prev)": 90.0,
        "Crédito / Captações": 0.80,
        "Perda Esperada / Carteira de Crédito Bruta": -0.042,
        "Carteira de Crédito Bruta": 50.0,
    }

    mapped = map_rating_inputs(record)

    assert mapped["mapped_inputs"]["asset_quality"]["source_kind"] == "missing"
    assert mapped["mapped_inputs"]["asset_quality"]["value"] is None
    assert "D-H / Carteira" in mapped["mapped_inputs"]["asset_quality"]["note"]


def test_map_rating_inputs_prefers_exact_legacy_dh_when_available():
    record = {
        "Instituição": "ABC-BRASIL - PRUDENCIAL",
        "ConglomeradoId": "80312",
        "Período": "4/2024",
        "Período Anterior": "4/2023",
        "Ativo Total": 66_000_000_000.0,
        "Índice de Capital Principal (CET1)": 0.16,
        "ROE Ac. Anualizado (%)": 0.15,
        "ROE Ac. Anualizado (%) (prev)": 0.12,
        "Core Funding": 100.0,
        "Core Funding (prev)": 90.0,
        "Crédito / Captações": 0.80,
        "Perda Esperada / Carteira de Crédito Bruta": -0.042,
        "D-H / Carteira": 0.033,
        "Carteira de Crédito Bruta": 50.0,
    }

    mapped = map_rating_inputs(record)

    assert mapped["mapped_inputs"]["asset_quality"]["source_kind"] == "exact_legacy"
    assert mapped["mapped_inputs"]["asset_quality"]["rule_set"] == "legacy_dh_ratio"
    assert mapped["mapped_inputs"]["asset_quality"]["value"] == 0.033


def test_calculate_rating_marks_incomplete_when_asset_quality_is_unavailable():
    record = {
        "Instituição": "ABC-BRASIL - PRUDENCIAL",
        "ConglomeradoId": "80312",
        "Período": "4/2025",
        "Período Anterior": "4/2024",
        "Ativo Total": 66_000_000_000.0,
        "Índice de Capital Principal (CET1)": 0.16,
        "Índice de Basileia Total (%)": 0.18,
        "ROE Ac. Anualizado (%)": 0.15,
        "ROE Ac. Anualizado (%) (prev)": 0.12,
        "Core Funding": 100.0,
        "Core Funding (prev)": 90.0,
        "Crédito / Captações": 0.80,
        "Perda Esperada / Carteira de Crédito Bruta": 0.025,
        "Carteira de Crédito Bruta": 50.0,
    }
    answers = {"q1": "A", "q2": "A", "q3": "A", "q4": "A", "q5": "A", "q6": "A"}

    result = calculate_rating(map_rating_inputs(record), answers)

    assert result["status"] == "incomplete"
    assert result["final_numeric_rating"] is None
    assert result["missing_quantitative_inputs"] == ["asset_quality"]


def test_build_audit_trail_markdown_explains_missing_asset_quality():
    record = {
        "Instituição": "ABC-BRASIL - PRUDENCIAL",
        "ConglomeradoId": "80312",
        "Período": "4/2025",
        "Período Anterior": "4/2024",
        "Ativo Total": 66_000_000_000.0,
        "Índice de Capital Principal (CET1)": 0.16,
        "ROE Ac. Anualizado (%)": 0.15,
        "ROE Ac. Anualizado (%) (prev)": 0.12,
        "Core Funding": 100.0,
        "Core Funding (prev)": 90.0,
        "Crédito / Captações": 0.80,
        "Perda Esperada / Carteira de Crédito Bruta": 0.025,
        "Carteira de Crédito Bruta": 50.0,
    }
    answers = {"q1": "A", "q2": "A", "q3": "A", "q4": "A", "q5": "A", "q6": "A"}

    result = calculate_rating(map_rating_inputs(record), answers)
    markdown = build_audit_trail_markdown(result)

    assert "Inputs quantitativos faltantes: Qualidade da Carteira" in markdown
    assert "[missing]" in markdown
    assert "Inadimplência / Carteira Total" in markdown


def test_calculate_rating_uses_proxy_ruleset_when_asset_quality_is_proxy():
    record = {
        "Instituição": "TESTE - PRUDENCIAL",
        "ConglomeradoId": "99999",
        "Período": "3/2025",
        "Período Anterior": "4/2024",
        "Ativo Total": 10_000_000_000.0,
        "Índice de Capital Principal (CET1)": 0.14,
        "Índice de Basileia Total (%)": 0.16,
        "ROE Ac. Anualizado (%)": 0.11,
        "ROE Ac. Anualizado (%) (prev)": 0.09,
        "Core Funding": 100.0,
        "Core Funding (prev)": 100.0,
        "Crédito / Captações": 0.80,
        "Perda Esperada / Carteira de Crédito Bruta": -0.10,
        "Carteira de Crédito Bruta": 100.0,
    }

    answers = {"q1": "A", "q2": "A", "q3": "A", "q4": "A", "q5": "A", "q6": "A"}
    result = calculate_rating(map_rating_inputs(record), answers)

    assert result["status"] == "ok"
    assert result["quantitative_scores"]["asset_quality"]["bucket"] == "> 8,0%"
    assert result["quantitative_scores"]["asset_quality"]["score"] == -0.43
