import {filterChart} from './data.js';

export const isScrChart = chart => String(chart.section || '').startsWith('SCR');

export function sectionLabel(section) {
  return section.replace(/^Crédito SFN · /, '').replace(/^Inadimplência · /, '');
}

export function seriesSections(manifest, extra = []) {
  return [...new Set([...(manifest?.sfnSections || []), ...extra.filter(isScrChart).map(chart => chart.section)])];
}

export function seriesCollections({sfn = [], extra = [], imob = [], window = '12', start = '', end = ''}) {
  const trim = chart => filterChart(chart, window, start, end);
  const monetary = sfn.map(trim);
  const additional = extra.map(trim);
  const housing = imob.map(trim);
  const financial = [...monetary, ...additional.filter(isScrChart)];
  return {sfn: financial, imob: housing, payments: additional.filter(chart => !isScrChart(chart)), all: [...financial, ...housing]};
}

export function competenceLabel(period) {
  const quarter = /^(\d{4})-Q([1-4])$/.exec(period || '');
  if (quarter) return `${['mar', 'jun', 'set', 'dez'][Number(quarter[2]) - 1]}/${quarter[1]}`;
  const month = /^(\d{4})-?(\d{2})/.exec(period || '');
  if (month && Number(month[2]) >= 1 && Number(month[2]) <= 12) return `${['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'][Number(month[2]) - 1]}/${month[1]}`;
  return period || 'N/D';
}

export function latestChartPeriod(charts) {
  return charts.flatMap(chart => chart.series.flatMap(series => series.data.filter(point => point[1] != null).map(point => point[0]))).filter(date => /^\d{4}-\d{2}/.test(date)).sort().at(-1)?.slice(0, 7) || null;
}

export function defaultInterval(charts = []) {
  const latest = latestChartPeriod(charts) || new Date().toISOString().slice(0, 7);
  const [year, month] = latest.split('-').map(Number);
  return {start: new Date(Date.UTC(year, month - 12, 1)).toISOString().slice(0, 7), end: latest};
}
