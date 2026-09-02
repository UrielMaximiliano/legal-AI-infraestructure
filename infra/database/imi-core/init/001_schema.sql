-- IMI LEG core database
--
-- This database is intentionally independent from the decree RAG database and
-- from the IMI dispositions vector database. The transactional model is in
-- 3NF: catalog values, many-to-many relationships, template variables and
-- document versions have their own relations. JSONB is limited to immutable
-- structured snapshots or one typed variable value; it is not used as a
-- substitute for relational columns.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS auth;
CREATE SCHEMA IF NOT EXISTS imi;
CREATE SCHEMA IF NOT EXISTS audit;

COMMENT ON SCHEMA auth IS
  'Reserved for Better Auth migrations. Do not hand-edit its tables here.';
COMMENT ON SCHEMA imi IS
  'Normalized IMI LEG transactional domain.';
COMMENT ON SCHEMA audit IS
  'Append-only operational audit events.';

CREATE TABLE imi.organizations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code varchar(50) NOT NULL UNIQUE,
  name varchar(200) NOT NULL,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_organizations_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_organizations_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE imi.document_types (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code varchar(50) NOT NULL UNIQUE,
  name varchar(100) NOT NULL,
  active boolean NOT NULL DEFAULT true,
  CONSTRAINT ck_document_types_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_document_types_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE imi.case_types (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code varchar(50) NOT NULL UNIQUE,
  name varchar(100) NOT NULL,
  active boolean NOT NULL DEFAULT true,
  CONSTRAINT ck_case_types_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_case_types_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE imi.case_statuses (
  code varchar(30) PRIMARY KEY,
  name varchar(100) NOT NULL,
  terminal boolean NOT NULL DEFAULT false,
  CONSTRAINT ck_case_statuses_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_case_statuses_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE imi.document_sources (
  code varchar(30) PRIMARY KEY,
  name varchar(100) NOT NULL,
  CONSTRAINT ck_document_sources_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_document_sources_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE imi.document_statuses (
  code varchar(30) PRIMARY KEY,
  name varchar(100) NOT NULL,
  CONSTRAINT ck_document_statuses_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_document_statuses_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE imi.review_statuses (
  code varchar(30) PRIMARY KEY,
  name varchar(100) NOT NULL,
  CONSTRAINT ck_review_statuses_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_review_statuses_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE imi.generation_statuses (
  code varchar(30) PRIMARY KEY,
  name varchar(100) NOT NULL,
  terminal boolean NOT NULL DEFAULT false,
  CONSTRAINT ck_generation_statuses_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_generation_statuses_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE imi.export_statuses (
  code varchar(30) PRIMARY KEY,
  name varchar(100) NOT NULL,
  terminal boolean NOT NULL DEFAULT false,
  CONSTRAINT ck_export_statuses_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_export_statuses_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE imi.identity_document_types (
  code varchar(20) PRIMARY KEY,
  name varchar(100) NOT NULL,
  CONSTRAINT ck_identity_document_types_code_nonempty CHECK (btrim(code) <> '')
);

CREATE TABLE imi.roles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code varchar(50) NOT NULL UNIQUE,
  name varchar(100) NOT NULL,
  CONSTRAINT ck_roles_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_roles_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE imi.organizational_units (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  parent_id uuid REFERENCES imi.organizational_units(id) ON DELETE RESTRICT,
  code varchar(80) NOT NULL UNIQUE,
  name varchar(200) NOT NULL,
  active boolean NOT NULL DEFAULT true,
  CONSTRAINT ck_organizational_units_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_organizational_units_name_nonempty CHECK (btrim(name) <> ''),
  CONSTRAINT ck_organizational_units_not_self_parent CHECK (parent_id IS NULL OR parent_id <> id)
);

CREATE TABLE imi.positions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code varchar(80) NOT NULL UNIQUE,
  name varchar(200) NOT NULL,
  active boolean NOT NULL DEFAULT true,
  CONSTRAINT ck_positions_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_positions_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE imi.employees (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  employee_number varchar(50) NOT NULL UNIQUE,
  first_name varchar(200) NOT NULL,
  last_name varchar(200) NOT NULL,
  identity_document_type_code varchar(20) NOT NULL
    REFERENCES imi.identity_document_types(code) ON DELETE RESTRICT,
  identity_document_number varchar(100) NOT NULL,
  cuil varchar(11) UNIQUE,
  email varchar(320),
  phone varchar(50),
  position_id uuid REFERENCES imi.positions(id) ON DELETE RESTRICT,
  organizational_unit_id uuid REFERENCES imi.organizational_units(id) ON DELETE RESTRICT,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_employees_identity UNIQUE (identity_document_type_code, identity_document_number),
  CONSTRAINT ck_employees_number_nonempty CHECK (btrim(employee_number) <> ''),
  CONSTRAINT ck_employees_first_name_nonempty CHECK (btrim(first_name) <> ''),
  CONSTRAINT ck_employees_last_name_nonempty CHECK (btrim(last_name) <> ''),
  CONSTRAINT ck_employees_identity_number_nonempty CHECK (btrim(identity_document_number) <> '')
);

-- Better Auth owns the user/session/account tables. This relation is the
-- explicit institutional allow-list and keeps roles in the IMI domain.
CREATE TABLE imi.employee_auth_accounts (
  employee_id uuid PRIMARY KEY REFERENCES imi.employees(id) ON DELETE CASCADE,
  auth_user_id varchar(200) NOT NULL UNIQUE,
  enabled boolean NOT NULL DEFAULT true,
  linked_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_employee_auth_accounts_user_nonempty CHECK (btrim(auth_user_id) <> '')
);

CREATE TABLE imi.employee_roles (
  employee_id uuid NOT NULL REFERENCES imi.employees(id) ON DELETE CASCADE,
  role_id uuid NOT NULL REFERENCES imi.roles(id) ON DELETE RESTRICT,
  assigned_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (employee_id, role_id)
);

CREATE TABLE imi.case_files (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_number varchar(50) NOT NULL UNIQUE,
  employee_id uuid NOT NULL REFERENCES imi.employees(id) ON DELETE RESTRICT,
  case_type_id uuid NOT NULL REFERENCES imi.case_types(id) ON DELETE RESTRICT,
  status_code varchar(30) NOT NULL REFERENCES imi.case_statuses(code) ON DELETE RESTRICT,
  title varchar(500) NOT NULL,
  description text,
  opened_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  closed_at timestamptz,
  CONSTRAINT ck_case_files_number_nonempty CHECK (btrim(case_number) <> ''),
  CONSTRAINT ck_case_files_title_nonempty CHECK (btrim(title) <> ''),
  CONSTRAINT ck_case_files_closed_after_opened CHECK (closed_at IS NULL OR closed_at >= opened_at)
);

CREATE TABLE imi.case_status_history (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_file_id uuid NOT NULL REFERENCES imi.case_files(id) ON DELETE CASCADE,
  from_status_code varchar(30) REFERENCES imi.case_statuses(code) ON DELETE RESTRICT,
  to_status_code varchar(30) NOT NULL REFERENCES imi.case_statuses(code) ON DELETE RESTRICT,
  changed_at timestamptz NOT NULL DEFAULT now(),
  changed_by_auth_user_id varchar(200) NOT NULL,
  reason text,
  request_id varchar(128),
  CONSTRAINT ck_case_status_history_actor_nonempty CHECK (btrim(changed_by_auth_user_id) <> '')
);

CREATE TABLE imi.case_designations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_file_id uuid NOT NULL UNIQUE REFERENCES imi.case_files(id) ON DELETE CASCADE,
  position_id uuid NOT NULL REFERENCES imi.positions(id) ON DELETE RESTRICT,
  organizational_unit_id uuid REFERENCES imi.organizational_units(id) ON DELETE RESTRICT,
  start_date date,
  legal_basis text,
  appointing_authority text,
  salary_category varchar(100),
  work_schedule varchar(100),
  observations text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE imi.document_templates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code varchar(100) NOT NULL UNIQUE,
  name varchar(200) NOT NULL,
  document_type_id uuid NOT NULL REFERENCES imi.document_types(id) ON DELETE RESTRICT,
  organization_id uuid NOT NULL REFERENCES imi.organizations(id) ON DELETE RESTRICT,
  jurisdiction varchar(120) NOT NULL DEFAULT 'Corrientes',
  language_code varchar(16) NOT NULL DEFAULT 'es-AR',
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_document_templates_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_document_templates_name_nonempty CHECK (btrim(name) <> ''),
  CONSTRAINT ck_document_templates_jurisdiction_nonempty CHECK (btrim(jurisdiction) <> ''),
  CONSTRAINT ck_document_templates_language_nonempty CHECK (btrim(language_code) <> '')
);

CREATE TABLE imi.document_template_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  template_id uuid NOT NULL REFERENCES imi.document_templates(id) ON DELETE CASCADE,
  version integer NOT NULL,
  issuing_organization_id uuid REFERENCES imi.organizations(id) ON DELETE RESTRICT,
  description text,
  body_template text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (template_id, version),
  CONSTRAINT ck_document_template_versions_version_positive CHECK (version > 0),
  CONSTRAINT ck_document_template_versions_body_nonempty CHECK (btrim(body_template) <> '')
);

CREATE TABLE imi.template_variables (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  template_version_id uuid NOT NULL REFERENCES imi.document_template_versions(id) ON DELETE CASCADE,
  variable_key varchar(100) NOT NULL,
  label varchar(200) NOT NULL,
  data_type varchar(30) NOT NULL,
  required boolean NOT NULL DEFAULT false,
  display_order integer NOT NULL,
  UNIQUE (template_version_id, variable_key),
  UNIQUE (template_version_id, display_order),
  CONSTRAINT ck_template_variables_key_nonempty CHECK (btrim(variable_key) <> ''),
  CONSTRAINT ck_template_variables_label_nonempty CHECK (btrim(label) <> ''),
  CONSTRAINT ck_template_variables_type CHECK (data_type IN ('text', 'integer', 'decimal', 'date', 'boolean', 'person', 'list', 'json')),
  CONSTRAINT ck_template_variables_display_order CHECK (display_order > 0)
);

CREATE TABLE imi.template_normative_references (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  template_version_id uuid NOT NULL REFERENCES imi.document_template_versions(id) ON DELETE CASCADE,
  reference_order integer NOT NULL,
  reference_text text NOT NULL,
  UNIQUE (template_version_id, reference_order),
  CONSTRAINT ck_template_normative_references_order CHECK (reference_order > 0),
  CONSTRAINT ck_template_normative_references_text_nonempty CHECK (btrim(reference_text) <> '')
);

CREATE TABLE imi.documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_file_id uuid NOT NULL REFERENCES imi.case_files(id) ON DELETE RESTRICT,
  template_version_id uuid NOT NULL REFERENCES imi.document_template_versions(id) ON DELETE RESTRICT,
  title varchar(300) NOT NULL,
  status_code varchar(30) NOT NULL REFERENCES imi.document_statuses(code) ON DELETE RESTRICT,
  current_version integer NOT NULL DEFAULT 1,
  created_by_auth_user_id varchar(200) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_documents_title_nonempty CHECK (btrim(title) <> ''),
  CONSTRAINT ck_documents_current_version_positive CHECK (current_version > 0),
  CONSTRAINT ck_documents_actor_nonempty CHECK (btrim(created_by_auth_user_id) <> '')
);

CREATE TABLE imi.document_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL REFERENCES imi.documents(id) ON DELETE CASCADE,
  version integer NOT NULL,
  source_code varchar(30) NOT NULL REFERENCES imi.document_sources(code) ON DELETE RESTRICT,
  content_json jsonb,
  content_text text,
  content_sha256 char(64) NOT NULL,
  edited_by_auth_user_id varchar(200) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (document_id, version),
  CONSTRAINT ck_document_versions_version_positive CHECK (version > 0),
  CONSTRAINT ck_document_versions_content_present CHECK (content_json IS NOT NULL OR content_text IS NOT NULL),
  CONSTRAINT ck_document_versions_json_object CHECK (content_json IS NULL OR jsonb_typeof(content_json) = 'object'),
  CONSTRAINT ck_document_versions_hash CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ck_document_versions_actor_nonempty CHECK (btrim(edited_by_auth_user_id) <> '')
);

-- One row per declared variable and document version. This avoids the old
-- variables JSON array while retaining JSON as the value of a single field.
CREATE TABLE imi.document_variable_values (
  document_version_id uuid NOT NULL REFERENCES imi.document_versions(id) ON DELETE CASCADE,
  template_variable_id uuid NOT NULL REFERENCES imi.template_variables(id) ON DELETE RESTRICT,
  value_json jsonb NOT NULL,
  PRIMARY KEY (document_version_id, template_variable_id),
  CONSTRAINT ck_document_variable_values_json_scalar_or_object CHECK (jsonb_typeof(value_json) IN ('string', 'number', 'boolean', 'object', 'array'))
);

-- The RAG database is physically separate, so these are opaque external IDs;
-- there are deliberately no cross-database foreign keys.
CREATE TABLE imi.document_citations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_version_id uuid NOT NULL REFERENCES imi.document_versions(id) ON DELETE CASCADE,
  citation_id varchar(32) NOT NULL,
  rag_run_id uuid NOT NULL,
  source_document_external_id varchar(256) NOT NULL,
  source_chunk_external_id uuid NOT NULL,
  confirmed boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (document_version_id, citation_id),
  CONSTRAINT ck_document_citations_citation_nonempty CHECK (btrim(citation_id) <> ''),
  CONSTRAINT ck_document_citations_source_nonempty CHECK (btrim(source_document_external_id) <> '')
);

CREATE TABLE imi.generation_operations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_file_id uuid NOT NULL REFERENCES imi.case_files(id) ON DELETE RESTRICT,
  template_version_id uuid NOT NULL REFERENCES imi.document_template_versions(id) ON DELETE RESTRICT,
  mode varchar(10) NOT NULL,
  idempotency_key varchar(128) NOT NULL UNIQUE,
  request_hash char(64) NOT NULL,
  request_id varchar(128) NOT NULL,
  status_code varchar(30) NOT NULL REFERENCES imi.generation_statuses(code) ON DELETE RESTRICT,
  rag_run_id uuid,
  document_id uuid REFERENCES imi.documents(id) ON DELETE SET NULL,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  CONSTRAINT ck_generation_operations_mode CHECK (mode IN ('AI', 'MANUAL')),
  CONSTRAINT ck_generation_operations_request_hash CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ck_generation_operations_request_nonempty CHECK (btrim(request_id) <> '')
);

CREATE TABLE imi.generation_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operation_id uuid NOT NULL REFERENCES imi.generation_operations(id) ON DELETE CASCADE,
  attempt_number integer NOT NULL,
  model varchar(128),
  prompt_sha256 char(64),
  status_code varchar(30) NOT NULL REFERENCES imi.generation_statuses(code) ON DELETE RESTRICT,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  error_code varchar(80),
  error_message text,
  UNIQUE (operation_id, attempt_number),
  CONSTRAINT ck_generation_attempts_number_positive CHECK (attempt_number > 0),
  CONSTRAINT ck_generation_attempts_prompt_hash CHECK (prompt_sha256 IS NULL OR prompt_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE imi.document_reviews (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_version_id uuid NOT NULL REFERENCES imi.document_versions(id) ON DELETE RESTRICT,
  status_code varchar(30) NOT NULL REFERENCES imi.review_statuses(code) ON DELETE RESTRICT,
  requested_by_auth_user_id varchar(200) NOT NULL,
  resolved_by_auth_user_id varchar(200),
  requested_at timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz,
  snapshot_json jsonb NOT NULL,
  snapshot_sha256 char(64) NOT NULL,
  UNIQUE (document_version_id),
  CONSTRAINT ck_document_reviews_snapshot_object CHECK (jsonb_typeof(snapshot_json) = 'object'),
  CONSTRAINT ck_document_reviews_snapshot_hash CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ck_document_reviews_requester_nonempty CHECK (btrim(requested_by_auth_user_id) <> '')
);

CREATE TABLE imi.review_comments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  review_id uuid NOT NULL REFERENCES imi.document_reviews(id) ON DELETE CASCADE,
  parent_comment_id uuid REFERENCES imi.review_comments(id) ON DELETE RESTRICT,
  author_auth_user_id varchar(200) NOT NULL,
  severity varchar(20) NOT NULL,
  status_code varchar(20) NOT NULL,
  body text NOT NULL,
  anchor_json jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz,
  CONSTRAINT ck_review_comments_severity CHECK (severity IN ('INFO', 'WARNING', 'BLOCKING')),
  CONSTRAINT ck_review_comments_status CHECK (status_code IN ('OPEN', 'RESOLVED')),
  CONSTRAINT ck_review_comments_body_nonempty CHECK (btrim(body) <> ''),
  CONSTRAINT ck_review_comments_author_nonempty CHECK (btrim(author_auth_user_id) <> '')
);

CREATE TABLE imi.document_transitions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL REFERENCES imi.documents(id) ON DELETE CASCADE,
  from_status_code varchar(30) REFERENCES imi.document_statuses(code) ON DELETE RESTRICT,
  to_status_code varchar(30) NOT NULL REFERENCES imi.document_statuses(code) ON DELETE RESTRICT,
  action varchar(50) NOT NULL,
  observations text,
  performed_by_auth_user_id varchar(200) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_document_transitions_action_nonempty CHECK (btrim(action) <> ''),
  CONSTRAINT ck_document_transitions_actor_nonempty CHECK (btrim(performed_by_auth_user_id) <> '')
);

CREATE TABLE imi.official_number_sequences (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_type_id uuid NOT NULL REFERENCES imi.document_types(id) ON DELETE RESTRICT,
  issued_year integer NOT NULL,
  UNIQUE (document_type_id, issued_year),
  CONSTRAINT ck_official_number_sequences_year CHECK (issued_year BETWEEN 1900 AND 9999)
);

CREATE TABLE imi.official_document_numbers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL UNIQUE REFERENCES imi.documents(id) ON DELETE RESTRICT,
  sequence_id uuid NOT NULL REFERENCES imi.official_number_sequences(id) ON DELETE RESTRICT,
  official_number integer NOT NULL,
  issued_on date NOT NULL,
  finalized_by_auth_user_id varchar(200) NOT NULL,
  finalized_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (sequence_id, official_number),
  CONSTRAINT ck_official_document_numbers_number_positive CHECK (official_number > 0),
  CONSTRAINT ck_official_document_numbers_actor_nonempty CHECK (btrim(finalized_by_auth_user_id) <> '')
);

CREATE FUNCTION imi.validate_official_document_number_year()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  sequence_year integer;
BEGIN
  SELECT issued_year
  INTO sequence_year
  FROM imi.official_number_sequences
  WHERE id = NEW.sequence_id;

  IF sequence_year IS NULL OR sequence_year <> extract(year FROM NEW.issued_on)::integer THEN
    RAISE EXCEPTION 'official number sequence year does not match issued_on';
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_official_document_number_year
BEFORE INSERT OR UPDATE OF sequence_id, issued_on
ON imi.official_document_numbers
FOR EACH ROW
EXECUTE FUNCTION imi.validate_official_document_number_year();

CREATE TABLE imi.document_exports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_version_id uuid NOT NULL REFERENCES imi.document_versions(id) ON DELETE RESTRICT,
  review_id uuid REFERENCES imi.document_reviews(id) ON DELETE RESTRICT,
  format varchar(10) NOT NULL,
  status_code varchar(30) NOT NULL REFERENCES imi.export_statuses(code) ON DELETE RESTRICT,
  storage_key varchar(500),
  content_sha256 char(64),
  created_by_auth_user_id varchar(200) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  error_code varchar(80),
  error_message text,
  CONSTRAINT ck_document_exports_format CHECK (format IN ('PDF', 'DOCX')),
  CONSTRAINT ck_document_exports_hash CHECK (content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ck_document_exports_actor_nonempty CHECK (btrim(created_by_auth_user_id) <> '')
);

CREATE TABLE imi.export_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  export_id uuid NOT NULL REFERENCES imi.document_exports(id) ON DELETE CASCADE,
  attempt_number integer NOT NULL,
  idempotency_key varchar(128) NOT NULL,
  request_hash char(64) NOT NULL,
  status_code varchar(30) NOT NULL REFERENCES imi.export_statuses(code) ON DELETE RESTRICT,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  error_code varchar(80),
  error_message text,
  UNIQUE (export_id, attempt_number),
  UNIQUE (idempotency_key),
  CONSTRAINT ck_export_attempts_number_positive CHECK (attempt_number > 0),
  CONSTRAINT ck_export_attempts_request_hash CHECK (request_hash ~ '^[0-9a-f]{64}$')
);

CREATE TABLE audit.events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type varchar(80) NOT NULL,
  entity_type varchar(80) NOT NULL,
  entity_id uuid NOT NULL,
  actor_auth_user_id varchar(200),
  request_id varchar(128),
  summary_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_audit_events_event_type_nonempty CHECK (btrim(event_type) <> ''),
  CONSTRAINT ck_audit_events_entity_type_nonempty CHECK (btrim(entity_type) <> ''),
  CONSTRAINT ck_audit_events_summary_object CHECK (jsonb_typeof(summary_json) = 'object')
);

CREATE INDEX ix_employees_active ON imi.employees (active);
CREATE INDEX ix_employees_organization ON imi.employees (organizational_unit_id);
CREATE INDEX ix_case_files_employee ON imi.case_files (employee_id);
CREATE INDEX ix_case_files_status ON imi.case_files (status_code);
CREATE INDEX ix_case_status_history_case ON imi.case_status_history (case_file_id, changed_at DESC);
CREATE INDEX ix_templates_type ON imi.document_templates (document_type_id);
CREATE INDEX ix_templates_active ON imi.document_templates (active);
CREATE UNIQUE INDEX uq_imi_active_template_per_organization_type
  ON imi.document_templates (organization_id, document_type_id)
  WHERE active;
CREATE INDEX ix_documents_case ON imi.documents (case_file_id);
CREATE INDEX ix_documents_status ON imi.documents (status_code);
CREATE INDEX ix_document_versions_document ON imi.document_versions (document_id, version DESC);
CREATE INDEX ix_generation_operations_status ON imi.generation_operations (status_code, started_at DESC);
CREATE INDEX ix_document_reviews_status ON imi.document_reviews (status_code, requested_at DESC);
CREATE INDEX ix_document_transitions_document ON imi.document_transitions (document_id, created_at DESC);
CREATE INDEX ix_official_document_numbers_sequence ON imi.official_document_numbers (sequence_id, official_number);
CREATE INDEX ix_audit_events_entity ON audit.events (entity_type, entity_id, occurred_at DESC);

INSERT INTO imi.organizations (code, name)
VALUES ('IMI', 'Instituto de Modernización e Innovación')
ON CONFLICT (code) DO NOTHING;

INSERT INTO imi.document_types (code, name)
VALUES
  ('DISPOSICION', 'Disposición'),
  ('NOTA_INICIO', 'Nota de inicio')
ON CONFLICT (code) DO NOTHING;

INSERT INTO imi.case_types (code, name)
VALUES ('OTRO', 'Expediente administrativo')
ON CONFLICT (code) DO NOTHING;

INSERT INTO imi.case_statuses (code, name, terminal)
VALUES
  ('DRAFT', 'Borrador', false),
  ('OPEN', 'Abierto', false),
  ('CLOSED', 'Cerrado', true)
ON CONFLICT (code) DO NOTHING;

INSERT INTO imi.document_sources (code, name)
VALUES ('AI', 'Generado por IA'), ('MANUAL', 'Redacción manual'), ('EDITED', 'Edición humana')
ON CONFLICT (code) DO NOTHING;

INSERT INTO imi.document_statuses (code, name)
VALUES
  ('DRAFT', 'Borrador'),
  ('IN_REVIEW', 'En revisión'),
  ('CHANGES_REQUESTED', 'Cambios solicitados'),
  ('APPROVED', 'Aprobado'),
  ('FINALIZED', 'Finalizado')
ON CONFLICT (code) DO NOTHING;

INSERT INTO imi.review_statuses (code, name)
VALUES
  ('IN_REVIEW', 'En revisión'),
  ('CHANGES_REQUESTED', 'Cambios solicitados'),
  ('APPROVED', 'Aprobada'),
  ('FINALIZED', 'Finalizada')
ON CONFLICT (code) DO NOTHING;

INSERT INTO imi.generation_statuses (code, name, terminal)
VALUES
  ('QUEUED', 'En cola', false),
  ('RUNNING', 'Procesando', false),
  ('SUCCEEDED', 'Completada', true),
  ('FAILED', 'Fallida', true),
  ('CANCELLED', 'Cancelada', true)
ON CONFLICT (code) DO NOTHING;

INSERT INTO imi.export_statuses (code, name, terminal)
VALUES
  ('QUEUED', 'En cola', false),
  ('RUNNING', 'Procesando', false),
  ('SUCCEEDED', 'Completada', true),
  ('FAILED', 'Fallida', true)
ON CONFLICT (code) DO NOTHING;

INSERT INTO imi.identity_document_types (code, name)
VALUES ('DNI', 'Documento Nacional de Identidad'), ('PASSPORT', 'Pasaporte')
ON CONFLICT (code) DO NOTHING;

INSERT INTO imi.roles (code, name)
VALUES
  ('OPERATOR', 'Operador'),
  ('LEGAL_REVIEWER', 'Revisor legal'),
  ('ADMIN', 'Administrador')
ON CONFLICT (code) DO NOTHING;

COMMIT;
