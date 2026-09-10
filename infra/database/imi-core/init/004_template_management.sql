-- Configuración editable de plantillas IMI LEG.
-- Se puede ejecutar sobre una base existente y también se carga en instalaciones nuevas.
BEGIN;

CREATE TABLE IF NOT EXISTS imi.template_version_configs (
  template_version_id uuid PRIMARY KEY
    REFERENCES imi.document_template_versions(id) ON DELETE CASCADE,
  status varchar(20) NOT NULL DEFAULT 'DRAFT',
  revision integer NOT NULL DEFAULT 1,
  fields_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  rules_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  blocks_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  instructions text,
  organ_emisor varchar(200),
  normativa text,
  extraction_warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz,
  CONSTRAINT ck_template_version_configs_status
    CHECK (status IN ('DRAFT', 'PUBLISHED', 'ARCHIVED')),
  CONSTRAINT ck_template_version_configs_revision CHECK (revision > 0),
  CONSTRAINT ck_template_version_configs_fields_array
    CHECK (jsonb_typeof(fields_json) = 'array'),
  CONSTRAINT ck_template_version_configs_rules_array
    CHECK (jsonb_typeof(rules_json) = 'array'),
  CONSTRAINT ck_template_version_configs_blocks_array
    CHECK (jsonb_typeof(blocks_json) = 'array'),
  CONSTRAINT ck_template_version_configs_warnings_array
    CHECK (jsonb_typeof(extraction_warnings) = 'array')
);

-- These columns make the migration safe for the core volume that predates
-- configurable template management.
ALTER TABLE imi.template_version_configs
  ADD COLUMN IF NOT EXISTS organ_emisor varchar(200),
  ADD COLUMN IF NOT EXISTS normativa text;

CREATE INDEX IF NOT EXISTS ix_template_version_configs_status
  ON imi.template_version_configs (status);

CREATE TABLE IF NOT EXISTS imi.template_import_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name varchar(200) NOT NULL,
  document_type varchar(50) NOT NULL,
  original_filename varchar(255) NOT NULL,
  content_type varchar(120),
  source_bytes bytea NOT NULL,
  status varchar(20) NOT NULL DEFAULT 'QUEUED',
  stage varchar(30) NOT NULL DEFAULT 'uploading',
  progress integer NOT NULL DEFAULT 0,
  pages_total integer,
  pages_processed integer NOT NULL DEFAULT 0,
  body_template text,
  blocks_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  warnings_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  error text,
  retryable boolean NOT NULL DEFAULT false,
  template_version_id uuid REFERENCES imi.document_template_versions(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_template_import_jobs_status
    CHECK (status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')),
  CONSTRAINT ck_template_import_jobs_progress CHECK (progress BETWEEN 0 AND 100),
  CONSTRAINT ck_template_import_jobs_pages CHECK (
    (pages_total IS NULL OR pages_total >= 0) AND pages_processed >= 0
  ),
  CONSTRAINT ck_template_import_jobs_blocks_array
    CHECK (jsonb_typeof(blocks_json) = 'array'),
  CONSTRAINT ck_template_import_jobs_warnings_array
    CHECK (jsonb_typeof(warnings_json) = 'array')
);

CREATE INDEX IF NOT EXISTS ix_template_import_jobs_status
  ON imi.template_import_jobs (status, updated_at DESC);

CREATE TABLE IF NOT EXISTS imi.template_analysis_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  status varchar(20) NOT NULL DEFAULT 'QUEUED',
  payload_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  suggestions_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  warnings_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_template_analysis_jobs_status
    CHECK (status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')),
  CONSTRAINT ck_template_analysis_jobs_payload_object
    CHECK (jsonb_typeof(payload_json) = 'object'),
  CONSTRAINT ck_template_analysis_jobs_suggestions_array
    CHECK (jsonb_typeof(suggestions_json) = 'array'),
  CONSTRAINT ck_template_analysis_jobs_warnings_array
    CHECK (jsonb_typeof(warnings_json) = 'array')
);

CREATE INDEX IF NOT EXISTS ix_template_analysis_jobs_status
  ON imi.template_analysis_jobs (status, updated_at DESC);

CREATE TABLE IF NOT EXISTS imi.template_idempotency (
  operation varchar(40) NOT NULL,
  idempotency_key varchar(128) NOT NULL,
  request_hash char(64) NOT NULL,
  response_json jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (operation, idempotency_key),
  CONSTRAINT ck_template_idempotency_hash CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ck_template_idempotency_response_object
    CHECK (jsonb_typeof(response_json) = 'object')
);

-- Multiple active models of the same catalog type are valid in the manager.
DROP INDEX IF EXISTS imi.uq_imi_active_template_per_organization_type;
CREATE INDEX IF NOT EXISTS ix_imi_active_template_per_organization_type
  ON imi.document_templates (organization_id, document_type_id) WHERE active;

-- Generic templates use the same catalog as the editor.  Official IMI models
-- remain the only seeded documents; these rows only make the catalog explicit.
INSERT INTO imi.document_types (code, name)
VALUES
  ('RESOLUCION', 'Resolución'),
  ('INFORME', 'Informe'),
  ('OFICIO', 'Oficio'),
  ('SOLICITUD', 'Solicitud'),
  ('ACUERDO', 'Acuerdo'),
  ('DECRETO', 'Decreto'),
  ('OTROS', 'Otros')
ON CONFLICT (code) DO UPDATE SET active = true;

COMMIT;
