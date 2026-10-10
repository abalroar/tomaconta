"""Fecha o recorte do Snapshot e seus históricos sem depender das escolhas de outras abas."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from tabs.carteira_4966 import build_carteira_4966_model, comparison_source_periods
from .peers_table_model import DEFAULT_METRICS, INDIVIDUAL_METRICS, build_query, period_sort, required_periods
from .snapshot_data import INDIVIDUAL, individual_snapshot_frame

BASE = "Consolidada / Prudencial"
log = logging.getLogger(__name__)


def latest_periods(periods, cutoff, count=3):
    """Últimas competências publicadas até a data-base, em ordem cronológica."""
    available = {str(p) for p in periods if pd.notna(p) and period_sort(p) <= period_sort(cutoff)}
    return sorted(available, key=period_sort)[-count:]


def snapshot_payload(bank, period, qoq_period, yoy_period, groups, histories, api, *, base=BASE):
    """Reutiliza exatamente a formatação, os deltas e as cores dos cards."""
    cards = []
    for group, configs in groups:
        for cfg in configs:
            series = cfg.get("serie", {})
            current = series.get(period)
            qlabel, ylabel = api["_snapshot_comparison_labels"](cfg)
            qoq = api["_snapshot_card_delta"](cfg, period, qoq_period, qlabel)
            yoy = api["_snapshot_card_delta"](cfg, period, yoy_period, ylabel)
            if cfg.get("comparison") == "yoy":
                qoq = {"display": "—", "tone": "neutral", "reason": "Acumulado no ano: comparar com os mesmos meses do ano anterior."}
            qoq["reference_period"] = qoq_period
            yoy["reference_period"] = yoy_period
            marker = cfg.get("status_marker", "")
            history = dict(histories.get(cfg["label"], {}))
            # O último trecho do histórico compara pontos consecutivos. Cards
            # acumulados no ano mantêm esse detalhe neutro por sazonalidade.
            comparison = qoq
            history["tone"] = cfg.get("history_tone", comparison.get("tone", "neutral"))
            history["direction"] = cfg.get("history_direction", comparison.get("direction"))
            cards.append({
                "key": cfg.get("format_key", cfg["label"]), "label": cfg["label"], "group": group,
                "value": api["_formatar_valor_snapshot"](cfg, current) + marker,
                "raw_value": current, "qoq": qoq, "yoy": yoy,
                "history": history, "source": cfg.get("source", ""),
                "scope": cfg.get("scope", base),
                "subtitle": cfg.get("subtitle", ""),
                "source_label": cfg.get("source_label", cfg.get("source", "")),
                "notes": cfg.get("notes") or cfg.get("definition") or api["get_help_text"](cfg.get("format_key", cfg["label"])) or api["get_help_text"](cfg["label"]),
                "status": cfg.get("status_note", ""),
            })
    individual = base == INDIVIDUAL
    return {
        "bank": bank, "base": base, "period": period, "period_label": api["periodo_para_exibicao"](period),
        "qoq_period_label": api["periodo_para_exibicao"](qoq_period) if qoq_period else "N/D",
        "yoy_period_label": api["periodo_para_exibicao"](yoy_period) if yoy_period else "N/D",
        "queried_at": datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M %Z"),
        "cards": cards,
        "notes": ("IFData trimestral. Perímetro Individual: entidade jurídica selecionada, sem consolidação do grupo. " if individual else
                  "IFData trimestral. Perímetro conforme a instituição selecionada: conglomerado prudencial ou instituição independente. ") +
                 "Saldos são de fechamento; lucro acumulado e ROE acumulado comparam os mesmos meses. "
                 "N/D preserva ausência de fonte ou denominador válido. As mudanças do IFData em 2025 afetam a comparação histórica.",
        "source_notes": (
            "Individual: balanço e carteira do Rel. 1; despesas de captação do Rel. 4 individual, quando disponíveis. "
            "Lucro YTD de set/dez soma junho ao segundo semestre; sem junho permanece N/D. "
            "ROE anualizado usa o patrimônio líquido atual. Capital, estágios, PDD e arrasto permanecem N/D "
            "quando não há fonte no mesmo perímetro. Os dados do conglomerado não completam as lacunas individuais."
            if individual else
            "Snapshot: Perda Esperada é o agregado curado do Rel. 2, que pode incluir ajustes de hedge e de valor justo. "
            "Carteira 4.966: PDD soma somente e2 + f2 + g2 + h2; cobre também ativos fora dos vencidos por arrasto. "
            "Inadimplência >90 dias: saldo integral das operações por arrasto dividido pela carteira total do Rel. 16, desde mar/2025."
        ),
    }


def peers_history(df, bank, cutoff, api, queried_at, *, base=BASE):
    df = df[df["Instituição"].astype(str).str.strip().eq(str(bank).strip())].copy()
    individual = base == INDIVIDUAL
    if individual:
        df = individual_snapshot_frame(df, bank)
    periods = latest_periods(df["Período"].dropna().unique(), cutoff)
    extended = required_periods(periods, "quarter")
    selected = df[df["Período"].astype(str).isin(extended)].copy()
    prepare_key = "_preparar_metricas_extra_peers_individual_from_slice" if individual else "_preparar_metricas_extra_peers_from_slice"
    extra = api[prepare_key](selected, [bank], extended)
    # Preserva o mesmo cache fechado do Snapshot, inclusive capital ausente.
    # O fallback global reconstruiria toda a base durante este download.
    values, columns, *_ = api["_montar_tabela_peers"](selected, [bank], list(extended), extra_values_precomputed=extra, allow_capital_fallback=False)
    statuses = api["_build_peers_status_lookup"](df_base=selected, bancos=[bank], periodos=periods, valores=values, colunas_usadas=columns)
    return build_query(selected, [bank], periods, list(INDIVIDUAL_METRICS if individual else DEFAULT_METRICS), values, statuses,
                       base=base, cache_token=api["_cache_version_token"]("principal_individual" if individual else "critical_screens"),
                       scale="R$ bilhões", mode="quarter", queried_at=queried_at)


def institution_slice(df, bank, codes, normalize):
    """Correspondência exata de nome canônico ou código oficial, sem aproximação."""
    if df is None or df.empty or "Instituição" not in df:
        return pd.DataFrame()
    mask = df["Instituição"].astype(str).str.strip().eq(str(bank).strip())
    if codes and "CodInst" in df:
        mask |= df["CodInst"].map(normalize).isin(codes)
    return df.loc[mask].copy()


def carteira_history(bank, cutoff, api, *, base=BASE):
    if base == INDIVIDUAL:
        return None, "Carteira 4.966 permanece N/D na base Individual: Rel. 16 e PDD do Rel. 2 não estão disponíveis nos caches no mesmo perímetro da entidade jurídica selecionada.", []
    manifest = api["_carregar_manifest_release_cache"](api["_CARTEIRA_4966_RELEASE_MANIFEST_URL"], api["_EXPECTED_CACHE_RELEASE_TAG"])
    token = api["_carteira_4966_release_token"](manifest)
    serialized = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    df, status = api["load_carteira_4966_data"](token, serialized)
    if not status.get("valid") or df is None or df.empty:
        return None, "Carteira 4.966 indisponível: a fonte não possui cobertura validada para este recorte.", []
    source = institution_slice(df, bank, set(), api["normalize_institution_code"])
    if source.empty:
        return None, "Sem publicação de Carteira 4.966 para a instituição e o perímetro do Snapshot. Dados disponíveis desde mar/2025.", []
    pcol = "Período" if "Período" in source else "Periodo"
    periods = latest_periods(source[pcol].dropna().unique(), cutoff)
    if not periods:
        return None, "Sem competências da Carteira 4.966 até a data-base do Snapshot. Dados disponíveis desde mar/2025.", []
    codes = {normalized for value in source.get("CodInst", pd.Series(dtype=object)).dropna()
             if (normalized := api["normalize_institution_code"](value))}
    warnings = [str(status["warning"])] if status.get("warning") else []
    if status.get("identity_collision_count"):
        warnings.append("Sobreposições de identidade na fonte: a linha oficial mais completa foi priorizada.")
    ativo = pd.DataFrame()
    try:
        raw, ativo_status = api["load_carteira_4966_ativo_periods"](token, serialized, comparison_source_periods(periods))
        if ativo_status.get("valid") and raw is not None and not raw.empty:
            canonical = api["canonicalize_institution_history"](raw, base_dir=api["APP_DIR"])
            ativo = institution_slice(canonical, bank, codes, api["normalize_institution_code"])
        else:
            warnings.append("Fonte de provisão do Rel. 2 indisponível; indicadores de PDD permanecem N/D.")
        if ativo_status.get("warning"):
            warnings.append(str(ativo_status["warning"]))
    except Exception:
        log.exception("Falha na fonte de provisão para Snapshot PPT")
        warnings.append("Fonte de provisão do Rel. 2 indisponível; indicadores de PDD permanecem N/D.")
    if len(periods) < 3:
        warnings.append(f"A instituição possui somente {len(periods)} competência(s) de Carteira 4.966 até a data-base.")
    return build_carteira_4966_model(source, ativo, periods), "", warnings


def export_snapshot_package(snapshot, df_bank_all, api):
    """Chamado somente no download: falha de uma fonte preserva os demais slides."""
    from .snapshot_pptx_export import export_snapshot_powerpoint
    peer_reason = carteira_reason = ""
    peers = carteira = None
    warnings = []
    base = snapshot.get("base", BASE)
    try:
        peers = peers_history(df_bank_all, snapshot["bank"], snapshot["period"], api, snapshot["queried_at"], base=base)
    except Exception:
        log.exception("Falha no histórico de Peers para Snapshot PPT")
        peer_reason = "Histórico da Tabela de Peers indisponível para este recorte."
    try:
        carteira, carteira_reason, warnings = carteira_history(snapshot["bank"], snapshot["period"], api, base=base)
    except Exception:
        log.exception("Falha na Carteira 4.966 para Snapshot PPT")
        carteira_reason = "Fonte da Carteira 4.966 indisponível para este recorte."
    payload = {**snapshot, "carteira_notes": warnings}
    return export_snapshot_powerpoint(payload, peers, carteira, peers_unavailable_reason=peer_reason,
                                     carteira_unavailable_reason=carteira_reason)
