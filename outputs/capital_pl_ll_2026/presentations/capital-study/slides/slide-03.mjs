import { C, addBackground, addFooter, addHeader, fmtCompact, hBarChart, loadData, sectionLabel } from "./shared.mjs";

export async function slide03(presentation, ctx) {
  const slide = presentation.slides.add();
  const data = loadData();
  addBackground(slide, ctx);
  addHeader(slide, ctx, "Ranking de proxy de aporte", "BNDES domina a lista; bancos privados e IPs aparecem no bloco seguinte", "Top 10 por Delta PL - LL 1T26");

  sectionLabel(slide, ctx, "Proxy capital/outras mutacoes no 1T26", 54, 122, 670);
  hBarChart(slide, ctx, 56, 166, 700, data.top_proxy, "Proxy_Capital_Outras_1T26", { labelW: 260, valueW: 92, rowH: 39, color: C.orange });

  const rows = data.top_proxy.slice(0, 5);
  sectionLabel(slide, ctx, "Leitura dos cinco maiores sinais", 818, 122, 350);
  rows.forEach((r, i) => {
    const y = 166 + i * 74;
    ctx.addShape(slide, { x: 818, y, w: 340, h: 58, fill: i === 0 ? C.black : C.gray100, line: { style: "solid", fill: C.gray300, width: 1 } });
    ctx.addText(slide, {
      text: r["Instituição"].replace(" - PRUDENCIAL", ""),
      x: 832,
      y: y + 10,
      w: 206,
      h: 18,
      fontSize: 11.5,
      bold: true,
      color: i === 0 ? C.white : C.black,
    });
    ctx.addText(slide, {
      text: fmtCompact(r.Proxy_Capital_Outras_1T26),
      x: 1038,
      y: y + 7,
      w: 106,
      h: 22,
      fontSize: 15,
      bold: true,
      color: i === 0 ? C.orange : C.black,
      align: "right",
    });
    ctx.addText(slide, {
      text: `Delta PL ${fmtCompact(r.Delta_PL_Dez25_Mar26)} | LL ${fmtCompact(r.LL_202603)}`,
      x: 832,
      y: y + 34,
      w: 310,
      h: 16,
      fontSize: 9.5,
      color: i === 0 ? "#D8D8D8" : C.gray700,
    });
  });

  addFooter(slide, ctx, 3);
  return slide;
}
