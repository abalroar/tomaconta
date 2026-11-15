"""Recortes do Snapshot com identidade, unidade e perímetro explícitos."""
from __future__ import annotations

import pandas as pd

from .ifdata_cache.institutions import normalize_institution_code
from .peers_table_model import arrasto_lookup, number, period_sort


INDIVIDUAL = "Individual"
INDIVIDUAL_RISK_NOTE = (
    "N/D na base Individual: os caches disponíveis não contêm Rel. 2, Rel. 5, "
    "Rel. 16 ou estágios COSIF no mesmo perímetro da entidade selecionada."
)
INDIVIDUAL_CARTEIRA_NOTE = (
    "Carteira de crédito do IFData Rel. 1 individual; carteira classificada "
    "quando o campo de carteira de crédito não foi publicado."
)

# Nenhum desses dados pode ser herdado do grupo para completar a entidade legal.
UNAVAILABLE_INDIVIDUAL_COLUMNS = (
    "Índice de Capital Principal (CET1)", "Índice de Basileia Total (%)",
    "Perda Esperada", "Perda Esperada / Estágio 3",
    "Perda Esperada / Carteira de Crédito*", "Ativos Estágio 2", "Ativos Estágio 3",
    "Carteira Total 4.966", "Inadimplência 4.966", "Ativos Problemáticos 4.966",
)


def individual_snapshot_frame(df, bank, derived=None, *, codes=()):
    """Adapta o Rel. 1 individual ao Snapshot, sem juntar dados de conglomerado.

    ``df`` deve ser o slice individual fechado pelo loader de Peers. A seleção
    permanece por CodInst, quando fornecido, ou pelo nome canônico exato. Lucros
    do segundo semestre são recompostos com junho; o trimestre isolado exige
    março em junho e setembro em dezembro. ROE usa o PL atual, como o conceito
    individual da Tabela de Peers. Todos os percentuais saem em escala decimal.
    """
    if df is None or df.empty or not {"Instituição", "Período"}.issubset(df):
        return pd.DataFrame()
    exact_codes = {c for value in codes if (c := normalize_institution_code(value))}
    if exact_codes:
        if "CodInst" not in df:
            return pd.DataFrame()
        selected = df["CodInst"].map(normalize_institution_code).isin(exact_codes)
    else:
        selected = df["Instituição"].astype(str).str.strip().eq(str(bank).strip())
    out = df.loc[selected].copy()
    if out.empty:
        return out
    if "CodInst" in out and out["CodInst"].map(normalize_institution_code).nunique() > 1:
        raise ValueError("Snapshot Individual exige uma única entidade identificada por CodInst.")
    if out["Período"].astype(str).duplicated().any():
        raise ValueError("Snapshot Individual contém mais de um registro por competência.")
    source_names = set(out["Instituição"].astype(str).str.strip())
    out["Instituição"] = str(bank).strip()
    out["Período"] = out["Período"].astype(str)

    def numbers(column):
        return pd.to_numeric(out.get(column, pd.Series(index=out.index, dtype=float)), errors="coerce")

    # O trace evita recomposição dupla quando o mesmo slice alimenta Peers e PPT.
    reported = "Trace::Lucro Líquido::Valor Reportado"
    out[reported] = numbers(reported if reported in out else
                            "Lucro Líquido" if "Lucro Líquido" in out else "Lucro Líquido Acumulado YTD")
    raw = dict(zip(out["Período"], (number(v) for v in out[reported])))
    ytd, quarterly, ytd_notes, quarterly_notes = {}, {}, {}, {}
    for period, value in raw.items():
        year, quarter = period_sort(period)
        june, previous = raw.get(f"2/{year}"), raw.get(f"{quarter - 1}/{year}")
        ytd[period] = value if quarter <= 2 else (
            june + value if june is not None and value is not None else None
        )
        quarterly[period] = value if quarter in (1, 3) else (
            value - previous if value is not None and previous is not None else None
        )
        ytd_notes[period] = (
            "Lucro YTD sem base de junho para recompor o segundo semestre."
            if quarter > 2 and value is not None and june is None else
            "Lucro líquido não publicado no Rel. 1 individual para a competência."
            if value is None else ""
        )
        quarterly_notes[period] = (
            f"Lucro trimestral sem base de {'março' if quarter == 2 else 'setembro'} para a subtração."
            if quarter in (2, 4) and value is not None and previous is None else
            "Lucro líquido não publicado no Rel. 1 individual para a competência."
            if value is None else ""
        )
    out["Lucro Líquido Acumulado YTD"] = out["Período"].map(ytd)
    out["Lucro Líquido Trimestral"] = out["Período"].map(quarterly)
    out["Trace::Lucro YTD::Observação"] = out["Período"].map(ytd_notes)
    out["Trace::Lucro Trimestral::Observação"] = out["Período"].map(quarterly_notes)

    portfolio = numbers("Carteira de Crédito")
    fallback = numbers("Carteira de Crédito Classificada")
    out["Carteira de Crédito Bruta"] = portfolio.where(portfolio.notna(), fallback)
    out["Carteira de Crédito*"] = out["Carteira de Crédito Bruta"]
    out["Trace::Carteira::Campo Selecionado"] = [
        "Carteira de Crédito" if number(value) is not None else "Carteira de Crédito Classificada"
        for value in portfolio
    ]
    out["Trace::Carteira::Status"] = [
        "official_individual_credit" if number(value) is not None else
        "official_individual_classified" if number(classified) is not None else "missing"
        for value, classified in zip(portfolio, fallback)
    ]
    funding, equity = numbers("Captações"), numbers("Patrimônio Líquido")
    out["Core Funding"] = funding
    out["Core Funding*"] = funding
    out["Crédito / Captações"] = out["Carteira de Crédito Bruta"] / funding.where(funding > 0)
    out["Trace::Core Funding::Status"] = [
        "official_individual_captacoes" if number(value) is not None else "missing" for value in funding
    ]
    annualization = out["Período"].map(lambda p: 4 / period_sort(p)[1])
    out["Trace::Fator Anualização"] = annualization
    out["Trace::PL Atual"] = equity
    valid_equity = equity.where(equity > 0)
    out["ROE Ac. Anualizado (%)"] = out["Lucro Líquido Acumulado YTD"] * annualization / valid_equity
    out["ROE Ac. YTD an. (%)"] = out["ROE Ac. Anualizado (%)"]
    out["ROE trimestral anualizado (%)"] = out["Lucro Líquido Trimestral"] * 4 / valid_equity

    # O derivado individual pode vir de Rel. 4. Versões atuais preservam CodInst;
    # versões legadas exigem nome exato e competência sem duplicidade.
    out["Desp Captação / Captação"] = float("nan")
    if derived is not None and not derived.empty and {"Instituição", "Período", "Métrica", "Valor"}.issubset(derived):
        identity = derived["Instituição"].astype(str).str.strip().isin(source_names | {str(bank).strip()})
        if "CodInst" in derived and "CodInst" in out:
            selected_codes = set(out["CodInst"].map(normalize_institution_code))
            identity = derived["CodInst"].map(normalize_institution_code).isin(selected_codes)
        exact = derived.loc[
            identity & derived["Métrica"].eq("Desp Captação / Captação")
            & derived["Período"].astype(str).isin(out["Período"])
        ].copy()
        if not exact["Período"].astype(str).duplicated().any():
            expenses = dict(zip(exact["Período"].astype(str), (number(v) for v in exact["Valor"])))
            out["Desp Captação / Captação"] = out["Período"].map(expenses)

    for column in UNAVAILABLE_INDIVIDUAL_COLUMNS:
        out[column] = float("nan")
    for column in tuple(out):
        if column.startswith("Trace::Perda Esperada::"):
            out[column] = float("nan")
    out["CapitalDisponivel"] = False
    out["BloprudencialDisponivel"] = False
    out["QualidadeCarteiraDisponivel"] = False
    out["Trace::Qualidade Carteira::Status"] = "individual_source_unavailable"
    out["Trace::Bloprudencial::Status"] = "individual_source_unavailable"
    out["Trace::Snapshot::Base"] = INDIVIDUAL
    return out


def snapshot_risk_maps(df, bank, periods, base="Consolidada / Prudencial"):
    """NPL por arrasto e cobertura com os mesmos componentes da tabela 4.966."""
    metric_keys = {"npl90": "Inadimplência / Carteira Total", "coverage90": "PDD / Inadimplência (arrasto)"}
    result = {key: {str(p): None for p in periods} for key in metric_keys}
    result["status"] = {key: {} for key in metric_keys}
    if base == INDIVIDUAL:
        lookup = {}
    elif df is None or df.empty or "Instituição" not in df:
        lookup = {}
    else:
        selected = df[df["Instituição"].astype(str).str.strip().eq(str(bank).strip())].copy()
        if selected["Período"].astype(str).duplicated().any():
            raise ValueError("Snapshot contém mais de um registro para o risco da instituição e competência.")
        lookup = arrasto_lookup(selected)
    for name, key in metric_keys.items():
        for period in map(str, periods):
            cell = lookup.get((key, str(bank), period), {})
            value = number(cell.get("value"))
            status = str(cell.get("status") or "missing")
            reason = str(cell.get("reason") or "")
            if base == INDIVIDUAL:
                reason = INDIVIDUAL_RISK_NOTE
            elif period_sort(period)[0] < 2025:
                reason = "Rel. 16 disponível desde mar/2025; sem série retroativa neste conceito."
            elif value is None and not reason:
                reason = "Componentes do Rel. 16 ou da PDD do Rel. 2 indisponíveis no mesmo perímetro e competência."
            result[name][period] = value
            result["status"][name][period] = {"status": status if value is not None else "missing",
                                             "reason": reason, "reliable": status not in {"warning", "critical", "missing"}}
    return result
