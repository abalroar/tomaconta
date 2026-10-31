"""Registro de inconsistências da DRE prudencial contra o Relatório 4 do IF.data.

Somente leitura: não altera bases nem valores. As regras são as mesmas para qualquer
instituição e competência, para que novos meses dispensem ajustes manuais.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.ifdata_cache import CacheManager
from utils.ifdata_cache.bloprudencial_cache import load_bloprudencial_parquet_slice
from utils.prudential_analysis import build_analysis
from utils.prudential_nim import required_periods

FIELDS = ["Instituição", "Código", "Competência", "Rubrica", "Valor original (R$ mm)", "Valor apresentado (R$ mm)",
          "Causa", "Correção", "Status de validação"]
CLASSIFICATION = ("Classificação: o COSIF deixa variação cambial e outros itens em Outras Operacionais; o Rel. 4 os considera "
                  "no Resultado de Intermediação.")


def number(value):
    return round(float(value), 2) if isinstance(value, (int, float)) else ""


def findings(analysis, period):
    sheet, rows = analysis.sheets["DRE"], analysis.rows["DRE"]
    column = "C"
    read = lambda ident: getattr(sheet.cells.get(f"{column}{rows[ident]}"), "value", None)
    base = dict(zip(FIELDS[:3], (analysis.institution, analysis.code, period)))
    after, provision = read("after_pdd"), read("provision")
    pair = analysis.reference.get(period)
    reference = pair["rel4"] if pair else None
    if pair and (pair["cosif"] < 0) != (pair["rel4"] < 0):
        yield {**base, "Rubrica": "Resultado Líquido da Intermediação (janela do Rel. 4)", "Valor original (R$ mm)": number(pair["rel4"]),
               "Valor apresentado (R$ mm)": number(pair["cosif"]), "Causa": CLASSIFICATION,
               "Correção": "Nenhuma no valor; asterisco e nota automáticos", "Status de validação": "Explicado por regra; composição exata não aberta"}
    if not isinstance(after, (int, float)):
        yield {**base, "Rubrica": "Resultado Líquido da Intermediação", "Valor original (R$ mm)": number(reference),
               "Valor apresentado (R$ mm)": "–", "Causa": "Componente ausente na fonte (bruto ou provisão).",
               "Correção": "Nenhuma; ausência preservada", "Status de validação": "Ausência preservada"}
    if isinstance(provision, (int, float)) and provision > 0:
        yield {**base, "Rubrica": "Provisão para Risco de Crédito (líquida)", "Valor original (R$ mm)": number(provision),
               "Valor apresentado (R$ mm)": number(provision), "Causa": "Reversões maiores que despesas nas contas 71992 e 81992.",
               "Correção": "Nenhuma", "Status de validação": "Coerente com as contas; motivo econômico não verificado"}
    for check in analysis.checks:
        if check["period"] == period and check["status"] == "Divergência" and check["check"].startswith("DRE:"):
            yield {**base, "Rubrica": check["check"], "Valor original (R$ mm)": "", "Valor apresentado (R$ mm)": number(check["difference"] / 1e6),
                   "Causa": "Diferença entre fontes; pode refletir retificação ou composição.", "Correção": "Nenhuma",
                   "Status de validação": "Pendente de confronto com a fonte"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--periods", nargs="+", default=["202512", "202603", "202606"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manager = CacheManager(ROOT)
    sources = {kind: manager.carregar(kind).dados for kind in ("ativo", "dre", "capital", "principal", "carteira_instrumentos")}
    cosif = load_bloprudencial_parquet_slice(manager.get_cache("bloprudencial"), periodos_yyyymm=required_periods(args.periods))
    cosif["DATA_BASE"] = cosif.DATA_BASE.astype(str)
    rows, analyses, failures = [], 0, []
    for code in sorted(cosif.COD_CONGL.dropna().astype(str).unique()):
        subset = cosif[cosif.COD_CONGL.astype(str) == code]
        for period in args.periods:
            if not (subset.DATA_BASE == period).any():
                continue
            try:
                analysis = build_analysis(subset, sources, code, [period])
            except Exception as error:
                failures.append((code, period, str(error)[:100]))
                continue
            analyses += 1
            rows.extend(findings(analysis, period))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, FIELDS, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    print(f"{analyses} análises, {len(failures)} falhas, {len(rows)} registros em {args.output}")
    for failure in failures[:10]:
        print("falha:", failure)


if __name__ == "__main__":
    main()
