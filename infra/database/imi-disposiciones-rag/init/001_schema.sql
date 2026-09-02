-- IMI LEG isolated 0.6B legal-corpus database
--
-- This is a vector-only re-embedded copy of the reviewed legal corpus. The
-- legacy legal_ai database remains intact and is never queried by IMI LEG.
-- There are no foreign keys to imi_leg_core: cross-database references are
-- opaque IDs recorded by the integration layer.

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS rag;
CREATE SCHEMA IF NOT EXISTS audit;

COMMENT ON SCHEMA rag IS
  'Normalized legal corpus, 0.6B/1024 embeddings and retrieval data only.';
COMMENT ON SCHEMA audit IS
  'Append-only RAG operational audit events.';

CREATE TABLE rag.document_types (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code varchar(50) NOT NULL UNIQUE,
  name varchar(100) NOT NULL,
  active boolean NOT NULL DEFAULT true,
  CONSTRAINT ck_rag_document_types_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_rag_document_types_name_nonempty CHECK (btrim(name) <> ''),
  CONSTRAINT ck_rag_document_types_only_decrees CHECK (code = 'DECRETO')
);

CREATE TABLE rag.document_subtypes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_type_id uuid NOT NULL REFERENCES rag.document_types(id) ON DELETE RESTRICT,
  code varchar(100) NOT NULL,
  name varchar(150) NOT NULL,
  active boolean NOT NULL DEFAULT true,
  UNIQUE (document_type_id, code),
  UNIQUE (id, document_type_id),
  CONSTRAINT ck_rag_document_subtypes_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_rag_document_subtypes_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE rag.jurisdictions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code varchar(80) NOT NULL UNIQUE,
  name varchar(150) NOT NULL,
  active boolean NOT NULL DEFAULT true,
  CONSTRAINT ck_rag_jurisdictions_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_rag_jurisdictions_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE rag.organizations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code varchar(80) NOT NULL UNIQUE,
  name varchar(200) NOT NULL,
  active boolean NOT NULL DEFAULT true,
  CONSTRAINT ck_rag_organizations_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_rag_organizations_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE rag.languages (
  code varchar(16) PRIMARY KEY,
  name varchar(100) NOT NULL,
  CONSTRAINT ck_rag_languages_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_rag_languages_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE rag.source_catalog (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code varchar(100) NOT NULL UNIQUE,
  name varchar(255) NOT NULL,
  base_url varchar(2048),
  active boolean NOT NULL DEFAULT true,
  CONSTRAINT ck_rag_source_catalog_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_rag_source_catalog_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE rag.review_statuses (
  code varchar(30) PRIMARY KEY,
  name varchar(100) NOT NULL,
  CONSTRAINT ck_rag_review_statuses_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_rag_review_statuses_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE rag.ingestion_statuses (
  code varchar(30) PRIMARY KEY,
  name varchar(100) NOT NULL,
  CONSTRAINT ck_rag_ingestion_statuses_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_rag_ingestion_statuses_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE rag.embedding_statuses (
  code varchar(30) PRIMARY KEY,
  name varchar(100) NOT NULL,
  CONSTRAINT ck_rag_embedding_statuses_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_rag_embedding_statuses_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE rag.chunk_states (
  code varchar(30) PRIMARY KEY,
  name varchar(100) NOT NULL,
  CONSTRAINT ck_rag_chunk_states_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_rag_chunk_states_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE rag.provenance_types (
  code varchar(30) PRIMARY KEY,
  name varchar(100) NOT NULL,
  CONSTRAINT ck_rag_provenance_types_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_rag_provenance_types_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE rag.generation_statuses (
  code varchar(30) PRIMARY KEY,
  name varchar(100) NOT NULL,
  terminal boolean NOT NULL DEFAULT false,
  CONSTRAINT ck_rag_generation_statuses_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_rag_generation_statuses_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE rag.retrieval_statuses (
  code varchar(30) PRIMARY KEY,
  name varchar(100) NOT NULL,
  terminal boolean NOT NULL DEFAULT false,
  CONSTRAINT ck_rag_retrieval_statuses_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_rag_retrieval_statuses_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE rag.embedding_models (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  model_name varchar(128) NOT NULL UNIQUE,
  dimensions integer NOT NULL,
  storage_type varchar(20) NOT NULL,
  active boolean NOT NULL DEFAULT true,
  CONSTRAINT ck_rag_embedding_models_name_nonempty CHECK (btrim(model_name) <> ''),
  CONSTRAINT ck_rag_embedding_models_dimensions CHECK (dimensions > 0),
  CONSTRAINT ck_rag_embedding_models_storage_type CHECK (storage_type IN ('halfvec', 'vector'))
);

CREATE TABLE rag.runtime_profiles (
  code varchar(50) PRIMARY KEY,
  embedding_model varchar(128) NOT NULL,
  embedding_dimensions integer NOT NULL,
  embedding_context_length integer NOT NULL,
  rag_context_length integer NOT NULL,
  generation_model varchar(128) NOT NULL,
  generation_context_length integer NOT NULL,
  top_k integer NOT NULL,
  candidate_pool_size integer NOT NULL,
  minimum_score numeric(8,7) NOT NULL,
  active boolean NOT NULL DEFAULT true,
  CONSTRAINT ck_rag_runtime_profiles_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_rag_runtime_profiles_dimensions CHECK (embedding_dimensions > 0),
  CONSTRAINT ck_rag_runtime_profiles_contexts CHECK (
    embedding_context_length > 0 AND rag_context_length > 0 AND generation_context_length > 0
  ),
  CONSTRAINT ck_rag_runtime_profiles_retrieval CHECK (
    top_k BETWEEN 1 AND 50 AND candidate_pool_size >= top_k AND minimum_score BETWEEN 0 AND 1
  )
);

CREATE TABLE rag.evaluation_splits (
  code varchar(30) PRIMARY KEY,
  name varchar(100) NOT NULL,
  CONSTRAINT ck_rag_evaluation_splits_code_nonempty CHECK (btrim(code) <> ''),
  CONSTRAINT ck_rag_evaluation_splits_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE rag.corpus_documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  external_id varchar(256) NOT NULL UNIQUE,
  title varchar(500),
  document_type_id uuid NOT NULL REFERENCES rag.document_types(id) ON DELETE RESTRICT,
  document_subtype_id uuid,
  jurisdiction_id uuid NOT NULL REFERENCES rag.jurisdictions(id) ON DELETE RESTRICT,
  organization_id uuid REFERENCES rag.organizations(id) ON DELETE RESTRICT,
  language_code varchar(16) NOT NULL REFERENCES rag.languages(code) ON DELETE RESTRICT,
  source_id uuid NOT NULL REFERENCES rag.source_catalog(id) ON DELETE RESTRICT,
  source_identifier varchar(512) NOT NULL,
  source_url varchar(2048),
  publication_date date,
  provenance_type_code varchar(30) NOT NULL REFERENCES rag.provenance_types(code) ON DELETE RESTRICT,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_id, source_identifier),
  CONSTRAINT fk_rag_corpus_documents_subtype_type
    FOREIGN KEY (document_subtype_id, document_type_id)
    REFERENCES rag.document_subtypes(id, document_type_id)
    ON DELETE RESTRICT,
  CONSTRAINT ck_rag_corpus_documents_external_id_nonempty CHECK (btrim(external_id) <> ''),
  CONSTRAINT ck_rag_corpus_documents_source_identifier_nonempty CHECK (btrim(source_identifier) <> '')
);

CREATE TABLE rag.corpus_document_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL REFERENCES rag.corpus_documents(id) ON DELETE CASCADE,
  version integer NOT NULL,
  raw_content text NOT NULL,
  raw_content_sha256 char(64) NOT NULL,
  normalized_content text NOT NULL,
  normalized_content_sha256 char(64) NOT NULL,
  review_status_code varchar(30) NOT NULL REFERENCES rag.review_statuses(code) ON DELETE RESTRICT,
  reviewed_by_auth_user_id varchar(200),
  reviewed_at timestamptz,
  review_notes text,
  ingestion_status_code varchar(30) NOT NULL REFERENCES rag.ingestion_statuses(code) ON DELETE RESTRICT,
  embedding_status_code varchar(30) NOT NULL REFERENCES rag.embedding_statuses(code) ON DELETE RESTRICT,
  pipeline_version varchar(100) NOT NULL,
  normalization_version varchar(100) NOT NULL,
  chunking_version varchar(100) NOT NULL,
  is_active boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (document_id, version),
  CONSTRAINT ck_rag_corpus_document_versions_version_positive CHECK (version > 0),
  CONSTRAINT ck_rag_corpus_document_versions_hashes CHECK (
    raw_content_sha256 ~ '^[0-9a-f]{64}' AND
    normalized_content_sha256 ~ '^[0-9a-f]{64}'
  ),
  CONSTRAINT ck_rag_corpus_document_versions_review_actor CHECK (
    (review_status_code = 'REVIEWED' AND reviewed_by_auth_user_id IS NOT NULL AND reviewed_at IS NOT NULL)
    OR review_status_code <> 'REVIEWED'
  )
);

CREATE TABLE rag.corpus_document_version_splits (
  document_version_id uuid NOT NULL REFERENCES rag.corpus_document_versions(id) ON DELETE CASCADE,
  split_code varchar(30) NOT NULL REFERENCES rag.evaluation_splits(code) ON DELETE RESTRICT,
  assigned_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (document_version_id, split_code)
);

CREATE TABLE rag.corpus_chunks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_version_id uuid NOT NULL REFERENCES rag.corpus_document_versions(id) ON DELETE CASCADE,
  generation integer NOT NULL,
  state_code varchar(30) NOT NULL REFERENCES rag.chunk_states(code) ON DELETE RESTRICT,
  section_type varchar(40) NOT NULL,
  section_index integer NOT NULL,
  paragraph_index integer NOT NULL,
  article_number varchar(50),
  content text NOT NULL,
  content_sha256 char(64) NOT NULL,
  token_count integer NOT NULL,
  embedding_model_id uuid REFERENCES rag.embedding_models(id) ON DELETE RESTRICT,
  embedding halfvec(1024),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (document_version_id, generation, section_index, paragraph_index),
  UNIQUE (document_version_id, generation, content_sha256),
  CONSTRAINT ck_rag_corpus_chunks_generation_positive CHECK (generation > 0),
  CONSTRAINT ck_rag_corpus_chunks_indexes_nonnegative CHECK (section_index >= 0 AND paragraph_index >= 0),
  CONSTRAINT ck_rag_corpus_chunks_content_nonempty CHECK (btrim(content) <> ''),
  CONSTRAINT ck_rag_corpus_chunks_hash CHECK (content_sha256 ~ '^[0-9a-f]{64}'),
  CONSTRAINT ck_rag_corpus_chunks_token_count CHECK (token_count > 0),
  CONSTRAINT ck_rag_corpus_chunks_embedding_pair CHECK ((embedding IS NULL) = (embedding_model_id IS NULL))
);

CREATE TABLE rag.ingestion_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  pipeline_version varchar(100) NOT NULL,
  status_code varchar(30) NOT NULL REFERENCES rag.ingestion_statuses(code) ON DELETE RESTRICT,
  requested_by varchar(200) NOT NULL,
  request_id varchar(128) NOT NULL,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  error_code varchar(80),
  error_message text,
  CONSTRAINT ck_rag_ingestion_runs_pipeline_nonempty CHECK (btrim(pipeline_version) <> ''),
  CONSTRAINT ck_rag_ingestion_runs_requester_nonempty CHECK (btrim(requested_by) <> ''),
  CONSTRAINT ck_rag_ingestion_runs_request_nonempty CHECK (btrim(request_id) <> '')
);

CREATE TABLE rag.ingestion_run_documents (
  ingestion_run_id uuid NOT NULL REFERENCES rag.ingestion_runs(id) ON DELETE CASCADE,
  document_version_id uuid NOT NULL REFERENCES rag.corpus_document_versions(id) ON DELETE RESTRICT,
  status_code varchar(30) NOT NULL REFERENCES rag.ingestion_statuses(code) ON DELETE RESTRICT,
  error_code varchar(80),
  error_message text,
  PRIMARY KEY (ingestion_run_id, document_version_id)
);

CREATE TABLE rag.ingestion_failures (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ingestion_run_id uuid NOT NULL REFERENCES rag.ingestion_runs(id) ON DELETE CASCADE,
  external_document_id varchar(256),
  stage varchar(40) NOT NULL,
  error_code varchar(80) NOT NULL,
  error_message text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_rag_ingestion_failures_stage_nonempty CHECK (btrim(stage) <> ''),
  CONSTRAINT ck_rag_ingestion_failures_code_nonempty CHECK (btrim(error_code) <> '')
);

CREATE TABLE rag.embedding_batches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ingestion_run_id uuid REFERENCES rag.ingestion_runs(id) ON DELETE SET NULL,
  embedding_model_id uuid NOT NULL REFERENCES rag.embedding_models(id) ON DELETE RESTRICT,
  status_code varchar(30) NOT NULL REFERENCES rag.embedding_statuses(code) ON DELETE RESTRICT,
  requested_count integer NOT NULL DEFAULT 0,
  completed_count integer NOT NULL DEFAULT 0,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  CONSTRAINT ck_rag_embedding_batches_counts CHECK (requested_count >= 0 AND completed_count >= 0 AND completed_count <= requested_count)
);

CREATE TABLE rag.embedding_batch_chunks (
  batch_id uuid NOT NULL REFERENCES rag.embedding_batches(id) ON DELETE CASCADE,
  chunk_id uuid NOT NULL REFERENCES rag.corpus_chunks(id) ON DELETE RESTRICT,
  status_code varchar(30) NOT NULL REFERENCES rag.embedding_statuses(code) ON DELETE RESTRICT,
  attempt_number integer NOT NULL DEFAULT 1,
  PRIMARY KEY (batch_id, chunk_id),
  CONSTRAINT ck_rag_embedding_batch_chunks_attempt CHECK (attempt_number > 0)
);

-- Retrieval filters are first-class columns instead of a JSON blob. The core
-- operation, case and template IDs are intentionally external UUIDs.
CREATE TABLE rag.retrieval_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  core_operation_id uuid,
  core_case_file_id uuid,
  core_template_version_id uuid,
  document_type_id uuid NOT NULL REFERENCES rag.document_types(id) ON DELETE RESTRICT,
  document_subtype_id uuid,
  jurisdiction_id uuid NOT NULL REFERENCES rag.jurisdictions(id) ON DELETE RESTRICT,
  organization_id uuid REFERENCES rag.organizations(id) ON DELETE RESTRICT,
  language_code varchar(16) NOT NULL REFERENCES rag.languages(code) ON DELETE RESTRICT,
  required_review_status_code varchar(30) NOT NULL REFERENCES rag.review_statuses(code) ON DELETE RESTRICT,
  required_split_code varchar(30) NOT NULL REFERENCES rag.evaluation_splits(code) ON DELETE RESTRICT,
  query_sha256 char(64) NOT NULL,
  top_k integer NOT NULL,
  candidate_pool_size integer NOT NULL,
  minimum_score numeric(8,7) NOT NULL DEFAULT 0,
  status_code varchar(30) NOT NULL REFERENCES rag.retrieval_statuses(code) ON DELETE RESTRICT,
  retrieved_count integer NOT NULL DEFAULT 0,
  selected_count integer NOT NULL DEFAULT 0,
  request_id varchar(128) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  CONSTRAINT ck_rag_retrieval_runs_query_hash CHECK (query_sha256 ~ '^[0-9a-f]{64}'),
  CONSTRAINT ck_rag_retrieval_runs_limits CHECK (top_k BETWEEN 1 AND 50 AND candidate_pool_size >= top_k),
  CONSTRAINT ck_rag_retrieval_runs_score CHECK (minimum_score BETWEEN 0 AND 1),
  CONSTRAINT ck_rag_retrieval_runs_counts CHECK (retrieved_count >= 0 AND selected_count >= 0 AND selected_count <= retrieved_count),
  CONSTRAINT ck_rag_retrieval_runs_request_nonempty CHECK (btrim(request_id) <> ''),
  CONSTRAINT fk_rag_retrieval_runs_subtype_type
    FOREIGN KEY (document_subtype_id, document_type_id)
    REFERENCES rag.document_subtypes(id, document_type_id)
    ON DELETE RESTRICT
);

CREATE TABLE rag.retrieval_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  retrieval_run_id uuid NOT NULL REFERENCES rag.retrieval_runs(id) ON DELETE CASCADE,
  chunk_id uuid NOT NULL REFERENCES rag.corpus_chunks(id) ON DELETE RESTRICT,
  retrieval_rank integer NOT NULL,
  similarity_score numeric(8,7) NOT NULL,
  selected boolean NOT NULL DEFAULT false,
  exclusion_reason varchar(40),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (retrieval_run_id, chunk_id),
  UNIQUE (retrieval_run_id, retrieval_rank),
  CONSTRAINT ck_rag_retrieval_results_rank CHECK (retrieval_rank > 0),
  CONSTRAINT ck_rag_retrieval_results_score CHECK (similarity_score BETWEEN 0 AND 1),
  CONSTRAINT ck_rag_retrieval_results_exclusion CHECK (selected OR exclusion_reason IS NOT NULL)
);

CREATE TABLE rag.generation_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  core_operation_id uuid,
  core_document_id uuid,
  core_document_version_id uuid,
  retrieval_run_id uuid NOT NULL REFERENCES rag.retrieval_runs(id) ON DELETE RESTRICT,
  status_code varchar(30) NOT NULL REFERENCES rag.generation_statuses(code) ON DELETE RESTRICT,
  embedding_model_id uuid NOT NULL REFERENCES rag.embedding_models(id) ON DELETE RESTRICT,
  generation_model varchar(128) NOT NULL,
  prompt_version varchar(64) NOT NULL,
  schema_version integer NOT NULL,
  request_hash char(64) NOT NULL,
  idempotency_key_hash char(64),
  profile_code varchar(50) NOT NULL DEFAULT 'imi_leg_06b',
  context_hash char(64),
  prompt_hash char(64),
  retrieved_count integer NOT NULL DEFAULT 0,
  selected_count integer NOT NULL DEFAULT 0,
  context_bytes integer NOT NULL DEFAULT 0,
  context_tokens_estimate integer NOT NULL DEFAULT 0,
  schema_repair_count integer NOT NULL DEFAULT 0,
  retrieval_duration_ms integer,
  generation_duration_ms integer,
  validation_duration_ms integer,
  total_duration_ms integer,
  request_id varchar(128) NOT NULL,
  started_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  error_code varchar(80),
  error_message text,
  CONSTRAINT ck_rag_generation_runs_model_nonempty CHECK (btrim(generation_model) <> ''),
  CONSTRAINT ck_rag_generation_runs_prompt_nonempty CHECK (btrim(prompt_version) <> ''),
  CONSTRAINT ck_rag_generation_runs_schema_positive CHECK (schema_version > 0),
  CONSTRAINT ck_rag_generation_runs_request_hash CHECK (request_hash ~ '^[0-9a-f]{64}'),
  CONSTRAINT ck_rag_generation_runs_idempotency_hash CHECK (idempotency_key_hash IS NULL OR idempotency_key_hash ~ '^[0-9a-f]{64}'),
  CONSTRAINT ck_rag_generation_runs_counts CHECK (retrieved_count >= 0 AND selected_count >= 0 AND selected_count <= retrieved_count),
  CONSTRAINT ck_rag_generation_runs_hashes CHECK (
    (context_hash IS NULL OR context_hash ~ '^[0-9a-f]{64}') AND
    (prompt_hash IS NULL OR prompt_hash ~ '^[0-9a-f]{64}')
  ),
  CONSTRAINT ck_rag_generation_runs_request_nonempty CHECK (btrim(request_id) <> '')
);

CREATE TABLE rag.generation_outputs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  generation_run_id uuid NOT NULL UNIQUE REFERENCES rag.generation_runs(id) ON DELETE RESTRICT,
  schema_version integer NOT NULL,
  content_json jsonb NOT NULL,
  content_sha256 char(64) NOT NULL,
  citation_count integer NOT NULL,
  warning_count integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_rag_generation_outputs_schema_positive CHECK (schema_version > 0),
  CONSTRAINT ck_rag_generation_outputs_object CHECK (jsonb_typeof(content_json) = 'object'),
  CONSTRAINT ck_rag_generation_outputs_hash CHECK (content_sha256 ~ '^[0-9a-f]{64}'),
  CONSTRAINT ck_rag_generation_outputs_counts CHECK (citation_count >= 0 AND warning_count >= 0)
);

CREATE TABLE audit.events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type varchar(80) NOT NULL,
  entity_type varchar(80) NOT NULL,
  entity_id uuid NOT NULL,
  request_id varchar(128),
  summary_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_rag_audit_events_event_type_nonempty CHECK (btrim(event_type) <> ''),
  CONSTRAINT ck_rag_audit_events_entity_type_nonempty CHECK (btrim(entity_type) <> ''),
  CONSTRAINT ck_rag_audit_events_summary_object CHECK (jsonb_typeof(summary_json) = 'object')
);

CREATE UNIQUE INDEX uq_rag_corpus_document_versions_active
  ON rag.corpus_document_versions (document_id)
  WHERE is_active;

CREATE INDEX ix_rag_corpus_documents_filters
  ON rag.corpus_documents (document_type_id, jurisdiction_id, organization_id, active);
CREATE INDEX ix_rag_corpus_document_versions_review
  ON rag.corpus_document_versions (review_status_code, is_active);
CREATE INDEX ix_rag_corpus_chunks_document_version
  ON rag.corpus_chunks (document_version_id, generation, state_code);
CREATE INDEX ix_rag_retrieval_runs_created
  ON rag.retrieval_runs (created_at DESC);
CREATE INDEX ix_rag_generation_runs_status
  ON rag.generation_runs (status_code, started_at DESC);
CREATE INDEX ix_rag_audit_events_entity
  ON audit.events (entity_type, entity_id, occurred_at DESC);

-- Centralized eligibility contract used by retrieval adapters. A document
-- must be active, reviewed, in the requested evaluation split and have an
-- active chunk with a 1024-dimensional halfvec embedding.
CREATE VIEW rag.eligible_legal_chunks AS
SELECT
  d.id AS document_id,
  d.external_id,
  d.title,
  d.document_subtype_id,
  d.jurisdiction_id,
  d.organization_id,
  v.id AS document_version_id,
  v.version,
  c.id AS chunk_id,
  c.section_type,
  c.section_index,
  c.paragraph_index,
  c.article_number,
  c.content,
  c.embedding
FROM rag.corpus_documents AS d
JOIN rag.corpus_document_versions AS v
  ON v.document_id = d.id
JOIN rag.corpus_chunks AS c
  ON c.document_version_id = v.id
JOIN rag.review_statuses AS rs
  ON rs.code = v.review_status_code
JOIN rag.chunk_states AS cs
  ON cs.code = c.state_code
WHERE d.active
  AND v.is_active
  AND rs.code = 'REVIEWED'
  AND cs.code = 'ACTIVE'
  AND c.embedding IS NOT NULL
  AND EXISTS (
    SELECT 1
    FROM rag.corpus_document_version_splits AS split
    WHERE split.document_version_id = v.id
      AND split.split_code = 'INDEX_90'
  );

-- The isolated index is populated from reviewed national decree corpus rows;
-- IMI templates, drafts and generated outputs never enter this database.
INSERT INTO rag.document_types (code, name)
VALUES ('DECRETO', 'Decreto')
ON CONFLICT (code) DO NOTHING;

INSERT INTO rag.jurisdictions (code, name)
VALUES ('NACION', 'Nación')
ON CONFLICT (code) DO NOTHING;

INSERT INTO rag.languages (code, name)
VALUES ('es', 'Español')
ON CONFLICT (code) DO NOTHING;

INSERT INTO rag.review_statuses (code, name)
VALUES
  ('PENDING_REVIEW', 'Pendiente de revisión'),
  ('REVIEWED', 'Revisado'),
  ('REJECTED', 'Rechazado')
ON CONFLICT (code) DO NOTHING;

INSERT INTO rag.ingestion_statuses (code, name)
VALUES
  ('DISCOVERED', 'Descubierto'),
  ('INGESTED', 'Ingerido'),
  ('FAILED', 'Fallido')
ON CONFLICT (code) DO NOTHING;

INSERT INTO rag.embedding_statuses (code, name)
VALUES
  ('PENDING', 'Pendiente'),
  ('COMPLETED', 'Completado'),
  ('FAILED', 'Fallido')
ON CONFLICT (code) DO NOTHING;

INSERT INTO rag.chunk_states (code, name)
VALUES ('ACTIVE', 'Activo'), ('INACTIVE', 'Inactivo')
ON CONFLICT (code) DO NOTHING;

INSERT INTO rag.provenance_types (code, name)
VALUES ('OFFICIAL', 'Fuente oficial'), ('AUTOMATED', 'Fuente automatizada'), ('MANUAL', 'Carga manual')
ON CONFLICT (code) DO NOTHING;

INSERT INTO rag.generation_statuses (code, name, terminal)
VALUES
  ('QUEUED', 'En cola', false),
  ('RUNNING', 'Procesando', false),
  ('SUCCEEDED', 'Completada', true),
  ('FAILED', 'Fallida', true),
  ('CANCELLED', 'Cancelada', true)
ON CONFLICT (code) DO NOTHING;

INSERT INTO rag.retrieval_statuses (code, name, terminal)
VALUES
  ('QUEUED', 'En cola', false),
  ('RUNNING', 'Procesando', false),
  ('SUCCEEDED', 'Completada', true),
  ('FAILED', 'Fallida', true),
  ('CANCELLED', 'Cancelada', true)
ON CONFLICT (code) DO NOTHING;

INSERT INTO rag.embedding_models (model_name, dimensions, storage_type)
VALUES ('qwen3-embedding:0.6b', 1024, 'halfvec')
ON CONFLICT (model_name) DO NOTHING;

INSERT INTO rag.runtime_profiles (
  code,
  embedding_model,
  embedding_dimensions,
  embedding_context_length,
  rag_context_length,
  generation_model,
  generation_context_length,
  top_k,
  candidate_pool_size,
  minimum_score
)
VALUES (
  'imi_leg_06b',
  'qwen3-embedding:0.6b',
  1024,
  2048,
  2048,
  'qwen3.6:35b',
  16384,
  8,
  24,
  0.0
)
ON CONFLICT (code) DO UPDATE SET
  embedding_model = EXCLUDED.embedding_model,
  embedding_dimensions = EXCLUDED.embedding_dimensions,
  embedding_context_length = EXCLUDED.embedding_context_length,
  rag_context_length = EXCLUDED.rag_context_length,
  generation_model = EXCLUDED.generation_model,
  generation_context_length = EXCLUDED.generation_context_length,
  top_k = EXCLUDED.top_k,
  candidate_pool_size = EXCLUDED.candidate_pool_size,
  minimum_score = EXCLUDED.minimum_score,
  active = true;

INSERT INTO rag.evaluation_splits (code, name)
VALUES ('INDEX_90', 'Conjunto de evaluación habilitado')
ON CONFLICT (code) DO NOTHING;

COMMIT;
