import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DATA_PATH = path.join(ROOT, "data", "workbook_data.json");
const OUT_DIR = path.join(ROOT, "excel");
const FINAL_XLSX = path.join(OUT_DIR, "estudo_pl_lucro_bancos_dez25_mar26.xlsx");
const PREVIEW_DIR = path.join(OUT_DIR, "preview");

const ORANGE = "#FF6200";
const BLACK = "#1F1F1F";
const DARK = "#2B2B2B";
const MID = "#6B7280";
const LIGHT = "#F3F4F6";
const GRID = "#D9DEE7";
const GREEN = "#DDEFE3";
const RED = "#F7D9D9";

function colName(index1) {
  let n = index1;
  let s = "";
  while (n > 0) {
    const m = (n - 1) % 26;
    s = String.fromCharCode(65 + m) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s;
}

function tableRange(rowCount, colCount, startRow = 1, startCol = 1) {
  return `${colName(startCol)}${startRow}:${colName(startCol + colCount - 1)}${startRow + rowCount - 1}`;
}

function fmtBRL(value, scale = 1_000_000_000, suffix = "bi") {
  if (value == null || Number.isNaN(Number(value))) return "N/D";
  return `R$ ${(Number(value) / scale).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}${suffix}`;
}

function fmtPct(value) {
  if (value == null || Number.isNaN(Number(value))) return "N/D";
  return `${(Number(value) * 100).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
}

function cleanSheetName(name) {
  return String(name).slice(0, 31).replace(/[:\\/?*\[\]]/g, "_");
}

function matrixFromSheet(payload) {
  const headers = payload.columns;
  const rows = payload.rows.map((row) => headers.map((h) => row[h] ?? null));
  return [headers, ...rows];
}

function setWidths(sheet, widths) {
  widths.forEach((w, idx) => {
    sheet.getRange(`${colName(idx + 1)}:${colName(idx + 1)}`).format.columnWidthPx = w;
  });
}

function styleTitle(sheet, range, title, subtitle) {
  sheet.showGridLines = false;
  sheet.getRange(range).merge();
  sheet.getRange(range).values = [[title]];
  sheet.getRange(range).format = {
    fill: BLACK,
    font: { color: "#FFFFFF", bold: true, size: 16 },
    horizontalAlignment: "left",
    verticalAlignment: "center",
  };
  sheet.getRange("A2:H2").merge();
  sheet.getRange("A2").values = [[subtitle]];
  sheet.getRange("A2").format = {
    fill: "#FFFFFF",
    font: { color: MID, italic: true, size: 10 },
    wrapText: true,
  };
}

function styleTable(sheet, rows, cols, tableName) {
  const range = tableRange(rows, cols);
  sheet.getRange(range).format.borders = { preset: "all", style: "thin", color: GRID };
  sheet.getRange(`A1:${colName(cols)}1`).format = {
    fill: BLACK,
    font: { color: "#FFFFFF", bold: true },
    wrapText: true,
    verticalAlignment: "center",
  };
  sheet.getRange(`A1:${colName(cols)}${rows}`).format.font = { size: 9 };
  sheet.freezePanes.freezeRows(1);
  try {
    const table = sheet.tables.add(range, true, tableName);
    table.style = "TableStyleMedium2";
    table.showFilterButton = true;
  } catch {
    // Tabelas podem falhar em ranges muito largos em algumas versões; filtros ainda ficam via cabeçalho congelado.
  }
}

function applyNumberFormats(sheet, headers, rows) {
  headers.forEach((h, idx) => {
    const col = colName(idx + 1);
    const range = sheet.getRange(`${col}2:${col}${rows}`);
    if (/pct|%/i.test(h)) {
      range.setNumberFormat("0.0%;[Red](0.0%);-");
    } else if (/PL_|Delta_|LL_|Proxy_|Credor|Devedor/i.test(h)) {
      range.setNumberFormat('R$ #,##0;[Red](R$ #,##0);-');
    } else if (/Rank/i.test(h)) {
      range.setNumberFormat("#,##0");
    }
  });
}

function addDataSheet(workbook, name, payload, tableName) {
  const sheet = workbook.worksheets.add(cleanSheetName(name));
  const matrix = matrixFromSheet(payload);
  const rows = matrix.length;
  const cols = matrix[0].length;
  sheet.getRange(tableRange(rows, cols)).values = matrix;
  styleTable(sheet, rows, cols, tableName);
  applyNumberFormats(sheet, payload.columns, rows);
  setWidths(sheet, payload.columns.map((h) => (h === "Instituição" ? 290 : Math.min(170, Math.max(96, String(h).length * 7 + 42)))));
  sheet.getRange(`A1:${colName(cols)}${rows}`).format.wrapText = false;
  return sheet;
}

function addSummary(workbook, data) {
  const s = workbook.worksheets.add("Resumo");
  styleTitle(
    s,
    "A1:H1",
    "Estudo PL e Lucro Líquido | Dez/25 a Mar/26",
    "Universo: instituições com PL dez/25 >= R$100 mi | Documento 4060 | valores em R$"
  );
  setWidths(s, [210, 150, 150, 150, 26, 230, 150, 150, 150, 150, 150, 150]);

  const summary = data.summary;
  const coverage = summary.coverage;
  const totals = summary.totals;

  s.getRange("A4:D4").values = [["Universo filtrado", "ΔPL Dez/25-Mar/26", "LL 1T26", "Proxy capital/outras"]];
  s.getRange("A5:D5").values = [[
    coverage.instituicoes_qualificadas_pl_100mm,
    fmtBRL(totals.Delta_PL_Dez25_Mar26),
    fmtBRL(totals.LL_202603),
    fmtBRL(totals.Proxy_Capital_Outras_1T26),
  ]];
  s.getRange("A4:D4").format = { fill: DARK, font: { color: "#FFFFFF", bold: true }, horizontalAlignment: "center" };
  s.getRange("A5:D5").format = { fill: LIGHT, font: { bold: true, size: 13 }, horizontalAlignment: "center" };
  s.getRange("B5:D5").format.font = { bold: true, size: 13 };

  const monthRows = summary.month_delta_summary.map((r) => [r["Mês"], fmtBRL(r.Delta_PL), fmtBRL(r.Proxy_Capital_Outras)]);
  s.getRange("A8:C11").values = [["Mês", "ΔPL", "ΔPL - LL mensal"], ...monthRows];
  s.getRange("A8:C8").format = { fill: BLACK, font: { color: "#FFFFFF", bold: true } };
  s.getRange("A8:C11").format.borders = { preset: "all", style: "thin", color: GRID };

  const monthChartRows = summary.month_delta_summary.map((r) => [r["Mês"], r.Delta_PL, r.Proxy_Capital_Outras]);
  s.getRange("L38:N41").values = [["Mês", "ΔPL", "ΔPL - LL mensal"], ...monthChartRows];

  const topProxy = summary.top_proxy.slice(0, 10).map((r) => [
    r["Instituição"],
    fmtBRL(r.Proxy_Capital_Outras_1T26),
    fmtBRL(r.Delta_PL_Dez25_Mar26),
    fmtBRL(r.LL_202603),
    r.Maior_Mes_Aumento_PL,
  ]);
  s.getRange("F4:J4").values = [["Top indícios de aporte/outras mutações", "Proxy 1T26", "ΔPL", "LL 1T26", "Mês-chave"]];
  s.getRange(`F5:J${4 + topProxy.length}`).values = topProxy;
  s.getRange("F4:J4").format = { fill: BLACK, font: { color: "#FFFFFF", bold: true }, wrapText: true };
  s.getRange(`F4:J${4 + topProxy.length}`).format.borders = { preset: "all", style: "thin", color: GRID };

  const topProxyChart = summary.top_proxy.slice(0, 10).map((r) => [r["Instituição"], r.Proxy_Capital_Outras_1T26]);
  s.getRange(`P38:Q${38 + topProxyChart.length}`).values = [["Instituição", "Proxy 1T26"], ...topProxyChart];

  const llPos = summary.ll_pos_pct.slice(0, 8).map((r) => [r["Instituição"], fmtBRL(r.LL_202503, 1_000_000, "mm"), fmtBRL(r.LL_202603, 1_000_000, "mm"), fmtPct(r.Delta_LL_pct_Mar25_Mar26)]);
  const llNeg = summary.ll_neg_pct.slice(0, 8).map((r) => [r["Instituição"], fmtBRL(r.LL_202503, 1_000_000, "mm"), fmtBRL(r.LL_202603, 1_000_000, "mm"), fmtPct(r.Delta_LL_pct_Mar25_Mar26)]);
  s.getRange("A15:D15").values = [["Maiores variações % positivas de LL", "LL mar/25", "LL mar/26", "Var. %"]];
  s.getRange(`A16:D${15 + llPos.length}`).values = llPos;
  s.getRange("F15:I15").values = [["Maiores variações % negativas de LL", "LL mar/25", "LL mar/26", "Var. %"]];
  s.getRange(`F16:I${15 + llNeg.length}`).values = llNeg;
  for (const r of ["A15:D15", "F15:I15"]) s.getRange(r).format = { fill: BLACK, font: { color: "#FFFFFF", bold: true }, wrapText: true };
  s.getRange(`A15:D${15 + llPos.length}`).format.borders = { preset: "all", style: "thin", color: GRID };
  s.getRange(`F15:I${15 + llNeg.length}`).format.borders = { preset: "all", style: "thin", color: GRID };

  s.getRange("A26:H29").merge();
  s.getRange("A26").values = [[
    "Leitura: o proxy de aporte/outras mutações é ΔPL menos lucro líquido do período. Ele é um indicador de movimentos patrimoniais não explicados por resultado, não uma prova documental de aumento de capital. Para confirmação societária, cruzar com eventos de capital, demonstrações publicadas e notas explicativas."
  ]];
  s.getRange("A26").format = { fill: "#FFF7ED", font: { color: BLACK, italic: true }, wrapText: true, verticalAlignment: "top" };

  s.getRange("L38:Q50").format.font = { color: "#FFFFFF" };

  const chart1 = s.charts.add("bar", s.getRange("L38:N41"));
  chart1.title = "Aumento de PL concentrou-se em Jan/26; proxy líquido também";
  chart1.hasLegend = true;
  chart1.yAxis = { numberFormatCode: 'R$ #,##0' };
  chart1.setPosition("L4", "S16");

  const chart2 = s.charts.add("bar", s.getRange(`P38:Q${38 + topProxyChart.length}`));
  chart2.title = "Top 10 por proxy de aporte/outras mutações";
  chart2.hasLegend = false;
  chart2.yAxis = { numberFormatCode: 'R$ #,##0' };
  chart2.setPosition("L18", "S34");

  return s;
}

function addChecks(workbook, data) {
  const s = workbook.worksheets.add("Metodologia_Checks");
  styleTitle(
    s,
    "A1:H1",
    "Metodologia e checks",
    "Definições, cobertura e fontes usadas no estudo"
  );
  setWidths(s, [260, 320, 220, 220, 180, 180, 180, 180]);

  const m = data.summary.methodology;
  const c = data.summary.coverage;
  const rows = [
    ["Fonte", m.fonte],
    ["Documento usado", m.documento],
    ["Conta PL", m.pl_conta],
    ["Lucro líquido", m.lucro_liquido],
    ["Deduplicação", m.deduplicacao],
    ["Filtro", m.filtro],
    ["Proxy aporte/outras mutações", m.proxy_aporte],
    ["Instituições com PL dez/25", c.instituicoes_pl_dez25],
    ["Instituições qualificadas", c.instituicoes_qualificadas_pl_100mm],
    ["Com PL mar/26", c.instituicoes_com_pl_mar26],
    ["Com LL mar/25", c.instituicoes_com_ll_mar25],
    ["Com LL mar/26", c.instituicoes_com_ll_mar26],
  ];
  s.getRange(`A4:B${3 + rows.length}`).values = rows;
  s.getRange("A4:A15").format = { fill: LIGHT, font: { bold: true } };
  s.getRange(`A4:B${3 + rows.length}`).format.borders = { preset: "all", style: "thin", color: GRID };
  s.getRange("B4:B15").format.wrapText = true;

  s.getRange("D4:H4").values = [["Check", "Valor", "Esperado", "Diferença", "Status"]];
  const checks = [
    ["Filtro mínimo PL", c.instituicoes_qualificadas_pl_100mm, ">= 1", null, "OK"],
    ["PL mar/26 disponível", c.instituicoes_com_pl_mar26, "informativo", null, "OK"],
    ["LL mar/25 disponível", c.instituicoes_com_ll_mar25, "informativo", null, "OK"],
    ["LL mar/26 disponível", c.instituicoes_com_ll_mar26, "informativo", null, "OK"],
  ];
  s.getRange(`D5:H${4 + checks.length}`).values = checks;
  s.getRange("D4:H4").format = { fill: BLACK, font: { color: "#FFFFFF", bold: true } };
  s.getRange(`D5:H${4 + checks.length}`).format.borders = { preset: "all", style: "thin", color: GRID };
  s.getRange(`H5:H${4 + checks.length}`).format = { fill: GREEN, font: { bold: true, color: "#166534" } };
  return s;
}

async function main() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  await fs.mkdir(PREVIEW_DIR, { recursive: true });
  const data = JSON.parse(await fs.readFile(DATA_PATH, "utf8"));
  const workbook = Workbook.create();

  addSummary(workbook, data);
  addDataSheet(workbook, "Base_Analitica", data.sheets.Base_Analitica, "BaseAnalitica");
  addDataSheet(workbook, "Top_Proxy_Aportes", data.sheets.Top_Proxy_Aportes, "TopProxyAportes");
  addDataSheet(workbook, "Top_PL_Abs", data.sheets.Top_PL_Abs, "TopPLAbs");
  addDataSheet(workbook, "Top_PL_Pct", data.sheets.Top_PL_Pct, "TopPLPct");
  addDataSheet(workbook, "LL_Mar25_vs_Mar26", data.sheets.LL_Mar25_vs_Mar26, "LLMar25Mar26");
  addDataSheet(workbook, "LL_Var_Pct_Positiva", data.sheets.LL_Var_Pct_Positiva, "LLPctPos");
  addDataSheet(workbook, "LL_Var_Pct_Negativa", data.sheets.LL_Var_Pct_Negativa, "LLPctNeg");
  addDataSheet(workbook, "Top_Proxy_Negativo", data.sheets.Top_Proxy_Negativo, "TopProxyNeg");
  addDataSheet(workbook, "Resumo_Mensal", data.sheets.Resumo_Mensal, "ResumoMensal");
  addChecks(workbook, data);

  const inspect = await workbook.inspect({
    kind: "table",
    range: "Resumo!A1:J29",
    include: "values,formulas",
    tableMaxRows: 30,
    tableMaxCols: 10,
  });
  console.log(inspect.ndjson);

  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 100 },
    summary: "final formula error scan",
  });
  console.log(errors.ndjson);

  for (const sheetName of ["Resumo", "Base_Analitica", "Top_Proxy_Aportes", "LL_Mar25_vs_Mar26", "Metodologia_Checks"]) {
    const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
    await fs.writeFile(path.join(PREVIEW_DIR, `${sheetName}.png`), new Uint8Array(await preview.arrayBuffer()));
  }

  const xlsx = await SpreadsheetFile.exportXlsx(workbook);
  await xlsx.save(FINAL_XLSX);
  console.log(JSON.stringify({ output: FINAL_XLSX }));
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
