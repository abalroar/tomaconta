"""Exporta os cards Plotly do módulo SGS como gráficos Office nativos."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Sequence

import pandas as pd

from .scr_pptx_export import exportar_paineis_pptx
from .sgs_credit_analytics import ITAU_MID_GRAY, ITAU_PALETTE


def _titulo(fig: Any) -> str:
    meta = fig.layout.meta if isinstance(fig.layout.meta, dict) else {}
    candidato = meta.get("chart_title")
    if isinstance(candidato, str) and candidato.strip():
        return candidato.strip()
    texto = getattr(getattr(fig.layout, "title", None), "text", None)
    if isinstance(texto, str) and texto.strip() and texto.strip().lower() != "undefined":
        return texto.strip()
    return "Gráfico"


def _cor_trace(trace: Any, posicao: int) -> str:
    linha = getattr(getattr(trace, "line", None), "color", None)
    marcador = getattr(getattr(trace, "marker", None), "color", None)
    cor = linha or marcador
    if isinstance(cor, str) and cor.startswith("#"):
        return cor
    return ITAU_PALETTE[posicao % len(ITAU_PALETTE)]


def _formato_e_escala(fig: Any) -> tuple[str, float]:
    meta = fig.layout.meta if isinstance(fig.layout.meta, dict) else {}
    formato_explicito = meta.get("value_format")
    escala_explicita = meta.get("value_scale")
    if isinstance(formato_explicito, str) and escala_explicita is not None:
        return formato_explicito, float(escala_explicita)
    eixo_y = getattr(fig.layout, "yaxis", None)
    titulo_y = str(getattr(getattr(eixo_y, "title", None), "text", None) or "")
    texto = titulo_y.lower()
    if "%" in texto or "p.p." in texto or "percent" in texto:
        return "0.0%", 0.01
    return "0.0", 1.0


def figura_para_painel(fig: Any) -> Any:
    """Converte traces Plotly em uma especificação aceita pelo exportador."""
    formato, escala = _formato_e_escala(fig)
    linhas: list[dict[str, Any]] = []
    ordem: list[str] = []
    cores: dict[str, str] = {}
    tipos: set[str] = set()

    for posicao, trace in enumerate(fig.data):
        if getattr(trace, "x", None) is None or getattr(trace, "y", None) is None:
            continue
        nome = str(getattr(trace, "name", None) or f"Série {posicao + 1}")
        if nome in ordem:
            nome = f"{nome} ({posicao + 1})"
        ordem.append(nome)
        cores[nome] = _cor_trace(trace, posicao)
        tipos.add(str(getattr(trace, "type", "scatter")))
        for data, valor in zip(trace.x, trace.y):
            numero = pd.to_numeric(valor, errors="coerce")
            linhas.append({
                "data_base": pd.Timestamp(data).strftime("%Y-%m"),
                "serie": nome,
                "valor": None if pd.isna(numero) else float(numero) * escala,
                "denominador": pd.NA,
            })

    apenas_barras = tipos == {"bar"}
    fonte = "fonte: Banco Central do Brasil · BCData/SGS"
    titulo_y = getattr(getattr(fig.layout, "yaxis", None), "title", None)
    subtitulo = getattr(titulo_y, "text", None) or "Série mensal"
    return SimpleNamespace(
        titulo=_titulo(fig),
        subtitulo=str(subtitulo),
        fonte=fonte,
        produto=_titulo(fig),
        series=pd.DataFrame(linhas),
        ordem_series=ordem,
        cores=cores or {"Série": ITAU_MID_GRAY},
        tracejadas=[],
        metrica="sgs",
        carteira_final_rs_mil=0.0,
        formato_numero=formato,
        tipo_grafico="column_stacked" if apenas_barras else "line",
    )


def exportar_figuras_pptx(
    figuras: Sequence[Any], *, titulo_deck: str
) -> tuple[bytes, dict[str, Any]]:
    """Gera um deck 16:9 com até quatro cards editáveis por slide."""
    paineis = [figura_para_painel(fig) for fig in figuras if getattr(fig, "data", None)]
    if not paineis:
        raise ValueError("nenhum gráfico com dados para exportar")
    return exportar_paineis_pptx(paineis, titulo_deck=titulo_deck)
