import {SCHEMA} from './shared-schema.js';

export const SHARED_ROOT = '/tomaconta/api/shared';
export const OIDC_AUDIENCE = 'https://matheusprat.es/tomaconta/api/shared/runner';
export const OIDC_WORKFLOW = 'abalroar/tomaconta/.github/workflows/tomaconta-shared.yml@refs/heads/main';
const ISSUER = 'https://token.actions.githubusercontent.com';
const JWKS_URL = `${ISSUER}/.well-known/jwks`;
const REPOSITORY_ID = '1141557164', OWNER_ID = '255978345';
const HEX = /^[a-f0-9]{64}$/, ID = /^[a-f0-9]{32}$/, COMMIT = /^[a-f0-9]{40}$/;
const LEASE_MS = 180000, MAX_ATTEMPTS = 3, MAX_PENDING = 4;
const SUCCESS_COOLDOWN = 15 * 60000, FAILED_COOLDOWN = 60000;
const KINDS = new Set(['financeiro', 'individual', 'mercado_credito_sgs', 'mercado_imobiliario', 'scr_data', 'spb_meios_pagamento', 'rede_agencias', 'tudo']);
const UFS = 'br ac al ap am ba ce df es go ma mt ms mg pa pb pr pe pi rj rn rs ro rr sc sp se to'.split(' ');
const REQUIRED_FILES = ['manifest.json', 'institutions.json', 'sfn.json', 'imob-br.json', 'imob-catalog.json', 'extra.json', 'statements/index.json', 'statements/engine/manifest.json', 'bank-network.json', 'bank-network-ufs.geojson'].map(path => `web/data/${path}`);
const initialized = new WeakMap(), keyCaches = new WeakMap(), manifestCache = new Map();
const random = () => crypto.randomUUID().replaceAll('-', '');
const timestamp = value => new Date(value).toISOString();
const digest = async bytes => [...new Uint8Array(await crypto.subtle.digest('SHA-256', typeof bytes === 'string' ? new TextEncoder().encode(bytes) : bytes))].map(byte => byte.toString(16).padStart(2, '0')).join('');
const reply = (data, status = 200, headers = {}) => Response.json(data, {status, headers: {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'X-TomaConta-Service': 'shared-v1', ...headers}});
class HttpError extends Error {constructor(status, message, headers) {super(message); this.status = status; this.headers = headers;}}
const fail = (status, message, headers) => {throw new HttpError(status, message, headers);};
const object = value => value && typeof value === 'object' && !Array.isArray(value);
const exactKeys = (input, keys) => {if (!object(input) || Object.keys(input).some(key => !keys.includes(key))) fail(400, 'Campo não permitido no pedido.');};

async function body(request, limit = 8192) {
  if (!request.headers.get('Content-Type')?.startsWith('application/json')) fail(415, 'Envie um pedido JSON.');
  const reader = request.body?.getReader();
  if (!reader) fail(400, 'Pedido vazio.');
  const chunks = []; let size = 0;
  while (true) {
    const {value, done} = await reader.read(); if (done) break;
    size += value.length; if (size > limit) {await reader.cancel(); fail(413, 'Pedido grande demais.');}
    chunks.push(value);
  }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) {bytes.set(chunk, offset); offset += chunk.length;}
  let input; try {input = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(bytes));} catch {fail(400, 'JSON inválido.');}
  if (!object(input)) fail(400, 'Pedido inválido.');
  return input;
}

export function validatePlan(input, {bootstrap = false} = {}) {
  exactKeys(input, ['kind', 'mode', 'period', 'start', 'end', 'uf']);
  if (bootstrap && input.kind === 'bootstrap') {exactKeys(input, ['kind']); return {kind: 'bootstrap', mode: 'incremental'};}
  if (!KINDS.has(input.kind)) fail(400, 'Fonte de atualização inválida.');
  if (input.kind === 'rede_agencias' && ['period', 'start', 'end', 'uf'].some(key => input[key] != null)) fail(400, 'A rede de agências atualiza o cadastro atual, sem janela histórica ou filtro estadual.');
  const mode = input.mode || 'incremental';
  if (!['incremental', 'overwrite'].includes(mode)) fail(400, 'Modo de atualização inválido.');
  const plan = {kind: input.kind, mode};
  const month = value => typeof value === 'string' && /^20\d{2}-(0[1-9]|1[0-2])$/.test(value);
  const financial = ['financeiro', 'individual', 'tudo'].includes(input.kind);
  if (input.period != null) {
    if (!financial || !month(input.period)) fail(400, 'Competência inválida. Use YYYY-MM.');
    if (input.kind === 'individual' && !['03', '06', '09', '12'].includes(input.period.slice(5))) fail(400, 'A visão individual usa fim de trimestre.');
    plan.period = input.period;
  }
  if (input.start != null || input.end != null) {
    if (financial || !month(input.start) || !month(input.end) || input.start > input.end) fail(400, 'Janela mensal inválida.');
    const index = value => Number(value.slice(0, 4)) * 12 + Number(value.slice(5));
    if (index(input.end) - index(input.start) > 23) fail(400, 'A atualização aceita uma janela de até 24 meses.');
    plan.start = input.start; plan.end = input.end;
  }
  if (input.uf != null) {
    if (input.kind !== 'mercado_imobiliario' || !UFS.includes(input.uf)) fail(400, 'Abrangência inválida.');
    plan.uf = input.uf;
  }
  return plan;
}

export function validFilePath(path) {
  if (typeof path !== 'string' || path.length > 240 || path.split('/').some(part => !part || part === '.' || part === '..')) return false;
  if (/^cache\/runtime\/financial_analysis_sources\/[a-f0-9]{2}\/([a-f0-9]{64})\.bin$/.test(path)) return true;
  return /^(?:web\/data|cache\/(?:bundled|runtime))\/[A-Za-z0-9_./-]+\.(?:json(?:\.gz)?|geojson|parquet|csv|zip|xlsx|pptx|py|whl)$/i.test(path);
}

export function validateFiles(files) {
  if (!Array.isArray(files) || !files.length || files.length > 20000) fail(400, 'Pacote de arquivos inválido.');
  const paths = new Map();
  for (const file of files) {
    if (!object(file) || !validFilePath(file.path) || paths.has(file.path) || !HEX.test(file.sha256 || '') || !Number.isSafeInteger(file.size) || file.size < 1 || file.size > 64000000 || !['identity', undefined].includes(file.encoding)) fail(400, 'Arquivo da revisão inválido. Preserve os bytes originais e encoding identity.');
    const archived = file.path.match(/^cache\/runtime\/financial_analysis_sources\/[a-f0-9]{2}\/([a-f0-9]{64})\.bin$/);
    if (archived && archived[1] !== file.sha256) fail(400, 'Hash da fonte arquivada diverge do nome.');
    paths.set(file.path, {...file, encoding: 'identity'});
  }
  if (REQUIRED_FILES.some(path => !paths.has(path))) fail(400, 'A revisão não contém todas as áreas do site.');
  return paths;
}

function decode64(value) {return Uint8Array.from(atob(value.replaceAll('-', '+').replaceAll('_', '/') + '='.repeat((4 - value.length % 4) % 4)), char => char.charCodeAt(0));}
export async function authenticateRunner(request, {fetcher = fetch, now = Date.now()} = {}) {
  const bearer = request.headers.get('Authorization') || '';
  if (!bearer.startsWith('Bearer ') || bearer.length > 17000) fail(401, 'Executor não autorizado.');
  let header, claims, parts;
  try {
    parts = bearer.slice(7).split('.'); if (parts.length !== 3) throw Error();
    header = JSON.parse(new TextDecoder().decode(decode64(parts[0])));
    claims = JSON.parse(new TextDecoder().decode(decode64(parts[1])));
  } catch {fail(401, 'Identidade do executor inválida.');}
  if (header.alg !== 'RS256' || typeof header.kid !== 'string' || !/^[A-Za-z0-9_.-]{1,160}$/.test(header.kid)) fail(401, 'Assinatura do executor inválida.');
  let cached = keyCaches.get(fetcher);
  if (!cached || cached.expires <= now) {
    let response, packet;
    try {response = await fetcher(JWKS_URL, {signal: AbortSignal.timeout(15000)}); if (!response.ok) throw Error(); packet = await response.json();} catch {fail(503, 'Não foi possível verificar o executor. A base anterior permanece disponível.');}
    if (!Array.isArray(packet.keys)) fail(503, 'Chaves do executor indisponíveis.');
    cached = {keys: packet.keys, expires: now + 60000}; keyCaches.set(fetcher, cached);
  }
  const jwk = cached.keys.find(key => key.kid === header.kid && key.kty === 'RSA' && (!key.alg || key.alg === 'RS256'));
  if (!jwk) fail(401, 'Chave do executor não reconhecida.');
  let verified = false;
  try {const key = await crypto.subtle.importKey('jwk', jwk, {name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256'}, false, ['verify']); verified = await crypto.subtle.verify('RSASSA-PKCS1-v1_5', key, decode64(parts[2]), new TextEncoder().encode(`${parts[0]}.${parts[1]}`));} catch {}
  if (!verified) fail(401, 'Assinatura do executor inválida.');
  const seconds = now / 1000;
  if (claims.iss !== ISSUER || claims.aud !== OIDC_AUDIENCE || String(claims.repository_id) !== REPOSITORY_ID || String(claims.repository_owner_id) !== OWNER_ID || claims.repository !== 'abalroar/tomaconta' || claims.ref !== 'refs/heads/main' || claims.workflow_ref !== OIDC_WORKFLOW || !['schedule', 'workflow_dispatch'].includes(claims.event_name) || claims.runner_environment !== 'github-hosted' || !COMMIT.test(claims.sha || '') || !COMMIT.test(claims.workflow_sha || '') || !Number.isFinite(claims.exp) || claims.exp <= seconds || !Number.isFinite(claims.nbf) || claims.nbf > seconds + 30 || !Number.isFinite(claims.iat) || claims.iat > seconds + 30 || claims.iat < seconds - 600 || !/^\d{1,25}$/.test(String(claims.run_id)) || !/^\d{1,8}$/.test(String(claims.run_attempt))) fail(403, 'Este workflow não está autorizado a atualizar a base.');
  return {id: `${claims.run_id}:${claims.run_attempt}`, event: claims.event_name, commit: claims.sha, workflowCommit: claims.workflow_sha};
}

async function initialize(db) {
  if (!initialized.has(db)) initialized.set(db, db.batch(SCHEMA.map(sql => db.prepare(sql))).catch(error => {initialized.delete(db); throw error;}));
  return initialized.get(db);
}
function publicJob(job) {
  if (!job) return null;
  return {id: job.id, kind: job.kind, params: JSON.parse(job.params), status: job.status, progress: job.progress, message: job.message,
    createdAt: job.created_at, updatedAt: job.updated_at, attempts: job.attempts, error: job.error, result: job.result ? JSON.parse(job.result) : null};
}
async function leased(db, id, lease, runner, now) {
  if (!ID.test(id || '') || !ID.test(lease || '')) fail(400, 'Reserva inválida.');
  const row = await db.prepare('SELECT * FROM tc_jobs WHERE id=?').bind(id).first();
  if (!row || row.status !== 'running' || row.lease_id !== lease || row.runner_id !== runner.id || row.lease_until <= now) fail(409, 'A reserva de execução foi encerrada.');
  return row;
}
async function revisionFor(db, bucket, id, published = true) {
  if (!ID.test(id || '')) fail(404, 'Versão inexistente.');
  const row = await db.prepare(`SELECT * FROM tc_revisions WHERE id=?${published ? ' AND published_at IS NOT NULL' : ''}`).bind(id).first();
  if (!row) fail(404, 'Versão ainda não publicada.');
  let manifest = manifestCache.get(row.manifest_sha);
  if (!manifest) {
    const stored = await bucket.get(row.manifest_key); if (!stored) fail(503, 'Manifesto indisponível.');
    const text = await stored.text(); if (await digest(text) !== row.manifest_sha) fail(503, 'Manifesto inconsistente.');
    manifest = JSON.parse(text); if (manifestCache.size >= 8) manifestCache.delete(manifestCache.keys().next().value); manifestCache.set(row.manifest_sha, manifest);
  }
  return {row, manifest};
}
const sourcePath = source => source.filename ? `cache/bundled/${source.filename}` : String(source.file || '').replace(/^data\//, 'cache/');

export async function validateDependencies(bucket, files, summary) {
  if (!object(summary) || summary.validation?.complete !== true || summary.validation?.failures !== 0 || !COMMIT.test(summary.generation?.sourceCommit || '') || typeof summary.generation?.modelVersion !== 'string' || !Array.isArray(summary.generation?.sourceFiles) || !summary.generation.sourceFiles.length) fail(400, 'Informe a geração, as fontes e a validação completa do candidato.');
  function requireFile(path, sha, size) {
    const file = files.get(path);
    if (!file || sha && file.sha256 !== sha || size != null && file.size !== size) fail(400, `Dependência ausente ou divergente: ${path}`);
    return file;
  }
  for (const source of summary.generation.sourceFiles) {if (!source.path?.startsWith('cache/') || !HEX.test(source.sha256 || '')) fail(400, 'A geração deve incluir as fontes originais com seus hashes.'); requireFile(source.path, source.sha256, source.size);}
  async function read(path) {
    const file = requireFile(path); if (file.size > 12000000) fail(400, 'Catálogo de dependências grande demais.');
    const stored = await bucket.get(`tomaconta/objects/${file.sha256}`); if (!stored || stored.size !== file.size) fail(409, 'Arquivo ainda não confirmado no armazenamento.');
    const text = await stored.text(); if (await digest(text) !== file.sha256) fail(409, 'Hash do catálogo diverge dos bytes armazenados.');
    try {return JSON.parse(text);} catch {fail(400, 'Catálogo JSON inválido.');}
  }
  const [site, institutions, statements, engine, network, housing, specs, sfn, extra] = await Promise.all([
    'manifest.json', 'institutions.json', 'statements/index.json', 'statements/engine/manifest.json', 'bank-network.json', 'imob-br.json', 'imob-catalog.json', 'sfn.json', 'extra.json',
  ].map(path => read(`web/data/${path}`)));
  if (!Array.isArray(site.ufs) || UFS.some(uf => !site.ufs.includes(uf)) || site.ufs.some(uf => !UFS.includes(uf))) fail(400, 'Cobertura estadual incompleta.');
  for (const uf of site.ufs) requireFile(`web/data/imob-${uf}.json`);
  if (!Array.isArray(institutions.institutions) || !institutions.institutions.length || !Array.isArray(statements.institutions) || !statements.institutions.length) fail(400, 'Catálogo de instituições vazio.');
  requireFile(sourcePath(institutions.source || {}), institutions.source?.sha256);
  for (const institution of institutions.institutions) requireFile(`web/${institution.historyPath}`);
  for (const entity of statements.institutions) {requireFile(`web/${entity.path}`, entity.snapshotSha256, entity.snapshotBytes); requireFile(`web/${entity.inputPath}`, entity.inputSha256, entity.inputBytes);}
  for (const source of Object.values(statements.sources || {})) requireFile(sourcePath(source), source.sha256);
  if (statements.crosswalkPath) {
    const crosswalk = await read(`web/${statements.crosswalkPath}`);
    for (const source of Object.values(crosswalk.sources || {})) requireFile(sourcePath(source), source.sha256);
  }
  if (statements.modelVersion !== summary.generation.modelVersion || engine.modelVersion !== statements.modelVersion || !Array.isArray(engine.modules) || !engine.modules.some(module => module.path === engine.bridge)) fail(400, 'Versão do modelo contábil divergente.');
  for (const module of engine.modules) {if (!/^(bridge\.py|utils\/[A-Za-z0-9_]+\.py)$/.test(module.path)) fail(400, 'Módulo contábil inválido.'); requireFile(`web/data/statements/engine/${module.path}`, module.sha256, module.size);}
  for (const wheel of engine.packages?.wheels || []) {if (!/^wheels\/[A-Za-z0-9_.-]+\.whl$/.test(wheel.path)) fail(400, 'Pacote de exportação inválido.'); requireFile(`web/data/statements/engine/${wheel.path}`, wheel.sha256, wheel.size);}
  if (!network.geometry?.path?.startsWith('data/')) fail(400, 'Geometria da rede bancária ausente.');
  requireFile(`web/${network.geometry.path}`, network.geometry.sha256, network.geometry.bytes);
  if (!Array.isArray(housing) || housing.length !== 24 || !Array.isArray(specs) || specs.length !== 24 || new Set(housing.map(chart => chart.id)).size !== 24 || housing.some(chart => /bndu/i.test(chart.id + chart.title)) || !Array.isArray(sfn) || !sfn.length || !Array.isArray(extra) || !extra.length || site.chartCount !== sfn.length + extra.length + housing.length) fail(400, 'Cobertura de gráficos divergente.');
}

function contentType(path) {
  if (path.endsWith('.json.gz')) return 'application/gzip';
  if (path.endsWith('.json')) return 'application/json; charset=utf-8';
  if (path.endsWith('.geojson')) return 'application/geo+json; charset=utf-8';
  if (path.endsWith('.py')) return 'text/plain; charset=utf-8';
  if (path.endsWith('.csv')) return 'text/csv; charset=utf-8';
  if (path.endsWith('.xlsx')) return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
  if (path.endsWith('.pptx')) return 'application/vnd.openxmlformats-officedocument.presentationml.presentation';
  return 'application/octet-stream';
}

export async function handleShared(request, env, {fetcher = fetch, clock = Date.now} = {}) {
  try {
    const url = new URL(request.url), path = url.pathname.slice(SHARED_ROOT.length), now = clock(), at = timestamp(now);
    if (!url.pathname.startsWith(`${SHARED_ROOT}/`)) return reply({error: 'Operação inexistente.'}, 404);
    if (!env.TOMACONTA_DB || !env.TOMACONTA_BUCKET) {
      if (path === '/current' && request.method === 'GET') return reply({revision: null, builtIn: true, configured: false});
      fail(503, 'A atualização compartilhada ainda não foi configurada.');
    }
    const runnerRoute = path.startsWith('/runner/');
    const runner = runnerRoute ? await authenticateRunner(request, {fetcher, now}) : null;
    if (!runnerRoute && !['GET', 'HEAD'].includes(request.method) && (request.headers.get('Origin') !== url.origin || request.headers.has('Sec-Fetch-Site') && request.headers.get('Sec-Fetch-Site') !== 'same-origin')) fail(403, 'Origem inválida.');
    await initialize(env.TOMACONTA_DB);
    const db = env.TOMACONTA_DB.withSession ? env.TOMACONTA_DB.withSession('first-primary') : env.TOMACONTA_DB;
    const bucket = env.TOMACONTA_BUCKET;
    if (path === '/current' && request.method === 'GET') {
      const state = await db.prepare('SELECT * FROM tc_state WHERE id=1').first();
      const current = state.current_revision ? await revisionFor(db, bucket, state.current_revision) : null;
      return reply({revision: current?.row.id || null, publishedAt: current?.row.published_at || null, summary: current ? JSON.parse(current.row.summary) : null, builtIn: !current, configured: true});
    }
    const dataPath = path.match(/^\/data\/([a-f0-9]{32})\/(.+)$/);
    if (dataPath && ['GET', 'HEAD'].includes(request.method)) {
      const logical = `web/data/${dataPath[2]}`; if (!validFilePath(logical)) fail(404, 'Arquivo inexistente.');
      const {manifest} = await revisionFor(db, bucket, dataPath[1]); const file = manifest.files.find(item => item.path === logical); if (!file) fail(404, 'Arquivo não pertence à versão.');
      const headers = {'Content-Type': contentType(logical), 'Cache-Control': 'public, max-age=31536000, immutable', ETag: `"${file.sha256}"`, 'X-TomaConta-Revision': dataPath[1], 'X-Content-Type-Options': 'nosniff'};
      if (request.headers.get('If-None-Match') === headers.ETag) return new Response(null, {status: 304, headers});
      const stored = request.method === 'HEAD' ? await bucket.head(`tomaconta/objects/${file.sha256}`) : await bucket.get(`tomaconta/objects/${file.sha256}`);
      if (!stored || stored.size !== file.size) fail(503, 'Arquivo da versão indisponível.');
      return new Response(request.method === 'HEAD' ? null : stored.body, {headers});
    }
    if (path === '/jobs' && request.method === 'GET') {
      const result = await db.prepare('SELECT * FROM tc_jobs ORDER BY created_ms DESC LIMIT 40').all(); return reply({jobs: result.results.map(publicJob)});
    }
    const jobPath = path.match(/^\/jobs\/([a-f0-9]{32})$/);
    if (jobPath && request.method === 'GET') {const job = await db.prepare('SELECT * FROM tc_jobs WHERE id=?').bind(jobPath[1]).first(); if (!job) fail(404, 'Atualização inexistente.'); return reply({job: publicJob(job)});}
    if (path === '/jobs' && request.method === 'POST') {
      const plan = validatePlan(await body(request)), params = JSON.stringify(plan), hash = await digest(params), key = request.headers.get('Idempotency-Key');
      if (!ID.test(key || '')) fail(400, 'Chave de solicitação inválida.');
      const state = await db.prepare('SELECT current_revision FROM tc_state WHERE id=1').first();
      if (!state.current_revision) fail(503, 'A primeira versão compartilhada está sendo preparada. A base publicada continua disponível.');
      const previous = await db.prepare('SELECT * FROM tc_jobs WHERE request_key=?').bind(key).first();
      if (previous) {if (previous.params !== params) fail(409, 'Chave já usada para outro pedido.'); return reply({job: publicJob(previous)}, 200);}
      const duplicate = await db.prepare("SELECT * FROM tc_jobs WHERE plan_hash=? AND (status IN ('queued','running') OR (status='succeeded' AND updated_ms>?)) ORDER BY created_ms DESC LIMIT 1").bind(hash, now - SUCCESS_COOLDOWN).first();
      if (duplicate) return reply({job: publicJob(duplicate)}, 200);
      const id = random();
      const inserted = await db.prepare(`INSERT OR IGNORE INTO tc_jobs(id,request_key,plan_hash,kind,params,created_at,updated_at,created_ms,updated_ms)
        SELECT ?,?,?,?,?,?,?,?,? WHERE (SELECT COUNT(*) FROM tc_jobs WHERE status IN ('queued','running'))<?
        AND NOT EXISTS(SELECT 1 FROM tc_jobs WHERE kind=? AND (status IN ('queued','running') OR (status='succeeded' AND updated_ms>?) OR (status IN ('failed','needs_review') AND updated_ms>?)))`).bind(id, key, hash, plan.kind, params, at, at, now, now, MAX_PENDING, plan.kind, now - SUCCESS_COOLDOWN, now - FAILED_COOLDOWN).run();
      if (!inserted.meta.changes) {
        const active = await db.prepare("SELECT * FROM tc_jobs WHERE kind=? AND status IN ('queued','running') ORDER BY created_ms DESC LIMIT 1").bind(plan.kind).first();
        if (active) return reply({job: publicJob(active)}, 200);
        fail(429, 'Há uma atualização recente ou a fila está cheia. Aguarde antes de solicitar novamente.', {'Retry-After': '60'});
      }
      return reply({job: publicJob(await db.prepare('SELECT * FROM tc_jobs WHERE id=?').bind(id).first())}, 201);
    }
    if (path === '/revisions' && request.method === 'GET') {const result = await db.prepare('SELECT id,parent_revision,summary,created_at,published_at FROM tc_revisions WHERE published_at IS NOT NULL ORDER BY published_at DESC LIMIT 30').all(); return reply({revisions: result.results.map(row => ({...row, summary: JSON.parse(row.summary)}))});}
    if (path === '/runner/pending' && request.method === 'GET') {const row = await db.prepare("SELECT COUNT(*) AS n FROM tc_jobs WHERE status='queued' OR (status='running' AND lease_until<=?)").bind(now).first(); return reply({pending: row.n > 0});}
    if (path === '/runner/seed' && request.method === 'POST') {
      if (runner.event !== 'workflow_dispatch') fail(403, 'A importação inicial exige execução manual.');
      const plan = validatePlan(await body(request), {bootstrap: true}); if (plan.kind !== 'bootstrap') fail(400, 'Pedido de importação inicial inválido.');
      const state = await db.prepare('SELECT current_revision FROM tc_state WHERE id=1').first(); if (state.current_revision) fail(409, 'A base compartilhada já foi inicializada.');
      const existing = await db.prepare("SELECT * FROM tc_jobs WHERE kind='bootstrap' AND status IN ('queued','running') LIMIT 1").first(); if (existing) return reply({id: existing.id});
      const id = random(); await db.prepare('INSERT INTO tc_jobs(id,request_key,plan_hash,kind,params,created_at,updated_at,created_ms,updated_ms) VALUES(?,?,?,?,?,?,?,?,?)').bind(id, id, await digest(JSON.stringify(plan)), 'bootstrap', JSON.stringify(plan), at, at, now, now).run(); return reply({id}, 201);
    }
    if (path === '/runner/claim' && request.method === 'POST') {
      await db.prepare("UPDATE tc_jobs SET status='failed',error='O executor interrompeu três tentativas. Solicite novamente.',message='Atualização interrompida',lease_id=NULL,runner_id=NULL,lease_until=NULL,updated_at=?,updated_ms=? WHERE status='running' AND lease_until<=? AND attempts>=?").bind(at, now, now, MAX_ATTEMPTS).run();
      const lease = random();
      const job = await db.prepare(`UPDATE tc_jobs SET status='running',lease_id=?,runner_id=?,lease_until=?,attempts=attempts+1,updated_at=?,updated_ms=?,message='Executando atualização'
        WHERE id=(SELECT id FROM tc_jobs WHERE (status='queued' OR (status='running' AND lease_until<=?)) AND attempts<? ORDER BY created_ms LIMIT 1)
        AND NOT EXISTS(SELECT 1 FROM tc_jobs WHERE status='running' AND lease_until>?) RETURNING *`).bind(lease, runner.id, now + LEASE_MS, at, now, now, MAX_ATTEMPTS, now).first();
      if (!job) return reply({job: null});
      if (!job.base_initialized) {const state = await db.prepare('SELECT current_revision FROM tc_state WHERE id=1').first(); await db.prepare('UPDATE tc_jobs SET base_revision=?,base_initialized=1 WHERE id=? AND lease_id=?').bind(state.current_revision, job.id, lease).run(); job.base_revision = state.current_revision; job.base_initialized = 1;}
      const base = job.base_revision ? (await revisionFor(db, bucket, job.base_revision)).manifest : null;
      return reply({job: {...job, params: JSON.parse(job.params), result: job.result ? JSON.parse(job.result) : null}, base});
    }
    const action = path.match(/^\/runner\/jobs\/([a-f0-9]{32})\/(heartbeat|progress|fail|prepare|publish)$/);
    if (action && request.method === 'POST') {
      const input = await body(request, action[2] === 'prepare' ? 8000000 : 65536);
      if (action[2] === 'publish') {
        const completed = await db.prepare("SELECT result FROM tc_jobs WHERE id=? AND status='succeeded'").bind(action[1]).first();
        if (completed && JSON.parse(completed.result || '{}').revision === input.revision) return reply({revision: input.revision, published: true, alreadyPublished: true});
      }
      const job = await leased(db, action[1], input.lease, runner, now);
      if (['heartbeat', 'progress'].includes(action[2])) {
        const progress = Number(input.progress ?? job.progress); if (!Number.isFinite(progress) || progress < 0 || progress > 1) fail(400, 'Progresso inválido.');
        await db.prepare('UPDATE tc_jobs SET lease_until=?,progress=?,message=?,updated_at=?,updated_ms=? WHERE id=? AND lease_id=?').bind(now + LEASE_MS, progress, String(input.message || 'Executando atualização').slice(0, 300), at, now, job.id, input.lease).run(); return reply({ok: true});
      }
      if (action[2] === 'fail') {
        const result = JSON.stringify(input.result || {}); if (result.length > 50000) fail(413, 'Relatório grande demais.');
        await db.prepare('UPDATE tc_jobs SET status=?,message=?,error=?,result=?,runner_id=NULL,lease_id=NULL,lease_until=NULL,updated_at=?,updated_ms=? WHERE id=? AND lease_id=?').bind(input.needsReview ? 'needs_review' : 'failed', input.needsReview ? 'Há contas para revisão' : 'Atualização não concluída', String(input.error || 'Execução interrompida').slice(0, 2000), result, at, now, job.id, input.lease).run(); return reply({ok: true});
      }
      if (action[2] === 'prepare') {
        const files = validateFiles(input.files); if (input.parent !== job.base_revision) fail(409, 'A geração de origem difere do pedido.');
        const hashes = [...new Set(input.files.map(file => file.sha256))];
        const confirmed = await db.prepare('SELECT sha,size FROM tc_blobs WHERE sha IN (SELECT value FROM json_each(?))').bind(JSON.stringify(hashes)).all();
        const stored = new Map(confirmed.results.map(row => [row.sha, row.size])); if (input.files.some(file => stored.get(file.sha256) !== file.size)) fail(409, 'Há arquivos ainda não confirmados no armazenamento.');
        if (JSON.stringify(input.summary || {}).length > 100000) fail(413, 'Resumo grande demais.');
        if (input.summary?.generation?.sourceCommit !== runner.commit) fail(400, 'A geração não corresponde ao commit verificado do executor.');
        await validateDependencies(bucket, files, input.summary);
        await leased(db, job.id, input.lease, runner, clock());
        const prepared = await db.prepare('SELECT id FROM tc_revisions WHERE job_id=? ORDER BY created_at DESC LIMIT 1').bind(job.id).first();
        if (prepared) {
          const previous = await revisionFor(db, bucket, prepared.id, false);
          if (JSON.stringify(previous.manifest.files) !== JSON.stringify([...files.values()]) || JSON.stringify(previous.manifest.summary) !== JSON.stringify(input.summary)) fail(409, 'Este pedido já preparou outro candidato. Inicie um novo pedido.');
          return reply({revision: prepared.id, reused: true});
        }
        const id = random(), manifest = {schemaVersion: 1, id, parent: job.base_revision, jobId: job.id, createdAt: at, files: [...files.values()], summary: input.summary};
        const text = JSON.stringify(manifest), sha = await digest(text), key = `tomaconta/manifests/${id}.json`;
        await bucket.put(key, text, {sha256: sha, httpMetadata: {contentType: 'application/json'}});
        await db.prepare('INSERT INTO tc_revisions(id,job_id,parent_revision,manifest_key,manifest_sha,summary,created_at) VALUES(?,?,?,?,?,?,?)').bind(id, job.id, job.base_revision, key, sha, JSON.stringify(input.summary), at).run();
        await db.prepare('UPDATE tc_jobs SET result=?,message=?,progress=MAX(progress,0.95),updated_at=?,updated_ms=? WHERE id=? AND lease_id=?').bind(JSON.stringify({preparedRevision: id, summary: input.summary}), 'Candidato validado, preparando publicação', at, now, job.id, input.lease).run();
        return reply({revision: id}, 201);
      }
      if (action[2] === 'publish') {
        const {row} = await revisionFor(db, bucket, input.revision, false); if (row.job_id !== job.id || row.parent_revision !== job.base_revision) fail(409, 'A revisão não pertence a esta execução.');
        const result = await db.batch([
          db.prepare('UPDATE tc_state SET previous_revision=current_revision,current_revision=?,updated_at=? WHERE id=1 AND current_revision IS ? AND EXISTS(SELECT 1 FROM tc_jobs WHERE id=? AND status=\'running\' AND lease_id=? AND runner_id=? AND lease_until>?)').bind(row.id, at, job.base_revision, job.id, input.lease, runner.id, now),
          db.prepare('UPDATE tc_revisions SET published_at=? WHERE id=? AND (SELECT current_revision FROM tc_state WHERE id=1)=?').bind(at, row.id, row.id),
          db.prepare("UPDATE tc_jobs SET status='succeeded',progress=1,message='Base validada e publicada',result=?,runner_id=NULL,lease_id=NULL,lease_until=NULL,updated_at=?,updated_ms=? WHERE id=? AND lease_id=? AND (SELECT current_revision FROM tc_state WHERE id=1)=?").bind(JSON.stringify({revision: row.id, parent: job.base_revision, summary: JSON.parse(row.summary)}), at, now, job.id, input.lease, row.id),
          db.prepare("INSERT INTO tc_events(actor,action,revision,created_at) SELECT ?,'publish',?,? WHERE (SELECT current_revision FROM tc_state WHERE id=1)=?").bind(`github:${runner.id}`, row.id, at, row.id),
        ]);
        if (!result[0].meta.changes) fail(409, 'A base mudou ou a reserva expirou. A versão anterior foi preservada.'); return reply({revision: row.id, published: true});
      }
    }
    const blob = path.match(/^\/runner\/blobs\/([a-f0-9]{64})$/);
    if (blob && request.method === 'PUT') {
      const job = await leased(db, url.searchParams.get('job'), request.headers.get('X-Lease-Id'), runner, now);
      const length = Number(request.headers.get('Content-Length')); if (!Number.isSafeInteger(length) || length < 1 || length > 64000000) fail(413, 'Tamanho de arquivo inválido.');
      const previous = await db.prepare('SELECT size FROM tc_blobs WHERE sha=?').bind(blob[1]).first();
      if (previous) {if (previous.size !== length) fail(409, 'O tamanho diverge do hash.'); return reply({stored: true, reused: true});}
      let stored; try {stored = await bucket.put(`tomaconta/objects/${blob[1]}`, request.body, {sha256: blob[1], httpMetadata: {contentType: 'application/octet-stream'}});} catch {fail(400, 'Os bytes recebidos não correspondem ao hash informado.');}
      if (!stored || stored.size !== length) fail(400, 'Arquivo recebido incompleto.');
      await leased(db, job.id, request.headers.get('X-Lease-Id'), runner, clock());
      await db.prepare('INSERT OR IGNORE INTO tc_blobs(sha,size,created_at) VALUES(?,?,?)').bind(blob[1], length, at).run(); return reply({stored: true}, 201);
    }
    if (blob && request.method === 'GET') {const stored = await bucket.get(`tomaconta/objects/${blob[1]}`); if (!stored) fail(404, 'Arquivo inexistente.'); return new Response(stored.body, {headers: {'Content-Type': 'application/octet-stream', 'Cache-Control': 'no-store'}});}
    if (path === '/runner/restore' && request.method === 'POST') {
      if (runner.event !== 'workflow_dispatch') fail(403, 'A restauração exige execução manual.');
      const input = await body(request); exactKeys(input, ['revision', 'expectedCurrent']); await revisionFor(db, bucket, input.revision);
      if (!ID.test(input.expectedCurrent || '')) fail(400, 'Versão atual inválida.');
      const result = await db.batch([
        db.prepare('UPDATE tc_state SET previous_revision=current_revision,current_revision=?,updated_at=? WHERE id=1 AND current_revision=?').bind(input.revision, at, input.expectedCurrent),
        db.prepare("INSERT INTO tc_events(actor,action,revision,created_at) SELECT ?,'restore',?,? WHERE (SELECT current_revision FROM tc_state WHERE id=1)=?").bind(`github:${runner.id}`, input.revision, at, input.revision),
      ]);
      if (!result[0].meta.changes) fail(409, 'A base mudou. Recarregue antes de restaurar.'); return reply({revision: input.revision, restored: true});
    }
    return reply({error: 'Operação inexistente.'}, 404);
  } catch (error) {
    if (error instanceof HttpError) return reply({error: error.message}, error.status, error.headers);
    console.error('Toma Conta shared operation failed', error?.name);
    return reply({error: 'Operação não concluída. A versão publicada foi preservada.'}, 500);
  }
}
