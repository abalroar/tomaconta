"""Portable Excel renderer for the Streamlit runtime (Python-only hosting).

The financial model is engine-independent. XlsxWriter is already part of the
application's deployment; the workbook stores the same independently calculated values alongside its
editable formulas. Native Excel and an independent recalculation verify the output.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from io import BytesIO

import xlsxwriter

from .prudential_analysis import Analysis
from .prudential_presentation import display_rows, institution_label


STYLES = {
    "body":{}, "bold":{"bold":True}, "indent":{"indent":1},
    "detail":{"indent":2,"italic":True,"font_size":9},
    "ratio":{"italic":True},
    "title":{"bold":True,"font_size":13,"bg_color":"#000000","font_color":"#FFFFFF"},
    "header":{"bold":True,"bg_color":"#000000","font_color":"#FFFFFF","align":"center"},
    "source":{"bold":True,"font_size":9,"bg_color":"#ECEFF2","align":"center","bottom":1,"bottom_color":"#A7ADB4"},
    "section":{"bg_color":"#D9DEE5","top":1,"top_color":"#A7ADB4"},
    "total":{"bold":True,"bg_color":"#000000","font_color":"#FFFFFF","top":2,"top_color":"#FFFFFF","bottom":2,"bottom_color":"#FFFFFF"},
    "note":{"font_size":9,"font_color":"#555555","text_wrap":True},
    "technical":{"font_size":8,"font_color":"#555555"},
}


def analysis_spec(analysis: Analysis) -> dict:
    return asdict(analysis)


def render_xlsx(analysis: Analysis) -> bytes:
    buffer=BytesIO()
    wb=xlsxwriter.Workbook(buffer,{"in_memory":True,"strings_to_formulas":False,"strings_to_urls":False})
    wb.set_properties({"title":f"{analysis.institution} — Análise financeira prudencial","author":"Toma Conta",
                       "comments":"BCB COSIF 4060/4066 e IFData. Fórmulas e fontes preservadas no arquivo."})
    wb.set_calc_mode("auto")
    formats={}
    def fmt(style,number_format=None,numeric=False,compact=False,edge=False):
        key=(style,number_format,numeric,compact,edge)
        if key not in formats:
            cfg={"font_name":"Tahoma","font_size":10,"font_color":"#000000","valign":"vcenter",**STYLES[style]}
            if numeric:cfg["align"]="right"
            if number_format:cfg["num_format"]=number_format
            if compact:cfg["font_size"]=9
            if edge:cfg.update(right=1,right_color="#A7ADB4")
            formats[key]=wb.add_format(cfg)
        return formats[key]

    # One editable committee page follows the supplied photograph: statements
    # side by side, narrow numeric columns, and compact black subtotal bands.
    from .prudential_analysis import col_name
    committee=wb.add_worksheet("Comitê")
    committee.hide_gridlines(2)
    committee.set_zoom(85)
    committee.set_default_row(14.5)
    committee.set_column(0,0,2)
    panel_columns=1+2*len(analysis.periods)
    right_start=1+panel_columns+2
    end_col=right_start+panel_columns-1
    committee.merge_range(1,1,1,end_col,"Conglomerado prudencial | Balanço e DRE",wb.add_format({"font_name":"Tahoma","font_size":12,"bold":True,"font_color":"#222222"}))
    committee.set_row(1,24)
    max_row=6
    for name,start_col in [("Balanço",1),("DRE",right_start)]:
        sheet=analysis.sheets[name]
        last_col=start_col+panel_columns-1
        committee.set_column(start_col,start_col,54)
        committee.merge_range(3,start_col,3,last_col,f"{institution_label(analysis.institution)} · {name}",fmt("header",compact=True))
        committee.write(4,start_col,"Fonte",fmt("source",compact=True))
        committee.write(5,start_col,"R$ MM",fmt("header",compact=True))
        for i,period in enumerate(analysis.periods):
            c=start_col+1+2*i
            committee.set_column(c,c,10)
            committee.set_column(c+1,c+1,7)
            committee.merge_range(4,c,4,c+1,sheet.cells[f"{col_name(3+2*i)}5"].value,fmt("source",compact=True))
            committee.merge_range(5,c,5,c+1,datetime(int(period[:4]),int(period[4:]),1),fmt("header","[$-416]mmm-yy",compact=True))
        for target_row,(ident,source_row,label) in enumerate(display_rows(analysis,name,committee=True),6):
            style=sheet.cells[f"B{source_row}"].style
            committee.write(target_row,start_col,label,fmt(style,compact=True))
            if style=="total":committee.set_row(target_row,17)
            for i,_ in enumerate(analysis.periods):
                for offset in range(2):
                    source_col=col_name(3+2*i+offset)
                    cell=sheet.cells.get(f"{source_col}{source_row}")
                    if name=="Balanço" and offset==1 and (style in {"indent","detail"} or ident=="net"):
                        cell=None
                    destination=start_col+1+2*i+offset
                    number_format=cell.fmt if cell else None
                    f=fmt(style,number_format,True,compact=True,edge=offset==1)
                    if cell is not None and cell.value is not None:
                        committee.write_formula(target_row,destination,f"='{name}'!{source_col}{source_row}",f,cell.value)
                    else:committee.write_blank(target_row,destination,None,f)
            max_row=max(max_row,target_row)
    committee.set_column(1+panel_columns, right_start-1,3)
    committee.merge_range(max_row+2,1,max_row+2,end_col,"BCB · Fontes, critérios e conciliações nas abas de apoio. N/D: dado não disponível.",fmt("note",compact=True))
    committee.set_landscape()
    committee.set_paper(9 if len(analysis.periods)<=2 else 8)
    committee.fit_to_pages(1,1)
    committee.set_margins(.2,.2,.25,.25)
    committee.print_area(1,1,max_row+2,end_col)
    committee.set_tab_color("#000000")
    for name,s in analysis.sheets.items():
        ws=wb.add_worksheet(name)
        ws.hide_gridlines(2)
        ws.set_zoom(90 if name in {"Balanço","DRE","Carteira 4.966"} else 85)
        ws.set_default_row(17)
        for col,width in s.widths.items():ws.set_column(f"{col}:{col}",width)
        for row,height in s.heights.items():ws.set_row(row-1,height,options={"hidden":row in s.hidden_rows})
        for row in s.hidden_rows:ws.set_row(row-1,s.heights.get(row,19),options={"hidden":True,"level":1})
        for merged in s.merges:
            anchor=merged.split(":")[0];cell=s.cells[anchor]
            ws.merge_range(merged,"",fmt(cell.style,cell.fmt))
        for address,cell in s.cells.items():
            numeric=isinstance(cell.value,(int,float)) or cell.value=="N/D" or cell.formula is not None
            style=fmt(cell.style,cell.fmt,numeric)
            if cell.formula:
                ws.write_formula(address,cell.formula,style,cell.value)
            elif cell.fmt=="[$-416]mmm-yy" and isinstance(cell.value,str):
                ws.write_datetime(address,datetime.fromisoformat(cell.value),style)
            elif isinstance(cell.value,str):ws.write_string(address,cell.value,style)
            else:ws.write(address,cell.value,style)
        ws.freeze_panes(s.freeze)
        if name in {"Dados COSIF","Dados IFData","Mapa COSIF"}:
            ws.autofilter(0,0,s.last_row-1,s.last_col-1)
            ws.set_row(0,26)
        if name=="Validações":
            ws.conditional_format(1,4,len(analysis.checks),4,{"type":"text","criteria":"containing","value":"Divergência", "format":wb.add_format({"bg_color":"#FCE4D6","font_color":"#9C0006","bold":True})})
        if name in {"Balanço","DRE","Carteira 4.966"}:
            ws.set_tab_color("#000000")
            ws.set_landscape() if len(analysis.periods)>2 else ws.set_portrait()
            ws.set_paper(9)
            ws.fit_to_pages(1,1)
            ws.set_margins(.25,.25,.3,.3)
            ws.print_area(s.print_area)
            ws.repeat_rows(4,5)
            ws.set_footer("&L Toma Conta — BCB &R&P / &N",{"margin":.15})
        else:ws.set_landscape();ws.fit_to_pages(1,0)
    wb.close()
    return buffer.getvalue()
