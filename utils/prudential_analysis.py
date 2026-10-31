"""Auditable financial statements from COSIF and same-entity IFData sources.

Amounts stay in reais until the presentation formulas. COSIF account stems
exclude the check digit and trailing padding, so both 8- and 10-digit plans can
be traversed without adding synthetic accounts to their descendants.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import math
import re
from typing import Any

import pandas as pd

BCB_URL = "https://www.bcb.gov.br/estabilidadefinanceira/balancetesbalancospatrimoniais"
IFDATA_URL = "https://www.bcb.gov.br/estabilidadefinanceira/ifdata"
ND = "N/D"
INTERMEDIATION_FIELD = "Resultado de Intermediação Financeira (k) = (a) + (b) + (c) + (d) + (e) + (f) + (g) + (h) + (i) + (j)"
MONEY = '#,##0;[Red]-#,##0;0'
PCT = '0%;[Red]-0%;0%'


def text_id(value: Any) -> str:
    return re.sub(r"\.0$", "", str(value).strip())


def stem(code: str) -> str:
    code = text_id(code)
    if not re.fullmatch(r"(?:\d{8}|\d{10})", code):
        raise ValueError(f"Código COSIF inválido: {code}")
    raw=code[:-1].rstrip("0")
    # COSIF levels are group/subgroup/title/subtitle/item/subitem, with
    # boundaries 1,2,3,5,7,9. 1.8.8.40 is a sibling of 1.8.8.45.
    width=next(n for n in (1,2,3,5,7,9) if n>=len(raw))
    return raw.ljust(width,"0")


def period_key(value: Any) -> str:
    value = text_id(value)
    if re.fullmatch(r"[1-4]/\d{4}", value):
        q, y = value.split("/")
        return f"{y}{int(q)*3:02d}"
    if not re.fullmatch(r"\d{4}(0[1-9]|1[0-2])", value):
        raise ValueError(f"Competência inválida: {value}")
    return value


def is_totalizer(prefix: str) -> bool:
    # COSIF 3.9.9.99.99 / 9.9.9.99.99 are general totals, including
    # on-balance-sheet accounts. They are not children of compensation 3/9.
    return prefix in {"3999999", "9999999"}


def number(value):
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


@dataclass
class Cell:
    value: Any = None
    formula: str | None = None
    style: str = "body"
    fmt: str | None = None


@dataclass
class Sheet:
    name: str
    cells: dict[str, Cell] = field(default_factory=dict)
    widths: dict[str, float] = field(default_factory=dict)
    heights: dict[int, float] = field(default_factory=dict)
    hidden_rows: list[int] = field(default_factory=list)
    merges: list[str] = field(default_factory=list)
    last_row: int = 1
    last_col: int = 1
    freeze: str = "C7"
    print_area: str | None = None

    def put(self, address, value=None, formula=None, style="body", fmt=None):
        self.cells[address] = Cell(value, formula, style, fmt)
        letters, row = re.fullmatch(r"([A-Z]+)(\d+)", address).groups()
        self.last_row = max(self.last_row, int(row))
        self.last_col = max(self.last_col, col_number(letters))
        return Ref(f"'{self.name}'!{address}", number(value))


def col_number(text):
    value = 0
    for c in text:
        value = value * 26 + ord(c) - 64
    return value


def col_name(index):
    value = ""
    while index:
        index, rem = divmod(index - 1, 26)
        value = chr(65 + rem) + value
    return value


@dataclass(frozen=True)
class Ref:
    address: str
    value: float | None


@dataclass
class Analysis:
    institution: str
    code: str
    periods: list[str]
    sheets: dict[str, Sheet] = field(default_factory=dict)
    checks: list[dict] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    rows: dict[str, dict[str, int]] = field(default_factory=dict)
    # Intermediação na janela publicada pelo Rel. 4, no COSIF e no próprio relatório (R$ milhões).
    reference: dict[str, dict[str, float]] = field(default_factory=dict)

    def sheet(self, name):
        self.sheets[name] = Sheet(name)
        return self.sheets[name]


DRE_DEFINITIONS=(
    ("revenue","Receitas da Intermediação Financeira","section",None),
    ("credit","Operações de Crédito","indent",[("711",1),("716",1)]),
    ("leasing","Arrendamento Financeiro","indent",[("712",1)]),
    ("sale","Resultado na Venda de Ativos Financeiros","indent",[("71915",1),("81915",1)]),
    ("sale_gain","Lucro na Venda de Ativos Financeiros","detail",[("71915",1)]),
    ("sale_loss","Prejuízo na Venda de Ativos Financeiros","detail",[("81915",1)]),
    ("tvm","TVM e Aplicações Interfinanceiras","indent",[("714",1),("715",1)]),
    ("other_inter","Outras Receitas de Intermediação","indent",[("713",1)]),
    ("expenses","Despesas da Intermediação Financeira","section",None),
    ("funding","Despesas de Captação","indent",[("811",1)]),
    ("other_funding","Empréstimos, Repasses e Outras Despesas","indent",[("812",1),("813",1),("814",1),("815",1)]),
    ("gross","Resultado Bruto da Intermediação","total",None),
    ("provision","Provisão para Risco de Crédito (líquida)","section",[("71992",1),("81992",1)]),
    ("after_pdd","Resultado Após PDD","total",None),
    ("other_op","Outras Receitas / Despesas Operacionais","section",None),
    ("services","Receitas de Serviços e Tarifas","indent",[("717",1)]),
    ("admin","Despesas Administrativas (incl. D&A)","indent",[("817",1),("818",1),("81727",-1),("81730",-1),("81733",-1),("81736",-1),("81769",-1)]),
    ("people","Despesas de Pessoal","indent",[("81727",1),("81730",1),("81733",1),("81736",1)]),
    ("tax","Despesas Tributárias","indent",[("81769",1),("81925",1),("81930",1),("81933",1)]),
    ("other_exp","Outras Despesas Operacionais","indent",[("819",1),("81915",-1),("81992",-1),("81925",-1),("81930",-1),("81933",-1)]),
    ("recovery","Recuperação de Créditos Baixados","indent",[("71920",1)]),
    ("equity_result","Resultado de Participações","indent",[("718",1),("816",1)]),
    ("other_rec","Outras Receitas Operacionais","indent",[("719",1),("71915",-1),("71920",-1),("71992",-1)]),
    ("operating","Resultado Operacional","total",None),
    ("non_op","Resultado Não Operacional","body",[("73",1),("83",1)]),
    ("profit_share","Participações nos Lucros","body",[("897",1)]),
    ("tax_income","IR / CS","section",[("794",1),("894",1)]),
    ("tax_credit","dos quais créditos de IR / CS","detail",[("794",1)]),
    ("other_close","Outros Ajustes de Apuração","body",[("79",1),("89",1),("794",-1),("894",-1),("897",-1)]),
    ("net","Resultado Líquido (acumulado no ano)","total",None),
        )


def dre_row_for(code):
    """Linha da DRE em que a conta cai pela regra de prefixos; ``None`` fora do mapa."""
    prefix=stem(code)
    best=None
    for id,_,style,rule in DRE_DEFINITIONS:
        if style=="detail":
            continue
        for candidate,sign in rule or ():
            if sign>0 and prefix.startswith(candidate) and (best is None or len(candidate)>len(best[0])):
                best=(candidate,id)
    return best[1] if best else None


def dre_row_labels():
    """Linhas que podem receber uma conta por decisão registrada na atualização."""
    return {id:label for id,label,style,rule in DRE_DEFINITIONS if rule and style!="detail"}


def dre_definitions(overrides=None):
    """Regras da DRE com as decisões registradas: a conta sai da linha padrão e entra na escolhida."""
    if not overrides:
        return DRE_DEFINITIONS
    allowed=dre_row_labels()
    extra={}
    for code,target in overrides.items():
        if target not in allowed:
            raise ValueError(f"Linha da DRE desconhecida para a conta {code}: {target}")
        default=dre_row_for(code)
        if default!=target:
            extra.setdefault(target,[]).append((code,1))
            if default:
                extra.setdefault(default,[]).append((code,-1))
    return tuple((id,label,style,[*rule,*extra.get(id,())] if rule else rule) for id,label,style,rule in DRE_DEFINITIONS)


class Accounts:
    def __init__(self, data):
        self.rows = {str(r.CONTA): r._asdict() for r in data.itertuples(index=False)}
        self.by_stem = {}
        for code in self.rows:
            prefix = stem(code)
            if prefix in self.by_stem:
                raise ValueError(f"Duas contas com o mesmo prefixo contábil: {prefix}")
            self.by_stem[prefix] = code

    def select(self, prefix):
        # A full code takes priority, followed by its hierarchy. No name-only join.
        if prefix in self.rows:
            return [prefix], "Código exato"
        prefix = stem(prefix) if len(prefix) in (8, 10) else prefix.ljust(next(n for n in (1,2,3,5,7,9) if n>=len(prefix)),"0")
        if prefix in self.by_stem:
            return [self.by_stem[prefix]], "Conta sintética do prefixo"
        candidates = sorted(p for p in self.by_stem if p.startswith(prefix) and not is_totalizer(p))
        chosen = []
        for candidate in candidates:
            if not any(candidate.startswith(p) for p in chosen):
                chosen.append(candidate)
        return [self.by_stem[p] for p in chosen], "Contas-filhas sem sobreposição" if chosen else "Ausente"


class Builder:
    def __init__(self, cosif, ifdata, code, periods, overrides=None):
        self.overrides = overrides or {}
        periods = sorted(set(period_key(p) for p in periods))
        if not periods or len(periods) > 8:
            raise ValueError("Selecione de uma a oito competências")
        cosif = cosif.copy()
        for col in ["DATA_BASE", "DOCUMENTO", "CONTA", "COD_CONGL"]:
            cosif[col] = cosif[col].map(text_id)
        self.all_cosif = cosif[cosif.COD_CONGL.eq(code)].copy()
        # Jul–set e jul–dez só viram acumulado do ano somados ao fechamento de junho.
        self.ytd_base = {p: f"{p[:4]}06" for p in periods if int(p[4:]) > 6}
        cosif = self.all_cosif[self.all_cosif.DATA_BASE.isin(set(periods) | set(self.ytd_base.values()))].copy()
        if not cosif.DATA_BASE.isin(periods).any():
            raise ValueError("Conglomerado sem dados COSIF nas competências selecionadas")
        if cosif.duplicated(["DATA_BASE", "DOCUMENTO", "COD_CONGL", "CONTA"]).any():
            raise ValueError("Duplicidade de instituição, data, documento e conta COSIF")
        cosif["SALDO"] = pd.to_numeric(cosif.SALDO, errors="raise")
        if not cosif.SALDO.map(math.isfinite).all():
            raise ValueError("Saldo COSIF ausente ou não finito")
        self.cosif = cosif.sort_values(["DATA_BASE", "DOCUMENTO", "CONTA"])
        name = self.cosif.sort_values("DATA_BASE").NOME_CONGL.iloc[-1]
        self.a = Analysis(name, code, periods)
        for name in ["Balanço", "DRE", "Carteira 4.966", "Mapa COSIF", "Dados COSIF", "Dados IFData", "Validações"]:
            self.a.sheet(name)
        self.indexes = {(p, doc): Accounts(g) for (p, doc), g in self.cosif.groupby(["DATA_BASE", "DOCUMENTO"])}
        self.ifdata = ifdata
        self.raw_cosif = {}
        self.raw_ifdata = {}
        self.mapping = {}
        self.map_row = 2
        self.lookup_ends = {}
        self.output = {}
        self._raw()

    def _raw(self):
        s = self.a.sheets["Dados COSIF"]
        headers = ["Chave", "Conglomerado", "Data-base", "Documento", "COSIF", "Descrição original", "Saldo (R$)", "Unidade", "Natureza", "CNPJ líder", "Instituição líder", "Fonte"]
        for j, h in enumerate(headers, 1):
            s.put(f"{col_name(j)}1", h, style="header")
        for row, r in enumerate(self.cosif.to_dict("records"), 2):
            p, doc, code = r["DATA_BASE"], r["DOCUMENTO"], r["CONTA"]
            key = "|".join([self.a.code, p, doc, code])
            nature = {"1":"Ativo", "2":"Ativo", "3":"Compensação ativa", "4":"Passivo", "5":"Passivo", "6":"Patrimônio líquido", "7":"Receita", "8":"Despesa", "9":"Compensação passiva"}.get(code[0], "A identificar")
            vals = [key,self.a.code,p,doc,code,r["NOME_CONTA"],float(r["SALDO"]),"BRL",nature,
                    text_id(r.get("CNPJ", "")).zfill(8),r.get("NOME_INSTITUICAO", ""),BCB_URL]
            for j, val in enumerate(vals, 1):
                s.put(f"{col_name(j)}{row}", val, fmt='#,##0.00' if j == 7 else None)
            s.put(f"A{row}",key,f'=B{row}&"|"&C{row}&"|"&D{row}&"|"&E{row}')
            self.raw_cosif[(p,doc,code)] = (key, float(r["SALDO"]))
        self.lookup_ends[s.name] = s.last_row
        s.widths = {"A":51,"B":16,"C":13,"D":12,"E":17,"F":86,"G":23,"H":12,"I":23,"J":16,"K":40,"L":65}
        s.freeze = "F2"
        s = self.a.sheets["Dados IFData"]
        headers = ["Chave", "Conglomerado", "Data-base", "Relatório", "Campo original", "Valor", "Unidade", "Fonte"]
        for j, h in enumerate(headers, 1):
            s.put(f"{col_name(j)}1", h, style="header")
        row = 2
        for source, report in [("ativo","2"),("dre","4"),("capital","5"),("principal","1"),("carteira_instrumentos","16")]:
            frame = self.ifdata.get(source, pd.DataFrame())
            if frame.empty or "CodInst" not in frame:
                self.a.limitations.append(f"IFData Rel. {report}: fonte ou CodInst indisponível.")
                continue
            frame = frame[frame.CodInst.astype(str).eq(self.a.code)].copy()
            frame["period_key"] = frame["Período"].map(period_key)
            frame = frame[frame.period_key.isin(set(self.a.periods) | set(self.ytd_base.values()))]
            if frame.duplicated(["CodInst", "period_key"]).any():
                raise ValueError(f"IFData {source}: identidade duplicada no mesmo período")
            for r in frame.to_dict("records"):
                for field_name, val in r.items():
                    if field_name in {"CodInst", "Instituição", "InstituiçãoRaw", "Período", "period_key"}:
                        continue
                    if number(val) is None:
                        continue
                    p = r["period_key"]
                    key = "|".join([self.a.code,p,report,field_name])
                    unit = ("Quantidade" if field_name.startswith(("Número de", "Quantidade de")) else
                            "Decimal" if any(word in field_name for word in ["Índice", "Razão", "(%)"]) else "BRL")
                    vals = [key,self.a.code,p,report,field_name,float(val),unit,IFDATA_URL]
                    for j, value in enumerate(vals, 1):
                        s.put(f"{col_name(j)}{row}",value,fmt='0.000000' if j == 6 and unit == "Decimal" else '#,##0.00' if j == 6 else None)
                    s.put(f"A{row}",key,f'=B{row}&"|"&C{row}&"|"&D{row}&"|"&E{row}')
                    self.raw_ifdata[(p,source,field_name)] = (key,float(val))
                    row += 1
        self.lookup_ends[s.name] = s.last_row
        s.widths = {"A":80,"B":16,"C":13,"D":12,"E":85,"F":24,"G":14,"H":65}
        s.freeze = "E2"
        s = self.a.sheets["Mapa COSIF"]
        headers = ["Instituição", "Data-base", "Documento", "Prefixo / campo", "Código selecionado", "Descrição / justificativa", "Método", "Chave de origem", "Saldo original"]
        for j,h in enumerate(headers,1):
            s.put(f"{col_name(j)}1",h,style="header")
        s.widths = {"A":16,"B":13,"C":13,"D":48,"E":18,"F":85,"G":43,"H":85,"I":23}
        s.freeze = "D2"

    def _lookup(self, p, document, requested, selected, description, method, key, value, raw_sheet, value_col):
        cache_key = (p,document,requested,selected,raw_sheet)
        if cache_key in self.mapping:
            return self.mapping[cache_key]
        s = self.a.sheets["Mapa COSIF"]
        row = self.map_row
        self.map_row += 1
        for j,val in enumerate([self.a.code,p,document,requested,selected,description,method,key],1):
            s.put(f"{col_name(j)}{row}",val)
        if value is not None:
            s.put(f"H{row}",key,f'=A{row}&"|"&B{row}&"|"&C{row}&"|"&E{row}')
        end = max(2,self.lookup_ends[raw_sheet])
        formula = f'=IF(COUNTIF(\'{raw_sheet}\'!$A$2:$A${end},H{row})=1,INDEX(\'{raw_sheet}\'!${value_col}$2:${value_col}${end},MATCH(H{row},\'{raw_sheet}\'!$A$2:$A${end},0)),"N/D")'
        result = s.put(f"I{row}", value if value is not None else ND,formula,fmt='#,##0.00')
        self.mapping[cache_key] = result
        return result

    def account(self,p,doc,prefix):
        index = self.indexes.get((p,doc))
        if index is None:
            index = Accounts(self.cosif.iloc[:0])
        codes, method = index.select(prefix)
        if not codes:
            return [self._lookup(p,doc,prefix,"", "Conta não informada no documento",method,
                                 f"{self.a.code}|{p}|{doc}|{prefix}|AUSENTE",None,"Dados COSIF","G")]
        result = []
        for code in codes:
            key, val = self.raw_cosif[(p,doc,code)]
            result.append(self._lookup(p,doc,prefix,code,index.rows[code]["NOME_CONTA"],method,key,val,"Dados COSIF","G"))
        return result

    def metric(self,p,source,fields):
        fields = [fields] if isinstance(fields,str) else fields
        selected = next((f for f in fields if (p,source,f) in self.raw_ifdata), fields[0])
        key,value = self.raw_ifdata.get((p,source,selected),(f"{self.a.code}|{p}|{source}|{selected}|AUSENTE",None))
        report = {"ativo":"2","dre":"4","capital":"5","principal":"1","carteira_instrumentos":"16"}[source]
        return self._lookup(p,report,selected,selected,selected,"Campo IFData e CodInst exatos" if value is not None else "Ausente",key,value,"Dados IFData","F")

    def sum_refs(self, sheet, row, col, refs, style="body", scale=1e6, strict=False, fmt=None):
        refs = [(r,1) if isinstance(r,Ref) else r for r in refs]
        valid = [(r,k) for r,k in refs if r.value is not None]
        addresses = ",".join(r.address for r,k in refs)
        if not refs:
            return sheet.put(f"{col}{row}",ND,style=style)
        # SUM ignores explicitly labelled unavailable optional branches. Whole
        # totals are checked against independent reported parent controls.
        pieces = [f"SUM({r.address})*({k})" for r,k in refs]
        condition = f"COUNT({addresses})={'%d' % len(refs)}" if strict else f"COUNT({addresses})>0"
        formula = f'=IF({condition},({"+".join(pieces)})/{scale:g},"N/D")'
        value = sum(r.value*k for r,k in valid)/scale if valid and (not strict or len(valid)==len(refs)) else None
        return sheet.put(f"{col}{row}",value if value is not None else ND,formula,style,fmt or MONEY)

    def ratio(self,s,row,col,numerator,denominator,multiplier=1,style="ratio",fmt="0.00%"):
        formula = f'=IF(AND(ISNUMBER({numerator.address}),ISNUMBER({denominator.address}),{denominator.address}>0),{numerator.address}/{denominator.address}*{multiplier:g},"N/D")'
        val = numerator.value/denominator.value*multiplier if numerator.value is not None and denominator.value is not None and denominator.value>0 else None
        return s.put(f"{col}{row}",val if val is not None else ND,formula,style,fmt)

    def header(self,name,labels):
        s = self.a.sheets[name]
        s.widths={"A":2.5,"B":65}
        last=col_name(2+len(self.a.periods)*2)
        s.merges += [f"B2:{last}2",f"B3:{last}3"]
        s.put("B2",f"{self.a.institution}",style="title")
        s.put("B3",f"{name} · Conglomerado prudencial · {self.a.code}",style="note")
        s.put("B4",name,style="header")
        s.put("B5","Fonte / período",style="source")
        s.put("B6","R$ MM",style="header")
        for i,p in enumerate(self.a.periods):
            c,pct=col_name(3+2*i),col_name(4+2*i)
            s.widths[c]=15;s.widths[pct]=10
            s.put(f"{c}4",p,style="technical")
            s.put(f"{pct}4",self.a.code,style="technical")
            s.merges += [f"{c}5:{pct}5",f"{c}6:{pct}6"]
            s.put(f"{c}5",labels[p],style="source")
            s.put(f"{c}6",date(int(p[:4]),int(p[4:]),1).isoformat(),style="header",fmt="[$-416]mmm-yy")
        s.hidden_rows=[4]
        s.heights={2:25,3:19,4:0,5:23,6:22}
        return s

    def add_row(self,s,id,label,style="body"):
        row = max(7,s.last_row+1)
        if style in {"total","section"}:
            for c in range(2,3+2*len(self.a.periods)):
                s.put(f"{col_name(c)}{row}",None,style=style)
        s.put(f"B{row}",label,style=style)
        s.heights[row]=21 if style in {"total","section"} else 19
        self.a.rows.setdefault(s.name,{})[id]=row
        return row

    def check(self,label,period,left,right,tolerance=.02,note=""):
        s=self.a.sheets["Validações"]
        row=s.last_row+1
        for j,v in enumerate([label,period],1): s.put(f"{col_name(j)}{row}",v)
        formula=f'=IF(AND(ISNUMBER({left.address}),ISNUMBER({right.address})),{left.address}-{right.address},"N/D")'
        val=left.value-right.value if left.value is not None and right.value is not None else None
        s.put(f"C{row}",val if val is not None else ND,formula,fmt='#,##0.00;[Red]-#,##0.00;0.00')
        s.put(f"D{row}",tolerance,fmt='0.00')
        status="N/D" if val is None else "OK" if abs(val)<=tolerance else "Divergência"
        s.put(f"E{row}",status,f'=IF(ISNUMBER(C{row}),IF(ABS(C{row})<=D{row},"OK","Divergência"),"N/D")')
        s.put(f"F{row}",note)
        self.a.checks.append({"check":label,"period":period,"difference":val,"tolerance":tolerance,"status":status,"note":note})

    def run(self):
        s=self.a.sheets["Validações"]
        for j,v in enumerate(["Conferência","Data-base","Diferença (R$ ou razão)","Tolerância","Situação","Nota"],1): s.put(f"{col_name(j)}1",v,style="header")
        s.widths={"A":67,"B":14,"C":28,"D":16,"E":20,"F":105};s.freeze="C2"
        self.dre()
        self.balance()
        self.portfolio()
        self.hierarchy_checks()
        self.notes()
        return self.a

    def dre(self):
        months=("jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez")
        labels={p:f"COSIF 4060 · jan–{months[int(p[4:])-1]}/{p[2:4]}" for p in self.a.periods}
        s=self.header("DRE",labels)
        definitions=dre_definitions(self.overrides)
        for id,label,style,rule in definitions:
            row=self.add_row(s,id,label,style)
            for i,p in enumerate(self.a.periods):
                c=col_name(3+i*2)
                if rule is not None:
                    terms=[(r,k) for q in self._ytd_periods(p) for prefix,k in rule for r in self.account(q,"4060",prefix)]
                    self.output[(s.name,id,p)]=self.sum_refs(s,row,c,terms,style)
        formulas={"revenue":["credit","leasing","sale","tvm","other_inter"],"expenses":["funding","other_funding"],
                  "gross":["revenue","expenses"],"after_pdd":["gross","provision"],
                  "other_op":["services","admin","people","tax","other_exp","recovery","equity_result","other_rec"],
                  "operating":["gross","provision","other_op"],"net":["operating","non_op","profit_share","tax_income","other_close"]}
        for id,parts in formulas.items():
            row=self.a.rows[s.name][id];style=next(d[2] for d in definitions if d[0]==id)
            for i,p in enumerate(self.a.periods):
                refs=[self.output[(s.name,x,p)] for x in parts]
                self.output[(s.name,id,p)]=self.sum_refs(s,row,col_name(3+2*i),refs,style,scale=1,strict=id=="after_pdd")
        for id,label,style,rule in definitions:
            row=self.a.rows[s.name][id]
            for i,p in enumerate(self.a.periods):
                self.ratio(s,row,col_name(4+2*i),self.output[(s.name,id,p)],self.output[(s.name,"revenue",p)],style=style,fmt=PCT)
            if id in {"leasing","other_inter","other_close"} and all(self.output[(s.name,id,p)].value in (None,0) for p in self.a.periods):
                s.hidden_rows.append(row)
        for i,p in enumerate(self.a.periods):
            # A full COSIF result is an independent control, never an output plug.
            raw=self._control_ytd(p,["7","8"],"Resultado 4060 acumulado")
            net=self.output[(s.name,"net",p)]
            self.check("DRE: resultado apresentado x grupos 7 + 8",p,Ref(net.address+"*1000000",None if net.value is None else net.value*1e6),raw)
            # O Rel. 4 publica a janela do semestre: a comparação usa essa mesma janela.
            window=self._control(p,"4060",["7","8"],"Resultado 4060 na janela do Rel. 4")
            report=self.metric(p,"dre",["Lucro Líquido (z) = (w) + (x) + (y)","Lucro Líquido (aa) = (x) + (y) + (z)","Lucro Líquido (j) = (g) + (h) + (i)"])
            self.check("DRE: 4060 x IFData Rel. 4",p,window,report,note="Divergência pode refletir retificação ou composição. O 4060 é a fonte da DRE apresentada.")
            intermediation=self.metric(p,"dre",INTERMEDIATION_FIELD)
            cosif=self._window_after_pdd(p,definitions)
            if intermediation.value is not None and cosif is not None:
                self.a.reference[p]={"rel4":intermediation.value/1e6,"cosif":cosif}

    def _window_after_pdd(self,p,definitions):
        """Intermediação após provisão só na janela da competência, em R$ milhões."""
        parts={"credit","leasing","sale","tvm","other_inter","funding","other_funding","provision"}
        values=[r.value*k for id,_,_,rule in definitions if id in parts and rule for prefix,k in rule for r in self.account(p,"4060",prefix) if r.value is not None]
        return sum(values)/1e6 if values else None

    def _ytd_periods(self,p):
        """Competências que compõem o acumulado; sem junho, a DRE fica N/D em vez de parcial."""
        base=self.ytd_base.get(p)
        if base is None:
            return [p]
        return [base,p] if (base,"4060") in self.indexes else []

    def _control_ytd(self,p,prefixes,label):
        s=self.a.sheets["Mapa COSIF"]
        row=self.map_row;self.map_row+=1
        for j,val in enumerate([self.a.code,p,"4060",label,"","Controle reportado","Soma de grupos independentes",""],1):s.put(f"{col_name(j)}{row}",val)
        refs=[r for q in self._ytd_periods(p) for prefix in prefixes for r in self.account(q,"4060",prefix)]
        return self.sum_refs(s,row,"I",refs,scale=1)

    def _control(self,p,doc,prefixes,label):
        s=self.a.sheets["Mapa COSIF"]
        row=self.map_row;self.map_row+=1
        for j,val in enumerate([self.a.code,p,doc,label,"","Controle reportado","Soma de grupos independentes",""],1):s.put(f"{col_name(j)}{row}",val)
        refs=[r for prefix in prefixes for r in self.account(p,doc,prefix)]
        return self.sum_refs(s,row,"I",refs,scale=1)

    def balance(self):
        docs={p:"4066" if (p,"4066") in self.indexes else "4060" for p in self.a.periods}
        s=self.header("Balanço",{p:f"COSIF {docs[p]}" for p in self.a.periods})
        defs=[
            ("liquid","Ativos Líquidos (disponibilidades e TVM livres)","bold",[("11",1),("12",1),("131",1)]),
            ("restricted","TVM Vinculados e Demais TVM / Derivativos","body",[("13",1),("131",-1)]),
            ("interbank","Relações Interfinanceiras","bold",[("14",1)]),
            ("credit","Operações de Crédito Líq. (inclui Cartão)","bold",[("16",1),("17",1),("18879",1),("18996",1)]),
            ("loans","Empréstimos e Direitos Creditórios Descontados","indent",[("161",1)]),
            ("card","Valores a Receber de Transações de Pagamento","indent",[("18879",1)]),
            ("card_pdd","(-) Provisão sobre Transações de Pagamento","indent",[("18996",1)]),
            ("other_credit","Demais Operações de Crédito e Arrendamento","indent",[("16",1),("17",1),("161",-1)]),
            ("others","Outros Créditos, Valores e Bens","bold",[("18",1),("19",1),("18879",-1),("18996",-1)]),
            ("debtors","Devedores Diversos e Outros","indent",[("18",1),("19",1),("18879",-1),("18996",-1),("199",-1),("18885",-1),("18825",-1),("18840",-1),("18845",-1),("18850",-1),("18852",-1)]),
            ("prepaid","Despesas Antecipadas","indent",[("199",1)]),
            ("related","A Receber de Sociedades Ligadas","indent",[("18885",1)]),
            ("taxes","Impostos a Compensar e Depósitos em Garantia","indent",[("18840",1),("18845",1),("18850",1),("18852",1)]),
            ("tax_credit","Crédito Tributário","indent",[("18825",1)]),
            ("other_assets","Relações Interdependências e Outros Ativos","body",[("15",1)]),
            ("fixed","Permanente","bold",[("2",1)]),
            ("fixed_tangible","Imobilizado de Uso","indent",[("22",1)]),
            ("intangible","Intangível","indent",[("25",1)]),
            ("other_fixed","Demais Itens do Permanente","indent",[("2",1),("22",-1),("25",-1)]),
            ("assets","ATIVO TOTAL","total",None),
            ("deposits","Depósitos","bold",[("41",1)]),
            ("demand","Depósitos à Vista","indent",[("411",1)]),
            ("term","Depósitos a Prazo","indent",[("415",1)]),
            ("other_deposits","Demais Depósitos","indent",[("41",1),("411",-1),("415",-1)]),
            ("securities","Debêntures, Letras e Outros Instrumentos","body",[("42",1),("43",1),("439",-1)]),
            ("payables","Relações Interfinanceiras","body",[("44",1)]),
            ("other_funding","Empréstimos, Repasses e Demais Obrigações","body",[("45",1),("46",1),("47",1),("48",1),("5",1)]),
            ("obligations","Outras Obrigações","body",[("49",1)]),
            ("fiscal","Fiscais e Previdenciárias","indent",[("494",1)]),
            ("subdebt","Dívida Subordinada","body",[("439",1)]),
            ("eligible","Elegível a Capital","indent",[("4391",1),("4392",1)]),
            ("liabilities","PASSIVO EXIGÍVEL","total",None),
            ("equity","Patrimônio Líquido (com resultado)","total",None),
            ("liab_equity","PASSIVO + PATRIMÔNIO LÍQUIDO","total",None),
            ("net","Resultado Líquido (acumulado no ano)","total",None),
            ("roe","ROE anualizado (resultado / PL de fechamento)","total",None),
            ("cet1","Capital Principal (CET1)","total",None),
            ("basel","Índice de Basileia Total","total",None),
            ("principal_capital","Capital Principal (valor)","body",None),
            ("tier1","Capital Nível I","body",None),
            ("tier1_ratio","Índice de Capital Nível I","ratio",None),
            ("capital","Patrimônio de Referência para RWA","body",None),
            ("rwa","Ativos Ponderados pelo Risco (RWA)","body",None),
        ]
        for id,label,style,rule in defs:
            row=self.add_row(s,id,label,style)
            if rule is not None:
                for i,p in enumerate(self.a.periods):
                    terms=[(r,k) for prefix,k in rule for r in self.account(p,docs[p],prefix)]
                    self.output[(s.name,id,p)]=self.sum_refs(s,row,col_name(3+2*i),terms,style)
        for i,p in enumerate(self.a.periods):
            c=col_name(3+2*i);out=lambda id:self.output[(s.name,id,p)]
            for id,parts in [("assets",["liquid","restricted","interbank","credit","others","other_assets","fixed"]),
                             ("liabilities",["deposits","securities","payables","other_funding","obligations","subdebt"])]:
                self.output[(s.name,id,p)]=self.sum_refs(s,self.a.rows[s.name][id],c,[out(x) for x in parts],"total",scale=1)
            equity=self.account(p,docs[p],"6")
            if docs[p]=="4060": equity+=self.account(p,"4060","7")+self.account(p,"4060","8")
            self.output[(s.name,"equity",p)]=self.sum_refs(s,self.a.rows[s.name]["equity"],c,equity,"total")
            self.output[(s.name,"liab_equity",p)]=self.sum_refs(s,self.a.rows[s.name]["liab_equity"],c,[out("liabilities"),out("equity")],"total",scale=1,strict=True)
            self.output[(s.name,"net",p)]=self.sum_refs(s,self.a.rows[s.name]["net"],c,[self.output[("DRE","net",p)]],"total",scale=1,strict=True)
            months=int(p[4:])
            self.output[(s.name,"roe",p)]=self.ratio(s,self.a.rows[s.name]["roe"],c,out("net"),out("equity"),12/months,"total",PCT)
            cp=self.metric(p,"capital","Capital Principal")
            tier=self.metric(p,"capital","Patrimônio de Referência Nível I")
            rwa=self.metric(p,"capital","RWA Total")
            pr=self.metric(p,"capital",["Patrimônio de Referência para Comparação com RWA","Patrimônio de Referência"])
            if pr.value is None:
                pr=self.metric(p,"principal",["Patrimônio de Referência para Comparação com o RWA (e)","Patrimônio de Referência para Comparação com RWA (e)"])
            self.output[(s.name,"cet1",p)]=self.ratio(s,self.a.rows[s.name]["cet1"],c,cp,rwa,style="total")
            self.output[(s.name,"basel",p)]=self.ratio(s,self.a.rows[s.name]["basel"],c,pr,rwa,style="total")
            self.output[(s.name,"tier1_ratio",p)]=self.ratio(s,self.a.rows[s.name]["tier1_ratio"],c,tier,rwa)
            for id,ref in [("principal_capital",cp),("tier1",tier),("capital",pr),("rwa",rwa)]:
                self.output[(s.name,id,p)]=self.sum_refs(s,self.a.rows[s.name][id],c,[ref],strict=True)
            a=self._control(p,docs[p],["1","2"],"Ativo reportado")
            l=self._control(p,docs[p],["4","5"],"Passivo reportado")
            scaled=lambda ref:Ref(ref.address+"*1000000",ref.value*1e6 if ref.value is not None else None)
            self.check("Balanço: Ativo = Passivo + PL",p,scaled(out("assets")),scaled(out("liab_equity")))
            self.check("Balanço: composição do Ativo x grupos 1 + 2",p,scaled(out("assets")),a)
            self.check("Balanço: composição do Passivo x grupos 4 + 5",p,scaled(out("liabilities")),l)
            for group,parts in [("credit",["loans","card","card_pdd","other_credit"]),
                                ("others",["debtors","prepaid","related","taxes","tax_credit"]),
                                ("fixed",["fixed_tangible","intangible","other_fixed"]),
                                ("deposits",["demand","term","other_deposits"])]:
                controls=self.a.sheets["Mapa COSIF"]; row=self.map_row; self.map_row+=1
                controls.put(f"D{row}",f"Composição apresentada: {group}")
                breakdown=self.sum_refs(controls,row,"I",[out(x) for x in parts],scale=1e-6)
                self.check(f"Balanço: subcontas apresentadas de {group}",p,scaled(out(group)),breakdown)
            self.check("Balanço x IFData: Ativo",p,a,self.metric(p,"principal","Ativo Total"))
            self.check("Balanço x IFData: PL",p,scaled(out("equity")),self.metric(p,"principal","Patrimônio Líquido"))
            if docs[p]=="4066":
                bridge=self._control(p,"4060",["6","7","8"],"PL 4060 + resultado")
                self.check("Conciliação patrimonial: PL 4066 x PL 4060 + resultado",p,scaled(out("equity")),bridge)
            self.check("Capital: CET1 calculado x índice reportado",p,out("cet1"),self.metric(p,"capital","Índice de Capital Principal"),1e-8)
            self.check("Capital: Basileia calculada x índice reportado",p,out("basel"),self.metric(p,"capital",["Índice de Basileia Capital","Índice de Basileia"]),1e-8)
            self.check("Capital: Nível I calculado x índice reportado",p,out("tier1_ratio"),self.metric(p,"capital","Índice de Capital Nível I"),1e-8)
        for id,label,style,rule in defs:
            row=self.a.rows[s.name][id]
            if id not in {"roe","cet1","basel","tier1_ratio"}:
                for i,p in enumerate(self.a.periods):
                    self.ratio(s,row,col_name(4+2*i),self.output[(s.name,id,p)],self.output[(s.name,"assets",p)],style=style,fmt=PCT)
            if id in {"other_assets","other_funding","other_deposits","other_credit","other_fixed"} and all(self.output[(s.name,id,p)].value is None or abs(self.output[(s.name,id,p)].value)<5e-9 for p in self.a.periods):s.hidden_rows.append(row)

    def portfolio(self):
        s=self.header("Carteira 4.966",{p:"IFData 16 / 2 e COSIF" for p in self.a.periods})
        definitions=[("total","Carteira Total (Relatório 16)","total","Total Geral"),
            *[(f"c{i}",f"Carteira C{i}","indent",f"C{i}") for i in range(1,6)],
            ("unclassified","Carteira Não Informada ou Não Aplicável","indent","Carteira não Informada ou não se Aplica"),
            ("exterior","Total Exterior","indent","Total Exterior"),
            ("non_ind","Total Não Individualizado","indent","Total não Individualizado"),
            ("growth","Crescimento entre datas selecionadas","ratio",None),
            ("bad","Ativos Problemáticos","bold","Ativos problemáticos"),
            ("bad_ratio","Ativos Problemáticos / Carteira","ratio",None),
            ("npl","Inadimplência (operações com atraso >90 dias)","bold","Inadimplência"),
            ("npl_ratio","Inadimplência / Carteira","ratio",None),
            ("gross","Carteira Bruta Contábil (Relatório 2)","total",None),
            ("loans","Operações de Crédito — Bruto","indent",None),
            ("lease","Arrendamento Financeiro — Bruto","indent",None),
            ("other","Outras Operações de Crédito — Bruto","indent",None),
            ("payments","Transações de Pagamento Pós-pago — Bruto","indent",None),
            ("pdd","Provisão para Perda Esperada (Relatório 2)","total",None),
            ("pdd_ratio","Provisão / Carteira Bruta Contábil","ratio",None),
            ("stage3","Estágio 3 (COSIF 4060)","body",None),
            ("cover_stage3","Cobertura de Estágio 3 (perímetros distintos)","ratio",None),
            ("cover_npl","Cobertura de Inadimplência (Rel. 2 / Rel. 16)","ratio",None),
            ("cover_bad","Cobertura de Ativos Problemáticos (proxy)","ratio",None),
            ("writeoffs","Baixas de Crédito no Período","body",None),
            ("renegotiated","Renegociações de Crédito no Período","body",None),
            ("recovery","Recuperação de Créditos Baixados (semestre)","body",None),
            ("expense","Despesa Líquida de Provisão (semestre)","body",None)]
        for id,label,style,field in definitions:
            row=self.add_row(s,id,label,style)
            for i,p in enumerate(self.a.periods):
                c=col_name(3+2*i)
                if field:
                    ref=self.metric(p,"carteira_instrumentos",field)
                    self.output[(s.name,id,p)]=self.sum_refs(s,row,c,[ref],style,strict=True)
                elif id in {"loans","lease","other","payments"}:
                    asset_field={"loans":"e1","lease":"f1","other":"g1","payments":"h1"}[id]
                    ref=self.metric(p,"ativo",f"Valor Contábil Bruto ({asset_field})")
                    self.output[(s.name,id,p)]=self.sum_refs(s,row,c,[ref],style,strict=True)
                elif id=="pdd":
                    refs=[(self.metric(p,"ativo",f"Perda Esperada ({x}2)"),-1) for x in "efgh"]
                    self.output[(s.name,id,p)]=self.sum_refs(s,row,c,refs,style,strict=True)
                elif id=="stage3":self.output[(s.name,id,p)]=self.sum_refs(s,row,c,self.account(p,"4060","3313"),style)
                elif id in {"recovery","expense"}:
                    ref=self.output[("DRE","recovery" if id=="recovery" else "provision",p)]
                    self.output[(s.name,id,p)]=self.sum_refs(s,row,c,[(ref,1 if id=="recovery" else -1)],style,scale=1,strict=True)
                elif id in {"writeoffs","renegotiated"}:
                    # Compensating-account stocks and tax loss controls are not
                    # write-off or renegotiation flows. No proxy is substituted.
                    self.output[(s.name,id,p)]=s.put(f"{c}{row}",ND)
        for i,p in enumerate(self.a.periods):
            c=col_name(3+2*i);out=lambda id:self.output[(s.name,id,p)]
            self.output[(s.name,"gross",p)]=self.sum_refs(s,self.a.rows[s.name]["gross"],c,[out(x) for x in ["loans","lease","other","payments"]],"total",scale=1,strict=True)
            for id,n,d in [("bad_ratio","bad","total"),("npl_ratio","npl","total"),("pdd_ratio","pdd","gross"),("cover_stage3","pdd","stage3"),("cover_npl","pdd","npl"),("cover_bad","pdd","bad")]:
                self.output[(s.name,id,p)]=self.ratio(s,self.a.rows[s.name][id],c,out(n),out(d))
            row=self.a.rows[s.name]["growth"]
            if i:
                prev=self.output[(s.name,"total",self.a.periods[i-1])]
                ratio=self.ratio(s,row,c,out("total"),prev)
                if ratio.value is not None:
                    s.cells[f"{c}{row}"].formula=s.cells[f"{c}{row}"].formula.replace(',"N/D")','-1,"N/D")')
                    s.cells[f"{c}{row}"].value-=1
            else:s.put(f"{c}{row}",ND,style="ratio")
            for id,label,style,field in definitions:
                if field or id in {"loans","lease","other","payments"}:
                    self.ratio(s,self.a.rows[s.name][id],col_name(4+2*i),out(id),out("gross") if id in {"loans","lease","other","payments"} else out("total"),style=style,fmt=PCT)
            controls=self.a.sheets["Mapa COSIF"];row=self.map_row;self.map_row+=1
            controls.put(f"D{row}","Composição Rel. 16 (todos os componentes)")
            composition=self.sum_refs(controls,row,"I",[out(x) for x in ["c1","c2","c3","c4","c5","unclassified","exterior","non_ind"]],scale=1e-6,strict=True)
            self.check("Carteira: C1–C5 + demais componentes x Total Rel. 16",p,composition,Ref(out("total").address+"*1000000",None if out("total").value is None else out("total").value*1e6))
            self.check("Carteira: Rel. 2 x Rel. 16 (perímetros distintos)",p,Ref(out("gross").address+"*1000000",None if out("gross").value is None else out("gross").value*1e6),Ref(out("total").address+"*1000000",None if out("total").value is None else out("total").value*1e6),note="Teste informativo. Carteira contábil e universo do Rel. 16 podem diferir; não se força igualdade.")

    def hierarchy_checks(self):
        for (p,doc),index in self.indexes.items():
            if p not in self.a.periods:
                continue
            for parent,code in sorted(index.by_stem.items()):
                descendants=sorted(x for x in index.by_stem if x!=parent and x.startswith(parent) and not is_totalizer(x))
                children=[]
                for candidate in descendants:
                    if not any(candidate.startswith(x) for x in children):children.append(candidate)
                if not children:continue
                parent_ref=self.account(p,doc,code)[0]
                s=self.a.sheets["Mapa COSIF"];row=self.map_row;self.map_row+=1
                s.put(f"D{row}",f"Filhas imediatas de {code}");s.put(f"F{row}",index.rows[code]["NOME_CONTA"])
                child_ref=self.sum_refs(s,row,"I",[r for child in children for r in self.account(p,doc,index.by_stem[child])],scale=1,strict=True)
                self.check(f"Subcontas {doc}: {code} — {index.rows[code]['NOME_CONTA']}",p,parent_ref,child_ref,note="Diferenças podem indicar granularidade parcial no arquivo público; não são compensadas por ajustes artificiais.")

    def notes(self):
        notes=[
            "Balanço: preferência pelo 4066. No 4060, o PL inclui os grupos 7 + 8, sem somar os dois documentos.",
            "DRE: resultado acumulado no ano até a data-base. As contas 7/8 encerram em junho e dezembro, então setembro e dezembro somam o fechamento de junho. Sem junho, a DRE fica N/D.",
            "ROE: resultado acumulado no ano × 12 / meses do ano / PL de fechamento. Não utiliza PL médio. PL nulo ou negativo gera N/D.",
            "Intermediação: subtotais pelas contas COSIF, com a mesma regra para todas as instituições. A comparação com o Rel. 4 usa a janela que ele publica: jan–mar, jan–jun, jul–set e jul–dez. Quando o sinal difere, a linha recebe asterisco e nota. Nenhuma conta é reclassificada caso a caso.",
            "Mapa: código exato, depois conta sintética ou fronteira de contas-filhas sem sobreposição. A descrição original permanece nos dados.",
            "Hierarquia: os totalizadores 3.9.9.99.99 e 9.9.9.99.99 não são filhas dos grupos de compensação 3 e 9 (BCB, Críticas COSIF, regra G7). Permanecem nos dados brutos.",
            "Reclassificações: cartão pós-pago e sua provisão em Crédito; TVM livres em Ativos Líquidos; TVM vinculados em linha própria.",
            "Histórico: a estrutura COSIF muda em 2025. Detalhes não publicados no regime anterior ficam N/D; resultados agregados seguem as contas disponíveis.",
            "DRE: pessoal e tributos segregados das despesas administrativas; D&A incluída em administração. Venda e recuperação segregadas de outras receitas/despesas.",
            "Ausência de conta permanece N/D. Somas de ramos disponíveis são confrontadas com os grupos reportados em Validações.",
            "Carteira: Rel. 16 inclui C1–C5, não informada/não aplicável, exterior e não individualizado. Componentes negativos reportados são preservados.",
            "Provisão: magnitude de e2 + f2 + g2 + h2 do Rel. 2. Coberturas com Rel. 16 e estágio 3 têm universos distintos e devem ser lidas com essa limitação.",
            "Baixas e renegociações: fluxos não disponíveis nas fontes selecionadas. Contas de compensação ou controles tributários não os substituem.",
            "Capital: CET1 = Capital Principal/RWA; Basileia = PR para comparação com RWA/RWA. PR do Rel. 1 quando não disponível no Rel. 5.",
            "Referência visual: imagem fornecida de Balanço e DRE. Tahoma, cabeçalhos pretos e negativos vermelhos. Carteira segue o mesmo padrão.",
            "As linhas técnicas e os ramos acessórios sem valores são ocultados; podem ser reexibidos. Nenhuma conta bruta é removida.",
        ]+self.a.limitations
        for source,frame in [("COSIF",self.all_cosif),*self.ifdata.items()]:
            provenance=frame.attrs.get("prudential_provenance")
            if provenance:
                notes.append(f"Arquivo {source}: {provenance['filename']}; SHA-256 {provenance['sha256']}.")
        for name in ["Balanço","DRE","Carteira 4.966"]:
            s=self.a.sheets[name]
            row=s.last_row+2
            s.put(f"B{row}","Fontes e conciliações nas abas de dados e Validações. Valores em R$ milhões.",style="note")
            end=col_name(2+len(self.a.periods)*2);s.merges.append(f"B{row}:{end}{row}")
            s.print_area=f"B2:{end}{row}"
        s=self.a.sheets["Validações"];r=s.last_row+3
        s.put(f"A{r}","Fontes, reclassificações e limites",style="header")
        for n,note in enumerate(notes,r+1):s.put(f"A{n}",note,style="note");s.merges.append(f"A{n}:F{n}");s.heights[n]=30
        self.a.limitations=notes


def build_analysis(cosif: pd.DataFrame, ifdata: dict[str,pd.DataFrame], code: str, periods: list[str], *, overrides=None) -> Analysis:
    return Builder(cosif,ifdata,code,periods,overrides).run()
