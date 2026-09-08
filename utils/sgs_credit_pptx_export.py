"""Exporta os cards Plotly do módulo SGS como gráficos Office nativos."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Sequence

import pandas as pd
import plotly.graph_objects as go

from .scr_pptx_export import exportar_deck_por_secao, exportar_paineis_pptx
from .sgs_credit_analytics import ITAU_MID_GRAY, PALETA_LINHA, PALETA_PREENCHIMENTO, escala_de_eixo


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


def figura_para_painel(fig: Any, *, perfil: str | None = None) -> Any:
    """Converte traces Plotly em uma especificação aceita pelo exportador."""
    formato, escala = _formato_e_escala(fig)
    meta = _meta(fig)
    linhas: list[dict[str, Any]] = []
    ordem: list[str] = []
    ordem_categorias: list[str] = []
    cores: dict[str, str] = {}
    tipos: set[str] = set()
    secundarias: list[str] = []
    taxas = perfil == "taxas"
    horizontal = taxas and bool(fig.data) and all(
        getattr(trace, "type", None) == "bar"
        and getattr(trace, "orientation", None) == "h"
        for trace in fig.data
    )
    cores_categorias: dict[str, str] = {}

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
        if meta_trace.get("eixo") == "secundario" or (not taxas and
            getattr(trace, "yaxis", None) == "y2"
        ):
            secundarias.append(nome)
        pontos = zip(trace.y, trace.x) if horizontal else zip(trace.x, trace.y)
        for data, valor in pontos:
            numero = pd.to_numeric(valor, errors="coerce")
            if horizontal:
                categoria = str(data)
                cores_categorias[categoria] = cores[nome]
            else:
                try:
                    formato_data = "%Y-%m-%d" if taxas and meta.get("formato_data") == "diaria" else "%Y-%m"
                    categoria = pd.Timestamp(data).strftime(formato_data)
                except (TypeError, ValueError):
                    categoria = str(data)
            if categoria not in ordem_categorias:
                ordem_categorias.append(categoria)
            linhas.append({
                "data_base": categoria,
                "serie": "Taxa" if horizontal else nome,
                "valor": None if pd.isna(numero) else float(numero) * escala,
                "denominador": pd.NA,
            })

    tipo_grafico = _tipo_grafico(fig, tipos)
    if taxas and not horizontal:
        ordem_categorias.sort()
    if horizontal:
        tipo_grafico = "bar_horizontal"
        ordem = ["Taxa"]
        categorias_eixo = getattr(fig.layout.yaxis, "categoryarray", None)
        if categorias_eixo is not None:
            ordenadas = [str(item) for item in categorias_eixo if str(item) in ordem_categorias]
            ordem_categorias = ordenadas + [item for item in ordem_categorias if item not in ordenadas]
    if tipo_grafico == "column_line" and not secundarias:
        tipo_grafico = "line"

    fonte = str(
        meta.get("source") or "fonte: Banco Central do Brasil · BCData/SGS"
    )
    titulo_y = getattr(getattr(fig.layout, "yaxis", None), "title", None)
    subtitulo = getattr(titulo_y, "text", None) or "Série mensal"
    if taxas:
        subtitulo = meta.get("subtitulo") or subtitulo
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
        estilo_taxas=taxas,
        preservar_lacunas=taxas,
        formato_data=meta.get("formato_data") if taxas else None,
        cores_categorias=cores_categorias,
        inverter_categorias=horizontal and fig.layout.yaxis.autorange == "reversed",
    )


def _paineis_taxas(fig: Any) -> list[Any]:
    """Separa facetas declaradas pelo caller, sem tratá-las como eixos duplos."""
    if not _meta(fig).get("separar_paineis"):
        return [figura_para_painel(fig, perfil="taxas")]
    grupos: dict[tuple[str, str], list[Any]] = {}
    for trace in fig.data:
        chave = (getattr(trace, "xaxis", None) or "x", getattr(trace, "yaxis", None) or "y")
        grupos.setdefault(chave, []).append(trace)
    paineis = []
    eixos = [getattr(fig.layout, "yaxis" + (eixo_y[1:] if eixo_y != "y" else "")) for _, eixo_y in grupos]
    escala_compartilhada = None
    if any(eixo.matches for eixo in eixos):
        _, escala = _formato_e_escala(fig)
        valores = pd.to_numeric(pd.Series([valor for trace in fig.data for valor in trace.y]), errors="coerce").dropna()
        if not valores.empty:
            escala_compartilhada = escala_de_eixo((valores * escala).tolist())
    for traces in grupos.values():
        meta = dict(_meta(fig))
        nomes = ", ".join(str(trace.name or "Instituição") for trace in traces)
        meta["chart_title"] = f"{_titulo(fig)} · {nomes}"
        separada = go.Figure(data=traces)
        separada.update_layout(meta=meta, yaxis_title=fig.layout.yaxis.title.text)
        painel = figura_para_painel(separada, perfil="taxas")
        painel.escala_taxas = escala_compartilhada
        paineis.append(painel)
    return paineis


def exportar_figuras_pptx(
    figuras: Sequence[Any], *, titulo_deck: str, perfil: str | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Gera gráficos nativos; ``perfil='taxas'`` habilita datas diárias e facetas.

    Taxas usa uma lâmina por figura e até quatro facetas por lâmina. Metadados
    ``source``, ``subtitulo``, ``formato_data`` e ``separar_paineis`` pertencem
    à figura, permitindo exportar os recortes atuais sem consultar dados.
    """
    if perfil not in {None, "taxas"}:
        raise ValueError(f"perfil de exportação desconhecido: {perfil}")
    if perfil == "taxas":
        paineis, blocos = [], []
        for fig in figuras:
            if not getattr(fig, "data", None):
                continue
            grupo = _paineis_taxas(fig)
            paineis.extend(grupo)
            blocos.extend(min(4, len(grupo) - inicio) for inicio in range(0, len(grupo), 4))
        if not paineis:
            raise ValueError("nenhum gráfico com dados para exportar")
        return exportar_paineis_pptx(paineis, titulo_deck=titulo_deck, blocos_por_slide=blocos)
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
    convertidas = [
        item for item in convertidas
        if item[2] or (item[1] and any(str(texto or "").strip() for texto in item[1]))
    ]
    if not convertidas:
        raise ValueError("nenhum gráfico com dados para exportar")
    return exportar_deck_por_secao(
        convertidas,
        titulo_deck=titulo_deck,
        subtitulo_capa=subtitulo_capa,
        rodape_capa=rodape_capa,
    )
