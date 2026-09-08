"""Deck contínuo: todas as abas de Estatísticas Crédito BC em um arquivo.

O deck é deliberadamente simples: caixa de texto e gráfico nativo, nada mais.
Sem slide divisor, sem régua, sem moldura em volta do gráfico.
"""

from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from pptx import Presentation
from pptx.oxml.ns import qn

import tabs.mercado_credito as MC
from utils.comentarios_credito import comentario
from utils.sgs_credit_analytics import derive_credit_totals, to_wide

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_credito_bc_legibilidade import (  # noqa: E402
    _NS,
    _graficos_do_deck,
    validar_xml_do_grafico,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def janela() -> pd.DataFrame:
    bruto = pd.read_parquet(
        PROJECT_ROOT / "data" / "bundled" / "mercado_credito_sgs" / "dados.parquet"
    )
    wide = derive_credit_totals(to_wide(bruto))
    analiticas = [c for c in wide.columns if c not in {"cdi_aa", "selic_aa"}]
    periodos = pd.DatetimeIndex(
        wide[analiticas].dropna(how="all").index
    ).sort_values().unique()
    fim = pd.Timestamp(periodos[-1])
    recorte = wide.loc[(wide.index >= fim - pd.DateOffset(months=11)) & (wide.index <= fim)].copy()
    recorte.attrs["full_history"] = wide
    return recorte


@pytest.fixture(scope="module")
def gerenciador(janela):
    """SCR sintético: o teste de exportação independe de caches e rede locais."""
    from utils.ifdata_cache import scr_data as S
    from test_scr_inadimplencia_ui import _fato, _linha

    periodos = pd.date_range(end=janela.index.max(), periods=18, freq="ME")
    linhas = [
        _linha(data_base=periodo.strftime("%Y-%m"), uf=uf, porte=porte,
               modalidade_bcb=modalidade, carteira_ativa=1000.0 + posicao,
               carteira_inadimplencia=30.0 + posicao)
        for periodo in periodos
        for modalidade in S.MODALIDADES_BCB_PF
        for porte in S.PORTE_PF_ORDEM[:3]
        for posicao, uf in enumerate(S.REGIAO_POR_UF)
    ]
    fato = _fato(linhas)

    class CacheSCRTeste:
        def get_info(self):
            return {"periodos": [p.strftime("%Y-%m") for p in periodos]}

        def carregar_detalhe(self, *, anos):
            return fato[fato["data_base"].str[:4].astype(int).isin(anos)].copy()

    cache = CacheSCRTeste()
    return lambda: SimpleNamespace(get_cache=lambda nome: cache if nome == "scr_data" else None)


@pytest.fixture(scope="module")
def deck(janela, gerenciador):
    blob, meta = MC._deck_completo(janela, gerenciador)
    return blob, meta, Presentation(BytesIO(blob))


def test_modo_silencioso_monta_as_figuras_sem_desenhar(janela):
    """Todas as abas entram no deck sem o usuário abrir uma por uma."""
    for titulo, _, render in MC.SECOES_DECK:
        if render is None:
            continue
        figuras = MC._figuras_da_secao(render, janela)
        assert figuras, f"{titulo} não produziu gráfico"
        assert all(figura.data for figura in figuras)
    # O modo silencioso não vaza para o render normal.
    assert MC._SILENCIOSO.get() is False


def test_deck_segue_a_ordem_das_abas_da_tela(deck):
    _, _, apresentacao = deck
    titulos = [
        forma.text_frame.paragraphs[0].runs[0].text
        for slide in apresentacao.slides
        for forma in slide.shapes
        if forma.has_text_frame and forma.text_frame.paragraphs[0].runs
    ]
    esperada = [titulo for titulo, _, _ in MC.SECOES_DECK]
    posicoes = [titulos.index(nome) for nome in esperada]
    assert posicoes == sorted(posicoes), "as abas saíram fora da ordem da tela"
    # A ordem do deck é a ordem do menu da seção.
    assert [t for t, _, _ in MC.SECOES_DECK][0] == MC.MAIN_SECTIONS[0]
    assert MC.CREDIT_SUBSECTIONS == tuple(
        t.split(" · ")[-1] for t, _, _ in MC.SECOES_DECK if t.startswith("Crédito SFN")
    )


def test_leitura_de_cada_aba_fica_acima_dos_graficos_dela(deck):
    """O comentário abre a aba, na mesma lâmina dos primeiros gráficos.

    Comentário longo demais para a faixa ganha lâmina própria; nesse caso os
    gráficos vêm na lâmina seguinte.
    """
    _, _, apresentacao = deck
    slides = list(apresentacao.slides)
    for _, chave, _ in MC.SECOES_DECK:
        leitura = comentario(chave)
        primeiro_paragrafo = leitura.paragrafos[0]
        indice = next(
            i for i, slide in enumerate(slides)
            if any(
                primeiro_paragrafo in forma.text
                for forma in slide.shapes if forma.has_text_frame
            )
        )
        com_grafico = [
            forma for forma in slides[indice].shapes if forma.has_chart
        ]
        if com_grafico:
            topo_comentario = min(
                forma.top for forma in slides[indice].shapes
                if forma.has_text_frame and primeiro_paragrafo in forma.text
            )
            assert topo_comentario < min(forma.top for forma in com_grafico)
        else:
            assert any(forma.has_chart for forma in slides[indice + 1].shapes)


def test_deck_so_tem_caixa_de_texto_e_grafico(deck):
    """Nada decorativo: nem régua, nem moldura, nem shape de enfeite."""
    _, _, apresentacao = deck
    estranhos = [
        forma
        for slide in apresentacao.slides
        for forma in slide.shapes
        if not forma.has_text_frame and not forma.has_chart
    ]
    assert estranhos == []


def test_grafico_nao_tem_contorno(deck):
    """Sem spPr explícito, o Office desenha a moldura do estilo padrão."""
    blob, _, _ = deck
    for xml in _graficos_do_deck(blob):
        from lxml import etree

        raiz = etree.fromstring(xml)
        sp_pr = raiz.find(qn("c:spPr"))
        assert sp_pr is not None, "gráfico sem spPr herda a moldura do tema"
        assert len(sp_pr.findall(f".//{qn('a:noFill')}")) == 2


def test_deck_inteiro_passa_no_schema(deck):
    blob, _, _ = deck
    erros = [erro for xml in _graficos_do_deck(blob) for erro in validar_xml_do_grafico(xml)]
    assert erros == []


def test_grade_de_ate_quatro_graficos_por_slide(deck):
    _, meta, apresentacao = deck
    assert meta["paineis_por_slide"] == 4
    for slide in apresentacao.slides:
        assert sum(1 for forma in slide.shapes if forma.has_chart) <= 4


def test_capa_traz_titulo_competencia_e_fonte(deck):
    _, _, apresentacao = deck
    capa = apresentacao.slides[0]
    textos = [forma.text for forma in capa.shapes if forma.has_text_frame]
    assert any("Estatísticas Crédito BC" in texto for texto in textos)
    assert any("janela até" in texto for texto in textos)
    assert any("Banco Central" in texto for texto in textos)
    assert not any(forma.has_chart for forma in capa.shapes)


def test_comentario_sai_em_paragrafos_separados(deck):
    """Linha em branco no JSON vira parágrafo no slide, como na tela."""
    _, _, apresentacao = deck
    leitura = comentario("credito_estoque")
    assert len(leitura.paragrafos) == 2
    slide = next(
        slide for slide in apresentacao.slides
        if any(leitura.paragrafos[0] in f.text for f in slide.shapes if f.has_text_frame)
    )
    corpo = next(
        forma for forma in slide.shapes
        if forma.has_text_frame and leitura.paragrafos[0] in forma.text
    )
    assert len(corpo.text_frame.paragraphs) == len(leitura.paragrafos)


def test_todas_as_abas_e_submenus_entram(deck):
    _, meta, _ = deck
    assert meta["secoes"] == len(MC.SECOES_DECK) + meta["secoes_glossario"]
    assert meta["completo"] is True
    # 42 gráficos do SGS mais os da aba de faixa de renda, que traz todas as
    # modalidades PF e a visão regional.
    assert meta["paineis"] >= 48


# =============================================================================
# FORMATAÇÃO PEDIDA
# =============================================================================

def _paragrafos_de_comentario(apresentacao):
    primeiro = comentario("concessoes").paragrafos[0]
    for slide in apresentacao.slides:
        for forma in slide.shapes:
            if forma.has_text_frame and primeiro in forma.text:
                return forma.text_frame.paragraphs
    raise AssertionError("comentário não encontrado no deck")


def test_comentario_sai_com_entrelinha_de_um_e_meio_e_sem_espaco_extra(deck):
    _, _, apresentacao = deck
    paragrafos = _paragrafos_de_comentario(apresentacao)
    assert len(paragrafos) >= 2
    for paragrafo in paragrafos:
        assert paragrafo.line_spacing == 1.5
        assert paragrafo.space_before.pt == 0
        assert paragrafo.space_after.pt == 0


def test_titulo_e_comentario_ficam_proximos(deck):
    """Antes o comentário vivia em outra lâmina, a 0,80 in do título."""
    from utils.scr_pptx_export import ALTURA_TITULO_SECAO, RESPIRO_TITULO

    _, _, apresentacao = deck
    primeiro = comentario("concessoes").paragrafos[0]
    slide = next(
        slide for slide in apresentacao.slides
        if any(primeiro in f.text for f in slide.shapes if f.has_text_frame)
    )
    corpo = next(f for f in slide.shapes if f.has_text_frame and primeiro in f.text)
    titulo = next(
        f for f in slide.shapes
        if f.has_text_frame and f.text.strip() == "Concessões"
    )
    vao = corpo.top - (titulo.top + titulo.height)
    assert 0 <= vao <= int(RESPIRO_TITULO) + 1
    assert titulo.height == ALTURA_TITULO_SECAO


def test_grade_preenche_a_altura_livre_do_slide(deck):
    """A célula cresce para ocupar o que sobra abaixo do comentário.

    Altura fixa deixava metade do slide vazia sempre que a faixa de leitura era
    curta. Dentro de um mesmo slide todos os gráficos continuam iguais.
    """
    _, _, apresentacao = deck
    limite = apresentacao.slide_height - 347472
    for slide in apresentacao.slides:
        graficos = [forma for forma in slide.shapes if forma.has_chart]
        if not graficos:
            continue
        assert len({forma.height for forma in graficos}) == 1
        base = max(forma.top + forma.height for forma in graficos)
        # A última linha encosta na margem inferior: sem sobra desperdiçada.
        assert limite - base <= 91440, "sobrou mais de 0,1 in de espaço vazio"
        assert base <= limite + 1


def test_nenhum_grafico_passa_da_margem_inferior(deck):
    _, _, apresentacao = deck
    limite = apresentacao.slide_height - 347472  # 7,5 in menos a margem de 0,38
    for slide in apresentacao.slides:
        for forma in slide.shapes:
            if forma.has_chart:
                assert forma.top + forma.height <= limite + 1


def test_rotulo_traz_nome_da_serie_junto_do_valor(deck):
    """O rótulo do último ponto identifica a linha sozinho, como na tela."""
    from lxml import etree

    blob, _, _ = deck
    encontrou = False
    for xml in _graficos_do_deck(blob):
        raiz = etree.fromstring(xml)
        # Só os rótulos ponto a ponto; o bloco de padrão do gráfico continua
        # desligado, e é ele que vale para os pontos sem rótulo.
        for grupo in raiz.iter():
            tipo = grupo.tag.replace(_NS, "")
            if tipo not in {"barChart", "lineChart"}:
                continue
            # Na coluna o nome não cabe na largura da barra e fica na legenda;
            # na linha ele vai junto do valor, na faixa da direita.
            esperado = "0" if tipo == "barChart" else "1"
            for rotulo in grupo.iter(qn("c:dLbl")):
                nome = rotulo.find(qn("c:showSerName"))
                valor = rotulo.find(qn("c:showVal"))
                assert valor is not None and valor.get("val") == "1"
                assert nome is not None and nome.get("val") == esperado
                encontrou = True
    assert encontrou, "nenhum rótulo configurado no deck"


def test_faixa_de_renda_traz_todas_as_modalidades_pf(gerenciador):
    """O deck leva as 7 modalidades PF, e não as 4 que a tela abre."""
    from tabs import scr_inadimplencia as scr_spec

    figuras = MC._figuras_faixa_de_renda(gerenciador)
    titulos = [
        (fig.layout.meta or {}).get("chart_title", "") for fig in figuras
    ]
    modalidades_pf = [
        modalidade for modalidade in scr_spec.MODALIDADES_BCB_PF
        if any(modalidade.split(" - ")[-1] in titulo for titulo in titulos)
    ]
    assert len(figuras) > scr_spec.PAINEIS_POR_SLIDE
    assert len(modalidades_pf) >= 5
    # A visão regional entra como barra por UF, já que mapa não é nativo.
    assert any("por UF" in titulo for titulo in titulos)
    assert any("por região" in titulo for titulo in titulos)


def test_mapa_nao_entra_no_deck(gerenciador):
    """Coroplético não existe como gráfico nativo do Office."""
    figuras = MC._figuras_faixa_de_renda(gerenciador)
    for figura in figuras:
        for trace in figura.data:
            assert trace.type not in {"choropleth", "choroplethmapbox", "scattergeo"}


# =============================================================================
# LEGIBILIDADE DOS RÓTULOS NO SLIDE RENDERIZADO
# =============================================================================

def test_rotulo_de_linha_fica_na_faixa_a_direita_da_plotagem(deck):
    """A área de plotagem encolhe e o rótulo do último ponto vai para a sobra.

    Sem isso o rótulo era desenhado sobre as próprias linhas e cortado na
    borda do gráfico.
    """
    from lxml import etree

    from pptx import Presentation
    from utils.scr_pptx_export import (
        GUTTER_ROTULO_LINHA,
        LARGURA_MINIMA_FAIXA_IN,
    )

    blob, _, apresentacao = deck
    conferidos = 0
    for slide in Presentation(BytesIO(blob)).slides:
        for forma in slide.shapes:
            if not forma.has_chart:
                continue
            raiz = forma.chart._chartSpace
            if raiz.find(f".//{qn('c:lineChart')}") is None:
                continue
            layout = raiz.find(
                f".//{qn('c:plotArea')}/{qn('c:layout')}/{qn('c:manualLayout')}"
            )
            assert layout is not None, "gráfico de linhas sem layout manual"
            esquerda = float(layout.find(qn("c:x")).get("val"))
            largura = float(layout.find(qn("c:w")).get("val"))
            faixa = 1.0 - (esquerda + largura)
            # A faixa é medida em polegadas: cabe o maior nome de série, com um
            # piso que não some e um teto que não come o gráfico.
            assert faixa * forma.width / 914400.0 >= LARGURA_MINIMA_FAIXA_IN * 0.95
            assert faixa <= GUTTER_ROTULO_LINHA + 0.001
            conferidos += 1
    assert conferidos, "nenhum gráfico de linhas no deck"


def test_rotulos_finais_nao_se_sobrepoem_na_faixa():
    """O escalonamento respeita a altura de cada nome, inclusive os que quebram."""
    from utils.scr_pptx_export import _escalonar_no_gutter

    finais = [
        ("Desconto de duplicatas/recebíveis", -3.6), ("Capital de giro", -5.4),
        ("Conta garantida", -2.5), ("Aquisição de bens", -9.7), ("ACC", -3.3),
        ("Financiamento à exportação", -10.3), ("Rural PJ", 22.4),
        ("Imobiliário PJ", 8.7), ("BNDES PJ", 5.5),
    ]
    posicoes = _escalonar_no_gutter(
        finais, int(2.5 * 914400), int(6.14 * 914400)
    )
    from utils.scr_pptx_export import FATOR_LINHA_CALIBRI, corpo_do_rotulo

    assert len(posicoes) == len(finais)
    # A folga exigida é a altura do rótulo de cima, não um número fixo: um nome
    # que quebra em duas linhas precisa do dobro do espaço do vizinho de baixo.
    linha = (corpo_do_rotulo(len(finais)) * FATOR_LINHA_CALIBRI / 72) / 2.5
    longos = {"Desconto de duplicatas/recebíveis", "Financiamento à exportação"}
    ordenadas = sorted(posicoes.items(), key=lambda item: item[1])
    for (nome, alto), (_, baixo) in zip(ordenadas, ordenadas[1:]):
        minimo = linha * (2 if nome in longos else 1)
        assert baixo - alto >= minimo * 0.98, f"{nome} invade o rótulo de baixo"
    assert ordenadas[0][1] >= 0.03
    assert ordenadas[-1][1] <= 0.95


def test_barra_empilhada_tem_barra_larga_para_o_rotulo_caber(deck):
    """O PowerPoint recorta o rótulo pela largura da barra."""
    from lxml import etree

    blob, _, _ = deck
    for xml in _graficos_do_deck(blob):
        raiz = etree.fromstring(xml)
        barra = raiz.find(f".//{qn('c:barChart')}")
        if barra is None or raiz.find(f".//{qn('c:lineChart')}") is not None:
            continue
        vao = barra.find(qn("c:gapWidth"))
        assert vao is not None and int(vao.get("val")) <= 50


def test_legenda_so_existe_onde_o_rotulo_nao_traz_o_nome(deck):
    """Linha não leva legenda: o nome já vai no rótulo e sobrava disputa de
    espaço com os meses do eixo."""
    from lxml import etree

    blob, _, _ = deck
    for xml in _graficos_do_deck(blob):
        raiz = etree.fromstring(xml)
        tem_legenda = raiz.find(f".//{qn('c:legend')}") is not None
        so_linhas = (
            raiz.find(f".//{qn('c:lineChart')}") is not None
            and raiz.find(f".//{qn('c:barChart')}") is None
        )
        if so_linhas:
            assert not tem_legenda


def test_eixo_secundario_do_deck_comeca_em_zero(deck):
    """Mesma sensibilidade da tela: prazo que varia pouco aparece plano."""
    from lxml import etree

    blob, _, _ = deck
    achou = False
    for xml in _graficos_do_deck(blob):
        raiz = etree.fromstring(xml)
        eixos = raiz.findall(f".//{qn('c:valAx')}")
        if len(eixos) < 2:
            continue
        minimo = eixos[-1].find(f"{qn('c:scaling')}/{qn('c:min')}")
        assert minimo is not None and float(minimo.get("val")) == 0
        achou = True
    assert achou, "nenhum card de dois eixos no deck"


def test_escala_de_eixo_usa_degrau_redondo_e_segue_o_dado():
    """A régua do eixo é calculada a cada leitura, e não deixada ao Office.

    O rótulo do último ponto é posicionado por coordenada: se a escala do
    gráfico não for a mesma que a conta do rótulo usa, o nome da série cai
    longe da linha que ele nomeia.
    """
    from utils.scr_pptx_export import escala_de_eixo

    # Dado que ocupa metade da altura com o zero dentro mantém o zero.
    assert escala_de_eixo([3.5, 30.8]) == (0.0, 35.0)
    # Dado espremido longe do zero é enquadrado: de 0 a 6 a linha vira reta.
    assert escala_de_eixo([3.62, 5.78]) == (3.0, 6.0)
    piso, teto = escala_de_eixo([430.2, 453.1, 436.2])
    assert piso >= 425 and teto >= 453.1
    # Série que cruza o zero mantém o zero, que é o que separa alta de queda.
    piso, teto = escala_de_eixo([-10.3, 22.4])
    assert piso <= -10.3 and teto >= 22.4
    # Barra e eixo secundário ancoram por declaração de quem chama.
    assert escala_de_eixo([0.42, 0.94], ancorar_zero=True)[0] == 0.0
    # O eixo anda com o dado: a mesma série deslocada muda piso e teto.
    antes = escala_de_eixo([3.62, 5.78])
    depois = escala_de_eixo([5.62, 7.78])
    assert depois[0] > antes[0] and depois[1] > antes[1]


def test_rotulo_fica_na_altura_da_propria_regua():
    """Duas séries em eixos diferentes, cada uma medida na escala do seu eixo.

    Normalizar as duas pelo intervalo dos valores finais mandava o rótulo do
    eixo da direita para o rodapé, ao lado de uma linha que corre no topo.
    """
    from utils.scr_pptx_export import _escalonar_no_gutter

    posicoes = _escalonar_no_gutter(
        [("Capital de giro", 5.8), ("Conta garantida", 4.9),
         ("Desconto de recebíveis", 0.9)],
        int(3.4 * 914400), int(12.0 * 914400),
        secundarias=["Desconto de recebíveis"],
        escalas={False: (0.0, 6.0), True: (0.0, 1.0)},
    )
    # 0,9 de 1,0 é o topo do eixo da direita: o rótulo acompanha a linha.
    assert posicoes["Desconto de recebíveis"] < posicoes["Conta garantida"]
    assert posicoes["Desconto de recebíveis"] < 0.2


def test_eixo_secundario_tem_teto_fixo_e_fio_claro(deck):
    """Teto explícito para casar com o rótulo; fio cinza como o eixo da esquerda."""
    from lxml import etree

    blob, _, _ = deck
    achou = False
    for xml in _graficos_do_deck(blob):
        raiz = etree.fromstring(xml)
        eixos = raiz.findall(f".//{qn('c:valAx')}")
        if len(eixos) < 2:
            continue
        maximo = eixos[-1].find(f"{qn('c:scaling')}/{qn('c:max')}")
        assert maximo is not None and float(maximo.get("val")) > 0
        cor = eixos[-1].find(
            f"{qn('c:spPr')}/{qn('a:ln')}/{qn('a:solidFill')}/{qn('a:srgbClr')}"
        )
        assert cor is not None and cor.get("val") == "E6E6E6"
        achou = True
    assert achou, "nenhum card de dois eixos no deck"


def test_barra_com_muitas_categorias_gira_o_rotulo(deck):
    """27 UFs deixam a barra mais estreita que o número, e o Office o corta."""
    from lxml import etree

    blob, _, _ = deck
    achou = False
    for xml in _graficos_do_deck(blob):
        raiz = etree.fromstring(xml)
        if raiz.find(f".//{qn('c:barChart')}") is None:
            continue
        primeira = raiz.find(f".//{qn('c:ser')}")
        categorias = primeira.findall(f"{qn('c:cat')}//{qn('c:pt')}")
        if len(categorias) <= 14:
            continue
        corpos = raiz.findall(
            f".//{qn('c:dLbl')}/{qn('c:txPr')}/{qn('a:bodyPr')}"
        )
        assert corpos, "barra densa sem rótulo"
        assert all(no.get("rot") == "-5400000" for no in corpos)
        achou = True
    assert achou, "nenhuma barra com muitas categorias no deck"


def test_serie_unica_nao_leva_legenda(deck):
    """Com uma série só o Office lista as categorias na legenda, o que é ruído."""
    from lxml import etree

    blob, _, _ = deck
    for xml in _graficos_do_deck(blob):
        raiz = etree.fromstring(xml)
        series = raiz.findall(f".//{qn('c:ser')}")
        if len(series) == 1:
            assert raiz.find(f".//{qn('c:legend')}") is None


def test_legenda_do_deck_cabe_todas_as_series(deck):
    """Sem caixa explícita o Office corta as entradas que não couberem.

    O mix da carteira tem dez séries e mostrava sete: as três escondidas eram
    as de nome comprido, que é justamente quem precisa de legenda.
    """
    from lxml import etree

    from pptx import Presentation
    from utils.scr_pptx_export import FONTE_LEGENDA_PT

    blob, _, _ = deck
    conferidos = 0
    for slide in Presentation(BytesIO(blob)).slides:
        for forma in slide.shapes:
            if not forma.has_chart:
                continue
            raiz = forma.chart._chartSpace
            legenda = raiz.find(f".//{qn('c:legend')}")
            if legenda is None:
                continue
            manual = legenda.find(f"{qn('c:layout')}/{qn('c:manualLayout')}")
            assert manual is not None, "legenda sem caixa explícita"
            altura_in = (
                float(manual.find(qn("c:h")).get("val")) * forma.height / 914400.0
            )
            series = len(raiz.findall(f".//{qn('c:ser')}"))
            # Uma linha de texto por entrada, com o corpo declarado.
            assert altura_in >= series * (FONTE_LEGENDA_PT / 72) * 1.2
            conferidos += 1
    assert conferidos, "nenhuma legenda no deck"


def test_rotulo_de_barra_empilhada_fica_dentro_da_fatia(deck):
    """Na borda de cima, a fatia de baixo jogava o rótulo sobre o nome do mês."""
    from lxml import etree

    blob, _, _ = deck
    achou = False
    for xml in _graficos_do_deck(blob):
        raiz = etree.fromstring(xml)
        grupo = raiz.find(f".//{qn('c:barChart')}")
        if grupo is None:
            continue
        empilhamento = grupo.find(qn("c:grouping"))
        if empilhamento is None or empilhamento.get("val") != "stacked":
            continue
        for posicao in grupo.iter(qn("c:dLblPos")):
            assert posicao.get("val") == "ctr"
            achou = True
    assert achou, "nenhum rótulo de coluna empilhada no deck"


# =============================================================================
# GERAÇÃO, COBERTURA E FILTROS
# =============================================================================


def test_scr_respeita_o_mesmo_periodo_do_deck(gerenciador, janela):
    inicio, fim = janela.index[-4], janela.index[-2]
    figuras = MC._figuras_faixa_de_renda(gerenciador, inicio=inicio, fim=fim)
    datas = [data for figura in figuras for data in MC._valid_trace_dates(figura)]
    assert datas
    assert min(datas).to_period("M") == inicio.to_period("M")
    assert max(datas).to_period("M") == fim.to_period("M")


def test_glossario_do_deck_preserva_definicoes_e_fontes_da_tela(deck):
    from utils.credito_bc_glossario import SGS_ROWS, SCR_SECTIONS

    _, meta, apresentacao = deck
    slides = [slide for slide in apresentacao.slides if any(
        forma.has_text_frame and forma.text.startswith("Glossário ·") for forma in slide.shapes
    )]
    texto = "\n".join(forma.text for slide in slides for forma in slide.shapes if forma.has_text_frame)
    assert len(slides) == meta["secoes_glossario"]
    assert all(not any(forma.has_chart for forma in slide.shapes) for slide in slides)
    for indicador, definicao, unidade in SGS_ROWS:
        assert indicador in texto
        assert definicao in texto
        assert unidade in texto
    for _, markdown in SCR_SECTIONS:
        for paragrafo in markdown.splitlines():
            assert paragrafo.removeprefix("- ").replace("**", "") in texto
    assert "https://www.bcb.gov.br/estabilidadefinanceira/scrdata" in texto
    for slide in slides:
        for forma in slide.shapes:
            if not forma.has_text_frame:
                continue
            assert forma.top + forma.height <= apresentacao.slide_height
            if len(forma.text) > 150:
                assert all(run.font.size.pt >= 15 for p in forma.text_frame.paragraphs for run in p.runs)


def _figura_workflow():
    import plotly.graph_objects as go

    fig = go.Figure(go.Scatter(x=pd.to_datetime(["2026-05-31", "2026-06-30"]),
                              y=[1.0, 2.0], name="Série de teste"))
    fig.update_layout(meta={"chart_title": "Gráfico de teste"})
    return fig


def test_ausencia_do_scr_e_declarada_no_arquivo_parcial(monkeypatch, janela):
    monkeypatch.setattr(MC, "_figuras_da_secao", lambda *args: [_figura_workflow()])
    blob, meta = MC._deck_completo(janela, None)
    assert meta["completo"] is False
    scr = next(item for item in meta["cobertura"] if "faixa de renda" in item["Seção"])
    assert scr["Situação"] == "Sem dados"
    assert scr["Gráficos"] == 0
    texto = "\n".join(f.text for s in Presentation(BytesIO(blob)).slides for f in s.shapes if f.has_text_frame)
    assert "exportação parcial" in texto
    assert "Sem dados disponíveis" in texto
    assert scr["Seção"] in texto


def test_falha_de_secao_mantem_as_demais_e_informa_cobertura(monkeypatch, janela):
    def figuras(render, wide):
        if render == "_render_concessoes":
            raise RuntimeError("falha controlada")
        return [_figura_workflow()]

    monkeypatch.setattr(MC, "_figuras_da_secao", figuras)
    monkeypatch.setattr(MC, "_figuras_faixa_de_renda", lambda *args, **kwargs: [_figura_workflow()])
    eventos = []
    _, meta = MC._deck_completo(janela, None, progresso=lambda valor, texto: eventos.append((valor, texto)))
    assert meta["completo"] is False
    assert meta["cobertura"][0]["Situação"] == "Falha"
    assert meta["cobertura"][0]["erro"] == "falha controlada"
    assert all(item["Gráficos"] == 1 for item in meta["cobertura"][1:])
    assert eventos[-1] == (1.0, "Arquivo pronto")
    assert [v for v, _ in eventos] == sorted(v for v, _ in eventos)


def test_nenhum_grafico_nao_vira_arquivo_completo(monkeypatch, janela):
    monkeypatch.setattr(MC, "_figuras_da_secao", lambda *args: [])
    monkeypatch.setattr(MC, "_figuras_faixa_de_renda", lambda *args, **kwargs: [])
    with pytest.raises(ValueError, match="Nenhuma seção"):
        MC._deck_completo(janela, None)


def test_assinatura_muda_com_valores_historico_comentarios_e_ignora_idade(monkeypatch):
    import utils.comentarios_credito as comentarios

    historia = pd.DataFrame({"valor": [10.0, float("nan"), 20.0]}, index=pd.date_range("2025-01-31", periods=3, freq="ME"))
    janela = historia.iloc[-1:].copy()
    janela.attrs["full_history"] = historia
    doc = {"texto": "primeira leitura"}
    monkeypatch.setattr(comentarios, "carregar", lambda: doc)
    idade = [1]
    info = {"periodos": ["2025-03"], "timestamp_salvamento": "2025-04-01"}
    cache = SimpleNamespace(get_info=lambda: {**info, "idade_horas": idade[0]})
    manager = lambda: SimpleNamespace(get_cache=lambda nome: cache)
    original = MC._assinatura_deck(janela, manager)
    idade[0] = 2
    assert MC._assinatura_deck(janela, manager) == original
    janela.iloc[0, 0] = 21.0
    assert MC._assinatura_deck(janela, manager) != original
    janela.iloc[0, 0] = 20.0
    historia.iloc[0, 0] = 12.0
    assert MC._assinatura_deck(janela, manager) != original
    historia.iloc[0, 0] = 10.0
    doc["texto"] = "leitura revisada"
    assert MC._assinatura_deck(janela, manager) != original
    doc["texto"] = "primeira leitura"
    info["timestamp_salvamento"] = "2025-04-02"
    assert MC._assinatura_deck(janela, manager) != original


def test_botao_so_gera_por_pedido_e_permite_tentar_novamente(monkeypatch, janela):
    from contextlib import nullcontext

    cliques, chamadas, downloads = [False], [], []
    estado = {}
    st = SimpleNamespace(
        session_state=estado,
        markdown=lambda *args, **kwargs: None,
        caption=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        button=lambda *args, **kwargs: cliques[0],
        toggle=lambda *args, **kwargs: True,
        selectbox=lambda label, opcoes, **kwargs: opcoes[kwargs.get("index", 0)],
        progress=lambda *args, **kwargs: SimpleNamespace(progress=lambda *a, **kw: None, empty=lambda: None),
        download_button=lambda *args, **kwargs: downloads.append(kwargs["data"]),
        expander=lambda *args, **kwargs: nullcontext(),
        dataframe=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(MC, "st", st)

    def gerar(*args, **kwargs):
        chamadas.append(True)
        if len(chamadas) == 1:
            raise RuntimeError("falha temporária")
        return b"arquivo", {"completo": True, "cobertura": [{"erro": ""}],
                            "paineis": 1, "slides": 1, "secoes_glossario": 1}

    monkeypatch.setattr(MC, "_deck_completo", gerar)
    MC._botao_deck_completo(janela, None)
    assert chamadas == []
    cliques[0] = True
    MC._botao_deck_completo(janela, None)
    assert estado["_deck_completo_memo"]["erro"] == "falha temporária"
    assert downloads == []
    MC._botao_deck_completo(janela, None)
    assert len(chamadas) == 2
    assert downloads == [b"arquivo"]
    cliques[0] = False
    MC._botao_deck_completo(janela, None)
    assert len(chamadas) == 2
    revisada = janela.copy()
    revisada.iloc[0, 0] = 123456.0
    MC._botao_deck_completo(revisada, None)
    assert "valor" not in estado["_deck_completo_memo"]


def test_exportacao_manual_funciona_sem_visitar_as_abas(monkeypatch):
    from streamlit.testing.v1 import AppTest

    argumentos = []

    def gerar(wide, manager, **kwargs):
        argumentos.append((wide.index.min(), wide.index.max(), kwargs["modalidade_regiao"]))
        return b"arquivo", {"completo": True, "cobertura": [{"erro": ""}],
                            "paineis": 1, "slides": 1, "secoes_glossario": 1}

    monkeypatch.setattr(MC, "_deck_completo", gerar)
    app = AppTest.from_string('''
import pandas as pd
from tabs.mercado_credito import _botao_deck_completo
wide = pd.DataFrame({"taxa_pf_livre": [10., 11., 12., 13.]},
                    index=pd.date_range("2026-03-31", periods=4, freq="ME"))
_botao_deck_completo(wide, None)
''').run()
    assert not app.exception
    assert argumentos == []
    app.toggle(key="sgs_deck_periodo_tela").set_value(False).run()
    app.selectbox(key="sgs_deck_period_start").set_value(pd.Timestamp("2026-04-30")).run()
    app.selectbox(key="sgs_deck_period_end").set_value(pd.Timestamp("2026-05-31")).run()
    app.selectbox(key="sgs_deck_modalidade_regiao").set_value("PF - Veículos").run()
    app.button(key="sgs_gerar_deck_completo").click().run()
    assert not app.exception
    assert argumentos == [(pd.Timestamp("2026-04-30"), pd.Timestamp("2026-05-31"), "PF - Veículos")]


def test_recorte_regional_selecionado_entra_no_deck(gerenciador):
    figuras = MC._figuras_faixa_de_renda(gerenciador, modalidade_regiao="PF - Veículos")
    assert figuras[-1].layout.meta["chart_title"] == "PF - Veículos por região"
    with pytest.raises(ValueError, match="Sem dados regionais"):
        MC._figuras_faixa_de_renda(gerenciador, modalidade_regiao="PJ - Capital de giro")
