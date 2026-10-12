-- PostgreSQL production-design draft; NOT used by the local SQLite demo.
-- Privacy markers: *_enc = application AEAD encryption, keys stored separately.
-- UUIDs and hashes that can be linked back are personal data, not anonymization.
-- Metadata is access-controlled; logs may contain request IDs/status only.

CREATE TABLE users (
  id uuid PRIMARY KEY,
  hospital_id uuid NOT NULL,
  openid_hmac bytea UNIQUE, -- keyed lookup; raw OpenID is never logged
  openid_enc bytea,        -- only when needed; encrypt with key version
  name_enc bytea,          -- display 王*兰 except authorized exact view
  phone_enc bytea,         -- display middle four digits masked
  birth_date_enc bytea,    -- show age band outside authorized care
  sex_enc bytea,
  role varchar(24) NOT NULL CHECK (role IN ('patient','clinician','volunteer','admin')),
  status varchar(24) NOT NULL,
  key_version varchar(32),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE encounters (
  id uuid PRIMARY KEY,
  patient_id uuid NOT NULL REFERENCES users(id),
  hospital_id uuid NOT NULL,
  admission_no_enc bytea, -- no admission number in public screens or logs
  ward_bed_enc bytea,     -- expose only to necessary assigned caregivers
  allergy_enc bytea,     -- exact clinical value only to patient/authorized care
  admitted_at timestamptz,
  discharged_at timestamptz
);
CREATE TABLE patient_delegates (
  id uuid PRIMARY KEY,
  patient_id uuid NOT NULL REFERENCES users(id),
  delegate_id uuid REFERENCES users(id),
  relationship_enc bytea,
  contact_enc bytea,       -- encrypt family name/phone, mask display
  scopes text[] NOT NULL,  -- contact does not imply record access/signature right
  evidence_object_enc bytea,
  valid_until timestamptz,
  revoked_at timestamptz
);
CREATE TABLE consent_grants (
  id uuid PRIMARY KEY,
  subject_id uuid NOT NULL REFERENCES users(id),
  purpose text NOT NULL,
  data_fields text[] NOT NULL,
  recipient text NOT NULL,
  legal_basis text NOT NULL,
  notice_version text NOT NULL,
  granted_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  evidence_enc bytea       -- notice snapshot/actions, no raw IP in general logs
);
CREATE TABLE medical_records (
  id uuid PRIMARY KEY,
  patient_id uuid NOT NULL REFERENCES users(id),
  encounter_id uuid REFERENCES encounters(id),
  kind text NOT NULL,
  source text NOT NULL,    -- patient_upload / certified_hospital_copy
  object_key_enc bytea,    -- encrypted original, no public permanent URL
  original_hmac bytea,     -- integrity check is not a reliable e-signature
  ocr_text_enc bytea,      -- redact direct identifiers before permitted export
  structured_enc bytea,   -- diagnoses, findings, drugs are sensitive throughout
  confidence numeric,
  review_status text NOT NULL,
  reviewer_id uuid REFERENCES users(id),
  version integer NOT NULL DEFAULT 1,
  supersedes_id uuid REFERENCES medical_records(id),
  retention_until timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE conversations (
  id uuid PRIMARY KEY,
  patient_id uuid NOT NULL REFERENCES users(id),
  domain text NOT NULL CHECK (domain IN ('medical','legal')),
  provider text NOT NULL,
  model_version text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);
CREATE TABLE messages (
  id uuid PRIMARY KEY,
  conversation_id uuid NOT NULL REFERENCES conversations(id),
  role text NOT NULL,
  content_enc bytea NOT NULL, -- input AND generated answer may contain PHI
  citations jsonb NOT NULL DEFAULT '[]', -- public source IDs/version; no PHI
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE medications (
  id uuid PRIMARY KEY,
  patient_id uuid NOT NULL REFERENCES users(id),
  prescription_ref_enc bytea,
  drug_dose_route_enc bytea NOT NULL, -- exact only for authorized clinical view
  schedule_enc bytea,
  adherence_enc bytea,
  source text NOT NULL, -- physician verified order; never AI-prescribed
  verified_by uuid REFERENCES users(id),
  valid_from timestamptz,
  valid_until timestamptz
);
CREATE TABLE devices (
  id uuid PRIMARY KEY,
  patient_id uuid NOT NULL REFERENCES users(id),
  serial_hmac bytea UNIQUE,
  credential_hash bytea NOT NULL,
  source text NOT NULL,
  revoked_at timestamptz
);
CREATE TABLE vitals (
  id uuid PRIMARY KEY,
  patient_id uuid NOT NULL REFERENCES users(id),
  device_id uuid NOT NULL REFERENCES devices(id),
  sample_id text NOT NULL,
  kind text NOT NULL,
  value_enc bytea NOT NULL, -- decrypt in authorized alert worker, not app logs
  unit text NOT NULL,
  quality text NOT NULL,
  measured_at timestamptz NOT NULL,
  received_at timestamptz NOT NULL DEFAULT now(),
  rule_version text,
  UNIQUE(device_id, sample_id)
);
CREATE TABLE informed_consents (
  id uuid PRIMARY KEY,
  patient_id uuid NOT NULL REFERENCES users(id),
  encounter_id uuid NOT NULL REFERENCES encounters(id),
  template_version text NOT NULL,
  status text NOT NULL CHECK (status IN ('draft','clinician_reviewed','explained','signed','archived')),
  document_enc bytea NOT NULL,
  signer_identity_enc bytea,
  explanation_evidence_enc bytea,
  signature_evidence_enc bytea, -- identity/control/time/tamper verification bundle
  document_hash bytea,
  signed_at timestamptz
);
CREATE TABLE emergency_events (
  id uuid PRIMARY KEY,
  patient_id uuid NOT NULL REFERENCES users(id),
  idempotency_key text NOT NULL,
  status text NOT NULL,
  location_enc bytea,      -- minimum necessary hospital location, no continuous GPS
  recipients_enc bytea,    -- per-recipient delivery/ack timestamps, contacts masked
  legal_basis text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(patient_id, idempotency_key)
);
CREATE TABLE outbox (
  id uuid PRIMARY KEY,
  event_id uuid NOT NULL REFERENCES emergency_events(id),
  payload_enc bytea NOT NULL, -- avoid duplicating full record into notification
  status text NOT NULL,
  attempts integer NOT NULL DEFAULT 0,
  next_attempt_at timestamptz
);
CREATE TABLE audit_events (
  id uuid PRIMARY KEY,
  actor_id uuid REFERENCES users(id),
  subject_id uuid REFERENCES users(id),
  action text NOT NULL,
  resource_id uuid,
  result text NOT NULL,
  request_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
  -- immutable privileged store in production; no message/medical body/password
);
CREATE TABLE knowledge_chunks (
  id uuid PRIMARY KEY,
  domain text NOT NULL,
  hospital_id uuid,        -- NULL only for approved public knowledge
  source_url text NOT NULL,
  title text NOT NULL,
  article_no text,
  version text NOT NULL,
  effective_from date,
  effective_until date,
  reviewed_by uuid REFERENCES users(id),
  text_content text NOT NULL -- approved public/clinical education, no patient PHI
  -- Add embedding vector(N) after selecting a local model and fixed dimension.
);
