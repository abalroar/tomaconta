import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {
  capitalCompositionChart, institutionChart, institutionExportCharts, trimChartStart,
} from '../src/institution-data.js';

const read = async path => JSON.parse(await readFile(new URL(`../public/${path}`, import.meta.url), 'utf8'));
const catalog = await read('data/institutions.json');
const metrics = catalog.metrics;
const entities = ['5f6d3c0745685d8f', 'f23b21d2312113e3', '5ea409bbd2d66d0f'].map(id => catalog.institutions.find(bank => bank.id === id));
const histories = await Promise.all(entities.map(bank => read(bank.historyPath)));
const options = (index, period, window = '1') => ({bank: entities[index], payload: histories[index], metrics, period, window});
const originalCapital = config => institutionChart({...config, keys: ['cet1', 'basel'], id: 'bank-capital'});
const values = chart => chart.series.map(series => series.data.map(([, value]) => value));

test('real Itaú capital composes CET1 plus the difference to Basel in percentage points without changing source or exports', () => {
  const config = options(0, '2026-Q2');
  const before = structuredClone({bank: config.bank, payload: config.payload, metrics});
  const exported = institutionExportCharts(config);
  const original = originalCapital(config);
  const chart = capitalCompositionChart(config);
  assert.equal(chart.compositionAvailable, true);
  assert.equal(chart.stacked, true);
  assert.equal(chart.unit, '%');
  assert.equal(chart.percent, true);
  assert.deepEqual(chart.series.map(series => [series.name, series.type]), [['CET1', 'bar'], ['Diferença para Basileia', 'bar']]);
  const [principal, difference] = chart.series.map(series => series.data[0][1]);
  assert.equal(principal, 12.30870927);
  assert.equal(difference, 15.3516322 - 12.30870927);
  assert.ok(Math.abs(principal + difference - 15.3516322) < 1e-12);
  assert.deepEqual(chart.totalData, original.series[1].data);
  assert.notEqual(chart.totalData, original.series[1].data);
  assert.deepEqual(chart.valueLabels, {total: true, innerSeries: 0});
  assert.deepEqual({bank: config.bank, payload: config.payload, metrics}, before);
  assert.equal(exported.length, 23);
  assert.deepEqual(institutionExportCharts(config), exported);
  assert.deepEqual(values(original), [[12.30870927], [15.3516322]]);
});

test('observed zero is composable, paired missing values remain gaps and an unpaired value triggers original lines', () => {
  const bank = {id: 'source-example', name: 'Fonte de teste', perimeter: 'Prudencial'};
  const payload = {id: bank.id, perimeter: bank.perimeter, history: [
    {period: '2025-Q2', values: {cet1: null, basel: null}},
    {period: '2025-Q3', values: {cet1: 0, basel: 0}},
    {period: '2025-Q4', values: {cet1: null, basel: null}},
    {period: '2026-Q1', values: {cet1: 5, basel: 7}},
  ]};
  const config = {bank, payload, metrics, period: '2026-Q1', window: 'all'};
  const before = structuredClone(payload);
  const chart = capitalCompositionChart(config);
  assert.equal(chart.compositionAvailable, true);
  assert.deepEqual(values(chart), [[null, 0, null, 5], [null, 0, null, 2]]);
  assert.deepEqual(chart.totalData.map(([, value]) => value), [null, 0, null, 7]);
  const trimmed = trimChartStart(chart);
  assert.deepEqual(trimmed.series[0].data, [['2025-09-30', 0], ['2025-12-31', null], ['2026-03-31', 5]]);
  assert.deepEqual(trimmed.totalData, [['2025-09-30', 0], ['2025-12-31', null], ['2026-03-31', 7]]);
  const incomplete = structuredClone(payload);
  incomplete.history.at(-1).values.cet1 = null;
  const fallback = capitalCompositionChart({...config, payload: incomplete});
  assert.equal(fallback.compositionAvailable, false);
  assert.deepEqual(values(fallback), [[null, 0, null, null], [null, 0, null, 7]]);
  assert.ok(fallback.series.every(series => series.type === 'line'));
  assert.equal(fallback.stacked, undefined);
  assert.deepEqual(payload, before);
});

test('real HARMOS March 2026 keeps its incompatible reported indices unchanged in the fallback', () => {
  const config = options(1, '2026-Q1');
  const before = structuredClone(config.payload);
  const chart = capitalCompositionChart(config);
  assert.equal(config.bank.name, 'HARMOS SCFI - PRUDENCIAL');
  assert.equal(chart.compositionAvailable, false);
  assert.deepEqual(values(chart), [[3342.78459082], [33.42784591]]);
  assert.deepEqual(chart.series, originalCapital(config).series);
  assert.ok(chart.series.every(series => series.type === 'line'));
  assert.match(chart.note, /Composição indisponível/);
  assert.equal(chart.totalData, undefined);
  assert.equal(chart.stacked, undefined);
  assert.equal(chart.unit, '%');
  assert.deepEqual(config.payload, before);
});

test('real SENSO March 2026 preserves both negative indices without a positive or zero substitute', () => {
  const config = options(2, '2026-Q1');
  const before = structuredClone(config.payload);
  const chart = capitalCompositionChart(config);
  assert.equal(config.bank.name, 'SENSO CCVM S.A. - PRUDENCIAL');
  assert.equal(chart.compositionAvailable, false);
  assert.deepEqual(values(chart), [[-60.33295898], [-60.33295898]]);
  assert.deepEqual(chart.series, originalCapital(config).series);
  assert.ok(chart.series.every(series => series.type === 'line'));
  assert.match(chart.note, /índices originais/);
  assert.equal(chart.stacked, undefined);
  assert.deepEqual(config.payload, before);
});

test('trim starts at the first observation across series, counts zero and retains internal and trailing gaps without mutation', () => {
  const dates = ['2025-06-30', '2025-09-30', '2025-12-31', '2026-03-31'];
  const points = entries => entries.map((value, i) => [dates[i], value]);
  const chart = {title: 'Contexto original', unit: '%', series: [
    {name: 'A', data: points([null, 0, null, 2])},
    {name: 'B', data: points([null, null, 3, null])},
  ], totalData: points([null, 0, null, 2])};
  const before = structuredClone(chart);
  const result = trimChartStart(chart);
  assert.equal(result.title, chart.title);
  assert.deepEqual(result.series.map(series => series.data), [points([null, 0, null, 2]).slice(1), points([null, null, 3, null]).slice(1)]);
  assert.deepEqual(result.totalData, chart.totalData.slice(1));
  assert.deepEqual(chart, before);
  const noObservation = {...chart, series: [{name: 'Missing', data: points([null, null, null, null])}], totalData: undefined};
  assert.equal(trimChartStart(noObservation), noObservation);
});
