import { C, addBackground, addFooter, addHeader, fmtCompact, loadData, sectionLabel, table, vGroupedBars } from "./shared.mjs";

export async function slide02(presentation, ctx) {
  const slide = presentation.slides.add();
  const data = loadData();
  addBackground(slide, ctx);
  addHeader(slide, ctx, "Ponte mensal de patrimonio liquido", "O salto aconteceu no primeiro mes do trimestre", "Delta PL e Delta PL - LL mensal");

  sectionLabel(slide, ctx, "Delta PL vs. movimento patrimonial liquido de lucro", 58, 124, 690);
  vGroupedBars(slide, ctx, 70, 180, 665, 285, data.month_delta_summary);

  sectionLabel(slide, ctx, "Resumo mensal", 812, 124, 310);
  table(
    slide,
    ctx,
    812,
    176,
    [
      { label: "Mes", w: 118, key: "Mês" },
      { label: "Delta PL", w: 102, value: (r) => fmtCompact(r.Delta_PL), align: "right" },
      { label: "Delta PL - LL", w: 116, value: (r) => fmtCompact(r.Proxy_Capital_Outras), align: "right" },
    ],
    data.month_delta_summary,
    { rowH: 42, fontSize: 11 },
  );

  ctx.addShape(slide, { x: 812, y: 362, w: 336, h: 132, fill: C.black, line: ctx.line() });
  ctx.addText(slide, {
    text: "Janeiro concentra a maior parte do sinal",
    x: 834,
    y: 386,
    w: 292,
    h: 32,
    fontSize: 20,
    bold: true,
    color: C.white,
    typeface: ctx.fonts.title,
  });
  ctx.addText(slide, {
    text: "A proxy positiva em janeiro supera a proxy acumulada no trimestre porque fevereiro e marco trazem reversoes liquidas relevantes.",
    x: 834,
    y: 434,
    w: 292,
    h: 48,
    fontSize: 12.5,
    color: "#D8D8D8",
  });

  addFooter(slide, ctx, 2);
  return slide;
}
