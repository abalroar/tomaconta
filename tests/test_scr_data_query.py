"""Testes da camada de consulta do SCR.data.

O invariante central é o da razão de somas: toda taxa é recalculada como
``Σ numerador / Σ denominador`` depois do filtro. Média de razões sobre
carteiras de tamanhos diferentes não significa nada, e é o erro mais fácil de
cometer nesta aba.
"""

from __future__ import annotations

import pandas as pd
import pytest

from utils import scr_data_query as Q
from utils.ifdata_cache import scr_data as S


def _fato(linhas):
    """Monta um fato já no formato materializado (valores em R$ mil)."""
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


# =============================================================================
# RAZÃO DE SOMAS
# =============================================================================

def test_taxa_e_razao_de_somas_nao_media_de_razoes():
    # UF pequena com taxa altíssima ao lado de UF grande com taxa baixa.
    df = _fato([
        _linha(uf="RR", carteira_ativa=10.0, carteira_inadimplencia=5.0),      # 50%
        _linha(uf="SP", carteira_ativa=9990.0, carteira_inadimplencia=99.9),   # 1%
    ])
    total = Q.agregar(df, "inadimplencia")
    esperado = (5.0 + 99.9) / (10.0 + 9990.0)

    assert float(total["valor"].iloc[0]) == pytest.approx(esperado)
    # A média das razões daria ~25,5%, quase 25x o valor correto.
    por_uf = Q.agregar(df, "inadimplencia", by=["uf"])
    assert float(por_uf["valor"].mean()) > 10 * esperado


def test_agregacao_devolve_denominador_junto():
    df = _fato([_linha(carteira_ativa=1000.0, carteira_inadimplencia=100.0)])
    resultado = Q.agregar(df, "inadimplencia", by=["uf"])
    assert float(resultado["denominador"].iloc[0]) == pytest.approx(1000.0)
    assert float(resultado["numerador"].iloc[0]) == pytest.approx(100.0)


def test_taxa_com_denominador_zero_vira_nulo():
    df = _fato([_linha(carteira_ativa=0.0, carteira_inadimplencia=0.0)])
    resultado = Q.agregar(df, "inadimplencia", by=["uf"])
    assert pd.isna(resultado["valor"].iloc[0])


def test_metrica_de_nivel_soma_sem_denominador():
    df = _fato([_linha(carteira_ativa=1000.0), _linha(uf="RJ", carteira_ativa=500.0)])
    resultado = Q.agregar(df, "carteira_ativa")
    assert float(resultado["valor"].iloc[0]) == pytest.approx(1500.0)
    assert pd.isna(resultado["denominador"].iloc[0])


def test_agregar_vazio_devolve_frame_com_colunas():
    resultado = Q.agregar(_fato([]).iloc[0:0], "inadimplencia", by=["uf"])
    assert resultado.empty
    assert list(resultado.columns) == ["uf", "numerador", "denominador", "valor"]


def test_agregar_rejeita_coluna_inexistente():
    with pytest.raises(KeyError):
        Q.agregar(_fato([_linha()]), "inadimplencia", by=["cnae_ocupacao"])


@pytest.mark.parametrize("chave", sorted(Q.METRICAS))
def test_todas_as_metricas_agregam(chave):
    resultado = Q.agregar(_fato([_linha()]), chave)
    assert len(resultado) == 1


def test_obter_metrica_aceita_chave_e_rotulo():
    assert Q.obter_metrica("inadimplencia").chave == "inadimplencia"
    assert Q.obter_metrica("Inadimplência").chave == "inadimplencia"
    with pytest.raises(KeyError):
        Q.obter_metrica("nao_existe")


def test_inadimplencia_e_maior_que_vencido_90_por_construcao():
    # O numerador da inadimplência é o saldo inteiro da operação contaminada,
    # não só a parcela vencida.
    df = _fato([_linha(carteira_inadimplencia=100.0, vencido_acima_de_90_dias=50.0)])
    inad = float(Q.agregar(df, "inadimplencia")["valor"].iloc[0])
    vencido = float(Q.agregar(df, "vencido_90")["valor"].iloc[0])
    assert inad > vencido


# =============================================================================
# FILTRO
# =============================================================================

def test_filtra_por_cliente_e_porte():
    df = _fato([
        _linha(cliente="PF", porte="Até 1 salário mínimo"),
        _linha(cliente="PJ", porte="Micro"),
    ])
    assert len(Q.filtrar(df, cliente="PF")) == 1
    assert len(Q.filtrar(df, porte=["Micro", "Pequeno"])) == 1
    assert len(Q.filtrar(df)) == 2


def test_filtra_por_intervalo_de_data_base():
    df = _fato([
        _linha(data_base="2025-12"),
        _linha(data_base="2026-03"),
        _linha(data_base="2026-06"),
    ])
    recorte = Q.filtrar(df, data_base_inicial="2026-01", data_base_final="2026-05")
    assert recorte["data_base"].tolist() == ["2026-03"]


def test_filtra_por_regiao_derivando_de_uf():
    df = _fato([_linha(uf="SP"), _linha(uf="BA"), _linha(uf="RS")])
    recorte = Q.filtrar(df, regiao="Nordeste")
    assert recorte["uf"].tolist() == ["BA"]


def test_adicionar_regiao_e_idempotente():
    df = Q.adicionar_regiao(_fato([_linha(uf="SP")]))
    assert df["regiao"].tolist() == ["Sudeste"]
    assert Q.adicionar_regiao(df)["regiao"].tolist() == ["Sudeste"]


def test_excluir_legado_remove_cartao_nao_migrado():
    df = _fato([
        _linha(submodalidade="Cheque especial"),
        _linha(submodalidade="Cartão de crédito - não migrado"),
    ])
    assert len(Q.filtrar(df, excluir_legado=True)) == 1


# =============================================================================
# ORDENS CATEGÓRICAS
# =============================================================================

def test_ordem_portes_segue_a_renda_com_indisponivel_no_fim():
    ordem = Q.ordem_portes("PF")
    assert ordem[0] == "Sem rendimento"
    assert ordem[-1] == S.PORTE_INDISPONIVEL
    assert ordem.index("Mais de 1 a 2 salários mínimos") < ordem.index("Acima de 20 salários mínimos")


def test_ordem_portes_pj_segue_o_faturamento():
    assert Q.ordem_portes("PJ") == ["Micro", "Pequeno", "Médio", "Grande", S.PORTE_INDISPONIVEL]


def test_ordem_portes_rejeita_cliente_invalido():
    with pytest.raises(ValueError):
        Q.ordem_portes("PJF")


def test_ordenar_categorico_preserva_valores_desconhecidos():
    # Uma categoria nova do BCB não pode desaparecer da tela.
    df = pd.DataFrame({"porte": ["Grande", "Categoria Nova", "Micro"]})
    ordenado = Q.ordenar_categorico(df, "porte", Q.ordem_portes("PJ"))
    assert ordenado["porte"].astype(str).tolist() == ["Micro", "Grande", "Categoria Nova"]


def test_agregacao_ordena_regiao_de_norte_a_sul():
    df = _fato([_linha(uf=uf) for uf in ("RS", "SP", "BA", "AM", "GO")])
    resultado = Q.agregar(Q.adicionar_regiao(df), "inadimplencia", by=["regiao"])
    assert resultado["regiao"].astype(str).tolist() == S.ORDEM_REGIOES


# =============================================================================
# RANKING E MATRIZ
# =============================================================================

def test_ranking_aplica_corte_de_materialidade():
    df = _fato([
        _linha(submodalidade="Produto minúsculo", carteira_ativa=1.0, carteira_inadimplencia=0.9),
        _linha(submodalidade="Cheque especial", carteira_ativa=5000.0, carteira_inadimplencia=500.0),
    ])
    completo = Q.ranking(df, "submodalidade", carteira_minima_rs_mil=0)
    filtrado = Q.ranking(df, "submodalidade", carteira_minima_rs_mil=100.0)

    assert completo["submodalidade"].astype(str).iloc[0] == "Produto minúsculo"
    assert filtrado["submodalidade"].astype(str).tolist() == ["Cheque especial"]


def test_ranking_exclui_legado_por_padrao():
    df = _fato([
        _linha(submodalidade="Cartão de crédito - não migrado", carteira_ativa=1000.0, carteira_inadimplencia=800.0),
        _linha(submodalidade="Cheque especial", carteira_ativa=1000.0, carteira_inadimplencia=100.0),
    ])
    assert Q.ranking(df, "submodalidade")["submodalidade"].astype(str).tolist() == ["Cheque especial"]
    incluindo = Q.ranking(df, "submodalidade", excluir_legado=False)
    assert len(incluindo) == 2


def test_ranking_respeita_limite_e_ordem():
    df = _fato([
        _linha(uf="SP", carteira_ativa=1000.0, carteira_inadimplencia=10.0),
        _linha(uf="RJ", carteira_ativa=1000.0, carteira_inadimplencia=300.0),
        _linha(uf="BA", carteira_ativa=1000.0, carteira_inadimplencia=200.0),
    ])
    topo = Q.ranking(df, "uf", limite=2)
    assert topo["uf"].astype(str).tolist() == ["RJ", "BA"]
    assert Q.ranking(df, "uf", ascendente=True)["uf"].astype(str).iloc[0] == "SP"


def test_matriz_cruza_duas_dimensoes():
    df = _fato([
        _linha(porte="Micro", uf="SP", carteira_ativa=1000.0, carteira_inadimplencia=100.0),
        _linha(porte="Grande", uf="SP", carteira_ativa=1000.0, carteira_inadimplencia=10.0),
    ])
    tabela = Q.matriz(df, "porte", "uf", "inadimplencia")
    assert tabela.loc["Micro", "SP"] == pytest.approx(0.10)
    assert tabela.loc["Grande", "SP"] == pytest.approx(0.01)


def test_matriz_respeita_ordem_explicita():
    df = _fato([_linha(porte=p) for p in ("Grande", "Micro", "Médio")])
    tabela = Q.matriz(df, "porte", "uf", ordem_linhas=Q.ordem_portes("PJ"))
    assert tabela.index.tolist() == ["Micro", "Médio", "Grande"]


# =============================================================================
# KPIs E JANELA
# =============================================================================

def test_kpis_calculam_delta_mensal_e_anual():
    linhas = []
    for periodo, inad in (("2025-06", 40.0), ("2026-05", 120.0), ("2026-06", 100.0)):
        linhas.append(_linha(data_base=periodo, carteira_ativa=1000.0, carteira_inadimplencia=inad))
    resultado = Q.kpis(_fato(linhas), metricas=["inadimplencia"]).iloc[0]

    assert resultado["valor"] == pytest.approx(0.10)
    # Percentual: delta em pontos percentuais.
    assert resultado["delta_mm"] == pytest.approx(-0.02)
    assert resultado["delta_12m"] == pytest.approx(0.06)


def test_kpis_delta_de_nivel_e_relativo():
    linhas = [
        _linha(data_base="2026-05", carteira_ativa=1000.0),
        _linha(data_base="2026-06", carteira_ativa=1100.0),
    ]
    resultado = Q.kpis(_fato(linhas), metricas=["carteira_ativa"]).iloc[0]
    assert resultado["delta_mm"] == pytest.approx(0.10)


def test_kpis_sem_comparativo_devolvem_none():
    resultado = Q.kpis(_fato([_linha(data_base="2026-06")]), metricas=["inadimplencia"]).iloc[0]
    assert resultado["delta_mm"] is None
    assert resultado["delta_12m"] is None


def test_janela_de_data_bases():
    assert Q.janela_de_data_bases("2026-06", 36) == ("2023-07", "2026-06")
    assert Q.janela_de_data_bases("2026-06", 1) == ("2026-06", "2026-06")
    with pytest.raises(ValueError):
        Q.janela_de_data_bases("2026-06", 0)


def test_anos_da_janela_cobre_o_intervalo():
    assert Q.anos_da_janela("2026-06", 36) == [2023, 2024, 2025, 2026]
    assert Q.anos_da_janela("2026-06", 6) == [2026]


# =============================================================================
# FAIXAS EM REAIS
# =============================================================================

def test_rotulos_em_reais_usam_o_salario_minimo():
    rotulos = Q.rotular_faixas_em_reais(1518.0)
    assert rotulos["Até 1 salário mínimo"] == "até R$ 1.518"
    assert rotulos["Mais de 1 a 2 salários mínimos"] == "R$ 1.518 a R$ 3.036"
    assert rotulos["Acima de 20 salários mínimos"] == "acima de R$ 30.360"
    assert rotulos["Sem rendimento"] == "sem renda"


def test_rotulos_caem_para_salarios_minimos_sem_a_serie():
    assert Q.rotular_faixas_em_reais(None) == S.PORTE_PF_ROTULO_CURTO
    assert Q.rotular_faixas_em_reais(0) == S.PORTE_PF_ROTULO_CURTO


def test_busca_salario_minimo_nao_propaga_erro_de_rede():
    class SessaoQuebrada:
        def get(self, *args, **kwargs):
            raise RuntimeError("sem rede")

    serie = Q.buscar_salario_minimo(session=SessaoQuebrada())
    assert serie.empty


# =============================================================================
# QUALIDADE
# =============================================================================

def test_quebras_filtradas_por_intervalo_e_metrica():
    assert len(Q.quebras_no_intervalo("2012-07", "2026-06")) == 2
    assert Q.quebras_no_intervalo("2020-01", "2024-12") == []
    ap = Q.quebras_no_intervalo("2012-07", "2026-06", "ativo_problematico")
    assert [q["data_base"] for q in ap] == ["2025-01"]


def test_resumo_supressao_usa_a_carteira_das_linhas_suprimidas():
    # A linha do fato agrega várias linhas-fonte: parte da carteira teve a
    # contagem suprimida, parte não. O share tem que refletir só a parte.
    df = _fato([
        _linha(carteira_ativa=1000.0, carteira_suprimida=100.0, ops_suprimidas=3),
        _linha(uf="RJ", carteira_ativa=1000.0, carteira_suprimida=0.0, ops_suprimidas=0),
    ])
    resumo = Q.resumo_supressao(df)
    assert resumo["linhas_suprimidas"] == 3
    assert resumo["carteira_suprimida_rs_mil"] == pytest.approx(100.0)
    assert resumo["share_carteira"] == pytest.approx(0.05)


def test_resumo_supressao_de_frame_vazio():
    resumo = Q.resumo_supressao(_fato([]).iloc[0:0])
    assert resumo["linhas_suprimidas"] == 0
    assert resumo["share_carteira"] is None


# =============================================================================
# FORMATAÇÃO
# =============================================================================

@pytest.mark.parametrize(
    "valor,formato,esperado",
    [
        (0.0463, "percentual", "4,63%"),
        (None, "percentual", "—"),
        (1234, "contagem", "1.234"),
    ],
)
def test_formatar_valor(valor, formato, esperado):
    assert Q.formatar_valor(valor, formato) == esperado


@pytest.mark.parametrize(
    "valor_em_mil,esperado",
    [
        (7_637_108_040.0, "R$ 7,6 tri"),
        (69_040_000.0, "R$ 69,0 bi"),
        (11_780.0, "R$ 11,8 mi"),
        (5.0, "R$ 5,0 mil"),
    ],
)
def test_formatar_reais_de_mil(valor_em_mil, esperado):
    assert Q.formatar_reais_de_mil(valor_em_mil) == esperado
