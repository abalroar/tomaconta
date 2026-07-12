from __future__ import annotations

import json
import math
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "outputs" / "capital_pl_ll_2026"
DATA_OUT = OUT / "data"
CSV_DIR = ROOT / "data" / "cache" / "bcb_bloprudencial" / "csv"

DOC = "4060"
PL_CONTA = "6000000004"
PL_MIN = 100_000_000.0
PL_PERIODS = ["202512", "202601", "202602", "202603"]
LL_PERIODS = ["202503", "202601", "202602", "202603"]


def norm_text(value: object) -> str:
    text = str(value or "").strip()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return " ".join(text.lower().split())


def read_bloprud(yyyymm: str) -> pd.DataFrame:
    path = CSV_DIR / f"{yyyymm}BLOPRUDENCIAL.CSV"
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path, sep=";", encoding="latin-1", skiprows=3, engine="python")
    df.columns = [str(c).lstrip("#").strip() for c in df.columns]
    df["DOCUMENTO_N"] = df["DOCUMENTO"].astype(str).str.replace(r"\D", "", regex=True)
    df["CONTA_N"] = df["CONTA"].astype(str).str.replace(r"\D", "", regex=True)
    df["SALDO_N"] = pd.to_numeric(
        df["SALDO"].astype(str).str.replace(".", "", regex=False).str.replace(",", ".", regex=False),
        errors="coerce",
    )
    inst = df["NOME_CONGL"].astype(str).str.strip()
    fallback = df["NOME_INSTITUICAO"].astype(str).str.strip()
    df["Instituição"] = inst.where(inst.ne("") & inst.ne("nan"), fallback)
    df["NOME_CONTA_NORM"] = df["NOME_CONTA"].map(norm_text)
    df["DATA_BASE"] = yyyymm
    dedupe_cols = ["DATA_BASE", "DOCUMENTO_N", "Instituição", "CONTA_N", "NOME_CONTA_NORM", "SALDO_N"]
    return df.drop_duplicates(subset=dedupe_cols).copy()


def load_pl(yyyymm: str) -> pd.DataFrame:
    df = read_bloprud(yyyymm)
    part = df[(df["DOCUMENTO_N"] == DOC) & (df["CONTA_N"] == PL_CONTA)].copy()
    out = (
        part.groupby(["Instituição"], dropna=False)["SALDO_N"]
        .sum(min_count=1)
        .reset_index(name=f"PL_{yyyymm}")
    )
    return out


def load_ll(yyyymm: str) -> pd.DataFrame:
    df = read_bloprud(yyyymm)
    part = df[
        (df["DOCUMENTO_N"] == DOC)
        & (df["NOME_CONTA_NORM"].isin(["resultado credor", "resultado devedor", "(-) resultado devedor"]))
    ].copy()
    if part.empty:
        return pd.DataFrame(columns=["Instituição", f"LL_{yyyymm}", f"Credor_{yyyymm}", f"Devedor_{yyyymm}"])

    part["PERNA"] = np.where(part["NOME_CONTA_NORM"].str.contains("credor"), "credor", "devedor")
    piv = part.pivot_table(index="Instituição", columns="PERNA", values="SALDO_N", aggfunc="sum").reset_index()
    for col in ["credor", "devedor"]:
        if col not in piv.columns:
            piv[col] = np.nan
    piv[f"Credor_{yyyymm}"] = piv["credor"]
    piv[f"Devedor_{yyyymm}"] = piv["devedor"]
    piv[f"LL_{yyyymm}"] = piv["credor"] - piv["devedor"].abs()
    return piv[["Instituição", f"LL_{yyyymm}", f"Credor_{yyyymm}", f"Devedor_{yyyymm}"]]


def pct_change(new: pd.Series, old: pd.Series) -> pd.Series:
    denom = old.abs()
    return np.where(denom > 0, (new - old) / denom, np.nan)


def rank_month(row: pd.Series, cols: list[str]) -> str:
    vals = row[cols].dropna()
    if vals.empty:
        return ""
    return str(vals.idxmax()).replace("Delta_PL_", "").replace("_", "->")


def format_brl(value: float | int | None, scale: float = 1_000_000.0, suffix: str = "mm") -> str:
    if value is None or pd.isna(value):
        return "N/D"
    return f"R$ {float(value) / scale:,.1f}{suffix}".replace(",", "X").replace(".", ",").replace("X", ".")


def to_records(df: pd.DataFrame, n: int | None = None) -> list[dict]:
    work = df.head(n).copy() if n else df.copy()
    records = []
    for row in work.replace({np.nan: None}).to_dict(orient="records"):
        clean = {}
        for k, v in row.items():
            if isinstance(v, (np.floating, np.integer)):
                clean[k] = float(v)
            elif isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                clean[k] = None
            else:
                clean[k] = v
        records.append(clean)
    return records


def main() -> None:
    DATA_OUT.mkdir(parents=True, exist_ok=True)

    pl = None
    for period in PL_PERIODS:
        df_period = load_pl(period)
        pl = df_period if pl is None else pl.merge(df_period, on="Instituição", how="outer")

    ll = None
    for period in LL_PERIODS:
        df_period = load_ll(period)
        ll = df_period if ll is None else ll.merge(df_period, on="Instituição", how="outer")

    base = pl.merge(ll, on="Instituição", how="left")
    base = base[base["PL_202512"].fillna(0) >= PL_MIN].copy()
    base["Rank_PL_Dez25"] = base["PL_202512"].rank(method="first", ascending=False).astype(int)

    periods_pairs = [("202512", "202601", "Dez25_Jan26"), ("202601", "202602", "Jan26_Fev26"), ("202602", "202603", "Fev26_Mar26")]
    for old, new, label in periods_pairs:
        base[f"Delta_PL_{label}"] = base[f"PL_{new}"] - base[f"PL_{old}"]
        base[f"Delta_PL_pct_{label}"] = pct_change(base[f"PL_{new}"], base[f"PL_{old}"])

    base["Delta_PL_Dez25_Mar26"] = base["PL_202603"] - base["PL_202512"]
    base["Delta_PL_pct_Dez25_Mar26"] = pct_change(base["PL_202603"], base["PL_202512"])

    base["LL_Mensal_Jan26"] = base["LL_202601"]
    base["LL_Mensal_Fev26"] = base["LL_202602"] - base["LL_202601"]
    base["LL_Mensal_Mar26"] = base["LL_202603"] - base["LL_202602"]
    base["Proxy_Capital_Outras_Jan26"] = base["Delta_PL_Dez25_Jan26"] - base["LL_Mensal_Jan26"]
    base["Proxy_Capital_Outras_Fev26"] = base["Delta_PL_Jan26_Fev26"] - base["LL_Mensal_Fev26"]
    base["Proxy_Capital_Outras_Mar26"] = base["Delta_PL_Fev26_Mar26"] - base["LL_Mensal_Mar26"]
    base["Proxy_Capital_Outras_1T26"] = base["Delta_PL_Dez25_Mar26"] - base["LL_202603"]
    base["Maior_Mes_Aumento_PL"] = base.apply(
        lambda row: rank_month(row, ["Delta_PL_Dez25_Jan26", "Delta_PL_Jan26_Fev26", "Delta_PL_Fev26_Mar26"]),
        axis=1,
    )

    base["Delta_LL_Mar25_Mar26"] = base["LL_202603"] - base["LL_202503"]
    base["Delta_LL_pct_Mar25_Mar26"] = pct_change(base["LL_202603"], base["LL_202503"])

    ordered_cols = [
        "Rank_PL_Dez25",
        "Instituição",
        "PL_202512",
        "PL_202601",
        "PL_202602",
        "PL_202603",
        "Delta_PL_Dez25_Jan26",
        "Delta_PL_Jan26_Fev26",
        "Delta_PL_Fev26_Mar26",
        "Delta_PL_Dez25_Mar26",
        "Delta_PL_pct_Dez25_Mar26",
        "Maior_Mes_Aumento_PL",
        "LL_Mensal_Jan26",
        "LL_Mensal_Fev26",
        "LL_Mensal_Mar26",
        "LL_202603",
        "Proxy_Capital_Outras_Jan26",
        "Proxy_Capital_Outras_Fev26",
        "Proxy_Capital_Outras_Mar26",
        "Proxy_Capital_Outras_1T26",
        "LL_202503",
        "Delta_LL_Mar25_Mar26",
        "Delta_LL_pct_Mar25_Mar26",
    ]
    all_detail = base[ordered_cols].sort_values("Rank_PL_Dez25").reset_index(drop=True)

    top_pl_abs = all_detail.sort_values("Delta_PL_Dez25_Mar26", ascending=False)
    top_pl_pct = all_detail[all_detail["PL_202512"] > 0].sort_values("Delta_PL_pct_Dez25_Mar26", ascending=False)
    top_proxy = all_detail.sort_values("Proxy_Capital_Outras_1T26", ascending=False)
    top_proxy_neg = all_detail.sort_values("Proxy_Capital_Outras_1T26", ascending=True)
    ll_valid = all_detail[all_detail["LL_202503"].abs() > 1].copy()
    ll_pos_pct = ll_valid.sort_values("Delta_LL_pct_Mar25_Mar26", ascending=False)
    ll_neg_pct = ll_valid.sort_values("Delta_LL_pct_Mar25_Mar26", ascending=True)
    ll_abs = all_detail.sort_values("Delta_LL_Mar25_Mar26", ascending=False)

    # Summary metrics and chart tables.
    coverage = {
        "instituicoes_pl_dez25": int(pl["PL_202512"].notna().sum()),
        "instituicoes_qualificadas_pl_100mm": int(len(all_detail)),
        "instituicoes_com_pl_mar26": int(all_detail["PL_202603"].notna().sum()),
        "instituicoes_com_ll_mar25": int(all_detail["LL_202503"].notna().sum()),
        "instituicoes_com_ll_mar26": int(all_detail["LL_202603"].notna().sum()),
    }

    totals = {
        "PL_202512": float(all_detail["PL_202512"].sum(skipna=True)),
        "PL_202603": float(all_detail["PL_202603"].sum(skipna=True)),
        "Delta_PL_Dez25_Mar26": float(all_detail["Delta_PL_Dez25_Mar26"].sum(skipna=True)),
        "LL_202603": float(all_detail["LL_202603"].sum(skipna=True)),
        "Proxy_Capital_Outras_1T26": float(all_detail["Proxy_Capital_Outras_1T26"].sum(skipna=True)),
    }

    month_delta_summary = pd.DataFrame([
        {"Mês": "Dez/25->Jan/26", "Delta_PL": all_detail["Delta_PL_Dez25_Jan26"].sum(skipna=True), "Proxy_Capital_Outras": all_detail["Proxy_Capital_Outras_Jan26"].sum(skipna=True)},
        {"Mês": "Jan/26->Fev/26", "Delta_PL": all_detail["Delta_PL_Jan26_Fev26"].sum(skipna=True), "Proxy_Capital_Outras": all_detail["Proxy_Capital_Outras_Fev26"].sum(skipna=True)},
        {"Mês": "Fev/26->Mar/26", "Delta_PL": all_detail["Delta_PL_Fev26_Mar26"].sum(skipna=True), "Proxy_Capital_Outras": all_detail["Proxy_Capital_Outras_Mar26"].sum(skipna=True)},
    ])

    pl_bridge_top = top_proxy.head(15)[[
        "Instituição",
        "PL_202512",
        "Delta_PL_Dez25_Mar26",
        "LL_202603",
        "Proxy_Capital_Outras_1T26",
        "Maior_Mes_Aumento_PL",
    ]].copy()

    sheet_map = {
        "Base_Analitica": all_detail,
        "Top_PL_Abs": top_pl_abs,
        "Top_PL_Pct": top_pl_pct,
        "Top_Proxy_Aportes": top_proxy,
        "Top_Proxy_Negativo": top_proxy_neg,
        "LL_Mar25_vs_Mar26": all_detail.sort_values("Delta_LL_Mar25_Mar26", ascending=False),
        "LL_Var_Pct_Positiva": ll_pos_pct,
        "LL_Var_Pct_Negativa": ll_neg_pct,
        "Resumo_Mensal": month_delta_summary,
        "Top_Bridge_PPT": pl_bridge_top,
    }

    for name, df_sheet in sheet_map.items():
        df_sheet.to_csv(DATA_OUT / f"{name}.csv", index=False)

    workbook_payload = {
        "sheets": {
            name: {
                "columns": list(df_sheet.columns),
                "rows": to_records(df_sheet),
            }
            for name, df_sheet in sheet_map.items()
        }
    }

    top_findings = {
        "coverage": coverage,
        "totals": totals,
        "top_pl_abs": to_records(top_pl_abs, 10),
        "top_proxy": to_records(top_proxy, 10),
        "top_proxy_neg": to_records(top_proxy_neg, 10),
        "ll_pos_pct": to_records(ll_pos_pct, 10),
        "ll_neg_pct": to_records(ll_neg_pct, 10),
        "ll_abs": to_records(ll_abs, 10),
        "month_delta_summary": to_records(month_delta_summary),
        "methodology": {
            "fonte": "Arquivos locais data/cache/bcb_bloprudencial/csv/*BLOPRUDENCIAL.CSV",
            "documento": DOC,
            "pl_conta": f"{PL_CONTA} | Patrimônio Líquido",
            "lucro_liquido": "Resultado Credor - abs(Resultado Devedor), localizado por nome da conta no documento 4060",
            "deduplicacao": "Linhas idênticas normalizadas são deduplicadas antes das somas por instituição/conta/período.",
            "filtro": "PL_202512 >= R$100 milhões",
            "proxy_aporte": "Delta_PL - lucro líquido do mês/1T; indica mutações patrimoniais não explicadas por resultado, não prova aporte sem documento societário.",
        },
        "display": {
            "total_delta_pl": format_brl(totals["Delta_PL_Dez25_Mar26"], scale=1_000_000_000, suffix="bi"),
            "total_proxy": format_brl(totals["Proxy_Capital_Outras_1T26"], scale=1_000_000_000, suffix="bi"),
            "total_ll_1t26": format_brl(totals["LL_202603"], scale=1_000_000_000, suffix="bi"),
            "count_qualified": str(coverage["instituicoes_qualificadas_pl_100mm"]),
        },
    }
    workbook_payload["summary"] = top_findings
    (DATA_OUT / "summary.json").write_text(json.dumps(top_findings, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA_OUT / "workbook_data.json").write_text(json.dumps(workbook_payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")

    print(json.dumps({
        "qualified": coverage["instituicoes_qualificadas_pl_100mm"],
        "top_proxy": top_proxy[["Instituição", "Proxy_Capital_Outras_1T26", "Delta_PL_Dez25_Mar26", "LL_202603"]].head(5).to_dict(orient="records"),
        "top_ll_pos_pct": ll_pos_pct[["Instituição", "LL_202503", "LL_202603", "Delta_LL_pct_Mar25_Mar26"]].head(5).to_dict(orient="records"),
        "output": str(DATA_OUT),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
