"""Presentation of the existing Evolução chart and five-row table."""

from html import escape
import math
import re

import pandas as pd
import plotly.graph_objects as go


HEADER_COLOR = "#EC7000"
METRIC_LABELS = {
    "ROE Ac. Anualizado (%)": "ROE Anualizado",
    "Carteira de Crédito* / PL": "Carteira / PL (x)",
    "Índice de Capital Principal (CET1)": "Capital Principal -CET1 (%)",
    "Índice de Capital T1 (%)": "Capital Nível 1 (%)",
    "Índice de Basileia Total (%)": "Índice de Basileia Total (%)",
}
SERIES = (
    ("Lucro Líquido", "Lucro Líquido Acumulado", "#111111", "y", -.17),
    ("Patrimônio Líquido", "Patrimônio Líquido", "#6E6E6E", "y", .17),
    ("Carteira de Crédito*", "Carteira de Crédito*", "#ff5a00", "y2", 0),
    ("Core Funding*", "Core Funding*", "#222222", "y2", 0),
)


def period_label(value: str) -> str:
    """Shorten display labels without changing the period keys."""
    match = re.fullmatch(r"([a-zA-Z]{3})[-/](\d{2})", str(value))
    return f"{match[1].capitalize()}/{match[2]}" if match else str(value)


def number_br(value: float, decimals: int = 1) -> str:
    return f"{value:,.{decimals}f}".translate(str.maketrans({",": ".", ".": ","}))


def _axis_range(values: list[float]) -> tuple[float, float]:
    finite = [v for v in values if math.isfinite(v)]
    low, high = min([0, *finite]), max([0, *finite])
    span = max(high - low, .1)
    return (low - span * .12 if low < 0 else 0, high + span * .25)


def build_evolucao_chart(df_graph: pd.DataFrame, labels: list[str], *, revision: str = "evolucao") -> go.Figure:
    """Keep four series/two axes, converting only the plotted values to R$ bi."""
    displayed = [period_label(label) for label in labels]
    values = {
        column: pd.to_numeric(df_graph[column], errors="coerce").to_numpy(dtype=float) / 1e9
        for column, *_ in SERIES
    }
    ranges = {
        axis: _axis_range([float(v) for column, _, _, series_axis, _ in SERIES if series_axis == axis for v in values[column]])
        for axis in ("y", "y2")
    }
    fig = go.Figure()
    last_indices = {}
    for column, name, color, axis, _ in SERIES:
        series = values[column]
        available = [i for i, value in enumerate(series) if math.isfinite(value)]
        last_indices[column] = available[-1] if available else None
        kwargs = dict(
            x=list(range(len(displayed))), y=series, name=name, yaxis=axis, legendgroup=column,
            customdata=[number_br(v, 2) if math.isfinite(v) else "N/D" for v in series],
            hovertemplate="%{customdata} R$ bi<extra>%{fullData.name}</extra>",
        )
        if axis == "y":
            fig.add_trace(go.Bar(**kwargs, marker_color=color))
        else:
            fig.add_trace(go.Scatter(
                **kwargs, mode="lines+markers", connectgaps=False,
                line=dict(color=color, width=2, shape="spline", smoothing=1.15),
                marker=dict(size=7, color=color),
            ))

    # Layout in screen pixels, across both axes, so nearby labels remain distinct.
    plot_height, gap = 377, 27
    label_traces = {column: {"x": [], "y": [], "text": [], "size": []} for column, *_ in SERIES}
    dense = len(labels) > 8
    for index in range(len(labels)):
        points = []
        for column, _, color, axis, xoffset in SERIES:
            value = values[column][index]
            is_last = last_indices[column] == index
            if not math.isfinite(value) or (dense and not is_last):
                continue
            low, high = ranges[axis]
            target = plot_height * (1 - (value - low) / (high - low)) - 12
            points.append(dict(column=column, value=value, color=color, axis=axis, xoffset=xoffset, target=target, last=is_last))
        points.sort(key=lambda point: point["target"])
        if points:
            points[-1]["position"] = min(plot_height - 14, max(14, points[-1]["target"]))
        for i in range(len(points) - 2, -1, -1):
            points[i]["position"] = min(points[i]["target"], points[i + 1]["position"] - gap)
        if points:
            top_shift = max(0, 14 - points[0]["position"])
            for point in points:
                point["position"] += top_shift
        for point in points:
            text = number_br(point["value"])
            if point["last"]:
                text = f"<b>{text}</b>"
                if dense and index != len(labels) - 1:
                    text += "<br>" + escape(displayed[index])
            low, high = ranges[point["axis"]]
            label_y = low + (1 - point["position"] / plot_height) * (high - low)
            trace = label_traces[point["column"]]
            trace["x"].append(index + point["xoffset"])
            trace["y"].append(label_y)
            trace["text"].append(text)
            trace["size"].append(13 if point["last"] else 12)

    # Labels share their series' native legend group: hide/show and hover stay fluent.
    for column, _, color, axis, _ in SERIES:
        trace = label_traces[column]
        fig.add_trace(go.Scatter(
            x=trace["x"], y=trace["y"], text=trace["text"], mode="text", yaxis=axis, legendgroup=column, showlegend=False,
            name=f"Rótulos · {column}", hoverinfo="skip", connectgaps=False,
            line=dict(color=color, width=.7), textposition="middle center",
            textfont=dict(family="Calibri, Arial, sans-serif", color=color, size=trace["size"],
                          shadow="1px 0 0 white, -1px 0 0 white, 0 1px 0 white, 0 -1px 0 white"),
        ))

    axis_common = dict(
        tickformat=",.0f", separatethousands=True, fixedrange=False,
        zerolinecolor="#dddddd", tickfont=dict(size=12),
        title_font=dict(size=12), showline=False,
    )
    fig.update_layout(
        barmode="group", bargap=.32, bargroupgap=.08, height=480,
        font=dict(family="Calibri, Arial, sans-serif", size=14, color="#333333"),
        separators=",.", plot_bgcolor="white", paper_bgcolor="white",
        yaxis=dict(**axis_common, title="Lucro / PL (R$ bi)", range=ranges["y"], gridcolor="#eeeeee"),
        yaxis2=dict(**axis_common, title="Carteira / funding (R$ bi)", range=ranges["y2"], overlaying="y", side="right", showgrid=False),
        xaxis=dict(type="linear", tickmode="array", tickvals=list(range(len(displayed))), ticktext=displayed,
                   labelalias={str(i): label for i, label in enumerate(displayed)}, range=[-.6, len(labels) - .4], tickfont=dict(size=12)),
        legend=dict(orientation="h", yanchor="bottom", y=1.04, xanchor="left", x=0, font=dict(size=12), groupclick="togglegroup"),
        margin=dict(t=65, b=38, l=68, r=80),
        hovermode="x unified", hoverlabel=dict(bgcolor="white", font=dict(family="Calibri, Arial, sans-serif", size=13)),
        uirevision=revision,
    )
    return fig


def render_evolucao_table(df_show: pd.DataFrame, periods: list[str], cell_tooltips: dict, glossary: dict) -> str:
    """Semantic HTML table: five existing metrics, original values and trace tips."""
    html = """
    <style>
    .evol-table-wrap {width:100%; overflow-x:auto; margin:8px 0 12px;}
    .evol-table {width:100%; border-collapse:separate; border-spacing:0; font-family:Calibri,Arial,sans-serif; font-size:14px; color:#222; font-variant-numeric:tabular-nums;}
    .evol-table th,.evol-table td {padding:9px 12px; border-bottom:1px solid #e5e5e5; white-space:nowrap;}
    .evol-table thead th {background:#EC7000; color:white; font-size:16px; font-weight:700; text-align:center;}
    .evol-table thead th:first-child {text-align:left;}
    .evol-table tbody th {font-weight:400; text-align:left; background:white;}
    .evol-table td {text-align:right; min-width:76px; background:white;}
    .evol-table tr>:first-child {position:sticky; left:0; z-index:1; min-width:215px;}
    .evol-table thead th:first-child {z-index:2;}
    .evol-table td:last-child {font-weight:700;}
    .evol-table .metric-info {margin-left:6px; color:#777; font-size:12px; text-decoration:none; cursor:help;}
    .evol-table td.has-tip {cursor:help;}
    @media (hover:hover) {.evol-table tbody tr:hover th,.evol-table tbody tr:hover td {background:#fafafa;}}
    @media (max-width:600px) {.evol-table th,.evol-table td {padding:8px 9px;} .evol-table tr>:first-child {min-width:190px;}}
    </style>
    <div class="evol-table-wrap" role="region" aria-label="Indicadores de Evolução" tabindex="0">
    <table class="evol-table" aria-label="Indicadores de Evolução"><thead><tr><th scope="col">Indicador</th>
    """
    for period in periods:
        html += f'<th scope="col">{escape(period_label(period))}</th>'
    html += "</tr></thead><tbody>"
    for _, row in df_show.iterrows():
        metric = str(row["Métrica"])
        label = escape(METRIC_LABELS.get(metric, metric))
        gloss = glossary.get(metric, "")
        if gloss:
            label += f'<abbr class="metric-info" title="{escape(gloss, quote=True)}" aria-label="{escape(gloss, quote=True)}">ⓘ</abbr>'
        html += f'<tr><th scope="row">{label}</th>'
        for period in periods:
            tip = str(cell_tooltips.get((metric, str(period)), "") or "").strip()
            attrs = f' class="has-tip" title="{escape(tip, quote=True)}"' if tip else ""
            html += f'<td{attrs}>{escape(str(row[period]))}</td>'
        html += "</tr>"
    return html + "</tbody></table></div>"
