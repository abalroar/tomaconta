from __future__ import annotations

from typing import Optional

import pandas as pd


def compute_delta(
    valor_atual: float,
    valor_anterior: float,
    tipo: str,
    escala: str = "pct",
) -> Optional[float]:
    """Computa delta com normalização explícita de escala.

    tipo:
      - "pp"  -> diferença em pontos percentuais
      - "bps" -> diferença em basis points
      - "pct" -> variação relativa percentual
    escala:
      - "pct" -> valores já em base percentual (ex.: 21.38)
      - "dec" -> valores em base decimal (ex.: 0.2138)
    """
    if valor_atual is None or valor_anterior is None:
        return None

    try:
        atual = float(valor_atual)
        anterior = float(valor_anterior)
    except (TypeError, ValueError):
        return None

    if pd.isna(atual) or pd.isna(anterior):
        return None

    if escala not in {"pct", "dec"}:
        raise ValueError(f"escala inválida: {escala}")

    if escala == "dec":
        atual *= 100
        anterior *= 100

    if tipo == "pp":
        return atual - anterior
    if tipo == "bps":
        return (atual - anterior) * 100
    if tipo == "pct":
        if anterior == 0:
            return None
        return (atual / anterior - 1) * 100

    raise ValueError(f"tipo inválido: {tipo}")
