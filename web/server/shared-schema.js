// The financial service uses its own D1 binding and R2 bucket.
export const SCHEMA = [
  `CREATE TABLE IF NOT EXISTS tc_state (id INTEGER PRIMARY KEY CHECK(id=1), current_revision TEXT, previous_revision TEXT, updated_at TEXT)`,
  `INSERT OR IGNORE INTO tc_state(id) VALUES(1)`,
  `CREATE TABLE IF NOT EXISTS tc_jobs (
    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, plan_hash TEXT NOT NULL,
    kind TEXT NOT NULL, params TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, created_ms INTEGER NOT NULL, updated_ms INTEGER NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0, runner_id TEXT, lease_id TEXT, lease_until INTEGER,
    base_revision TEXT, base_initialized INTEGER NOT NULL DEFAULT 0,
    progress REAL NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT 'Aguardando executor', error TEXT, result TEXT)`,
  `CREATE INDEX IF NOT EXISTS tc_jobs_status ON tc_jobs(status, created_ms)`,
  `CREATE UNIQUE INDEX IF NOT EXISTS tc_jobs_active_plan ON tc_jobs(plan_hash) WHERE status IN ('queued','running')`,
  `CREATE TABLE IF NOT EXISTS tc_blobs (sha TEXT PRIMARY KEY, size INTEGER NOT NULL, created_at TEXT NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS tc_revisions (
    id TEXT PRIMARY KEY, job_id TEXT NOT NULL, parent_revision TEXT,
    manifest_key TEXT NOT NULL, manifest_sha TEXT NOT NULL, summary TEXT NOT NULL,
    created_at TEXT NOT NULL, published_at TEXT)`,
  `CREATE TABLE IF NOT EXISTS tc_events (id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL, action TEXT NOT NULL, revision TEXT, created_at TEXT NOT NULL)`,
];
