"""Garantias de leitura da seção "Estatísticas Crédito BC".

Cada teste aqui trava um defeito medido no app e corrigido: rótulo de barra em
nove tamanhos diferentes na mesma barra, rótulos de fim de linha desenhados no
mesmo pixel, empilhado exportado como linha e card de dois eixos achatado num
eixo só.
"""

from __future__ import annotations

import itertools
import math
from io import BytesIO

import pandas as pd
import pytest
from pptx import Presentation
from pptx.oxml.ns import qn

from utils.sgs_credit_analytics import (
    COR_ROTULO_SOBRE,
    PALETA_LINHA,
    PALETA_PREENCHIMENTO,
    TAMANHO_ROTULO_PX,
    _altura_area_plotagem,
    _espalhar_em_pixels,
    bar_line_figure,
    line_figure,
    stacked_figure,
)
from utils.sgs_credit_pptx_export import exportar_figuras_pptx, figura_para_painel


# =============================================================================
# APOIO
# =============================================================================

def _luminancia(cor: str) -> float:
    canais = [int(cor.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in canais]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contraste(a: str, b: str) -> float:
    la, lb = _luminancia(a), _luminancia(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _lab(cor: str) -> tuple[float, float, float]:
    canais = [int(cor.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    r, g, b = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in canais]
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 216 / 24389 else (841 / 108) * t + 4 / 29

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def _delta_e(a: str, b: str) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(_lab(a), _lab(b))))


def _wide(meses: int = 12, series: int = 9) -> pd.DataFrame:
    index = pd.date_range("2025-08-31", periods=meses, freq="ME")
    return pd.DataFrame(
        {
            f"serie_{i}": [10.0 + i * 0.4 + passo * 0.05 for passo in range(meses)]
            for i in range(series)
        },
        index=index,
    )


# =============================================================================
# PALETA
# =============================================================================

def test_paleta_de_linha_e_legivel_no_branco_e_distinguivel_entre_si():
    """Cinco cores, todas visíveis sobre o papel e nenhuma confundível.

    A paleta anterior tinha dez cores das quais oito eram cinzas com ΔE entre
    6,5 e 10,9 — 20 dos 45 pares eram indistinguíveis.
    """
    for cor in PALETA_LINHA:
        assert _contraste(cor, "#FFFFFF") >= 3.0, f"{cor} some no papel branco"
    for a, b in itertools.combinations(PALETA_LINHA, 2):
        assert _delta_e(a, b) >= 25.0, f"{a} e {b} são confundíveis (ΔE {_delta_e(a, b):.1f})"


def test_todo_preenchimento_declara_cor_de_rotulo_que_passa_no_contraste():
    """Preto ou branco declarado, nunca a escolha automática da biblioteca.

    Sozinha, a biblioteca escolhia #444444 sobre o laranja: 3,19:1, reprovado.
    """
    for preenchimento in PALETA_PREENCHIMENTO:
        rotulo = COR_ROTULO_SOBRE[preenchimento]
        assert rotulo in {"#FFFFFF", "#141414"}
        assert _contraste(preenchimento, rotulo) >= 4.5, (
            f"rótulo {rotulo} sobre {preenchimento} tem contraste insuficiente"
        )


def test_fatias_vizinhas_do_empilhado_nunca_repetem_cor():
    for posicao in range(len(PALETA_PREENCHIMENTO) * 2):
        atual = PALETA_PREENCHIMENTO[posicao % len(PALETA_PREENCHIMENTO)]
        seguinte = PALETA_PREENCHIMENTO[(posicao + 1) % len(PALETA_PREENCHIMENTO)]
        assert _delta_e(atual, seguinte) >= 25.0


# =============================================================================
# RÓTULO DE BARRA
# =============================================================================

def test_rotulo_de_barra_tem_tamanho_unico_e_nunca_deita():
    """Trava de tamanho ligada e ângulo fixo em zero.

    Sem isso a biblioteca desenhava, na mesma barra, rótulos de 0,2 px a 11,4
    px e girava um deles em 90 graus.
    """
    wide = _wide(series=6)
    fig = stacked_figure(
        wide, [f"serie_{i}" for i in range(6)],
        title="Empilhado", y_title="R$ bi",
    )
    assert fig.layout.uniformtext.mode == "hide"
    assert fig.layout.uniformtext.minsize == TAMANHO_ROTULO_PX
    for trace in fig.data:
        assert trace.textangle == 0
        assert trace.insidetextfont.size == TAMANHO_ROTULO_PX
        assert trace.insidetextfont.color == COR_ROTULO_SOBRE[trace.marker.color]


def test_total_do_empilhado_e_anotacao_e_nao_serie_invisivel():
    """O total como série de texto fazia o exportador trocar barra por linha."""
    wide = _wide(series=4)
    total = wide[[f"serie_{i}" for i in range(4)]].sum(axis=1)
    fig = stacked_figure(
        wide, [f"serie_{i}" for i in range(4)],
        title="Empilhado", y_title="R$ bi", total=total,
    )
    assert {trace.type for trace in fig.data} == {"bar"}
    assert len(fig.data) == 4
    assert any(anotacao.text for anotacao in fig.layout.annotations)


# =============================================================================
# RÓTULO DE FIM DE LINHA
# =============================================================================

def test_rotulos_de_fim_de_linha_nunca_se_sobrepoem():
    """Nove séries, nove rótulos, nenhum par colado.

    No app, "8,8%" e "6,3%" eram desenhados no mesmo pixel: a rotina calculava
    o espaçamento em unidades de dado e convertia para pixel usando uma altura
    de área fixada em 285 px, quando a área real era 323 px.
    """
    wide = _wide(series=9)
    fig = line_figure(
        wide, [f"serie_{i}" for i in range(9)],
        title="Nove linhas", y_title="%", suffix="%",
    )
    anotacoes = list(fig.layout.annotations)
    assert len(anotacoes) == 9

    altura_area = _altura_area_plotagem(fig)
    menor, maior = fig.layout.yaxis.range
    pixels_por_unidade = altura_area / (maior - menor)
    posicoes = sorted(
        (maior - anotacao.y) * pixels_por_unidade + anotacao.ay
        for anotacao in anotacoes
    )
    for anterior, seguinte in zip(posicoes, posicoes[1:]):
        assert seguinte - anterior >= TAMANHO_ROTULO_PX, (
            f"rótulos a {seguinte - anterior:.1f} px um do outro"
        )


def test_area_de_plotagem_e_deterministica():
    """A conta dos rótulos só fecha se a geometria for conhecida."""
    fig = line_figure(_wide(series=3), ["serie_0", "serie_1", "serie_2"],
                      title="Três linhas", y_title="%")
    assert fig.layout.margin.autoexpand is False
    esperado = fig.layout.height - fig.layout.margin.t - fig.layout.margin.b
    assert _altura_area_plotagem(fig) == pytest.approx(esperado)


def test_espalhar_preserva_a_ordem_mesmo_quando_nao_cabe():
    alvos = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
    posicoes = _espalhar_em_pixels(alvos, 20.0, 60.0)
    assert posicoes == sorted(posicoes)
    assert min(posicoes) >= 0
    assert max(posicoes) <= 60.0


def test_acima_de_cinco_series_a_cor_repete_com_tracejado_e_o_nome_vai_na_ponta():
    wide = _wide(series=7)
    fig = line_figure(wide, [f"serie_{i}" for i in range(7)],
                      title="Sete linhas", y_title="%")
    assert fig.layout.showlegend is False
    assert fig.data[5].line.color == fig.data[0].line.color
    assert fig.data[5].line.dash == "dash"
    assert fig.data[0].line.dash == "solid"
    # nome + valor, e não só o valor
    assert any("serie_0" in anotacao.text for anotacao in fig.layout.annotations)


# =============================================================================
# EXPORTAÇÃO
# =============================================================================

def test_empilhado_sai_empilhado_no_pptx():
    wide = _wide(series=4)
    total = wide[[f"serie_{i}" for i in range(4)]].sum(axis=1)
    fig = stacked_figure(
        wide, [f"serie_{i}" for i in range(4)],
        title="Empilhado", y_title="R$ bi", total=total,
    )
    painel = figura_para_painel(fig)
    assert painel.tipo_grafico == "column_stacked"
    assert painel.ordem_series == [f"serie_{i}" for i in range(4)]

    blob, _ = exportar_figuras_pptx([fig], titulo_deck="Teste")
    deck = Presentation(BytesIO(blob))
    grafico = [s.chart for s in deck.slides[0].shapes if s.has_chart][0]
    plot_area = grafico._chartSpace.chart.plotArea
    assert plot_area.find(qn("c:barChart")) is not None
    assert plot_area.find(qn("c:lineChart")) is None


def test_card_de_volume_e_prazo_mantem_os_dois_eixos_no_pptx():
    """R$ 246-353 bi e 23-34 meses não podem dividir o mesmo eixo."""
    index = pd.date_range("2025-08-31", periods=12, freq="ME")
    wide = pd.DataFrame(
        {
            "concessoes_livre_pj": [250_000.0 + i * 8_000 for i in range(12)],
            "prazo_livre_pj": [24.0 + i * 0.8 for i in range(12)],
        },
        index=index,
    )
    fig = bar_line_figure(
        wide, bar_alias="concessoes_livre_pj", line_alias="prazo_livre_pj",
        title="Concessões PJ",
    )
    painel = figura_para_painel(fig)
    assert painel.tipo_grafico == "column_line"
    assert len(painel.series_secundarias) == 1

    blob, meta = exportar_figuras_pptx([fig], titulo_deck="Teste")
    deck = Presentation(BytesIO(blob))
    grafico = [s.chart for s in deck.slides[0].shapes if s.has_chart][0]
    plot_area = grafico._chartSpace.chart.plotArea
    assert plot_area.find(qn("c:barChart")) is not None
    assert plot_area.find(qn("c:lineChart")) is not None
    assert len(plot_area.findall(qn("c:valAx"))) == 2
    assert meta["detalhe"][0]["eixo_secundario"] is True
