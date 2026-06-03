import fs from "node:fs";

const SUMMARY_URL = new URL("../../../data/summary.json", import.meta.url);

export const C = {
  orange: "#EC7000",
  orangeDark: "#B65300",
  black: "#171717",
  nearBlack: "#252525",
  gray900: "#303030",
  gray700: "#595959",
  gray500: "#888888",
  gray300: "#D7D7D7",
  gray200: "#ECECEC",
  gray100: "#F7F7F7",
  white: "#FFFFFF",
  blue: "#0F6B8A",
  red: "#B42318",
  green: "#117A44",
  paleOrange: "#FFF1E5",
};

export function loadData() {
  return JSON.parse(fs.readFileSync(SUMMARY_URL, "utf8"));
}

export function fmtCompact(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const n = Number(value);
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  const fmt = (v) => v.toLocaleString("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  if (abs >= 1_000_000_000) return `${sign}R$ ${fmt(abs / 1_000_000_000)}bi`;
  if (abs >= 1_000_000) return `${sign}R$ ${fmt(abs / 1_000_000)}mi`;
  if (abs >= 1_000) return `${sign}R$ ${fmt(abs / 1_000)}mil`;
  return `${sign}R$ ${fmt(abs)}`;
}

export function fmtPct(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return `${(Number(value) * 100).toLocaleString("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits })}%`;
}

export function shortName(name, max = 24) {
  const clean = String(name)
    .replace(" - PRUDENCIAL", "")
    .replace("BANCO ", "BCO ")
    .replace("BANCO", "BCO")
    .replace("ECONÔMICA FEDERAL", "CEF");
  return clean.length > max ? `${clean.slice(0, max - 1)}...` : clean;
}

export function addBackground(slide, ctx) {
  ctx.addShape(slide, { x: 0, y: 0, w: ctx.W, h: ctx.H, fill: C.white, line: ctx.line() });
}

export function addHeader(slide, ctx, kicker, title, subtitle = "") {
  ctx.addShape(slide, { x: 0, y: 0, w: ctx.W, h: 86, fill: C.black, line: ctx.line() });
  ctx.addShape(slide, { x: 0, y: 86, w: ctx.W, h: 8, fill: C.orange, line: ctx.line() });
  ctx.addText(slide, {
    text: kicker,
    x: 44,
    y: 15,
    w: 420,
    h: 18,
    fontSize: 12,
    color: C.orange,
    bold: true,
    typeface: ctx.fonts.body,
  });
  ctx.addText(slide, {
    text: title,
    x: 44,
    y: 40,
    w: 940,
    h: 34,
    fontSize: 25,
    color: C.white,
    bold: true,
    typeface: ctx.fonts.title,
  });
  if (subtitle) {
    ctx.addText(slide, {
      text: subtitle,
      x: 870,
      y: 20,
      w: 260,
      h: 28,
      fontSize: 9.5,
      color: "#D9D9D9",
      align: "right",
      typeface: ctx.fonts.body,
    });
  }
}

export function addFooter(slide, ctx, page) {
  ctx.addShape(slide, { x: 44, y: 674, w: 1088, h: 1, fill: C.gray300, line: ctx.line() });
  ctx.addText(slide, {
    text: "Este estudo usou dados do tomaconta | BCB BLOPRUDENCIAL 4060 local | universo: PL Dez/25 >= R$100 mi | valores em R$",
    x: 44,
    y: 684,
    w: 990,
    h: 16,
    fontSize: 8.8,
    color: C.gray700,
  });
  ctx.addText(slide, {
    text: String(page).padStart(2, "0"),
    x: 1135,
    y: 681,
    w: 40,
    h: 18,
    fontSize: 10,
    color: C.gray700,
    align: "right",
  });
}

export function addKpi(slide, ctx, x, y, w, label, value, note, accent = C.orange) {
  ctx.addShape(slide, { x, y: y + 3, w: 3, h: 56, fill: accent, line: ctx.line() });
  ctx.addText(slide, { text: label, x: x + 12, y: y + 2, w: w - 18, h: 14, fontSize: 8.8, bold: true, color: C.gray700 });
  ctx.addText(slide, {
    text: value,
    x: x + 12,
    y: y + 19,
    w: w - 18,
    h: 23,
    fontSize: 18,
    bold: true,
    color: C.black,
    typeface: ctx.fonts.title,
  });
  ctx.addText(slide, { text: note, x: x + 12, y: y + 45, w: w - 18, h: 13, fontSize: 7.8, color: C.gray700 });
}

export function addFactLine(slide, ctx, x, y, facts, opts = {}) {
  const gap = opts.gap ?? 32;
  let cursor = x;
  for (const fact of facts) {
    const w = fact.w ?? 170;
    ctx.addText(slide, {
      text: fact.label,
      x: cursor,
      y,
      w,
      h: 13,
      fontSize: 8.5,
      bold: true,
      color: C.gray700,
    });
    ctx.addText(slide, {
      text: fact.value,
      x: cursor,
      y: y + 17,
      w,
      h: 22,
      fontSize: 16,
      bold: true,
      color: fact.color ?? C.black,
      typeface: ctx.fonts.title,
    });
    ctx.addText(slide, {
      text: fact.note ?? "",
      x: cursor,
      y: y + 42,
      w,
      h: 12,
      fontSize: 7.6,
      color: C.gray700,
    });
    cursor += w + gap;
  }
}

export function sectionLabel(slide, ctx, text, x, y, w = 420) {
  ctx.addText(slide, { text, x, y, w, h: 18, fontSize: 12.5, bold: true, color: C.black });
  ctx.addShape(slide, { x, y: y + 23, w, h: 1, fill: C.gray300, line: ctx.line() });
}

export function table(slide, ctx, x, y, columns, rows, opts = {}) {
  const rowH = opts.rowH ?? 24;
  const headerH = opts.headerH ?? 27;
  const fontSize = opts.fontSize ?? 8.7;
  const totalW = columns.reduce((sum, col) => sum + col.w, 0);
  ctx.addShape(slide, { x, y, w: totalW, h: headerH, fill: C.black, line: ctx.line() });
  let cx = x;
  for (const col of columns) {
    ctx.addText(slide, {
      text: col.label,
      x: cx + 5,
      y: y + 7,
      w: col.w - 10,
      h: 15,
      fontSize: opts.headerFontSize ?? 8.4,
      bold: true,
      color: C.white,
      align: col.align ?? "left",
    });
    cx += col.w;
  }

  rows.forEach((row, i) => {
    const yy = y + headerH + i * rowH;
    const isHighlight = opts.highlight?.(row, i);
    const fill = isHighlight ? opts.highlightFill ?? C.white : i % 2 === 0 ? C.white : C.gray100;
    ctx.addShape(slide, { x, y: yy, w: totalW, h: rowH, fill, line: { style: "solid", fill: C.gray200, width: 1 } });
    let cxx = x;
    columns.forEach((col, j) => {
      const value = typeof col.value === "function" ? col.value(row, i) : row[col.key];
      ctx.addText(slide, {
        text: value ?? "",
        x: cxx + 5,
        y: yy + 6,
        w: col.w - 10,
        h: rowH - 7,
        fontSize,
        color: col.color?.(row, i) ?? (isHighlight ? opts.highlightColor ?? C.black : j === 0 ? C.black : C.gray900),
        bold: isHighlight || (j === 0 && opts.boldFirst !== false),
        align: col.align ?? "left",
      });
      cxx += col.w;
    });
  });
}

export function hBarChart(slide, ctx, x, y, w, rows, key, opts = {}) {
  const rowH = opts.rowH ?? 25;
  const labelW = opts.labelW ?? 174;
  const valueW = opts.valueW ?? 78;
  const barW = w - labelW - valueW - 18;
  const max = Math.max(...rows.map((row) => Math.abs(Number(row[key]) || 0)), 1);
  rows.forEach((row, i) => {
    const yy = y + i * rowH;
    const value = Number(row[key]) || 0;
    const bw = Math.max(2, (Math.abs(value) / max) * barW);
    const color = opts.color ?? (value < 0 ? C.red : C.orange);
    const isHighlight = opts.highlight?.(row, i);
    ctx.addText(slide, {
      text: `${i + 1}. ${shortName(row["Instituição"], opts.nameMax ?? 23)}`,
      x,
      y: yy + 2,
      w: labelW,
      h: 16,
      fontSize: opts.fontSize ?? 8.9,
      color: C.black,
      bold: isHighlight || i < 3,
    });
    ctx.addShape(slide, { x: x + labelW, y: yy + 6, w: barW, h: 11, fill: C.gray200, line: ctx.line() });
    ctx.addShape(slide, { x: x + labelW, y: yy + 6, w: bw, h: 11, fill: color, line: ctx.line() });
    ctx.addText(slide, {
      text: opts.formatValue ? opts.formatValue(value, row, i) : fmtCompact(value),
      x: x + labelW + barW + 9,
      y: yy + 1,
      w: valueW,
      h: 17,
      fontSize: opts.valueFontSize ?? 8.7,
      color: value < 0 ? C.red : C.gray900,
      bold: isHighlight || i < 3,
      align: "right",
    });
  });
}
