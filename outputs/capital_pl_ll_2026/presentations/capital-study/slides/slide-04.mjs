import { C, addBackground, addFooter, addHeader, fmtCompact, loadData, sectionLabel, table } from "./shared.mjs";

export async function slide04(presentation, ctx) {
  const slide = presentation.slides.add();
  const data = loadData();
  addBackground(slide, ctx);
  addHeader(slide, ctx, "Precisao temporal dos maiores sinais", "A triagem aponta em qual mes a variacao patrimonial apareceu", "Top 8 por proxy acumulada no 1T26");

  sectionLabel(slide, ctx, "Proxy mensal: Delta PL menos LL mensal", 48, 122, 1080);
  table(
    slide,
    ctx,
    48,
    166,
    [
      { label: "Instituicao", w: 245, value: (r) => r["Instituição"].replace(" - PRUDENCIAL", "") },
      { label: "PL dez/25", w: 110, value: (r) => fmtCompact(r.PL_202512), align: "right" },
      { label: "Dez->Jan", w: 112, value: (r) => fmtCompact(r.Proxy_Capital_Outras_Jan26), align: "right" },
      { label: "Jan->Fev", w: 112, value: (r) => fmtCompact(r.Proxy_Capital_Outras_Fev26), align: "right" },
      { label: "Fev->Mar", w: 112, value: (r) => fmtCompact(r.Proxy_Capital_Outras_Mar26), align: "right" },
      { label: "Proxy 1T26", w: 116, value: (r) => fmtCompact(r.Proxy_Capital_Outras_1T26), align: "right" },
      { label: "Mes-chave", w: 130, value: (r) => r.Maior_Mes_Aumento_PL },
      { label: "LL 1T26", w: 108, value: (r) => fmtCompact(r.LL_202603), align: "right" },
    ],
    data.top_proxy.slice(0, 8),
    { rowH: 42, fontSize: 10.2 },
  );

  ctx.addShape(slide, { x: 48, y: 566, w: 1045, h: 50, fill: C.gray100, line: { style: "solid", fill: C.gray300, width: 1 } });
  ctx.addText(slide, {
    text: "Como ler: valores positivos indicam aumento de PL nao explicado pelo lucro do mes. Valores negativos indicam reducao/reversao patrimonial ou lucro superior ao crescimento de PL.",
    x: 68,
    y: 582,
    w: 1004,
    h: 20,
    fontSize: 12.2,
    color: C.gray900,
  });

  addFooter(slide, ctx, 4);
  return slide;
}
