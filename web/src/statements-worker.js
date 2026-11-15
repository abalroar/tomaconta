/* Python and its packages are loaded on demand, outside the interface thread. */
import {datasetPath,validateDatasetRoot} from './data.js';
const PYTHON_ROOT = '/tc-engine';
let enginePromise;
let nativePromise;
let activeBase;
let queue = Promise.resolve();
const sources = new Map();
const packets = new Map();
const cancelled = new Set();
const knownJobs = new Set();

function context(job) {return {entityId: job.entity.id, periods: job.periods, operation: job.type, format: job.format || null,dataBase:job.dataBase};}
function status(job, message) {if (!cancelled.has(job.id)) self.postMessage({type: 'status', id: job.id, context: context(job), message});}
export function statementAssetUrl(dataBase,path,origin=globalThis.location?.href||'http://localhost/'){
  return new URL(datasetPath(path),validateDatasetRoot(dataBase,origin)).href;
}

function validateJob(job) {
  if (!job || !['analyze', 'export'].includes(job.type) || typeof job.id !== 'string' || !job.entity) throw new Error('Pedido inválido.');
  const {scope, code, id, inputPath} = job.entity;
  if (!['individual', 'prudential'].includes(scope) || !(scope === 'individual' ? /^\d{8}$/ : /^C\d{7}$/).test(code || '') || id !== `${scope}-${code}` || ![`data/statements/inputs/${id}.json.gz`, `data/statements/inputs/${id}.json`].includes(inputPath)) throw new Error('Identidade contábil inválida.');
  if (!Array.isArray(job.periods) || !job.periods.length || job.periods.length > 8 || new Set(job.periods).size !== job.periods.length || job.periods.some(p => typeof p !== 'string' || !/^\d{4}(0[1-9]|1[0-2])$/.test(p)) || [...job.periods].sort().some((p, i) => p !== job.periods[i])) throw new Error('Competências inválidas.');
  if (job.type === 'export' && !['xlsx', 'pptx'].includes(job.format)) throw new Error('Formato inválido.');
  const base=validateDatasetRoot(job.dataBase,self.location.href);
  if (activeBase && activeBase !== base) throw new Error('A origem da análise foi alterada.');
  activeBase = base;
}

async function response(url) {
  const result = await fetch(url, {credentials: 'same-origin', signal: AbortSignal.timeout(45000)});
  if (!result.ok) throw new Error(`Dados indisponíveis (${result.status}).`);
  return result;
}

/** A CDN may decode Content-Encoding before fetch exposes the response bytes. */
export async function decodeStatementBytes(input, Decompressor = globalThis.DecompressionStream) {
  const bytes = input instanceof Uint8Array ? input : new Uint8Array(input);
  if (bytes[0] !== 0x1f || bytes[1] !== 0x8b) return new TextDecoder('utf-8', {fatal: true}).decode(bytes);
  if (typeof Decompressor !== 'function') {
    const error = new Error('Este navegador não consegue ler a base compactada. Use uma versão atualizada.');
    error.userMessage = error.message;
    throw error;
  }
  const stream = new Blob([bytes]).stream().pipeThrough(new Decompressor('gzip'));
  return new Response(stream).text();
}

async function verified(url, expectedHash, expectedSize) {
  if (!/^[a-f0-9]{64}$/.test(expectedHash || '')) throw new Error('Assinatura dos recursos ausente.');
  const bytes = new Uint8Array(await (await response(url)).arrayBuffer());
  if (Number.isFinite(expectedSize) && bytes.byteLength !== expectedSize) throw new Error('Recurso incompleto.');
  const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(v => v.toString(16).padStart(2, '0')).join('');
  if (hash !== expectedHash) throw new Error('Os recursos da análise não correspondem à versão publicada.');
  return bytes;
}

function validateManifest(manifest) {
  const version = manifest.pyodide?.version;
  if (!/^\d+\.\d+\.\d+$/.test(version || '') || manifest.pyodide?.indexURL !== `https://cdn.jsdelivr.net/pyodide/v${version}/full/`) throw new Error('Versão dos recursos inválida.');
  if (manifest.schemaVersion !== 1 || manifest.bridge !== 'bridge.py' || !Array.isArray(manifest.modules) || !manifest.modules.length || !manifest.modules.some(m => m.path === 'bridge.py')) throw new Error('Catálogo dos recursos inválido.');
  const paths = new Set();
  for (const module of manifest.modules) {
    if (!/^(bridge\.py|utils\/[A-Za-z0-9_]+\.py)$/.test(module.path) || paths.has(module.path)) throw new Error('Módulo da análise inválido.');
    paths.add(module.path);
  }
  if (!Array.isArray(manifest.packages?.builtIn) || !manifest.packages.builtIn.includes('pandas') || manifest.packages.builtIn.some(p => !['pandas', 'lxml', 'pillow', 'micropip', 'typing-extensions'].includes(p))) throw new Error('Pacotes da análise inválidos.');
  if (!Array.isArray(manifest.packages?.pip) || manifest.packages.pip.some(p => !/^(?:XlsxWriter|python-pptx)==\d+\.\d+\.\d+$/.test(p))) throw new Error('Versões de exportação inválidas.');
  return manifest;
}

async function engine(job) {
  if (!enginePromise) {
    enginePromise = (async () => {
      status(job, 'Carregando recursos da análise…');
      const engineBase = new URL('.',statementAssetUrl(activeBase,'data/statements/engine/manifest.json',self.location.href));
      const manifest = validateManifest(await (await response(new URL('manifest.json', engineBase))).json());
      const runtimeUrl = `${manifest.pyodide.indexURL}pyodide.mjs`;
      const {loadPyodide} = await import(/* @vite-ignore */ runtimeUrl);
      const pyodide = await loadPyodide({indexURL: manifest.pyodide.indexURL});
      await pyodide.loadPackage('pandas');
      pyodide.FS.mkdirTree(`${PYTHON_ROOT}/utils`);
      const modules = await Promise.all(manifest.modules.map(async module => ({module, bytes: await verified(new URL(module.path, engineBase), module.sha256, module.size)})));
      for (const {module, bytes} of modules) {
        pyodide.FS.writeFile(`${PYTHON_ROOT}/${module.path}`, bytes);
      }
      pyodide.runPython(`import sys\nsys.path.insert(0, '${PYTHON_ROOT}')`);
      return {pyodide, manifest, engineBase, bridge: pyodide.pyimport('bridge')};
    })().catch(error => {enginePromise = undefined; nativePromise = undefined; throw error;});
  }
  return enginePromise;
}

async function native(engineState, job) {
  if (!nativePromise) {
    nativePromise = (async () => {
      status(job, 'Preparando exportações…');
      const {pyodide, manifest, engineBase} = engineState;
      await pyodide.loadPackage(manifest.packages.builtIn.filter(p => p !== 'pandas'));
      const wheels = manifest.packages.wheels;
      let requirements = manifest.packages.pip;
      if (Array.isArray(wheels) && wheels.length) {
        pyodide.FS.mkdirTree(`${PYTHON_ROOT}/wheels`);
        requirements = [];
        for (const wheel of wheels) {
          if (!/^wheels\/[A-Za-z0-9_.-]+\.whl$/.test(wheel.path)) throw new Error('Pacote de exportação inválido.');
          const bytes = await verified(new URL(wheel.path, engineBase), wheel.sha256, wheel.size);
          const filename = wheel.path.split('/').at(-1);
          pyodide.FS.writeFile(`${PYTHON_ROOT}/wheels/${filename}`, bytes);
          requirements.push(`emfs:${PYTHON_ROOT}/wheels/${filename}`);
        }
      }
      const micropip = pyodide.pyimport('micropip');
      const requested = pyodide.toPy(requirements);
      try {await micropip.install.callKwargs(requested, {deps: false});}
      finally {requested.destroy(); micropip.destroy();}
    })().catch(error => {nativePromise = undefined; throw error;});
  }
  return nativePromise;
}

async function input(job) {
  if (!sources.has(job.entity.id)) {
    const promise = (async () => {
      status(job, 'Carregando dados da instituição…');
      const text = await decodeStatementBytes(await (await response(statementAssetUrl(activeBase,job.entity.inputPath,self.location.href))).arrayBuffer());
      const packet = JSON.parse(text);
      if (packet.id !== job.entity.id || packet.scope !== job.entity.scope || packet.code !== job.entity.code) throw new Error('Os dados recebidos pertencem a outra instituição.');
      return {text, packet};
    })().catch(error => {sources.delete(job.entity.id); throw error;});
    sources.set(job.entity.id, promise);
    // A bounded cache avoids retaining the complete catalog in the worker.
    if (sources.size > 4) sources.delete(sources.keys().next().value);
  }
  return sources.get(job.entity.id);
}

function bytesFromPython(value) {
  if (value instanceof Uint8Array) return value.slice();
  const view = value.getBuffer('u8');
  try {return new Uint8Array(view.data.buffer, view.data.byteOffset, view.data.byteLength).slice();}
  finally {view.release(); value.destroy();}
}

async function process(job) {
  let phase = 'bootstrap';
  try {
    validateJob(job);
    if (cancelled.has(job.id)) return;
    const runtime = await engine(job);
    phase = 'input';
    const source = await input(job);
    if (Array.isArray(source.packet.periods) && job.periods.some(p => !source.packet.periods.includes(p))) throw new Error('Competência indisponível para esta instituição.');
    if (cancelled.has(job.id)) return;
    const selected = JSON.stringify(job.periods);
    const key = `${job.entity.id}:${selected}`;
    if (job.type === 'analyze') {
      phase = 'analysis';
      let packet = packets.get(key);
      if (!packet) {
        status(job, 'Preparando os demonstrativos…');
        packet = JSON.parse(runtime.bridge.analyze(source.text, selected));
        if (packet.id !== job.entity.id || JSON.stringify(packet.periods) !== selected) throw new Error('O resultado não corresponde ao recorte solicitado.');
        packets.set(key, packet);
        if (packets.size > 12) packets.delete(packets.keys().next().value);
      }
      if (!cancelled.has(job.id)) self.postMessage({type: 'result', id: job.id, context: context(job), packet});
    } else {
      phase = 'export';
      await native(runtime, job);
      if (cancelled.has(job.id)) return;
      status(job, job.format === 'xlsx' ? 'Gerando arquivo Excel…' : 'Gerando arquivo PowerPoint…');
      const bytes = bytesFromPython(runtime.bridge.export_native(source.text, selected, job.format));
      if (!cancelled.has(job.id)) self.postMessage({type: 'result', id: job.id, context: context(job), bytes: bytes.buffer}, [bytes.buffer]);
    }
  } catch (error) {
    if (!cancelled.has(job.id)) {
      const messages = {bootstrap: 'Não foi possível carregar os recursos da análise. Verifique a conexão e tente novamente.', input: 'Os dados desta instituição não puderam ser carregados. Tente novamente.', analysis: 'A análise não pôde ser preparada para as competências escolhidas.', export: 'O arquivo não pôde ser gerado. Tente novamente.'};
      self.postMessage({type: 'error', id: job.id, context: job.entity ? context(job) : {}, error: {message: error?.userMessage || messages[phase], phase, details: String(error?.message || error)}});
    }
  } finally {cancelled.delete(job.id); knownJobs.delete(job.id);}
}

if (typeof self !== 'undefined') self.addEventListener('message', ({data: job}) => {
  if (job?.type === 'cancel') {if (knownJobs.has(job.id)) cancelled.add(job.id); return;}
  if (!job || typeof job.id !== 'string') return;
  knownJobs.add(job.id);
  queue = queue.then(() => process(job)).catch(() => {});
});
