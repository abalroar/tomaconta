import { C, addBackground, addFooter, addHeader, addKpi, fmtCompact, fmtPct, hBarChart, loadData, sectionLabel, table } from "./shared.mjs";

function llTableRows(rows) {
  return rows.slice(0, 8);
}

export async function slide02(presentation, ctx) {
  const slide = presentation.slides.add();
  const data = loadData();
  const up = llTableRows(data.top_ll_up);
  const down = llTableRows(data.top_ll_down);

  addBackground(slide, ctx);
  addHeader(
    slide,
    ctx,
    "Produto 2 | Lucro líquido",
    "Lucro líquido mostra melhora concentrada e deterioração relevante nos grandes players",
    "Mar/25 vs Mar/26 | por ΔLL bruto",
  );

  addKpi(slide, ctx, 44, 116, 250, "LL Mar/25", fmtCompact(data.totals.LL_202503), "soma do universo filtrado");
  addKpi(slide, ctx, 316, 116, 250, "LL Mar/26", fmtCompact(data.totals.LL_202603), "soma do universo filtrado");
  addKpi(slide, ctx, 588, 116, 250, "ΔLL total", data.display.ll_delta_total, "Mar/25 para Mar/26");
  addKpi(slide, ctx, 860, 116, 250, "Cobertura", String(data.coverage.instituicoes_com_ll_mar25_e_mar26), "IFs com LL nos dois períodos");

  sectionLabel(slide, ctx, "Maiores melhoras de lucro líquido", 44, 220, 510);
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

  sectionLabel(slide, ctx, "Maiores deteriorações de lucro líquido", 622, 220, 510);
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
    {
      rowH: 21,
      headerH: 25,
      fontSize: 7.0,
      headerFontSize: 7.2,
      highlight: (row) => row["Instituição"] === "CLOUDWALK IP - PRUDENCIAL",
    },
  );

  ctx.addText(slide, {
    text: "LL26/PL usa PL de Dez/25 como base para dimensionar geração ou consumo de capital.",
    x: 44,
    y: 660,
    w: 760,
    h: 16,
    fontSize: 10,
    color: C.gray700,
  });

  addFooter(slide, ctx, 2);
  return slide;
}
