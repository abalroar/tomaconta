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
ITAU_PALETTE = (
    ITAU_ORANGE,
    ITAU_BLACK,
    "#423E3B",
    ITAU_DARK_GRAY,
    "#69615C",
    "#7B726C",
    ITAU_MID_GRAY,
    "#9D938B",
    "#AEA59F",
    ITAU_LIGHT_GRAY,
)


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


def _source_aliases(wide: pd.DataFrame, aliases: Sequence[str]) -> list[str]:
    """Resolve as séries SGS de origem para a ficha de informação do gráfico."""
    candidates = [*wide.attrs.get("source_aliases", []), *aliases]
    return list(dict.fromkeys(alias for alias in candidates if alias in SGS_SERIES))


def _staggered_positions(raw_values: Sequence[float], data_span: float) -> list[float]:
    """Distribui rótulos finais mantendo a ordem vertical das séries."""
    if not raw_values:
        return []
    values = np.asarray(raw_values, dtype="float64")
    reference = max(float(np.nanmax(np.abs(values))), 1.0)
    gap = max(data_span * 0.065, reference * 0.006)

    ordered = sorted(range(len(values)), key=lambda index: values[index])
    positions = values.copy()
    for previous, current in zip(ordered, ordered[1:]):
        positions[current] = max(values[current], positions[previous] + gap)

    raw_midpoint = float(np.nanmean(values))
    positioned_midpoint = float(np.nanmean(positions))
    positions -= positioned_midpoint - raw_midpoint
    return positions.tolist()


def _add_last_line_labels(
    fig: go.Figure,
    endpoints: Sequence[tuple[pd.Timestamp, float, str, str]],
    *,
    yref: str = "y",
    plot_height: int = 285,
) -> None:
    """Adiciona rótulos coloridos e escalonados junto ao fim de cada linha."""
    if not endpoints:
        return
    raw_values = [point[1] for point in endpoints]
    trace_values: list[float] = []
    for trace in fig.data:
        trace_yref = getattr(trace, "yaxis", None) or "y"
        if trace_yref != yref or getattr(trace, "y", None) is None:
            continue
        numeric = pd.to_numeric(pd.Series(trace.y), errors="coerce").dropna()
        trace_values.extend(float(value) for value in numeric)
    if trace_values:
        span = float(np.nanmax(trace_values) - np.nanmin(trace_values))
    else:
        span = float(np.nanmax(raw_values) - np.nanmin(raw_values))
    reference = max(float(np.nanmax(np.abs(raw_values))), 1.0)
    span = max(span, reference * 0.1, 1e-9)
    positioned = _staggered_positions(raw_values, span)

    for (last_x, raw_y, text, color), label_y in zip(endpoints, positioned):
        pixel_offset = int(round(-(label_y - raw_y) / span * plot_height))
        fig.add_annotation(
            x=last_x,
            y=raw_y,
            xref="x",
            yref=yref,
            text=text,
            showarrow=True,
            arrowhead=0,
            arrowwidth=1,
            arrowcolor=color,
            ax=42,
            ay=pixel_offset,
            xanchor="left",
            align="left",
            font={"color": color, "size": 11},
            bgcolor="rgba(255,255,255,0.82)",
            borderpad=1,
        )
    x_values: list[pd.Timestamp] = []
    for trace in fig.data:
        trace_x = getattr(trace, "x", None)
        if trace_x is not None:
            x_values.extend(pd.Timestamp(value) for value in trace_x if pd.notna(value))
    if x_values:
        fig.update_xaxes(
            range=[min(x_values), max(x_values) + pd.DateOffset(months=1)]
        )


def _base_layout(fig: go.Figure, *, title: str, y_title: str, height: int = 390) -> go.Figure:
    fig.update_layout(
        title={"text": title, "x": 0.01, "xanchor": "left"},
        height=height,
        margin={"l": 12, "r": 96, "t": 72, "b": 25},
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
    endpoints: list[tuple[pd.Timestamp, float, str, str]] = []
    for index, alias in enumerate(aliases):
        if alias not in wide.columns:
            continue
        values = pd.to_numeric(wide[alias], errors="coerce")
        label = (labels or {}).get(alias) or (get_series(alias).label if alias in SGS_SERIES else alias)
        color = ITAU_PALETTE[index % len(ITAU_PALETTE)]
        fig.add_trace(
            go.Scatter(
                x=wide.index,
                y=values,
                name=label,
                mode="lines",
                cliponaxis=False,
                line={"color": color, "width": 2.3},
                meta={"series_alias": alias},
            )
        )
        valid = values.dropna()
        if not valid.empty:
            value = float(valid.iloc[-1])
            text = f"{value:.{decimals}f}{suffix}".replace(".", ",")
            endpoints.append((pd.Timestamp(valid.index[-1]), value, text, color))
    _add_last_line_labels(fig, endpoints)
    fig.update_layout(meta={"source_aliases": _source_aliases(wide, aliases)})
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
                meta={"series_alias": alias},
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
    total_alias = getattr(total, "name", None) if total is not None else None
    source_candidates = [*aliases, *([total_alias] if total_alias else [])]
    fig.update_layout(meta={"source_aliases": _source_aliases(wide, source_candidates)})
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
                meta={"series_alias": bar_alias},
            ),
            secondary_y=False,
        )
    if line_alias in wide.columns:
        line = pd.to_numeric(wide[line_alias], errors="coerce")
        line_color = ITAU_ORANGE
        fig.add_trace(
            go.Scatter(
                x=wide.index,
                y=line,
                name=get_series(line_alias).label,
                mode="lines",
                line={"color": line_color, "width": 2.5},
                cliponaxis=False,
                meta={"series_alias": line_alias},
            ),
            secondary_y=True,
        )
        valid = line.dropna()
        if not valid.empty:
            value = float(valid.iloc[-1])
            _add_last_line_labels(
                fig,
                [(pd.Timestamp(valid.index[-1]), value, f"{value:.1f}".replace(".", ","), line_color)],
                yref="y2",
            )
    fig.update_layout(meta={"source_aliases": _source_aliases(wide, [bar_alias, line_alias])})
    _base_layout(fig, title=title, y_title=bar_title)
    fig.update_yaxes(title_text=bar_title, secondary_y=False)
    fig.update_yaxes(title_text=line_title, secondary_y=True, showgrid=False)
    return fig
