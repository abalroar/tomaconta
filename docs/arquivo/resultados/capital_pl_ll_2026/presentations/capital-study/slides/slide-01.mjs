import { C, addBackground, addFooter, addHeader, addKpi, fmtCompact, loadData, sectionLabel, table } from "./shared.mjs";

export async function slide01(presentation, ctx) {
  const slide = presentation.slides.add();
  const data = loadData();
  addBackground(slide, ctx);
  addHeader(
    slide,
    ctx,
    "Estudo pontual | PL e lucro liquido",
    "Aumento de PL no 1T26 concentrou-se em janeiro",
    "Dez/25 a Mar/26 | BLOPRUDENCIAL 4060",
  );

  addKpi(slide, ctx, 44, 132, 260, "Universo filtrado", String(data.coverage.instituicoes_qualificadas_pl_100mm), "IFs com PL dez/25 >= R$100 mi");
  addKpi(slide, ctx, 322, 132, 260, "Delta PL 1T26", fmtCompact(data.totals.Delta_PL_Dez25_Mar26), "Dez/25 para Mar/26");
  addKpi(slide, ctx, 600, 132, 260, "Lucro liquido 1T26", fmtCompact(data.totals.LL_202603), "Resultado credor - devedor");
  addKpi(slide, ctx, 878, 132, 260, "Proxy capital/outras", fmtCompact(data.totals.Proxy_Capital_Outras_1T26), "Delta PL menos LL 1T26", C.black);

  sectionLabel(slide, ctx, "Leitura executiva", 44, 278, 520);
  const top = data.top_proxy[0];
  const jan = data.month_delta_summary[0];
  const bullets = [
    `Janeiro e a janela-chave: ${fmtCompact(jan.Proxy_Capital_Outras)} de proxy liquido no movimento Dez/25->Jan/26.`,
    `${top["Instituição"]} lidera a triagem: ${fmtCompact(top.Proxy_Capital_Outras_1T26)} de proxy no 1T26.`,
    `A proxy separa variacao patrimonial do resultado, mas exige checagem societaria para confirmar aporte.`,
  ].join("\n");
  ctx.addText(slide, {
    text: bullets,
    x: 44,
    y: 318,
    w: 520,
    h: 115,
    fontSize: 18,
    color: C.black,
    typeface: ctx.fonts.title,
    insets: { left: 0, right: 20, top: 0, bottom: 0 },
  });

  sectionLabel(slide, ctx, "Top 5 proxy de aporte/outras mutacoes", 628, 278, 488);
  table(
    slide,
    ctx,
    628,
    318,
    [
      { label: "Instituicao", w: 230, value: (r) => r["Instituição"].replace(" - PRUDENCIAL", "") },
      { label: "Proxy", w: 88, value: (r) => fmtCompact(r.Proxy_Capital_Outras_1T26), align: "right" },
      { label: "Delta PL", w: 88, value: (r) => fmtCompact(r.Delta_PL_Dez25_Mar26), align: "right" },
      { label: "Mes-chave", w: 92, value: (r) => r.Maior_Mes_Aumento_PL },
    ],
    data.top_proxy.slice(0, 5),
    { rowH: 31, fontSize: 9.6 },
  );

  ctx.addShape(slide, { x: 44, y: 524, w: 1092, h: 82, fill: "#FFF3E8", line: { style: "solid", fill: "#F2C49C", width: 1 } });
  ctx.addText(slide, {
    text: "Definicao operacional: proxy capital/outras mutacoes = Delta PL - lucro liquido do periodo. Para confirmar aumento de capital, cruzar os nomes priorizados com eventos societarios, demonstracoes publicadas e notas explicativas.",
    x: 66,
    y: 544,
    w: 1046,
    h: 38,
    fontSize: 14,
    color: C.black,
  });

  addFooter(slide, ctx, 1);
  return slide;
}
