-- Synthetic-data demo only. No encryption or tamper-evident audit claims.
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, role TEXT NOT NULL CHECK(role IN ('patient','volunteer')),
  display_name TEXT NOT NULL, synthetic INTEGER NOT NULL DEFAULT 1 CHECK(synthetic=1)
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY CHECK(length(token_hash)=64),
  user_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);
CREATE TABLE IF NOT EXISTS consents (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  scope TEXT NOT NULL CHECK(scope IN ('ai_medical','ai_legal','vitals','records_read')),
  granted INTEGER NOT NULL CHECK(granted IN (0,1)), policy_version TEXT NOT NULL,
  recipient TEXT NOT NULL, purpose TEXT NOT NULL, created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL, revoked_at TEXT, UNIQUE(user_id,scope)
);
CREATE TABLE IF NOT EXISTS consent_fields (
  consent_id TEXT NOT NULL REFERENCES consents(id) ON DELETE CASCADE,
  field_name TEXT NOT NULL, PRIMARY KEY(consent_id,field_name)
);
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  domain TEXT NOT NULL CHECK(domain IN ('medical','legal')), created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS conversations_owner ON conversations(user_id,id);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK(role IN ('user','assistant')), text TEXT NOT NULL,
  provider TEXT, retrieval TEXT, disclaimer TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id,id);
CREATE TABLE IF NOT EXISTS message_sources (
  message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE, position INTEGER NOT NULL,
  source_id TEXT NOT NULL, domain TEXT NOT NULL CHECK(domain IN ('medical','legal')),
  title TEXT NOT NULL, text TEXT NOT NULL, url TEXT, PRIMARY KEY(message_id,position)
);
CREATE TABLE IF NOT EXISTS vitals (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), sample_id TEXT NOT NULL,
  source TEXT NOT NULL CHECK(source='demo_device'),
  kind TEXT NOT NULL CHECK(kind IN ('heart_rate','spo2','systolic_bp','diastolic_bp')),
  value REAL NOT NULL, unit TEXT NOT NULL CHECK(unit IN ('bpm','%','mmHg')),
  measured_at TEXT NOT NULL, quality TEXT NOT NULL CHECK(quality='good'),
  alert_status TEXT NOT NULL CHECK(alert_status IN ('demo_review','demo_no_flag')),
  alert_message TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(user_id,source,sample_id)
);
CREATE TABLE IF NOT EXISTS emergency_events (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), idempotency_key TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status='received'), delivery TEXT NOT NULL CHECK(delivery='mock'),
  created_at TEXT NOT NULL, acknowledged_at TEXT CHECK(acknowledged_at IS NULL),
  message TEXT NOT NULL, UNIQUE(user_id,idempotency_key)
);
CREATE TABLE IF NOT EXISTS audit_events (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), action TEXT NOT NULL,
  object_id TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_owner_time ON audit_events(user_id,created_at);
PRAGMA user_version = 1;
COMMIT;
