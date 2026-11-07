import {BASE} from './data.js';

const MIME = {
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
};

function abortError(message = 'Preparação cancelada.') {
  const error = new Error(message);
  error.name = 'AbortError';
  return error;
}

export function statementSelection(entity, periods) {
  if (!entity || !['individual', 'prudential'].includes(entity.scope)) throw new Error('Perímetro contábil inválido.');
  const code = String(entity.code || '');
  if (!(entity.scope === 'individual' ? /^\d{8}$/ : /^C\d{7}$/).test(code)) throw new Error('Identificador contábil inválido.');
  const id = `${entity.scope}-${code}`;
  if (entity.id !== id) throw new Error('A identidade contábil não corresponde à instituição selecionada.');
  if (!Array.isArray(periods) || periods.length < 1 || periods.length > 8 ||
      periods.some(p => typeof p !== 'string' || !/^\d{4}(0[1-9]|1[0-2])$/.test(p)) ||
      new Set(periods).size !== periods.length) throw new Error('Selecione de uma a oito competências distintas.');
  const selected = [...periods].sort();
  if (Array.isArray(entity.periods) && selected.some(p => !entity.periods.includes(p))) throw new Error('Competência indisponível para esta instituição.');
  const canonicalPath = `data/statements/inputs/${id}.json.gz`;
  const legacyPath = `data/statements/inputs/${id}.json`;
  const inputPath = entity.inputPath || canonicalPath;
  if (![canonicalPath, legacyPath].includes(inputPath)) throw new Error('O endereço dos dados não corresponde à instituição selecionada.');
  return {entity: {id, code, scope: entity.scope, inputPath}, periods: selected};
}

function sameContext(message, request) {
  return message.context?.entityId === request.entity.id &&
    message.context?.operation === request.operation &&
    (message.context?.format || null) === (request.format || null) &&
    Array.isArray(message.context?.periods) &&
    message.context.periods.length === request.periods.length &&
    message.context.periods.every((p, i) => p === request.periods[i]);
}

/** A worker is created only when a statement or native file is requested. */
export function createStatementRuntime({
  baseUrl = BASE,
  WorkerClass = globalThis.Worker,
  timeoutMs = 180000,
  workerUrl = new URL('./statements-worker.js', import.meta.url),
} = {}) {
  let worker = null;
  let sequence = 0;
  const pending = new Map();

  function remove(id) {
    const request = pending.get(id);
    if (!request) return null;
    pending.delete(id);
    clearTimeout(request.timer);
    request.signal?.removeEventListener('abort', request.onAbort);
    return request;
  }

  function reset(reason = abortError()) {
    const current = worker;
    worker = null;
    current?.terminate();
    for (const id of [...pending.keys()]) remove(id).reject(reason);
  }

  function getWorker() {
    if (worker) return worker;
    if (typeof WorkerClass !== 'function') throw new Error('Este navegador não oferece os recursos necessários para preparar as demonstrações.');
    const instance = new WorkerClass(workerUrl, {type: 'module', name: 'tomaconta-statements'});
    worker = instance;
    instance.addEventListener('message', ({data: message}) => {
      if (worker !== instance || !message || !pending.has(message.id)) return;
      const request = pending.get(message.id);
      if (!sameContext(message, request)) {
        remove(message.id).reject(new Error('A resposta recebida pertence a outro recorte da análise. Tente novamente.'));
        return;
      }
      if (message.type === 'status') {
        if (typeof message.message === 'string') request.onStatus?.(message.message);
        return;
      }
      if (message.type === 'error') {
        const error = new Error(message.error?.message || 'Não foi possível preparar a análise. Tente novamente.');
        error.details = message.error?.details || '';
        error.phase = message.error?.phase || '';
        remove(message.id).reject(error);
        if (error.phase === 'bootstrap') reset(new Error('Os recursos da análise precisam ser carregados novamente. Tente novamente.'));
        return;
      }
      if (message.type !== 'result') return;
      const completed = remove(message.id);
      if (request.operation === 'analyze') {
        const packet = message.packet;
        if (!packet || packet.id !== request.entity.id || !Array.isArray(packet.periods) ||
            packet.periods.length !== request.periods.length ||
            packet.periods.some((p, i) => p !== request.periods[i])) {
          completed.reject(new Error('Os demonstrativos recebidos não correspondem à seleção. Tente novamente.'));
        } else completed.resolve(packet);
      } else {
        const bytes = message.bytes;
        if (!(bytes instanceof ArrayBuffer) || bytes.byteLength < 4 || new Uint8Array(bytes)[0] !== 0x50 || new Uint8Array(bytes)[1] !== 0x4b) {
          completed.reject(new Error('O arquivo gerado está incompleto. Tente novamente.'));
        } else completed.resolve(new Blob([bytes], {type: MIME[request.format]}));
      }
    });
    const fail = event => {
      if (worker !== instance) return;
      event.preventDefault?.();
      reset(new Error('A preparação da análise foi interrompida. Tente novamente.'));
    };
    instance.addEventListener('error', fail);
    instance.addEventListener('messageerror', fail);
    return instance;
  }

  function run(operation, entity, periods, format, onStatus, {signal} = {}) {
    let selection;
    try {
      selection = statementSelection(entity, periods);
      if (operation === 'export' && !Object.hasOwn(MIME, format)) throw new Error('Formato de exportação inválido.');
      if (signal?.aborted) throw abortError();
    } catch (error) {return Promise.reject(error);}
    return new Promise((resolve, reject) => {
      const id = `statement-${++sequence}`;
      const request = {...selection, operation, format, onStatus, signal, resolve, reject};
      request.onAbort = () => {
        const cancelled = remove(id);
        if (!cancelled) return;
        worker?.postMessage({type: 'cancel', id});
        cancelled.reject(abortError());
      };
      request.timer = setTimeout(() => {
        if (!pending.has(id)) return;
        reset(new Error('A preparação demorou mais que o esperado. Verifique a conexão e tente novamente.'));
      }, timeoutMs);
      pending.set(id, request);
      signal?.addEventListener('abort', request.onAbort, {once: true});
      try {
        const active = getWorker();
        const origin = globalThis.location?.href || 'http://localhost/';
        const base = new URL(baseUrl, origin).href;
        onStatus?.('Preparando análise…');
        active.postMessage({type: operation, id, ...selection, format, baseUrl: base});
      } catch (error) {remove(id)?.reject(error);}
    });
  }

  return {
    prepare: (entity, periods, onStatus, options) => run('analyze', entity, periods, null, onStatus, options),
    export: (entity, periods, format, onStatus, options) => run('export', entity, periods, format, onStatus, options),
    reset,
  };
}

let runtime;
function instance() {return runtime || (runtime = createStatementRuntime());}
export const prepareStatement = (entity, periods, onStatus, options) => instance().prepare(entity, periods, onStatus, options);
export const exportStatement = (entity, periods, format, onStatus, options) => instance().export(entity, periods, format, onStatus, options);
export function resetStatementRuntime() {runtime?.reset(); runtime = undefined;}
