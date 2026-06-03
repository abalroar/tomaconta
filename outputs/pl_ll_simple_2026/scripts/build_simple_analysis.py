from __future__ import annotations

import json
import math
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "outputs" / "pl_ll_simple_2026"
DATA_OUT = OUT / "data"
CSV_DIR = ROOT / "data" / "cache" / "bcb_bloprudencial" / "csv"

DOC = "4060"
PL_CONTA = "6000000004"
RESULTADO_CREDOR_CONTA = "7000000003"
RESULTADO_DEVEDOR_CONTA = "8000000002"
PL_MIN = 100_000_000.0


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

    congl = df["NOME_CONGL"].astype(str).str.strip()
    inst = df["NOME_INSTITUICAO"].astype(str).str.strip()
    df["Instituição"] = congl.where(congl.ne("") & congl.ne("nan"), inst)
    df["NOME_CONTA_NORM"] = df["NOME_CONTA"].map(norm_text)
    df["DATA_BASE"] = yyyymm

    dedupe_cols = ["DATA_BASE", "DOCUMENTO_N", "Instituição", "CONTA_N", "NOME_CONTA_NORM", "SALDO_N"]
    return df.drop_duplicates(subset=dedupe_cols).copy()


def load_pl(yyyymm: str) -> pd.DataFrame:
    df = read_bloprud(yyyymm)
    part = df[(df["DOCUMENTO_N"] == DOC) & (df["CONTA_N"] == PL_CONTA)].copy()
    return (
        part.groupby("Instituição", dropna=False)["SALDO_N"]
        .sum(min_count=1)
        .reset_index(name=f"PL_{yyyymm}")
    )


def load_ll(yyyymm: str) -> pd.DataFrame:
    df = read_bloprud(yyyymm)
    account_mask = df["CONTA_N"].isin([RESULTADO_CREDOR_CONTA, RESULTADO_DEVEDOR_CONTA])
    name_mask = df["NOME_CONTA_NORM"].isin(["resultado credor", "resultado devedor", "(-) resultado devedor"])
    part = df[(df["DOCUMENTO_N"] == DOC) & (account_mask | name_mask)].copy()

    if part.empty:
        return pd.DataFrame(columns=["Instituição", f"LL_{yyyymm}", f"Credor_{yyyymm}", f"Devedor_{yyyymm}"])

    part["PERNA"] = np.where(
        (part["CONTA_N"] == RESULTADO_CREDOR_CONTA) | part["NOME_CONTA_NORM"].str.contains("credor"),
        "credor",
        "devedor",
    )
    pivot = part.pivot_table(index="Instituição", columns="PERNA", values="SALDO_N", aggfunc="sum").reset_index()
    for col in ["credor", "devedor"]:
        if col not in pivot.columns:
            pivot[col] = np.nan

    pivot[f"Credor_{yyyymm}"] = pivot["credor"]
    pivot[f"Devedor_{yyyymm}"] = pivot["devedor"]
    pivot[f"LL_{yyyymm}"] = pivot["credor"].fillna(0) - pivot["devedor"].abs().fillna(0)
    return pivot[["Instituição", f"LL_{yyyymm}", f"Credor_{yyyymm}", f"Devedor_{yyyymm}"]]


def pct_change(new: pd.Series, old: pd.Series) -> pd.Series:
    denom = old.abs()
    return np.where(denom > 0, (new - old) / denom, np.nan)


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denom = denominator.abs()
    return np.where(denom > 0, numerator / denominator, np.nan)


def to_records(df: pd.DataFrame, n: int | None = None) -> list[dict]:
    work = df.head(n).copy() if n else df.copy()
    records = []
    for row in work.replace({np.nan: None}).to_dict(orient="records"):
        clean = {}
        for key, value in row.items():
            if isinstance(value, (np.floating, np.integer)):
                clean[key] = float(value)
            elif isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                clean[key] = None
            else:
                clean[key] = value
        records.append(clean)
    return records


def brl(value: float | None, scale: float = 1_000_000_000.0, suffix: str = " bi") -> str:
    if value is None or pd.isna(value):
        return "N/D"
    return f"R$ {float(value) / scale:,.1f}{suffix}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "N/D"
    return f"{float(value) * 100:,.1f}%".replace(",", "X").replace(".", ",").replace("X", ".")


def classifica_ponte_pl_ll(row: pd.Series) -> str:
    delta_pl = row["Delta_PL"]
    lucro_liquido = 0.0 if pd.isna(row["LL_202603"]) else row["LL_202603"]
    if pd.isna(delta_pl) or abs(delta_pl) < 1:
        return "sem variação material de PL"
    if delta_pl > 0:
        if lucro_liquido <= 0:
            return "aumento não explicado por LL"
        share = lucro_liquido / delta_pl
        if share >= 1.10:
            return "LL excede o aumento; outras mutações reduziram PL"
        if share >= 0.90:
            return "aumento majoritariamente explicado por LL"
        if share >= 0.50:
            return "aumento parcialmente explicado por LL"
        return "aumento pouco explicado por LL"
    if lucro_liquido > 0:
        return "queda apesar de LL positivo"
    return "queda com LL negativo"


def main() -> None:
    DATA_OUT.mkdir(parents=True, exist_ok=True)

    pl = load_pl("202512").merge(load_pl("202603"), on="Instituição", how="outer")
    ll = load_ll("202503").merge(load_ll("202603"), on="Instituição", how="outer")
    base = pl.merge(ll, on="Instituição", how="left")
    base = base[base["PL_202512"].fillna(0) >= PL_MIN].copy()
    base["Rank_PL_Dez25"] = base["PL_202512"].rank(method="first", ascending=False).astype(int)

    base["Delta_PL"] = base["PL_202603"] - base["PL_202512"]
    base["Var_PL_pct"] = pct_change(base["PL_202603"], base["PL_202512"])
    positive_pl_total = base.loc[base["Delta_PL"] > 0, "Delta_PL"].sum()
    base["Contrib_Delta_PL_Pos_pct"] = np.where(
        (base["Delta_PL"] > 0) & (positive_pl_total > 0),
        base["Delta_PL"] / positive_pl_total,
        np.nan,
    )

    pl_all = base[
        [
            "Rank_PL_Dez25",
            "Instituição",
            "PL_202512",
            "PL_202603",
            "Delta_PL",
            "Var_PL_pct",
            "Contrib_Delta_PL_Pos_pct",
        ]
    ].sort_values("Delta_PL", ascending=False)
    pl_up = pl_all[pl_all["Delta_PL"] > 0].copy()
    pl_up["Contrib_Acum_Delta_PL_Pos_pct"] = pl_up["Contrib_Delta_PL_Pos_pct"].cumsum()
    pl_down = pl_all[pl_all["Delta_PL"] < 0].sort_values("Delta_PL", ascending=True).copy()
    pl_up_pct = pl_all[pl_all["Delta_PL"] > 0].sort_values("Var_PL_pct", ascending=False).copy()
    pl_down_pct = pl_all[pl_all["Delta_PL"] < 0].sort_values("Var_PL_pct", ascending=True).copy()

    base["Delta_LL"] = base["LL_202603"] - base["LL_202503"]
    base["Var_LL_pct"] = pct_change(base["LL_202603"], base["LL_202503"])
    base["LL_202503_pct_PL_Dez25"] = safe_divide(base["LL_202503"], base["PL_202512"])
    base["LL_202603_pct_PL_Dez25"] = safe_divide(base["LL_202603"], base["PL_202512"])
    base["Delta_LL_pct_PL_Dez25"] = safe_divide(base["Delta_LL"], base["PL_202512"])
    ll_202603_bridge = base["LL_202603"].fillna(0)
    base["Residual_Delta_PL_menos_LL"] = base["Delta_PL"] - ll_202603_bridge
    base["Pct_Delta_PL_explicado_por_LL"] = safe_divide(ll_202603_bridge, base["Delta_PL"])
    base["Residual_pct_Delta_PL"] = safe_divide(base["Residual_Delta_PL_menos_LL"], base["Delta_PL"])
    base["Leitura_PL_vs_LL"] = base.apply(classifica_ponte_pl_ll, axis=1)

    ll_all = base[
        [
            "Rank_PL_Dez25",
            "Instituição",
            "PL_202512",
            "LL_202503",
            "LL_202603",
            "Delta_LL",
            "Var_LL_pct",
            "LL_202503_pct_PL_Dez25",
            "LL_202603_pct_PL_Dez25",
            "Delta_LL_pct_PL_Dez25",
        ]
    ].sort_values("Delta_LL", ascending=False)
    ll_up = ll_all[ll_all["Delta_LL"] > 0].copy()
    ll_down = ll_all[ll_all["Delta_LL"] < 0].sort_values("Delta_LL", ascending=True).copy()
    ll_pct_base = ll_all[ll_all["LL_202503"].abs() > 0].copy()
    ll_up_pct = ll_pct_base[ll_pct_base["Delta_LL"] > 0].sort_values("Var_LL_pct", ascending=False).copy()
    ll_down_pct = ll_pct_base[ll_pct_base["Delta_LL"] < 0].sort_values("Var_LL_pct", ascending=True).copy()

    bridge_pl_ll = base[
        [
            "Rank_PL_Dez25",
            "Instituição",
            "PL_202512",
            "PL_202603",
            "Delta_PL",
            "LL_202603",
            "Residual_Delta_PL_menos_LL",
            "Pct_Delta_PL_explicado_por_LL",
            "Residual_pct_Delta_PL",
            "Var_PL_pct",
            "Leitura_PL_vs_LL",
        ]
    ].sort_values("Delta_PL", ascending=False)
    top_residual_positive = bridge_pl_ll[bridge_pl_ll["Residual_Delta_PL_menos_LL"] > 0].sort_values(
        "Residual_Delta_PL_menos_LL",
        ascending=False,
    )
    top_residual_negative = bridge_pl_ll[bridge_pl_ll["Residual_Delta_PL_menos_LL"] < 0].sort_values(
        "Residual_Delta_PL_menos_LL",
        ascending=True,
    )

    sheets = {
        "PL_Todas_IFs": pl_all,
        "PL_Maiores_Altas": pl_up,
        "PL_Maiores_Quedas": pl_down,
        "PL_Maiores_Altas_pct": pl_up_pct,
        "PL_Maiores_Quedas_pct": pl_down_pct,
        "LL_Todas_IFs": ll_all,
        "LL_Maiores_Altas": ll_up,
        "LL_Maiores_Quedas": ll_down,
        "LL_Maiores_Altas_pct": ll_up_pct,
        "LL_Maiores_Quedas_pct": ll_down_pct,
        "PL_vs_LL_IF_a_IF": bridge_pl_ll,
    }
    for name, df_sheet in sheets.items():
        df_sheet.to_csv(DATA_OUT / f"{name}.csv", index=False)

    picpay_rows = pl_all[pl_all["Instituição"].str.contains("PICPAY", case=False, na=False)].copy()
    picpay = picpay_rows.iloc[0].to_dict() if not picpay_rows.empty else None
    picpay_rank = None
    if picpay is not None:
        picpay_rank = int(pl_up.reset_index(drop=True).index[pl_up["Instituição"].eq(picpay["Instituição"])][0] + 1)

    top5_share = float(pl_up.head(5)["Delta_PL"].sum() / positive_pl_total) if positive_pl_total else np.nan
    top10_share = float(pl_up.head(10)["Delta_PL"].sum() / positive_pl_total) if positive_pl_total else np.nan
    summary = {
        "coverage": {
            "instituicoes_qualificadas_pl_100mm": int(len(base)),
            "instituicoes_com_aumento_pl": int(len(pl_up)),
            "instituicoes_com_queda_pl": int(len(pl_down)),
            "instituicoes_com_ll_mar25_e_mar26": int(base[["LL_202503", "LL_202603"]].notna().all(axis=1).sum()),
        },
        "totals": {
            "PL_202512": float(base["PL_202512"].sum(skipna=True)),
            "PL_202603": float(base["PL_202603"].sum(skipna=True)),
            "Delta_PL_total": float(base["Delta_PL"].sum(skipna=True)),
            "Delta_PL_positivo_total": float(positive_pl_total),
            "Delta_PL_negativo_total": float(base.loc[base["Delta_PL"] < 0, "Delta_PL"].sum(skipna=True)),
            "LL_202503": float(base["LL_202503"].sum(skipna=True)),
            "LL_202603": float(base["LL_202603"].sum(skipna=True)),
            "Delta_LL_total": float(base["Delta_LL"].sum(skipna=True)),
        },
        "concentration": {
            "top5_delta_pl_positive_share": top5_share,
            "top10_delta_pl_positive_share": top10_share,
        },
        "picpay": picpay,
        "picpay_rank_delta_pl_positive": picpay_rank,
        "top_pl_up": to_records(pl_up, 15),
        "top_pl_down": to_records(pl_down, 10),
        "top_pl_up_pct": to_records(pl_up_pct, 15),
        "top_pl_down_pct": to_records(pl_down_pct, 10),
        "top_ll_up": to_records(ll_up, 12),
        "top_ll_down": to_records(ll_down, 12),
        "top_ll_up_pct": to_records(ll_up_pct, 12),
        "top_ll_down_pct": to_records(ll_down_pct, 12),
        "top_pl_residual_positive": to_records(top_residual_positive, 15),
        "top_pl_residual_negative": to_records(top_residual_negative, 10),
        "bridge_pl_ll_counts": {
            str(key): int(value)
            for key, value in bridge_pl_ll["Leitura_PL_vs_LL"].value_counts().to_dict().items()
        },
        "methodology": {
            "fonte": "Dados do tomaconta, a partir dos arquivos locais data/cache/bcb_bloprudencial/csv/*BLOPRUDENCIAL.CSV",
            "documento": DOC,
            "pl_conta": f"{PL_CONTA} | Patrimônio Líquido",
            "lucro_liquido": f"{RESULTADO_CREDOR_CONTA} Resultado Credor - abs({RESULTADO_DEVEDOR_CONTA} Resultado Devedor)",
            "universo": "Instituições com PL em 202512 >= R$ 100 milhões, usando NOME_CONGL como chave prudencial quando disponível.",
            "deduplicacao": "Linhas idênticas normalizadas são deduplicadas antes das somas por instituição/conta/período.",
            "ordenacao": "Rankings por delta bruto em reais e por variação percentual, sempre dentro do corte de PL em Dez/25 >= R$ 100 milhões.",
            "omitido": "Não há proxy de aporte, Delta PL - LL, batimento ou inferência no produto executivo.",
            "ponte_pl_ll": "Residual = Delta PL Dez/25-Mar/26 - Lucro Líquido acumulado em Mar/26. Residual positivo indica aumento de PL não explicado por LL.",
        },
        "display": {
            "qualified": f"{len(base):,}".replace(",", "."),
            "positive_pl_delta": brl(float(positive_pl_total)),
            "net_pl_delta": brl(float(base["Delta_PL"].sum(skipna=True))),
            "top5_share": pct(top5_share),
            "top10_share": pct(top10_share),
            "picpay_delta": brl(float(picpay["Delta_PL"])) if picpay is not None else "N/D",
            "picpay_var": pct(float(picpay["Var_PL_pct"])) if picpay is not None else "N/D",
            "ll_delta_total": brl(float(base["Delta_LL"].sum(skipna=True))),
            "bridge_residual_total": brl(float(bridge_pl_ll["Residual_Delta_PL_menos_LL"].sum(skipna=True))),
            "bridge_ll_share_delta_pl": pct(
                float(bridge_pl_ll["LL_202603"].sum(skipna=True) / bridge_pl_ll["Delta_PL"].sum(skipna=True))
            ),
        },
    }

    workbook_payload = {
        "summary": summary,
        "sheets": {name: {"columns": list(df_sheet.columns), "rows": to_records(df_sheet)} for name, df_sheet in sheets.items()},
    }

    (DATA_OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA_OUT / "workbook_data.json").write_text(
        json.dumps(workbook_payload, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "qualified": summary["coverage"]["instituicoes_qualificadas_pl_100mm"],
                "top_positive_pl": summary["top_pl_up"][:5],
                "top_positive_pl_pct": summary["top_pl_up_pct"][:5],
                "picpay": summary["picpay"],
                "picpay_rank_delta_pl_positive": summary["picpay_rank_delta_pl_positive"],
                "output": str(DATA_OUT),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
