"""Presentation tokens shared by financial tables and native Office exports."""

FONT = "Calibri"
FONT_FAMILY = "Calibri, Arial, sans-serif"
ACCENT = "#EC7000"
INK = "#24282E"
MUTED = "#626970"
GRID = "#E8EAED"
SECTION = "#F3F5F6"
NEGATIVE = "#B32624"
LABEL_MAX_PX = 320
LABEL_MOBILE_PX = 210
SLIDE_WIDTH, SLIDE_HEIGHT = 13.333, 7.5
SLIDE_MARGIN, SLIDE_CONTENT = .42, 12.493

EXCEL_STYLES = {
    "body": {}, "bold": {"bold": True}, "indent": {"indent": 1},
    "detail": {"indent": 2, "italic": True, "font_size": 10},
    "ratio": {"italic": True},
    "title": {"bold": True, "font_size": 18},
    "header": {"bold": True, "bg_color": ACCENT, "font_color": "#FFFFFF", "align": "center"},
    "source": {"font_size": 10, "font_color": MUTED, "align": "center", "bottom": 1, "bottom_color": GRID},
    "section": {"bold": True, "bg_color": SECTION},
    "total": {"bold": True, "bg_color": SECTION, "top": 1, "top_color": GRID, "bottom": 1, "bottom_color": GRID},
    "note": {"font_size": 9, "font_color": MUTED, "text_wrap": True},
    "technical": {"font_size": 8, "font_color": MUTED},
}


def label_width(labels) -> int:
    """Approximate Calibri glyph advances, bounded for desktop and mobile."""
    widths = [sum(3.5 if c in " ilI.,:;|" else 9 if c in "MWmw" else 6.8 for c in label) + 40
              for label in labels]
    return min(LABEL_MAX_PX, max(220, round(max(widths, default=220))))


def excel_number_format(value):
    # OOXML stores invariant separators; the locale tag selects Brazilian display.
    if not value or "[$-" in value:
        return value
    return "[$-416]" + value
