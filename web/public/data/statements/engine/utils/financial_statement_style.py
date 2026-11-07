"""Presentation tokens shared by financial tables and native Office exports."""

FONT = "Calibri"
FONT_FAMILY = "Calibri, Arial, sans-serif"
ACCENT = "#EC7000"
INK = "#24282E"
MUTED = "#626970"
GRID = "#E8EAED"
SECTION = "#F3F5F6"
KEY_FILL = "#E9ECEF"
RULE = "#8A9099"
BAND = ACCENT
# Vermelho sobre laranja não se lê: na faixa, o negativo fica branco e leva o sinal.
BAND_NEGATIVE = "#FFFFFF"
BAND_MUTED = "#FFE3CC"
NEGATIVE = "#B32624"
MISSING = "–"
LABEL_MAX_PX = 320
LABEL_MOBILE_PX = 170
AMOUNT_PX = 84
PERCENT_PX = 46
PERIOD_MAX_PX = 340
SLIDE_WIDTH, SLIDE_HEIGHT = 13.333, 7.5
SLIDE_MARGIN, SLIDE_CONTENT = .42, 12.493

EXCEL_STYLES = {
    "body": {}, "bold": {"bold": True}, "indent": {"indent": 1},
    "detail": {"indent": 2, "italic": True, "font_size": 9, "font_color": MUTED},
    "ratio": {"italic": True},
    "title": {"bold": True, "font_size": 14},
    "header": {"bold": True, "bg_color": BAND, "font_color": "#FFFFFF", "align": "center"},
    "source": {"font_size": 9, "font_color": MUTED, "align": "center", "bottom": 1, "bottom_color": GRID},
    "section": {"bold": True, "bg_color": SECTION},
    "total": {"bold": True, "bg_color": SECTION, "top": 1, "top_color": RULE},
    "key": {"bold": True, "bg_color": BAND, "font_color": "#FFFFFF"},
    "band": {"bold": True, "bg_color": BAND, "font_color": "#FFFFFF"},
    "note": {"font_size": 9, "font_color": MUTED, "text_wrap": True},
    "technical": {"font_size": 8, "font_color": MUTED},
}


def label_width(labels) -> int:
    """Approximate Calibri glyph advances, bounded for desktop and mobile."""
    widths = [sum(3.5 if c in " ilI.,:;|" else 9 if c in "MWmw" else 6.8 for c in label) + 40
              for label in labels]
    return min(LABEL_MAX_PX, max(220, round(max(widths, default=220))))


def excel_label_width(labels, *, ceiling=46) -> float:
    """Excel column width that holds the longest label, bold totals included."""
    return min(ceiling, max(24, max((len(label) for label in labels), default=24) * .86 + 2))


def excel_amount_width(values) -> float:
    """Room for the largest amount in pt-BR notation, with sign and bold weight."""
    largest = max((abs(v) for v in values if isinstance(v, (int, float))), default=0)
    digits = len(f"{largest:,.0f}")
    return max(7.5, digits * .9 + 1.6)


def excel_visible_format(value):
    """Negatives take the brand's red through rules; an unavailable value prints as a dash."""
    if not value:
        return value
    sections = value.replace("[Red]", "").split(";")
    sections = (sections + sections[:1] * 3)[:3] if len(sections) < 3 else sections
    if len(value.split(";")) == 1:
        sections = [value, "-" + value, value]
    return excel_number_format(";".join(sections) + ';"' + MISSING + '"')


def excel_number_format(value):
    # OOXML stores invariant separators; the locale tag selects Brazilian display.
    if not value or "[$-" in value:
        return value
    return "[$-416]" + value
