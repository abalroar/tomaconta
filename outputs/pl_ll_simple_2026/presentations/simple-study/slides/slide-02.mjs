import { C, addBackground, addFactLine, addFooter, addHeader, fmtCompact, fmtPct, hBarChart, loadData, sectionLabel, table } from "./shared.mjs";

export async function slide02(presentation, ctx) {
  const slide = presentation.slides.add();
  const data = loadData();
  const top = data.top_pl_up_pct.slice(0, 12);

  addBackground(slide, ctx);
  addHeader(
    slide,
    ctx,
    "Produto 1 | Patrimônio líquido",
    "Ranking percentual traz IPs para o topo: Bullla, BMP e PicPay lideram",
    "Dez/25 vs Mar/26 | ordenado por variação percentual positiva",
  );

  const leader = top[0];
  const picpay = data.picpay;
  addFactLine(slide, ctx, 44, 118, [
    { label: "Líder percentual", value: fmtPct(leader.Var_PL_pct), note: leader["Instituição"].replace(" - PRUDENCIAL", ""), w: 185 },
    { label: "Delta do líder", value: fmtCompact(leader.Delta_PL), note: "PL Dez/25 >= R$100 mi", w: 170 },
    { label: "PicPay", value: fmtPct(picpay.Var_PL_pct), note: `${fmtCompact(picpay.Delta_PL)} de ΔPL`, w: 160, color: C.orangeDark },
    { label: "CloudWalk", value: fmtPct(top.find((r) => r["Instituição"] === "CLOUDWALK IP - PRUDENCIAL")?.Var_PL_pct), note: "aparece entre as maiores altas", w: 190 },
  ], { gap: 46 });

  sectionLabel(slide, ctx, "Ranking por variação percentual de PL", 44, 222, 505);
  hBarChart(slide, ctx, 44, 260, 520, top, "Var_PL_pct", {
    rowH: 26,
    labelW: 178,
    valueW: 86,
    color: C.orange,
    formatValue: (value) => fmtPct(value),
    highlight: (row) => row["Instituição"] === "PICPAY - PRUDENCIAL",
    nameMax: 25,
  });

  sectionLabel(slide, ctx, "Patamar evita leitura por denominador pequeno", 610, 222, 518);
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
      { label: "Rank PL", w: 58, value: (r) => String(Math.round(r.Rank_PL_Dez25)), align: "right" },
    ],
    top,
    {
      rowH: 25,
      headerH: 28,
      fontSize: 7.5,
      headerFontSize: 7.6,
      highlight: (row) => row["Instituição"] === "PICPAY - PRUDENCIAL",
      highlightColor: C.orangeDark,
    },
  );

  ctx.addText(slide, {
    text: "O corte de PL Dez/25 >= R$100 mi permanece em todos os rankings percentuais.",
    x: 44,
    y: 638,
    w: 900,
    h: 18,
    fontSize: 11.5,
    color: C.gray700,
  });

  addFooter(slide, ctx, 2);
  return slide;
}
