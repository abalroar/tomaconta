import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {Worker} from 'node:worker_threads';
import {build} from 'vite';

const root = fileURLToPath(new URL('../', import.meta.url));

test('production application references an executable worker with bundled imports and the deployed data base', {timeout: 90000}, async t => {
  const outDir = await mkdtemp(path.join(tmpdir(), 'tomaconta-worker-build-'));
  t.after(() => rm(outDir, {recursive: true, force: true}));
  const result = await build({
    root,
    configFile: path.join(root, 'vite.config.js'),
    logLevel: 'silent',
    build: {outDir, emptyOutDir: true, copyPublicDir: false},
  });
  const chunks = (Array.isArray(result) ? result : [result]).flatMap(item => item.output).filter(item => item.type === 'chunk');
  const workerReferences = chunks.flatMap(chunk => [...chunk.code.matchAll(/new Worker\(\s*new URL\(\s*["']([^"']*statements-worker[^"']*\.js)["']/g)].map(match => match[1]));
  assert.equal(workerReferences.length, 1, 'the real application must instantiate exactly one bundled statements worker');
  const workerPath = new URL(workerReferences[0], 'https://example.test');
  assert.ok(workerPath.pathname.startsWith('/atlas-sfn/assets/'));
  const file = path.join(outDir, workerPath.pathname.slice('/atlas-sfn/'.length));
  assert.ok((await readFile(file)).byteLength > 0);

  // Import the exact emitted worker. Missing local imports fail in Node's ESM
  // loader, independently of Vite source patterns or a development server.
  const harness = `
    const {parentPort, workerData} = require('node:worker_threads');
    let fetches = 0;
    globalThis.location = {href: workerData.href};
    globalThis.self = {
      location: globalThis.location,
      addEventListener(type, listener) {
        if (type === 'message') parentPort.on('message', data => listener({data}));
      },
      postMessage(message) { parentPort.postMessage({...message, fetches}); },
    };
    globalThis.fetch = async () => {fetches++; throw Error('Unexpected network request');};
    import(workerData.file).then(
      () => parentPort.postMessage({type: 'ready', fetches}),
      error => {throw error;}
    );
  `;
  const worker = new Worker(harness, {eval: true, workerData: {file: pathToFileURL(file).href, href: workerPath.href}});
  t.after(() => worker.terminate());
  let inbox = [], waiter;
  worker.on('message', message => {if (waiter) {const resolve = waiter; waiter = null; resolve(message);} else inbox.push(message);});
  let workerError;
  worker.on('error', error => {workerError = error; if (waiter) {const resolve = waiter; waiter = null; resolve({failed: error});}});
  const next = async () => {
    if (workerError) throw workerError;
    const message = inbox.length ? inbox.shift() : await new Promise((resolve, reject) => {
      const timer = setTimeout(() => {waiter = null; reject(Error('The emitted worker did not respond.'));}, 5000);
      waiter = value => {clearTimeout(timer); resolve(value);};
    });
    if (message.failed) throw message.failed;
    return message;
  };
  assert.deepEqual(await next(), {type: 'ready', fetches: 0});
  const entity = {id: 'prudential-C0080099', scope: 'prudential', code: 'C0080099', inputPath: 'data/statements/inputs/prudential-C0080099.json.gz'};
  const job = {type: 'analyze', entity, periods: ['202512', '202606'], dataBase: 'https://example.test/atlas-sfn/data/'};
  for (const [id, change, expected] of [
    ['identity', {entity: {...entity, code: 'C0083539'}}, /Identidade contábil inválida/],
    ['base', {dataBase: 'https://example.test/data/'}, /Origem dos dados inválida/],
    ['revision', {dataBase: 'https://example.test/atlas-sfn/api/shared/data/invalid/'}, /Origem dos dados inválida/],
    ['periods', {periods: ['202606', '202512']}, /Competências inválidas/],
  ]) {
    worker.postMessage({...job, ...change, id});
    const response = await next();
    assert.equal(response.type, 'error');
    assert.equal(response.id, id);
    assert.match(response.error.details, expected);
    assert.equal(response.fetches, 0, 'invalid production jobs must fail before any request');
  }
});
