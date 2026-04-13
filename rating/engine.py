"""Pure scoring engine for the rating model."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping

from .config import CET1_RULES, FUNDING_RULES, NPL_CREATION_RULES, QUALITATIVE_QUESTIONS, ROE_RULES, STARTING_SCORE_RULES, WEIGHTS_DISCLOSURE, WEIGHTS_VERSION


def _match_rule(value: float, rules: list[dict[str, Any]]) -> dict[str, Any]:
    for rule in rules:
        min_value = rule.get("min")
        max_value = rule.get("max")
        min_inclusive = bool(rule.get("min_inclusive", True))
        max_inclusive = bool(rule.get("max_inclusive", True))

        if min_value is not None:
            if min_inclusive and value < float(min_value):
                continue
            if not min_inclusive and value <= float(min_value):
                continue
        if max_value is not None:
            if max_inclusive and value > float(max_value):
                continue
            if not max_inclusive and value >= float(max_value):
                continue
        return rule
    raise ValueError(f"no rule matched value={value}")


def _round_half_up(value: float) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _clamp(value: int, min_value: int = 1, max_value: int = 25) -> int:
    return max(min_value, min(max_value, value))


def get_size_bucket(total_assets: float) -> dict[str, Any]:
    for rule in STARTING_SCORE_RULES:
        min_assets = rule.get("min_assets")
        max_assets = rule.get("max_assets")
        if min_assets is not None and float(total_assets) < float(min_assets):
            continue
        if max_assets is not None and float(total_assets) >= float(max_assets) and rule["key"] != "above_200bn":
            continue
        return dict(rule)
    return dict(STARTING_SCORE_RULES[-1])


def get_starting_score(total_assets: float) -> tuple[str, int]:
    bucket = get_size_bucket(total_assets)
    return str(bucket["key"]), int(bucket["starting_score"])


def score_cet1(cet1: float, size_bucket: str) -> dict[str, Any]:
    rule = _match_rule(float(cet1), CET1_RULES[str(size_bucket)])
    return {
        "factor": "cet1",
        "value": float(cet1),
        "bucket": str(rule["bucket"]),
        "score": float(rule["score"]),
        "hard_floor_score": rule.get("hard_floor_score"),
        "note": str(rule.get("note") or ""),
        "provisional": bool(rule.get("provisional", False)),
    }


def score_roe(roe: float) -> dict[str, Any]:
    rule = _match_rule(float(roe), ROE_RULES)
    return {
        "factor": "roe",
        "value": float(roe),
        "bucket": str(rule["bucket"]),
        "score": float(rule["score"]),
        "note": "",
        "provisional": False,
    }


def score_npl_creation(npl_creation: float) -> dict[str, Any]:
    rule = _match_rule(float(npl_creation), NPL_CREATION_RULES)
    return {
        "factor": "npl_creation",
        "value": float(npl_creation),
        "bucket": str(rule["bucket"]),
        "score": float(rule["score"]),
        "note": "",
        "provisional": False,
    }


def score_funding(delta_funding: float, structural_ratio: float) -> dict[str, Any]:
    delta = float(delta_funding)
    ratio = float(structural_ratio)
    if delta >= 0:
        rule = FUNDING_RULES[0]
    elif ratio > 0.95:
        rule = FUNDING_RULES[1]
    elif ratio >= 0.85:
        rule = FUNDING_RULES[2]
    else:
        rule = FUNDING_RULES[3]
    return {
        "factor": "funding",
        "value": delta,
        "bucket": str(rule["bucket"]),
        "score": float(rule["score"]),
        "note": f"credito_captacoes={ratio:.6f}",
        "provisional": False,
    }


def score_qualitative(
    answers: Mapping[str, str],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    result: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for question in QUALITATIVE_QUESTIONS:
        question_id = str(question["id"])
        answer_code = str(answers.get(question_id) or "").strip()
        option = next((item for item in question["options"] if str(item["code"]) == answer_code), None)
        if option is None:
            missing.append(question_id)
            continue
        result[question_id] = {
            "factor": question_id,
            "question": str(question["title"]),
            "group": str(question["group"]),
            "answer_code": answer_code,
            "answer_label": str(option["label"]),
            "score": float(option["score"]),
            "note": str(option.get("note") or question.get("note") or ""),
            "provisional": bool(option.get("provisional", False)),
        }
    return result, missing


def calculate_rating(
    mapped_record: Mapping[str, Any],
    qualitative_answers: Mapping[str, str],
) -> dict[str, Any]:
    mapped_inputs = dict(mapped_record.get("mapped_inputs") or {})
    raw_inputs = dict(mapped_record.get("raw_inputs") or {})

    required_keys = [
        "total_assets",
        "cet1",
        "roe",
        "npl_creation",
        "funding_delta",
        "funding_structural_ratio",
    ]
    missing_quantitative = [
        key
        for key in required_keys
        if mapped_inputs.get(key, {}).get("value") is None
    ]

    qualitative_scores, missing_qualitative = score_qualitative(qualitative_answers)
    if missing_quantitative or missing_qualitative:
        return {
            "institution_id": mapped_record.get("institution_id"),
            "institution_name": mapped_record.get("institution_name"),
            "period": mapped_record.get("period"),
            "raw_inputs": raw_inputs,
            "mapped_inputs": mapped_inputs,
            "replacements": list(mapped_record.get("replacements") or []),
            "size_bucket": None,
            "starting_score": None,
            "quantitative_scores": {},
            "qualitative_scores": qualitative_scores,
            "raw_final_score": None,
            "final_numeric_rating": None,
            "status": "incomplete",
            "missing_quantitative_inputs": missing_quantitative,
            "missing_qualitative_inputs": missing_qualitative,
            "weights_version": WEIGHTS_VERSION,
            "weights_disclosure": WEIGHTS_DISCLOSURE,
        }

    total_assets = float(mapped_inputs["total_assets"]["value"])
    size_bucket = get_size_bucket(total_assets)
    starting_score = int(size_bucket["starting_score"])

    quantitative_scores = {
        "cet1": score_cet1(float(mapped_inputs["cet1"]["value"]), str(size_bucket["key"])),
        "roe": score_roe(float(mapped_inputs["roe"]["value"])),
        "npl_creation": score_npl_creation(float(mapped_inputs["npl_creation"]["value"])),
        "funding": score_funding(
            float(mapped_inputs["funding_delta"]["value"]),
            float(mapped_inputs["funding_structural_ratio"]["value"]),
        ),
    }

    raw_final_score = float(starting_score)
    for item in quantitative_scores.values():
        raw_final_score += float(item["score"])
    for item in qualitative_scores.values():
        raw_final_score += float(item["score"])

    rounded_score = _round_half_up(raw_final_score)
    bounded_score = _clamp(rounded_score, 1, 25)
    hard_floors = [
        int(item["hard_floor_score"])
        for item in quantitative_scores.values()
        if item.get("hard_floor_score") is not None
    ]
    if hard_floors:
        bounded_score = min([bounded_score, *hard_floors])

    return {
        "institution_id": mapped_record.get("institution_id"),
        "institution_name": mapped_record.get("institution_name"),
        "period": mapped_record.get("period"),
        "previous_period": mapped_record.get("previous_period"),
        "raw_inputs": raw_inputs,
        "mapped_inputs": mapped_inputs,
        "replacements": list(mapped_record.get("replacements") or []),
        "size_bucket": {
            "key": str(size_bucket["key"]),
            "label": str(size_bucket["label"]),
            "starting_label": str(size_bucket["starting_label"]),
        },
        "starting_score": starting_score,
        "quantitative_scores": quantitative_scores,
        "qualitative_scores": qualitative_scores,
        "raw_final_score": raw_final_score,
        "rounded_final_score": rounded_score,
        "final_numeric_rating": bounded_score,
        "status": "ok",
        "missing_quantitative_inputs": [],
        "missing_qualitative_inputs": [],
        "weights_version": WEIGHTS_VERSION,
        "weights_disclosure": WEIGHTS_DISCLOSURE,
        "hard_floor_applied": bool(hard_floors and bounded_score != rounded_score),
    }
