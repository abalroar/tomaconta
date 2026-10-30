from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

from utils.prudential_analysis import Accounts, build_analysis, stem
from utils.prudential_workbook import render_xlsx
from utils.ifdata_cache.bloprudencial_ingest import read_source, ingest_source


def records(accounts,period="202606",doc="4066",code="C1"):
    return pd.DataFrame([dict(DATA_BASE=period,DOCUMENTO=doc,COD_CONGL=code,CONTA=c,NOME_CONTA=n,SALDO=v,
                              CNPJ="00001234",NOME_INSTITUICAO="Banco Teste",NOME_CONGL="Teste Prudencial") for c,n,v in accounts])


def test_cosif_hierarchy_respects_level_boundaries_and_check_digit():
    data=records([("1880000009","Diversos",100),("1884000005","Garantia",40),("1884500000","Impostos",60)])
    account=Accounts(data)
    assert stem("1884000005")=="18840"
    assert account.select("188")[0]==["1880000009"]
    assert account.select("1884")[0]==["1884000005"]
    assert Accounts(data.iloc[1:]).select("188")[0]==["1884000005","1884500000"]
    assert stem("18840005")=="18840"


def test_cosif_general_total_is_not_a_compensation_child(simple_sources):
    extra=records([("3000000007","Compensação ativa",100),
                   ("3010000004","Coobrigações",100),
                   ("3999999009","TOTAL GERAL DO ATIVO",1100)])
    a=build_analysis(pd.concat([simple_sources,extra]),{},"C1",["202606"])
    check=next(c for c in a.checks if c["check"].startswith("Subcontas 4066: 3000000007"))
    assert check["status"]=="OK"
    assert Accounts(extra.iloc[1:]).select("3")[0]==["3010000004"]


@pytest.fixture
def simple_sources():
    amounts=[("1000000009","Ativo",1000),("1100000002","Disponibilidades",1000),
             ("4000000006","Passivo",800),("4100000009","Depósitos",800),
             ("4150000004","Prazo",800),("6000000004","PL",200)]
    data=records(amounts)
    pre=records([(c,n,150 if c.startswith("6") else v) for c,n,v in amounts],doc="4060")
    result=records([("7000000003","Credor",70),("7100000006","Receitas",70),("7110000003","Crédito",70),
                    ("8000000002","Devedor",-20),("8100000005","Despesas",-20),("8110000002","Captação",-20)],doc="4060")
    return pd.concat([data,pre,result],ignore_index=True)


def value(a,sheet,row_id,col="C"):
    return a.sheets[sheet].cells[f"{col}{a.rows[sheet][row_id]}"].value


def test_4066_is_not_added_to_4060_and_preclosing_equity_is_bridged(simple_sources):
    a=build_analysis(simple_sources,{},"C1",["202606"])
    assert value(a,"Balanço","assets")==.001
    assert value(a,"Balanço","equity")==.0002
    assert value(a,"DRE","net")==pytest.approx(.00005)
    assert value(a,"Balanço","roe")==pytest.approx(.5)
    assert all(c["status"]=="OK" for c in a.checks if c["check"].startswith(("Balanço: Ativo", "Balanço: composição", "Conciliação patrimonial:","DRE: resultado")))
    fallback=build_analysis(simple_sources[simple_sources.DOCUMENTO.eq("4060")],{},"C1",["202606"])
    assert value(fallback,"Balanço","equity")==.0002


def test_missing_zero_and_identity_are_not_interchangeable(simple_sources):
    capital=pd.DataFrame([{"CodInst":"C2","Período":"2/2026","Capital Principal":100,"RWA Total":1000},
                          {"CodInst":"C1","Período":"2/2026","Capital Principal":0,"RWA Total":1000}])
    a=build_analysis(simple_sources,{"capital":capital},"C1",["202606"])
    assert value(a,"Balanço","cet1")==0
    assert value(a,"Balanço","basel")=="N/D"
    assert value(a,"Carteira 4.966","writeoffs")=="N/D"
    assert value(a,"Carteira 4.966","total")=="N/D"
    with pytest.raises(ValueError,match="Duplicidade"):
        build_analysis(pd.concat([simple_sources,simple_sources.iloc[:1]]),{},"C1",["202606"])


def test_december_dre_is_second_semester_without_adding_june(simple_sources):
    dec=simple_sources.copy();dec.DATA_BASE="202612"
    a=build_analysis(pd.concat([simple_sources,dec]),{},"C1",["202606","202612"])
    assert value(a,"DRE","net","E")==value(a,"DRE","net","C")
    assert "2S26" in a.sheets["DRE"].cells["E5"].value


def test_xlsx_contains_live_formulas_tahoma_black_bands_and_inspectable_inputs(simple_sources):
    a=build_analysis(simple_sources,{},"C1",["202606"])
    payload=render_xlsx(a)
    wb=load_workbook(BytesIO(payload),data_only=False)
    assert wb.sheetnames[:4]==["Comitê","Balanço","DRE","Carteira 4.966"]
    assert wb["Comitê"]["C7"].value == "='Balanço'!C7"
    assert "INDEX(" in wb["Mapa COSIF"]["I2"].value and "MATCH(" in wb["Mapa COSIF"]["I2"].value
    assert wb["Balanço"]["B2"].font.name=="Tahoma"
    assert wb["Balanço"].row_dimensions[4].hidden
    row=a.rows["Balanço"]["roe"]
    assert wb["Balanço"][f"D{row}"].fill.fgColor.rgb=="FF000000"
    assert all("Validações" not in c.value for s in wb if s.title!="Validações" for row in s for c in row if c.data_type=="f")


def source_file(tmp_path,rows):
    path=tmp_path/"202606BLOPRUDENCIAL.CSV"
    path.write_text("Balancete\nData de geracao: 2026-10-19\nFonte: IFs\n#DATA_BASE;DOCUMENTO;CNPJ;AGENCIA;NOME_INSTITUICAO;COD_CONGL;NOME_CONGL;TAXONOMIA;CONTA;NOME_CONTA;SALDO\n"+"\n".join(rows)+"\n",encoding="latin1")
    return path


def test_strict_ingestion_preserves_zero_leading_cnpj_and_replaces_period(tmp_path):
    row="202606;4066;00001234;;Banco;C1;Grupo;Prudencial;1100000002;Caixa;0,00"
    path=source_file(tmp_path,[row])
    data,meta=read_source(path)
    assert data.CNPJ.iloc[0]=="00001234" and data.SALDO.iloc[0]==0
    root=tmp_path/"repo";root.mkdir()
    first=ingest_source(path,root)
    path=source_file(tmp_path,[row.replace("1100000002;Caixa;0,00","1000000009;Ativo;100,00")])
    second=ingest_source(path,root)
    saved=pd.read_parquet(root/"data/cache/bloprudencial/dados.parquet")
    assert len(saved)==1 and saved.CONTA.iloc[0]=="1000000009"
    assert second["comparison"]=={"previous_rows":1,"added":1,"removed":1,"changed_balances":0}
    assert (root/first["archive"]).exists() and (root/second["archive"]).exists()
    source_file(tmp_path,[row,row])
    with pytest.raises(ValueError,match="duplicada"):read_source(path)
    source_file(tmp_path,[row.replace("0,00","")])
    with pytest.raises(ValueError,match="Saldo"):read_source(path)


@pytest.mark.parametrize("code",["C0083539","C0080099","C0080075","C0080185","C0080336","C0084693","C0084710"])
def test_bundled_real_institutions_close_without_synthetic_child_double_count(code):
    from tools.build_prudential_workbook import load_local_sources
    root=Path(__file__).resolve().parents[1]
    c,s=load_local_sources(root,["202512","202606"])
    a=build_analysis(c,s,code,["202512","202606"])
    critical=[x for x in a.checks if x["check"].startswith(("Balanço: Ativo", "Balanço: composição", "DRE: resultado"))]
    assert critical and all(x["status"]=="OK" for x in critical),critical
    assert not any(x["status"]=="Divergência" for x in a.checks if "subcontas apresentadas" in x["check"])

