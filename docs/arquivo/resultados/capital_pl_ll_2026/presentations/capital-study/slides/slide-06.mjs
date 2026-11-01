import { C, addBackground, addFooter, addHeader, fmtCompact, fmtPct, hBarChart, loadData, sectionLabel, table } from "./shared.mjs";

export async function slide06(presentation, ctx) {
  const slide = presentation.slides.add();
  const data = loadData();
  addBackground(slide, ctx);
  addHeader(slide, ctx, "Lucro liquido | deterioracoes e proximos cruzamentos", "A cauda negativa ajuda a separar aumento de capital de deterioracao operacional", "LL acumulado de marco");

  sectionLabel(slide, ctx, "Maiores variacoes percentuais negativas", 54, 122, 540);
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
    data.ll_neg_pct.slice(0, 9),
    { rowH: 36, fontSize: 10.2 },
  );

  sectionLabel(slide, ctx, "Proxy negativa de PL no 1T26", 720, 122, 390);
  hBarChart(slide, ctx, 720, 166, 410, data.top_proxy_neg.slice(0, 7), "Proxy_Capital_Outras_1T26", { labelW: 190, valueW: 86, rowH: 42, color: C.gray700, fontSize: 10.2 });

  ctx.addShape(slide, { x: 720, y: 500, w: 410, h: 92, fill: C.black, line: ctx.line() });
  ctx.addText(slide, {
    text: "Proximos cruzamentos",
    x: 742,
    y: 518,
    w: 220,
    h: 22,
    fontSize: 17,
    bold: true,
    color: C.orange,
    typeface: ctx.fonts.title,
  });
  ctx.addText(slide, {
    text: "Eventos societarios, notas explicativas e demonstracoes publicadas para confirmar se a proxy decorre de aporte, reorganizacao ou outro movimento de PL.",
    x: 742,
    y: 548,
    w: 372,
    h: 44,
    fontSize: 11.5,
    color: "#E0E0E0",
  });

  addFooter(slide, ctx, 6);
  return slide;
}
