#!/usr/bin/env python3
"""Materializa SCR.data e SPB para o piloto sem executar a interface Streamlit."""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def numeric(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def date(value):
    text = str(value)
    if re.fullmatch(r"\d{5}", text):
        return pd.Period(year=int(text[:4]), quarter=int(text[4]), freq="Q").end_time.strftime("%Y-%m-%d")
    if re.fullmatch(r"\d{6}", text):
        return pd.Timestamp(year=int(text[:4]), month=int(text[4:]), day=1).strftime("%Y-%m-%d")
    try:
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return text


def chart(key, title, section, unit, series, note, source="BCB · Olinda/MPV_DadosAbertos", stacked=False):
    all_dates = [p[0] for s in series for p in s["data"] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p[0]) and p[1] is not None]
    competence = max(all_dates)[:7] if all_dates else None
    return {"id": key, "title": title, "section": section, "unit": unit, "source": source,
            "note": note + (f" Última competência disponível neste gráfico: {competence}." if competence else ""),
            "percent": "%" in unit, "stacked": stacked, "series": series,
            "latestPeriod": competence}


def scr_charts(cache_dir: Path):
    from tabs.mercado_credito import _figuras_faixa_de_renda

    metadata = json.loads((cache_dir / "metadata.json").read_text())
    periods = sorted(metadata.get("periodos", []))
    end = pd.Timestamp(periods[-1] + "-01")
    start = end - pd.DateOffset(months=23)
    available_years = {int(p.stem) for p in (cache_dir / "staging/annual").glob("*.parquet")}
    start = max(start, pd.Timestamp(year=min(available_years), month=1, day=1))

    class LocalCache:
        def get_info(self):
            return metadata

        def carregar_detalhe(self, *, anos):
            frames = [pd.read_parquet(cache_dir / "staging/annual" / f"{year}.parquet")
                      for year in anos if year in available_years]
            return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    class Manager:
        def get_cache(self, name):
            return LocalCache() if name == "scr_data" else None

    figures = _figuras_faixa_de_renda(lambda: Manager(), inicio=start, fim=end)
    charts = []
    regional_title = re.sub(r"<[^>]*>", " ", figures[-1].layout.title.text or "") if figures else ""
    regional_product = regional_title.removesuffix(" por região")
    for i, fig in enumerate(figures):
        meta = dict(fig.layout.meta or {})
        scale = float(meta.get("value_scale", 1.0)) * 100
        series = []
        for trace in fig.data:
            if getattr(trace, "y", None) is None:
                continue
            xs, ys = trace.x, trace.y
            if getattr(trace, "orientation", None) == "h":
                xs, ys = ys, xs
            points = [[date(x), None if numeric(y) is None else numeric(y) * scale]
                      for x, y in zip(xs, ys)]
            series.append({"name": trace.name or "Inadimplência", "type": "bar" if trace.type == "bar" else "line", "data": points})
        title = re.sub(r"<[^>]*>", " ", meta.get("chart_title") or fig.layout.title.text or f"SCR.data {i + 1}")
        if title.endswith("por UF") and regional_product:
            title += " · " + regional_product
        note = (f"SCR.data: inadimplência calculada pelos construtores existentes do Toma Conta. "
                f"Base disponível {start:%Y-%m} a {end:%Y-%m}; recortes por renda, região e UF. "
                "Razão entre somas do numerador e da carteira ativa, sem média de percentuais entre UFs. "
                "A classificação das modalidades segue o de-para BCB e pode ter quebras de série.")
        item = chart(f"scr-{i}", title, "SCR.data · renda e região", "%", series, note,
                     source="BCB · SCR.data · https://www.bcb.gov.br/estabilidadefinanceira/scrdata")
        if not item["latestPeriod"]:
            item["latestPeriod"] = end.strftime("%Y-%m")
            item["note"] += f" Distribuição regional referente a {end:%Y-%m}."
        charts.append(item)
    return charts


def spb_charts(source_dir: Path):
    from utils.spb_meios_pagamento_viz import melt_nucleo_spb, compute_share, SPB_CONSOLIDADO_MAPA

    charts = []

    def grouped(data, group_col, value_col, key, title, unit, note, *, scale=1, mean=False):
        selected = data.dropna(subset=[group_col]).copy()
        selected[value_col] = pd.to_numeric(selected[value_col], errors="coerce")
        grouped = selected.groupby(["trimestre", group_col], as_index=False)[value_col]
        grouped = grouped.mean() if mean else grouped.sum(min_count=1)
        series = [{"name": str(name), "type": "line", "data": [[date(p), None if numeric(v) is None else numeric(v) * scale]
                    for p, v in zip(part["trimestre"], part[value_col])]}
                  for name, part in grouped.sort_values("trimestre").groupby(group_col, sort=True)]
        charts.append(chart(key, title, "Meios de pagamento · SPB", unit, series, note))

    for filename, frequency, period_col in (("nucleo_mensal", "mensal", "ano_mes"), ("nucleo_trimestral", "trimestral", "trimestre")):
        raw = pd.read_parquet(source_dir / f"{filename}.parquet")
        long = melt_nucleo_spb(raw, period_col, frequency)
        for tipo, unit, suffix in (("Quantidade (mil)", "mil transações", "quantidade"), ("Valor (R$ milhão)", "R$ milhões", "valor")):
            subset = long[long.tipo == tipo]
            series = [{"name": str(name), "type": "line", "data": [[date(x), numeric(v)] for x, v in zip(part.periodo_ordem, part.valor)]}
                      for name, part in subset.groupby("instrumento", sort=False)]
            charts.append(chart(f"spb-{frequency}-{suffix}", f"Meios de pagamento · {suffix} {frequency}", "Meios de pagamento · SPB", unit, series,
                                "Unidades e séries do núcleo SPB preservadas. A base mensal não contém cartões; a trimestral inclui os instrumentos publicados."))
            if frequency == "trimestral":
                shares = compute_share(long, tipo, long.instrumento.unique().tolist())
                share_series = [{"name": str(name), "type": "line", "data": [[date(x), numeric(v)] for x, v in zip(part.periodo_ordem, part.participacao)]}
                                for name, part in shares.groupby("instrumento", sort=False)]
                charts.append(chart(f"spb-participacao-{suffix}", f"Participação por instrumento · {suffix}", "Meios de pagamento · SPB", "%", share_series,
                                    "Participação sobre todos os instrumentos presentes no núcleo trimestral em cada competência; a legenda não recalcula o denominador."))
                macro = subset.copy()
                macro["instrumento"] = macro.instrumento.map(SPB_CONSOLIDADO_MAPA).fillna(macro.instrumento)
                macro = macro.groupby(["periodo_ordem", "instrumento"], as_index=False).valor.sum(min_count=1)
                macro_series = [{"name": str(name), "type": "line", "data": [[date(x), numeric(v)] for x, v in zip(part.periodo_ordem, part.valor)]}
                                for name, part in macro.groupby("instrumento", sort=False)]
                charts.append(chart(f"spb-consolidado-{suffix}", f"Meios de pagamento consolidados · {suffix}", "Meios de pagamento · SPB", unit, macro_series,
                                    "Macro-categorias reproduzem SPB_CONSOLIDADO_MAPA do módulo existente. Cartões reúne crédito, débito e pré-pago; Cobranças reúne boleto, convênios e débito direto."))

    for filename, field, title in (("intercambio", "tarifa_intercambio_ponderada", "Tarifa de intercâmbio por função"), ("desconto", "tx_media_desconto", "Taxa de desconto (MDR) por função")):
        data = pd.read_parquet(source_dir / f"{filename}.parquet")
        grouped(data, "funcao_cartao", field, f"spb-{filename}", title, "%",
                "Média simples das taxas publicadas por combinação, conforme o módulo existente. Cada combinação recebe o mesmo peso; não há nova ponderação pelo volume de transações.", mean=True)

    data = pd.read_parquet(source_dir / "canais_servicos.parquet")
    grouped(data, "operacao", "qtd_transacoes", "spb-servicos", "Serviços por canal de acesso", "milhões de transações",
            "Quantidade publicada dividida por 1 milhão, conforme o módulo existente.", scale=1e-6)
    data = pd.read_parquet(source_dir / "canais_transacoes.parquet")
    for i, product in enumerate(sorted(data.produto.dropna().unique())):
        grouped(data[data.produto == product], "canal_acesso", "qtd_transacoes", f"spb-canais-{i}", f"{product} por canal de acesso", "milhões de transações",
                "Quantidade publicada dividida por 1 milhão. Soma por trimestre e canal dentro do produto indicado, preservando as categorias de acesso ATM.", scale=1e-6)

    data = pd.read_parquet(source_dir / "cartoes.parquet")
    for field, title, unit in (("qtd_cartoes_emitidos", "Cartões emitidos", "unidades"), ("qtd_cartoes_ativos", "Cartões ativos", "unidades"),
                               ("qtd_transacoes_nacionais", "Cartões · transações nacionais", "transações"), ("valor_transacoes_nacionais", "Cartões · valor das transações nacionais", "R$"),
                               ("qtd_transacoes_internacionais", "Cartões · transações internacionais", "transações"), ("valor_transacoes_internacionais", "Cartões · valor das transações internacionais", "R$")):
        grouped(data, "nome_funcao", field, f"spb-cartoes-{field}", title, unit,
                "Soma das linhas publicadas por função do cartão e trimestre, sem conversão de unidade. Contagem de cartões/transações, não de pessoas únicas.")

    data = pd.read_parquet(source_dir / "atm.parquet")
    grouped(data, "cod_localizacao", "qtd_terminal", "spb-atm", "ATM por localização", "terminais",
            "Soma por localização e trimestre dos terminais publicados nas UFs, funções e tipos de compartilhamento.")
    data = pd.read_parquet(source_dir / "terminais.parquet")
    melted = data.melt(id_vars=["trimestre", "uf_terminal"], value_vars=["qtd_term_pos", "qtd_term_pdv"], var_name="tipo", value_name="quantidade")
    melted["tipo"] = melted.tipo.map({"qtd_term_pos": "POS", "qtd_term_pdv": "PDV"})
    grouped(melted, "tipo", "quantidade", "spb-terminais", "Terminais POS e PDV", "terminais",
            "Soma por trimestre nas UFs. POS compartilhados e POS chip são subconjuntos e não são somados ao total.")
    return charts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--scr-cache", type=Path)
    parser.add_argument("--only", choices=("scr", "spb"), help="Preserva a outra fonte já materializada no output")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    args.output = args.output or args.root / "web/public/data/extra.json"
    previous = json.loads(args.output.read_text()) if args.only and args.output.exists() else []
    scr = ([chart for chart in previous if chart["section"].startswith("SCR")]
           if args.only == "spb" else scr_charts(args.scr_cache or args.root / "data/cache/scr_data"))
    spb = ([chart for chart in previous if not chart["section"].startswith("SCR")]
           if args.only == "scr" else spb_charts(args.root / "data/bundled/spb_meios_pagamento"))
    if args.only and not (scr and spb):
        raise ValueError("A geração parcial exige a outra fonte já materializada")
    charts = scr + spb
    if len({item["id"] for item in charts}) != len(charts):
        raise ValueError("Identificadores duplicados")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(charts, ensure_ascii=False, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"charts": len(charts), "scr": sum(c["id"].startswith("scr-") for c in charts), "bytes": args.output.stat().st_size,
                      "lastPeriods": sorted({c["latestPeriod"] for c in charts if c["latestPeriod"]})}))


if __name__ == "__main__":
    main()
