"""Testes da ingestão do SCR.data.

O foco é o ETL puro: parsing do CSV do BCB (BOM, decimal com vírgula, resíduo de
CP1252, supressão -1), a agregação no grão e as dimensões derivadas. Nada aqui
toca a rede.
"""

from __future__ import annotations

import io
import textwrap

import pandas as pd
import pytest

from utils.ifdata_cache import scr_data as S


CABECALHO = (
    "data_base;uf;segmento;cliente;cnae_ocupacao;porte;modalidade;submodalidade;"
    "origem;indexador;numero_de_operacoes;a_vencer_ate_90_dias;"
    "a_vencer_de_91_ate_360_dias;a_vencer_de_361_ate_1080_dias;"
    "a_vencer_de_1081_ate_1800_dias;a_vencer_de_1801_ate_5400_dias;"
    "a_vencer_acima_de_5400_dias;carteira_a_vencer;vencido_de_15_ate_90_dias;"
    "vencido_acima_de_90_dias;carteira_vencida;carteira_ativa;"
    "carteira_inadimplencia;ativo_problematico"
)


def _linha(
    *,
    uf="SP",
    segmento="Banco",
    cliente="PF",
    cnae="Empregado de empresa privada",
    porte="Até 1 salário mínimo",
    modalidade="Empréstimos",
    submodalidade="Cheque especial",
    origem="Sem destinação específica",
    indexador="Prefixado",
    operacoes="10",
    carteira="1000,00",
    inadimplencia="100,00",
    problematico="150,00",
    vencido_15_90="20,00",
    vencido_90="80,00",
    data_base="2026-06-30",
):
    campos = [
        data_base, uf, segmento, cliente, cnae, porte, modalidade, submodalidade,
        origem, indexador, operacoes,
        "0,00", "0,00", "0,00", "0,00", "0,00", "0,00", "900,00",
        vencido_15_90, vencido_90, "100,00", carteira, inadimplencia, problematico,
    ]
    return ";".join(f'"{campo}"' for campo in campos)


def _csv(linhas, *, com_bom=True):
    corpo = "\n".join([CABECALHO, *linhas]) + "\n"
    prefixo = "﻿" if com_bom else ""
    return io.BytesIO((prefixo + corpo).encode("utf-8"))


# =============================================================================
# LEITURA
# =============================================================================

def test_le_csv_com_bom_e_decimal_virgula():
    df = S.ler_csv_scr(_csv([_linha()]))
    assert list(df.columns) == S.CSV_USECOLS
    assert df.loc[0, "carteira_ativa"] == pytest.approx(1000.0)
    assert df.loc[0, "uf"] == "SP"


def test_le_csv_sem_bom():
    df = S.ler_csv_scr(_csv([_linha()], com_bom=False))
    assert df.loc[0, "carteira_ativa"] == pytest.approx(1000.0)


def test_descarta_colunas_fora_de_escopo():
    df = S.ler_csv_scr(_csv([_linha()]))
    for coluna in ("cnae_ocupacao", "origem", "indexador", "carteira_a_vencer"):
        assert coluna not in df.columns


# =============================================================================
# NORMALIZAÇÃO
# =============================================================================

@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("Financiamento habitacional \x96 exceto SFH", "Financiamento habitacional - exceto SFH"),
        ("Comercialização ", "Comercialização"),
        ("  Cheque   especial  ", "Cheque especial"),
        ("Cartão de crédito - compra à vista e parcelado lojista ",
         "Cartão de crédito - compra à vista e parcelado lojista"),
    ],
)
def test_normaliza_rotulo(entrada, esperado):
    assert S.normalizar_rotulo(entrada) == esperado


def test_normaliza_rotulo_ignora_nao_texto():
    assert S.normalizar_rotulo(None) is None
    assert S.normalizar_rotulo(3) == 3


def test_data_base_vira_periodo_mensal():
    df = S.normalizar_csv_scr(S.ler_csv_scr(_csv([_linha()])))
    assert df.loc[0, "data_base"] == "2026-06"


def test_supressao_vira_zero_e_alimenta_contador():
    df = S.normalizar_csv_scr(
        S.ler_csv_scr(_csv([
            _linha(operacoes="-1", carteira="500,00"),
            _linha(operacoes="7", carteira="300,00", submodalidade="Cartão de crédito - não migrado"),
        ]))
    )
    assert df["numero_de_operacoes"].tolist() == [0, 7]
    assert df["ops_suprimidas"].tolist() == [1, 0]
    # Só a carteira da linha suprimida entra em carteira_suprimida.
    assert df["carteira_suprimida"].tolist() == [500.0, 0.0]


def test_normalizacao_limpa_rotulos_do_csv():
    df = S.normalizar_csv_scr(
        S.ler_csv_scr(_csv([_linha(submodalidade="Financiamento habitacional \x96 exceto SFH")]))
    )
    assert df.loc[0, "submodalidade"] == "Financiamento habitacional - exceto SFH"


# =============================================================================
# AGREGAÇÃO
# =============================================================================

def test_agregar_fato_colapsa_dimensoes_fora_de_escopo():
    # Mesmo recorte de interesse, CNAE/origem/indexador diferentes.
    linhas = [
        _linha(cnae="Autônomo", origem="Sem destinação específica", carteira="1000,00"),
        _linha(cnae="Empresário", origem="Com destinação específica", carteira="500,00"),
    ]
    fato = S.agregar_fato(S.normalizar_csv_scr(S.ler_csv_scr(_csv(linhas))))
    assert len(fato) == 1
    # Gravado em R$ mil.
    assert float(fato.loc[0, "carteira_ativa"]) == pytest.approx(1.5)


def test_agregar_fato_preserva_totais():
    linhas = [
        _linha(uf="SP", carteira="1000,00", inadimplencia="100,00"),
        _linha(uf="RJ", carteira="2000,00", inadimplencia="50,00"),
        _linha(uf="BA", carteira="3000,00", inadimplencia="600,00"),
    ]
    bruto = S.ler_csv_scr(_csv(linhas))
    fato = S.agregar_fato(S.normalizar_csv_scr(bruto))
    total_bruto = bruto["carteira_ativa"].sum()
    total_fato = fato["carteira_ativa"].astype("float64").sum() * S.ESCALA_MONETARIA
    assert total_fato == pytest.approx(total_bruto, rel=1e-6)


def test_agregar_fato_mantem_modalidade_no_grao():
    # A mesma submodalidade sob modalidades diferentes não pode ser colapsada:
    # o rollup por lookup atribuiria a carteira à modalidade errada.
    linhas = [
        _linha(modalidade="Empréstimos", submodalidade="Microcrédito", carteira="1000,00"),
        _linha(modalidade="Financiamentos", submodalidade="Microcrédito", carteira="2000,00"),
    ]
    fato = S.agregar_fato(S.normalizar_csv_scr(S.ler_csv_scr(_csv(linhas))))
    assert len(fato) == 2
    assert set(fato["modalidade"].astype(str)) == {"Empréstimos", "Financiamentos"}


def test_agregar_fato_tipos_finais():
    fato = S.agregar_fato(S.normalizar_csv_scr(S.ler_csv_scr(_csv([_linha()]))))
    assert list(fato.columns) == S.FACT_COLUMNS
    for coluna in S.FACT_DIM_COLUMNS:
        assert isinstance(fato[coluna].dtype, pd.CategoricalDtype)
    for coluna in S.METRIC_MONETARIAS:
        assert fato[coluna].dtype == "float32"
    for coluna in S.METRIC_CONTAGENS:
        assert fato[coluna].dtype == "int32"


def test_agregar_resumo_troca_uf_por_regiao_sem_perder_total():
    linhas = [
        _linha(uf="SP", carteira="1000,00"),
        _linha(uf="MG", carteira="500,00"),
        _linha(uf="BA", carteira="300,00"),
    ]
    fato = S.agregar_fato(S.normalizar_csv_scr(S.ler_csv_scr(_csv(linhas))))
    resumo = S.agregar_resumo(fato)

    assert "uf" not in resumo.columns
    assert "segmento" not in resumo.columns
    assert set(resumo["regiao"].astype(str)) == {"Sudeste", "Nordeste"}
    assert resumo["carteira_ativa"].astype("float64").sum() == pytest.approx(
        fato["carteira_ativa"].astype("float64").sum(), rel=1e-5
    )


def test_concatenar_fatos_reconcilia_categorias_divergentes():
    # 2012 não tem Fintech; 2026 tem. Concatenar categóricos divergentes sem
    # reconciliação degrada para object e quebra os filtros.
    antigo = S.agregar_fato(S.normalizar_csv_scr(S.ler_csv_scr(
        _csv([_linha(segmento="Banco", data_base="2012-07-31")])
    )))
    novo = S.agregar_fato(S.normalizar_csv_scr(S.ler_csv_scr(
        _csv([_linha(segmento="Fintech", data_base="2026-06-30")])
    )))
    juntos = S.concatenar_fatos([antigo, novo])

    assert len(juntos) == 2
    assert isinstance(juntos["segmento"].dtype, pd.CategoricalDtype)
    assert set(juntos["segmento"].astype(str)) == {"Banco", "Fintech"}


def test_concatenar_fatos_vazio():
    assert S.concatenar_fatos([]).empty
    assert list(S.concatenar_fatos([]).columns) == S.FACT_COLUMNS


# =============================================================================
# DIMENSÕES
# =============================================================================

def test_dim_geo_cobre_as_27_ufs():
    dim = S.construir_dim_geo()
    assert len(dim) == 27
    assert set(dim["regiao"]) == set(S.ORDEM_REGIOES)
    assert dim.loc[dim["uf"] == "SP", "codigo_ibge"].iloc[0] == 35


def test_dim_porte_separa_pf_de_pj():
    dim = S.construir_dim_porte()
    pf = dim[dim["cliente"] == "PF"]
    pj = dim[dim["cliente"] == "PJ"]
    assert len(pf) == len(S.PORTE_PF_ORDEM) + 1  # + Indisponível
    assert len(pj) == len(S.PORTE_PJ_ORDEM) + 1
    assert set(pf["tipo_criterio"]) == {"renda_salarios_minimos", "indisponivel"}
    assert set(pj["tipo_criterio"]) == {"faturamento_anual", "indisponivel"}


def test_dim_porte_traz_limites_de_faturamento_da_lei():
    dim = S.construir_dim_porte().set_index(["cliente", "porte"])
    micro = dim.loc[("PJ", "Micro")]
    pequeno = dim.loc[("PJ", "Pequeno")]
    medio = dim.loc[("PJ", "Médio")]
    grande = dim.loc[("PJ", "Grande")]

    assert micro["limite_superior_faturamento"] == 360_000
    assert pequeno["limite_inferior_faturamento"] == 360_000
    assert pequeno["limite_superior_faturamento"] == 4_800_000
    assert medio["limite_superior_faturamento"] == 300_000_000
    assert grande["limite_inferior_faturamento"] == 300_000_000
    assert "240" in grande["criterio"]  # o teste de ativo total precisa aparecer


def test_dim_porte_ordena_faixas_pela_renda():
    dim = S.construir_dim_porte()
    pf = dim[(dim["cliente"] == "PF") & (dim["tipo_criterio"] != "indisponivel")]
    assert pf.sort_values("ordem")["porte"].tolist() == S.PORTE_PF_ORDEM


def test_dim_produto_marca_legado_e_vigencia():
    pares = pd.DataFrame([
        {"modalidade": "Empréstimos", "submodalidade": "Cheque especial", "data_base": "2012-07"},
        {"modalidade": "Empréstimos", "submodalidade": "Cheque especial", "data_base": "2026-06"},
        {"modalidade": "Outros créditos", "submodalidade": "Cartão de crédito - não migrado", "data_base": "2026-06"},
    ])
    dim = S.construir_dim_produto(pares)
    cheque = dim[dim["submodalidade"] == "Cheque especial"].iloc[0]
    assert cheque["primeira_data_base"] == "2012-07"
    assert cheque["ultima_data_base"] == "2026-06"
    assert not bool(cheque["legado"])
    assert bool(dim[dim["submodalidade"] == "Cartão de crédito - não migrado"].iloc[0]["legado"])


def test_dim_segmento_registra_primeira_data_base():
    observados = pd.DataFrame([
        {"segmento": "Banco", "data_base": "2012-07"},
        {"segmento": "Fintech", "data_base": "2019-03"},
    ])
    dim = S.construir_dim_segmento(observados).set_index("segmento")
    assert dim.loc["Banco", "primeira_data_base"] == "2012-07"
    assert dim.loc["Fintech", "primeira_data_base"] == "2019-03"
    # Segmento nunca observado aparece na dimensão, sem vigência.
    assert pd.isna(dim.loc["Instituição de pagamento", "primeira_data_base"])


# =============================================================================
# VALIDAÇÃO
# =============================================================================

def test_validacao_aceita_slice_saudavel():
    fato = S.agregar_fato(S.normalizar_csv_scr(S.ler_csv_scr(_csv([_linha()]))))
    relatorio = S.validar_fato_anual(fato, ano="2026")
    assert relatorio["linhas"] == 1
    assert relatorio["data_bases"] == ["2026-06"]


def test_validacao_rejeita_uf_desconhecida():
    fato = S.agregar_fato(S.normalizar_csv_scr(S.ler_csv_scr(_csv([_linha(uf="XX")]))))
    with pytest.raises(S.SCRQualityError, match="UF fora do domínio"):
        S.validar_fato_anual(fato, ano="2026")


def test_validacao_rejeita_porte_desconhecido():
    fato = S.agregar_fato(S.normalizar_csv_scr(S.ler_csv_scr(_csv([_linha(porte="Gigante")]))))
    with pytest.raises(S.SCRQualityError, match="porte fora do domínio"):
        S.validar_fato_anual(fato, ano="2026")


def test_validacao_rejeita_slice_vazio():
    with pytest.raises(S.SCRQualityError, match="vazio"):
        S.validar_fato_anual(pd.DataFrame(columns=S.FACT_COLUMNS), ano="2026")


def test_validacao_avisa_salto_de_carteira_entre_meses():
    linhas = [
        _linha(data_base="2026-01-31", carteira="1000,00"),
        _linha(data_base="2026-02-28", carteira="5000,00"),
    ]
    fato = S.agregar_fato(S.normalizar_csv_scr(S.ler_csv_scr(_csv(linhas))))
    relatorio = S.validar_fato_anual(fato, ano="2026")
    assert any("2026-02" in aviso for aviso in relatorio["avisos"])


def test_validacao_avisa_ufs_ausentes():
    fato = S.agregar_fato(S.normalizar_csv_scr(S.ler_csv_scr(_csv([_linha(uf="SP")]))))
    relatorio = S.validar_fato_anual(fato, ano="2026")
    assert any("UFs sem dados" in aviso for aviso in relatorio["avisos"])


# =============================================================================
# CACHE
# =============================================================================

def test_cache_expoe_caminhos_e_assets(tmp_path):
    cache = S.SCRDataCache(tmp_path)
    assert cache.cache_dir == tmp_path / "data" / "cache" / "scr_data"
    assert cache.annual_path(2026).name == "2026.parquet"
    assert cache.annual_asset_name(2026) == "scr_data_ano_2026.parquet"
    assert set(cache.dimension_paths()) == {"produto", "porte", "geo", "segmento"}


def test_cache_scr_usa_release_proprio_quando_release_global_avanca(tmp_path, monkeypatch):
    monkeypatch.setenv("TOMACONTA_RELEASE_TAG", "v2.0-cache")
    monkeypatch.delenv("TOMACONTA_SCR_RELEASE_TAG", raising=False)

    cache = S.SCRDataCache(tmp_path)

    assert cache.release_tag == "v1.1-cache"
    assert cache.github_release_parquet_url == (
        "https://github.com/abalroar/tomaconta/releases/download/"
        "v1.1-cache/scr_data_dados.parquet"
    )


def test_cache_scr_permite_override_do_release_proprio(tmp_path, monkeypatch):
    monkeypatch.setenv("TOMACONTA_RELEASE_TAG", "v2.0-cache")
    monkeypatch.setenv("TOMACONTA_SCR_RELEASE_TAG", "v3-scr-cache")

    cache = S.SCRDataCache(tmp_path)

    assert cache.release_tag == "v3-scr-cache"
    assert "/releases/download/v3-scr-cache/" in cache.github_release_parquet_url


def test_extra_release_assets_inclui_slices_anuais(tmp_path):
    cache = S.SCRDataCache(tmp_path)
    cache._garantir_estrutura()
    fato = S.agregar_fato(S.normalizar_csv_scr(S.ler_csv_scr(_csv([_linha()]))))
    fato.to_parquet(cache.annual_path(2026), index=False)
    S.construir_dim_geo().to_parquet(cache.dimension_paths()["geo"], index=False)

    nomes = {asset for _, asset in cache.extra_release_assets()}
    assert "scr_data_ano_2026.parquet" in nomes
    assert "scr_data_dim_geo.parquet" in nomes


def test_anos_locais_ignora_arquivos_estranhos(tmp_path):
    cache = S.SCRDataCache(tmp_path)
    cache._garantir_estrutura()
    (cache.annual_dir / "2026.parquet").touch()
    (cache.annual_dir / "rascunho.parquet").touch()
    assert cache.anos_locais() == [2026]


def test_carregar_detalhe_junta_anos_locais(tmp_path):
    cache = S.SCRDataCache(tmp_path)
    cache._garantir_estrutura()
    for ano, data_base in ((2025, "2025-12-31"), (2026, "2026-06-30")):
        fato = S.agregar_fato(
            S.normalizar_csv_scr(S.ler_csv_scr(_csv([_linha(data_base=data_base)])))
        )
        fato.to_parquet(cache.annual_path(ano), index=False)

    detalhe = cache.carregar_detalhe(anos=[2025, 2026], baixar_ausentes=False)
    assert sorted(detalhe["data_base"].astype(str)) == ["2025-12", "2026-06"]


def test_carregar_detalhe_sem_anos_devolve_vazio(tmp_path):
    cache = S.SCRDataCache(tmp_path)
    assert cache.carregar_detalhe(anos=[], baixar_ausentes=False).empty


def test_carregar_dimensoes_reconstroi_estaticas_ausentes(tmp_path):
    cache = S.SCRDataCache(tmp_path)
    dimensoes = cache.carregar_dimensoes()
    assert len(dimensoes["geo"]) == 27
    assert not dimensoes["porte"].empty
    assert dimensoes["produto"].empty  # depende da série, não é reconstruível


def test_extrair_periodo_rejeita_periodo_invalido(tmp_path):
    cache = S.SCRDataCache(tmp_path)
    resultado = cache.extrair_periodo("jun/2026")
    assert not resultado.sucesso
    assert "inválido" in resultado.mensagem


def test_validar_dados_exige_colunas_do_resumo(tmp_path):
    cache = S.SCRDataCache(tmp_path)
    ok, _ = cache._validar_dados(pd.DataFrame({"data_base": ["2026-06"]}))
    assert not ok

    resumo = S.agregar_resumo(
        S.agregar_fato(S.normalizar_csv_scr(S.ler_csv_scr(_csv([_linha()]))))
    )
    ok, mensagem = cache._validar_dados(resumo)
    assert ok, mensagem


def test_quebras_de_serie_documentadas():
    datas = {quebra["data_base"] for quebra in S.QUEBRAS_DE_SERIE}
    assert datas == {"2016-06", "2025-01"}
