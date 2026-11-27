import pandas as pd
import pytest

from utils.concessoes_ajustadas_bc import MODALIDADES_SGS, concessoes_das_tabelas


def test_outubro_usa_total_proprio_do_anexo_e_preserva_a_janela():
    datas = pd.to_datetime(["2026-09-01", "2026-10-01", "2026-11-01"])
    sgs = pd.DataFrame({"concessoes_sa_total": [720000, None, 740100]}, index=datas)
    dados, fonte = concessoes_das_tabelas(sgs)
    assert dados["concessoes_sa_total"].tolist() == [721.1, 727.5, 740.1]
    cruzamentos = ["concessoes_sa_livre_pf", "concessoes_sa_livre_pj",
                   "concessoes_sa_direcionado_pf", "concessoes_sa_direcionado_pj"]
    assert dados.loc[datas[1], cruzamentos].sum() == pytest.approx(726.2)
    assert dados.loc[datas[2], cruzamentos].isna().all()
    assert len(dados.columns) == 9 and not set(MODALIDADES_SGS).intersection(dados)
    assert "tabelas 2 a 5" in fonte["source"] and "SGS nos meses fora do anexo" in fonte["source"]
    recorte, ficha = concessoes_das_tabelas(sgs.loc[datas[1]:datas[1]])
    assert list(recorte.index) == [datas[1]] and "SGS nos meses" not in ficha["source"]


def test_periodo_fora_do_anexo_indica_exclusivamente_sgs():
    sgs = pd.DataFrame({"concessoes_sa_total": [740100]}, index=pd.to_datetime(["2026-11-01"]))
    dados, fonte = concessoes_das_tabelas(sgs)
    assert dados.iloc[0]["concessoes_sa_total"] == 740.1
    assert fonte["source"] == "BC · SGS"
