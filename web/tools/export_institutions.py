#!/usr/bin/env python3
"""Exporta a base curada IF.data para leitura estática, sem refazer cálculos.

Uso: python web/tools/export_institutions.py [--root REPOSITORIO] [--output DIR]
Os valores percentuais são convertidos de razão para pontos percentuais;
ausência permanece null. O índice é pequeno e o histórico é carregado por IF.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


# Coluna curada, rótulo público, unidade de saída, multiplicador da fonte.
METRICS = {
    "assets": ("Ativo Total", "Ativo total", "R$", 1),
    "equity": ("Patrimônio Líquido", "Patrimônio líquido", "R$", 1),
    "profitYtd": ("Lucro Líquido Acumulado YTD", "Lucro líquido acumulado no ano", "R$", 1),
    "profitQuarter": ("Lucro Líquido Trimestral", "Lucro líquido trimestral", "R$", 1),
    "roe": ("ROE Ac. YTD an. (%)", "ROE acumulado anualizado", "%", 100),
    "roeQuarter": ("ROE trimestral anualizado (%)", "ROE trimestral anualizado", "%", 100),
    "credit": ("Carteira de Crédito Bruta", "Carteira de crédito bruta", "R$", 1),
    "funding": ("Core Funding", "Core funding", "R$", 1),
    "creditFunding": ("Crédito / Captações", "Crédito / captações", "%", 100),
    "liquidAssets": ("Ativos Líquidos", "Ativos líquidos", "R$", 1),
    "deposits": ("Depósitos Totais", "Depósitos totais", "R$", 1),
    "expectedLoss": ("Perda Esperada", "Perda esperada", "R$", 1),
    "expectedLossRatio": ("Perda Esperada / Carteira de Crédito Bruta", "Perda esperada / carteira", "%", 100),
    "stage2": ("Ativos Estágio 2", "Ativos em estágio 2", "R$", 1),
    "stage3": ("Ativos Estágio 3", "Ativos em estágio 3", "R$", 1),
    "stage3Ratio": ("Ativos Estágio 3 / Carteira de Crédito", "Estágio 3 / carteira", "%", 100),
    "npl": ("Inadimplência / Carteira Total", "Inadimplência / carteira total", "%", 100),
    "problemAssets": ("Ativos Problemáticos / Carteira Total", "Ativos problemáticos / carteira total", "%", 100),
    "cet1": ("Índice de Capital Principal (CET1)", "Capital principal (CET1)", "%", 100),
    "basel": ("Índice de Basileia Total (%)", "Índice de Basileia total", "%", 100),
    "creditCost": ("Custo de Crédito (%)", "Custo de crédito", "%", 100),
    "capitalPrincipal": ("Trace::Capital::Capital Principal", "Capital principal", "R$", 1),
    "rwa": ("Trace::Capital::RWA Total", "Ativos ponderados pelo risco (RWA)", "R$", 1),
}


def period_info(value: str) -> tuple[str, str]:
    quarter, year = (int(v) for v in value.split("/"))
    period = pd.Period(year=year, quarter=quarter, freq="Q")
    return f"{year}-Q{quarter}", period.end_time.strftime("%Y-%m-%d")


def number(value, scale: float):
    if value is None or pd.isna(value):
        return None
    value = float(value) * scale
    return round(value, 8 if scale == 100 else 2) if math.isfinite(value) else None


def write_json(path: Path, value) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    path.write_text(payload, encoding="utf-8")
    return len(payload.encode("utf-8"))


def export(root: Path, output: Path) -> dict:
    source_dir = root / "data/bundled/critical_screens"
    parquet = source_dir / "dados.parquet"
    metadata = json.loads((source_dir / "metadata.json").read_text())
    frame = pd.read_parquet(parquet)
    if frame.duplicated(["InstituiçãoKey", "Período"]).any():
        raise ValueError("Instituição/período duplicado na base curada")
    missing = [definition[0] for definition in METRICS.values() if definition[0] not in frame]
    if missing:
        raise ValueError(f"Colunas curadas ausentes: {missing}")
    periods = {value: period_info(value) for value in frame["Período"].unique()}
    frame["_period"] = frame["Período"].map(lambda p: periods[p][0])
    frame = frame.sort_values(["InstituiçãoKey", "_period"])
    definitions = {
        key: {"label": label, "unit": unit, "sourceColumn": column,
              "sourceScale": scale, "source": "BCB / IF.data · base curada Toma Conta"}
        for key, (column, label, unit, scale) in METRICS.items()
    }
    definitions["roe"]["note"] = "Lucro acumulado anualizado sobre PL médio conforme critério curado do Toma Conta."
    definitions["credit"]["note"] = "Composição e regime contábil mudam em 2025. Preserve a quebra metodológica da Resolução 4.966."
    definitions["npl"]["note"] = "Indicador de carteira 4.966 disponível conforme cobertura da fonte. Ausência é N/D."
    definitions["funding"]["note"] = "Até 2024: captações; desde 2025: captações + instrumentos de dívida elegíveis a capital, exigindo ambos os componentes."
    source = {
        "name": "Banco Central do Brasil · IF.data",
        "url": "https://www3.bcb.gov.br/ifdata/",
        "file": "data/bundled/critical_screens/dados.parquet",
        "sha256": hashlib.sha256(parquet.read_bytes()).hexdigest(),
        "publicationId": metadata.get("publication_id"),
        "materializedAt": metadata.get("timestamp_salvamento"),
        "notes": [
            "Snapshot da base curada existente; os cálculos financeiros não foram refeitos no navegador.",
            "As instituições podem ter perímetros diferentes. PRUDENCIAL é mantido quando consta do nome publicado.",
            "Demais nomes pertencem ao perímetro consolidado financeiro / instituição independente desta base; não equivalem à visão individual COSIF.",
            "Percentuais expressos em pontos percentuais (0–100). Valores monetários em reais. null significa N/D; zero permanece zero.",
            "Não some conglomerados e instituições relacionadas. A lista não constitui um agregado sem duplicidades do SFN.",
            "Comparações devem usar a mesma competência e o mesmo perímetro. Instituições sem observação na competência escolhida devem ser excluídas da comparação.",
        ],
    }
    institutions = []
    bytes_written = 0
    total_history = 0
    ids = set()
    for key, group in frame.groupby("InstituiçãoKey", sort=True):
        institution_id = hashlib.sha256(str(key).encode()).hexdigest()[:16]
        if institution_id in ids:
            raise ValueError("Identificador de instituição colidiu")
        ids.add(institution_id)
        latest = group.iloc[-1]
        name = str(latest["Instituição"])
        perimeter = "Prudencial" if "PRUDENCIAL" in name.upper() else "Consolidado financeiro / instituição independente"
        history = []
        for row in group.to_dict("records"):
            period, date = periods[row["Período"]]
            history.append({
                "period": period, "date": date,
                "sourceName": row["Instituição"],
                "values": {metric: number(row[column], scale)
                           for metric, (column, _, _, scale) in METRICS.items()},
            })
        path = f"data/institutions/{institution_id}.json"
        shard = {"schemaVersion": 1, "id": institution_id, "name": name, "key": str(key),
                 "perimeter": perimeter, "sourceSha256": source["sha256"], "history": history}
        bytes_written += write_json(output / "institutions" / f"{institution_id}.json", shard)
        total_history += len(history)
        institutions.append({
            "id": institution_id, "name": name, "key": str(key), "perimeter": perimeter,
            "latestPeriod": history[-1]["period"], "firstPeriod": history[0]["period"],
            "historyCount": len(history), "historyPath": path,
            "latest": history[-1]["values"],
            "coverage": {metric: sum(row["values"][metric] is not None for row in history)
                         for metric in METRICS},
        })
    all_periods = sorted({value[0] for value in periods.values()})
    latest_period = all_periods[-1]
    result = {
        "schemaVersion": 1, "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": source, "metrics": definitions, "periods": all_periods,
        "latestPeriod": latest_period,
        "count": len(institutions), "observationCount": total_history,
        "latestInstitutionCount": sum(item["latestPeriod"] == latest_period for item in institutions),
        "institutions": institutions,
    }
    bytes_written += write_json(output / "institutions.json", result)
    summary = {"institutions": len(institutions), "observations": total_history,
               "periods": len(all_periods), "latestPeriod": latest_period,
               "latestInstitutionCount": result["latestInstitutionCount"], "bytes": bytes_written}
    print(json.dumps(summary, ensure_ascii=False))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    export(args.root, args.output or args.root / "web/public/data")
