import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {gunzipSync} from 'node:zlib';
import {
  preferredStatement, selectedStatementPeriods, statementFileName,
  statementPeriodLabel, statementSearchCatalog, validateStatementPacket,
} from '../src/statement-data.js';

const publicRoot = new URL('../public/', import.meta.url);
const repositoryRoot = new URL('../../', import.meta.url);
const plain = async path => JSON.parse(await readFile(new URL(path, publicRoot), 'utf8'));
const compressed = async path => JSON.parse(gunzipSync(await readFile(new URL(path, publicRoot))));
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const [index, crosswalk, catalog, manifest] = await Promise.all([
  'data/statements/index.json', 'data/statements/crosswalk.json',
  'data/institutions.json', 'data/statements/engine/manifest.json',
].map(plain));
const byId = new Map(index.institutions.map(entity => [entity.id, entity]));
const bank = catalog.institutions.find(entity => entity.id === '5f6d3c0745685d8f');
const prudential = byId.get('prudential-C0080099');
const individual = byId.get('individual-60701190');
const amount = (packet, table, row, period = '202606') => packet.tables.find(t => t.name === table).rows.find(r => r.id === row).cells[period].amount.value;
const close = (actual, expected, tolerance, label) => assert.ok(Math.abs(actual - expected) <= tolerance, `${label}: ${actual} versus ${expected}`);

test('published statement index fixes historical coverage and exact official identities', () => {
  assert.equal(index.schemaVersion, 2);
  assert.equal(index.coverage, 'all-source-identities');
  assert.deepEqual(index.selection, {scopes: ['individual', 'prudential'], codes: null});
  assert.equal(index.institutions.length, 2143);
  assert.equal(byId.size, 2143);
  assert.deepEqual(index.counts, {individual: 1938, prudential: 205});
  assert.deepEqual(index.transport, {encoding: 'gzip', deterministic: true, mtime: 0});
  assert.equal(index.modelVersion, manifest.modelVersion);
  assert.equal(index.unit, 'R$ milhões');
  assert.equal(index.percentUnit, 'fraction');
  for (const [scope, expected] of Object.entries({individual: [1938, 1771, 14], prudential: [205, 168, 34]})) {
    const entities = index.institutions.filter(entity => entity.scope === scope);
    assert.equal(entities.length, expected[0]);
    assert.equal(entities.filter(entity => entity.latestPeriod === '202606').length, expected[1]);
    assert.equal(new Set(entities.flatMap(entity => entity.periods)).size, expected[2]);
  }
});

test('all 4286 indexed gzip assets retain bytes, SHA-256, identity, coverage and model context', async () => {
  // Deliberately serial: inflated JSON totals about 874 MB, but no catalog of
  // parsed packets is retained. A failed file reports its official identity.
  let checked = 0;
  const errors = [];
  for (const entity of index.institutions) {
    for (const kind of ['snapshot', 'input']) {
      const isInput = kind === 'input';
      const path = entity[isInput ? 'inputPath' : 'path'];
      const expectedPath = `data/statements/${isInput ? 'inputs/' : ''}${entity.id}.json.gz`;
      const bytes = await readFile(new URL(path, publicRoot));
      const prefix = `${entity.id}/${kind}`;
      const check = (condition, detail) => {if (!condition) errors.push(`${prefix}: ${detail}`);};
      check(path === expectedPath, 'canonical asset path');
      check(entity.id === `${entity.scope}-${entity.code}`, 'scope/code identity');
      check(bytes.length === entity[isInput ? 'inputBytes' : 'snapshotBytes'], 'compressed byte size');
      check(hash(bytes) === entity[isInput ? 'inputSha256' : 'snapshotSha256'], 'SHA-256');
      check(bytes[0] === 0x1f && bytes[1] === 0x8b && bytes.readUInt32LE(4) === 0, 'gzip header/mtime');
      const packet = JSON.parse(gunzipSync(bytes));
      check(packet.schemaVersion === 2 && packet.modelVersion === index.modelVersion, 'schema/model version');
      check(packet.id === entity.id && packet.scope === entity.scope && packet.code === entity.code, 'packet identity');
      const source = index.sources[entity.scope === 'individual' ? 'balancete_individual' : 'bloprudencial'];
      check(packet.source.sha256 === source.sha256 && packet.source.filename === source.filename, 'source provenance');
      if (isInput) {
        check(equal(packet.periods, entity.periods), 'full input coverage');
        check(packet.cosif.constants.COD_CONGL === entity.code, 'COSIF source identity');
      } else {
        check(equal(packet.periods, entity.defaultPeriods) && equal(packet.defaultPeriods, entity.defaultPeriods), 'default selection');
        check(equal(packet.availablePeriods, entity.periods), 'available periods');
        check(packet.inputPath === entity.inputPath && packet.filename, 'input/filename');
        check(packet.unit === 'R$ milhões' && packet.percentUnit === 'fraction', 'financial units');
        check(Array.isArray(packet.tables) && packet.tables.length === 3, 'statement tables');
        check(packet.tables.every(table => table.rows.every(row => equal(Object.keys(row.cells), entity.defaultPeriods))), 'cell period context');
        check(!('native' in packet), 'no default Office download bypass');
      }
      checked++;
    }
  }
  assert.equal(checked, 4286);
  assert.deepEqual(errors, []);
});

test('published engine hashes match every original module and the portable bridge source', async () => {
  assert.equal(index.enginePath, 'data/statements/engine/manifest.json');
  assert.equal(manifest.pyodide.version, '0.29.3');
  assert.deepEqual(manifest.packages.pip, ['XlsxWriter==3.2.9', 'python-pptx==0.6.23']);
  assert.equal(manifest.modules.length, 9);
  for (const module of manifest.modules) {
    const published = await readFile(new URL(`data/statements/engine/${module.path}`, publicRoot));
    const originalPath = module.path === 'bridge.py' ? 'web/tools/statements_bridge.py' : module.path;
    const original = await readFile(new URL(originalPath, repositoryRoot));
    assert.equal(published.length, module.size, module.path);
    assert.equal(hash(published), module.sha256, module.path);
    assert.deepEqual(published, original, module.path);
  }
  const bridge = await readFile(new URL('web/tools/statements_bridge.py', repositoryRoot), 'utf8');
  assert.ok(bridge.includes(`MODEL_VERSION = "${index.modelVersion}"`));
});

test('crosswalk preserves exact official prudential scope without name or individual substitution', () => {
  assert.equal(Object.keys(crosswalk.links).length, 176);
  assert.deepEqual(crosswalk.ambiguousAnalysisIds, []);
  for (const [analysisId, link] of Object.entries(crosswalk.links)) {
    const entity = byId.get(link.statementId);
    assert.ok(catalog.institutions.some(bank => bank.id === analysisId));
    assert.equal(entity.scope, 'prudential');
    assert.equal(entity.code, link.code);
    assert.equal(entity.scope, link.scope);
    assert.ok(entity.periods.includes(link.effectivePeriod));
  }
  assert.equal(preferredStatement(index, bank, crosswalk), prudential);
  assert.equal(preferredStatement(index, bank, {links: {}}), prudential);
  assert.equal(preferredStatement(index, {id: 'unmatched', name: bank.name, perimeter: 'Prudencial'}, crosswalk), null);
  assert.equal(preferredStatement(index, {id: '60701190', name: individual.name, perimeter: 'Individual'}, crosswalk), null);
  const choices = statementSearchCatalog(index, 'individual').institutions;
  assert.equal(choices.length, 1938);
  assert.ok(choices.every(entity => entity.scope === 'individual' && entity.perimeter.startsWith('Individual · CNPJ-base ')));
  assert.equal(choices.find(entity => entity.code === '60701190').id, individual.id);
});

test('Itaú prudential balances reconcile to published IF.data with explicit scales and asset residue', async () => {
  const packet = await compressed(prudential.path);
  assert.equal(bank.latestPeriod, '2026-Q2');
  assert.equal(catalog.metrics.assets.unit, 'R$');
  assert.equal(catalog.metrics.cet1.unit, '%');
  // COSIF assets retain a R$105.56 residual versus the curated IF.data figure.
  close(amount(packet, 'Balanço', 'assets') * 1e6 - bank.latest.assets, 105.56, .02, 'COSIF/IF.data asset residue (R$)');
  close(amount(packet, 'Balanço', 'equity') * 1e6, bank.latest.equity, .01, 'equity (R$)');
  close(amount(packet, 'DRE', 'net') * 1e6, bank.latest.profitYtd, .01, 'YTD net profit (R$)');
  close(amount(packet, 'Balanço', 'cet1') * 100, bank.latest.cet1, 1e-8, 'CET1 percentage points');
  close(amount(packet, 'Balanço', 'basel') * 100, bank.latest.basel, 1e-8, 'Basel percentage points');
});

test('Itaú individual reconciles only to its own CNPJ-base sources and leaves prudential capital unavailable', async () => {
  const [packet, input] = await Promise.all([compressed(individual.path), compressed(individual.inputPath)]);
  const source = input.ifdata.principal;
  const records = source.data.map(values => ({...source.constants, ...Object.fromEntries(source.columns.map((column, i) => [column, values[i]]))}));
  const principal = records.find(row => row['Período'] === '2/2026');
  assert.equal(packet.scope, 'individual');
  assert.equal(packet.cnpjBase, '60701190');
  assert.equal(principal.CodInst, '60701190');
  close(amount(packet, 'Balanço', 'assets') * 1e6, principal['Ativo Total'], .01, 'individual assets (R$)');
  close(amount(packet, 'Balanço', 'equity') * 1e6, principal['Patrimônio Líquido'], .01, 'individual equity (R$)');
  close(amount(packet, 'DRE', 'net') * 1e6, principal['Lucro Líquido Acumulado YTD'], .01, 'individual YTD profit (R$)');
  assert.equal(amount(packet, 'Balanço', 'cet1'), null);
  assert.equal(amount(packet, 'Balanço', 'basel'), null);
  const zero = packet.tables.find(table => table.name === 'DRE').rows.find(row => row.id === 'other_close').cells['202509'].amount;
  assert.deepEqual([zero.value, zero.state, zero.display], [0, 'value', '0']);
  assert.notEqual(amount(packet, 'Balanço', 'assets'), bank.latest.assets / 1e6);
});

test('selection helpers retain 1–8 periods and reject a default snapshot for another context', async () => {
  const snapshot = await compressed(prudential.path);
  const eight = prudential.periods.slice(0, 8).reverse();
  assert.deepEqual(selectedStatementPeriods(prudential, eight), [...eight].sort());
  assert.deepEqual(selectedStatementPeriods(prudential, ['202606']), ['202606']);
  for (const invalid of [null, [], ['202606', '202606'], ['201512'], prudential.periods.slice(0, 9)]) {
    assert.deepEqual(selectedStatementPeriods(prudential, invalid), prudential.defaultPeriods);
  }
  assert.equal(validateStatementPacket(prudential, prudential.defaultPeriods, snapshot), snapshot);
  assert.throws(() => validateStatementPacket(prudential, ['202606'], snapshot), /perímetro/);
  assert.throws(() => validateStatementPacket(individual, prudential.defaultPeriods, snapshot), /perímetro/);
  assert.throws(() => validateStatementPacket(prudential, prudential.defaultPeriods, {...snapshot, percentUnit: '%'}), /perímetro/);
  assert.equal(statementFileName(snapshot, prudential, prudential.defaultPeriods, 'xlsx'), `${snapshot.filename}.xlsx`);
  assert.equal(statementFileName(null, prudential, ['202512', '202606'], 'pptx'), 'C0080099_Analise_Financeira_202512_a_202606.pptx');
  assert.equal(statementPeriodLabel('202606'), 'jun/26');
  assert.equal(statementPeriodLabel('202606', true), 'jun/2026');
});
