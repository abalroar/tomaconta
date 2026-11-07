import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {createHash} from 'node:crypto';
import {gzipSync} from 'node:zlib';
import {authenticateRunner, handleShared, OIDC_AUDIENCE, OIDC_WORKFLOW, SHARED_ROOT, validateFiles, validatePlan, validFilePath} from '../server/shared.js';

const origin = 'https://matheusprat.es';
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const encoder = new TextEncoder();
const key = await crypto.subtle.generateKey({name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256'}, true, ['sign', 'verify']);
const publicKey = {...await crypto.subtle.exportKey('jwk', key.publicKey), kid: 'test-key', alg: 'RS256'};
const base64 = value => Buffer.from(value).toString('base64url');

class D1 {
  constructor() {this.sql = new DatabaseSync(':memory:');}
  prepare(query) {
    const db = this.sql;
    return {query, values: [], bind(...values) {this.values = values; return this;},
      async first() {return db.prepare(query).get(...this.values) || null;},
      async all() {return {results: db.prepare(query).all(...this.values)};},
      async run() {const result = db.prepare(query).run(...this.values); return {success: true, meta: {changes: Number(result.changes)}};}};
  }
  async batch(statements) {
    this.sql.exec('BEGIN');
    try {const results = []; for (const statement of statements) results.push(await statement.run()); this.sql.exec('COMMIT'); return results;}
    catch (error) {this.sql.exec('ROLLBACK'); throw error;}
  }
}
class R2 {
  objects = new Map();
  async put(path, input, options = {}) {
    const bytes = typeof input === 'string' ? Buffer.from(input) : Buffer.from(await new Response(input).arrayBuffer());
    if (options.sha256 && sha(bytes) !== options.sha256) throw Error('checksum mismatch');
    this.objects.set(path, bytes); return {size: bytes.length};
  }
  async get(path) {const bytes = this.objects.get(path); return bytes ? {size: bytes.length, body: new Response(bytes).body, text: async () => bytes.toString('utf8')} : null;}
  async head(path) {const bytes = this.objects.get(path); return bytes ? {size: bytes.length} : null;}
}

function setup() {
  let now = 1800000000000;
  const env = {TOMACONTA_DB: new D1(), TOMACONTA_BUCKET: new R2()};
  const options = {clock: () => now, fetcher: async url => {assert.equal(url, 'https://token.actions.githubusercontent.com/.well-known/jwks'); return Response.json({keys: [publicKey]});}};
  async function token(overrides = {}) {
    const header = base64(JSON.stringify({alg: 'RS256', typ: 'JWT', kid: 'test-key'}));
    const claims = base64(JSON.stringify({iss: 'https://token.actions.githubusercontent.com', aud: OIDC_AUDIENCE,
      repository: 'abalroar/tomaconta', repository_id: '1141557164', repository_owner_id: '255978345', ref: 'refs/heads/main', workflow_ref: OIDC_WORKFLOW,
      event_name: 'workflow_dispatch', runner_environment: 'github-hosted', sha: 'a'.repeat(40), workflow_sha: 'a'.repeat(40), run_id: '1234', run_attempt: '1',
      iat: now / 1000 - 5, nbf: now / 1000 - 5, exp: now / 1000 + 300, ...overrides}));
    const signature = await crypto.subtle.sign('RSASSA-PKCS1-v1_5', key.privateKey, encoder.encode(`${header}.${claims}`));
    return `${header}.${claims}.${base64(new Uint8Array(signature))}`;
  }
  async function call(path, {method = 'GET', input, jwt, headers = {}, raw} = {}) {
    const requestHeaders = {Origin: origin, ...headers}; if (jwt) requestHeaders.Authorization = `Bearer ${jwt}`;
    if (input !== undefined) requestHeaders['Content-Type'] = 'application/json';
    return handleShared(new Request(`${origin}${SHARED_ROOT}${path}`, {method, headers: requestHeaders, body: raw ?? (input === undefined ? undefined : JSON.stringify(input))}), env, options);
  }
  return {env, options, token, call, now: () => now, advance: value => {now += value;}};
}

function candidate() {
  const entries = new Map();
  function add(path, value, binary = false) {const bytes = binary ? Buffer.from(value) : Buffer.from(JSON.stringify(value)); entries.set(path, bytes); return {sha256: sha(bytes), size: bytes.length};}
  const source = add('cache/bundled/critical_screens/dados.parquet', 'test-source-bytes', true);
  const geometry = add('web/data/bank-network-ufs.geojson', {type: 'FeatureCollection', features: []});
  add('web/data/bank-network.json', {geometry: {path: 'data/bank-network-ufs.geojson', sha256: geometry.sha256, bytes: geometry.size}});
  const history = {id: 'bank', history: [{period: '2026-Q2', values: {assets: 0}}]};
  add('web/data/institutions/bank.json', history);
  add('web/data/institutions.json', {source: {file: 'data/bundled/critical_screens/dados.parquet', sha256: source.sha256}, institutions: [{historyPath: 'data/institutions/bank.json'}]});
  const input = add('web/data/statements/inputs/individual-00000000.json.gz', gzipSync(Buffer.from('{"id":"individual-00000000","zero":0}')), true);
  const snapshot = add('web/data/statements/individual-00000000.json.gz', gzipSync(Buffer.from('{"table":[],"missing":null}')), true);
  const bridge = add('web/data/statements/engine/bridge.py', 'original_engine = True\n', true);
  add('web/data/statements/engine/manifest.json', {modelVersion: 'statement-v6', bridge: 'bridge.py', modules: [{path: 'bridge.py', sha256: bridge.sha256, size: bridge.size}]});
  add('web/data/statements/index.json', {modelVersion: 'statement-v6', institutions: [{path: 'data/statements/individual-00000000.json.gz', snapshotSha256: snapshot.sha256, snapshotBytes: snapshot.size, inputPath: 'data/statements/inputs/individual-00000000.json.gz', inputSha256: input.sha256, inputBytes: input.size}], sources: {critical_screens: {filename: 'critical_screens/dados.parquet', sha256: source.sha256}}, crosswalkPath: 'data/statements/crosswalk.json'});
  add('web/data/statements/crosswalk.json', {sources: {critical_screens: {filename: 'critical_screens/dados.parquet', sha256: source.sha256}}});
  const housing = Array.from({length: 24}, (_, index) => ({id: `chart-${index}`, title: `Chart ${index}`, series: [{data: [['2026-06-30', index === 0 ? null : 0]]}]}));
  const ufs = 'br ac al ap am ba ce df es go ma mt ms mg pa pb pr pe pi rj rn rs ro rr sc sp se to'.split(' ');
  for (const uf of ufs) add(`web/data/imob-${uf}.json`, housing);
  add('web/data/imob-catalog.json', housing.map(chart => ({id: chart.id})));
  add('web/data/sfn.json', [{id: 'sfn'}]); add('web/data/extra.json', [{id: 'spb'}]);
  add('web/data/manifest.json', {ufs, chartCount: 26});
  const files = [...entries].map(([path, bytes]) => ({path, sha256: sha(bytes), size: bytes.length, encoding: 'identity'}));
  const summary = {validation: {complete: true, failures: 0}, generation: {sourceCommit: 'a'.repeat(40), modelVersion: 'statement-v6', sourceFiles: [{path: 'cache/bundled/critical_screens/dados.parquet', ...source}]}, coverage: {charts: 26, institutions: 1}};
  return {entries, files, summary};
}

async function seed(fixture, jwt) {
  assert.equal((await fixture.call('/runner/seed', {method: 'POST', jwt, input: {kind: 'bootstrap'}})).status, 201);
  const response = await fixture.call('/runner/claim', {method: 'POST', jwt}); assert.equal(response.status, 200); return (await response.json()).job;
}
async function upload(fixture, job, data, jwt) {
  const uploaded = new Set();
  for (const file of data.files) {
    if (uploaded.has(file.sha256)) continue; uploaded.add(file.sha256);
    const response = await fixture.call(`/runner/blobs/${file.sha256}?job=${job.id}`, {method: 'PUT', jwt, raw: data.entries.get(file.path), headers: {'X-Lease-Id': job.lease_id, 'Content-Length': String(file.size)}});
    assert.equal(response.status, 201, await response.text());
  }
}
async function publishInitial(fixture) {
  const jwt = await fixture.token(), job = await seed(fixture, jwt), data = candidate(); await upload(fixture, job, data, jwt);
  const response = await fixture.call(`/runner/jobs/${job.id}/prepare`, {method: 'POST', jwt, input: {lease: job.lease_id, parent: null, files: data.files, summary: data.summary}});
  assert.equal(response.status, 201, await response.clone().text()); const {revision} = await response.json();
  const published = await fixture.call(`/runner/jobs/${job.id}/publish`, {method: 'POST', jwt, input: {lease: job.lease_id, revision}}); assert.equal(published.status, 200, await published.text());
  return {jwt, job, data, revision};
}

test('plans whitelist source/mode/window and archive paths without accepting public account reclassification', () => {
  assert.deepEqual(validatePlan({kind: 'mercado_imobiliario', start: '2025-01', end: '2026-12'}), {kind: 'mercado_imobiliario', mode: 'incremental', start: '2025-01', end: '2026-12'});
  assert.deepEqual(validatePlan({kind: 'financeiro'}), {kind: 'financeiro', mode: 'incremental'});
  assert.deepEqual(validatePlan({kind: 'rede_agencias'}), {kind: 'rede_agencias', mode: 'incremental'});
  for (const fields of [{period: '2026-06'}, {start: '2026-01', end: '2026-06'}, {uf: 'sp'}]) assert.throws(() => validatePlan({kind: 'rede_agencias', ...fields}), /cadastro atual/);
  assert.throws(() => validatePlan({kind: 'financeiro', decisions: {account: 'ignored'}}), /Campo/);
  assert.throws(() => validatePlan({kind: 'financeiro', mode: 'rebuild'}), /Modo/);
  assert.throws(() => validatePlan({kind: 'individual', period: '2026-02'}), /trimestre/);
  assert.throws(() => validatePlan({kind: 'mercado_imobiliario', start: '2024-12', end: '2026-12'}), /24 meses/);
  for (const path of ['web/data/statements/inputs/individual-00000000.json.gz', 'web/data/statements/engine/bridge.py', 'web/data/bank-network-ufs.geojson']) assert.equal(validFilePath(path), true);
  for (const path of ['web/data/../secret.json', 'web/data/script.js', 'cache/runtime/anything.bin', 'web/data/%2e%2e/a.json']) assert.equal(validFilePath(path), false);
  const file = `cache/runtime/financial_analysis_sources/aa/${'a'.repeat(64)}.bin`; assert.equal(validFilePath(file), true);
  const data = candidate(); assert.equal(validateFiles(data.files).size, data.files.length);
  assert.throws(() => validateFiles(data.files.map(file => file.path.endsWith('.gz') ? {...file, encoding: 'gzip'} : file)), /encoding identity/);
});

test('OIDC accepts only signed exact workflow/repository/main/audience and expires independently of leases', async () => {
  const fixture = setup(); const jwt = await fixture.token();
  const auth = token => authenticateRunner(new Request(origin, {headers: {Authorization: `Bearer ${token}`}}), {fetcher: fixture.options.fetcher, now: fixture.now()});
  assert.equal((await auth(jwt)).id, '1234:1');
  for (const overrides of [{repository_id: '999'}, {repository_owner_id: '999'}, {ref: 'refs/pull/1/merge'}, {aud: 'wrong'}, {workflow_ref: OIDC_WORKFLOW.replace('tomaconta-shared', 'other')}, {event_name: 'pull_request'}, {runner_environment: 'self-hosted'}, {exp: fixture.now() / 1000 - 1}]) await assert.rejects(auth(await fixture.token(overrides)), /autorizado/);
  const parts = jwt.split('.'); parts[1] = base64(JSON.stringify({ref: 'refs/heads/main'}));
  await assert.rejects(auth(parts.join('.')), /Assinatura/);
});

test('unconfigured financial bindings retain static mode and never touch photo storage', async () => {
  const env = {PHOTOS_DB: {prepare() {throw Error('photo binding touched');}}, PHOTOS_BUCKET: {get() {throw Error('photo bucket touched');}}};
  const response = await handleShared(new Request(`${origin}${SHARED_ROOT}/current`), env);
  assert.deepEqual(await response.json(), {revision: null, builtIn: true, configured: false});
  assert.equal((await handleShared(new Request(`${origin}${SHARED_ROOT}/jobs`, {method: 'POST'}), env)).status, 503);
});

test('bootstrap prepares complete immutable bytes and only publication changes the shared pointer', async () => {
  const fixture = setup(), jwt = await fixture.token(), job = await seed(fixture, jwt), data = candidate();
  assert.equal((await (await fixture.call('/current')).json()).revision, null);
  await upload(fixture, job, data, jwt);
  const prepared = await fixture.call(`/runner/jobs/${job.id}/prepare`, {method: 'POST', jwt, input: {lease: job.lease_id, parent: null, files: data.files, summary: data.summary}});
  assert.equal(prepared.status, 201, await prepared.clone().text()); const {revision} = await prepared.json();
  const retried = await fixture.call(`/runner/jobs/${job.id}/prepare`, {method: 'POST', jwt, input: {lease: job.lease_id, parent: null, files: data.files, summary: data.summary}});
  assert.deepEqual(await retried.json(), {revision, reused: true});
  const conflictingSummary = {...data.summary, coverage: {charts: 26, institutions: 2}};
  const conflicted = await fixture.call(`/runner/jobs/${job.id}/prepare`, {method: 'POST', jwt, input: {lease: job.lease_id, parent: null, files: data.files, summary: conflictingSummary}});
  assert.equal(conflicted.status, 409);
  assert.equal(fixture.env.TOMACONTA_DB.sql.prepare('SELECT COUNT(*) AS n FROM tc_revisions WHERE job_id=?').get(job.id).n, 1);
  assert.equal((await (await fixture.call('/current')).json()).revision, null);
  assert.equal((await fixture.call(`/data/${revision}/manifest.json`)).status, 404);
  const published = await fixture.call(`/runner/jobs/${job.id}/publish`, {method: 'POST', jwt, input: {lease: job.lease_id, revision}});
  assert.equal(published.status, 200);
  const current = await (await fixture.call('/current')).json(); assert.equal(current.revision, revision); assert.equal(current.builtIn, false);
  const compressed = await fixture.call(`/data/${revision}/statements/inputs/individual-00000000.json.gz`);
  assert.equal(compressed.headers.get('Content-Encoding'), null);
  assert.deepEqual(Buffer.from(await compressed.arrayBuffer()), data.entries.get('web/data/statements/inputs/individual-00000000.json.gz'));
  const repeated = await fixture.call(`/runner/jobs/${job.id}/publish`, {method: 'POST', jwt, input: {lease: job.lease_id, revision}}); assert.equal((await repeated.json()).alreadyPublished, true);
});

test('bad bytes or missing source/geometry dependencies cannot prepare or replace the prior generation', async () => {
  const fixture = setup(); const initial = await publishInitial(fixture);
  const created = await fixture.call('/jobs', {method: 'POST', input: {kind: 'mercado_imobiliario'}, headers: {'Idempotency-Key': 'b'.repeat(32)}}); assert.equal(created.status, 201);
  const {job} = await (await fixture.call('/runner/claim', {method: 'POST', jwt: initial.jwt})).json();
  const corrupt = Buffer.from('corrupt');
  const bad = await fixture.call(`/runner/blobs/${'f'.repeat(64)}?job=${job.id}`, {method: 'PUT', jwt: initial.jwt, raw: corrupt, headers: {'X-Lease-Id': job.lease_id, 'Content-Length': String(corrupt.length)}}); assert.equal(bad.status, 400);
  const missing = initial.data.files.filter(file => !file.path.endsWith('.geojson'));
  assert.equal((await fixture.call(`/runner/jobs/${job.id}/prepare`, {method: 'POST', jwt: initial.jwt, input: {lease: job.lease_id, parent: initial.revision, files: missing, summary: initial.data.summary}})).status, 400);
  const wrong = structuredClone(initial.data.summary); wrong.generation.sourceFiles[0].sha256 = 'f'.repeat(64);
  assert.equal((await fixture.call(`/runner/jobs/${job.id}/prepare`, {method: 'POST', jwt: initial.jwt, input: {lease: job.lease_id, parent: initial.revision, files: initial.data.files, summary: wrong}})).status, 400);
  const unrelatedCommit = structuredClone(initial.data.summary); unrelatedCommit.generation.sourceCommit = 'b'.repeat(40);
  assert.equal((await fixture.call(`/runner/jobs/${job.id}/prepare`, {method: 'POST', jwt: initial.jwt, input: {lease: job.lease_id, parent: initial.revision, files: initial.data.files, summary: unrelatedCommit}})).status, 400);
  assert.equal((await (await fixture.call('/current')).json()).revision, initial.revision);
});

test('public jobs require same-origin and initial import and restore require an explicit manual executor', async () => {
  const fixture = setup(), scheduled = await fixture.token({event_name: 'schedule'});
  const seedResponse = await fixture.call('/runner/seed', {method: 'POST', jwt: scheduled, input: {kind: 'bootstrap'}});
  assert.equal(seedResponse.status, 403);
  const beforeSeed = await fixture.call('/jobs', {method: 'POST', input: {kind: 'financeiro'}, headers: {'Idempotency-Key': 'b'.repeat(32)}});
  assert.equal(beforeSeed.status, 503);
  const initial = await publishInitial(fixture);
  const crossOrigin = await fixture.call('/jobs', {method: 'POST', input: {kind: 'financeiro'}, headers: {Origin: 'https://other.example', 'Idempotency-Key': 'b'.repeat(32)}});
  assert.equal(crossOrigin.status, 403);
  const restore = await fixture.call('/runner/restore', {method: 'POST', jwt: scheduled, input: {revision: initial.revision, expectedCurrent: initial.revision}});
  assert.equal(restore.status, 403);
  assert.equal((await (await fixture.call('/current')).json()).revision, initial.revision);
});

test('public requests deduplicate and bound queue activity while lease ownership fences different runs', async () => {
  const fixture = setup(); const initial = await publishInitial(fixture);
  const submit = (kind, key, params = {}) => fixture.call('/jobs', {method: 'POST', input: {kind, ...params}, headers: {'Idempotency-Key': key.repeat(32)}});
  const created = await submit('mercado_imobiliario', 'b'); const first = (await created.json()).job; assert.equal(created.status, 201);
  const repeated = await submit('mercado_imobiliario', 'c'); assert.equal(repeated.status, 200); assert.equal((await repeated.json()).job.id, first.id);
  assert.equal((await submit('mercado_imobiliario', 'b', {mode: 'overwrite'})).status, 409);
  const {job} = await (await fixture.call('/runner/claim', {method: 'POST', jwt: initial.jwt})).json();
  const otherRun = await fixture.token({run_id: '9999'});
  assert.equal((await fixture.call(`/runner/jobs/${job.id}/heartbeat`, {method: 'POST', jwt: otherRun, input: {lease: job.lease_id, progress: .5}})).status, 409);
  fixture.advance(181000); const renewed = await fixture.token();
  const {job: resumed} = await (await fixture.call('/runner/claim', {method: 'POST', jwt: renewed})).json();
  assert.notEqual(resumed.lease_id, job.lease_id); assert.equal(resumed.base_revision, initial.revision);
  assert.equal((await fixture.call(`/runner/jobs/${job.id}/heartbeat`, {method: 'POST', jwt: renewed, input: {lease: job.lease_id, progress: .5}})).status, 409);
  const status = await (await fixture.call(`/jobs/${job.id}`)).json();
  for (const privateKey of ['lease_id', 'runner_id', 'request_key', 'subject']) assert.equal(privateKey in status.job, false);
  assert.equal((await submit('financeiro', 'd')).status, 201); assert.equal((await submit('individual', 'e')).status, 201); assert.equal((await submit('mercado_credito_sgs', 'f')).status, 201);
  assert.equal((await submit('scr_data', '1')).status, 429);
});

test('a newer active generation prevents publishing a candidate prepared from an older one', async () => {
  const fixture = setup(); const initial = await publishInitial(fixture);
  await fixture.call('/jobs', {method: 'POST', input: {kind: 'financeiro'}, headers: {'Idempotency-Key': 'b'.repeat(32)}});
  const {job} = await (await fixture.call('/runner/claim', {method: 'POST', jwt: initial.jwt})).json();
  const response = await fixture.call(`/runner/jobs/${job.id}/prepare`, {method: 'POST', jwt: initial.jwt, input: {lease: job.lease_id, parent: initial.revision, files: initial.data.files, summary: initial.data.summary}});
  assert.equal(response.status, 201, await response.clone().text()); const {revision} = await response.json();
  const newer = 'c'.repeat(32); fixture.env.TOMACONTA_DB.sql.prepare('UPDATE tc_state SET current_revision=? WHERE id=1').run(newer);
  const publish = await fixture.call(`/runner/jobs/${job.id}/publish`, {method: 'POST', jwt: initial.jwt, input: {lease: job.lease_id, revision}}); assert.equal(publish.status, 409);
  assert.equal(fixture.env.TOMACONTA_DB.sql.prepare('SELECT current_revision FROM tc_state WHERE id=1').get().current_revision, newer);
  assert.equal(fixture.env.TOMACONTA_DB.sql.prepare('SELECT published_at FROM tc_revisions WHERE id=?').get(revision).published_at, null);
});
