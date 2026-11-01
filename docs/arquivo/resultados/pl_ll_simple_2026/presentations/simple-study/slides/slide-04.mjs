import { C, addBackground, addFactLine, addFooter, addHeader, fmtCompact, fmtPct, hBarChart, loadData, sectionLabel, table } from "./shared.mjs";

export async function slide04(presentation, ctx) {
  const slide = presentation.slides.add();
  const data = loadData();
  const up = data.top_ll_up_pct.slice(0, 8);
  const down = data.top_ll_down_pct.slice(0, 8);

  addBackground(slide, ctx);
  addHeader(
    slide,
    ctx,
    "Produto 2 | Lucro líquido",
    "Percentual de LL evidencia IPs e viradas de sinal; patamar fica ao lado",
    "Mar/25 vs Mar/26 | variação calculada contra |LL Mar/25|",
  );

  addFactLine(slide, ctx, 44, 118, [
    { label: "Maior alta %", value: fmtPct(up[0].Var_LL_pct), note: up[0]["Instituição"].replace(" - PRUDENCIAL", ""), w: 190, color: C.green },
    { label: "ΔLL do líder", value: fmtCompact(up[0].Delta_LL), note: `${fmtCompact(up[0].LL_202503)} para ${fmtCompact(up[0].LL_202603)}`, w: 215 },
    { label: "Maior queda %", value: fmtPct(down[0].Var_LL_pct), note: down[0]["Instituição"].replace(" - PRUDENCIAL", ""), w: 190, color: C.red },
    { label: "ΔLL da queda", value: fmtCompact(down[0].Delta_LL), note: `${fmtCompact(down[0].LL_202503)} para ${fmtCompact(down[0].LL_202603)}`, w: 215 },
  ], { gap: 44 });

  sectionLabel(slide, ctx, "Maiores altas percentuais de LL", 44, 220, 510);
  hBarChart(slide, ctx, 44, 258, 515, up, "Var_LL_pct", {
    rowH: 24,
    labelW: 180,
    valueW: 88,
    color: C.green,
    nameMax: 25,
    formatValue: (value) => fmtPct(value),
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
      { label: "Var.", w: 54, value: (r) => fmtPct(r.Var_LL_pct), align: "right" },
      { label: "LL26/PL", w: 54, value: (r) => fmtPct(r.LL_202603_pct_PL_Dez25), align: "right" },
    ],
    up,
    { rowH: 21, headerH: 25, fontSize: 7.0, headerFontSize: 7.2 },
  );

  sectionLabel(slide, ctx, "Maiores quedas percentuais de LL", 622, 220, 510);
  hBarChart(slide, ctx, 622, 258, 515, down, "Var_LL_pct", {
    rowH: 24,
    labelW: 180,
    valueW: 88,
    color: C.red,
    nameMax: 25,
    formatValue: (value) => fmtPct(value),
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
      { label: "Var.", w: 54, value: (r) => fmtPct(r.Var_LL_pct), align: "right" },
      { label: "LL26/PL", w: 54, value: (r) => fmtPct(r.LL_202603_pct_PL_Dez25), align: "right" },
    ],
    down,
    { rowH: 21, headerH: 25, fontSize: 7.0, headerFontSize: 7.2 },
  );

  ctx.addText(slide, {
    text: "Percentuais extremos foram mantidos porque pertencem ao universo filtrado; a tabela mostra o patamar para leitura econômica.",
    x: 44,
    y: 660,
    w: 920,
    h: 16,
    fontSize: 10,
    color: C.gray700,
  });

  addFooter(slide, ctx, 4);
  return slide;
}
