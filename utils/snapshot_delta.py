from __future__ import annotations

from typing import Optional
import math


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
      - "absolute" -> diferença na unidade original
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

    if not math.isfinite(atual) or not math.isfinite(anterior):
        return None

    if escala not in {"pct", "dec"}:
        raise ValueError(f"escala inválida: {escala}")

    difference = atual - anterior
    if tipo == "absolute":
        return difference
    if tipo == "pp":
        return difference * (100 if escala == "dec" else 1)
    if tipo == "bps":
        return difference * (10_000 if escala == "dec" else 100)
    if tipo == "pct":
        if anterior <= 0:
            return None
        return difference / anterior * 100

    raise ValueError(f"tipo inválido: {tipo}")
