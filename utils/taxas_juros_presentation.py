"""Apresentação e estado das exportações de Taxas, sem transformar a base."""

from __future__ import annotations

import hashlib
from typing import Sequence

import plotly.graph_objects as go
import plotly.io as pio


def figura_taxas_para_exportar(
    figura: go.Figure,
    *,
    titulo: str,
    subtitulo: str,
    diaria: bool = False,
    paineis: bool = False,
) -> go.Figure:
    """Acrescenta contexto a uma cópia da figura efetivamente mostrada."""
    copia = go.Figure(figura)
    copia.update_layout(meta={
        **(figura.layout.meta if isinstance(figura.layout.meta, dict) else {}),
        "chart_title": titulo,
        "subtitulo": subtitulo,
        "source": "Fonte: Banco Central do Brasil · Taxas de Juros / ConsultaUnificada",
        "value_format": "0.00%",
        "value_scale": 0.01,
        "formato_data": "diaria" if diaria else "mensal",
        "separar_paineis": paineis,
    })
    return copia


def assinatura_figuras_taxas(figuras: Sequence[go.Figure]) -> str:
    """Invalida o download se valores, filtros, cores ou contexto mudarem."""
    digest = hashlib.sha256()
    for figura in figuras:
        digest.update(pio.to_json(figura, engine="json").encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def formatar_planilhas_taxas(writer) -> None:
    """Aplica acabamento aos arquivos existentes, mantendo células e abas."""
    workbook = writer.book
    cabecalho = workbook.add_format({
        "font_name": "Calibri", "font_size": 11, "bold": True,
        "font_color": "#FFFFFF", "bg_color": "#20252B",
        "valign": "vcenter", "text_wrap": True,
    })
    contexto_texto = workbook.add_format({
        "font_name": "Calibri", "font_size": 11, "font_color": "#333333",
        "text_wrap": True, "valign": "vcenter",
    })
    for nome, worksheet in writer.sheets.items():
        worksheet.hide_gridlines(2)
        worksheet.set_default_row(21)
        worksheet.set_row(0, 32, cabecalho)
        worksheet.set_tab_color("#EC7000" if nome != "contexto" else "#717171")
        worksheet.set_landscape()
        worksheet.fit_to_pages(1, 0)
        worksheet.repeat_rows(0)
        worksheet.set_margins(0.3, 0.3, 0.4, 0.4)
        if nome == "contexto":
            worksheet.write_row(0, 0, ["Campo", "Valor"], cabecalho)
            worksheet.set_column(0, 0, 25, contexto_texto)
            worksheet.set_column(1, 1, 76, contexto_texto)
            worksheet.set_row(2, 42)
            worksheet.freeze_panes(1, 0)
