"""Static configuration for the reverse-engineered rating model."""

from __future__ import annotations

NUMERIC_TO_LABEL = {
    25: "Aaa",
    24: "Aa3",
    23: "A1",
    22: "A3",
    21: "A4",
    20: "Baa1",
    19: "Baa3",
    18: "Baa4",
    17: "Ba1",
    16: "Ba4",
    15: "Ba5",
    14: "Ba6",
    13: "B1",
    12: "B2",
    11: "B3",
    10: "B4",
    9: "C1",
    8: "C2",
    7: "C3",
    6: "D1",
    5: "D3",
    4: "E1",
    3: "F",
    2: "G",
    1: "H",
}

WEIGHTS_VERSION = "rounded_lookup_table_fallback"
WEIGHTS_DISCLOSURE = (
    "Exact workbook coefficients were not found in the repository. "
    "The engine is using the rounded lookup-table weights visible in the reverse-engineered material."
)

STARTING_SCORE_RULES = [
    {
        "key": "above_200bn",
        "label": "Above R$ 200bn",
        "min_assets": 200_000_000_000.0,
        "max_assets": None,
        "starting_score": 22,
        "starting_label": "A3",
    },
    {
        "key": "between_20bn_200bn",
        "label": "R$ 20bn to R$ 200bn",
        "min_assets": 20_000_000_000.0,
        "max_assets": 200_000_000_000.0,
        "starting_score": 19,
        "starting_label": "Baa3",
    },
    {
        "key": "below_20bn",
        "label": "Below R$ 20bn",
        "min_assets": None,
        "max_assets": 20_000_000_000.0,
        "starting_score": 16,
        "starting_label": "Ba4",
    },
]

CET1_RULES = {
    "above_200bn": [
        {"bucket": "> 16%", "min": 0.16, "max": None, "score": 0.41, "min_inclusive": False},
        {"bucket": "16% to 14.01%", "min": 0.14, "max": 0.16, "score": 0.20},
        {"bucket": "14% to 10.01%", "min": 0.10, "max": 0.14, "score": 0.00},
        {"bucket": "10% to 8%", "min": 0.08, "max": 0.10, "score": -0.22},
        {
            "bucket": "< 8%",
            "min": None,
            "max": 0.08,
            "score": -0.22,
            "hard_floor_score": 1,
            "provisional": True,
            "note": (
                "The source material shows a severe CET1 floor/red flag below 8%, "
                "but not the exact coefficient. This implementation keeps the last visible penalty "
                "and applies a provisional hard floor to rating 1."
            ),
        },
    ],
    "between_20bn_200bn": [
        {"bucket": "> 18%", "min": 0.18, "max": None, "score": 0.41, "min_inclusive": False},
        {"bucket": "18% to 16.01%", "min": 0.16, "max": 0.18, "score": 0.20},
        {"bucket": "16% to 12.01%", "min": 0.12, "max": 0.16, "score": 0.00},
        {"bucket": "12% to 7%", "min": 0.07, "max": 0.12, "score": -0.22},
        {
            "bucket": "< 7%",
            "min": None,
            "max": 0.07,
            "score": -0.22,
            "hard_floor_score": 1,
            "provisional": True,
            "note": (
                "The source material shows a severe CET1 floor/red flag below 7%, "
                "but not the exact coefficient. This implementation keeps the last visible penalty "
                "and applies a provisional hard floor to rating 1."
            ),
        },
    ],
    "below_20bn": [
        {"bucket": "> 20%", "min": 0.20, "max": None, "score": 0.41, "min_inclusive": False},
        {"bucket": "20% to 18.01%", "min": 0.18, "max": 0.20, "score": 0.20},
        {"bucket": "18% to 14.01%", "min": 0.14, "max": 0.18, "score": 0.00},
        {"bucket": "14% to 7%", "min": 0.07, "max": 0.14, "score": -0.22},
        {
            "bucket": "< 7%",
            "min": None,
            "max": 0.07,
            "score": -0.22,
            "hard_floor_score": 1,
            "provisional": True,
            "note": (
                "The source material shows a severe CET1 floor/red flag below 7%, "
                "but not the exact coefficient. This implementation keeps the last visible penalty "
                "and applies a provisional hard floor to rating 1."
            ),
        },
    ],
}

ROE_RULES = [
    {"bucket": "> 18%", "min": 0.18, "max": None, "score": 0.91, "min_inclusive": False},
    {"bucket": "18% to 14.01%", "min": 0.14, "max": 0.18, "score": 0.45},
    {"bucket": "14% to 9.01%", "min": 0.09, "max": 0.14, "score": 0.00},
    {"bucket": "9% to 0%", "min": 0.0, "max": 0.09, "score": -0.42},
    {"bucket": "< 0%", "min": None, "max": 0.0, "score": -0.83, "max_inclusive": False},
]

NPL_CREATION_RULES = [
    {"bucket": "> 4%", "min": 0.04, "max": None, "score": -0.43, "min_inclusive": False},
    {"bucket": "4% to 2.01%", "min": 0.02, "max": 0.04, "score": -0.21},
    {"bucket": "< 2%", "min": None, "max": 0.02, "score": 0.00},
]

FUNDING_RULES = [
    {
        "bucket": "Delta funding >= 0",
        "score": 0.00,
        "condition": "delta_non_negative",
    },
    {
        "bucket": "Delta funding < 0 and structural ratio > 95%",
        "score": 0.00,
        "condition": "delta_negative_ratio_above_95",
    },
    {
        "bucket": "Delta funding < 0 and structural ratio between 95% and 85%",
        "score": -0.23,
        "condition": "delta_negative_ratio_between_95_85",
    },
    {
        "bucket": "Delta funding < 0 and structural ratio < 85%",
        "score": -0.45,
        "condition": "delta_negative_ratio_below_85",
    },
]

QUALITATIVE_QUESTIONS = [
    {
        "id": "q1",
        "label": "Q1",
        "title": "Audit",
        "group": "Quality of information",
        "note": "Reverse-engineered from screenshots. Option wording remains provisional.",
        "options": [
            {
                "code": "A",
                "label": "First-line / no relevant audit issue",
                "score": 0.00,
            },
            {
                "code": "B",
                "label": "Second-line / one relevant issue",
                "score": -0.22,
            },
            {
                "code": "C",
                "label": "No audit / material issue",
                "score": -0.58,
                "provisional": True,
                "note": "The severe penalty is inferred from the material and should be validated against the original workbook.",
            },
        ],
    },
    {
        "id": "q2",
        "label": "Q2",
        "title": "Reservations / qualifications",
        "group": "Quality of information",
        "note": "Reverse-engineered from screenshots. Option wording remains provisional.",
        "options": [
            {
                "code": "A",
                "label": "No relevant reservation",
                "score": 0.00,
            },
            {
                "code": "B",
                "label": "One relevant reservation",
                "score": -0.22,
            },
            {
                "code": "C",
                "label": "Material reservation / qualified information",
                "score": -0.58,
                "provisional": True,
                "note": "The exact severe penalty for Q2 was not visible; this mirrors the Q1 severe penalty as a documented fallback.",
            },
        ],
    },
    {
        "id": "q3",
        "label": "Q3",
        "title": "Shareholder strength / support",
        "group": "Management",
        "note": "Reverse-engineered from screenshots. Option wording remains provisional.",
        "options": [
            {
                "code": "A",
                "label": "Strong shareholder support",
                "score": 1.13,
            },
            {
                "code": "B",
                "label": "Neutral / limited support",
                "score": 0.00,
            },
            {
                "code": "C",
                "label": "Weak support / reputation risk",
                "score": -1.13,
            },
        ],
    },
    {
        "id": "q4",
        "label": "Q4",
        "title": "Governance / adherence",
        "group": "Management",
        "note": "Reverse-engineered from screenshots. Option wording remains provisional.",
        "options": [
            {
                "code": "A",
                "label": "Full adherence",
                "score": 0.00,
            },
            {
                "code": "B",
                "label": "Partial adherence",
                "score": -0.41,
            },
            {
                "code": "C",
                "label": "Non-adherent / severe governance issue",
                "score": -0.82,
                "provisional": True,
                "note": "The severe Q4 penalty was not legible in the material; this uses a doubled visible step as an explicit fallback.",
            },
        ],
    },
    {
        "id": "q5",
        "label": "Q5",
        "title": "Concentration",
        "group": "Market sensitivity",
        "note": "Reverse-engineered from screenshots. Option wording remains provisional.",
        "options": [
            {
                "code": "A",
                "label": "Diversified / favorable concentration profile",
                "score": 0.22,
            },
            {
                "code": "B",
                "label": "Neutral concentration profile",
                "score": 0.00,
            },
            {
                "code": "C",
                "label": "High concentration / fragile profile",
                "score": -0.22,
            },
        ],
    },
    {
        "id": "q6",
        "label": "Q6",
        "title": "Sustainability / resilience / market sensitivity",
        "group": "Market sensitivity",
        "note": "Reverse-engineered from screenshots. Option wording remains provisional.",
        "options": [
            {
                "code": "A",
                "label": "Resilient / favorable market reference",
                "score": 0.72,
            },
            {
                "code": "B",
                "label": "Neutral",
                "score": 0.00,
            },
            {
                "code": "C",
                "label": "Fragile market position",
                "score": -0.72,
            },
        ],
    },
]

MODEL_DISCLOSURES = [
    "No legacy rating workbook or exact scoring engine was found in the repository.",
    WEIGHTS_DISCLOSURE,
    (
        "The selected prudential source for this tab is the existing critical_screens cache, "
        "which already consolidates prudential, balance-sheet and trace fields used by Snapshot/Peers."
    ),
    (
        "CET1 uses the exact curated field when available. If CET1 is missing but total Basel ratio exists, "
        "the engine uses total Basel ratio as an explicit fallback proxy for capital adequacy."
    ),
    (
        "The legacy NPL Creation field was not found. The primary proxy is the quarter-on-quarter change in "
        "Perda Esperada / Carteira de Crédito Bruta. A secondary proxy is the quarter-on-quarter change in "
        "Ativos Estágio 3 / Carteira de Crédito Bruta."
    ),
    (
        "The legacy structural funding ratio field was not found. The engine uses the existing curated field "
        "Crédito / Captações as the structural funding proxy and computes delta funding from current minus "
        "previous-quarter Core Funding."
    ),
]
