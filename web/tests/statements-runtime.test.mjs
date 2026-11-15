import test from 'node:test';
import assert from 'node:assert/strict';
import {createStatementRuntime, statementSelection} from '../src/statements-runtime.js';
import {decodeStatementBytes} from '../src/statements-worker.js';
import {gzipSync} from 'node:zlib';
import {datasetRoot,pinDataRevision} from '../src/data.js';

const itau = {id: 'prudential-C0080099', scope: 'prudential', code: 'C0080099', periods: ['202512', '202603', '202606'], inputPath: 'data/statements/inputs/prudential-C0080099.json'};
const individual = {id: 'individual-60701190', scope: 'individual', code: '60701190', periods: ['202512', '202603', '202606']};

function fixture(t, options = {}) {
  const instances = [];
  class Worker {
    constructor(url, config) {this.url = url; this.config = config; this.events = new Map(); this.messages = []; this.terminated = false; instances.push(this);}
    addEventListener(type, listener) {this.events.set(type, listener);}
    postMessage(message) {this.messages.push(message);}
    terminate() {this.terminated = true;}
    emit(data) {this.events.get('message')({data});}
    fail() {this.events.get('error')({preventDefault() {}});}
  }
  const runtime = createStatementRuntime({WorkerClass: Worker, dataBase: 'http://localhost/data/', timeoutMs: 5000, ...options});
  t.after(() => runtime.reset());
  return {runtime, instances};
}

const context = request => ({entityId: request.entity.id, periods: request.periods, operation: request.type, format: request.format || null,dataBase:request.dataBase});
function complete(worker, request, extra = {}) {worker.emit({type: 'result', id: request.id, context: context(request), packet: {id: request.entity.id, periods: request.periods, tables: []}, ...extra});}

test('Python worker stays lazy; selection is sorted without changing the source and preserves identity', async t => {
  const {runtime, instances} = fixture(t);
  assert.equal(instances.length, 0);
  const periods = ['202606', '202512'];
  const statuses = [];
  const result = runtime.prepare(itau, periods, value => statuses.push(value));
  assert.deepEqual(periods, ['202606', '202512']);
  assert.equal(instances.length, 1);
  assert.equal(instances[0].config.type, 'module');
  const request = instances[0].messages[0];
  assert.deepEqual(request.periods, ['202512', '202606']);
  assert.equal(request.dataBase, 'http://localhost/data/');
  instances[0].emit({type: 'status', id: request.id, context: context(request), message: 'Carregando dados da instituição…'});
  const packet = {id: itau.id, periods: request.periods, tables: [{values: [null, 0, -12]}]};
  complete(instances[0], request, {packet});
  assert.deepEqual(await result, packet);
  assert.ok(statuses.includes('Carregando dados da instituição…'));
});

test('invalid IDs, ambiguous scopes, forged paths and unavailable periods fail before starting Python', async t => {
  const {runtime, instances} = fixture(t);
  for (const [entity, periods] of [
    [{...itau, id: individual.id}, ['202606']],
    [{...individual, code: '6070119'}, ['202606']],
    [{...itau, scope: 'financial'}, ['202606']],
    [{...itau, inputPath: 'https://example.com/dados.json'}, ['202606']],
    [itau, ['202606', '202606']], [itau, ['202613']], [itau, ['202409']],
    [itau, []], [itau, Array.from({length: 9}, (_, i) => `2025${String(i + 1).padStart(2, '0')}`)],
  ]) await assert.rejects(runtime.prepare(entity, periods));
  assert.equal(instances.length, 0);
});

test('simultaneous institutions cannot consume one another’s results', async t => {
  const {runtime, instances} = fixture(t);
  const first = runtime.prepare(itau, ['202606']);
  const second = runtime.prepare(individual, ['202603']);
  const worker = instances[0], [a, b] = worker.messages;
  complete(worker, b);
  complete(worker, a);
  assert.equal((await first).id, itau.id);
  assert.equal((await second).id, individual.id);
});

test('responses must match entity, period, operation and export format', async t => {
  const {runtime, instances} = fixture(t);
  for (const changed of [{entityId: individual.id}, {periods: ['202603']}, {operation: 'export'}, {format: 'pptx'},{dataBase:'http://localhost/api/shared/data/'+'a'.repeat(32)+'/'}]) {
    const result = runtime.prepare(itau, ['202606']);
    const worker = instances[0], request = worker.messages.at(-1);
    worker.emit({type: 'result', id: request.id, context: {...context(request), ...changed}, packet: {id: itau.id, periods: ['202606']}});
    await assert.rejects(result, /outro recorte/);
  }
});

test('packet identity is independently checked after the matching envelope', async t => {
  const {runtime, instances} = fixture(t);
  const result = runtime.prepare(itau, ['202606']);
  const worker = instances[0], request = worker.messages[0];
  complete(worker, request, {packet: {id: individual.id, periods: ['202606']}});
  await assert.rejects(result, /não correspondem/);
});

test('changing a selection cancels delivery of the old result and keeps another request available', async t => {
  const {runtime, instances} = fixture(t);
  const controller = new AbortController();
  const first = runtime.prepare(itau, ['202603'], null, {signal: controller.signal});
  const rejected = assert.rejects(first, {name: 'AbortError'});
  const worker = instances[0], a = worker.messages[0];
  const second = runtime.prepare(itau, ['202606']);
  const b = worker.messages[1];
  controller.abort();
  await rejected;
  assert.deepEqual(worker.messages.at(-1), {type: 'cancel', id: a.id});
  complete(worker, a);
  complete(worker, b);
  assert.deepEqual((await second).periods, ['202606']);
  assert.equal(worker.terminated, false);
});

test('an already cancelled request creates no worker', async t => {
  const {runtime, instances} = fixture(t), controller = new AbortController();
  controller.abort();
  await assert.rejects(runtime.prepare(itau, ['202606'], null, {signal: controller.signal}), {name: 'AbortError'});
  assert.equal(instances.length, 0);
});

test('worker crashes reject pending jobs and the next attempt starts a fresh worker', async t => {
  const {runtime, instances} = fixture(t);
  const first = runtime.prepare(itau, ['202606']);
  instances[0].fail();
  await assert.rejects(first, /interrompida/);
  assert.equal(instances[0].terminated, true);
  const second = runtime.prepare(itau, ['202606']);
  assert.equal(instances.length, 2);
  complete(instances[1], instances[1].messages[0]);
  assert.equal((await second).id, itau.id);
});

test('bootstrap download failures discard the failed engine and remain retryable', async t => {
  const {runtime, instances} = fixture(t);
  const first = runtime.prepare(itau, ['202606']), worker = instances[0], request = worker.messages[0];
  worker.emit({type: 'error', id: request.id, context: context(request), error: {message: 'Falha de conexão.', phase: 'bootstrap'}});
  await assert.rejects(first, /conexão/);
  assert.equal(worker.terminated, true);
  const second = runtime.prepare(itau, ['202606']);
  complete(instances[1], instances[1].messages[0]);
  await second;
});

test('timeout terminates the blocked worker instead of keeping an unusable promise', async t => {
  const {runtime, instances} = fixture(t, {timeoutMs: 10});
  await assert.rejects(runtime.prepare(itau, ['202606']), /demorou/);
  assert.equal(instances[0].terminated, true);
});

test('native exports return the correct Office MIME and reject incomplete bytes', async t => {
  const {runtime, instances} = fixture(t);
  for (const format of ['xlsx', 'pptx']) {
    const result = runtime.export(itau, ['202512', '202606'], format);
    const worker = instances[0], request = worker.messages.at(-1);
    const bytes = new Uint8Array([0x50, 0x4b, 3, 4, 0, 0]).buffer;
    complete(worker, request, {bytes});
    const blob = await result;
    assert.equal(blob.size, 6);
    assert.ok(blob.type.includes(format === 'xlsx' ? 'spreadsheetml' : 'presentationml'));
  }
  const bad = runtime.export(itau, ['202606'], 'pptx'), worker = instances[0], request = worker.messages.at(-1);
  complete(worker, request, {bytes: new Uint8Array([1, 2]).buffer});
  await assert.rejects(bad, /incompleto/);
  await assert.rejects(runtime.export(itau, ['202606'], 'pdf'), /Formato/);
});

test('individual CNPJ identity retains leading zeroes', () => {
  const selection = statementSelection({id: 'individual-00360305', scope: 'individual', code: '00360305'}, ['202606']);
  assert.equal(selection.entity.code, '00360305');
  assert.equal(selection.entity.inputPath, 'data/statements/inputs/individual-00360305.json.gz');
});

test('canonical compressed and legacy plain input paths stay bound to the official identity', () => {
  for (const suffix of ['.json.gz', '.json']) {
    const entity = {...individual, inputPath: `data/statements/inputs/${individual.id}${suffix}`};
    assert.equal(statementSelection(entity, ['202606']).entity.inputPath, entity.inputPath);
  }
  for (const inputPath of [
    `data/statements/inputs/${itau.id}.json.gz`,
    `data/statements/inputs/${individual.id}.json.gz?url=https://example.com`,
    `data/statements/inputs/../${individual.id}.json.gz`,
    `https://example.com/${individual.id}.json.gz`,
  ]) assert.throws(() => statementSelection({...individual, inputPath}, ['202606']), /endereço/);
});

test('gzip transport preserves complete JSON, numeric zero, negative balances, nulls and formulas', async () => {
  const packet = {id: individual.id, name: 'ITAÚ UNIBANCO S.A.', cells: [null, 0, -10.25], formula: '=IF(COUNT(C7)>0,C7,"N/D")'};
  const source = JSON.stringify(packet), compressed = gzipSync(source, {mtime: 0});
  assert.equal(compressed[0], 0x1f);
  assert.equal(await decodeStatementBytes(compressed), source);
  assert.deepEqual(JSON.parse(await decodeStatementBytes(compressed)), packet);
});

test('plain or CDN-decoded responses are read directly without a second decompression', async () => {
  const source = '{"name":"Crédito","value":0,"missing":null}';
  const bytes = new TextEncoder().encode(source);
  assert.equal(await decodeStatementBytes(bytes, null), source);
  assert.equal(await decodeStatementBytes(bytes.buffer), source);
});

test('missing gzip support and incomplete streams reject without producing a packet', async () => {
  const compressed = gzipSync('{"value":10}');
  await assert.rejects(decodeStatementBytes(compressed, null), /navegador/);
  await assert.rejects(decodeStatementBytes(compressed.subarray(0, 8)));
});

test('the runtime posts an explicit revision base while retaining canonical identity paths',async t=>{
  const dataBase='http://localhost/api/shared/data/'+'a'.repeat(32)+'/';
  const {runtime,instances}=fixture(t,{dataBase});
  const pending=runtime.prepare(individual,['202606']);
  const request=instances[0].messages[0];
  assert.equal(request.dataBase,dataBase);
  assert.equal(request.entity.inputPath,'data/statements/inputs/individual-60701190.json.gz');
  complete(instances[0],request);
  assert.equal((await pending).id,individual.id);
});

test('a changed publication terminates the old worker and cannot reuse its engine or late response',async t=>{
  t.after(()=>pinDataRevision(null));pinDataRevision('a'.repeat(32));
  const {runtime,instances}=fixture(t,{dataBase:datasetRoot});
  const first=runtime.prepare(individual,['202606']),rejected=assert.rejects(first,/revisão/);
  const old=instances[0],previous=old.messages[0];
  pinDataRevision('b'.repeat(32));
  const second=runtime.prepare(individual,['202606']);
  await rejected;
  assert.equal(old.terminated,true);
  assert.equal(instances.length,2);
  assert.notEqual(instances[1].messages[0].dataBase,previous.dataBase);
  complete(old,previous);
  complete(instances[1],instances[1].messages[0]);
  assert.equal((await second).id,individual.id);
});

test('a late response is rejected after a pin changes even before another Python request starts',async t=>{
  t.after(()=>pinDataRevision(null));pinDataRevision('a'.repeat(32));
  const {runtime,instances}=fixture(t,{dataBase:datasetRoot});
  const pending=runtime.prepare(individual,['202606']),rejected=assert.rejects(pending,/revisão/);
  const worker=instances[0],request=worker.messages[0];
  pinDataRevision('b'.repeat(32));complete(worker,request);
  await rejected;assert.equal(worker.terminated,true);
});
