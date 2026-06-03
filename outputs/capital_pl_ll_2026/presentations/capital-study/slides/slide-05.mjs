import { C, addBackground, addFooter, addHeader, fmtCompact, fmtPct, hBarChart, loadData, sectionLabel, table } from "./shared.mjs";

export async function slide05(presentation, ctx) {
  const slide = presentation.slides.add();
  const data = loadData();
  addBackground(slide, ctx);
  addHeader(slide, ctx, "Lucro liquido | maiores altas percentuais", "IPs e bancos digitais lideram a comparacao Mar/25 vs Mar/26", "LL acumulado de marco");

  sectionLabel(slide, ctx, "Maiores variacoes percentuais positivas", 54, 122, 520);
  table(
    slide,
    ctx,
    54,
    166,
    [
      { label: "Instituicao", w: 250, value: (r) => r["Instituição"].replace(" - PRUDENCIAL", "") },
      { label: "LL mar/25", w: 105, value: (r) => fmtCompact(r.LL_202503), align: "right" },
      { label: "LL mar/26", w: 105, value: (r) => fmtCompact(r.LL_202603), align: "right" },
      { label: "Var. %", w: 88, value: (r) => fmtPct(r.Delta_LL_pct_Mar25_Mar26), align: "right" },
    ],
    data.ll_pos_pct.slice(0, 9),
    { rowH: 36, fontSize: 10.2 },
  );

  sectionLabel(slide, ctx, "Lucro mar/26 dos destaques", 720, 122, 390);
  hBarChart(slide, ctx, 720, 166, 410, data.ll_pos_pct.slice(0, 7), "LL_202603", { labelW: 190, valueW: 86, rowH: 42, color: C.black, fontSize: 10.2 });

  ctx.addShape(slide, { x: 720, y: 502, w: 410, h: 66, fill: "#FFF3E8", line: { style: "solid", fill: "#F2C49C", width: 1 } });
  ctx.addText(slide, {
    text: "Nota: variacoes percentuais podem ficar muito altas quando a base de Mar/25 e pequena ou negativa. Por isso a aba de Excel tambem traz variacao absoluta e PL de base.",
    x: 740,
    y: 520,
    w: 372,
    h: 46,
    fontSize: 11.5,
    color: C.black,
  });

  addFooter(slide, ctx, 5);
  return slide;
}
