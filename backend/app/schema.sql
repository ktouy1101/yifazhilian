-- Synthetic-data demo only. No encryption or tamper-evident audit claims.
BEGIN IMMEDIATE;
-- 版本记录（SQLite 用 PRAGMA user_version，MySQL 用这张表）
CREATE TABLE IF NOT EXISTS schema_meta (
  k VARCHAR(64) PRIMARY KEY,
  v VARCHAR(255) NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, role TEXT NOT NULL CHECK(role IN ('patient','volunteer')),
  display_name TEXT NOT NULL, synthetic INTEGER NOT NULL DEFAULT 0 CHECK(synthetic IN (0,1)),
  openid TEXT UNIQUE,
  phone TEXT UNIQUE,
  deleted_at TEXT,
  password_hash TEXT
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
-- M05: structured agent metadata (topic, merged suggestions).
CREATE TABLE IF NOT EXISTS message_metadata (
  message_id INTEGER PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
  data TEXT NOT NULL
);
-- M07: reviewed, versioned public knowledge. Patient data never belongs here.
CREATE TABLE IF NOT EXISTS knowledge_sources (
  id TEXT PRIMARY KEY,
  domain TEXT NOT NULL CHECK(domain IN ('medical','legal')),
  title TEXT NOT NULL,
  publisher TEXT,
  url TEXT,
  document_version TEXT NOT NULL,
  effective_from TEXT,
  effective_until TEXT,
  reviewed_by TEXT,
  reviewed_at TEXT,
  status TEXT NOT NULL CHECK(status IN ('draft','reviewed','published','retired')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS knowledge_sources_domain ON knowledge_sources(domain,status,effective_from);
CREATE TABLE IF NOT EXISTS knowledge_chunks (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
  domain TEXT NOT NULL CHECK(domain IN ('medical','legal')),
  title TEXT NOT NULL,
  text TEXT NOT NULL,
  keywords TEXT NOT NULL DEFAULT '[]',
  position INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS knowledge_chunks_domain ON knowledge_chunks(domain,source_id);
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
  status TEXT NOT NULL CHECK(status='received'), delivery TEXT NOT NULL CHECK(delivery IN ('recorded','mock')),
  created_at TEXT NOT NULL, acknowledged_at TEXT CHECK(acknowledged_at IS NULL),
  message TEXT NOT NULL, UNIQUE(user_id,idempotency_key)
);
CREATE TABLE IF NOT EXISTS audit_events (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), action TEXT NOT NULL,
  object_id TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_owner_time ON audit_events(user_id,created_at);

-- 用户资料（登录后可编辑）
CREATE TABLE IF NOT EXISTS user_profiles (
  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  nickname TEXT, age INTEGER, gender TEXT, bed_location TEXT, allergies TEXT,
  emergency_name TEXT, emergency_phone TEXT, doctor_phone TEXT,
  updated_at TEXT NOT NULL
);

-- 短信验证码（开发阶段固定 123456，生产接短信服务后替换）
CREATE TABLE IF NOT EXISTS verification_codes (
  phone TEXT NOT NULL,
  code TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (phone, code)
);

-- 用药记录（用户自己录入）
CREATE TABLE IF NOT EXISTS medications (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL, dose TEXT, scheduled_time TEXT, note TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS medications_user ON medications(user_id,created_at);

-- 就诊笔记/病历摘要（用户自己记录）
CREATE TABLE IF NOT EXISTS medical_records (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL, summary TEXT, record_date TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS records_user ON medical_records(user_id,created_at);

-- ===== M11 导航采集与审核 =====
-- 导航角色由 memberships 分配，不接受前端自称；patient 默认 browse+feedback，
-- volunteer 可 collect，reviewer 可 review。不建独立 ERP。
CREATE TABLE IF NOT EXISTS navigation_memberships (
  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  hospital_id TEXT NOT NULL DEFAULT 'demo-hospital',
  can_collect INTEGER NOT NULL DEFAULT 0 CHECK(can_collect IN (0,1)),
  can_review INTEGER NOT NULL DEFAULT 0 CHECK(can_review IN (0,1))
);

CREATE TABLE IF NOT EXISTS navigation_tasks (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT,
  hospital_id TEXT NOT NULL DEFAULT 'demo-hospital',
  floor TEXT,
  status TEXT NOT NULL CHECK(status IN ('open','claimed','done')),
  claimed_by TEXT REFERENCES users(id),
  claimed_at TEXT,
  created_at TEXT NOT NULL
);

-- 提交草稿：draft -> submitted -> changes_requested/published -> disabled
-- 只有 draft / changes_requested 可编辑；revision 用于并发冲突检测。
CREATE TABLE IF NOT EXISTS navigation_submissions (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES navigation_tasks(id),
  collector_id TEXT NOT NULL REFERENCES users(id),
  revision INTEGER NOT NULL DEFAULT 1,
  title TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('draft','submitted','changes_requested','published','disabled')),
  privacy_confirmed INTEGER NOT NULL DEFAULT 0,
  walkthrough_confirmed INTEGER NOT NULL DEFAULT 0,
  ar_ready INTEGER NOT NULL DEFAULT 0,
  client_request_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  reviewer_id TEXT REFERENCES users(id),
  reviewed_at TEXT,
  review_note TEXT,
  disabled_reason TEXT,
  UNIQUE(task_id, client_request_id)
);
CREATE INDEX IF NOT EXISTS submissions_collector ON navigation_submissions(collector_id,status);
CREATE INDEX IF NOT EXISTS submissions_review_queue ON navigation_submissions(status,id);

CREATE TABLE IF NOT EXISTS navigation_nodes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  submission_id TEXT NOT NULL REFERENCES navigation_submissions(id) ON DELETE CASCADE,
  node_key TEXT NOT NULL,
  position INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('start','turn','landmark','elevator','stairs','end')),
  floor TEXT,
  direction TEXT,
  description TEXT,
  UNIQUE(submission_id, node_key)
);

-- 采集照片：私有 BLOB，仅所有者或同院审核员可鉴权读取；不公开静态 URL。
-- 一张节点对应一张照片（重拍覆盖），revision 仅记录拍摄时草稿版本。
CREATE TABLE IF NOT EXISTS navigation_media (
  id TEXT PRIMARY KEY,
  submission_id TEXT NOT NULL REFERENCES navigation_submissions(id) ON DELETE CASCADE,
  node_key TEXT NOT NULL,
  revision INTEGER NOT NULL,
  client_upload_id TEXT,
  mime TEXT NOT NULL,
  size INTEGER NOT NULL,
  data BLOB NOT NULL,
  sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(submission_id, node_key)
);

CREATE TABLE IF NOT EXISTS navigation_feedback (
  id TEXT PRIMARY KEY,
  route_id TEXT NOT NULL,
  user_id TEXT NOT NULL REFERENCES users(id),
  category TEXT NOT NULL CHECK(category IN ('closed','misdirected','privacy','other')),
  note TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS feedback_route ON navigation_feedback(route_id,created_at);

-- Immutable submitted versions and decisions survive returns, retakes and disable.
CREATE TABLE IF NOT EXISTS navigation_versions (
  submission_id TEXT NOT NULL REFERENCES navigation_submissions(id),
  revision INTEGER NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(submission_id,revision)
);
CREATE TABLE IF NOT EXISTS navigation_version_media (
  submission_id TEXT NOT NULL, revision INTEGER NOT NULL, node_key TEXT NOT NULL,
  mime TEXT NOT NULL, data BLOB NOT NULL,
  PRIMARY KEY(submission_id,revision,node_key),
  FOREIGN KEY(submission_id,revision) REFERENCES navigation_versions(submission_id,revision)
);
CREATE TABLE IF NOT EXISTS navigation_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  submission_id TEXT NOT NULL REFERENCES navigation_submissions(id),
  actor_id TEXT NOT NULL REFERENCES users(id), action TEXT NOT NULL,
  from_revision INTEGER NOT NULL, revision INTEGER NOT NULL,
  payload TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(submission_id,from_revision,action)
);
CREATE TABLE IF NOT EXISTS navigation_feedback_requests (
  user_id TEXT NOT NULL REFERENCES users(id), request_id TEXT NOT NULL,
  feedback_id TEXT NOT NULL REFERENCES navigation_feedback(id),
  PRIMARY KEY(user_id,request_id)
);
-- M03: immutable source image, independently retained OCR attempts and confirmed versions.
CREATE TABLE IF NOT EXISTS record_documents (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  sha256 TEXT NOT NULL, image BLOB NOT NULL, mime TEXT NOT NULL,
  width INTEGER NOT NULL, height INTEGER NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1, archived_version INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL CHECK(status IN ('uploaded','recognizing','review','failed','archived')),
  draft TEXT NOT NULL, latest_job_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(user_id,sha256)
);
CREATE INDEX IF NOT EXISTS record_documents_owner ON record_documents(user_id,updated_at);
CREATE TABLE IF NOT EXISTS record_ocr_jobs (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES record_documents(id) ON DELETE CASCADE,
  request_id TEXT NOT NULL, status TEXT NOT NULL,
  result TEXT, error TEXT, started_at TEXT NOT NULL, finished_at TEXT,
  UNIQUE(document_id,request_id)
);
CREATE TABLE IF NOT EXISTS record_document_versions (
  document_id TEXT NOT NULL REFERENCES record_documents(id) ON DELETE CASCADE,
  version INTEGER NOT NULL, snapshot TEXT NOT NULL, changes TEXT NOT NULL,
  actor_id TEXT NOT NULL REFERENCES users(id), reason TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(document_id,version)
);
CREATE TABLE IF NOT EXISTS record_document_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id TEXT NOT NULL REFERENCES record_documents(id) ON DELETE CASCADE,
  request_id TEXT NOT NULL, action TEXT NOT NULL, payload TEXT NOT NULL,
  created_at TEXT NOT NULL, UNIQUE(document_id,request_id)
);
-- M04: manual health entries, versioned plans and explicitly self-reported doses.
CREATE TABLE IF NOT EXISTS health_entries (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  request_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
  payload TEXT NOT NULL, measured_at TEXT NOT NULL, created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL, UNIQUE(user_id,request_id)
);
CREATE INDEX IF NOT EXISTS health_entries_owner ON health_entries(user_id,measured_at);
CREATE TABLE IF NOT EXISTS health_medication_plans (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  request_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
  payload TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(user_id,request_id)
);
CREATE TABLE IF NOT EXISTS health_plan_versions (
  plan_id TEXT NOT NULL REFERENCES health_medication_plans(id) ON DELETE CASCADE,
  revision INTEGER NOT NULL, payload TEXT NOT NULL,
  effective_from TEXT NOT NULL, effective_until TEXT,
  PRIMARY KEY(plan_id,revision)
);
CREATE TABLE IF NOT EXISTS health_dose_logs (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  plan_id TEXT NOT NULL REFERENCES health_medication_plans(id) ON DELETE CASCADE,
  scheduled_at TEXT NOT NULL, snapshot TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('taken','skipped','postponed','pending')),
  actual_at TEXT, postponed_until TEXT, note TEXT NOT NULL DEFAULT '',
  revision INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL,
  UNIQUE(user_id,plan_id,scheduled_at)
);
CREATE TABLE IF NOT EXISTS health_followups (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  request_id TEXT NOT NULL, title TEXT NOT NULL, due_at TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '', done INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, UNIQUE(user_id,request_id)
);
-- v9 身份与能力位。users.role 保持 patient/volunteer 不变：它是 CHECK 约束，
-- 加取值要重建整张表，所以额外能力（志愿者、审核员）放在这里。
CREATE TABLE IF NOT EXISTS user_roles (
  user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role       TEXT NOT NULL CHECK(role IN ('patient','volunteer','reviewer')),
  granted_by TEXT REFERENCES users(id),
  granted_at TEXT NOT NULL,
  PRIMARY KEY (user_id, role)
);
CREATE TABLE IF NOT EXISTS volunteer_profiles (
  user_id     TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  hospital_id TEXT NOT NULL DEFAULT 'demo-hospital',
  kinds       TEXT NOT NULL DEFAULT '',
  real_name   TEXT,
  status      TEXT NOT NULL CHECK(status IN ('none','pending','approved','rejected','suspended')),
  note        TEXT,
  reviewed_by TEXT REFERENCES users(id),
  reviewed_at TEXT,
  updated_at  TEXT NOT NULL
);
-- v11 法律帮扶：律师凭证、求助工单与往来消息。
-- 凭证图片只存私有 BLOB，仅本人与审核员可通过鉴权接口读取。
CREATE TABLE IF NOT EXISTS volunteer_credentials (
  id          TEXT PRIMARY KEY,
  user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL CHECK(kind IN ('lawyer_license','legal_aid')),
  mime        TEXT NOT NULL,
  size        INTEGER NOT NULL,
  data        BLOB NOT NULL,
  status      TEXT NOT NULL CHECK(status IN ('pending','approved','rejected')),
  note        TEXT,
  reviewed_by TEXT REFERENCES users(id),
  reviewed_at TEXT,
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS volunteer_credentials_user ON volunteer_credentials(user_id,status);
CREATE TABLE IF NOT EXISTS legal_help_requests (
  id           TEXT PRIMARY KEY,
  patient_id   TEXT NOT NULL REFERENCES users(id),
  topic        TEXT NOT NULL,
  text         TEXT NOT NULL,
  status       TEXT NOT NULL CHECK(status IN ('open','claimed','answered','closed')),
  volunteer_id TEXT REFERENCES users(id),
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS legal_help_requests_status ON legal_help_requests(status,updated_at);
CREATE TABLE IF NOT EXISTS legal_help_messages (
  id         TEXT PRIMARY KEY,
  request_id TEXT NOT NULL REFERENCES legal_help_requests(id) ON DELETE CASCADE,
  sender_id  TEXT NOT NULL REFERENCES users(id),
  role       TEXT NOT NULL CHECK(role IN ('patient','volunteer')),
  text       TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS legal_help_messages_request ON legal_help_messages(request_id,created_at);
-- Database.initialize advances user_version after the data migration commits.
COMMIT;
