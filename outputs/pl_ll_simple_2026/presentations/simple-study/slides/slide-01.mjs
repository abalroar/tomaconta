import { C, addBackground, addFooter, addHeader, addKpi, fmtCompact, fmtPct, hBarChart, loadData, sectionLabel, table } from "./shared.mjs";

export async function slide01(presentation, ctx) {
  const slide = presentation.slides.add();
  const data = loadData();
  const top = data.top_pl_up.slice(0, 12);

  addBackground(slide, ctx);
  addHeader(
    slide,
    ctx,
    "Produto 1 | Patrimônio líquido",
    "Maiores aumentos de PL explicam a maior parte do delta positivo do sistema",
    "Dez/25 vs Mar/26 | ordenado por ΔPL bruto",
  );

  addKpi(slide, ctx, 44, 116, 205, "Universo", data.display.qualified, "IFs com PL Dez/25 >= R$100 mi");
  addKpi(slide, ctx, 266, 116, 205, "Aumentos de PL", data.display.positive_pl_delta, "delta positivo total");
  addKpi(slide, ctx, 488, 116, 205, "Concentração top 10", data.display.top10_share, "share do delta positivo");
  addKpi(slide, ctx, 710, 116, 205, "PicPay", data.display.picpay_delta, `rank #${data.picpay_rank_delta_pl_positive} | ${data.display.picpay_var}`, C.orangeDark);
  addKpi(slide, ctx, 932, 116, 205, "Delta líquido", data.display.net_pl_delta, "altas menos quedas");

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
    },
  );

  ctx.addShape(slide, { x: 44, y: 628, w: 1088, h: 36, fill: C.paleOrange, line: { style: "solid", fill: "#F2C49C", width: 1 } });
  ctx.addText(slide, {
    text: "Leitura: PicPay entra como #12 no ranking puro de aumento de PL. Ele ficava menos visível no estudo anterior porque aquele produto ordenava por proxy, não por ΔPL bruto.",
    x: 62,
    y: 638,
    w: 1048,
    h: 18,
    fontSize: 12,
    color: C.black,
  });

  addFooter(slide, ctx, 1);
  return slide;
}
