"""Testes da visão "Inadimplência SCR".

Duas camadas: a especificação em ``tabs/scr_inadimplencia.py`` (que é testável
diretamente, por não depender de Streamlit) e o renderer integrado ao módulo
de Estatísticas Crédito BC (verificado por AST, sem executar o app).
"""

from __future__ import annotations

import ast
import json
from functools import lru_cache
from pathlib import Path

import pandas as pd
import pytest

from tabs import scr_inadimplencia as T
from utils import scr_data_query as Q
from utils.ifdata_cache import scr_data as S


APP_PATH = Path(__file__).resolve().parents[1] / "app1.py"
SCR_VIEW_PATH = Path(__file__).resolve().parents[1] / "tabs" / "scr_inadimplencia_view.py"


# =============================================================================
# FIXTURES
# =============================================================================

def _fato(linhas):
    df = pd.DataFrame(linhas, columns=S.FACT_COLUMNS)
    for coluna in S.FACT_DIM_COLUMNS:
        df[coluna] = df[coluna].fillna("n/a")
    for coluna in S.METRIC_COLUMNS:
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce").fillna(0.0)
    return df


def _linha(**kwargs):
    base = {
        "data_base": "2026-06",
        "uf": "SP",
        "segmento": "Banco",
        "cliente": "PF",
        "porte": "Até 1 salário mínimo",
        "modalidade": "Empréstimos",
        "submodalidade": "Cheque especial",
        "modalidade_bcb": "PF - Outros créditos",
        "numero_de_operacoes": 10,
        "ops_suprimidas": 0,
        "carteira_ativa": 1000.0,
        "vencido_de_15_ate_90_dias": 20.0,
        "vencido_acima_de_90_dias": 50.0,
        "carteira_inadimplencia": 100.0,
        "ativo_problematico": 150.0,
        "carteira_suprimida": 0.0,
    }
    base.update(kwargs)
    return base


@pytest.fixture
def fato_multiperiodo():
    linhas = []
    for periodo in ("2026-04", "2026-05", "2026-06"):
        linhas += [
            _linha(data_base=periodo, cliente="PF", porte="Até 1 salário mínimo",
                   uf="SP", segmento="Banco", submodalidade="Cheque especial",
                   carteira_ativa=1000.0, carteira_inadimplencia=90.0),
            _linha(data_base=periodo, cliente="PF", porte="Acima de 20 salários mínimos",
                   uf="BA", segmento="Fintech", submodalidade="Crédito pessoal - sem consignação em folha de pagam.",
                   modalidade="Empréstimos", carteira_ativa=4000.0, carteira_inadimplencia=80.0),
            _linha(data_base=periodo, cliente="PJ", porte="Grande",
                   uf="RS", segmento="Banco", submodalidade="Capital de giro com teto rotativo",
                   modalidade="Empréstimos", modalidade_bcb="PJ - Capital de giro",
                   carteira_ativa=8000.0, carteira_inadimplencia=40.0),
            _linha(data_base=periodo, cliente="PJ", porte="Micro",
                   uf="AM", segmento="Financeira", submodalidade="Cartão de crédito - não migrado",
                   modalidade="Outros créditos", modalidade_bcb="PJ - Outros créditos",
                   carteira_ativa=2000.0, carteira_inadimplencia=1500.0),
        ]
    return _fato(linhas)


# =============================================================================
# ESPECIFICAÇÃO
# =============================================================================

def test_secoes_cobrem_os_recortes_pedidos():
    chaves = [secao.key for secao in T.SECOES]
    assert chaves == ["paineis", "regiao"]


def test_secoes_tem_chave_unica_e_rotulo():
    chaves = [secao.key for secao in T.SECOES]
    assert len(chaves) == len(set(chaves))
    assert all(secao.label and secao.resumo for secao in T.SECOES)


def test_apenas_regiao_e_segmento_exigem_o_grao_completo():
    # O mapa usa o grão de UF.
    exigem = {secao.key for secao in T.SECOES if secao.exige_detalhe}
    assert exigem == {"regiao"}


def test_descrever_secoes_expoe_a_tabela():
    tabela = T.descrever_secoes()
    assert len(tabela) == len(T.SECOES)
    assert set(tabela.columns) >= {"key", "label", "resumo", "exige_detalhe"}


def test_janela_padrao_esta_entre_as_disponiveis():
    assert T.JANELA_PADRAO_MESES in T.JANELAS_DISPONIVEIS


def test_tabela_criterios_pj_cobre_os_quatro_portes():
    tabela = T.tabela_criterios_pj()
    assert tabela["porte"].tolist() == S.PORTE_PJ_ORDEM
    assert all(tabela["criterio"].str.len() > 20)
    # Os limites da lei precisam estar visíveis na aba, não só no código.
    texto = " ".join(tabela["criterio"])
    for limite in ("360 mil", "4,8 mi", "300 mi", "240 mi"):
        assert limite in texto


# =============================================================================
# PANORAMA
# =============================================================================

def test_panorama_traz_kpis_serie_e_composicao(fato_multiperiodo):
    resultado = T.construir_panorama(fato_multiperiodo)
    assert set(resultado) == {"kpis", "serie", "composicao", "quebras"}
    assert not resultado["kpis"].empty
    assert set(resultado["serie"]["recorte"].astype(str)) == {"Total", "PF", "PJ"}
    assert list(resultado["composicao"].columns) == [
        "data_base", "A vencer", "Vencido 15–90d", "Vencido > 90d"
    ]


def test_panorama_composicao_fecha_com_a_carteira(fato_multiperiodo):
    comp = T.construir_panorama(fato_multiperiodo)["composicao"]
    soma = comp[["A vencer", "Vencido 15–90d", "Vencido > 90d"]].sum(axis=1)
    carteira = (
        fato_multiperiodo.groupby("data_base", observed=True)["carteira_ativa"].sum().values
    )
    assert soma.values == pytest.approx(carteira)


# =============================================================================
# PRODUTO
# =============================================================================

def test_produto_usa_apenas_modalidades_agregadas_oficiais(fato_multiperiodo):
    resultado = T.construir_por_produto(fato_multiperiodo, carteira_minima_rs_mil=0)
    produtos = resultado["ranking"]["modalidade_bcb"].astype(str).tolist()
    assert set(produtos) <= set(S.MODALIDADES_BCB)
    assert "Cartão de crédito - não migrado" not in produtos
    assert resultado["legado_ocultado"] == []


def test_produto_rejeita_modalidade_bruta_e_submodalidade(fato_multiperiodo):
    for nivel in ("modalidade", "submodalidade"):
        with pytest.raises(ValueError, match="modalidade_bcb"):
            T.construir_por_produto(
                fato_multiperiodo, nivel=nivel, carteira_minima_rs_mil=0
            )


def test_produto_rejeita_nivel_invalido(fato_multiperiodo):
    with pytest.raises(ValueError):
        T.construir_por_produto(fato_multiperiodo, nivel="cnae")


def test_produto_series_seguem_os_destaques(fato_multiperiodo):
    resultado = T.construir_por_produto(
        fato_multiperiodo,
        carteira_minima_rs_mil=0,
        destaques=["PF - Outros créditos"],
    )
    assert set(resultado["series"]["modalidade_bcb"].astype(str)) == {
        "PF - Outros créditos"
    }


def test_modalidades_disponiveis_reproduzem_filtro_oficial_do_bcb():
    assert T.modalidades_bcb_disponiveis("PF") == list(S.MODALIDADES_BCB_PF)
    assert T.modalidades_bcb_disponiveis("PJ") == list(S.MODALIDADES_BCB_PJ)
    assert len(T.modalidades_bcb_disponiveis("PF")) == 7
    assert len(T.modalidades_bcb_disponiveis("PJ")) == 9
    assert "PJ - Cheque especial e conta garantida" in T.modalidades_bcb_disponiveis("PJ")
    assert all("Capital de giro rotativo" not in item for item in S.MODALIDADES_BCB_PJ)


# =============================================================================
# RENDA / PORTE
# =============================================================================

def test_porte_pf_ordena_pela_renda_nao_pelo_valor(fato_multiperiodo):
    resultado = T.construir_por_porte(fato_multiperiodo, cliente="PF")
    ordem_saida = resultado["barras"]["porte"].astype(str).tolist()
    esperada = [p for p in Q.ordem_portes("PF") if p in ordem_saida]
    assert ordem_saida == esperada


def test_porte_pf_rotula_faixas_em_reais_quando_ha_salario_minimo(fato_multiperiodo):
    com_sm = T.construir_por_porte(fato_multiperiodo, cliente="PF", salario_minimo=1518.0)
    rotulos = dict(zip(
        com_sm["barras"]["porte"].astype(str), com_sm["barras"]["rotulo_faixa"]
    ))
    assert rotulos["Até 1 salário mínimo"] == "até R$ 1.518"


def test_porte_pf_cai_para_salarios_minimos_sem_a_serie(fato_multiperiodo):
    sem_sm = T.construir_por_porte(fato_multiperiodo, cliente="PF", salario_minimo=None)
    rotulos = dict(zip(
        sem_sm["barras"]["porte"].astype(str), sem_sm["barras"]["rotulo_faixa"]
    ))
    assert rotulos["Até 1 salário mínimo"] == "até 1 SM"


def test_porte_pj_traz_o_card_de_criterios(fato_multiperiodo):
    pj = T.construir_por_porte(fato_multiperiodo, cliente="PJ")
    assert pj["criterios_pj"] is not None
    assert T.construir_por_porte(fato_multiperiodo, cliente="PF")["criterios_pj"] is None


def test_porte_nunca_mistura_pf_e_pj(fato_multiperiodo):
    pf = T.construir_por_porte(fato_multiperiodo, cliente="PF")["barras"]
    pj = T.construir_por_porte(fato_multiperiodo, cliente="PJ")["barras"]
    assert set(pf["porte"].astype(str)).isdisjoint(set(pj["porte"].astype(str)))


def test_porte_indexado_normaliza_cada_serie_em_100(fato_multiperiodo):
    resultado = T.construir_por_porte(fato_multiperiodo, cliente="PF", indexar_series=True)
    series = resultado["series"]
    assert "valor_indexado" in series.columns
    primeiros = series.dropna(subset=["valor_indexado"]).groupby(
        "porte", observed=True
    )["valor_indexado"].first()
    assert all(valor == pytest.approx(100.0) for valor in primeiros)


# =============================================================================
# REGIÃO
# =============================================================================

def test_regiao_monta_mapa_com_codigo_ibge(fato_multiperiodo):
    resultado = T.construir_por_regiao(fato_multiperiodo)
    mapa = resultado["mapa"]
    assert {"uf", "uf_nome", "regiao", "codigo_ibge"} <= set(mapa.columns)
    sp = mapa[mapa["uf"] == "SP"].iloc[0]
    assert sp["codigo_ibge"] == "35"
    assert sp["regiao"] == "Sudeste"


def test_regiao_ancora_escala_na_media_brasil(fato_multiperiodo):
    resultado = T.construir_por_regiao(fato_multiperiodo)
    jun = Q.filtrar(fato_multiperiodo, data_base_inicial="2026-06", data_base_final="2026-06")
    esperado = float(Q.agregar(jun, "inadimplencia")["valor"].iloc[0])
    assert resultado["media_brasil"] == pytest.approx(esperado)


def test_regiao_calcula_participacao_sobre_carteira_ativa_e_ordena_ufs():
    fato = _fato([
        _linha(uf="SP", carteira_ativa=6000.0, carteira_inadimplencia=600.0),
        _linha(uf="RJ", carteira_ativa=3000.0, carteira_inadimplencia=600.0),
        _linha(uf="BA", carteira_ativa=1000.0, carteira_inadimplencia=500.0),
    ])

    resultado = T.construir_por_regiao(fato)
    mapa = resultado["mapa"]

    assert resultado["carteira_brasil_rs_mil"] == pytest.approx(10000.0)
    shares = dict(zip(mapa["uf"].astype(str), mapa["participacao_carteira"]))
    assert shares == pytest.approx({"SP": 0.6, "RJ": 0.3, "BA": 0.1})
    sudeste = mapa[mapa["regiao"].astype(str) == "Sudeste"]
    assert sudeste["uf"].astype(str).tolist() == ["SP", "RJ"]
    assert sudeste["ordem_na_regiao"].tolist() == [0, 1]


def test_regiao_series_seguem_ordem_norte_sul(fato_multiperiodo):
    series = T.construir_por_regiao(fato_multiperiodo)["series"]
    ordem = series["regiao"].astype(str).drop_duplicates().tolist()
    esperada = [r for r in S.ORDEM_REGIOES if r in ordem]
    assert ordem == esperada


def test_regiao_rejeita_nivel_invalido(fato_multiperiodo):
    with pytest.raises(ValueError):
        T.construir_por_regiao(fato_multiperiodo, nivel="municipio")


# =============================================================================
# GEOJSON
# =============================================================================

def test_geojson_das_ufs_esta_versionado():
    assert T.GEOJSON_UF_PATH.exists(), (
        "malha de UFs ausente; rebaixe de "
        "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR"
        "?formato=application/vnd.geo+json&qualidade=minima&intrarregiao=UF"
    )


def test_geojson_casa_com_os_codigos_ibge_da_dimensao():
    geojson = T.carregar_geojson_uf()
    assert geojson is not None
    codigos_malha = {
        feature["properties"]["codarea"] for feature in geojson["features"]
    }
    codigos_dim = {f"{codigo}" for codigo in S.UF_IBGE.values()}
    assert codigos_malha == codigos_dim


def test_geojson_ausente_nao_quebra(monkeypatch, tmp_path):
    monkeypatch.setattr(T, "GEOJSON_UF_PATH", tmp_path / "nao_existe.geojson")
    assert T.carregar_geojson_uf() is None


# =============================================================================
# SEGMENTO
# =============================================================================

def test_segmento_usa_a_vigencia_da_dimensao(fato_multiperiodo):
    dim = pd.DataFrame([
        {"segmento": "Fintech", "primeira_data_base": "2019-05"},
        {"segmento": "Banco", "primeira_data_base": "2012-07"},
    ])
    resultado = T.construir_por_segmento(fato_multiperiodo, dim_segmento=dim)
    vigencia = dict(zip(
        resultado["vigencia"]["segmento"], resultado["vigencia"]["primeira_data_base"]
    ))
    assert vigencia["Fintech"] == "2019-05"


def test_segmento_deriva_vigencia_do_fato_sem_dimensao(fato_multiperiodo):
    resultado = T.construir_por_segmento(fato_multiperiodo, dim_segmento=None)
    assert set(resultado["vigencia"]["segmento"]) == set(
        fato_multiperiodo["segmento"].astype(str).unique()
    )


def test_segmento_ordena_bancos_antes_de_outros(fato_multiperiodo):
    barras = T.construir_por_segmento(fato_multiperiodo)["barras"]
    ordem = barras["segmento"].astype(str).tolist()
    esperada = [s for s in S.ORDEM_SEGMENTOS if s in ordem]
    assert ordem == esperada


# =============================================================================
# RODAPÉ
# =============================================================================

def test_rodape_reporta_supressao_e_notas(fato_multiperiodo):
    rodape = T.rodape(fato_multiperiodo)
    assert rodape["primeira_data_base_disponivel"] == S.PRIMEIRA_DATA_BASE
    assert "supressao" in rodape
    assert any("CEP" in nota for nota in rodape["notas"])
    assert any("IF.data" in nota for nota in rodape["notas"])
    assert all(fonte["url"].startswith("https://") for fonte in rodape["fontes"])


def test_construtores_aceitam_frame_vazio():
    vazio = _fato([]).iloc[0:0]
    assert T.construir_panorama(vazio)["kpis"].empty
    assert T.construir_por_produto(vazio, carteira_minima_rs_mil=0)["ranking"].empty
    assert T.construir_por_porte(vazio, cliente="PF")["barras"].empty
    assert T.construir_por_regiao(vazio)["mapa"].empty
    assert T.construir_por_segmento(vazio)["barras"].empty


# =============================================================================
# ROTA EM app1.py
# =============================================================================

@lru_cache(maxsize=1)
def _app_source() -> str:
    return APP_PATH.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _scr_route_source() -> str:
    return SCR_VIEW_PATH.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _scr_route_tree() -> ast.Module:
    return ast.parse(_scr_route_source())


def test_rota_existe_e_e_unica():
    assert _scr_route_source().count("def render_scr_inadimplencia(") == 1
    assert 'elif menu == "Inadimplência (SCR)":' not in _app_source()


def test_menu_registra_a_aba():
    fonte = _app_source()
    assert '"Estatísticas Crédito BC": ["mercado_credito_sgs", "scr_data"]' in fonte
    mercado = (APP_PATH.parent / "tabs" / "mercado_credito.py").read_text(encoding="utf-8")
    assert '"Inad por Faixa de Renda"' in mercado
    assert "render_scr_inadimplencia(get_cache_manager)" in mercado


def test_aba_declarada_em_atualizar_base():
    # A aba "Atualizar Base" tem que oferecer o cache novo, senão ele nunca é
    # atualizado pela UI.
    fonte = _app_source()
    inicio = fonte.index('"Atualizar Base": [')
    fim = fonte.index("]", inicio)
    assert f'"{T.CACHE_NAME}"' in fonte[inicio:fim]


def test_app_recarrega_modulo_scr_antigo_no_hot_reload():
    fonte = _app_source()
    assert '_EXPECTED_SCR_RELEASE_TAG = "v1.2-scr-cache"' in fonte
    assert 'getattr(_ifdata_scr_data, "SCR_RELEASE_TAG", None)' in fonte
    assert "importlib.reload(_ifdata_scr_data)" in fonte
    assert "_ifdata_cache_package._manager = None" in fonte


def test_rota_usa_a_camada_de_consulta_e_a_spec():
    fonte = _scr_route_source()
    assert "from tabs import scr_inadimplencia as scr_spec" in fonte
    assert "from utils import scr_data_query as scr_q" in fonte


def test_rota_nunca_tira_media_de_percentual():
    # A regra da aba é razão de somas. Qualquer `.mean()` aqui é suspeito.
    for node in ast.walk(_scr_route_tree()):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"mean", "median"}, (
                "a rota não pode tirar média de taxas: use scr_data_query.agregar"
            )


def test_rota_cacheia_o_carregamento_pesado():
    fonte = _scr_route_source()
    assert "@st.cache_data" in fonte
    assert "def _detalhe(" in fonte


def test_rota_renderiza_todas_as_secoes():
    fonte = _scr_route_source()
    assert 'st.tabs(["Painéis", "Brasil e regiões"])' in fonte
    assert [secao.key for secao in T.SECOES] == ["paineis", "regiao"]
    assert "px.choropleth" in fonte
    assert "_figura_heatmap_ufs" not in fonte
    assert '"Recorte", ["uf", "regiao"]' in fonte
    assert '"Baixar PPTX desta aba"' in fonte


def test_rota_protege_secoes_que_exigem_grao_completo():
    fonte = _scr_route_source()
    assert 'st.tabs(["Painéis", "Brasil e regiões"])' in fonte
    assert "Por segmento de IF" not in fonte


def test_rota_coloca_alertas_no_popover_e_remove_rodape_verbose():
    fonte = _scr_route_source()
    assert 'st.popover("i"' in fonte
    assert "Alertas de legibilidade" in fonte
    assert "scr_spec.rodape(" not in fonte
    assert "st.warning(_pn_texto" not in fonte
    assert "st.caption(f\"ℹ️" not in fonte


def test_rota_scr_tem_intervalo_mensal_flexivel_e_ordem_recente_primeiro():
    fonte = _scr_route_source()
    assert '"Período inicial"' in fonte
    assert '"Período final"' in fonte
    assert '"Mais recente"' in fonte
    assert "reversed(periodos_timestamp)" in fonte
    assert "formatar_competencia" in fonte


def test_rota_scr_expoe_somente_modalidades_oficiais():
    fonte = _scr_route_source()
    assert 'nivel_produto="modalidade_bcb"' in fonte
    assert '"nível de produto"' not in fonte
    assert '"submodalidade", "modalidade"' not in fonte


def test_rota_marca_quebras_de_serie():
    fonte = _scr_route_source()
    assert "_marcar_quebras" in fonte
    assert "scr_spec.marcar_quebras" in fonte


# =============================================================================
# APOIO À RENDERIZAÇÃO
# =============================================================================

@pytest.mark.parametrize(
    "delta,formato,esperado",
    [
        (-0.0021, "percentual", "-0,21 p.p. m/m"),
        (0.0089, "percentual", "+0,89 p.p. m/m"),
        (0.10308, "monetario", "+10,3% m/m"),
        (None, "percentual", None),
    ],
)
def test_formatar_delta_kpi(delta, formato, esperado):
    # A vírgula decimal não pode comer o ponto de "p.p.".
    assert T.formatar_delta_kpi(delta, formato) == esperado


def test_marcar_quebras_funciona_em_eixo_categorico():
    # As data-bases são strings ("2025-01"), então o eixo é categórico. O
    # `add_vline` do Plotly com `annotation_text` estoura nesse caso ao tentar
    # tirar a média de x0 e x1 — a anotação tem que ir separada.
    px = pytest.importorskip("plotly.express")
    fig = px.line(
        pd.DataFrame({"data_base": ["2024-12", "2025-01", "2025-02"], "valor": [1, 2, 3]}),
        x="data_base",
        y="valor",
    )
    quebras = Q.quebras_no_intervalo("2024-12", "2025-02", "ativo_problematico")
    assert quebras, "a quebra de jan/2025 deveria estar no intervalo"

    T.marcar_quebras(fig, quebras)

    assert len(fig.layout.shapes) == len(quebras)
    assert len(fig.layout.annotations) == len(quebras)
    assert fig.layout.annotations[0].text == "2025-01"


def test_marcar_quebras_sem_quebras_nao_altera_figura():
    px = pytest.importorskip("plotly.express")
    fig = px.line(pd.DataFrame({"data_base": ["2026-06"], "valor": [1]}), x="data_base", y="valor")
    T.marcar_quebras(fig, [])
    assert not fig.layout.shapes


# =============================================================================
# PAINÉIS
# =============================================================================

def _fato_paineis():
    """Dois produtos, três faixas de renda PF, quatro data-bases."""
    linhas = []
    for i, periodo in enumerate(("2026-03", "2026-04", "2026-05", "2026-06")):
        for produto, modalidade_bcb, base in (
            ("Cheque especial", "PF - Outros créditos", 0.10),
            ("Custeio", "PF - Rural e agroindustrial", 0.04),
        ):
            for faixa, mult in (
                ("Até 1 salário mínimo", 1.6),
                ("Mais de 1 a 2 salários mínimos", 1.2),
                ("Acima de 20 salários mínimos", 0.5),
            ):
                linhas.append(_linha(
                    data_base=periodo, cliente="PF", porte=faixa, uf="SP",
                    submodalidade=produto, modalidade="Empréstimos",
                    modalidade_bcb=modalidade_bcb,
                    carteira_ativa=1000.0,
                    carteira_inadimplencia=1000.0 * base * mult * (1 + i * 0.05),
                ))
    return _fato(linhas)


def test_paineis_um_por_produto():
    paineis = T.construir_paineis(
        _fato_paineis(),
        produtos=["PF - Outros créditos", "PF - Rural e agroindustrial"],
        quebra="renda",
    )
    assert [p.produto for p in paineis] == [
        "PF - Outros créditos", "PF - Rural e agroindustrial"
    ]
    assert all("Inad (> 90 d)" in p.titulo for p in paineis)
    assert all(p.subtitulo == "Por Faixa Salário Mínimo - % carteira" for p in paineis)


def test_paineis_incluem_linha_todos_como_referencia():
    painel = T.construir_paineis(
        _fato_paineis(), produtos=["PF - Outros créditos"], quebra="renda", incluir_total=True
    )[0]
    assert T.SERIE_TOTAL in painel.ordem_series
    assert painel.ordem_series[-1] == T.SERIE_TOTAL   # sempre por último
    assert painel.cores[T.SERIE_TOTAL] == T.COR_PRETO
    assert T.SERIE_TOTAL in painel.tracejadas

    sem_total = T.construir_paineis(
        _fato_paineis(), produtos=["PF - Outros créditos"], quebra="renda", incluir_total=False
    )[0]
    assert T.SERIE_TOTAL not in sem_total.ordem_series


def test_paineis_ordenam_faixas_pela_renda_nao_pelo_valor():
    painel = T.construir_paineis(
        _fato_paineis(), produtos=["PF - Outros créditos"], quebra="renda", incluir_total=False
    )[0]
    esperada = [p for p in Q.ordem_portes("PF") if p in painel.ordem_series]
    assert list(painel.ordem_series) == esperada


def test_paineis_usam_rampa_ordenada_na_renda():
    painel = T.construir_paineis(
        _fato_paineis(), produtos=["PF - Outros créditos"], quebra="renda", incluir_total=False
    )[0]
    cores = [painel.cores[s] for s in painel.ordem_series]
    # Dimensão ordenada usa a rampa, e a faixa mais baixa recebe o laranja Itaú.
    assert cores[0] == T.COR_LARANJA
    assert len(set(cores)) == len(cores), "cores repetidas tornam as faixas indistinguíveis"
    assert all(c in T.RAMPA_ORDENADA for c in cores)


def test_paleta_e_so_laranja_preto_e_cinza():
    # Itaú BBA: nada de azul, verde ou vermelho na paleta institucional.
    for cor in [*T.RAMPA_ORDENADA, *T.PALETA_CATEGORICA, T.COR_TOTAL]:
        r, g, b = (int(cor[i:i + 2], 16) for i in (1, 3, 5))
        cinza = abs(r - g) < 12 and abs(g - b) < 12
        laranja = r > g > b and r > 120
        assert cinza or laranja, f"{cor} não é cinza nem laranja"


def test_paineis_rejeitam_quebra_desconhecida():
    with pytest.raises(ValueError):
        T.construir_paineis(_fato_paineis(), produtos=["PF - Outros créditos"], quebra="cnae")


def test_faixas_padrao_da_renda_sao_as_sete_principais():
    faixas = T.faixas_padrao("renda")
    assert len(faixas) == 7
    assert "Sem rendimento" not in faixas          # pouca carteira, rouba cor
    assert S.PORTE_INDISPONIVEL not in faixas


def test_rotulo_serie_encurta_faixa_de_renda():
    quebra = T.QUEBRAS_POR_KEY["renda"]
    assert T.rotulo_serie("Mais de 1 a 2 salários mínimos", quebra) == "1 a 2"
    assert T.rotulo_serie("Acima de 20 salários mínimos", quebra) == "Acima 20"
    # Dimensão sem dicionário de apelidos passa direto.
    assert T.rotulo_serie("Nordeste", T.QUEBRAS_POR_KEY["regiao"]) == "Nordeste"


@pytest.mark.parametrize("valor,esperado", [
    (0.0463, "4,63%"), (0.1642, "16,42%"), (0.0, "0,00%"), (None, "—"),
])
def test_formatar_percentual_2casas(valor, esperado):
    assert T.formatar_percentual_2casas(valor) == esperado


# =============================================================================
# LEGIBILIDADE
# =============================================================================

def test_legibilidade_alerta_com_series_demais():
    linhas = []
    for faixa in [*Q.ordem_portes("PF")]:
        linhas.append(_linha(
            porte=faixa,
            submodalidade="Cheque especial",
            modalidade_bcb="PF - Outros créditos",
            cliente="PF",
        ))
    paineis = T.construir_paineis(
        _fato(linhas), produtos=["PF - Outros créditos"], quebra="renda",
        faixas=Q.ordem_portes("PF"), incluir_total=True,
    )
    avisos = T.avaliar_legibilidade(paineis)
    assert any("linhas no mesmo painel" in a["mensagem"] for a in avisos)
    assert any(a["nivel"] == "alerta" for a in avisos)


def test_legibilidade_detecta_rotulos_colados():
    # Duas faixas terminando a 0,01 p.p. uma da outra.
    linhas = [
        _linha(porte="Até 1 salário mínimo", cliente="PF", submodalidade="X",
               modalidade_bcb="PF - Outros créditos",
               carteira_ativa=1000.0, carteira_inadimplencia=50.0),
        _linha(porte="Acima de 20 salários mínimos", cliente="PF", submodalidade="X",
               modalidade_bcb="PF - Outros créditos",
               carteira_ativa=1000.0, carteira_inadimplencia=50.1),
    ]
    painel = T.construir_paineis(
        _fato(linhas), produtos=["PF - Outros créditos"], quebra="renda", incluir_total=False
    )[0]
    assert T.rotulos_sobrepostos(painel)


def test_legibilidade_avisa_carteira_pequena():
    linhas = [_linha(porte="Até 1 salário mínimo", cliente="PF", submodalidade="Nicho",
                     modalidade_bcb="PF - Outros créditos",
                     carteira_ativa=100.0, carteira_inadimplencia=10.0)]
    paineis = T.construir_paineis(
        _fato(linhas), produtos=["PF - Outros créditos"], quebra="renda"
    )
    assert any("base pequena" in a["mensagem"] for a in T.avaliar_legibilidade(paineis))


def test_legibilidade_nao_reclama_de_painel_saudavel():
    paineis = T.construir_paineis(
        _fato_paineis(), produtos=["PF - Outros créditos"], quebra="renda", incluir_total=False
    )
    alertas = [a for a in T.avaliar_legibilidade(paineis) if a["nivel"] == "alerta"]
    assert not alertas
