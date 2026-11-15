import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {competenceLabel, defaultInterval, latestChartPeriod, seriesCollections, seriesSections} from '../src/series-data.js';
import {publicationStatus, publishedSources, sgsChart} from '../src/update-data.js';

const read = async name => JSON.parse(await readFile(new URL(`../public/data/${name}`, import.meta.url), 'utf8'));

test('section collections retain every source chart and the complete SFN export composition', async () => {
  const [manifest, sfn, extra, imob] = await Promise.all(['manifest.json', 'sfn.json', 'extra.json', 'imob-br.json'].map(read));
  const original = JSON.stringify({sfn, extra, imob});
  const all = seriesCollections({sfn, extra, imob, window: 'all'});
  const scr = extra.filter(chart => chart.section.startsWith('SCR'));
  assert.deepEqual(all.sfn, [...sfn, ...scr]);
  assert.deepEqual(all.payments, extra.filter(chart => !chart.section.startsWith('SCR')));
  assert.deepEqual(all.imob, imob);
  assert.deepEqual(all.all, [...sfn, ...scr, ...imob]);
  assert.equal(all.all.length + all.payments.length, manifest.chartCount);
  assert.deepEqual(seriesSections(manifest, extra), [...new Set([...manifest.sfnSections, ...scr.map(chart => chart.section)])]);
  const filtered = seriesCollections({sfn, extra, imob, window: '12'});
  assert.deepEqual(filtered.all.map(chart => chart.id), all.all.map(chart => chart.id));
  assert.equal(JSON.stringify({sfn, extra, imob}), original);
  assert.equal(filtered.imob.length, 24);
  assert.ok(!filtered.imob.some(chart => /bndu/i.test(chart.id + chart.title)));
  assert.ok(filtered.imob.filter(chart => chart.historical).every(chart => chart.series.every(series => series.data.every(([date]) => date <= '2024-12-31'))));
});

test('source competence labels preserve quarterly, monthly and missing identities', () => {
  assert.equal(competenceLabel('2026-Q2'), 'jun/2026');
  assert.equal(competenceLabel('202606'), 'jun/2026');
  assert.equal(competenceLabel('2026-08-31T00:00:00Z'), 'ago/2026');
  assert.equal(competenceLabel(null), 'N/D');
  const charts = [{series: [{data: [['2026-09-01', 0], ['2026-10-01', null]]}]}];
  assert.equal(latestChartPeriod(charts), '2026-09');
  assert.deepEqual(defaultInterval(charts), {start: '2025-10', end: '2026-09'});
});

test('live SGS data preserve source scale, zero and negative observations', () => {
  const spec = {code: 4392, name: 'Taxa CDI', unit: 'pct_year'};
  const input = [{data: '31/01/2026', valor: '12.3'}, {data: '28/02/2026', valor: '0'}, {data: '31/03/2026', valor: '-0.5'}];
  const chart = sgsChart(spec, input);
  assert.equal(chart.unit, '% a.a.');
  assert.equal(chart.percent, true);
  assert.equal(chart.source, 'BCB · SGS 4392');
  assert.deepEqual(chart.series[0].data, [['2026-01-31', 12.3], ['2026-02-28', 0], ['2026-03-31', -.5]]);
  assert.throws(() => sgsChart(spec, []), /não retornou observações/);
  for (const value of [null, '', 'abc']) assert.throws(() => sgsChart(spec, [{data: '31/01/2026', valor: value}]), /inválida/);
  assert.throws(() => sgsChart(spec, [{data: '31/02/2026', valor: '12.3'}]), /competência inválida/);
});

test('published source table keeps individual and prudential statement coverage separate', () => {
  const manifest = {sources: [{id: 'imob', name: 'Mercado Imobiliário', provider: 'BCB · Olinda', period: '2026-08', rows: 100}]};
  const catalog = {latestPeriod: '2026-Q2', institutions: [{id: 'bank'}]};
  const statementIndex = {institutions: [
    {scope: 'individual', periods: ['202512', '202606']},
    {scope: 'individual', periods: ['202603']},
    {scope: 'prudential', periods: ['202512']},
  ]};
  const rows = publishedSources(manifest, catalog, statementIndex);
  assert.equal(rows[0].period, '2026-Q2');
  assert.equal(rows.find(row => row.id === 'statements-individual').count, 2);
  assert.equal(rows.find(row => row.id === 'statements-individual').period, '202606');
  assert.equal(rows.find(row => row.id === 'statements-prudential').count, 1);
  assert.equal(rows.find(row => row.id === 'statements-prudential').period, '202512');
  assert.equal(rows.at(-1).count, 100);
  assert.equal(publicationStatus([{data: '31/10/2026'}], {value: [{Data: '2026-08-31'}]}), 'Publicações consultadas: SGS 31/10/2026 · Mercado imobiliário ago/2026.');
  assert.throws(() => publicationStatus([], {value: []}), /duas competências/);
});
