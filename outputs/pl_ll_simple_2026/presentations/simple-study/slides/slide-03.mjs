import { C, addBackground, addFactLine, addFooter, addHeader, fmtCompact, fmtPct, hBarChart, loadData, sectionLabel, table } from "./shared.mjs";

export async function slide03(presentation, ctx) {
  const slide = presentation.slides.add();
  const data = loadData();
  const up = data.top_ll_up.slice(0, 8);
  const down = data.top_ll_down.slice(0, 8);

  addBackground(slide, ctx);
  addHeader(
    slide,
    ctx,
    "Produto 2 | Lucro líquido",
    "ΔLL agregado cai R$ 6,6bi; Stone, BTG e Itaú são os maiores offsets",
    "Mar/25 vs Mar/26 | ordenado por ΔLL bruto",
  );

  addFactLine(slide, ctx, 44, 118, [
    { label: "LL Mar/25", value: fmtCompact(data.totals.LL_202503), note: "soma do universo filtrado", w: 160 },
    { label: "LL Mar/26", value: fmtCompact(data.totals.LL_202603), note: "soma do universo filtrado", w: 160 },
    { label: "ΔLL total", value: data.display.ll_delta_total, note: "Mar/25 para Mar/26", w: 160, color: C.red },
    { label: "Cobertura", value: String(data.coverage.instituicoes_com_ll_mar25_e_mar26), note: "IFs com LL nos dois períodos", w: 170 },
  ], { gap: 56 });

  sectionLabel(slide, ctx, "Maiores melhoras por volume", 44, 220, 510);
  hBarChart(slide, ctx, 44, 258, 515, up, "Delta_LL", {
    rowH: 24,
    labelW: 180,
    valueW: 88,
    color: C.green,
    nameMax: 25,
  });
  table(
    slide,
    ctx,
    44,
    465,
    [
      { label: "IF", w: 150, value: (r) => r["Instituição"].replace(" - PRUDENCIAL", "") },
      { label: "LL 25", w: 70, value: (r) => fmtCompact(r.LL_202503), align: "right" },
      { label: "LL 26", w: 70, value: (r) => fmtCompact(r.LL_202603), align: "right" },
      { label: "ΔLL", w: 72, value: (r) => fmtCompact(r.Delta_LL), align: "right" },
      { label: "Var.", w: 50, value: (r) => fmtPct(r.Var_LL_pct), align: "right" },
      { label: "LL26/PL", w: 58, value: (r) => fmtPct(r.LL_202603_pct_PL_Dez25), align: "right" },
    ],
    up,
    { rowH: 21, headerH: 25, fontSize: 7.0, headerFontSize: 7.2 },
  );

  sectionLabel(slide, ctx, "Maiores deteriorações por volume", 622, 220, 510);
  hBarChart(slide, ctx, 622, 258, 515, down, "Delta_LL", {
    rowH: 24,
    labelW: 180,
    valueW: 88,
    color: C.red,
    nameMax: 25,
  });
  table(
    slide,
    ctx,
    622,
    465,
    [
      { label: "IF", w: 150, value: (r) => r["Instituição"].replace(" - PRUDENCIAL", "") },
      { label: "LL 25", w: 70, value: (r) => fmtCompact(r.LL_202503), align: "right" },
      { label: "LL 26", w: 70, value: (r) => fmtCompact(r.LL_202603), align: "right" },
      { label: "ΔLL", w: 72, value: (r) => fmtCompact(r.Delta_LL), align: "right" },
      { label: "Var.", w: 50, value: (r) => fmtPct(r.Var_LL_pct), align: "right" },
      { label: "LL26/PL", w: 58, value: (r) => fmtPct(r.LL_202603_pct_PL_Dez25), align: "right" },
    ],
    down,
    { rowH: 21, headerH: 25, fontSize: 7.0, headerFontSize: 7.2 },
  );

  addFooter(slide, ctx, 3);
  return slide;
}
