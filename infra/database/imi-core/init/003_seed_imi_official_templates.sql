-- Official IMI LEG templates.
--
-- This script is idempotent and is also safe to run manually against an
-- existing IMI core database. The previous seed remains only as historical
-- template version 1; the active disposition is version 2 and the old model
-- is not exposed as a separate active template.

BEGIN;

DO $$
DECLARE
  imi_org uuid;
  disposition_type uuid;
  note_type uuid;
BEGIN
  INSERT INTO imi.document_types (code, name, active)
  VALUES ('NOTA_INICIO', 'Nota de inicio', true)
  ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    active = true;

  SELECT id INTO imi_org FROM imi.organizations WHERE code = 'IMI';
  SELECT id INTO disposition_type FROM imi.document_types WHERE code = 'DISPOSICION';
  SELECT id INTO note_type FROM imi.document_types WHERE code = 'NOTA_INICIO';

  IF imi_org IS NULL OR disposition_type IS NULL OR note_type IS NULL THEN
    RAISE EXCEPTION 'IMI official template prerequisites are missing';
  END IF;

  UPDATE imi.document_templates
  SET active = false
  WHERE organization_id = imi_org
    AND document_type_id = disposition_type
    AND code <> 'IMI_DISPOSICION_FONDO_PERMANENTE';

  UPDATE imi.document_templates
  SET active = false
  WHERE organization_id = imi_org
    AND document_type_id = note_type
    AND code <> 'IMI_NOTA_INICIO';

  INSERT INTO imi.document_templates (
    id, code, name, document_type_id, organization_id,
    jurisdiction, language_code, active
  )
  VALUES (
    '4f1b0c80-6e89-4de1-8f1f-6fbdde5b8c12',
    'IMI_DISPOSICION_FONDO_PERMANENTE',
    'Disposición por Fondo Permanente',
    disposition_type, imi_org, 'Corrientes', 'es-AR', true
  )
  ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    document_type_id = EXCLUDED.document_type_id,
    organization_id = EXCLUDED.organization_id,
    jurisdiction = EXCLUDED.jurisdiction,
    language_code = EXCLUDED.language_code,
    active = true;

  INSERT INTO imi.document_templates (
    id, code, name, document_type_id, organization_id,
    jurisdiction, language_code, active
  )
  VALUES (
    '7b3e9e3a-4e25-4c36-9a21-5f78b8d2c1a4',
    'IMI_NOTA_INICIO',
    'Nota de Inicio de Actuaciones',
    note_type, imi_org, 'Corrientes', 'es-AR', true
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

-- The exact legal text is kept as a versioned prompt contract. Placeholders
-- are the only portions the generator may replace.
INSERT INTO imi.document_template_versions (
  id, template_id, version, issuing_organization_id, description, body_template
)
SELECT
  '2c9d6b31-8f0a-4f45-9e16-7b7e1e4c2a90',
  t.id,
  2,
  t.organization_id,
  'Modelo oficial de Disposición por Fondo Permanente; texto y orden tomados del DOCX institucional vigente.',
  $$DISPOSICIÓN N.º {{numero}}/{{anio}}
CORRIENTES, {{fecha}}

VISTO:

El Expediente N.º {{expediente}}, caratulado: “INSTITUTO DE MODERNIZACION E INNOVACION IMI –  SOLICITUD DE PAGO A {{beneficiario}} POR {{concepto}}”; la Ley de Administración Financiera N.º 5.571; el Decreto N.º 3.055/2004; el Decreto N.º 798/2026; el Decreto N.º 1.674/2026; la Orden de Compra N.º {{orden_compra}}/{{anio}}; la Factura C N.º {{factura}}; el Acta de Recepción N.º {{acta_recepcion}}/{{anio}}; y,

CONSIDERANDO:

Que por las presentes actuaciones se tramita la solicitud de pago al Sr. {{beneficiario}}, CUIT N°{{cuit}}, por servicio de {{concepto}} para el Instituto de Modernización e Innovación;

Que a fs. {{fojas_orden_compra}} obra la Orden de Compra N.º {{orden_compra}}/{{anio}}, emitida por el Instituto de Modernización e Innovación, por la suma total de PESOS {{monto_letras}} (${{monto_numerico}}); y Factura C N.º {{factura}}, emitida por el Sr. {{beneficiario}}, por el importe de PESOS {{monto_letras}} (${{monto_numerico}});

Que a fs. {{fojas_documentacion}} se encuentran agregadas las constancias y documentación respaldatoria correspondiente al proveedor, incluyendo, Constancia de Opción de ARCA, Constatación de Comprobantes con CAE, Constancia de Inscripción en la Dirección General de Rentas, Certificado Fiscal para Contratar y Constancia de CBU como así también los comprobantes correspondientes al sellado de ley y tasas retributivas;

Que a fs. {{fojas_acta}} obra el Acta de Recepción N.º {{acta_recepcion}}/{{anio}}, mediante la cual se deja constancia de la recepción de los trabajos por el importe total de PESOS {{monto_letras}} (${{monto_numerico}});

Que a fs. {{fojas_nota}} obra nota N° {{nota_numero}}/{{anio}} suscripta por el Sr. Presidente del Instituto de Modernización e Innovación, mediante la cual se solicita la colaboración de la Dirección de Asesoría Legal del Ministerio de Coordinación y Planificación y su posterior derivación.

Que el gasto será atendido con cargo al Fondo Permanente del Instituto de Modernización e Innovación, constituido mediante Decreto N.º 1.674/2026;

Que conforme lo dispuesto por el Decreto N.º 3.055/2004, corresponde observar los requisitos establecidos para la tramitación de los Libramientos Internos de Pago con cargo a Fondos Permanentes;

Que mediante Dictamen N.º {{dictamen_numero}}/{{anio}} de la Dirección de Asesoría Legal del Ministerio de Coordinación y Planificación se ha efectuado el correspondiente análisis de legitimidad del procedimiento, concluyendo que no existen objeciones jurídicas para la prosecución del trámite y que podrá autorizarse el pago solicitado, con cargo al Fondo Permanente constituido por Decreto N.º 1.674/2026;

Que en virtud de las constancias obrantes en autos corresponde autorizar el pago de la Factura C N.º {{factura}} por la suma de PESOS {{monto_letras}} (${{monto_numerico}});

Que han tomado la intervención que les compete los organismos administrativos y legales correspondientes;

Que la presente medida se dicta en ejercicio de las facultades conferidas por la normativa vigente;

POR ELLO:

EL PRESIDENTE DEL INSTITUTO DE MODERNIZACIÓN E INNOVACIÓN

DISPONE:

ARTÍCULO 1°.- AUTORIZAR el pago a favor de la firma “{{beneficiario}}, CUIT N° {{cuit}}, de la Factura C N.º {{factura}}, por la suma total de PESOS {{monto_letras}} (${{monto_numerico}}); en concepto de {{concepto}} para el Instituto de Modernización e Innovación, conforme las constancias obrantes en el Expediente N.º {{expediente}}.

ARTÍCULO 2°.- IMPUTAR el gasto autorizado en el artículo precedente al Fondo Permanente del Instituto de Modernización e Innovación, constituido por Decreto N.º 1.674/2026, conforme a la imputación presupuestaria que corresponda.

ARTÍCULO 3°.- AUTORIZAR a la Dirección de Gestión Administrativa del Instituto de Modernización e Innovación a emitir el correspondiente Libramiento Interno de Pago, con cargo al Fondo Permanente del Instituto de Modernización e Innovación, por la suma indicada en el artículo 1° de la presente.

ARTÍCULO 4°.- ESTABLECER que la Dirección de Gestión Administrativa deberá verificar, previo a la efectivización del pago, el cumplimiento de los recaudos y documentación exigidos por la normativa vigente para los Libramientos Internos de Pago con cargo a Fondos Permanentes.

ARTÍCULO 5°.- COMUNICAR, notificar y girar las presentes actuaciones a la Dirección de Gestión Administrativa del Instituto de Modernización e Innovación, a sus efectos.

ARTÍCULO 6°.- REGISTRAR y oportunamente archivar.$$
FROM imi.document_templates AS t
WHERE t.code = 'IMI_DISPOSICION_FONDO_PERMANENTE'
ON CONFLICT (template_id, version) DO UPDATE SET
  issuing_organization_id = EXCLUDED.issuing_organization_id,
  description = EXCLUDED.description,
  body_template = EXCLUDED.body_template;

INSERT INTO imi.template_variables (
  template_version_id, variable_key, label, data_type, required, display_order
)
SELECT v.id, variables.variable_key, variables.label, variables.data_type,
       variables.required, variables.display_order
FROM imi.document_template_versions AS v
CROSS JOIN (
  VALUES
    ('fecha', 'Fecha', 'date', true, 1),
    ('monto_numerico', 'Monto', 'decimal', true, 2),
    ('beneficiario', 'Destinatario', 'text', true, 3),
    ('concepto', 'Razón a pagar', 'text', true, 4),
    ('numero', 'Número de disposición', 'integer', true, 5),
    ('anio', 'Año', 'integer', false, 6),
    ('expediente', 'Número de expediente', 'text', false, 7),
    ('cuit', 'CUIT', 'text', false, 8),
    ('orden_compra', 'Orden de compra', 'text', false, 9),
    ('factura', 'Factura', 'text', false, 10),
    ('acta_recepcion', 'Acta de recepción', 'text', false, 11),
    ('monto_letras', 'Monto en letras', 'text', false, 12),
    ('fojas_orden_compra', 'Fojas de la orden de compra', 'text', false, 13),
    ('fojas_documentacion', 'Fojas de la documentación', 'text', false, 14),
    ('fojas_acta', 'Fojas del acta', 'text', false, 15),
    ('fojas_nota', 'Fojas de la nota', 'text', false, 16),
    ('nota_numero', 'Número de nota', 'text', false, 17),
    ('dictamen_numero', 'Número de dictamen', 'text', false, 18)
) AS variables(variable_key, label, data_type, required, display_order)
WHERE v.template_id = (SELECT id FROM imi.document_templates WHERE code = 'IMI_DISPOSICION_FONDO_PERMANENTE')
  AND v.version = 2
ON CONFLICT (template_version_id, variable_key) DO UPDATE SET
  label = EXCLUDED.label,
  data_type = EXCLUDED.data_type,
  required = EXCLUDED.required,
  display_order = EXCLUDED.display_order;

INSERT INTO imi.document_template_versions (
  id, template_id, version, issuing_organization_id, description, body_template
)
SELECT
  '6f0f6bc2-1d33-40c8-9a1a-2c3d4e5f6071',
  t.id,
  1,
  t.organization_id,
  'Modelo oficial de Nota de Inicio de Actuaciones; texto y orden tomados del DOCX institucional vigente.',
  $$Expediente N° {{expediente}}	Corrientes, {{fecha}}

INFORME DE INICIO DE ACTUACIONES

Por medio del presente, esta Dirección de Gestión Administrativa del Instituto de Modernización e Innovación (IMI) inicia de oficio las presentes actuaciones, a fin de propiciar la liquidación y pago del Sr. {{beneficiario}} por el {{concepto}} del/para  Instituto de Modernización e Innovación, en virtud de la necesidad operativa existente en el ámbito de este Instituto, conforme a las funciones asignadas al IMI por el Decreto N° 798/2026 y conforme a lo dispuesto por la Ley N°3.460.

Que se incorporará la Orden de Compra, la Factura correspondiente, el Acta de Recepción, con la conformidad y firma del Sr. Presidente del Instituto de Modernización e Innovación, junto con la documentación impositiva de la firma proveedora.$$
FROM imi.document_templates AS t
WHERE t.code = 'IMI_NOTA_INICIO'
ON CONFLICT (template_id, version) DO UPDATE SET
  issuing_organization_id = EXCLUDED.issuing_organization_id,
  description = EXCLUDED.description,
  body_template = EXCLUDED.body_template;

INSERT INTO imi.template_variables (
  template_version_id, variable_key, label, data_type, required, display_order
)
SELECT v.id, variables.variable_key, variables.label, variables.data_type,
       variables.required, variables.display_order
FROM imi.document_template_versions AS v
CROSS JOIN (
  VALUES
    ('expediente', 'Número de expediente', 'text', true, 1),
    ('fecha', 'Fecha', 'date', true, 2),
    ('beneficiario', 'Destinatario', 'text', true, 3),
    ('concepto', 'Razón de la actuación', 'text', true, 4)
) AS variables(variable_key, label, data_type, required, display_order)
WHERE v.template_id = (SELECT id FROM imi.document_templates WHERE code = 'IMI_NOTA_INICIO')
  AND v.version = 1
ON CONFLICT (template_version_id, variable_key) DO UPDATE SET
  label = EXCLUDED.label,
  data_type = EXCLUDED.data_type,
  required = EXCLUDED.required,
  display_order = EXCLUDED.display_order;

COMMIT;
