"""Transformações e figuras do módulo Mercado de Crédito SGS."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .sgs_credit_registry import SGS_SERIES, get_series


ITAU_ORANGE = "#EC7000"
ITAU_BLACK = "#231F20"
ITAU_DARK_GRAY = "#56504C"
ITAU_MID_GRAY = "#8C8279"
ITAU_LIGHT_GRAY = "#C9C3BE"
ITAU_PALETTE = (ITAU_ORANGE, ITAU_BLACK, ITAU_DARK_GRAY, ITAU_MID_GRAY, ITAU_LIGHT_GRAY)


def normalized_long(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"data", "serie", "valor"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Colunas ausentes: {', '.join(sorted(missing))}")
    result = frame.copy()
    result["data"] = pd.to_datetime(result["data"], errors="coerce")
    result["valor"] = pd.to_numeric(result["valor"], errors="coerce")
    return (
        result.dropna(subset=["data", "serie", "valor"])
        .drop_duplicates(["data", "serie"], keep="last")
        .sort_values(["data", "serie"])
        .reset_index(drop=True)
    )


def to_wide(frame: pd.DataFrame, aliases: Sequence[str] | None = None) -> pd.DataFrame:
    long = normalized_long(frame)
    if aliases is not None:
        unknown = set(aliases).difference(SGS_SERIES)
        if unknown:
            raise KeyError(f"Séries fora do registry: {', '.join(sorted(unknown))}")
        long = long[long["serie"].isin(aliases)]
    if long.empty:
        return pd.DataFrame()
    return long.pivot(index="data", columns="serie", values="valor").sort_index()


def build_ipca_index(ipca_monthly_pct: pd.Series, base: float = 100.0) -> pd.Series:
    """Constrói o índice encadeado usado para deflacionar os estoques."""
    inflation = pd.to_numeric(ipca_monthly_pct, errors="coerce")
    valid = inflation.dropna()
    result = pd.Series(index=inflation.index, dtype="float64", name="ipca_index")
    if valid.empty:
        return result
    result.loc[valid.index] = base * (1.0 + valid / 100.0).cumprod()
    return result


def real_yoy(nominal: pd.Series, ipca_index: pd.Series) -> pd.Series:
    """Variação real em 12 meses: (X/IPCA)/(X[-12]/IPCA[-12]) - 1."""
    aligned = pd.concat(
        [pd.to_numeric(nominal, errors="coerce"), pd.to_numeric(ipca_index, errors="coerce")],
        axis=1,
    )
    aligned.columns = ["nominal", "deflator"]
    real_level = aligned["nominal"] / aligned["deflator"]
    return (real_level / real_level.shift(12) - 1.0) * 100.0


def yoy_pp(values: pd.Series) -> pd.Series:
    """Diferença em pontos percentuais contra o mesmo mês do ano anterior."""
    return pd.to_numeric(values, errors="coerce").diff(12)


def sum_columns(wide: pd.DataFrame, aliases: Sequence[str], *, min_count: int | None = None) -> pd.Series:
    missing = set(aliases).difference(wide.columns)
    if missing:
        return pd.Series(index=wide.index, dtype="float64")
    required_count = len(aliases) if min_count is None else min_count
    return wide[list(aliases)].sum(axis=1, min_count=required_count)


def shares(wide: pd.DataFrame, aliases: Sequence[str], total: pd.Series | None = None) -> pd.DataFrame:
    available = [alias for alias in aliases if alias in wide.columns]
    if not available:
        return pd.DataFrame(index=wide.index)
    values = wide[available]
    denominator = total if total is not None else values.sum(axis=1, min_count=len(available))
    denominator = pd.to_numeric(denominator, errors="coerce").replace(0, np.nan)
    return values.div(denominator, axis=0) * 100.0


def derive_credit_totals(wide: pd.DataFrame) -> pd.DataFrame:
    result = wide.copy()
    component_aliases = [
        "saldo_livre_pj", "saldo_livre_pf", "saldo_direcionado_pj", "saldo_direcionado_pf"
    ]
    result["saldo_sfn_total_derivado"] = sum_columns(result, component_aliases)
    result["saldo_pj_total_derivado"] = sum_columns(
        result, ["saldo_livre_pj", "saldo_direcionado_pj"]
    )
    result["saldo_pf_total_derivado"] = sum_columns(
        result, ["saldo_livre_pf", "saldo_direcionado_pf"]
    )
    return result


def coverage_ratio(provision_pct: pd.Series, delinquency_pct: pd.Series) -> pd.Series:
    delinquency = pd.to_numeric(delinquency_pct, errors="coerce").replace(0, np.nan)
    return pd.to_numeric(provision_pct, errors="coerce") / delinquency * 100.0


def _last_text(values: pd.Series, decimals: int = 1, suffix: str = "") -> list[str | None]:
    text: list[str | None] = [None] * len(values)
    valid_positions = np.flatnonzero(values.notna().to_numpy())
    if len(valid_positions):
        value = float(values.iloc[valid_positions[-1]])
        text[valid_positions[-1]] = f"{value:.{decimals}f}{suffix}".replace(".", ",")
    return text


def _base_layout(fig: go.Figure, *, title: str, y_title: str, height: int = 390) -> go.Figure:
    fig.update_layout(
        title={"text": title, "x": 0.01, "xanchor": "left"},
        height=height,
        margin={"l": 12, "r": 42, "t": 72, "b": 25},
        paper_bgcolor="white",
        plot_bgcolor="white",
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        font={"family": "Arial", "color": ITAU_BLACK},
        yaxis_title=y_title,
    )
    fig.update_xaxes(showgrid=False, tickformat="%b-%y")
    fig.update_yaxes(gridcolor="#ECE8E5", zerolinecolor="#B8B1AB")
    return fig


def line_figure(
    wide: pd.DataFrame,
    aliases: Sequence[str],
    *,
    title: str,
    y_title: str,
    labels: Mapping[str, str] | None = None,
    decimals: int = 1,
    suffix: str = "",
) -> go.Figure:
    fig = go.Figure()
    for index, alias in enumerate(aliases):
        if alias not in wide.columns:
            continue
        values = pd.to_numeric(wide[alias], errors="coerce")
        label = (labels or {}).get(alias) or (get_series(alias).label if alias in SGS_SERIES else alias)
        fig.add_trace(
            go.Scatter(
                x=wide.index,
                y=values,
                name=label,
                mode="lines+text",
                text=_last_text(values, decimals, suffix),
                textposition="middle right",
                cliponaxis=False,
                line={"color": ITAU_PALETTE[index % len(ITAU_PALETTE)], "width": 2.3},
            )
        )
    return _base_layout(fig, title=title, y_title=y_title)


def stacked_figure(
    wide: pd.DataFrame,
    aliases: Sequence[str],
    *,
    title: str,
    y_title: str,
    labels: Mapping[str, str] | None = None,
    scale: float = 1.0,
    total: pd.Series | None = None,
    percent: bool = False,
) -> go.Figure:
    fig = go.Figure()
    for index, alias in enumerate(aliases):
        if alias not in wide.columns:
            continue
        values = pd.to_numeric(wide[alias], errors="coerce") * scale
        label = (labels or {}).get(alias) or (get_series(alias).label if alias in SGS_SERIES else alias)
        fig.add_trace(
            go.Bar(
                x=wide.index,
                y=values,
                name=label,
                marker_color=ITAU_PALETTE[index % len(ITAU_PALETTE)],
                text=_last_text(values, 1, "%" if percent else ""),
                textposition="inside",
            )
        )
    if total is not None:
        total_values = pd.to_numeric(total, errors="coerce") * scale
        fig.add_trace(
            go.Scatter(
                x=wide.index,
                y=total_values,
                name="Total",
                mode="text",
                text=_last_text(total_values, 1, "%" if percent else ""),
                textposition="top center",
                showlegend=False,
                cliponaxis=False,
            )
        )
    fig.update_layout(barmode="stack")
    return _base_layout(fig, title=title, y_title=y_title)


def bar_line_figure(
    wide: pd.DataFrame,
    *,
    bar_alias: str,
    line_alias: str,
    title: str,
    bar_title: str = "R$ bi",
    line_title: str = "meses",
) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if bar_alias in wide.columns:
        bar = pd.to_numeric(wide[bar_alias], errors="coerce") / 1000.0
        fig.add_trace(
            go.Bar(
                x=wide.index,
                y=bar,
                name=get_series(bar_alias).label,
                marker_color=ITAU_LIGHT_GRAY,
                text=_last_text(bar, 1),
                textposition="outside",
            ),
            secondary_y=False,
        )
    if line_alias in wide.columns:
        line = pd.to_numeric(wide[line_alias], errors="coerce")
        fig.add_trace(
            go.Scatter(
                x=wide.index,
                y=line,
                name=get_series(line_alias).label,
                mode="lines+text",
                line={"color": ITAU_ORANGE, "width": 2.5},
                text=_last_text(line, 1),
                textposition="middle right",
                cliponaxis=False,
            ),
            secondary_y=True,
        )
    _base_layout(fig, title=title, y_title=bar_title)
    fig.update_yaxes(title_text=bar_title, secondary_y=False)
    fig.update_yaxes(title_text=line_title, secondary_y=True, showgrid=False)
    return fig
