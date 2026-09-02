-- Idempotent IMI LEG canonical template seed.
-- The source DOCX is a presentation reference and is deliberately not copied
-- into the RAG database.  This row stores only the structured contract needed
-- by the core API and renderer.

BEGIN;

DO $$
DECLARE
  imi_org uuid;
  disposition_type uuid;
BEGIN
  SELECT id INTO imi_org FROM imi.organizations WHERE code = 'IMI';
  SELECT id INTO disposition_type FROM imi.document_types WHERE code = 'DISPOSICION';

  IF imi_org IS NULL OR disposition_type IS NULL THEN
    RAISE EXCEPTION 'IMI canonical template prerequisites are missing';
  END IF;

  UPDATE imi.document_templates
  SET active = false
  WHERE organization_id = imi_org
    AND document_type_id = disposition_type
    AND code <> 'IMI_DISPOSICION_FONDO_PERMANENTE';

  INSERT INTO imi.document_templates (
    id,
    code,
    name,
    document_type_id,
    organization_id,
    jurisdiction,
    language_code,
    active
  )
  VALUES (
    '4f1b0c80-6e89-4de1-8f1f-6fbdde5b8c12',
    'IMI_DISPOSICION_FONDO_PERMANENTE',
    'Disposición IMI — Fondo Permanente',
    disposition_type,
    imi_org,
    'Corrientes',
    'es-AR',
    true
  )
  ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    document_type_id = EXCLUDED.document_type_id,
    organization_id = EXCLUDED.organization_id,
    jurisdiction = EXCLUDED.jurisdiction,
    language_code = EXCLUDED.language_code,
    active = true;
END;
$$;

INSERT INTO imi.document_template_versions (
  id,
  template_id,
  version,
  issuing_organization_id,
  description,
  body_template
)
SELECT
  'd0c12a1e-4d0f-4f36-8d04-0f2e0a4e7c12',
  t.id,
  1,
  t.organization_id,
  'Modelo canónico de Disposición IMI — Fondo Permanente; estructura basada en el DOCX institucional de referencia.',
  $$ENCABEZADO INSTITUCIONAL
DISPOSICIÓN N.º {{numero}}/{{anio}}
CORRIENTES, {{fecha}}

VISTO:
El Expediente N.º {{expediente}}, caratulado: “{{caratula}}”; {{antecedentes}}; y,

CONSIDERANDO:
{{considerandos}}

POR ELLO:
EL PRESIDENTE DEL INSTITUTO DE MODERNIZACIÓN E INNOVACIÓN

DISPONE:
{{articulos}}

Comunicar, notificar y girar las presentes actuaciones a la dependencia competente, a sus efectos. Registrar y oportunamente archivar.

{{firma}}$$
FROM imi.document_templates AS t
WHERE t.code = 'IMI_DISPOSICION_FONDO_PERMANENTE'
ON CONFLICT (template_id, version) DO UPDATE SET
  issuing_organization_id = EXCLUDED.issuing_organization_id,
  description = EXCLUDED.description,
  body_template = EXCLUDED.body_template;

INSERT INTO imi.template_variables (
  template_version_id,
  variable_key,
  label,
  data_type,
  required,
  display_order
)
SELECT
  v.id,
  variables.variable_key,
  variables.label,
  variables.data_type,
  variables.required,
  variables.display_order
FROM imi.document_template_versions AS v
CROSS JOIN (
  VALUES
    ('numero', 'Número de disposición', 'integer', true, 1),
    ('anio', 'Año', 'integer', true, 2),
    ('fecha', 'Lugar y fecha', 'date', true, 3),
    ('expediente', 'Número de expediente', 'text', true, 4),
    ('caratula', 'Carátula del expediente', 'text', true, 5),
    ('beneficiario', 'Beneficiario', 'person', true, 6),
    ('cuit', 'CUIT', 'text', true, 7),
    ('factura', 'Factura', 'text', true, 8),
    ('periodo', 'Período', 'text', true, 9),
    ('monto_numerico', 'Monto numérico', 'decimal', true, 10),
    ('monto_letras', 'Monto en letras', 'text', true, 11),
    ('concepto', 'Concepto', 'text', true, 12),
    ('programa', 'Programa', 'text', true, 13),
    ('fondo_permanente', 'Fondo Permanente', 'text', true, 14),
    ('partida_presupuestaria', 'Partida presupuestaria', 'text', true, 15),
    ('normativa', 'Normativa aplicable', 'list', true, 16),
    ('dictamenes', 'Dictámenes', 'list', false, 17),
    ('antecedentes', 'Antecedentes', 'list', true, 18),
    ('autoridad', 'Autoridad', 'text', true, 19),
    ('firma', 'Firma', 'text', true, 20)
) AS variables(variable_key, label, data_type, required, display_order)
WHERE v.template_id = (
  SELECT id FROM imi.document_templates WHERE code = 'IMI_DISPOSICION_FONDO_PERMANENTE'
)
AND v.version = 1
ON CONFLICT (template_version_id, variable_key) DO UPDATE SET
  label = EXCLUDED.label,
  data_type = EXCLUDED.data_type,
  required = EXCLUDED.required,
  display_order = EXCLUDED.display_order;

INSERT INTO imi.template_normative_references (
  template_version_id,
  reference_order,
  reference_text
)
SELECT
  v.id,
  refs.reference_order,
  refs.reference_text
FROM imi.document_template_versions AS v
CROSS JOIN (
  VALUES
    (1, 'Ley de Administración Financiera N.º 5.571'),
    (2, 'Decreto N.º 3.055/2004'),
    (3, 'Decreto N.º 798/2026'),
    (4, 'Decreto N.º 1.674/2026'),
    (5, 'Resolución Ministerial N.º 474/2026'),
    (6, 'Disposición N.º 0023/2026 del ex IPECD'),
    (7, 'Orden de Compra'),
    (8, 'Factura'),
    (9, 'Acta de Recepción')
) AS refs(reference_order, reference_text)
WHERE v.template_id = (
  SELECT id FROM imi.document_templates WHERE code = 'IMI_DISPOSICION_FONDO_PERMANENTE'
)
AND v.version = 1
ON CONFLICT (template_version_id, reference_order) DO UPDATE SET
  reference_text = EXCLUDED.reference_text;

COMMIT;
