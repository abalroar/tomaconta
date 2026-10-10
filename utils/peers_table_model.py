"""Consulta imutável e catálogo da nova tabela; sem alterar o cache legado."""
from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
import math
from typing import Mapping

import pandas as pd

from tabs.peers_config import PEERS_TABELA_LAYOUT, PEERS_GLOSSARIO_RESUMIDO
from utils.ui_help import get_help_text
from utils.snapshot_delta import compute_delta
from utils.formatting import formatar_delta_br


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    section: str
    unit: str
    formula: str
    source: str
    note: str = ""
    ytd: bool = False
    delta_kind: str = "pct"
    delta_unit: str = "%"
    delta_decimals: int = 2
    value_decimals: int = 2
    favorable_direction: str | None = None


_META = {
    "Ativo Total": ("Ativo total", "R$", "Valor reportado", "IFData Rel. 1"),
    "Ativos Líquidos": ("Ativos líquidos", "R$", "Disponibilidades + AIL + TVM", "IFData Rel. 2"),
    "Carteira de Crédito*": ("Carteira de crédito ampliada", "R$", "Carteira bruta e1 + f1 + g1 + h1 (2025+); regra histórica no detalhe", "IFData Rel. 2"),
    "Perda Esperada": ("Perdas e ajustes contábeis", "R$", "Perdas esperadas + hedge + ajustes a valor justo", "IFData Rel. 2"),
    "Depósitos Totais": ("Depósitos totais", "R$", "Agregado publicado; soma dos componentes quando o agregado está ausente", "IFData Rel. 3"),
    "Core Funding*": ("Core funding", "R$", "Até 2024: captações. 2025+: captações + instrumentos elegíveis a capital", "IFData Rel. 3"),
    "Patrimônio Líquido (PL)": ("Patrimônio líquido", "R$", "Valor reportado", "IFData Rel. 1"),
    "Custo de Crédito (%)": ("Custo de crédito", "%", "−resultado f3 YTD × fator anual ÷ carteira ampliada", "IFData Rel. 4 + Rel. 2"),
    "Custo de Crédito / Receita de Crédito (%)": ("Custo / receita de crédito", "%", "−resultado f3 YTD ÷ receita de crédito YTD", "IFData Rel. 4"),
    "Ativos Problemáticos / Carteira Total": ("Ativos problemáticos / carteira", "%", "Ativos problemáticos ÷ carteira total do Rel. 16", "IFData Rel. 16"),
    "Inadimplência / Carteira Total": ("Vencidos >90 dias (arrasto) / carteira total", "%", "Inadimplência ÷ Total Geral do Rel. 16", "IFData Rel. 16"),
    "Ativos Estágio 2": ("Ativos em estágio 2", "R$", "Conta 3312000001", "Cadoc 4060"),
    "Ativos Estágio 3": ("Ativos em estágio 3", "R$", "Conta 3313000000", "Cadoc 4060"),
    "Ativos Estágio 3 / Carteira de Crédito": ("Estágio 3 / carteira ampliada", "%", "Estágio 3 ÷ carteira ampliada", "Cadoc 4060 + IFData Rel. 2"),
    "Inadimplência": ("Vencidos >90 dias (arrasto)", "R$", "Saldo integral das operações com alguma parcela vencida há mais de 90 dias", "IFData Rel. 16"),
    "Inadimplência / Carteira de Crédito": ("Inadimplência / carteira ampliada", "%", "Inadimplência do Rel. 16 ÷ carteira ampliada do Rel. 2", "IFData Rel. 16 + Rel. 2"),
    "Perda Esperada / Estágio 3": ("Perdas e ajustes / estágio 3", "%", "|Perdas e ajustes contábeis| ÷ estágio 3", "IFData Rel. 2 + Cadoc 4060"),
    "Perda Esperada / Est2+3": ("Perdas e ajustes / estágios 2 e 3", "%", "|Perdas e ajustes contábeis| ÷ (estágio 2 + estágio 3)", "IFData Rel. 2 + Cadoc 4060"),
    "Perda Esperada / Carteira de Crédito*": ("Perdas e ajustes / carteira ampliada", "%", "|Perdas e ajustes contábeis| ÷ carteira ampliada", "IFData Rel. 2"),
    "Ativo Total / PL": ("Ativo / PL", "x", "Ativo total ÷ patrimônio líquido", "IFData Rel. 1"),
    "Carteira de Crédito* / PL": ("Carteira ampliada / PL", "x", "Carteira ampliada ÷ patrimônio líquido", "IFData Rel. 2 + Rel. 1"),
    "Índice de Capital Principal (CET1)": ("Capital principal (CET1)", "%", "Capital principal ÷ RWA total", "IFData Rel. 5"),
    "Índice de Basileia Total (%)": ("Basileia total", "%", "(Capital principal + complementar + nível II) ÷ RWA; índice publicado como fallback", "IFData Rel. 5"),
    "Lucro Líquido Acumulado": ("Lucro líquido acumulado", "R$", "Lucro líquido de janeiro até a competência", "IFData Rel. 1"),
    "ROE Acumulado YTD (%)": ("ROE anualizado", "%", "Lucro YTD × fator anual ÷ média do PL atual e dezembro anterior", "IFData Rel. 1"),
}

# A unidade do nível (%) não determina a unidade mais legível da variação.
# Coberturas e custo/receita usam p.p.; taxas de capital, retorno e risco usam bps.
_PERCENTAGE_POLICIES = {
    "Custo de Crédito (%)": ("bps", "down"),
    "Custo de Crédito / Receita de Crédito (%)": ("pp", "down"),
    "Ativos Problemáticos / Carteira Total": ("bps", "down"),
    "Inadimplência / Carteira Total": ("bps", "down"),
    "Ativos Estágio 3 / Carteira de Crédito": ("bps", "down"),
    "Inadimplência / Carteira de Crédito": ("bps", "down"),
    "Perda Esperada / Estágio 3": ("pp", "up"),
    "Perda Esperada / Est2+3": ("pp", "up"),
    "Perda Esperada / Carteira de Crédito*": ("bps", None),
    "PDD / Inadimplência (arrasto)": ("pp", "up"),
    "Índice de Capital Principal (CET1)": ("bps", "up"),
    "Índice de Basileia Total (%)": ("bps", "up"),
    "ROE Acumulado YTD (%)": ("bps", "up"),
}


def _with_variation_policy(metric):
    if metric.unit == "%":
        kind, favorable = _PERCENTAGE_POLICIES[metric.key]
        return replace(metric, delta_kind=kind, delta_unit="p.p." if kind == "pp" else "bps",
                       delta_decimals=1 if kind == "pp" else 0,
                       value_decimals=2,
                       favorable_direction=favorable)
    if metric.unit == "x":
        return replace(metric, delta_kind="absolute", delta_unit="x", favorable_direction="down")
    return metric  # Saldos: crescimento relativo, sem juízo automático de crédito.


def _catalog():
    result = []
    for block in PEERS_TABELA_LAYOUT:
        for row in block["rows"]:
            key = row["label"]
            if key == "Inadimplência":
                continue  # O volume aparece junto à participação, no bloco de qualidade.
            label, unit, formula, source = _META[key]
            section = block["section"]
            if section.startswith("Qualidade Carteira"):
                section = "Qualidade da carteira" if "4060" not in section else "Detalhamento e cobertura"
            if section == "Alavancagem":
                section = "Capital e alavancagem"
            note = get_help_text(key, context="Peers") or PEERS_GLOSSARIO_RESUMIDO[key]
            if key == "Inadimplência / Carteira Total":
                volume = _META["Inadimplência"]
                result.append(Metric("Inadimplência", volume[0], section, *volume[1:],
                                     get_help_text("Inadimplência", context="Peers")))
            result.append(Metric(key, label, section, unit, formula, source, note, key == "Lucro Líquido Acumulado"))
            if key == "Inadimplência / Carteira Total":
                result.append(Metric(
                    "PDD / Inadimplência (arrasto)", "PDD / vencidos >90 dias (arrasto)", section, "%",
                    "|e2 + f2 + g2 + h2 do Rel. 2| ÷ Inadimplência do Rel. 16",
                    "IFData Rel. 2 + Rel. 16", get_help_text("PDD / Inadimplência (arrasto)", context="Peers"),
                ))
    return tuple(_with_variation_policy(metric) for metric in result)


METRICS = _catalog()
BY_KEY = {m.key: m for m in METRICS}
DEFAULT_METRICS = tuple(m.key for m in METRICS if m.section != "Detalhamento e cobertura" and m.key not in {"Perda Esperada", "Ativo Total / PL", "Carteira de Crédito* / PL", "Ativos Líquidos"})
INDIVIDUAL_METRICS = ("Ativo Total", "Carteira de Crédito*", "Core Funding*", "Patrimônio Líquido (PL)", "Lucro Líquido Acumulado", "ROE Acumulado YTD (%)")
BASELINES = {"quarter": "QoQ · trimestre anterior", "year": "YoY · mesmo trimestre do ano anterior", "none": "Sem variação"}
SCALES = {"R$ milhões": 1e6, "R$ bilhões": 1e9}
COLORS = ("#174A7E", "#B35421", "#56734A", "#7C5C8F", "#276C75", "#6B6B6B")


def get_metric(key, base):
    metric = BY_KEY[key]
    if base != "Individual":
        return metric
    overrides = {
        "Carteira de Crédito*": dict(label="Carteira de crédito", formula="Carteira de crédito publicada; classificada quando a carteira está ausente", note="Carteira do Rel. 1 individual."),
        "Core Funding*": dict(label="Captações", formula="Captações publicadas", note="Captações do Rel. 1 individual."),
        "Carteira de Crédito* / PL": dict(label="Carteira de crédito / PL", formula="Carteira do Rel. 1 ÷ patrimônio líquido", note="Perímetro individual."),
        "ROE Acumulado YTD (%)": dict(formula="Lucro YTD × fator anual ÷ PL atual", note="ROE do cache individual usa o PL atual. Fator Mar=4, Jun=2, Set=12/9, Dez=1."),
    }
    supported = key in INDIVIDUAL_METRICS or key in {"Ativo Total / PL", "Carteira de Crédito* / PL"}
    result = replace(metric, source="IFData Rel. 1 individual" if supported else metric.source,
                     **overrides.get(key, {}))
    return replace(result, note=get_help_text(key, base="Individual", context="Peers") if supported
                   else "Indicador indisponível na base individual desta aba. O valor permanece N/D.")


def number(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def period_sort(p):
    q, y = str(p).split("/")
    return int(y), int(q)


def period_label(p):
    q, y = period_sort(p)[1], period_sort(p)[0]
    return f"{['Mar','Jun','Set','Dez'][q-1]}/{y % 100:02d}"


def reference(p, mode):
    y, q = period_sort(p)
    if mode == "year":
        return f"{q}/{y-1}"
    if mode == "quarter":
        return f"{q-1}/{y}" if q > 1 else f"4/{y-1}"
    return None


def required_periods(periods, mode):
    all_periods = set(periods)
    all_periods.update(reference(p, mode) for p in periods)
    all_periods.discard(None)
    all_periods.update(f"4/{period_sort(p)[0]-1}" for p in tuple(all_periods))
    all_periods.update(f"2/{period_sort(p)[0]}" for p in tuple(all_periods) if period_sort(p)[1] > 2)
    return tuple(sorted(all_periods, key=period_sort))


def comparison_label(mode):
    return {"quarter": "QoQ", "year": "YoY", "none": ""}[mode]


def period_comparison_label(p, mode):
    base = reference(p, mode)
    return f"{comparison_label(mode)} vs {period_label(base)}" if base else ""


def delta_measure(value, old, metric):
    """Subtração de razões e múltiplos; crescimento relativo de montantes."""
    return compute_delta(value, old, metric.delta_kind, "dec" if metric.unit == "%" else "pct"), metric.delta_unit


def format_value(value, metric, scale):
    v = number(value)
    if v is None:
        return "N/D"
    if metric.unit == "%":
        v *= 100
    elif metric.unit == "R$":
        v /= SCALES[scale]
    return f"{v:,.{metric.value_decimals}f}".replace(",", "~").replace(".", ",").replace("~", ".") + ("%" if metric.unit == "%" else "x" if metric.unit == "x" else "")


def delta(value, old, metric, mode):
    v, b = number(value), number(old)
    if mode == "none":
        return None, ""
    if metric.ytd and mode == "quarter":
        return None, "YTD: janelas diferentes"
    if v is None or b is None:
        return None, "Base N/D"
    change, unit = delta_measure(v, b, metric)
    if change is None:
        return None, "Base ≤ 0"
    direction = "up" if change > 0 else "down" if change < 0 else "flat"
    return direction, formatar_delta_br(change, unit, metric.delta_decimals, com_seta=True)


VARIATION_NOTE = "Variações: capital, retorno e taxas de risco em bps inteiros; coberturas e custo/receita em p.p.; saldos em %; alavancagem em x. Razões e múltiplos usam subtração."
COLOR_NOTE = "Verde: direção usualmente favorável no indicador. Vermelho: direção de atenção. Saldos e indicadores sem leitura unívoca usam cor neutra. As setas indicam alta ou queda."
VARIATION_COLORS = {"favorable": "#16713B", "attention": "#B32624", "neutral": "#666666"}


def variation_tone(metric, direction, status="available"):
    if direction not in {"up", "down"} or metric.favorable_direction is None or status not in {"available", "curated_value", "derived_from_curated"}:
        return "neutral"
    return "favorable" if direction == metric.favorable_direction else "attention"


def variation_definition(metric):
    return {"bps": "diferença entre percentuais × 100; bps arredondados ao inteiro",
            "pp": "percentual atual − percentual de referência; diferença em p.p.",
            "absolute": "múltiplo atual − múltiplo de referência; diferença em x",
            "pct": "(saldo atual − saldo de referência) ÷ saldo de referência × 100; requer base positiva"}[metric.delta_kind]


ARRASTO_ROWS = {
    "Inadimplência": ("delinquency", "primary"),
    "Inadimplência / Carteira Total": ("delinquency", "secondary"),
    "PDD / Inadimplência (arrasto)": ("provision_over_delinquency", "primary"),
}


def arrasto_lookup(df):
    """Adapta componentes do cache curado ao mesmo modelo e alertas da aba 4.966."""
    from tabs.carteira_4966 import EXPECTED_LOSS_COLUMNS, build_carteira_4966_model, quality_issue_message

    result = {}
    for bank, frame in df.groupby("Instituição", sort=False):
        periods = [str(p) for p in frame["Período"] if period_sort(p)[0] >= 2025]
        if not periods:
            continue
        # O cache também contém aliases legados. Selecionar explicitamente evita
        # criar duas colunas Inadimplência e tomar um agregado de outro conceito.
        portfolio = pd.DataFrame({"Período": frame["Período"],
                                  "Total Geral": frame.get("Carteira Total 4.966"),
                                  "Inadimplência": frame.get("Inadimplência 4.966")})
        losses = pd.DataFrame({"Período": frame["Período"],
                               **{c: frame[f"Trace::Perda Esperada::{c}"] for c in EXPECTED_LOSS_COLUMNS
                                  if f"Trace::Perda Esperada::{c}" in frame}})
        model = build_carteira_4966_model(portfolio, losses, periods)
        for key, (row_key, field) in ARRASTO_ROWS.items():
            for p in model.periods:
                issues = model.cell_quality_issues(row_key, p)
                result[key, str(bank), p] = {
                    "value": getattr(model.cells[row_key][p], field),
                    "status": "critical" if any(i.severity == "critical" for i in issues) else "warning" if issues else "available",
                    "reason": "\n".join(quality_issue_message(i) for i in issues),
                }
    return result


def build_query(df, banks, periods, metrics, values, statuses, *, base, cache_token, scale, mode, queried_at):
    """Fecha os valores e a proveniência efetivamente usados por todos os formatos."""
    if df.duplicated(["Instituição", "Período"]).any():
        raise ValueError("A base contém mais de um registro para a mesma instituição e competência.")
    lookup = {(str(r["Instituição"]), str(r["Período"])): r for r in df.to_dict("records")}
    arrasto = arrasto_lookup(df) if base != "Individual" and any(key in ARRASTO_ROWS for key in metrics) else {}
    cells = []
    for key in metrics:
        metric = get_metric(key, base)
        for bank in banks:
            for p in periods:
                old_period = reference(p, mode)
                row = lookup.get((bank, p), {})
                value = number(values.get((key, bank, p)))
                old = number(values.get((key, bank, old_period)))
                reason = ""
                arrasto_status = None
                if base != "Individual" and key in ARRASTO_ROWS:
                    current = arrasto.get((key, bank, p), {})
                    value = current.get("value")
                    old = arrasto.get((key, bank, old_period), {}).get("value")
                    arrasto_status = current.get("status", "missing")
                    reason = current.get("reason", "")
                    if period_sort(p)[0] < 2025:
                        reason = "Relatório 16 disponível a partir de mar/2025; sem série retroativa neste conceito."
                if base == "Individual":
                    if key == "Core Funding*":
                        value = number(row.get("Captações"))
                        old = number(lookup.get((bank, old_period), {}).get("Captações"))
                    elif key not in INDIVIDUAL_METRICS and key not in {"Ativo Total / PL", "Carteira de Crédito* / PL"}:
                        value, old = None, None
                        reason = "Indicador não disponível no cache de demonstrações individuais"
                if metric.ytd or key == "ROE Acumulado YTD (%)":
                    def comparable_ytd(r, period):
                        if not r or not period:
                            return False
                        year, quarter = period_sort(period)
                        return quarter <= 2 or number(lookup.get((bank, f"2/{year}"), {}).get("Lucro Líquido Acumulado YTD")) is not None
                    if not comparable_ytd(row, p):
                        value = None
                        reason = "Lucro YTD sem base de junho para recompor o segundo semestre"
                    if not comparable_ytd(lookup.get((bank, old_period), {}), old_period):
                        old = None
                # Corrige apenas a consulta desta aba. Mantém as colunas do legado.
                if key.startswith("Custo") and base != "Individual":
                    trace = "Trace::Custo de Crédito::PDD Crédito Anualizada" if key == "Custo de Crédito (%)" else "Trace::Custo de Crédito::PDD Crédito YTD"
                    denominator = "Carteira de Crédito Bruta" if key == "Custo de Crédito (%)" else "Trace::Custo de Crédito::Receita de Crédito YTD"
                    def signed(r):
                        n, d = number(r.get(trace)), number(r.get(denominator))
                        return -n / d if n is not None and d is not None and d > 0 else None
                    value, old = signed(row), signed(lookup.get((bank, old_period), {}))
                if key == "Ativos Líquidos" and base != "Individual":
                    components = [number(row.get(f"Trace::Ativos Líquidos::{c}")) for c in ("Disponibilidades (a)", "Aplicações Interfinanceiras de Liquidez (b)", "Títulos e Valores Mobiliários (c)")]
                    if any(c is None for c in components):
                        value = None
                        reason = "Componentes de liquidez incompletos"
                    else:
                        value = sum(components)
                    old_row = lookup.get((bank, old_period), {})
                    old_components = [number(old_row.get(f"Trace::Ativos Líquidos::{c}")) for c in ("Disponibilidades (a)", "Aplicações Interfinanceiras de Liquidez (b)", "Títulos e Valores Mobiliários (c)")]
                    old = sum(old_components) if all(c is not None for c in old_components) else None
                analytic = {} if key in ARRASTO_ROWS or base == "Individual" and key == "Core Funding*" else statuses.get((key, bank, p), {})
                detail = str(analytic.get("Fonte analítica") or "")
                source = metric.source + (": " + detail if detail and detail != metric.source else "")
                status = str(arrasto_status or analytic.get("Status analítico") or ("available" if value is not None else "missing"))
                if value is None:
                    reason = reason or str(analytic.get("Observação") or "Indicador indisponível nesta base e competência")
                    status = "missing"
                direction, variation = delta(value, old, metric, mode)
                if base != "Individual" and old_period and period_sort(p)[0] >= 2025 > period_sort(old_period)[0] and key in {"Carteira de Crédito*", "Core Funding*", "Carteira de Crédito* / PL", "Inadimplência / Carteira de Crédito", "Perda Esperada / Carteira de Crédito*"}:
                    direction, variation = None, "Quebra em 2025"
                display = format_value(value, metric, scale) + ("†" if status in {"warning", "critical"} else "")
                delta_value, delta_unit = delta_measure(value, old, metric)
                if direction is None:
                    delta_value = None
                cells.append({"metric": key, "bank": bank, "period": p, "value": value, "display": display, "direction": direction, "variation": variation, "delta_value": delta_value, "delta_unit": delta_unit, "reference": old_period, "reference_value": old, "status": status, "source": source, "reason": reason})
    # Hash do slice efetivo inclui componentes e referências. Independe da data da consulta.
    fingerprint = sha256(pd.util.hash_pandas_object(df.astype(str), index=False).values.tobytes()).hexdigest()
    result = {"schema_version": 3, "base": base, "banks": list(banks), "periods": list(periods), "metrics": list(metrics), "scale": scale, "mode": mode, "cache_token": cache_token, "data_sha256": fingerprint, "query_type": "Comparação de peers em competências selecionadas", "cells": cells}
    result["signature"] = sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    result["queried_at"] = queried_at
    return result


def methodology_rows(query):
    return [{"Indicador": m.label, "Unidade": query["scale"] if m.unit == "R$" else m.unit, "Variação": variation_definition(m), "Unidade da variação": m.delta_unit, "Fórmula": m.formula, "Fonte": m.source, "Nota": m.note} for m in (get_metric(key, query["base"]) for key in query["metrics"])]


def short_bank(bank):
    individual_names = {"ITAÚ UNIBANCO S.A.": "Itaú Unibanco", "BANCO BRADESCO S.A.": "Bradesco", "BANCO SANTANDER (BRASIL) S.A.": "Santander"}
    if bank in individual_names:
        return individual_names[bank]
    return str(bank).replace(" - PRUDENCIAL", "").replace("ITAU", "Itaú").replace("BRADESCO", "Bradesco").replace("SANTANDER", "Santander")
