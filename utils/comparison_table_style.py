"""Paleta e tipografia das tabelas de peers e da Carteira 4.966."""

HEADER_BACKGROUND = "#EC7000"
SECTION_BACKGROUND = "#ECEFF1"
LINE_COLOR = "#DEDEDE"
FONT_FAMILY = "Calibri,Arial,sans-serif"

VARIATION_COLORS = {"favorable": "#16713B", "attention": "#B32624", "neutral": "#666666"}


def credit_variation_tone(direction, favorable_direction, *, reliable=True):
    """Cor da direção usual de crédito; valores contextuais ou alertados ficam neutros."""
    if not reliable or direction not in {"up", "down"} or favorable_direction is None:
        return "neutral"
    return "favorable" if direction == favorable_direction else "attention"
