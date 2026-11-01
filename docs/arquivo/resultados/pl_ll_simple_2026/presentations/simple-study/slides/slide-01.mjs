import { C, addBackground, addFactLine, addFooter, addHeader, fmtCompact, fmtPct, hBarChart, loadData, sectionLabel, table } from "./shared.mjs";

export async function slide01(presentation, ctx) {
  const slide = presentation.slides.add();
  const data = loadData();
  const top = data.top_pl_up.slice(0, 12);

  addBackground(slide, ctx);
  addHeader(
    slide,
    ctx,
    "Produto 1 | Patrimônio líquido",
    "BNDES lidera por volume; PicPay entra no top 12 de aumento de PL",
    "Dez/25 vs Mar/26 | ordenado por ΔPL bruto",
  );

  addFactLine(slide, ctx, 44, 118, [
    { label: "Universo", value: data.display.qualified, note: "IFs com PL Dez/25 >= R$100 mi", w: 150 },
    { label: "Aumentos de PL", value: data.display.positive_pl_delta, note: "delta positivo total", w: 185 },
    { label: "Top 10", value: data.display.top10_share, note: "share do delta positivo", w: 145 },
    { label: "PicPay", value: data.display.picpay_delta, note: `rank #${data.picpay_rank_delta_pl_positive} | ${data.display.picpay_var}`, w: 165, color: C.orangeDark },
    { label: "Delta líquido", value: data.display.net_pl_delta, note: "altas menos quedas", w: 170 },
  ], { gap: 38 });

  sectionLabel(slide, ctx, "Ranking por volume de aumento", 44, 222, 505);
  hBarChart(slide, ctx, 44, 260, 520, top, "Delta_PL", {
    rowH: 26,
    labelW: 178,
    valueW: 86,
    color: C.orange,
    highlight: (row) => row["Instituição"] === "PICPAY - PRUDENCIAL",
    nameMax: 25,
  });

  sectionLabel(slide, ctx, "Patamar, delta e variação percentual", 610, 222, 518);
  table(
    slide,
    ctx,
    610,
    260,
    [
      { label: "IF", w: 158, value: (r) => r["Instituição"].replace(" - PRUDENCIAL", "") },
      { label: "PL Dez/25", w: 83, value: (r) => fmtCompact(r.PL_202512), align: "right" },
      { label: "PL Mar/26", w: 83, value: (r) => fmtCompact(r.PL_202603), align: "right" },
      { label: "ΔPL", w: 78, value: (r) => fmtCompact(r.Delta_PL), align: "right" },
      { label: "Var.", w: 56, value: (r) => fmtPct(r.Var_PL_pct), align: "right" },
      { label: "Acum.", w: 58, value: (r) => fmtPct(r.Contrib_Acum_Delta_PL_Pos_pct), align: "right" },
    ],
    top,
    {
      rowH: 25,
      headerH: 28,
      fontSize: 7.6,
      headerFontSize: 7.7,
      highlight: (row) => row["Instituição"] === "PICPAY - PRUDENCIAL",
      highlightColor: C.orangeDark,
    },
  );

  ctx.addText(slide, {
    text: "PicPay: PL de R$ 3,5bi para R$ 5,7bi; ΔPL de R$ 2,3bi e variação de 65,3%.",
    x: 44,
    y: 638,
    w: 1048,
    h: 18,
    fontSize: 12,
    color: C.black,
    bold: true,
  });

  addFooter(slide, ctx, 1);
  return slide;
}
