import fs from "node:fs";

const SUMMARY_URL = new URL("../../../data/summary.json", import.meta.url);

export const C = {
  orange: "#EC7000",
  orangeDark: "#B65300",
  black: "#171717",
  nearBlack: "#242424",
  gray900: "#303030",
  gray700: "#555555",
  gray500: "#858585",
  gray300: "#DADADA",
  gray200: "#ECECEC",
  gray100: "#F6F6F6",
  white: "#FFFFFF",
  blue: "#0F6B8A",
  red: "#B42318",
  green: "#117A44",
};

export function loadData() {
  return JSON.parse(fs.readFileSync(SUMMARY_URL, "utf8"));
}

export function fmtCompact(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const n = Number(value);
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  const fmt = (v) => v.toLocaleString("pt-BR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  if (abs >= 1_000_000_000) return `${sign}R$ ${fmt(abs / 1_000_000_000)}bi`;
  if (abs >= 1_000_000) return `${sign}R$ ${fmt(abs / 1_000_000)}mi`;
  if (abs >= 1_000) return `${sign}R$ ${fmt(abs / 1_000)}mil`;
  return `${sign}R$ ${fmt(abs)}`;
}

export function fmtPct(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return `${(Number(value) * 100).toLocaleString("pt-BR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}%`;
}

export function shortName(name, max = 25) {
  const clean = String(name)
    .replace(" - PRUDENCIAL", "")
    .replace("BANCO ", "BCO ")
    .replace("BANCO", "BCO")
    .replace("ECONÔMICA FEDERAL", "CEF");
  return clean.length > max ? `${clean.slice(0, max - 1)}...` : clean;
}

export function addBackground(slide, ctx, fill = C.white) {
  ctx.addShape(slide, { x: 0, y: 0, w: ctx.W, h: ctx.H, fill, line: ctx.line() });
}

export function addHeader(slide, ctx, kicker, title, subtitle = "") {
  ctx.addShape(slide, { x: 0, y: 0, w: ctx.W, h: 84, fill: C.black, line: ctx.line() });
  ctx.addShape(slide, { x: 0, y: 84, w: ctx.W, h: 8, fill: C.orange, line: ctx.line() });
  ctx.addText(slide, {
    text: kicker,
    x: 44,
    y: 16,
    w: 360,
    h: 18,
    fontSize: 13,
    color: C.orange,
    bold: true,
    typeface: ctx.fonts.body,
  });
  ctx.addText(slide, {
    text: title,
    x: 44,
    y: 42,
    w: 950,
    h: 32,
    fontSize: 25,
    color: C.white,
    bold: true,
    typeface: ctx.fonts.title,
  });
  if (subtitle) {
    ctx.addText(slide, {
      text: subtitle,
      x: 930,
      y: 20,
      w: 235,
      h: 16,
      fontSize: 9.5,
      color: "#D6D6D6",
      align: "right",
      typeface: ctx.fonts.body,
    });
  }
}

export function addFooter(slide, ctx, page) {
  ctx.addShape(slide, { x: 44, y: 675, w: 1088, h: 1, fill: C.gray300, line: ctx.line() });
  ctx.addText(slide, {
    text: "Fonte: BCB BLOPRUDENCIAL 4060 local | universo: PL dez/25 >= R$100 mi | valores em R$",
    x: 44,
    y: 684,
    w: 910,
    h: 16,
    fontSize: 9,
    color: C.gray700,
  });
  ctx.addText(slide, {
    text: String(page).padStart(2, "0"),
    x: 1136,
    y: 681,
    w: 40,
    h: 18,
    fontSize: 10,
    color: C.gray700,
    align: "right",
  });
}

export function addKpi(slide, ctx, x, y, w, label, value, note, accent = C.orange) {
  ctx.addShape(slide, { x, y, w, h: 104, fill: C.white, line: { style: "solid", fill: C.gray300, width: 1 } });
  ctx.addShape(slide, { x, y, w: 6, h: 104, fill: accent, line: ctx.line() });
  ctx.addText(slide, {
    text: label,
    x: x + 18,
    y: y + 14,
    w: w - 28,
    h: 20,
    fontSize: 12,
    bold: true,
    color: C.gray700,
  });
  ctx.addText(slide, {
    text: value,
    x: x + 18,
    y: y + 38,
    w: w - 28,
    h: 35,
    fontSize: 27,
    bold: true,
    color: C.black,
    typeface: ctx.fonts.title,
  });
  ctx.addText(slide, {
    text: note,
    x: x + 18,
    y: y + 76,
    w: w - 28,
    h: 18,
    fontSize: 9.5,
    color: C.gray700,
  });
}

export function sectionLabel(slide, ctx, text, x, y, w = 420) {
  ctx.addShape(slide, { x, y: y + 21, w, h: 1, fill: C.gray300, line: ctx.line() });
  ctx.addText(slide, {
    text,
    x,
    y,
    w,
    h: 20,
    fontSize: 13,
    bold: true,
    color: C.black,
  });
}

export function table(slide, ctx, x, y, columns, rows, opts = {}) {
  const rowH = opts.rowH ?? 28;
  const headerH = opts.headerH ?? 30;
  const fontSize = opts.fontSize ?? 10.5;
  const totalW = columns.reduce((sum, col) => sum + col.w, 0);
  ctx.addShape(slide, { x, y, w: totalW, h: headerH, fill: C.black, line: ctx.line() });
  let cx = x;
  for (const col of columns) {
    ctx.addText(slide, {
      text: col.label,
      x: cx + 6,
      y: y + 8,
      w: col.w - 12,
      h: 16,
      fontSize: 9.5,
      bold: true,
      color: C.white,
      align: col.align ?? "left",
    });
    cx += col.w;
  }
  rows.forEach((row, i) => {
    const yy = y + headerH + i * rowH;
    ctx.addShape(slide, {
      x,
      y: yy,
      w: totalW,
      h: rowH,
      fill: i % 2 === 0 ? C.white : C.gray100,
      line: { style: "solid", fill: C.gray200, width: 1 },
    });
    let cxx = x;
    columns.forEach((col, j) => {
      const value = typeof col.value === "function" ? col.value(row, i) : row[col.key];
      ctx.addText(slide, {
        text: value ?? "",
        x: cxx + 6,
        y: yy + 7,
        w: col.w - 12,
        h: rowH - 8,
        fontSize,
        color: j === 0 ? C.black : C.gray900,
        bold: j === 0 && opts.boldFirst !== false,
        align: col.align ?? "left",
      });
      cxx += col.w;
    });
  });
}

export function hBarChart(slide, ctx, x, y, w, rows, key, opts = {}) {
  const max = Math.max(...rows.map((r) => Math.abs(Number(r[key]) || 0)), 1);
  const rowH = opts.rowH ?? 32;
  const labelW = opts.labelW ?? 205;
  const valueW = opts.valueW ?? 84;
  const barW = w - labelW - valueW - 18;
  rows.forEach((row, i) => {
    const yy = y + i * rowH;
    const value = Number(row[key]) || 0;
    const bw = Math.max(2, (Math.abs(value) / max) * barW);
    ctx.addText(slide, {
      text: `${i + 1}. ${shortName(row["Instituição"], 26)}`,
      x,
      y: yy + 3,
      w: labelW,
      h: 18,
      fontSize: opts.fontSize ?? 10.5,
      color: C.black,
      bold: i < 3,
    });
    ctx.addShape(slide, { x: x + labelW, y: yy + 7, w: barW, h: 12, fill: C.gray200, line: ctx.line() });
    ctx.addShape(slide, {
      x: x + labelW,
      y: yy + 7,
      w: bw,
      h: 12,
      fill: opts.color ?? C.orange,
      line: ctx.line(),
    });
    ctx.addText(slide, {
      text: fmtCompact(value),
      x: x + labelW + barW + 10,
      y: yy + 2,
      w: valueW,
      h: 20,
      fontSize: 10,
      color: C.gray900,
      bold: i < 3,
      align: "right",
    });
  });
}

export function vGroupedBars(slide, ctx, x, y, w, h, rows) {
  const values = rows.flatMap((r) => [Number(r.Delta_PL), Number(r.Proxy_Capital_Outras)]);
  const max = Math.max(...values, 0);
  const min = Math.min(...values, 0);
  const yScale = (v) => y + h - ((v - min) / (max - min || 1)) * h;
  const zeroY = yScale(0);
  ctx.addShape(slide, { x, y: zeroY, w, h: 1.5, fill: C.black, line: ctx.line() });
  for (let i = 1; i <= 4; i += 1) {
    const yy = y + (h / 4) * i;
    ctx.addShape(slide, { x, y: yy, w, h: 1, fill: "#E8E8E8", line: ctx.line() });
  }
  const groupW = w / rows.length;
  rows.forEach((row, i) => {
    const baseX = x + i * groupW + groupW * 0.23;
    const vals = [
      { label: "Delta PL", v: Number(row.Delta_PL), color: C.black },
      { label: "Delta PL - LL", v: Number(row.Proxy_Capital_Outras), color: C.orange },
    ];
    vals.forEach((item, j) => {
      const barX = baseX + j * 30;
      const top = Math.min(yScale(item.v), zeroY);
      const bh = Math.max(3, Math.abs(yScale(item.v) - zeroY));
      ctx.addShape(slide, { x: barX, y: top, w: 23, h: bh, fill: item.color, line: ctx.line() });
      ctx.addText(slide, {
        text: fmtCompact(item.v),
        x: barX - 24,
        y: item.v >= 0 ? top - 18 : top + bh + 3,
        w: 70,
        h: 15,
        fontSize: 8.5,
        color: C.gray900,
        align: "center",
      });
    });
    ctx.addText(slide, {
      text: row["Mês"].replace("->", "\n"),
      x: x + i * groupW + 10,
      y: y + h + 12,
      w: groupW - 20,
      h: 36,
      fontSize: 9.5,
      color: C.gray700,
      align: "center",
    });
  });
  ctx.addShape(slide, { x: x + w - 172, y: y - 28, w: 10, h: 10, fill: C.black, line: ctx.line() });
  ctx.addText(slide, { text: "Delta PL", x: x + w - 158, y: y - 31, w: 70, h: 16, fontSize: 9.5, color: C.gray700 });
  ctx.addShape(slide, { x: x + w - 82, y: y - 28, w: 10, h: 10, fill: C.orange, line: ctx.line() });
  ctx.addText(slide, { text: "Delta PL - LL", x: x + w - 68, y: y - 31, w: 90, h: 16, fontSize: 9.5, color: C.gray700 });
}
