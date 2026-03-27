from __future__ import annotations

import pandas as pd


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
