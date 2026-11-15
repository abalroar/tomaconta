from __future__ import annotations

import pandas as pd
from decimal import Decimal, ROUND_HALF_UP
import math


def _ptbr(texto: str) -> str:
    return str(texto).replace(",", "X").replace(".", ",").replace("X", ".")


def formatar_percentual_br(valor: float, casas: int = 1) -> str:
    if valor is None or pd.isna(valor):
        return "N/D"
    return _ptbr(f"{float(valor):,.{casas}f}%")


def formatar_pp_br(valor: float, casas: int = 1) -> str:
    if valor is None or pd.isna(valor):
        return "N/D"
    return _ptbr(f"{float(valor):+,.{casas}f} p.p.")


def formatar_razao_br(valor: float, casas: int = 2) -> str:
    if valor is None or pd.isna(valor):
        return "N/D"
    return _ptbr(f"{float(valor):,.{casas}f}x")


def formatar_numero_br(valor: float, casas: int = 2, sufixo: str = "", com_sinal: bool = False) -> str:
    if valor is None or pd.isna(valor):
        return "N/D"
    v = float(valor)
    if com_sinal:
        texto = f"{v:+,.{casas}f}"
    else:
        texto = f"{v:,.{casas}f}"
    return f"{_ptbr(texto)}{sufixo}"


def formatar_delta_br(valor: float, unidade: str, casas: int = 2, com_seta: bool = False) -> str:
    """Arredonda somente a exibição e preserva o sinal de movimentos pequenos."""
    if valor is None or not math.isfinite(float(valor)):
        return "N/D"
    value = float(valor)
    # Remove o ruído binário da subtração em floats antes de arredondar a exibição.
    rounded = Decimal(f"{value:.12g}").quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP)
    arrow = "↑ " if value > 0 else "↓ " if value < 0 else "= "
    sign = "+" if value > 0 else "−" if value < 0 else ""
    if not rounded and value:
        threshold_unit = "bp" if unidade == "bps" else unidade
        threshold = _ptbr(f"{10 ** -casas:.{casas}f}")
        return f"{arrow if com_seta else sign}<{threshold} {threshold_unit}"
    text = _ptbr(f"{abs(rounded):,.{casas}f}")
    return f"{arrow if com_seta else ''}{sign}{text} {unidade}".rstrip()


def formatar_monetario_br_auto_reais(valor_reais: float) -> str:
    """Formata monetário em BR com escala automática (R$, mil, MM, bi, tri)."""
    if valor_reais is None or pd.isna(valor_reais):
        return "N/D"

    valor = float(valor_reais)
    sinal = "-" if valor < 0 else ""
    abs_val = abs(valor)

    if abs_val >= 1_000_000_000_000:
        return f"{sinal}R$ {_ptbr(f'{abs_val/1e12:,.1f}')} tri"
    if abs_val >= 1_000_000_000:
        return f"{sinal}R$ {_ptbr(f'{abs_val/1e9:,.1f}')} bi"
    if abs_val >= 1_000_000:
        return f"{sinal}R$ {_ptbr(f'{abs_val/1e6:,.0f}')} MM"
    if abs_val >= 1_000:
        return f"{sinal}R$ {_ptbr(f'{abs_val/1e3:,.1f}')} mil"
    return f"{sinal}R$ {_ptbr(f'{abs_val:,.0f}')}"
