"""Exporta os cards Plotly do módulo SGS como gráficos Office nativos."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Sequence

import pandas as pd

from .scr_pptx_export import exportar_deck_por_secao, exportar_paineis_pptx
from .sgs_credit_analytics import ITAU_MID_GRAY, PALETA_LINHA, PALETA_PREENCHIMENTO


def _meta(fig: Any) -> dict:
    return fig.layout.meta if isinstance(fig.layout.meta, dict) else {}


def _titulo(fig: Any) -> str:
    candidato = _meta(fig).get("chart_title")
    if isinstance(candidato, str) and candidato.strip():
        return candidato.strip()
    texto = getattr(getattr(fig.layout, "title", None), "text", None)
    if isinstance(texto, str) and texto.strip() and texto.strip().lower() != "undefined":
        return texto.strip()
    return "Gráfico"


def _cor_trace(trace: Any, posicao: int, *, empilhado: bool) -> str:
    linha = getattr(getattr(trace, "line", None), "color", None)
    marcador = getattr(getattr(trace, "marker", None), "color", None)
    cor = linha or marcador
    if isinstance(cor, str) and cor.startswith("#"):
        return cor
    paleta = PALETA_PREENCHIMENTO if empilhado else PALETA_LINHA
    return paleta[posicao % len(paleta)]


def _formato_e_escala(fig: Any) -> tuple[str, float]:
    meta = _meta(fig)
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


def _tipo_grafico(fig: Any, tipos: set[str]) -> str:
    """Tipo do gráfico exportado, na ordem: o que a figura declara, depois o
    que os traces mostram.

    A dedução por tipo de trace sozinha errava em todo empilhado: o rótulo do
    total era uma série invisível de texto, então a figura chegava aqui como
    "barra + ponto" e caía no ramo de linhas. Hoje o total é anotação, e a
    figura ainda pode declarar o tipo explicitamente.
    """
    declarado = _meta(fig).get("tipo_grafico")
    if isinstance(declarado, str) and declarado:
        return declarado
    if tipos == {"bar"}:
        return "column_stacked"
    return "line"


def figura_para_painel(fig: Any) -> Any:
    """Converte traces Plotly em uma especificação aceita pelo exportador."""
    formato, escala = _formato_e_escala(fig)
    meta = _meta(fig)
    linhas: list[dict[str, Any]] = []
    ordem: list[str] = []
    ordem_categorias: list[str] = []
    cores: dict[str, str] = {}
    tipos: set[str] = set()
    secundarias: list[str] = []

    traces = [
        trace for trace in fig.data
        if getattr(trace, "x", None) is not None and getattr(trace, "y", None) is not None
    ]
    empilhado = {str(getattr(t, "type", "scatter")) for t in traces} == {"bar"}

    for posicao, trace in enumerate(traces):
        meta_trace = trace.meta if isinstance(trace.meta, dict) else {}
        # O nome do trace pode trazer marcação HTML, usada para tingir o item
        # da legenda no navegador. No deck vale o texto limpo.
        nome = str(
            meta_trace.get("rotulo_limpo")
            or getattr(trace, "name", None)
            or f"Série {posicao + 1}"
        )
        if nome in ordem:
            nome = f"{nome} ({posicao + 1})"
        ordem.append(nome)
        cores[nome] = _cor_trace(trace, posicao, empilhado=empilhado)
        tipos.add(str(getattr(trace, "type", "scatter")))
        if meta_trace.get("eixo") == "secundario" or (
            getattr(trace, "yaxis", None) == "y2"
        ):
            secundarias.append(nome)
        for data, valor in zip(trace.x, trace.y):
            numero = pd.to_numeric(valor, errors="coerce")
            try:
                categoria = pd.Timestamp(data).strftime("%Y-%m")
            except (TypeError, ValueError):
                categoria = str(data)
            if categoria not in ordem_categorias:
                ordem_categorias.append(categoria)
            linhas.append({
                "data_base": categoria,
                "serie": nome,
                "valor": None if pd.isna(numero) else float(numero) * escala,
                "denominador": pd.NA,
            })

    tipo_grafico = _tipo_grafico(fig, tipos)
    if tipo_grafico == "column_line" and not secundarias:
        tipo_grafico = "line"

    fonte = str(
        meta.get("source") or "fonte: Banco Central do Brasil · BCData/SGS"
    )
    titulo_y = getattr(getattr(fig.layout, "yaxis", None), "title", None)
    subtitulo = getattr(titulo_y, "text", None) or "Série mensal"
    if tipo_grafico == "column_line":
        subtitulo = (
            f"{meta.get('titulo_eixo_primario', subtitulo)} · "
            f"{meta.get('titulo_eixo_secundario', 'eixo direito')} à direita"
        )
    return SimpleNamespace(
        titulo=_titulo(fig),
        subtitulo=str(subtitulo),
        fonte=fonte,
        produto=_titulo(fig),
        series=pd.DataFrame(linhas),
        ordem_series=ordem,
        ordem_categorias=ordem_categorias,
        cores=cores or {"Série": ITAU_MID_GRAY},
        tracejadas=[],
        metrica="sgs",
        carteira_final_rs_mil=0.0,
        formato_numero=str(meta.get("formato_primario") or formato),
        formato_secundario=str(meta.get("formato_secundario") or formato),
        series_secundarias=secundarias,
        tipo_grafico=tipo_grafico,
        rotular_todos_pontos=bool(meta.get("label_all_points", False)),
    )


def exportar_figuras_pptx(
    figuras: Sequence[Any], *, titulo_deck: str
) -> tuple[bytes, dict[str, Any]]:
    """Gera um deck 16:9 com até quatro cards editáveis por slide."""
    paineis = [figura_para_painel(fig) for fig in figuras if getattr(fig, "data", None)]
    if not paineis:
        raise ValueError("nenhum gráfico com dados para exportar")
    return exportar_paineis_pptx(paineis, titulo_deck=titulo_deck)


def exportar_deck_secoes_pptx(
    secoes: Sequence[tuple[str, tuple[str, str] | None, Sequence[Any]]],
    *,
    titulo_deck: str,
    subtitulo_capa: str = "",
    rodape_capa: str = "",
) -> tuple[bytes, dict[str, Any]]:
    """Deck contínuo de várias abas: a leitura de cada uma e depois os gráficos.

    ``secoes`` chega como ``(titulo, (texto, fontes) | None, figuras)`` na ordem
    em que as abas aparecem na tela.
    """
    convertidas = [
        (
            titulo,
            leitura,
            [figura_para_painel(fig) for fig in figuras if getattr(fig, "data", None)],
        )
        for titulo, leitura, figuras in secoes
    ]
    convertidas = [item for item in convertidas if item[2]]
    if not convertidas:
        raise ValueError("nenhum gráfico com dados para exportar")
    return exportar_deck_por_secao(
        convertidas,
        titulo_deck=titulo_deck,
        subtitulo_capa=subtitulo_capa,
        rodape_capa=rodape_capa,
    )
