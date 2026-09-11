-- Provenance and immutable history for the DOCX template flow.
-- Safe to run on fresh and existing core volumes (all statements idempotent).
BEGIN;

-- Controlled source metadata + extractor provenance on import jobs.
ALTER TABLE imi.template_import_jobs
  ADD COLUMN IF NOT EXISTS source_sha256 char(64),
  ADD COLUMN IF NOT EXISTS source_size_bytes integer,
  ADD COLUMN IF NOT EXISTS extractor_version varchar(50),
  ADD COLUMN IF NOT EXISTS candidates_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS decisions_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS decided_by varchar(200),
  ADD COLUMN IF NOT EXISTS decided_at timestamptz;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_template_import_jobs_source_sha'
  ) THEN
    ALTER TABLE imi.template_import_jobs
      ADD CONSTRAINT ck_template_import_jobs_source_sha
      CHECK (source_sha256 IS NULL OR source_sha256 ~ '^[0-9a-f]{64}$');
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_template_import_jobs_source_size'
  ) THEN
    ALTER TABLE imi.template_import_jobs
      ADD CONSTRAINT ck_template_import_jobs_source_size
      CHECK (source_size_bytes IS NULL OR source_size_bytes > 0);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_template_import_jobs_candidates_array'
  ) THEN
    ALTER TABLE imi.template_import_jobs
      ADD CONSTRAINT ck_template_import_jobs_candidates_array
      CHECK (jsonb_typeof(candidates_json) = 'array');
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_template_import_jobs_decisions_array'
  ) THEN
    ALTER TABLE imi.template_import_jobs
      ADD CONSTRAINT ck_template_import_jobs_decisions_array
      CHECK (jsonb_typeof(decisions_json) = 'array');
  END IF;
END
$$;

-- Provenance link from a version config back to the import it was promoted from.
ALTER TABLE imi.template_version_configs
  ADD COLUMN IF NOT EXISTS source_import_id uuid
    REFERENCES imi.template_import_jobs(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS source_sha256 char(64),
  ADD COLUMN IF NOT EXISTS extractor_version varchar(50);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_template_version_configs_source_sha'
  ) THEN
    ALTER TABLE imi.template_version_configs
      ADD CONSTRAINT ck_template_version_configs_source_sha
      CHECK (source_sha256 IS NULL OR source_sha256 ~ '^[0-9a-f]{64}$');
  END IF;
END
$$;

CREATE INDEX IF NOT EXISTS ix_template_version_configs_source_import
  ON imi.template_version_configs (source_import_id);

-- Immutable PUBLISHED history: only DRAFT rows are mutable; PUBLISHED rows
-- may only transition to ARCHIVED (status + updated_at). All other content
-- changes and DELETEs of PUBLISHED rows are rejected at the database level.
CREATE OR REPLACE FUNCTION imi.protect_published_template_configs()
RETURNS trigger
LANGUAGE plpgsql
AS $func$
BEGIN
  IF OLD.status = 'PUBLISHED' THEN
    IF TG_OP = 'DELETE' THEN
      RAISE EXCEPTION 'TEMPLATE_VERSION_IMMUTABLE';
    END IF;
    IF NEW.status = 'ARCHIVED'
      AND NEW.template_version_id = OLD.template_version_id
      AND NEW.revision = OLD.revision
      AND NEW.fields_json = OLD.fields_json
      AND NEW.rules_json = OLD.rules_json
      AND NEW.blocks_json = OLD.blocks_json
      AND COALESCE(NEW.instructions, '') = COALESCE(OLD.instructions, '')
      AND COALESCE(NEW.organ_emisor, '') = COALESCE(OLD.organ_emisor, '')
      AND COALESCE(NEW.normativa, '') = COALESCE(OLD.normativa, '')
      AND NEW.extraction_warnings = OLD.extraction_warnings
      AND COALESCE(NEW.source_sha256, '') = COALESCE(OLD.source_sha256, '')
      AND COALESCE(NEW.extractor_version, '') = COALESCE(OLD.extractor_version, '')
      AND COALESCE(NEW.source_import_id::text, '') = COALESCE(OLD.source_import_id::text, '')
    THEN
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'TEMPLATE_VERSION_IMMUTABLE';
  END IF;
  RETURN NEW;
END;
$func$;

DROP TRIGGER IF EXISTS trg_protect_published_template_configs
  ON imi.template_version_configs;

CREATE TRIGGER trg_protect_published_template_configs
BEFORE UPDATE OR DELETE ON imi.template_version_configs
FOR EACH ROW EXECUTE FUNCTION imi.protect_published_template_configs();

-- Body text lives in document_template_versions; reject body changes while
-- the linked config is PUBLISHED so history stays immutable end to end.
CREATE OR REPLACE FUNCTION imi.protect_published_template_body()
RETURNS trigger
LANGUAGE plpgsql
AS $func$
DECLARE
  current_status varchar(20);
BEGIN
  SELECT status INTO current_status
  FROM imi.template_version_configs
  WHERE template_version_id = OLD.id;
  IF current_status = 'PUBLISHED' AND NEW.body_template IS DISTINCT FROM OLD.body_template THEN
    RAISE EXCEPTION 'TEMPLATE_VERSION_IMMUTABLE';
  END IF;
  RETURN NEW;
END;
$func$;

DROP TRIGGER IF EXISTS trg_protect_published_template_body
  ON imi.document_template_versions;

CREATE TRIGGER trg_protect_published_template_body
BEFORE UPDATE OF body_template ON imi.document_template_versions
FOR EACH ROW EXECUTE FUNCTION imi.protect_published_template_body();

COMMIT;
