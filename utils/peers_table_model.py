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
    "Inadimplência / Carteira Total": ("Inadimplência / carteira total", "%", "Inadimplência ÷ carteira total do Rel. 16", "IFData Rel. 16"),
    "Ativos Estágio 2": ("Ativos em estágio 2", "R$", "Conta 3312000001", "Cadoc 4060"),
    "Ativos Estágio 3": ("Ativos em estágio 3", "R$", "Conta 3313000000", "Cadoc 4060"),
    "Ativos Estágio 3 / Carteira de Crédito": ("Estágio 3 / carteira ampliada", "%", "Estágio 3 ÷ carteira ampliada", "Cadoc 4060 + IFData Rel. 2"),
    "Inadimplência": ("Inadimplência", "R$", "Valor reportado", "IFData Rel. 16"),
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


def _catalog():
    result = []
    for block in PEERS_TABELA_LAYOUT:
        for row in block["rows"]:
            key = row["label"]
            label, unit, formula, source = _META[key]
            section = block["section"]
            if section.startswith("Qualidade Carteira"):
                section = "Qualidade da carteira" if "4060" not in section else "Detalhamento e cobertura"
            if section == "Alavancagem":
                section = "Capital e alavancagem"
            note = get_help_text(key, context="Peers") or PEERS_GLOSSARIO_RESUMIDO[key]
            result.append(Metric(key, label, section, unit, formula, source, note, key == "Lucro Líquido Acumulado"))
    return tuple(result)


METRICS = _catalog()
BY_KEY = {m.key: m for m in METRICS}
DEFAULT_METRICS = tuple(m.key for m in METRICS if m.section != "Detalhamento e cobertura" and m.key not in {"Perda Esperada", "Ativo Total / PL", "Carteira de Crédito* / PL", "Ativos Líquidos"})
INDIVIDUAL_METRICS = ("Ativo Total", "Carteira de Crédito*", "Core Funding*", "Patrimônio Líquido (PL)", "Lucro Líquido Acumulado", "ROE Acumulado YTD (%)")
BASELINES = {"year": "Mesmo trimestre do ano anterior", "quarter": "Trimestre anterior", "none": "Sem variação"}
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


def format_value(value, metric, scale):
    v = number(value)
    if v is None:
        return "N/D"
    if metric.unit == "%":
        v *= 100
    elif metric.unit == "R$":
        v /= SCALES[scale]
    return f"{v:,.2f}".replace(",", "~").replace(".", ",").replace("~", ".") + ("%" if metric.unit == "%" else "x" if metric.unit == "x" else "")


def delta(value, old, metric, mode):
    v, b = number(value), number(old)
    if mode == "none":
        return None, ""
    if metric.ytd and mode == "quarter":
        return None, "YTD: janelas diferentes"
    if v is None or b is None:
        return None, "Base N/D"
    if metric.unit == "%":
        change, unit = (v - b) * 100, "p.p."
    elif metric.unit == "x":
        change, unit = v - b, "x"
    elif b > 0:
        change, unit = (v / b - 1) * 100, "%"
    else:
        return None, "Base ≤ 0"
    rounded = round(change, 2)
    direction = "up" if rounded > 0 else "down" if rounded < 0 else "flat"
    text = f"{abs(rounded):.2f}".replace(".", ",")
    return direction, f"{'↑ +' if direction == 'up' else '↓ −' if direction == 'down' else '= '}{text} {unit}"


def build_query(df, banks, periods, metrics, values, statuses, *, base, cache_token, scale, mode, queried_at):
    """Fecha os valores e a proveniência efetivamente usados por todos os formatos."""
    if df.duplicated(["Instituição", "Período"]).any():
        raise ValueError("A base contém mais de um registro para a mesma instituição e competência.")
    lookup = {(str(r["Instituição"]), str(r["Período"])): r for r in df.to_dict("records")}
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
                analytic = {} if base == "Individual" and key == "Core Funding*" else statuses.get((key, bank, p), {})
                detail = str(analytic.get("Fonte analítica") or "")
                source = metric.source + (": " + detail if detail and detail != metric.source else "")
                status = str(analytic.get("Status analítico") or ("available" if value is not None else "missing"))
                if value is None:
                    reason = reason or str(analytic.get("Observação") or "Indicador indisponível nesta base e competência")
                    status = "missing"
                direction, variation = delta(value, old, metric, mode)
                if base != "Individual" and old_period and period_sort(p)[0] >= 2025 > period_sort(old_period)[0] and key in {"Carteira de Crédito*", "Core Funding*", "Carteira de Crédito* / PL", "Inadimplência / Carteira de Crédito", "Perda Esperada / Carteira de Crédito*"}:
                    direction, variation = None, "Quebra em 2025"
                cells.append({"metric": key, "bank": bank, "period": p, "value": value, "display": format_value(value, metric, scale), "direction": direction, "variation": variation, "reference": old_period, "reference_value": old, "status": status, "source": source, "reason": reason})
    # Hash do slice efetivo inclui componentes e referências. Independe da data da consulta.
    fingerprint = sha256(pd.util.hash_pandas_object(df.astype(str), index=False).values.tobytes()).hexdigest()
    result = {"schema_version": 1, "base": base, "banks": list(banks), "periods": list(periods), "metrics": list(metrics), "scale": scale, "mode": mode, "cache_token": cache_token, "data_sha256": fingerprint, "query_type": "Comparação de peers em competências selecionadas", "cells": cells}
    result["signature"] = sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    result["queried_at"] = queried_at
    return result


def methodology_rows(query):
    return [{"Indicador": m.label, "Unidade": query["scale"] if m.unit == "R$" else m.unit, "Fórmula": m.formula, "Fonte": m.source, "Nota": m.note} for m in (get_metric(key, query["base"]) for key in query["metrics"])]


def short_bank(bank):
    individual_names = {"ITAÚ UNIBANCO S.A.": "Itaú Unibanco", "BANCO BRADESCO S.A.": "Bradesco", "BANCO SANTANDER (BRASIL) S.A.": "Santander"}
    if bank in individual_names:
        return individual_names[bank]
    return str(bank).replace(" - PRUDENCIAL", "").replace("ITAU", "Itaú").replace("BRADESCO", "Bradesco").replace("SANTANDER", "Santander")
