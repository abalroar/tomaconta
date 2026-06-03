import { C, addBackground, addFactLine, addFooter, addHeader, fmtCompact, fmtPct, hBarChart, loadData, sectionLabel, table } from "./shared.mjs";

export async function slide05(presentation, ctx) {
  const slide = presentation.slides.add();
  const data = loadData();
  const top = data.top_pl_residual_positive.slice(0, 12);

  addBackground(slide, ctx);
  addHeader(
    slide,
    ctx,
    "Ponte PL vs. lucro líquido",
    "R$ 66,0bi do aumento de PL não é explicado pelo lucro líquido",
    "Dez/25 vs Mar/26 | residual = ΔPL - LL acumulado em Mar/26",
  );

  addFactLine(slide, ctx, 44, 118, [
    { label: "ΔPL total", value: fmtCompact(data.totals.Delta_PL_total), note: "Dez/25 para Mar/26", w: 160 },
    { label: "LL Mar/26", value: fmtCompact(data.totals.LL_202603), note: "lucro acumulado no período", w: 160 },
    { label: "Residual", value: data.display.bridge_residual_total, note: "ΔPL menos LL", w: 160, color: C.orangeDark },
    { label: "% explicado por LL", value: data.display.bridge_ll_share_delta_pl, note: "LL / ΔPL total", w: 165 },
  ], { gap: 54 });

  sectionLabel(slide, ctx, "Maiores residuais positivos", 44, 222, 505);
  hBarChart(slide, ctx, 44, 260, 520, top, "Residual_Delta_PL_menos_LL", {
    rowH: 26,
    labelW: 178,
    valueW: 86,
    color: C.orange,
    highlight: (row) => ["BNDES - PRUDENCIAL", "CLOUDWALK IP - PRUDENCIAL", "PICPAY - PRUDENCIAL"].includes(row["Instituição"]),
    nameMax: 25,
  });

  sectionLabel(slide, ctx, "Ponte por instituição", 610, 222, 518);
  table(
    slide,
    ctx,
    610,
    260,
    [
      { label: "IF", w: 162, value: (r) => r["Instituição"].replace(" - PRUDENCIAL", "") },
      { label: "ΔPL", w: 86, value: (r) => fmtCompact(r.Delta_PL), align: "right" },
      { label: "LL", w: 82, value: (r) => fmtCompact(r.LL_202603), align: "right" },
      { label: "ΔPL-LL", w: 94, value: (r) => fmtCompact(r.Residual_Delta_PL_menos_LL), align: "right" },
      { label: "% LL", w: 55, value: (r) => fmtPct(r.Pct_Delta_PL_explicado_por_LL), align: "right" },
    ],
    top,
    {
      rowH: 25,
      headerH: 28,
      fontSize: 7.5,
      headerFontSize: 7.6,
      highlight: (row) => ["BNDES - PRUDENCIAL", "CLOUDWALK IP - PRUDENCIAL", "PICPAY - PRUDENCIAL"].includes(row["Instituição"]),
      highlightColor: C.orangeDark,
    },
  );

  ctx.addText(slide, {
    text: "Residual positivo não prova aporte isoladamente; prova que o lucro líquido não explica integralmente o aumento de PL.",
    x: 44,
    y: 638,
    w: 1000,
    h: 18,
    fontSize: 11.5,
    color: C.gray700,
  });

  addFooter(slide, ctx, 5);
  return slide;
}
