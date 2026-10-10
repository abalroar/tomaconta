"""Apresentação compacta do COSIF; valores de origem e cálculos ficam intactos."""
from __future__ import annotations

import pandas as pd


def period_label(period: str) -> str:
    months = ("Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez")
    return f"{months[int(period[4:6]) - 1]}/{period[2:4]}"


def account_label(code: str, label: str) -> str:
    name = str(label).split(" | ", 1)[-1].strip()
    return f"{name} · {code}" if name and name != code else code


def _number(value, digits: int = 1) -> str:
    if pd.isna(value):
        return "N/D"
    return f"{value:,.{digits}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def compact_table(rank: pd.DataFrame, periods: list[str]) -> pd.DataFrame:
    """Somente campos de leitura, R$ milhões e percentuais brasileiros."""
    view = rank[["Ranking", "Instituição"]].copy()
    for period in periods:
        view[f"{period_label(period)} (R$ mi)"] = rank[f"Valor {period}"].map(lambda v: _number(v / 1_000_000))
    if len(periods) > 1:
        view["Variação (R$ mi)"] = rank["Variação"].map(lambda v: _number(v / 1_000_000))
        view["Variação (%)"] = rank["Variação %"].map(lambda v: _number(v) + "%" if pd.notna(v) else "N/D")
    view["Participação (%)"] = rank["% do Total Exibido"].map(lambda v: _number(v) + "%" if pd.notna(v) else "N/D")
    return view
