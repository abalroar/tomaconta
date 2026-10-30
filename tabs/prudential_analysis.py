"""Balanço, DRE and portfolio workbook in the prudential analysis area."""
from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from utils.ifdata_cache.bloprudencial_cache import load_bloprudencial_parquet_slice
from utils.ifdata_cache.revision_cache import revision_cache_data
from utils.prudential_analysis import build_analysis, col_name, text_id
from utils.prudential_workbook import render_xlsx


def render(manager,cache_token):
    st.markdown("### Balanço, DRE e Carteira do Conglomerado")
    st.caption("Excel com períodos lado a lado, fórmulas, dados brutos e conciliações. Balanço 4066, DRE 4060 e carteira e capital IFData.")
    cache=manager.get_cache("bloprudencial")
    if cache is None or not cache.arquivo_dados.exists():
        st.info("Base de conglomerados indisponível. Atualize BLOPRUDENCIAL em Atualizar Base.")
        return

    @revision_cache_data(show_spinner=False,max_entries=4)
    def catalog(token):
        path=manager.get_cache("bloprudencial").arquivo_dados
        data=pd.read_parquet(path,columns=["COD_CONGL","NOME_CONGL","DATA_BASE"])
        data["DATA_BASE"]=data.DATA_BASE.map(text_id)
        return data.drop_duplicates().sort_values("DATA_BASE")

    source_token=tuple((kind,cache_token(kind)) for kind in ["bloprudencial","ativo","dre","principal","capital","carteira_instrumentos"])
    data=catalog(source_token)
    names=data.drop_duplicates("COD_CONGL",keep="last").set_index("COD_CONGL").NOME_CONGL.to_dict()
    codes=sorted(names,key=lambda code:names[code])
    default=next((i for i,code in enumerate(codes) if "ITAU" in names[code].upper()),0)
    left,right=st.columns([1,2])
    with left:
        code=st.selectbox("Conglomerado prudencial",codes,index=default,format_func=lambda c:f"{names[c]} ({c})",key="prudential_excel_code")
    available=sorted(data.loc[data.COD_CONGL.eq(code),"DATA_BASE"].unique(),reverse=True)
    context=(code,tuple(available))
    if st.session_state.get("prudential_excel_period_context")!=context:
        semi=[p for p in available if p.endswith(("06","12"))]
        st.session_state["prudential_excel_periods"]=(semi or available)[:2]
        st.session_state["prudential_excel_period_context"]=context
    with right:
        periods=st.multiselect("Datas-base",available,key="prudential_excel_periods",max_selections=8,
                               format_func=lambda p:f"{p[4:]}/{p[:4]}")
    if not periods:
        st.info("Selecione pelo menos uma data-base.")
        return
    signature=hashlib.sha256(repr((code,sorted(periods),source_token)).encode()).hexdigest()
    if st.button("Gerar análise e Excel",key="generate_prudential_excel",type="primary"):
        try:
            with st.spinner("Conferindo Balanço, DRE, subcontas, carteira e capital..."):
                cosif=load_bloprudencial_parquet_slice(cache,periodos_yyyymm=periods)
                cosif.attrs["prudential_provenance"]={"filename":"bloprudencial/dados.parquet","sha256":hashlib.sha256(cache.arquivo_dados.read_bytes()).hexdigest()}
                sources={}
                for kind in ["ativo","dre","principal","capital","carteira_instrumentos"]:
                    result=manager.carregar(kind)
                    if result.sucesso and result.dados is not None:
                        sources[kind]=result.dados.copy()
                        path=manager.get_cache(kind).arquivo_dados
                        if path.is_file():sources[kind].attrs["prudential_provenance"]={"filename":f"{kind}/dados.parquet","sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
                analysis=build_analysis(cosif,sources,code,periods)
                binary=render_xlsx(analysis)
                st.session_state["prudential_excel_result"]=(signature,analysis,binary)
        except (ValueError,KeyError,OSError) as exc:
            st.error(f"A análise não pôde ser gerada: {exc}")
            return
    saved=st.session_state.get("prudential_excel_result")
    if not saved or saved[0]!=signature:return
    _,analysis,binary=saved
    checks=pd.DataFrame(analysis.checks)
    issues=checks[checks.status.eq("Divergência")]
    if not issues.empty:
        st.warning(f"{len(issues)} conciliações com diferenças. Consulte os valores e a natureza de cada diferença em Validações.")
    st.download_button("Baixar Excel de análise financeira",data=binary,
                       file_name=f"analise_prudencial_{code}_{'_'.join(analysis.periods)}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key=f"download_prudential_excel_{signature}",on_click="ignore")
    for tab,name in zip(st.tabs(["Balanço","DRE","Carteira 4.966"]),["Balanço","DRE","Carteira 4.966"]):
        with tab:
            sheet=analysis.sheets[name]
            rows=[]
            for ident,row in analysis.rows[name].items():
                if row in sheet.hidden_rows:continue
                record={"Conta / indicador":sheet.cells[f"B{row}"].value}
                for i,p in enumerate(analysis.periods):
                    cell=sheet.cells.get(f"{col_name(3+2*i)}{row}")
                    val=cell.value if cell else "N/D"
                    if isinstance(val,(float,int)):
                        val=(f"{val:.2%}" if "%" in (cell.fmt or "") else f"{val:,.1f}").replace(",","_").replace(".",",").replace("_",".")
                    record[f"{p[4:]}/{p[:4]}"]=val
                rows.append(record)
            st.caption("Valores em R$ milhões. A DRE acumula o semestre civil até cada data-base.")
            st.dataframe(pd.DataFrame(rows),hide_index=True,width="stretch")
    with st.expander("Fontes e conciliações"):
        st.dataframe(checks.rename(columns={"check":"Conferência","period":"Data-base","difference":"Diferença","tolerance":"Tolerância","status":"Situação","note":"Nota"}),hide_index=True,width="stretch")
        for note in analysis.limitations:st.caption(note)
