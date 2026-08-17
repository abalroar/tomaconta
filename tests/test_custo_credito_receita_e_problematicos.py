"""Testes das métricas de cobertura ampla: PDD/Receita e Ativos Problemáticos.

As duas métricas foram adicionadas por cobrirem mais de mil instituições e mais de
70% do saldo do SFN, critério que as separa das razões de estágio do Cadoc 4060.
Os invariantes fixados aqui são os que distinguem cada uma:

- `Custo de Crédito / Receita de Crédito (%)` é uma razão entre dois fluxos do mesmo
  período, logo **não** pode depender do fator de anualização;
- `Ativos Problemáticos / Carteira Total` sai inteiramente do Relatório 16 e nunca
  pode ser preenchida por outra fonte nem imputada como zero.
"""

import math

import pandas as pd
import pytest

from utils.ifdata_cache.derived_metrics import (
    DERIVED_METRICS,
    METRIC_ATIVOS_PROBLEMATICOS_CARTEIRA,
    METRIC_CUSTO_CREDITO,
    METRIC_CUSTO_CREDITO_RECEITA,
    build_derived_metrics,
)
from utils.ifdata_cache.critical_screens import (
    CRITICAL_EXTRA_METRICS,
    build_critical_screens_dataframe,
)
from utils.ifdata_cache.metric_registry import (
    DERIVED_METRIC_KEYS,
    METRIC_REGISTRY,
    get_derived_metric_formula_map,
)
from tabs.peers_config import (
    PEERS_GLOSSARIO_RESUMIDO,
    PEERS_RATIO_COMPONENTS,
    PEERS_TABELA_LAYOUT,
    PEERS_TRACE_COMPONENTS,
)


TOL = 1e-6
PERIODOS = ["1/2025", "2/2025", "3/2025", "4/2025"]


def _df_dre(instituicao="Banco A", periodos=None, f3=None, c=None, **overrides):
    periodos = list(periodos or PERIODOS)
    n = len(periodos)
    dados = {
        "Instituição": [instituicao] * n,
        "Período": periodos,
        "Resultado com Perda Esperada (f)": [-1.0] * n,
        "Resultado com Perda Esperada de Operações de Crédito (f3)": list(f3 if f3 is not None else [-1.0] * n),
        "Rendas de Operações de Crédito (c)": list(c if c is not None else [10.0] * n),
        "Rendas de Arrendamento Financeiro (d)": [10.0] * n,
        "Rendas de Outras Operações com Características de Concessão de Crédito (e)": [10.0] * n,
        "Rendas de Aplicações Interfinanceiras de Liquidez (a)": [5.0] * n,
        "Rendas de Títulos e Valores Mobiliários (b)": [5.0] * n,
        "Despesas de Captações (g)": [1.0] * n,
    }
    dados.update(overrides)
    return pd.DataFrame(dados)


def _df_principal(instituicao="Banco A", periodos=None):
    periodos = list(periodos or PERIODOS)
    return pd.DataFrame(
        {
            "Instituição": [instituicao] * len(periodos),
            "Período": periodos,
            "Captações": [100.0] * len(periodos),
            "Carteira de Crédito": [100.0] * len(periodos),
        }
    )


def _df_carteira_instrumentos(
    instituicao="Banco A",
    periodos=None,
    problematicos=None,
    total=None,
):
    periodos = list(periodos or PERIODOS)
    n = len(periodos)
    return pd.DataFrame(
        {
            "Instituição": [instituicao] * n,
            "Período": periodos,
            "Ativos problemáticos": list(problematicos if problematicos is not None else [5.0] * n),
            "Total Geral": list(total if total is not None else [100.0] * n),
        }
    )


def _valores(df_resultado, metrica):
    recorte = df_resultado[df_resultado["Métrica"].astype(str) == metrica]
    return {str(row["Período"]): row["Valor"] for _, row in recorte.iterrows()}


def _build(**kwargs):
    df_dre = kwargs.pop("df_dre", None)
    df_principal = kwargs.pop("df_principal", None)
    resultado, _ = build_derived_metrics(
        df_dre if df_dre is not None else _df_dre(),
        df_principal if df_principal is not None else _df_principal(),
        **kwargs,
    )
    return resultado


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "chave, label",
    [
        ("custo_credito_receita", METRIC_CUSTO_CREDITO_RECEITA),
        ("ativos_problematicos_carteira_total", METRIC_ATIVOS_PROBLEMATICOS_CARTEIRA),
    ],
)
def test_metricas_registradas_com_escala_decimal(chave, label):
    definicao = METRIC_REGISTRY[chave]
    assert definicao.display_name == label
    assert definicao.internal_scale == "decimal_0_1"
    assert definicao.display_format == "pct"
    assert chave in DERIVED_METRIC_KEYS
    assert label in DERIVED_METRICS
    assert label in get_derived_metric_formula_map()


def test_registro_declara_fontes_reais_de_cada_metrica():
    """A fonte declarada é o que a memória de cálculo e o glossário prometem ao usuário."""
    assert METRIC_REGISTRY["custo_credito_receita"].source_tables == ["dre", "derived_metrics"]
    assert "carteira_instrumentos" in METRIC_REGISTRY["ativos_problematicos_carteira_total"].source_tables
    # Relatório 16 é a única fonte de carteira dessa métrica: nem Rel. 2 nem Cadoc 4060.
    assert "ativo" not in METRIC_REGISTRY["ativos_problematicos_carteira_total"].source_tables
    assert "bloprudencial" not in METRIC_REGISTRY["ativos_problematicos_carteira_total"].source_tables


# ---------------------------------------------------------------------------
# Custo de Crédito / Receita de Crédito
# ---------------------------------------------------------------------------


def test_pdd_receita_usa_ytd_reconstruido_e_nao_o_valor_bruto_do_trimestre():
    """Set do Rel. 4 é Jul-Set: o YTD soma junho antes de dividir."""
    resultado = _build(
        df_dre=_df_dre(f3=[-1.0, -3.0, -2.0, -5.0], c=[10.0, 30.0, 20.0, 50.0]),
    )
    valores = _valores(resultado, METRIC_CUSTO_CREDITO_RECEITA)
    # 1T: 1/10. 1S: 3/30. Set: (2+3)/(20+30). Dez: (5+3)/(50+30).
    assert math.isclose(float(valores["1/2025"]), 0.10, rel_tol=TOL)
    assert math.isclose(float(valores["2/2025"]), 0.10, rel_tol=TOL)
    assert math.isclose(float(valores["3/2025"]), 5.0 / 50.0, rel_tol=TOL)
    assert math.isclose(float(valores["4/2025"]), 8.0 / 80.0, rel_tol=TOL)


def test_pdd_receita_e_invariante_ao_fator_de_anualizacao():
    """Numerador e denominador são fluxos do mesmo período: escalar os dois não muda a razão.

    É o invariante que distingue esta métrica do Custo de Crédito (%), cujo denominador
    é um estoque e por isso exige o fator explícito.
    """
    base = _build(df_dre=_df_dre(f3=[-2.0] * 4, c=[8.0] * 4))
    escalado = _build(df_dre=_df_dre(f3=[-2.0 * 7] * 4, c=[8.0 * 7] * 4))
    assert _valores(base, METRIC_CUSTO_CREDITO_RECEITA) == pytest.approx(
        _valores(escalado, METRIC_CUSTO_CREDITO_RECEITA)
    )


def test_pdd_receita_devolve_magnitude_para_pdd_negativa_ou_positiva():
    negativa = _build(df_dre=_df_dre(f3=[-2.0] * 4))
    positiva = _build(df_dre=_df_dre(f3=[2.0] * 4))
    assert math.isclose(
        float(_valores(negativa, METRIC_CUSTO_CREDITO_RECEITA)["1/2025"]),
        float(_valores(positiva, METRIC_CUSTO_CREDITO_RECEITA)["1/2025"]),
        rel_tol=TOL,
    )


@pytest.mark.parametrize("receita", [0.0, -5.0])
def test_pdd_receita_sem_receita_valida_resulta_em_nd(receita):
    """Quem não opera crédito fica N/D — nunca zero, nunca infinito."""
    resultado = _build(df_dre=_df_dre(c=[receita] * 4))
    valores = _valores(resultado, METRIC_CUSTO_CREDITO_RECEITA)
    assert all(pd.isna(v) for v in valores.values())


def test_pdd_receita_sem_junho_publicado_bloqueia_set_e_dez():
    resultado = _build(
        df_dre=_df_dre(periodos=["1/2025", "3/2025", "4/2025"], f3=[-1.0, -2.0, -5.0], c=[10.0, 20.0, 50.0]),
        df_principal=_df_principal(periodos=["1/2025", "3/2025", "4/2025"]),
    )
    valores = _valores(resultado, METRIC_CUSTO_CREDITO_RECEITA)
    assert math.isclose(float(valores["1/2025"]), 0.10, rel_tol=TOL)
    assert pd.isna(valores["3/2025"])
    assert pd.isna(valores["4/2025"])


def test_pdd_receita_sem_coluna_f3_fica_nd_em_toda_a_serie():
    """Layout anterior a 2025 não abre PDD por tipo de ativo."""
    df_dre = _df_dre().drop(columns=["Resultado com Perda Esperada de Operações de Crédito (f3)"])
    valores = _valores(_build(df_dre=df_dre), METRIC_CUSTO_CREDITO_RECEITA)
    assert all(pd.isna(v) for v in valores.values())


def test_pdd_receita_e_custo_credito_sao_metricas_distintas():
    """Mesma PDD, denominadores diferentes: a razão sobre receita não pode copiar a de carteira."""
    resultado = _build(df_dre=_df_dre(f3=[-4.0] * 4, c=[8.0] * 4))
    custo = _valores(resultado, METRIC_CUSTO_CREDITO)
    receita = _valores(resultado, METRIC_CUSTO_CREDITO_RECEITA)
    assert math.isclose(float(receita["1/2025"]), 0.5, rel_tol=TOL)
    assert not math.isclose(float(custo["1/2025"]), float(receita["1/2025"]), rel_tol=1e-3)


# ---------------------------------------------------------------------------
# Ativos Problemáticos / Carteira Total
# ---------------------------------------------------------------------------


def test_ativos_problematicos_usa_numerador_e_denominador_do_relatorio_16():
    resultado = _build(
        df_carteira_instrumentos=_df_carteira_instrumentos(problematicos=[7.0] * 4, total=[140.0] * 4),
    )
    valores = _valores(resultado, METRIC_ATIVOS_PROBLEMATICOS_CARTEIRA)
    assert all(math.isclose(float(v), 0.05, rel_tol=TOL) for v in valores.values())


def test_ativos_problematicos_sem_relatorio_16_fica_nd():
    """Ausência do Rel. 16 não pode ser confundida com ausência de ativo problemático."""
    valores = _valores(_build(), METRIC_ATIVOS_PROBLEMATICOS_CARTEIRA)
    assert all(pd.isna(v) for v in valores.values())


def test_ativos_problematicos_preserva_zero_reportado():
    """Zero publicado é informação: uma carteira sem ativo problemático vale 0%, não N/D."""
    resultado = _build(
        df_carteira_instrumentos=_df_carteira_instrumentos(problematicos=[0.0] * 4, total=[100.0] * 4),
    )
    valores = _valores(resultado, METRIC_ATIVOS_PROBLEMATICOS_CARTEIRA)
    assert all(float(v) == 0.0 for v in valores.values())


def test_ativos_problematicos_com_carteira_zero_resulta_em_nd():
    resultado = _build(
        df_carteira_instrumentos=_df_carteira_instrumentos(problematicos=[5.0] * 4, total=[0.0] * 4),
    )
    valores = _valores(resultado, METRIC_ATIVOS_PROBLEMATICOS_CARTEIRA)
    assert all(pd.isna(v) for v in valores.values())


def test_ativos_problematicos_nao_e_afetado_pela_regra_de_ytd():
    """É razão de estoque no fim do período: Set e Dez não somam junho."""
    resultado = _build(
        df_carteira_instrumentos=_df_carteira_instrumentos(
            problematicos=[1.0, 2.0, 3.0, 4.0],
            total=[100.0, 100.0, 100.0, 100.0],
        ),
    )
    valores = _valores(resultado, METRIC_ATIVOS_PROBLEMATICOS_CARTEIRA)
    assert math.isclose(float(valores["3/2025"]), 0.03, rel_tol=TOL)
    assert math.isclose(float(valores["4/2025"]), 0.04, rel_tol=TOL)


def test_ativos_problematicos_ausente_para_instituicao_fora_do_relatorio_16():
    """Cobertura parcial do Rel. 16 é a regra: quem não publica fica N/D, os demais não."""
    periodos = list(PERIODOS)
    df_dre = pd.concat([_df_dre("Banco A"), _df_dre("Banco B")], ignore_index=True)
    df_principal = pd.concat(
        [_df_principal("Banco A"), _df_principal("Banco B")], ignore_index=True
    )
    resultado = _build(
        df_dre=df_dre,
        df_principal=df_principal,
        df_carteira_instrumentos=_df_carteira_instrumentos("Banco A", periodos),
    )
    recorte = resultado[resultado["Métrica"].astype(str) == METRIC_ATIVOS_PROBLEMATICOS_CARTEIRA]
    por_banco = recorte.groupby(recorte["Instituição"].astype(str))["Valor"]
    assert por_banco.apply(lambda s: s.notna().all())["Banco A"]
    assert por_banco.apply(lambda s: s.isna().all())["Banco B"]


# ---------------------------------------------------------------------------
# Camada curada (Peers / Snapshot)
# ---------------------------------------------------------------------------


def _curated_row(f3=-8.0, c=100.0, vcb=400.0, problematicos=24.0, total_4966=400.0):
    """Uma instituição, um período, com o mínimo que o construtor curado exige."""
    inst, periodo = "TEST BANK - PRUDENCIAL", "1/2025"
    principal = pd.DataFrame(
        [{"Instituição": inst, "Período": periodo, "Ativo Total": 1000.0,
          "Patrimônio Líquido": 100.0, "Lucro Líquido Acumulado YTD": 10.0, "Captações": 500.0}]
    )
    ativo = pd.DataFrame(
        [{"Instituição": inst, "Período": periodo, "Disponibilidades (a)": 10.0,
          "Valor Contábil Bruto (e1)": vcb, "Valor Contábil Bruto (f1)": 0.0,
          "Valor Contábil Bruto (g1)": 0.0, "Valor Contábil Bruto (h1)": 0.0,
          "Perda Esperada (e2)": -20.0}]
    )
    dre = pd.DataFrame(
        [{"Instituição": inst, "Período": periodo,
          "Resultado com Perda Esperada (f)": -12.0,
          "Resultado com Perda Esperada de Operações de Crédito (f3)": f3,
          "Rendas de Operações de Crédito (c)": c,
          "Rendas de Arrendamento Financeiro (d)": 10.0,
          "Rendas de Outras Operações com Características de Concessão de Crédito (e)": 5.0,
          "Rendas de Aplicações Interfinanceiras de Liquidez (a)": 8.0,
          "Rendas de Títulos e Valores Mobiliários (b)": 7.0,
          "Despesas de Captações (g)": 11.0}]
    )
    carteira_instr = pd.DataFrame(
        [{"Instituição": inst, "Período": periodo, "C4": 5.0, "C5": 10.0,
          "Total Geral": total_4966, "Inadimplência": 12.0,
          "Ativos problemáticos": problematicos}]
    )
    curado = build_critical_screens_dataframe(
        df_principal=principal,
        df_ativo=ativo,
        df_passivo=None,
        df_capital=None,
        df_dre=dre,
        df_carteira_pf=None,
        df_carteira_pj=None,
        df_carteira_instrumentos=carteira_instr,
        df_bloprudencial=None,
    )
    return curado[curado["Período"] == periodo].iloc[0]


def test_camada_curada_publica_as_tres_metricas_de_cobertura_ampla():
    """Peers e Snapshot leem do cache curado: as colunas precisam existir lá."""
    for metrica in (
        "Custo de Crédito (%)",
        "Custo de Crédito / Receita de Crédito (%)",
        "Ativos Problemáticos / Carteira Total",
    ):
        assert metrica in CRITICAL_EXTRA_METRICS


def test_camada_curada_calcula_custo_de_credito_contra_a_carteira_exibida():
    """O denominador é a mesma Carteira de Crédito* renderizada na tabela.

    Sem isso a memória de cálculo mostraria um denominador que não bate com a linha
    logo acima na tela.
    """
    row = _curated_row(f3=-8.0, vcb=400.0)
    assert row["Carteira de Crédito Bruta"] == 400.0
    # 1T/2025 anualiza ×4: |−8| × 4 ÷ 400.
    assert math.isclose(float(row["Custo de Crédito (%)"]), 32.0 / 400.0, rel_tol=1e-6)


def test_camada_curada_calcula_pdd_receita_sem_anualizar():
    # Receita 200 e carteira 400 mantêm as duas razões distintas: 8/200 = 4% contra
    # (8×4)/400 = 8%. Denominadores iguais fariam o teste passar por coincidência.
    row = _curated_row(f3=-8.0, c=200.0, vcb=400.0)
    assert math.isclose(float(row["Custo de Crédito / Receita de Crédito (%)"]), 0.04, rel_tol=1e-6)
    # A diferença entre as duas métricas é justamente o fator: se fossem iguais a
    # anualização teria vazado para a razão de fluxos.
    assert not math.isclose(
        float(row["Custo de Crédito / Receita de Crédito (%)"]),
        float(row["Custo de Crédito (%)"]),
        rel_tol=1e-3,
    )


def test_camada_curada_expoe_traces_para_memoria_de_calculo():
    row = _curated_row(f3=-8.0, c=100.0)
    assert math.isclose(float(row["Trace::Custo de Crédito::PDD Crédito YTD"]), -8.0, rel_tol=1e-6)
    assert math.isclose(float(row["Trace::Custo de Crédito::PDD Crédito Anualizada"]), -32.0, rel_tol=1e-6)
    assert math.isclose(float(row["Trace::Custo de Crédito::Receita de Crédito YTD"]), 100.0, rel_tol=1e-6)


def test_camada_curada_sem_f3_deixa_as_duas_metricas_de_custo_em_nd():
    row = _curated_row(f3=None)
    assert pd.isna(row["Custo de Crédito (%)"])
    assert pd.isna(row["Custo de Crédito / Receita de Crédito (%)"])
    # A métrica do Rel. 16 é independente do Rel. 4 e não pode ser arrastada junto.
    assert not pd.isna(row["Ativos Problemáticos / Carteira Total"])


def test_camada_curada_e_cache_derivado_concordam_em_ativos_problematicos():
    """As duas camadas calculam a razão a partir do Rel. 16; divergir seria bug.

    A duplicação existe porque Peers lê o cache curado e Rankings/Scatter leem o
    cache derivado. Este teste transforma a duplicação em invariante verificado.
    """
    row = _curated_row(problematicos=24.0, total_4966=400.0)
    derivado = _build(
        df_carteira_instrumentos=_df_carteira_instrumentos(problematicos=[24.0] * 4, total=[400.0] * 4),
    )
    valor_derivado = float(_valores(derivado, METRIC_ATIVOS_PROBLEMATICOS_CARTEIRA)["1/2025"])
    assert math.isclose(float(row["Ativos Problemáticos / Carteira Total"]), valor_derivado, rel_tol=1e-6)


# ---------------------------------------------------------------------------
# Exposição nas abas
# ---------------------------------------------------------------------------


def test_metricas_aparecem_na_tabela_de_peers_com_glossario_e_componentes():
    labels = [row["label"] for section in PEERS_TABELA_LAYOUT for row in section["rows"]]
    for metrica in (
        "Custo de Crédito (%)",
        "Custo de Crédito / Receita de Crédito (%)",
        "Ativos Problemáticos / Carteira Total",
    ):
        assert metrica in labels, f"{metrica} ausente do layout de Peers"
        assert metrica in PEERS_GLOSSARIO_RESUMIDO, f"{metrica} sem verbete de glossário"
        assert metrica in PEERS_RATIO_COMPONENTS, f"{metrica} sem componentes declarados"


def test_trace_components_derivam_de_ratio_components():
    """A lista de traces carregados não pode sair de sincronia com as razões declaradas."""
    esperado = {
        componente
        for componentes in PEERS_RATIO_COMPONENTS.values()
        for componente in componentes
        if str(componente).startswith("Trace::")
    }
    assert set(PEERS_TRACE_COMPONENTS) == esperado
    assert esperado, "as razões de custo de crédito dependem de traces do Rel. 4"
