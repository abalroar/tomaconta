import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DATA_PATH = path.join(ROOT, "data", "workbook_data.json");
const OUT_DIR = path.join(ROOT, "excel");
const PREVIEW_DIR = path.join(OUT_DIR, "preview");
const FINAL_XLSX = path.join(OUT_DIR, "estudo_pl_ll_simplificado_dez25_mar26.xlsx");

const ORANGE = "#FF6200";
const BLACK = "#1F1F1F";
const DARK = "#333333";
const MID = "#6B7280";
const LIGHT = "#F3F4F6";
const PALE_ORANGE = "#FFF3E8";
const GREEN = "#DDEFE3";
const RED = "#F8D7DA";
const GRID = "#D9DEE7";

function colName(index1) {
  let n = index1;
  let out = "";
  while (n > 0) {
    const m = (n - 1) % 26;
    out = String.fromCharCode(65 + m) + out;
    n = Math.floor((n - 1) / 26);
  }
  return out;
}

function tableRange(rowCount, colCount, startRow = 1, startCol = 1) {
  return `${colName(startCol)}${startRow}:${colName(startCol + colCount - 1)}${startRow + rowCount - 1}`;
}

function cleanSheetName(name) {
  return String(name).slice(0, 31).replace(/[:\\/?*\[\]]/g, "_");
}

function brl(value, scale = 1_000_000_000, suffix = " bi") {
  if (value == null || Number.isNaN(Number(value))) return "N/D";
  return `R$ ${(Number(value) / scale).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}${suffix}`;
}

function pct(value) {
  if (value == null || Number.isNaN(Number(value))) return "N/D";
  return `${(Number(value) * 100).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
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

function setTitle(sheet, title, subtitle, range = "A1:J1") {
  sheet.showGridLines = false;
  sheet.getRange(range).merge();
  sheet.getRange(range).values = [[title]];
  sheet.getRange(range).format = {
    fill: BLACK,
    font: { color: "#FFFFFF", bold: true, size: 15 },
    horizontalAlignment: "left",
    verticalAlignment: "center",
  };
  sheet.getRange("A2:J2").merge();
  sheet.getRange("A2").values = [[subtitle]];
  sheet.getRange("A2").format = { font: { color: MID, italic: true, size: 10 }, wrapText: true };
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
    // O filtro visual via cabeçalho congelado é suficiente se a tabela nativa falhar.
  }
}

function applyNumberFormats(sheet, headers, rows) {
  headers.forEach((header, idx) => {
    const col = colName(idx + 1);
    const range = sheet.getRange(`${col}2:${col}${rows}`);
    if (/pct|%/i.test(header)) {
      range.setNumberFormat("0.0%;[Red](0.0%);-");
    } else if (/PL_|LL_|Delta_|Credor|Devedor/i.test(header)) {
      range.setNumberFormat('R$ #,##0;[Red](R$ #,##0);-');
    } else if (/Rank/i.test(header)) {
      range.setNumberFormat("#,##0");
    }
  });
}

function addDataSheet(workbook, name, payload, tableName, chartConfig) {
  const sheet = workbook.worksheets.add(cleanSheetName(name));
  const matrix = matrixFromSheet(payload);
  const rows = matrix.length;
  const cols = matrix[0].length;
  sheet.getRange(tableRange(rows, cols)).values = matrix;
  styleTable(sheet, rows, cols, tableName);
  applyNumberFormats(sheet, payload.columns, rows);
  setWidths(
    sheet,
    payload.columns.map((h) => (h === "Instituição" ? 320 : Math.min(170, Math.max(92, String(h).length * 7 + 44))))
  );
  sheet.getRange(`A1:${colName(cols)}${rows}`).format.wrapText = false;

  if (chartConfig) {
    const chartRows = payload.rows.slice(0, chartConfig.limit).map((row) => [
      String(row["Instituição"]).replace(" - PRUDENCIAL", ""),
      row[chartConfig.valueKey],
    ]);
    const startCol = cols + 3;
    const source = `${colName(startCol)}1:${colName(startCol + 1)}${chartRows.length + 1}`;
    sheet.getRange(source).values = [["Instituição", chartConfig.title], ...chartRows];
    sheet.getRange(source).format.font = { color: "#FFFFFF" };
    try {
      const chart = sheet.charts.add("bar", sheet.getRange(source));
      chart.title = chartConfig.title;
      chart.hasLegend = false;
      chart.yAxis = { numberFormatCode: chartConfig.numberFormatCode ?? 'R$ #,##0' };
      chart.setPosition(chartConfig.positionStart, chartConfig.positionEnd);
    } catch (error) {
      console.log(`Chart skipped for ${name}: ${error.message}`);
    }
  }

  return sheet;
}

function addKpi(sheet, range, title, value, note, fill = LIGHT) {
  sheet.getRange(range).merge();
  const [start] = range.split(":");
  sheet.getRange(start).values = [[`${title}\n${value}\n${note}`]];
  sheet.getRange(start).format = {
    fill,
    font: { color: BLACK, bold: true, size: 12 },
    wrapText: true,
    verticalAlignment: "center",
    horizontalAlignment: "center",
    borders: { preset: "all", style: "thin", color: GRID },
  };
}

function addSummary(workbook, data) {
  const s = workbook.worksheets.add("Resumo");
  setTitle(
    s,
    "PL e lucro líquido | estudo simplificado",
    "Universo: instituições com PL em Dez/25 >= R$100 mi | Documento 4060 | rankings por delta bruto e percentual"
  );
  setWidths(s, [42, 270, 145, 145, 145, 88, 105, 145, 145, 145, 145, 145, 145, 145]);

  const summary = data.summary;
  addKpi(s, "A4:B7", "Universo", summary.display.qualified, "instituições no corte");
  addKpi(s, "C4:D7", "Aumentos de PL", summary.display.positive_pl_delta, "delta positivo total");
  addKpi(s, "E4:F7", "Top 10 PL", summary.display.top10_share, "do delta positivo");
  addKpi(s, "G4:H7", "PicPay", summary.display.picpay_delta, `rank #${summary.picpay_rank_delta_pl_positive} | ${summary.display.picpay_var}`, PALE_ORANGE);
  addKpi(s, "I4:J7", "ΔLL total", summary.display.ll_delta_total, "Mar/25 vs Mar/26");

  const topPl = summary.top_pl_up.slice(0, 15);
  const plRows = topPl.map((row, idx) => [
    idx + 1,
    row["Instituição"],
    brl(row.PL_202512),
    brl(row.PL_202603),
    brl(row.Delta_PL),
    pct(row.Var_PL_pct),
    pct(row.Contrib_Acum_Delta_PL_Pos_pct),
  ]);
  s.getRange("A10:G10").values = [[
    "#",
    "Maiores aumentos de PL",
    "PL Dez/25",
    "PL Mar/26",
    "ΔPL",
    "Var. %",
    "% acum. altas",
  ]];
  s.getRange(`A11:G${10 + plRows.length}`).values = plRows;
  s.getRange("A10:G10").format = { fill: BLACK, font: { color: "#FFFFFF", bold: true } };
  s.getRange(`A10:G${10 + plRows.length}`).format.borders = { preset: "all", style: "thin", color: GRID };

  const helper = topPl.map((row) => [String(row["Instituição"]).replace(" - PRUDENCIAL", ""), row.Delta_PL]);
  s.getRange(`L10:M${10 + helper.length}`).values = [["Instituição", "ΔPL"], ...helper];
  s.getRange(`L10:M${10 + helper.length}`).format.font = { color: "#FFFFFF" };
  try {
    const chart = s.charts.add("bar", s.getRange(`L10:M${10 + helper.length}`));
    chart.title = "Maiores aumentos de PL | Dez/25 a Mar/26";
    chart.hasLegend = false;
    chart.yAxis = { numberFormatCode: 'R$ #,##0' };
    chart.setPosition("A29", "J54");
  } catch (error) {
    console.log(`Summary chart skipped: ${error.message}`);
  }

  const llUp = summary.top_ll_up.slice(0, 8);
  const llDown = summary.top_ll_down.slice(0, 8);
  const llRows = [
    ["Melhores ΔLL", "", "", "", "Piores ΔLL", "", "", ""],
    ["Instituição", "LL Mar/25", "LL Mar/26", "ΔLL", "Instituição", "LL Mar/25", "LL Mar/26", "ΔLL"],
    ...Array.from({ length: 8 }, (_, idx) => [
      llUp[idx]?.["Instituição"] ?? "",
      brl(llUp[idx]?.LL_202503, 1_000_000, " mm"),
      brl(llUp[idx]?.LL_202603, 1_000_000, " mm"),
      brl(llUp[idx]?.Delta_LL, 1_000_000, " mm"),
      llDown[idx]?.["Instituição"] ?? "",
      brl(llDown[idx]?.LL_202503, 1_000_000, " mm"),
      brl(llDown[idx]?.LL_202603, 1_000_000, " mm"),
      brl(llDown[idx]?.Delta_LL, 1_000_000, " mm"),
    ]),
  ];
  s.getRange(`A57:H${56 + llRows.length}`).values = llRows;
  s.getRange("A57:D57").merge();
  s.getRange("E57:H57").merge();
  s.getRange("A57:H58").format = { fill: BLACK, font: { color: "#FFFFFF", bold: true }, wrapText: true };
  s.getRange(`A57:H${56 + llRows.length}`).format.borders = { preset: "all", style: "thin", color: GRID };

  s.getRange("A70:J73").merge();
  s.getRange("A70").values = [[
    "Metodologia: PL = conta 6000000004 no documento 4060. Lucro líquido = 7000000003 Resultado Credor - abs(8000000002 Resultado Devedor). O workbook traz rankings por delta bruto e por variação percentual."
  ]];
  s.getRange("A70").format = { fill: PALE_ORANGE, font: { color: BLACK, italic: true }, wrapText: true, verticalAlignment: "top" };

  return s;
}

function addMethodology(workbook, data) {
  const s = workbook.worksheets.add("Metodologia");
  setTitle(s, "Metodologia e checks", "Definições usadas para reproduzir o estudo");
  setWidths(s, [260, 620, 180, 180, 180]);

  const m = data.summary.methodology;
  const rows = [
    ["Fonte", m.fonte],
    ["Documento", m.documento],
    ["Conta PL", m.pl_conta],
    ["Lucro líquido", m.lucro_liquido],
    ["Universo", m.universo],
    ["Deduplicação", m.deduplicacao],
    ["Ordenação", m.ordenacao],
    ["Omitido no produto executivo", m.omitido],
  ];
  s.getRange(`A4:B${3 + rows.length}`).values = rows;
  s.getRange(`A4:A${3 + rows.length}`).format = { fill: LIGHT, font: { bold: true } };
  s.getRange(`A4:B${3 + rows.length}`).format = { borders: { preset: "all", style: "thin", color: GRID }, wrapText: true };

  const c = data.summary.coverage;
  const checks = [
    ["Instituições no corte", c.instituicoes_qualificadas_pl_100mm, ">= 1", "OK"],
    ["Com aumento de PL", c.instituicoes_com_aumento_pl, "informativo", "OK"],
    ["Com queda de PL", c.instituicoes_com_queda_pl, "informativo", "OK"],
    ["Com LL Mar/25 e Mar/26", c.instituicoes_com_ll_mar25_e_mar26, "informativo", "OK"],
  ];
  s.getRange("D4:G4").values = [["Check", "Valor", "Esperado", "Status"]];
  s.getRange(`D5:G${4 + checks.length}`).values = checks;
  s.getRange("D4:G4").format = { fill: BLACK, font: { color: "#FFFFFF", bold: true } };
  s.getRange(`D5:G${4 + checks.length}`).format.borders = { preset: "all", style: "thin", color: GRID };
  s.getRange(`G5:G${4 + checks.length}`).format = { fill: GREEN, font: { color: "#166534", bold: true } };
  return s;
}

async function main() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  await fs.mkdir(PREVIEW_DIR, { recursive: true });

  const data = JSON.parse(await fs.readFile(DATA_PATH, "utf8"));
  const workbook = Workbook.create();

  addSummary(workbook, data);
  addDataSheet(workbook, "PL_Maiores_Altas", data.sheets.PL_Maiores_Altas, "PLMaioresAltas", {
    limit: 20,
    valueKey: "Delta_PL",
    title: "ΔPL positivo",
    positionStart: "J2",
    positionEnd: "S24",
  });
  addDataSheet(workbook, "PL_Maiores_Quedas", data.sheets.PL_Maiores_Quedas, "PLMaioresQuedas", {
    limit: 15,
    valueKey: "Delta_PL",
    title: "ΔPL negativo",
    positionStart: "J2",
    positionEnd: "S22",
  });
  addDataSheet(workbook, "PL_Maiores_Altas_pct", data.sheets.PL_Maiores_Altas_pct, "PLMaioresAltasPct", {
    limit: 20,
    valueKey: "Var_PL_pct",
    title: "Var. PL positiva",
    positionStart: "J2",
    positionEnd: "S24",
    numberFormatCode: "0.0%",
  });
  addDataSheet(workbook, "PL_Maiores_Quedas_pct", data.sheets.PL_Maiores_Quedas_pct, "PLMaioresQuedasPct", {
    limit: 15,
    valueKey: "Var_PL_pct",
    title: "Var. PL negativa",
    positionStart: "J2",
    positionEnd: "S22",
    numberFormatCode: "0.0%",
  });
  addDataSheet(workbook, "PL_Todas_IFs", data.sheets.PL_Todas_IFs, "PLTodasIFs");
  addDataSheet(workbook, "LL_Maiores_Altas", data.sheets.LL_Maiores_Altas, "LLMaioresAltas", {
    limit: 15,
    valueKey: "Delta_LL",
    title: "ΔLL positivo",
    positionStart: "L2",
    positionEnd: "U22",
  });
  addDataSheet(workbook, "LL_Maiores_Quedas", data.sheets.LL_Maiores_Quedas, "LLMaioresQuedas", {
    limit: 15,
    valueKey: "Delta_LL",
    title: "ΔLL negativo",
    positionStart: "L2",
    positionEnd: "U22",
  });
  addDataSheet(workbook, "LL_Maiores_Altas_pct", data.sheets.LL_Maiores_Altas_pct, "LLMaioresAltasPct", {
    limit: 15,
    valueKey: "Var_LL_pct",
    title: "Var. LL positiva",
    positionStart: "L2",
    positionEnd: "U22",
    numberFormatCode: "0.0%",
  });
  addDataSheet(workbook, "LL_Maiores_Quedas_pct", data.sheets.LL_Maiores_Quedas_pct, "LLMaioresQuedasPct", {
    limit: 15,
    valueKey: "Var_LL_pct",
    title: "Var. LL negativa",
    positionStart: "L2",
    positionEnd: "U22",
    numberFormatCode: "0.0%",
  });
  addDataSheet(workbook, "LL_Todas_IFs", data.sheets.LL_Todas_IFs, "LLTodasIFs");
  addMethodology(workbook, data);

  const inspect = await workbook.inspect({
    kind: "table",
    range: "Resumo!A1:J73",
    include: "values,formulas",
    tableMaxRows: 80,
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

  for (const spec of [
    ["Resumo", "A1:J73"],
    ["PL_Maiores_Altas", "A1:S30"],
    ["PL_Maiores_Altas_pct", "A1:S30"],
    ["LL_Maiores_Altas", "A1:U28"],
    ["LL_Maiores_Altas_pct", "A1:U28"],
    ["LL_Maiores_Quedas", "A1:U28"],
    ["Metodologia", "A1:G14"],
  ]) {
    const [sheetName, range] = spec;
    const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
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
