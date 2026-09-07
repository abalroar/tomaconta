from __future__ import annotations

from io import BytesIO
from math import ceil, floor, log10
from typing import Mapping, Sequence

import pandas as pd
import plotly.graph_objects as go


ITAU_BBA_PALETTE = {
    "Pix": "#EC7000",
    "TED": "#111111",
    "Boleto": "#6F6F6F",
    "Cheque": "#B8B8B8",
    "DOC": "#7E3F98",
    "TEC": "#F4C542",
    "Cartão de Crédito": "#003A70",
    "Cartão de Débito": "#1F77B4",
    "Cartão Pré-Pago": "#63A8E2",
    "Transferências Intrabancárias": "#4B4B4B",
    "Convênios": "#F7A35C",
    "Débito Direto": "#9A9A9A",
    "Saques": "#5B2C6F",
    "Cobranças": "#6F6F6F",
    "Cartões": "#003A70",
    "Transferências Interbancárias": "#111111",
}

SPB_INSTRUMENTOS_LABEL = {
    "pix": "Pix",
    "ted": "TED",
    "tec": "TEC",
    "cheque": "Cheque",
    "boleto": "Boleto",
    "doc": "DOC",
    "cartao_credito": "Cartão de Crédito",
    "cartao_debito": "Cartão de Débito",
    "cartao_pre_pago": "Cartão Pré-Pago",
    "trans_intrabancaria": "Transferências Intrabancárias",
    "convenios": "Convênios",
    "debito_direto": "Débito Direto",
    "saques": "Saques",
}

SPB_CONSOLIDADO_MAPA = {
    "Pix": "Pix",
    "Saques": "Saques",
    "Boleto": "Cobranças",
    "Convênios": "Cobranças",
    "Débito Direto": "Cobranças",
    "Cartão de Crédito": "Cartões",
    "Cartão de Débito": "Cartões",
    "Cartão Pré-Pago": "Cartões",
    "TED": "Transferências Interbancárias",
    "DOC": "Transferências Interbancárias",
    "TEC": "Transferências Interbancárias",
    "Cheque": "Cheque",
    "Transferências Intrabancárias": "Transferências Intrabancárias",
}

MONTHLY_DEFAULT_INSTRUMENTS = ["Pix", "TED", "Boleto", "Cheque", "TEC", "DOC"]
QUARTERLY_DEFAULT_INSTRUMENTS = [
    "Pix",
    "TED",
    "Boleto",
    "Cheque",
    "Cartão de Crédito",
    "Cartão de Débito",
    "Cartão Pré-Pago",
]

_MONTHS_ABBR = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def format_ano_mes_label(value) -> str:
    s = str(value)
    if len(s) == 6 and s.isdigit():
        return f"{s[4:6]}-{s[:4]}"
    try:
        dt = pd.Timestamp(value)
        if not pd.isna(dt):
            return f"{dt.month:02d}-{dt.year}"
    except Exception:
        pass
    return s


def format_trimestre_label(value) -> str:
    dt = _period_to_timestamp(value, "trimestral")
    if pd.isna(dt):
        return str(value)
    return f"{_MONTHS_ABBR[dt.month - 1]}-{str(dt.year)[-2:]}"


def _period_to_timestamp(value, periodicidade: str) -> pd.Timestamp:
    s = str(value)
    if periodicidade == "mensal":
        if len(s) == 6 and s.isdigit():
            return pd.Timestamp(year=int(s[:4]), month=int(s[4:6]), day=1)
        return pd.Timestamp(value)

    if len(s) == 5 and s.isdigit():
        quarter = int(s[4])
        return pd.Timestamp(year=int(s[:4]), month=quarter * 3, day=1)
    dt = pd.Timestamp(value)
    quarter_month = ((dt.month - 1) // 3 + 1) * 3
    return pd.Timestamp(year=dt.year, month=quarter_month, day=1)


def melt_nucleo_spb(df: pd.DataFrame, periodo_col: str, periodicidade: str) -> pd.DataFrame:
    columns = ["periodo", "periodo_ordem", "periodo_label", "instrumento", "tipo", "valor"]
    if df.empty or periodo_col not in df.columns:
        return pd.DataFrame(columns=columns)

    rows = []
    for prefix, tipo in (("valor_", "Valor (R$ milhão)"), ("quantidade_", "Quantidade (mil)")):
        value_cols = [col for col in df.columns if col.startswith(prefix)]
        for col in value_cols:
            suffix = col[len(prefix):]
            part = df[[periodo_col, col]].copy()
            part.columns = ["periodo", "valor"]
            part["instrumento"] = SPB_INSTRUMENTOS_LABEL.get(suffix, suffix)
            part["tipo"] = tipo
            rows.append(part)

    if not rows:
        return pd.DataFrame(columns=columns)

    long_df = pd.concat(rows, ignore_index=True)
    long_df["valor"] = pd.to_numeric(long_df["valor"], errors="coerce")
    long_df["periodo_ordem"] = long_df["periodo"].map(lambda value: _period_to_timestamp(value, periodicidade))
    if periodicidade == "mensal":
        long_df["periodo_label"] = long_df["periodo"].map(format_ano_mes_label)
    else:
        long_df["periodo_label"] = long_df["periodo"].map(format_trimestre_label)
    return long_df.dropna(subset=["valor", "periodo_ordem"]).sort_values(["periodo_ordem", "instrumento"])


def period_options(long_df: pd.DataFrame) -> list[pd.Timestamp]:
    if long_df.empty:
        return []
    return (
        long_df[["periodo_ordem"]]
        .drop_duplicates()
        .sort_values("periodo_ordem")["periodo_ordem"]
        .tolist()
    )


def period_label_map(long_df: pd.DataFrame) -> dict[pd.Timestamp, str]:
    if long_df.empty:
        return {}
    labels = (
        long_df[["periodo_ordem", "periodo_label"]]
        .drop_duplicates()
        .sort_values("periodo_ordem")
    )
    return dict(zip(labels["periodo_ordem"], labels["periodo_label"]))


def filter_period_range(long_df: pd.DataFrame, start_period, end_period) -> pd.DataFrame:
    if long_df.empty:
        return long_df.copy()
    return long_df[
        (long_df["periodo_ordem"] >= pd.Timestamp(start_period))
        & (long_df["periodo_ordem"] <= pd.Timestamp(end_period))
    ].copy()


def available_instruments(long_df: pd.DataFrame) -> list[str]:
    if long_df.empty:
        return []
    return sorted(long_df["instrumento"].dropna().unique().tolist(), key=lambda x: _instrument_sort_key(x))


def default_start_index(periods: Sequence[pd.Timestamp], periodicidade: str) -> int:
    if not periods:
        return 0
    cutoff = pd.Timestamp("2020-11-01") if periodicidade == "mensal" else pd.Timestamp("2020-12-01")
    for idx, period in enumerate(periods):
        if pd.Timestamp(period) >= cutoff:
            return idx
    return max(0, len(periods) - 24)


def compute_share(long_df: pd.DataFrame, tipo: str, instruments: Sequence[str]) -> pd.DataFrame:
    df = long_df[(long_df["tipo"] == tipo) & (long_df["instrumento"].isin(instruments))].copy()
    if df.empty:
        return df.assign(participacao=pd.Series(dtype="float64"))
    totals = df.groupby("periodo_ordem", as_index=False)["valor"].sum().rename(columns={"valor": "total_periodo"})
    df = df.merge(totals, on="periodo_ordem", how="left")
    df["participacao"] = df["valor"] / df["total_periodo"].replace(0, pd.NA) * 100
    return df.dropna(subset=["participacao"]).sort_values(["periodo_ordem", "instrumento"])


def latest_summary(long_df: pd.DataFrame, tipo: str, instruments: Sequence[str]) -> pd.DataFrame:
    share_df = compute_share(long_df, tipo, instruments)
    if share_df.empty:
        return pd.DataFrame(columns=["Período", "Instrumento", "Valor", "Participação"])
    latest_period = share_df["periodo_ordem"].max()
    latest = share_df[share_df["periodo_ordem"] == latest_period].copy()
    latest = latest.sort_values("participacao", ascending=False)
    return pd.DataFrame(
        {
            "Período": latest["periodo_label"],
            "Instrumento": latest["instrumento"],
            "Valor": latest["valor"],
            "Participação": latest["participacao"],
        }
    )


def build_line_figure(
    long_df: pd.DataFrame,
    *,
    tipo: str,
    instruments: Sequence[str],
    title: str,
    yaxis_title: str,
    palette: Mapping[str, str] | None = None,
) -> go.Figure:
    palette = palette or ITAU_BBA_PALETTE
    fig = go.Figure()
    df = long_df[(long_df["tipo"] == tipo) & (long_df["instrumento"].isin(instruments))].copy()
    x_order = _x_order(df)

    for instrument in instruments:
        series = df[df["instrumento"] == instrument].sort_values("periodo_ordem")
        if series.empty:
            continue
        text = [""] * len(series)
        valid_indices = [index for index, value in enumerate(series["valor"]) if pd.notna(value)]
        if valid_indices:
            last_index = valid_indices[-1]
            text[last_index] = _format_value(series.iloc[last_index]["valor"], tipo)
        color = palette.get(instrument, "#4B5563")
        fig.add_trace(
            go.Scatter(
                x=series["periodo_label"],
                y=series["valor"],
                mode="lines+markers",
                name=instrument,
                text=text,
                textposition="middle right",
                textfont=dict(color=color, size=11),
                line=dict(color=color, width=2.4),
                marker=dict(color=color, size=4 if len(series) <= 24 else 2.5),
                cliponaxis=False,
                hovertemplate=f"<b>%{{fullData.name}}</b><br>%{{x}}<br>%{{y:,.2f}} {yaxis_title}<extra></extra>",
            )
        )

    _apply_base_layout(fig, title, yaxis_title, x_order)
    _add_latest_labels(fig)
    return fig


def build_share_figure(
    long_df: pd.DataFrame,
    *,
    tipo: str,
    instruments: Sequence[str],
    title: str,
    palette: Mapping[str, str] | None = None,
) -> go.Figure:
    palette = palette or ITAU_BBA_PALETTE
    fig = go.Figure()
    share_df = compute_share(long_df, tipo, instruments)
    x_order = _x_order(share_df)

    for instrument in instruments:
        series = share_df[share_df["instrumento"] == instrument].sort_values("periodo_ordem")
        if series.empty:
            continue
        text = [""] * len(series)
        text[-1] = f"{series.iloc[-1]['participacao']:.1f}%".replace(".", ",")
        color = palette.get(instrument, "#4B5563")
        fig.add_trace(
            go.Scatter(
                x=series["periodo_label"],
                y=series["participacao"],
                mode="lines+markers",
                name=instrument,
                text=text,
                textposition="middle right",
                textfont=dict(color=color, size=11),
                line=dict(color=color, width=2.3),
                marker=dict(color=color, size=4 if len(series) <= 24 else 2.5),
                cliponaxis=False,
                hovertemplate="<b>%{fullData.name}</b><br>%{x}<br>%{y:.1f}%<extra></extra>",
            )
        )

    _apply_base_layout(fig, title, "% do total selecionado", x_order)
    fig.update_yaxes(range=[0, 100], ticksuffix="%", tickformat=".0f")
    _add_latest_labels(fig, value_range=(0, 100))
    return fig


def style_spb_figure(
    fig: go.Figure, *, title: str, yaxis_title: str, series_order: Sequence[str] | None = None,
    period_order: Sequence[str] | None = None,
) -> go.Figure:
    """Apply SPB presentation styling to an existing chart without changing its data."""
    x_order = list(period_order) if period_order is not None else list(dict.fromkeys(value for trace in fig.data for value in trace.x))
    colors = ["#EC7000", "#003A70", "#6F6F6F", "#7E3F98", "#1F77B4", "#4B4B4B", "#A85517"]
    series_order = list(series_order or [trace.name for trace in fig.data])
    for index, trace in enumerate(fig.data):
        color_index = series_order.index(trace.name) if trace.name in series_order else index
        color = ITAU_BBA_PALETTE.get(trace.name, colors[color_index % len(colors)])
        trace.update(
            line=dict(color=color, width=2.3),
            marker=dict(color=color, size=4 if len(trace.x) <= 24 else 2.5),
            hovertemplate=f"<b>%{{fullData.name}}</b><br>%{{x}}<br>%{{y:,.2f}} {yaxis_title}<extra></extra>",
        )
    _apply_base_layout(fig, title, yaxis_title, x_order)
    if yaxis_title == "%":
        fig.update_yaxes(ticksuffix="%", tickformat=".2f")
    return fig


def build_spb_pptx(
    *,
    title: str,
    figures: Mapping[str, bytes | None],
    summaries: Mapping[str, pd.DataFrame],
    source_note: str,
) -> bytes:
    missing = [chart_title for chart_title, png in figures.items() if not png]
    if missing:
        missing_list = ", ".join(missing)
        raise RuntimeError(
            "Exportação SPB legada baseada em imagem recebeu gráfico vazio. "
            "Use build_spb_native_pptx para gerar charts nativos do PowerPoint. "
            f"Gráficos ausentes: {missing_list}"
        )

    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    def add_title(slide, text: str, top: float = 0.28):
        box = slide.shapes.add_textbox(Inches(0.45), Inches(top), Inches(12.2), Inches(0.38))
        frame = box.text_frame
        frame.clear()
        p = frame.paragraphs[0]
        p.text = text
        p.font.size = Pt(18)
        p.font.bold = True
        p.font.color.rgb = RGBColor(17, 17, 17)
        return box

    def add_footer(slide):
        box = slide.shapes.add_textbox(Inches(0.45), Inches(7.05), Inches(12.0), Inches(0.22))
        p = box.text_frame.paragraphs[0]
        p.text = source_note
        p.font.size = Pt(7.5)
        p.font.color.rgb = RGBColor(105, 105, 105)

    blank = prs.slide_layouts[6]
    cover = prs.slides.add_slide(blank)
    cover.background.fill.solid()
    cover.background.fill.fore_color.rgb = RGBColor(255, 255, 255)
    accent = cover.shapes.add_shape(1, Inches(0), Inches(0), Inches(0.12), Inches(7.5))
    accent.fill.solid()
    accent.fill.fore_color.rgb = RGBColor(236, 112, 0)
    accent.line.fill.background()
    title_box = cover.shapes.add_textbox(Inches(0.55), Inches(2.45), Inches(11.8), Inches(0.8))
    p = title_box.text_frame.paragraphs[0]
    p.text = title
    p.font.size = Pt(30)
    p.font.bold = True
    p.font.color.rgb = RGBColor(17, 17, 17)
    sub = cover.shapes.add_textbox(Inches(0.58), Inches(3.35), Inches(10.8), Inches(0.55))
    p = sub.text_frame.paragraphs[0]
    p.text = "Banco Central do Brasil | MPV_DadosAbertos"
    p.font.size = Pt(14)
    p.font.color.rgb = RGBColor(85, 85, 85)
    add_footer(cover)

    for chart_title, png in figures.items():
        slide = prs.slides.add_slide(blank)
        add_title(slide, chart_title)
        slide.shapes.add_picture(BytesIO(png), Inches(0.45), Inches(0.85), width=Inches(12.25), height=Inches(5.85))
        add_footer(slide)

    slide = prs.slides.add_slide(blank)
    add_title(slide, "Última composição disponível")
    left = 0.55
    for section, df in summaries.items():
        box = slide.shapes.add_textbox(Inches(left), Inches(0.95), Inches(5.9), Inches(5.85))
        frame = box.text_frame
        frame.clear()
        header = frame.paragraphs[0]
        header.text = section
        header.font.bold = True
        header.font.size = Pt(13)
        header.font.color.rgb = RGBColor(236, 112, 0)
        for _, row in df.head(12).iterrows():
            p = frame.add_paragraph()
            value_label = _format_value(row["Valor"], "Valor (R$ milhão)" if "Valor" in section else "Quantidade (mil)")
            share_label = f"{row['Participação']:.1f}".replace(".", ",")
            p.text = f"{row['Instrumento']}: {value_label} ({share_label}%)"
            p.font.size = Pt(9.5)
            p.font.color.rgb = RGBColor(35, 35, 35)
        left += 6.25
    add_footer(slide)

    output = BytesIO()
    prs.save(output)
    return output.getvalue()


def build_spb_native_pptx(
    *,
    title: str,
    charts: Sequence[Mapping[str, object]],
    summaries: Mapping[str, pd.DataFrame],
    source_note: str,
) -> bytes:
    from pptx import Presentation
    from pptx.chart.data import ChartData
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_MARKER_STYLE
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.oxml.xmlchemy import OxmlElement
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    def rgb(hex_color: str) -> RGBColor:
        value = hex_color.lstrip("#")
        return RGBColor(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))

    def text_box(slide, text, left, top, width, height, size, color="#111111", bold=False):
        box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
        frame = box.text_frame
        frame.clear()
        frame.word_wrap = True
        frame.margin_left = frame.margin_right = Inches(0)
        frame.margin_top = frame.margin_bottom = Inches(0)
        p = frame.paragraphs[0]
        p.text = text
        p.font.name = "Arial"
        p.font.size = Pt(size)
        p.font.bold = bold
        p.font.color.rgb = rgb(color)
        return box

    def add_title(slide, text: str):
        text_box(slide, text, 0.5, 0.28, 12.3, 0.5, 23, bold=True)

    def add_footer(slide):
        text_box(slide, source_note, 0.5, 7.02, 11.9, 0.32, 9, "#6F6F6F")
        text_box(slide, str(len(prs.slides)), 12.6, 7.02, 0.25, 0.22, 9, "#6F6F6F")

    def add_cover():
        slide = prs.slides.add_slide(blank)
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = rgb("#FFFFFF")
        accent = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(0.12), Inches(7.5))
        accent.fill.solid()
        accent.fill.fore_color.rgb = rgb("#EC7000")
        accent.line.fill.background()
        text_box(slide, title, 0.6, 2.4, 11.8, 1.0, 32, bold=True)
        text_box(slide, "Banco Central do Brasil | MPV_DadosAbertos", 0.62, 3.5, 11.5, 0.5, 16, "#EC7000")
        add_footer(slide)

    def add_latest_strip(slide, latest_items):
        text_box(slide, "Último ponto disponível", 9.9, 1.35, 2.95, 0.35, 13, bold=True)
        for index, item in enumerate(latest_items):
            top = 1.88 + index * 0.66
            text_box(slide, str(item["instrumento"]), 9.9, top, 2.95, 0.36, 11.5, str(item["color"]))
            text_box(slide, f"{item['label']}  |  {item['periodo_label']}", 9.9, top + 0.34, 2.95, 0.25, 11.5, str(item["color"]), True)

    def add_chart_slides(spec: Mapping[str, object]):
        instruments = list(spec["instruments"])
        share = bool(spec.get("share", False))
        categories, series_payload, latest_items = _native_chart_payload(
            spec["long_df"], tipo=str(spec["tipo"]), instruments=instruments,
            share=share, palette=spec.get("palette") or ITAU_BBA_PALETTE,
        )
        chart_title = str(spec["title"])
        if not categories or not series_payload:
            slide = prs.slides.add_slide(blank)
            add_title(slide, chart_title)
            text_box(slide, "Sem dados disponíveis para a janela selecionada.", 0.8, 2.7, 11.6, 0.5, 17, "#6F6F6F")
            add_footer(slide)
            return

        # Calculate all series first, so pagination preserves the selected-share denominator.
        pages = ceil(len(series_payload) / 7)
        full_values = [value for _, values, _ in series_payload for value in values if value is not None]
        lower, upper = min(full_values), max(full_values)
        for page in range(pages):
            page_series = series_payload[page * 7:(page + 1) * 7]
            page_latest = latest_items[page * 7:(page + 1) * 7]
            slide = prs.slides.add_slide(blank)
            page_suffix = f" ({page + 1}/{pages})" if pages > 1 else ""
            add_title(slide, chart_title + page_suffix)
            subtitle = f"{categories[0]} a {categories[-1]} | {spec.get('yaxis_title', '')}"
            if share:
                subtitle += f" | Base: {len(instruments)} instrumentos selecionados"
            text_box(slide, subtitle, 0.5, 0.87, 12.3, 0.35, 12, "#EC7000")

            chart_data = ChartData()
            chart_data.categories = categories
            for series_name, values, _color in page_series:
                chart_data.add_series(series_name, values)
            frame = slide.shapes.add_chart(
                XL_CHART_TYPE.LINE_MARKERS if len(categories) <= 24 else XL_CHART_TYPE.LINE,
                Inches(0.5), Inches(1.35), Inches(9.0), Inches(5.3), chart_data,
            )
            chart = frame.chart
            chart.font.name = "Arial"
            chart.font.size = Pt(11)
            chart.has_legend = True
            chart.legend.position = XL_LEGEND_POSITION.BOTTOM
            chart.legend.include_in_layout = False
            chart.legend.font.size = Pt(10)
            chart.value_axis.has_title = False
            chart.value_axis.has_major_gridlines = True
            chart.value_axis.major_gridlines.format.line.color.rgb = rgb("#E6E6E6")
            chart.value_axis.major_gridlines.format.line.width = Pt(0.5)
            chart.value_axis.tick_labels.number_format = "0%" if share else "#,##0"
            chart.value_axis.minimum_scale = 0 if share or lower >= 0 else lower * 1.05
            chart.value_axis.maximum_scale = 1 if share else max(upper * 1.08, 1)
            for axis in (chart.category_axis, chart.value_axis):
                axis.tick_labels.font.name = "Arial"
                axis.tick_labels.font.size = Pt(11)
                axis.tick_labels.font.color.rgb = rgb("#6F6F6F")
                axis.format.line.color.rgb = rgb("#DDDDDD")
            # Keep every embedded observation, and show fewer labels on the category axis.
            for element_name in ("tickLblSkip", "tickMarkSkip"):
                element = OxmlElement(f"c:{element_name}")
                element.set("val", str(max(1, ceil(len(categories) / 9))))
                chart.category_axis._element.append(element)
            for index, series in enumerate(chart.series):
                color = rgb(page_series[index][2])
                series.format.line.color.rgb = color
                series.format.line.width = Pt(2.1)
                series.marker.style = XL_MARKER_STYLE.CIRCLE if len(categories) <= 24 else XL_MARKER_STYLE.NONE
                series.marker.size = 4
                series.marker.format.fill.solid()
                series.marker.format.fill.fore_color.rgb = color
                series.marker.format.line.color.rgb = color
            add_latest_strip(slide, page_latest)
            add_footer(slide)

    def add_summary_slides():
        # Two native tables per slide, with continuation pages when all rows do not fit.
        sections = list(summaries.items())
        if not sections:
            return
        rows_per_page = 8
        for section_offset in range(0, len(sections), 2):
            pair = sections[section_offset:section_offset + 2]
            pages = max(1, max(ceil(len(df) / rows_per_page) for _, df in pair))
            for page in range(pages):
                slide = prs.slides.add_slide(blank)
                suffix = f" ({page + 1}/{pages})" if pages > 1 else ""
                add_title(slide, "Última composição disponível" + suffix)
                for column, (section, df) in enumerate(pair):
                    left = 0.5 + column * 6.2
                    rows = df.iloc[page * rows_per_page:(page + 1) * rows_per_page]
                    periods = ", ".join(dict.fromkeys(str(value) for value in rows.get("Período", [])))
                    text_box(slide, f"{section}{' | ' + periods if periods else ''}", left, 0.98, 5.8, 0.4, 14, "#EC7000", True)
                    if rows.empty:
                        text_box(slide, "Sem linhas adicionais.", left, 1.6, 5.8, 0.4, 12, "#6F6F6F")
                        continue
                    shape = slide.shapes.add_table(len(rows) + 1, 3, Inches(left), Inches(1.55), Inches(5.85), Inches(0.5 * (len(rows) + 1)))
                    table = shape.table
                    for index, width in enumerate((3.0, 1.75, 1.1)):
                        table.columns[index].width = Inches(width)
                    values = [["Instrumento", "R$ milhão" if "Valor" in section else "mil transações", "% selecionado"]]
                    for _, row in rows.iterrows():
                        values.append([
                            str(row["Instrumento"]),
                            _format_value(row["Valor"], "Quantidade (mil)"),
                            f"{row['Participação']:.1f}%".replace(".", ","),
                        ])
                    for row_index, row_values in enumerate(values):
                        for col_index, value in enumerate(row_values):
                            cell = table.cell(row_index, col_index)
                            cell.text = value
                            cell.margin_left = cell.margin_right = Inches(0.09)
                            cell.margin_top = cell.margin_bottom = Inches(0.06)
                            cell.fill.solid()
                            cell.fill.fore_color.rgb = rgb("#222222" if row_index == 0 else ("#F3F3F3" if row_index % 2 else "#FFFFFF"))
                            for p in cell.text_frame.paragraphs:
                                p.font.name = "Arial"
                                p.font.size = Pt(11 if row_index == 0 else 12)
                                p.font.bold = row_index == 0
                                p.font.color.rgb = rgb("#FFFFFF" if row_index == 0 else "#333333")
                add_footer(slide)

    add_cover()
    for chart_spec in charts:
        add_chart_slides(chart_spec)
    add_summary_slides()
    output = BytesIO()
    prs.save(output)
    return output.getvalue()

def _apply_base_layout(fig: go.Figure, title: str, yaxis_title: str, x_order: Sequence[str]) -> None:
    legend_rows = max(1, ceil(len(fig.data) / 3))
    tick_step = max(1, ceil(len(x_order) / 8))
    ticks = list(x_order)[::tick_step]
    if x_order and x_order[-1] not in ticks:
        ticks.append(x_order[-1])
    magnitudes = [abs(float(value)) for trace in fig.data for value in trace.y if pd.notna(value)]
    max_magnitude = max(magnitudes, default=0)
    decimals = max(0, min(8, 1 - floor(log10(max_magnitude)))) if max_magnitude else 0
    fig.update_layout(
        title=dict(text=title, x=0, xanchor="left", font=dict(size=16, color="#111111")),
        height=440 + 20 * legend_rows,
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="IBM Plex Sans, Arial", size=12, color="#333333"),
        separators=",.",
        hovermode="x unified",
        hoverlabel=dict(bgcolor="white", font_size=12),
        legend=dict(
            orientation="h", yanchor="top", y=-0.19, xanchor="left", x=0,
            title_text="", font=dict(size=11), entrywidth=175, entrywidthmode="pixels",
            groupclick="togglegroup",
        ),
        margin=dict(l=54, r=90, t=58, b=68 + 22 * legend_rows),
        xaxis=dict(
            title="",
            type="category",
            categoryorder="array",
            categoryarray=list(x_order),
            tickmode="array",
            tickvals=ticks,
            ticktext=ticks,
            tickangle=0,
            tickfont=dict(size=11, color="#6F6F6F"),
            showgrid=False,
            showline=True,
            linecolor="#DDDDDD",
            automargin=True,
        ),
        yaxis=dict(
            title=dict(text=yaxis_title, font=dict(size=11, color="#6F6F6F")),
            tickfont=dict(size=11, color="#6F6F6F"), tickformat=f",.{decimals}f",
            gridcolor="#ECECEC", zerolinecolor="#D8D8D8", automargin=True,
        ),
    )


def _add_latest_labels(fig: go.Figure, value_range: tuple[float, float] | None = None) -> None:
    """Separate final-value labels in screen space; never move the series points."""
    items = []
    for trace in fig.data:
        valid_indices = [index for index, value in enumerate(trace.y) if pd.notna(value)]
        if valid_indices:
            index = valid_indices[-1]
            items.append((trace, index, float(trace.y[index])))
    if not items:
        return
    all_values = [float(value) for trace, _, _ in items for value in trace.y if pd.notna(value)]
    lower, upper = value_range or (min(all_values), max(all_values))
    span = upper - lower or max(abs(upper), 1)
    plot_height = fig.layout.height - fig.layout.margin.t - fig.layout.margin.b
    positioned = []
    for trace, last_index, value in sorted(items, key=lambda item: item[2]):
        desired = (value - lower) / span * plot_height
        position = max(desired, positioned[-1][3] + 16) if positioned else desired
        positioned.append((trace, last_index, desired, position))
    ceiling = plot_height
    for index in range(len(positioned) - 1, -1, -1):
        trace, last_index, desired, position = positioned[index]
        position = min(position, ceiling)
        positioned[index] = (trace, last_index, desired, position)
        ceiling = position - 16
    for trace, last_index, desired, position in positioned:
        trace.legendgroup = trace.name
        # A text-only trace follows its series when the legend hides a group.
        # Only this label's display position moves; the measurement trace is untouched.
        fig.add_trace(go.Scatter(
            x=[trace.x[last_index]], y=[lower + position / plot_height * span],
            mode="text", text=[" " + trace.text[last_index]], textposition="middle right",
            textfont=dict(color=trace.line.color, size=11),
            legendgroup=trace.name, showlegend=False, hoverinfo="skip", cliponaxis=False,
            meta={"spb_label_only": True},
        ))


def _x_order(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return []
    return (
        df[["periodo_ordem", "periodo_label"]]
        .drop_duplicates()
        .sort_values("periodo_ordem")["periodo_label"]
        .tolist()
    )


def _native_chart_payload(
    long_df: pd.DataFrame,
    *,
    tipo: str,
    instruments: Sequence[str],
    share: bool,
    palette: Mapping[str, str],
) -> tuple[list[str], list[tuple[str, tuple[float | None, ...], str]], list[dict[str, object]]]:
    if share:
        df = compute_share(long_df, tipo, instruments)
        value_col = "participacao"
    else:
        df = long_df[(long_df["tipo"] == tipo) & (long_df["instrumento"].isin(instruments))].copy()
        value_col = "valor"
    if df.empty:
        return [], [], []

    order = (
        df[["periodo_ordem", "periodo_label"]]
        .drop_duplicates()
        .sort_values("periodo_ordem")
    )
    categories = order["periodo_label"].tolist()
    payload: list[tuple[str, tuple[float | None, ...], str]] = []
    latest_items: list[dict[str, object]] = []

    for instrument in instruments:
        series = df[df["instrumento"] == instrument].sort_values("periodo_ordem")
        if series.empty:
            continue
        valid_series = series.dropna(subset=[value_col])
        if valid_series.empty:
            continue
        by_label = series.set_index("periodo_label")[value_col]
        values = []
        for label in categories:
            value = by_label.get(label, None)
            if value is None or pd.isna(value):
                values.append(None)
            else:
                number = float(value) / 100 if share else float(value)
                values.append(number)
        color = palette.get(instrument, "#4B5563")
        payload.append((instrument, tuple(values), color))

        latest = valid_series.iloc[-1]
        latest_value = float(latest[value_col])
        latest_items.append(
            {
                "instrumento": instrument,
                "color": color,
                "periodo_label": str(latest["periodo_label"]),
                "label": f"{latest_value:.1f}%".replace(".", ",") if share else _format_value(latest_value, tipo),
            }
        )

    return categories, payload, latest_items


def _instrument_sort_key(instrument: str) -> tuple[int, str]:
    preferred = [
        "Pix",
        "TED",
        "Boleto",
        "Cheque",
        "TEC",
        "DOC",
        "Cartão de Crédito",
        "Cartão de Débito",
        "Cartão Pré-Pago",
        "Saques",
        "Convênios",
        "Débito Direto",
        "Transferências Intrabancárias",
    ]
    try:
        return (preferred.index(instrument), instrument)
    except ValueError:
        return (999, instrument)


def _format_value(value: float, tipo: str) -> str:
    if pd.isna(value):
        return ""
    formatted = f"{float(value):,.0f}".replace(",", ".")
    if tipo == "Valor (R$ milhão)":
        return f"R$ {formatted}"
    return formatted
