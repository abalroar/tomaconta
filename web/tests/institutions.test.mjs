import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {ANALYSIS_GROUPS, comparisonChart, historyThrough, institutionChart, institutionExportCharts, institutionRanking, metricNumber, observationAt, previousObservation, validateInstitutionHistory} from '../src/institution-data.js';
import {chartOption, csvDownload} from '../src/data.js';
import {chartDataForPptx, coverageForCharts} from '../src/export.js';
import {chartLabel, chartNumber, chartTick, chartValue, showInnerLabel} from '../src/chart-format.js';

const read = async path => JSON.parse(await readFile(new URL(`../public/${path}`, import.meta.url), 'utf8'));
const catalog = await read('data/institutions.json');
const itau = catalog.institutions.find(bank => bank.id === '5f6d3c0745685d8f');
const afinz = catalog.institutions.find(bank => bank.id === '73f0e1311a08e627');
const bradesco = catalog.institutions.find(bank => bank.id === '1271a247d1938e89');
const [itauHistory, afinzHistory, bradescoHistory] = await Promise.all([itau, afinz, bradesco].map(bank => read(bank.historyPath)));
const metrics = catalog.metrics;
const chart = (keys, overrides = {}) => institutionChart({bank: itau, payload: itauHistory, metrics, keys, period: '2026-Q2', window: 'all', ...overrides});
const last = config => config.series[0].data.at(-1)[1];
const near = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} differs from ${expected}`);

test('real Itaú analysis exposes all 23 registered indicators in their original perimeter and scale', () => {
  const before = JSON.stringify(itauHistory);
  const grouped = ANALYSIS_GROUPS.flatMap(group => [...group.metrics, ...group.more]);
  assert.equal(grouped.length, 23);
  assert.deepEqual(new Set(grouped), new Set(Object.keys(metrics)));
  assert.equal(itau.perimeter, 'Prudencial');
  assert.equal(observationAt(itauHistory, '2026-Q2').values.assets, 2846417632562.91);
  near(last(chart(['assets'])), 2846.41763256291);
  near(last(chart(['credit'])), 1288.92843156755);
  near(last(chart(['profitYtd'])), 24.6703059397);
  near(last(chart(['expectedLoss'])), -53.69759559089);
  assert.equal(last(chart(['roe'])), 20.66501736);
  assert.equal(last(chart(['stage3Ratio'])), 4.9411029);
  assert.equal(last(chart(['npl'])), 2.32689424);
  assert.equal(chart(['assets']).unit, 'R$ bilhões');
  assert.equal(chart(['roe']).unit, '%');
  const exports = institutionExportCharts({bank: itau, payload: itauHistory, metrics, period: '2026-Q2', window: '12'});
  assert.equal(exports.length, 23);
  assert.ok(exports.every(config => config.section === 'ITAU - PRUDENCIAL' && config.source === 'BCB / IFData · Prudencial'));
  assert.equal(JSON.stringify(itauHistory), before);
});

test('competence and calendar-quarter windows exclude future observations and preserve gaps', () => {
  const rows = historyThrough(itauHistory, '2026-Q1', '4');
  assert.deepEqual(rows.map(row => row.period), ['2025-Q2', '2025-Q3', '2025-Q4', '2026-Q1']);
  assert.equal(observationAt(itauHistory, '2026-Q1').values.profitYtd, 12150492100.62);
  assert.equal(previousObservation(itauHistory, '2026-Q2').period, '2026-Q1');
  const sourceWithGap = {...itauHistory, history: itauHistory.history.filter(row => row.period !== '2025-Q4')};
  const config = chart(['assets'], {payload: sourceWithGap, period: '2026-Q2', window: '4'});
  assert.deepEqual(config.series[0].data.map(([date]) => date), ['2025-09-30', '2025-12-31', '2026-03-31', '2026-06-30']);
  assert.equal(config.series[0].data[1][1], null);
  assert.equal(chartOption(config).series[0].connectNulls, false);
  assert.equal(chartDataForPptx(config)[0].values[1], null);
  const missingLatest = {...itauHistory, history: itauHistory.history.filter(row => row.period !== '2026-Q2')};
  assert.equal(last(chart(['assets'], {payload: missingLatest, period: '2026-Q2', window: '4'})), null);
});

test('late responses, duplicate competences and mixed financial units are rejected', () => {
  assert.throws(() => validateInstitutionHistory(itau, bradescoHistory), /instituição e ao perímetro/);
  assert.throws(() => validateInstitutionHistory(itau, {...itauHistory, perimeter: 'Individual'}), /instituição e ao perímetro/);
  assert.throws(() => validateInstitutionHistory(itau, {...itauHistory, history: [itauHistory.history[0], itauHistory.history[0]]}), /duplicada/);
  assert.throws(() => chart(['assets', 'roe']), /mesma unidade/);
});

test('real Afinz losses keep their accounting signs, unavailable stage 2 remains missing, and zero is observed', () => {
  const configs = institutionExportCharts({bank: afinz, payload: afinzHistory, metrics, period: '2026-Q2', window: '4'});
  const byId = new Map(configs.map(config => [config.id, config]));
  assert.equal(last(byId.get('institution-roe')), -136.33175621);
  near(last(byId.get('institution-profitYtd')), -.09337012756);
  near(last(byId.get('institution-expectedLoss')), -.64856523099);
  assert.equal(last(byId.get('institution-stage2')), null);
  assert.equal(metricNumber(null, 'stage2', metrics), 'N/D');
  assert.equal(metricNumber(0, 'stage2', metrics), '0,00');
  const coverage = coverageForCharts(configs);
  assert.equal(coverage.complete, false);
  assert.ok(coverage.missing.some(config => config.id === 'institution-stage2'));
  assert.ok(coverage.ready.some(config => config.id === 'institution-expectedLoss'));
  const observedZero = structuredClone(itauHistory);
  observedZero.history.at(-1).values.profitQuarter = 0;
  assert.equal(last(chart(['profitQuarter'], {payload: observedZero, window: '1'})), 0);
  assert.deepEqual(chartDataForPptx(chart(['profitQuarter'], {payload: observedZero, window: '1'}))[0].values, [0]);
});

test('comparison uses one competence, one perimeter and source units without substituting unavailable dates', () => {
  const compare = comparisonChart({banks: [itau, bradesco], histories: [itauHistory, bradescoHistory], metrics, key: 'roe', period: '2026-Q1', window: '1', perimeter: 'Prudencial'});
  assert.deepEqual(compare.series.map(series => series.data.map(([date]) => date)), [['2026-03-31'], ['2026-03-31']]);
  assert.equal(compare.series[0].data[0][1], 21.12146195);
  const staleBradesco = {...bradescoHistory, history: bradescoHistory.history.filter(row => row.period < '2026-Q2')};
  const partial = comparisonChart({banks: [itau, bradesco], histories: [itauHistory, staleBradesco], metrics, key: 'assets', period: '2026-Q2', window: '2', perimeter: 'Prudencial'});
  assert.equal(partial.unit, 'R$ bilhões');
  assert.equal(partial.series[1].data.at(-1)[0], '2026-06-30');
  assert.equal(partial.series[1].data.at(-1)[1], null);
  assert.equal(chartOption(partial).series[1].connectNulls, false);
  const otherPerimeter = catalog.institutions.find(bank => bank.perimeter !== itau.perimeter);
  assert.throws(() => comparisonChart({banks: [itau, otherPerimeter], histories: [itauHistory], metrics, key: 'roe', period: '2026-Q2', perimeter: 'Prudencial'}), /mesmo perímetro/);
  assert.throws(() => comparisonChart({banks: [itau, itau], histories: [itauHistory], metrics, key: 'roe', period: '2026-Q2', perimeter: 'Prudencial'}), /distintas/);
  const sourceMissing = comparisonChart({banks: [itau, bradesco], histories: [itauHistory], metrics, key: 'roe', period: '2026-Q2', perimeter: 'Prudencial'});
  assert.deepEqual(sourceMissing.series[1].data, []);
});

test('rank positions are calculated on the common-date perimeter before the search, with observed zeros retained', () => {
  const row = (id, name, value, period = '2026-Q2', perimeter = 'Prudencial') => ({id, name, perimeter, latestPeriod: period, latest: {roe: value}});
  const example = {latestPeriod: '2026-Q2', institutions: [row('a', 'Árvore', 20), row('b', 'Ponte', 0), row('c', 'Céu', null), row('d', 'Passado', 50, '2026-Q1'), row('e', 'Outra entidade', 100, '2026-Q2', 'Individual'), row('f', 'Valor em texto', '10')]};
  assert.deepEqual(institutionRanking(example, {perimeter: 'Prudencial', key: 'roe'}).map(result => [result.bank.id, result.rank]), [['a', 1], ['b', 2]]);
  assert.deepEqual(institutionRanking(example, {perimeter: 'Prudencial', key: 'roe', query: 'ponte'}).map(result => [result.bank.id, result.rank]), [['b', 2]]);
  assert.equal(institutionRanking(example, {perimeter: 'Prudencial', key: 'roe', query: 'arvore'})[0].bank.id, 'a');
  const all = institutionRanking(catalog, {perimeter: 'Prudencial', key: 'roe'});
  const filtered = institutionRanking(catalog, {perimeter: 'Prudencial', key: 'roe', query: 'itau'});
  assert.equal(all.find(result => result.bank.id === itau.id).rank, 135);
  assert.equal(filtered.find(result => result.bank.id === itau.id).rank, 135);
  assert.ok(all.every(result => result.bank.latestPeriod === '2026-Q2'));
});

test('CSV and editable Office chart values preserve displayed monetary scale and convert percentages exactly once', async () => {
  const configs = [chart(['assets'], {window: '1'}), chart(['roe'], {window: '1'}), chart(['expectedLoss'], {window: '1'})];
  near(chartDataForPptx(configs[0])[0].values[0], 2846.41763256291);
  near(chartDataForPptx(configs[1])[0].values[0], .2066501736);
  near(chartDataForPptx(configs[2])[0].values[0], -53.69759559089);
  const originalDocument = globalThis.document, originalCreate = URL.createObjectURL, originalTimeout = globalThis.setTimeout;
  let blob, filename, clicked = false;
  try {
    URL.createObjectURL = value => {blob = value; return 'blob:csv-test';};
    globalThis.document = {createElement: () => ({click() {clicked = true; filename = this.download;}})};
    globalThis.setTimeout = () => 0;
    csvDownload(configs, 'Instituição e recorte');
    assert.equal(clicked, true);
    assert.equal(filename, 'Instituição e recorte.csv');
    const text = await blob.text();
    assert.match(text, /"R\$ bilhões";"BCB \/ IFData · Prudencial"/);
    assert.match(text, /"%";"BCB \/ IFData · Prudencial"/);
    assert.ok(text.includes(`"${2846417632562.91 / 1e9}"`));
    assert.ok(text.includes('"20.66501736"'));
    assert.ok(text.includes(`"${-53697595590.89 / 1e9}"`));
    assert.ok(!text.includes('"0.2066501736"'));
  } finally {
    URL.createObjectURL = originalCreate;
    globalThis.setTimeout = originalTimeout;
    if (originalDocument === undefined) delete globalThis.document; else globalThis.document = originalDocument;
  }
});

test('small plotted amounts remain nonzero in ticks and tooltips while null and true zero remain distinct', () => {
  assert.equal(chartTick(.005), '0,005');
  assert.equal(chartTick(.005, true), '0,005%');
  assert.equal(chartValue(-.00000000000001, 'R$ bilhões'), '-1,00E-14 R$ bilhões');
  assert.equal(chartNumber(null), 'N/D');
  assert.equal(chartNumber(0), '0,00');
  assert.equal(chartNumber(-0), '0,00');
});

test('percentage ticks retain fractional steps above ten without redundant trailing zeroes', () => {
  assert.deepEqual([19, 19.5, 20, 20.5].map(value => chartTick(value, true)), ['19%', '19,5%', '20%', '20,5%']);
  assert.deepEqual([19, 19.5, 20, 20.5].map(value => chartTick(value)), ['19', '19,5', '20', '20,5']);
  assert.equal(chartTick(null, true), 'N/D');
  assert.equal(chartTick(0, true), '0%');
  assert.equal(chartTick(-0, true), '0%');
  assert.equal(chartTick(.00000000000001), '1,00E-14');
});

test('column value labels use the supplied source value and omit units and missing observations', () => {
  assert.equal(chartLabel(12.30870927), '12,3');
  assert.equal(chartLabel(15.3516322), '15,4');
  assert.equal(chartLabel(null), '');
  assert.equal(chartLabel(0), '0,0');
  assert.equal(chartLabel(-2.35), '-2,4');
});

test('capital annotations adapt to plot width and keep the first and last quarters separated from intervening labels', () => {
  const quarters = Array.from({length: 12}, (_, index) => index);
  const labelsAt = width => quarters.filter(index => showInnerLabel(index, quarters.length, width));
  assert.deepEqual(labelsAt(780), quarters);
  assert.deepEqual(labelsAt(300), [0, 2, 4, 6, 8, 11]);
  assert.deepEqual(labelsAt(210), [0, 3, 6, 11]);
  for (const width of [300, 210]) {
    const labels = labelsAt(width);
    assert.equal(labels[0], 0);
    assert.equal(labels.at(-1), 11);
    assert.ok(labels.slice(1).every((index, at) => (index - labels[at]) * width / quarters.length >= 42));
  }
  assert.equal(showInnerLabel(0, 1, 100), true);
  assert.equal(showInnerLabel(0, 0, 100), false);
  assert.equal(showInnerLabel(12, 12, 300), false);
});
