"""Static configuration for the rating model."""

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

WEIGHTS_VERSION = "configured_weight_table_v1"
WEIGHTS_DISCLOSURE = "O motor está usando a tabela de pesos configurada para esta modelagem."

STARTING_SCORE_RULES = [
    {
        "key": "above_200bn",
        "label": "Acima de R$ 200 bi",
        "min_assets": 200_000_000_000.0,
        "max_assets": None,
        "starting_score": 22,
        "starting_label": "A3",
    },
    {
        "key": "between_20bn_200bn",
        "label": "Entre R$ 20 bi e R$ 200 bi",
        "min_assets": 20_000_000_000.0,
        "max_assets": 200_000_000_000.0,
        "starting_score": 19,
        "starting_label": "Baa3",
    },
    {
        "key": "below_20bn",
        "label": "Abaixo de R$ 20 bi",
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
            "note": "Severe CET1 floor applied below the threshold.",
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
            "note": "Severe CET1 floor applied below the threshold.",
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
            "note": "Severe CET1 floor applied below the threshold.",
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

ASSET_QUALITY_RULES = {
    "inad_ratio_exact": [
        {"bucket": "> 5,0%", "min": 0.05, "max": None, "score": -0.43, "min_inclusive": False},
        {"bucket": "5,0% a 2,51%", "min": 0.025, "max": 0.05, "score": -0.21},
        {"bucket": "≤ 2,5%", "min": None, "max": 0.025, "score": 0.00},
    ],
    "proxy_loss_ratio": [
        {"bucket": "> 8,0%", "min": 0.08, "max": None, "score": -0.43, "min_inclusive": False},
        {"bucket": "8,0% a 4,01%", "min": 0.04, "max": 0.08, "score": -0.21},
        {"bucket": "≤ 4,0%", "min": None, "max": 0.04, "score": 0.00},
    ],
    "legacy_dh_ratio": [
        {"bucket": "> 5,0%", "min": 0.05, "max": None, "score": -0.43, "min_inclusive": False},
        {"bucket": "5,0% a 2,51%", "min": 0.025, "max": 0.05, "score": -0.21},
        {"bucket": "≤ 2,5%", "min": None, "max": 0.025, "score": 0.00},
    ],
}

FUNDING_RULES = [
    {
        "bucket": "Variação % do funding >= 0",
        "score": 0.00,
        "condition": "delta_non_negative",
    },
    {
        "bucket": "Funding negativo e Crédito / Captações > 95%",
        "score": 0.00,
        "condition": "delta_negative_ratio_above_95",
    },
    {
        "bucket": "Funding negativo e Crédito / Captações entre 95% e 85%",
        "score": -0.23,
        "condition": "delta_negative_ratio_between_95_85",
    },
    {
        "bucket": "Funding negativo e Crédito / Captações < 85%",
        "score": -0.45,
        "condition": "delta_negative_ratio_below_85",
    },
]

QUALITATIVE_QUESTIONS = [
    {
        "id": "q1",
        "label": "Q1",
        "title": "Auditoria",
        "group": "Qualidade da informação",
        "note": "",
        "options": [
            {
                "code": "A",
                "label": "Auditoria sem ressalva relevante",
                "score": 0.00,
            },
            {
                "code": "B",
                "label": "Auditoria com ressalva relevante",
                "score": -0.22,
            },
            {
                "code": "C",
                "label": "Sem auditoria ou com problema material",
                "score": -0.58,
                "provisional": True,
                "note": "",
            },
        ],
    },
    {
        "id": "q2",
        "label": "Q2",
        "title": "Ressalvas",
        "group": "Qualidade da informação",
        "note": "",
        "options": [
            {
                "code": "A",
                "label": "Sem ressalva relevante",
                "score": 0.00,
            },
            {
                "code": "B",
                "label": "Uma ressalva relevante",
                "score": -0.22,
            },
            {
                "code": "C",
                "label": "Ressalva material",
                "score": -0.58,
                "provisional": True,
                "note": "",
            },
        ],
    },
    {
        "id": "q3",
        "label": "Q3",
        "title": "Suporte acionário",
        "group": "Gestão",
        "note": "",
        "options": [
            {
                "code": "A",
                "label": "Suporte forte do acionista",
                "score": 1.13,
            },
            {
                "code": "B",
                "label": "Suporte neutro ou limitado",
                "score": 0.00,
            },
            {
                "code": "C",
                "label": "Suporte fraco ou risco reputacional",
                "score": -1.13,
            },
        ],
    },
    {
        "id": "q4",
        "label": "Q4",
        "title": "Governança",
        "group": "Gestão",
        "note": "",
        "options": [
            {
                "code": "A",
                "label": "Aderência plena",
                "score": 0.00,
            },
            {
                "code": "B",
                "label": "Aderência parcial",
                "score": -0.41,
            },
            {
                "code": "C",
                "label": "Não aderente ou com problema grave",
                "score": -0.82,
                "provisional": True,
                "note": "",
            },
        ],
    },
    {
        "id": "q5",
        "label": "Q5",
        "title": "Concentração",
        "group": "Sensibilidade de mercado",
        "note": "",
        "options": [
            {
                "code": "A",
                "label": "Perfil diversificado",
                "score": 0.22,
            },
            {
                "code": "B",
                "label": "Perfil neutro",
                "score": 0.00,
            },
            {
                "code": "C",
                "label": "Alta concentração",
                "score": -0.22,
            },
        ],
    },
    {
        "id": "q6",
        "label": "Q6",
        "title": "Resiliência de mercado",
        "group": "Sensibilidade de mercado",
        "note": "",
        "options": [
            {
                "code": "A",
                "label": "Perfil resiliente",
                "score": 0.72,
            },
            {
                "code": "B",
                "label": "Perfil neutro",
                "score": 0.00,
            },
            {
                "code": "C",
                "label": "Perfil frágil",
                "score": -0.72,
            },
        ],
    },
]

MODEL_DISCLOSURES = [
    WEIGHTS_DISCLOSURE,
]
