# Especificación: Revisión y Exportación de Documentos

**ID de Especificación**: `004-document-review-and-export`
**Creada**: 2026-08-03
**Estado**: Borrador
**Entrada**: Descripción del usuario: "Document review and export"

## Clarifications

### Sesión 2026-08-03

- La revisión humana sigue siendo obligatoria. La exportación no cambia el
  estado jurídico del documento ni equivale a publicación, aprobación legal o
  firma digital.
- La unidad revisable es una versión concreta del borrador. Si el borrador se
  edita o regenera, la nueva versión inicia un nuevo ciclo de revisión y las
  anotaciones anteriores permanecen asociadas a la versión previa.
- Los comentarios de revisión son registros auditables. Pueden pasar a
  `RESUELTO` o `DESCARTADO`, pero no se eliminan ni se reescribe su contenido.
- Solo se puede exportar una versión de borrador `APROBADA` que no tenga
  comentarios bloqueantes abiertos. La comprobación se realiza en backend en
  cada solicitud de exportación.
- El contenido exportado se toma literalmente del snapshot aprobado. Exportar
  no invoca Ollama, no modifica el borrador y no incorpora datos externos.
- HTML se usa únicamente como preview y representación intermedia no
  persistida. Las exportaciones persistidas y descargables son solo DOCX y
  PDF, generadas mediante adaptadores reemplazables detrás de puertos de
  aplicación.
- La persistencia de artefactos usa un puerto de almacenamiento. El adaptador
  local sobre volumen administrado por Docker es el objetivo del MVP; no se
  incorpora almacenamiento público ni se fija una dependencia de proveedor.
- La autenticación y autorización continúan fuera de alcance, como en 003. Los
  endpoints reciben el identificador de actor que la capa de seguridad futura
  deberá validar.

- Q: ¿Qué estrategia debe usar 004 para representar la finalización exportable
  de un borrador aprobado? → A: B — mantener `DraftStatus.APPROVED` y agregar
  metadatos de finalización al draft. La operación exige `expected_version`,
  aplica optimistic locking e incrementa `document_drafts.version` (el valor
  se expone como `draft_version`); persiste `finalized_by`,
  `finalized_at` en UTC, `finalization_notes` y un snapshot final exportable
  inmutable. Solo una versión aprobada con estos metadatos puede superar el
  gate de exportación.

- Q: ¿Qué máquina de estados debe usar una exportación desde su solicitud hasta
  su reemplazo? → A: A — usar `PENDING → GENERATING → GENERATED`, con `FAILED`
  como estado reintentable y `SUPERSEDED` únicamente después de una
  regeneración exitosa. Cada procesamiento se registra en `export_attempts` y
  las versiones `GENERATED` y `SUPERSEDED` siguen siendo descargables.

- Q: ¿Qué rol debe cumplir HTML en relación con la previsualización y los
  artefactos persistidos? → A: A — HTML es preview y representación intermedia
  no persistida; las únicas exportaciones persistidas y descargables son DOCX
  y PDF.

- Q: ¿Qué pipeline funcional debe usar el sistema para generar PDF desde la
  representación aprobada? → A: C — generar el PDF desde el HTML canónico
  intermedio mediante un renderer headless reemplazable. El pipeline mantiene
  coherencia con la previsualización, desacopla PDF de DOCX y funciona en
  Linux/contenedores.

- Q: ¿Qué política de idempotencia debe aplicar la creación y el reintento de
  exportaciones? → A: A — `Idempotency-Key` obligatorio de 16 a 100 caracteres
  seguros, ventana de 24 horas y `request_hash`. Misma clave y payload devuelve
  el resultado existente; payload distinto devuelve `409 IDEMPOTENCY_CONFLICT`;
  intento activo devuelve `409 EXPORT_IN_PROGRESS`; un intento fallido permite
  reintento con la misma clave. `request_id` queda solo para trazabilidad.

### Session 2026-08-03

- Q: ¿Qué modelo de datos y estrategia de migración debe fijar 004 para la
  finalización y las exportaciones? → A: A — extender `document_drafts` con
  metadatos de finalización y crear `document_exports` para artefactos válidos
  versionados y `export_attempts` para cada intento, incluidos fallos e
  idempotencia. Migración: alterar drafts → crear exports → crear attempts;
  downgrade en orden inverso.

- Q: ¿Qué comportamiento debe tener la finalización repetida y qué operaciones
  deben bloquearse después de finalizar un draft? → A: A — la primera
  finalización ocurre desde `APPROVED` con revisión cerrada; una solicitud
  idéntica devuelve `200`; un payload diferente devuelve
  `DRAFT_ALREADY_FINALIZED`; una versión obsoleta devuelve
  `CONCURRENT_MODIFICATION`; después se bloquean edición, cambios de revisión,
  rechazo, nueva aprobación y regeneración del draft. Solo se regeneran las
  exportaciones posteriores.

- Q: ¿Cómo debe registrarse un reintento fallido en `export_attempts` sin perder
  la auditoría de cada procesamiento? → A: A — cada procesamiento crea una
  fila nueva con el mismo `idempotency_key` y `request_hash`, un
  `attempt_number` incremental y el historial de fallos. Una constraint o
  índice único parcial permite como máximo un intento `PENDING` o `PROCESSING`
  activo por `exported_by + idempotency_key`.

- Q: ¿Qué layout y controles de seguridad debe usar el almacenamiento local de
  los artefactos exportados? → A: A — usar
  `{case_file_id}/{draft_id}/{format}/v{export_version}/{file_name}`, persistir solo
  la ruta relativa, configurar el root con `EXPORT_STORAGE_ROOT`, rechazar
  paths absolutos, `..`, escapes del root y symlinks, usar directorios `0700`,
  archivos `0600`, temporales aleatorios en el destino y rename atómico. La
  jerarquía usa UUIDs y versión, sin PII ni `case_number`.

- Q: ¿Qué estrategia de compensación debe usar 004 cuando filesystem y
  PostgreSQL no pueden confirmarse atómicamente? → A: A — Tx1 crea export y
  attempt en `PENDING`; la generación, validación y rename ocurren fuera de la
  transacción; Tx2 confirma `GENERATED`, `SUCCEEDED` y `SUPERSEDED`. Los fallos
  eliminan temporales, intentan eliminar el definitivo, conservan un error
  sanitizado y se reparan mediante reconciliación manual.

### Session 2026-08-03

- Q: ¿Qué contrato debe tener el preview HTML? → A: usar
  `GET /api/v1/drafts/{draft_id}/preview?draft_version={n}` únicamente para drafts
  `APPROVED`. Antes de finalizar, renderiza el contenido aprobado de la versión
  solicitada; después de finalizar, usa exclusivamente `final_snapshot`. Los
  drafts finalizados siguen siendo previsualizables. Responde
  `text/html; charset=utf-8`, incluye `ETag` basado en SHA-256 y
  `Cache-Control: no-store`; no persiste archivos, no crea exportaciones, no
  modifica estado ni incrementa `document_drafts.version`.

- Q: ¿Qué contrato debe tener la descarga de artefactos? → A: usar
  `GET /api/v1/exports/{export_id}/download`, permitido solo para estados
  `GENERATED` y `SUPERSEDED`, con respuesta binaria en streaming,
  `Content-Disposition: attachment`, `ETag` SHA-256 y
  `Cache-Control: private, no-store`. En 004 no hay Range requests: si llega
  el header `Range`, se responde `416 Range Not Satisfiable` con el código
  estable `RANGE_NOT_SUPPORTED`, envelope JSON uniforme con `request_id` y
  `timestamp` y
  `Accept-Ranges: none`; no se inicia streaming, no se lee el archivo completo
  y no se devuelve `Content-Range`; este rechazo tiene precedencia sobre
  `If-None-Match`. Antes de una descarga válida se valida la
  ruta canónica y el hash, sin exponer `storage_path`; la ausencia devuelve
  `EXPORT_FILE_NOT_FOUND` y un hash inconsistente devuelve
  `EXPORT_FILE_CORRUPTED`.

- Q: ¿Qué validaciones de integridad deben aplicarse a los artefactos? → A:
  calcular SHA-256 al crear el artefacto y recalcularlo antes de cada descarga.
  DOCX exige extensión `.docx`, MIME
  `application/vnd.openxmlformats-officedocument.wordprocessingml.document`,
  ZIP válido con `[Content_Types].xml` y `word/document.xml`, como máximo 500
  entradas, 50 MiB (52.428.800 bytes) descomprimidos y ratio de compresión
  máximo 100:1. PDF exige
  extensión `.pdf`, MIME `application/pdf`, encabezado `%PDF-` y marcador
  `%%EOF` en el tramo final. Ante corrupción se bloquea la descarga, se
  registra un evento y se devuelve `EXPORT_FILE_CORRUPTED`; `GENERATED` no
  cambia automáticamente a `FAILED` y se exige regeneración explícita.

- Q: ¿Qué requisitos institucionales debe cumplir el DOCX? → A: A4 vertical;
  márgenes superior e inferior de 2,5 cm, izquierdo de 3 cm y derecho de 2 cm;
  cuerpo Arial 11; título Arial 12 negrita centrado; texto justificado,
  interlineado 1,5 y espaciado posterior de 6 pt. Debe incluir encabezado
  institucional configurable, secciones `VISTO`, `CONSIDERANDO` y `POR ELLO`,
  artículos `ARTÍCULO 1°`, `ARTÍCULO 2°`, etc., y espacios de firma
  configurables. No debe incluir pie de página salvo numeración de página. El
  locale es `es-AR`, los metadatos no incluyen datos personales innecesarios y
  los datos obligatorios faltantes producen un error de validación.

- Q: ¿Qué límites operativos y reglas de nombres debe aplicar 004? → A:
  contenido nuevo de 004 con techo máximo 2 MiB (2.097.152 bytes); los endpoints de edición
  heredados de 003 conservan su límite efectivo de 100 KiB;
  `final_snapshot` máximo 2 MiB (2.097.152 bytes) serializado;
  preview HTML máximo 5 MiB (5.242.880 bytes); DOCX máximo 20 MiB
  (20.971.520 bytes); PDF máximo 30 MiB (31.457.280 bytes); timeout de
  DOCX de 30 s y de PDF de 60 s; `file_name` máximo 120 caracteres;
  `relative_path` máximo 500 caracteres; `finalization_notes` máximo 2.000
  caracteres; identidad textual del actor entre 1 y 100 caracteres;
  `page_size` máximo 100; sin límite funcional adicional de versiones y una
  sola generación activa por `draft_id + format`. El nombre determinista es
  `{draft_id}_v{export_version}.{extension}`, en minúsculas, con solo UUID, dígitos,
  guion bajo, punto y extensión; sin espacios, doble extensión, PII,
  `case_number`, nombres personales, `document_type` ni fechas. La combinación
  `draft_id + format + export_version` debe impedir colisiones.

### Session 2026-08-03

- Q: ¿Qué política de retención y qué comando administrativo manual deben regir
  las exportaciones, intentos, temporales, huérfanos, registros sin archivo y
  archivos corruptos? → A: `GENERATED` y `SUPERSEDED` tienen retención
  indefinida; se conservan los metadatos de `document_exports` fallidos; los
  `export_attempts` fallidos tienen una retención mínima de 180 días. Los
  temporales son elegibles para cleanup manual después de 24 horas y los
  huérfanos después de 7 días desde su detección. Los registros sin archivo y
  los archivos corruptos no se eliminan automáticamente. No existe endpoint
  DELETE, scheduler, Redis ni cola. El comando administrativo es
  `document-exports reconcile`: dry-run por defecto, eliminación real solo con
  `--execute`, filtros por `case_file_id`, `draft_id`, formato, tipo de
  incidencia y antigüedad, y salida JSON con `run_id`, candidatos, eliminados,
  omitidos, conflictos y errores. Audita actor, timestamp UTC, recurso, acción
  y resultado; `run_id` proporciona idempotencia. Nunca elimina el último
  `GENERATED` válido ni un archivo con un intento `PROCESSING` activo.

- Q: ¿Cómo deben recibirse y validarse `finalized_by` y `exported_by` para que
  sean actores auditables sin confundirse con autenticación o trazabilidad? →
  A: ambos son obligatorios y strings de 1–100 caracteres con trim; se rechazan
  vacío y solo espacios, se aceptan letras Unicode, números, espacios, punto,
  guion, guion bajo y `@`, y se conservan las mayúsculas/minúsculas originales.
  Se comparan exactamente después de trim, no se usan para autenticación ni
  autorización, no requieren unicidad, no aparecen en `file_name`,
  `storage_path` ni rutas y solo se registran como actores de auditoría.
  `finalized_by` llega en el body de finalización; `exported_by`, en los bodies
  de creación, retry y regeneración. Un valor inválido devuelve
  `VALIDATION_ERROR`; `request_id` queda exclusivamente para trazabilidad en
  header o middleware.

- Q: ¿Cuál debe ser el contrato completo para regenerar una exportación sin
  modificar el snapshot final ni depender del archivo anterior? → A: usar
  `POST /api/v1/exports/{export_id}/regenerate` con body
  `{expected_version, exported_by}` e `Idempotency-Key` obligatorio. Acepta
  `GENERATED` y `SUPERSEDED`, incluso si falta o está corrupto el archivo
  origen; regenera exclusivamente desde `final_snapshot`, conserva el formato,
  crea un nuevo `document_export` y `export_attempt`, enlaza
  `parent_export_id`, usa `max(export_version) + 1` para `(draft_id, format)` y genera
  nuevo SHA-256 y `storage_path`. `expected_version` debe coincidir con la
  versión máxima actual; de lo contrario devuelve
  `CONCURRENT_MODIFICATION`. Responde inicialmente `202` con la nueva
  exportación en `PENDING` o `GENERATING`; una repetición idempotente con el
  mismo payload puede devolver `200`. La exportación `GENERATED` vigente pasa
  a `SUPERSEDED` solo después del éxito; un origen ya `SUPERSEDED` conserva ese
  estado. Si falla, el artefacto anterior conserva estado y descargabilidad.
  Un `FAILED` se reintenta mediante
  `POST /api/v1/exports/{export_id}/retry`, con la misma clave y un nuevo
  `export_attempt`, sin crear otro `document_export`.

- Q: ¿Qué catálogo HTTP, parámetros, respuestas, errores y envelope deben
  quedar como contrato final de 004? → A: todas las respuestas JSON DEBEN
  incluir `request_id`; `Idempotency-Key` es obligatorio en creación, retry y
  regeneración; las listas usan paginación uniforme con `page_size` máximo 100
  y orden estable; `expected_version` es obligatorio en finalización,
  mutaciones de revisión y regeneración. `storage_path`, errores internos y
  contenido documental nunca se exponen. Se incluye
  `GET /api/v1/exports/{export_id}/attempts` para auditoría, se mantienen los
  errores de revisión heredados de 003 y no se usa HTTP 507. Los errores usan
  exactamente el envelope público de 003 con `code`, `message`, `details`,
  `request_id` y `timestamp`, todos
  sanitizados y sin paths, stack traces, excepciones de librerías, secretos ni
  contenido documental.

### Session 2026-08-03

- Q: ¿Cómo deben dividirse las transacciones del pipeline de exportación? → A:
  exactamente dos transacciones PostgreSQL cortas. Tx1 valida draft,
  idempotencia y concurrencia, reserva `export_version`, crea las filas de
  export y attempt, y confirma ya las transiciones
  `PENDING → GENERATING` y `PENDING → PROCESSING`. La generación, validación y
  rename ocurren fuera de PostgreSQL. Tx2 marca éxito (`GENERATED`,
  `SUCCEEDED` y, si corresponde, `SUPERSEDED`) o fallo (`FAILED` en export y
  attempt), sin una transacción intermedia para marcar estados activos.

- Q: ¿Cómo se hace idempotente cada operación mutable de revisión? → A: exigir
  `Idempotency-Key` de 16–100 caracteres seguros y `request_hash` canónico en
  crear review, comentar, actualizar comentario, submit, approve y
  request-changes. El scope es operación + recurso principal + clave; el
  mismo payload devuelve replay, uno distinto devuelve
  `IDEMPOTENCY_CONFLICT` y una operación `PROCESSING` devuelve
  `REVIEW_OPERATION_IN_PROGRESS`, todo dentro de una ventana de 24 horas.
  004 persiste estas solicitudes en `review_operation_requests` porque la
  infraestructura de 003 no cubre este scope ni replay de respuestas.

- Q: ¿Qué debe conservar una revisión para que sus anclajes sigan siendo
  reproducibles? → A: `review_snapshot JSONB NOT NULL`,
  `review_snapshot_sha256 CHAR(64) NOT NULL` y `draft_version INTEGER NOT NULL`.
  El snapshot y su hash se fijan al abrir la revisión, se serializan de forma
  canónica y nunca se actualizan; comentarios, submit, approve y
  request-changes siempre usan esa versión persistida.

- Q: ¿Cómo se distingue un replay de un nuevo retry de una exportación? → A: la
  creación inicial no crea otro attempt desde su endpoint cuando el export ya
  está `FAILED`; devuelve sus metadatos y orienta a `/retry`. `/retry` solo
  acepta `FAILED`, valida actor y payload contra la solicitud inicial para
  reutilizar la misma clave y `request_hash`, crea un nuevo attempt por cada
  invocación posterior a un fallo, incrementa `attempt_number` y reutiliza el
  mismo export. Un attempt activo devuelve `EXPORT_IN_PROGRESS`, uno exitoso
  se repite con `200`, otro payload devuelve `IDEMPOTENCY_CONFLICT`.

- Q: ¿Qué código público representa cualquier corrupción detectada durante una
  descarga? → A: siempre `409 EXPORT_FILE_CORRUPTED`, tanto para hash, MIME,
  estructura DOCX/PDF, truncamiento como archivo vacío. Los códigos
  `HASH_VALIDATION_FAILED` y `MIME_VALIDATION_FAILED` quedan como causas
  internas de generación o logs, pero no compiten en el contrato público de
  descarga; un archivo inexistente sigue siendo `410 EXPORT_FILE_NOT_FOUND`.

- Q: ¿Cómo se comunica un fallo de renderer después de aceptar una operación
  diferida? → A: la solicitud aceptada devuelve `202` y no puede transformarse
  luego en `500`. El procesamiento marca export y attempt como `FAILED`, guarda
  un código sanitizado y el cliente consulta ese resultado mediante metadata o
  attempts. `EXPORT_GENERATION_FAILED` (`500`) solo aplica a un fallo síncrono
  previo a aceptar/programar el recurso.

- Q: ¿Qué nombres deben usar las versiones en 004? → A: `draft_version` para
  contenido de draft, revisión, finalización, preview y request de creación;
  `export_version` para el contador independiente por `(draft_id, format)`,
  incluidos filtros, paths, nombres, unicidad y regeneración con
  `max(export_version) + 1`. En los contratos de 004, `draft_version` es el
  nombre explícito del valor de contenido respaldado por
  `document_drafts.version`; no se agrega una segunda columna de versión de
  draft. `expected_version` protege la columna optimista correspondiente de
  cada operación. Las versiones de optimistic locking de review/comment
  permanecen como columnas internas, pero no se exponen como una versión de
  exportación ambigua.

- Q: ¿Cómo se resuelve el límite de contenido heredado de 003? → A: 2 MiB
  (2.097.152 bytes) es
  el techo máximo de 004, pero los endpoints de edición reutilizados de 003
  mantienen su límite efectivo más estricto de 100 KiB y su error
  `CONTENT_TOO_LARGE`; ninguna tarea de 004 puede relajar ese contrato. El
  límite de 2 MiB (2.097.152 bytes) se aplica al snapshot final serializado y a cualquier
  superficie nueva de 004 que no esté sujeta al límite heredado.

### Session 2026-08-03

- Q: ¿Cómo deben tratarse los objetivos de rendimiento de 004? → A: son
  métricas informativas no bloqueantes, pero se ejecutan con benchmarks
  reproducibles y umbrales explícitos para revisión, preview, aceptación `202`,
  descarga y reconciliación dry-run. Cada benchmark fija dataset, warm-up,
  iteraciones, entorno de referencia, métrica p95 y umbral; se ejecuta mediante
  un comando documentado, fuera de la suite unitaria ordinaria y del CI
  estándar. Registra resultados y alerta regresiones relevantes. La latencia de
  aceptación `202` excluye la generación completa DOCX/PDF. Los benchmarks
  podrán convertirse en gate de release mediante una decisión futura cuando
  exista infraestructura estable y resultados reproducibles.

- Q: ¿Cómo deben aislarse y cancelarse los renderers al vencer un timeout? → A:
  DOCX y PDF se ejecutan en procesos hijos aislados y terminables, uno por
  operación, iniciados con el contexto `spawn`. El hijo recibe únicamente datos
  serializables y una ruta temporal segura. El timeout es de 30 s para DOCX y
  60 s para PDF; al vencer se solicita terminación, se espera una gracia breve,
  se fuerza `kill` si sigue activo, se hace `join`, se eliminan temporales y se
  registra `GENERATION_TIMEOUT`. El proceso fallido no se reutiliza. No se
  mantienen transacciones DB abiertas, se evitan zombis y nunca se publica un
  artefacto vencido. Los puertos de renderer siguen siendo reemplazables para
  pruebas; la cancelación cooperativa sola no es suficiente para librerías
  bloqueantes.

- Q: ¿Cómo debe rechazarse una solicitud Range en la descarga? → A: responder
  `416 Range Not Satisfiable` con el código estable `RANGE_NOT_SUPPORTED` y el
  envelope JSON uniforme con `request_id` y `timestamp`; incluir `Accept-Ranges: none`, no
  iniciar streaming, no leer el archivo completo y no devolver `Content-Range`
  de un recurso parcial inexistente. Ignorar Range y devolver `200` no es
  admisible porque puede producir comportamiento ambiguo en clientes y
  proxies.

### Estado de clarificación

No quedan decisiones funcionales abiertas en esta ronda de clarificación.
**Veredicto:** `READY_FOR_PLAN`.

## Resumen ejecutivo

Este incremento completa el circuito operativo posterior a la generación de
borradores introducido en 003. Permite abrir una sesión de revisión sobre una
versión inmutable, registrar comentarios anclados al contenido, solicitar y
verificar correcciones, cerrar la revisión con trazabilidad y producir una
representación exportable únicamente cuando una persona haya aprobado el
documento.

El incremento no vuelve autónomo al sistema: no decide la corrección jurídica,
no aprueba por sí mismo, no firma y no publica actos administrativos. La
exportación es una operación técnica sobre contenido ya aprobado y conserva un
hash, la versión exacta y los parámetros usados para reproducirla.

## Declaración del problema

### Estado actual

003 permite generar, editar, rechazar, aprobar y regenerar borradores, pero no
ofrece una superficie de revisión colaborativa ni una forma controlada de
obtener archivos utilizables fuera de la API. Las observaciones de una persona
revisora quedan fuera del modelo de datos o se pierden en intercambios
manuales. Además, no existe una barrera uniforme que impida exportar contenido
no aprobado o que permita demostrar qué versión terminó en un archivo.

### Estado deseado

El personal de Legal y Técnica puede:

1. Abrir una revisión para una versión concreta del borrador.
2. Añadir comentarios generales o anclados a una sección/intervalo estable,
   con severidad y autor.
3. Resolver o descartar comentarios sin perder el historial original.
4. Enviar la versión a decisión y aprobarla o solicitar cambios con control
   optimista y eventos append-only.
5. Previsualizar la versión aprobada como HTML y exportarla a DOCX o PDF.
6. Consultar el estado, hash, parámetros y auditoría de cada exportación.
7. Reintentar de forma idempotente una exportación fallida sin crear artefactos
   duplicados.

### Impacto del negocio

La revisión estructurada reduce intercambios manuales, hace visibles las
correcciones pendientes y evita que una versión no validada llegue a un archivo
operativo. La exportación reproducible permite compartir el resultado con los
procesos administrativos existentes sin introducir todavía firma digital,
publicación automática o integraciones externas.

## Alcance funcional

### Historias de usuario

**HU-01: Abrir revisión de una versión**
Como revisor autorizado, quiero abrir o recuperar la sesión de revisión de una
versión del borrador para saber si está pendiente de análisis y quién la está
revisando.

**HU-02: Anotar un documento**
Como revisor, quiero agregar comentarios generales o anclados a una sección del
documento, con severidad y texto, para indicar correcciones concretas.

**HU-03: Gestionar observaciones**
Como revisor, quiero responder, resolver o descartar una observación sin
eliminarla para conservar la trazabilidad de la decisión.

**HU-04: Enviar una revisión a decisión**
Como editor, quiero enviar una versión cuando las observaciones aplicables
fueron atendidas para que una persona revisora pueda aprobarla o solicitar
cambios.

**HU-05: Aprobar o solicitar cambios**
Como revisor, quiero aprobar la versión o solicitar cambios con un motivo
obligatorio, para que el estado del borrador y el historial reflejen la decisión
humana.

**HU-06: Previsualizar**
Como usuario autorizado, quiero obtener una previsualización HTML de la versión
aprobada para verificar el resultado visual antes de descargar un archivo.

**HU-07: Exportar un documento**
Como usuario autorizado, quiero previsualizar una versión aprobada como HTML y
solicitar un archivo DOCX o PDF para utilizarlo en el circuito administrativo
vigente.

**HU-08: Consultar exportaciones**
Como usuario autorizado, quiero consultar el estado, hash, formato, versión y
errores de una exportación para poder auditarla o reintentarla.

**HU-09: Auditar el ciclo completo**
Como responsable de auditoría, quiero consultar los eventos de revisión y
exportación en orden cronológico, para reconstruir quién hizo cada cambio y qué
contenido se exportó.

## Requisitos funcionales

### Revisión y comentarios

- **FR-001**: El sistema DEBE crear o recuperar una sesión de revisión por
  `draft_id` y `draft_version`, sin mezclar versiones distintas. Al abrirla
  DEBE persistir el snapshot canónico de esa versión y su SHA-256; ambos son
  inmutables durante toda la revisión.
- **FR-002**: Una sesión DEBE tener estados `OPEN`, `SUBMITTED`, `CHANGES_REQUESTED`,
  `APPROVED` o `CLOSED`, con transiciones explícitas y auditadas.
- **FR-003**: El sistema DEBE permitir comentarios generales y comentarios
  anclados a una sección o rango de texto del snapshot revisado.
- **FR-004**: Cada comentario DEBE guardar autor, timestamp, severidad
  (`INFO`, `SUGGESTION`, `WARNING`, `BLOCKING`), cuerpo y referencia de anclaje
  cuando corresponda.
- **FR-005**: El anclaje DEBE incluir una referencia estable a la versión y no
  puede apuntar a contenido de otra versión.
- **FR-006**: Un comentario DEBE poder marcarse como `OPEN`, `RESOLVED` o
  `DISMISSED`; los cambios de estado deben crear un evento y no borrar datos.
- **FR-007**: El sistema DEBE permitir respuestas enlazadas a un comentario y
  conservar el orden temporal de la conversación.
- **FR-008**: El texto de comentarios y respuestas DEBE estar limitado a 10.000
  caracteres por entrada y rechazarse con error estructurado si excede el límite.
- **FR-009**: No se puede cerrar o aprobar una revisión con comentarios
  `BLOCKING` abiertos.
- **FR-010**: La aprobación DEBE exigir actor, timestamp, versión revisada y una
  confirmación explícita de revisión humana.
- **FR-011**: Solicitar cambios DEBE exigir una observación no vacía y mover el
  borrador a `RECHAZADO` o al estado equivalente definido por 003.
- **FR-012**: La edición o regeneración de un borrador DEBE invalidar la sesión
  abierta de la versión anterior para exportación, sin eliminar su historial.
  La invalidación se registra como evento y la sesión anterior no puede
  reutilizarse para la nueva versión.

### Control de concurrencia y auditoría

- **FR-013**: Las operaciones mutables DEBEN aceptar `expected_version` o `If-Match` y
  devolver `CONCURRENT_MODIFICATION` cuando el valor no coincida.
- **FR-014**: Cada transición, comentario, respuesta, resolución, aprobación,
  rechazo y exportación DEBE producir un evento append-only con request ID. Los
  eventos del comando administrativo de reconciliación usan `run_id` como
  identificador de trazabilidad de la corrida.
- **FR-015**: Los eventos DEBEN incluir actor, recurso, versión, tipo, timestamp
  UTC y un resumen minimizado; nunca deben incluir secretos ni prompts completos.
- **FR-015.1**: `finalized_by` y `exported_by` DEBEN ser obligatorios en sus
  operaciones respectivas, strings con trim de 1 a 100 caracteres, no vacíos ni
  compuestos solo por espacios. Se permiten letras Unicode, números, espacios,
  punto, guion, guion bajo y `@`; se conservan las mayúsculas/minúsculas y se
  compara el valor exacto después de trim. Estos campos no DEBEN usarse para
  autenticación o autorización, no requieren unicidad, no pueden aparecer en
  `file_name`, `storage_path` ni rutas y solo representan el actor de auditoría.
  `finalized_by` llega en el body de finalización y `exported_by` en los bodies
  de creación, retry y regeneración. Un valor inválido devuelve
  `VALIDATION_ERROR`; `request_id` permanece solo para trazabilidad en header o
  middleware. La representación textual debe conservar compatibilidad para una
  futura sustitución por `authenticated_subject_id`, sin convertir esos campos
  en identificadores de autorización en 004.
- **FR-016**: Las lecturas DEBEN permitir recuperar el estado actual y el
  historial ordenado sin alterar registros.
- **FR-017**: Las mutaciones de revisión DEBEN exigir `Idempotency-Key` de
  16–100 caracteres seguros: crear review, crear comentario, actualizar
  comentario, submit, approve y request-changes. El backend DEBE calcular un
  `request_hash` JSON canónico y usar como scope la operación, el recurso
  principal y la clave. Dentro de 24 horas, la misma clave y payload DEBEN
  devolver replay de la respuesta previa; un payload diferente DEBE devolver
  `409 IDEMPOTENCY_CONFLICT`; una operación `PROCESSING` DEBE devolver
  `409 REVIEW_OPERATION_IN_PROGRESS`. `request_id` solo sirve para trazabilidad.

### Previsualización y exportación

- **FR-018**: El endpoint de previsualización DEBE renderizar el snapshot exacto
  de una versión, sin llamar al modelo y sin cambiar su estado.
- **FR-018.1**: El endpoint DEBE ser `GET
  /api/v1/drafts/{draft_id}/preview?draft_version={n}` y aceptar únicamente
  drafts `APPROVED`. Antes de la finalización DEBE exigir que `draft_version`
  sea la versión aprobada actual y renderizar ese contenido; después de la
  finalización DEBE exigir que `draft_version` sea la versión final actual y
  usar exclusivamente `final_snapshot`. Un draft finalizado DEBE seguir siendo
  previsualizable.
  La respuesta DEBE ser `text/html; charset=utf-8`, incluir un `ETag` basado en
  SHA-256 y usar `Cache-Control: no-store`. El preview DEBE ser efímero: no
  persiste archivos, no crea `document_exports`, no modifica estado y no
  incrementa `document_drafts.version`.
- **FR-019**: Solo una versión `APROBADA`, con revisión cerrada y sin comentarios
  `BLOCKING` abiertos, puede exportarse.
- **FR-020**: El backend DEBE volver a verificar la elegibilidad en el momento
  de exportar; no puede confiar únicamente en una comprobación previa de UI.
- **FR-021**: El sistema DEBE aceptar únicamente los formatos persistidos
  `DOCX` y `PDF`, y rechazar `HTML` o cualquier otro formato de exportación con
  `EXPORT_FORMAT_UNSUPPORTED`. HTML queda reservado para preview y pipeline
  interno no persistido.
- **FR-022**: El HTML DEBE ser sanitizado, autocontenido para la previsualización
  y no permitir scripts, iframes ni referencias remotas no declaradas.
- **FR-023**: DOCX y PDF DEBEN derivarse de la misma representación canónica que
  HTML; las diferencias de maquetación no pueden cambiar el texto aprobado.
- **FR-023.1**: El pipeline de PDF DEBE renderizar el HTML canónico mediante un
  adaptador headless reemplazable. No debe convertir DOCX a PDF ni depender de
  una biblioteca concreta en esta especificación.
- **FR-024**: El artefacto DEBE conservar `draft_id`, `draft_version`, formato,
  `renderer_version`, hash SHA-256, actor y timestamp de creación.
- **FR-025**: El contenido del artefacto DEBE ser inmutable. Una nueva solicitud
  con parámetros distintos crea un nuevo registro; una repetición idempotente
  devuelve el registro existente.
- **FR-026**: Una exportación debe tener estados `PENDING`, `GENERATING`,
  `GENERATED`, `FAILED` o `SUPERSEDED`; los fallos deben conservar código y
  mensaje seguro.
- **FR-027**: El sistema DEBE permitir reintentar una exportación fallida sin
  modificar el borrador ni la revisión aprobada.
- **FR-027.1**: Cada procesamiento de una exportación DEBE registrar un
  `export_attempt`, tanto si termina correctamente como si falla. Un retry de
  `FAILED` reutiliza la misma exportación, crea un attempt nuevo y, dentro de
  Tx1, transiciona la exportación a `GENERATING` y el attempt a `PROCESSING`
  antes del commit. La generación ocurre fuera de PostgreSQL y Tx2 marca
  `GENERATED`/`SUCCEEDED` o `FAILED`; no existe una transacción intermedia.
- **FR-027.2**: Una exportación `GENERATED` solo puede pasar a `SUPERSEDED`
  después de que una regeneración compatible termine exitosamente. Los estados
  `GENERATED` y `SUPERSEDED` son descargables.
- **FR-027.3**: La creación, el retry y la regeneración de una exportación DEBEN
  exigir el header `Idempotency-Key`, con longitud de 16 a 100 caracteres y
  caracteres seguros. La ventana de idempotencia es de 24 horas.
- **FR-027.4**: `export_attempts` DEBE guardar `request_hash`. En la creación,
  la misma clave y payload con intento activo devuelve `409 EXPORT_IN_PROGRESS`,
  con éxito devuelve replay `200`, con payload diferente devuelve
  `409 IDEMPOTENCY_CONFLICT` y con export fallido devuelve sus metadatos sin
  crear otro attempt; el retry es el único endpoint que crea el siguiente
  attempt. `request_id` se usa exclusivamente para trazabilidad.
- **FR-027.5**: Cada reintento de un intento `FAILED` DEBE crear una nueva fila
  en `export_attempts` con el mismo `idempotency_key` y `request_hash`, y un
  `attempt_number` incremental. Debe existir como máximo un intento activo
  (`PENDING` o `PROCESSING`) por `exported_by + idempotency_key`, mediante un
  índice único parcial o constraint equivalente.
- **FR-028**: El endpoint de descarga DEBE validar que el artefacto pertenece a
  la versión persistida del `export_id` solicitado y devolver
  `EXPORT_NOT_FOUND` si no existe.
- **FR-028.1**: `GET /api/v1/exports/{export_id}/download` solo DEBE permitir
  artefactos `GENERATED` o `SUPERSEDED` y DEBE responder el binario en
  streaming con `Content-Disposition: attachment`, `ETag` basado en SHA-256 y
  `Cache-Control: private, no-store`. En 004 no se soportan Range requests. Si
  la solicitud incluye `Range`, el backend DEBE responder `416 Range Not
  Satisfiable` con `RANGE_NOT_SUPPORTED`, envelope JSON uniforme con
  `request_id`, `timestamp` y `Accept-Ranges: none`; no DEBE iniciar streaming, leer el
  archivo completo ni devolver `Content-Range`; este rechazo DEBE tener
  precedencia sobre `If-None-Match`. Antes de iniciar una descarga
  válida, el backend DEBE validar la ruta canónica y el hash; no debe exponer
  `storage_path`. Un archivo ausente DEBE producir
  `EXPORT_FILE_NOT_FOUND` y un hash inconsistente DEBE producir
  `EXPORT_FILE_CORRUPTED`.
- **FR-028.2**: El sistema DEBE calcular SHA-256 al crear cada artefacto y
  recalcularlo antes de cada descarga. Para DOCX DEBE validar extensión `.docx`,
  MIME `application/vnd.openxmlformats-officedocument.wordprocessingml.document`,
  ZIP válido, presencia de `[Content_Types].xml` y `word/document.xml`, máximo
  500 entradas, 50 MiB (52.428.800 bytes) descomprimidos y ratio de compresión
  máximo 100:1. Para
  PDF DEBE validar extensión `.pdf`, MIME `application/pdf`, encabezado `%PDF-`
  y marcador `%%EOF` en el tramo final. La corrupción DEBE bloquear la
  descarga, registrar un evento y devolver `EXPORT_FILE_CORRUPTED`; no DEBE
  cambiar automáticamente `GENERATED` a `FAILED` y requiere regeneración
  explícita.
- **FR-029**: Los límites DEBEN medirse sobre bytes, no caracteres, y ser:
  contenido editable con techo máximo 2 MiB (2.097.152 bytes);
  los endpoints de edición heredados de 003 conservan el límite efectivo de
  100 KiB y `CONTENT_TOO_LARGE`; 004 eleva el límite efectivo de runtime a
  2 MiB sin modificar los artefactos documentales de 003; `final_snapshot`
  máximo 2 MiB (2.097.152 bytes) serializado; preview HTML máximo 5 MiB
  (5.242.880 bytes); DOCX máximo 20 MiB (20.971.520 bytes); PDF máximo 30 MiB
  (31.457.280 bytes). Las pruebas DEBEN cubrir el límite exacto, el límite más
  un byte y contenido multibyte. El sistema DEBE devolver
  `CONTENT_TOO_LARGE` o `EXPORT_SIZE_EXCEEDED` según corresponda.
- **FR-029.1**: Los timeouts DEBEN ser 30 s para DOCX y 60 s para PDF. Cada
  operación de render DEBE ejecutarse en un proceso hijo aislado y terminable,
  iniciado con contexto `spawn`, y el hijo solo DEBE recibir datos
  serializables y rutas temporales seguras. Al vencer el timeout, el
  orquestador DEBE solicitar terminación, esperar una gracia breve, forzar
  `kill` si el hijo sigue activo, ejecutar `join`, eliminar temporales y
  registrar `GENERATION_TIMEOUT`. No DEBE reutilizar el proceso fallido,
  mantener transacciones DB abiertas durante el render, dejar procesos zombis
  ni publicar artefactos vencidos. Los puertos de renderer DEBEN permanecer
  reemplazables para pruebas; la cancelación cooperativa sola no es garantía de
  terminación frente a librerías bloqueantes. `file_name` DEBE tener como máximo
  120 caracteres y la ruta relativa DEBE
  tener como máximo 500 caracteres. `finalization_notes` DEBE tener como
  máximo 2.000 caracteres; la identidad textual de actor DEBE tener entre 1 y
  100 caracteres; `page_size` DEBE tener como máximo 100. No existe un límite
  funcional adicional de versiones y solo puede existir una generación activa
  por `draft_id + format`.
- **FR-029.2**: El nombre de archivo DEBE ser determinista y seguir
  `{draft_id}_v{export_version}.{extension}`. Debe estar en minúsculas y contener
  únicamente UUID, dígitos, guion bajo, punto y extensión; no puede contener
  espacios, doble extensión, PII, `case_number`, nombres personales,
  `document_type` ni fechas. La combinación `draft_id + format + export_version` DEBE
  impedir colisiones.
- **FR-030**: La generación del archivo NO DEBE invocar Ollama, embeddings,
  recuperación vectorial ni servicios externos.
- **FR-030.1**: El DOCX DEBE cumplir requisitos institucionales verificables:
  formato A4 vertical; márgenes superior e inferior de 2,5 cm, izquierdo de
  3 cm y derecho de 2 cm; cuerpo Arial 11; título Arial 12 negrita centrado;
  texto justificado, interlineado 1,5 y espaciado posterior de 6 pt; encabezado
  institucional configurable; secciones `VISTO`, `CONSIDERANDO` y `POR ELLO`;
  artículos numerados `ARTÍCULO 1°`, `ARTÍCULO 2°`, etc.; espacios de firma
  configurables; y ningún pie de página salvo numeración de página. DEBE usar
  locale `es-AR`, excluir metadatos con datos personales innecesarios y devolver
  un error de validación cuando falten datos obligatorios.

### Errores y contrato HTTP

- **FR-031**: Los errores DEBEN reutilizar o extender, sin crear un serializer
  público separado para 004, exactamente el envelope público vigente de 003:
  `{"error":{"code":"...","message":"...","details":{},"request_id":"...","timestamp":"2026-08-03T21:00:00Z"}}`.
  `code` es estable; `message` y `details` deben estar sanitizados y no pueden
  contener paths internos, stack traces, excepciones de librerías, secretos ni
  contenido documental. `timestamp` es obligatorio, lo genera el servidor en
  UTC y usa RFC 3339 con sufijo `Z`.
- **FR-031.1**: Todas las respuestas JSON, exitosas o de error, DEBEN incluir
  `request_id`. Las respuestas binarias de descarga no exponen un envelope
  JSON, pero conservan el request ID en la trazabilidad de la solicitud.
- **FR-032**: UUID inválido DEBE responder 422 `INVALID_UUID`; las transiciones
  de revisión inválidas DEBEN conservar los errores heredados de 003,
  incluyendo `INVALID_REVIEW_TRANSITION` (409), y los recursos inexistentes
  DEBEN usar el código específico de recurso.
- **FR-032.1**: El catálogo canónico de 004 DEBE mapear
  `REVIEW_NOT_FOUND`, `COMMENT_NOT_FOUND`, `DRAFT_NOT_FOUND` y
  `EXPORT_NOT_FOUND` a 404; `DRAFT_NOT_APPROVED`,
  `DRAFT_NOT_FINALIZED`, `DRAFT_ALREADY_FINALIZED`, `EXPORT_IN_PROGRESS`,
  `EXPORT_ALREADY_EXISTS`, `EXPORT_FILE_CORRUPTED`,
  `INVALID_EXPORT_TRANSITION`, `IDEMPOTENCY_CONFLICT`,
  `CONCURRENT_MODIFICATION`, `INVALID_REVIEW_TRANSITION`,
  `REVIEW_VERSION_MISMATCH`, `OPEN_BLOCKING_COMMENTS`,
  `REVIEW_OPERATION_IN_PROGRESS`,
  `ACTIVE_GENERATION_EXISTS` y `CLEANUP_CONFLICT` a 409;
  `RANGE_NOT_SUPPORTED` a 416;
  `EXPORT_FILE_NOT_FOUND` a 410; `INVALID_FINALIZATION`,
  `EXPORT_FORMAT_UNSUPPORTED`, `VALIDATION_ERROR`, `HUMAN_REVIEW_REQUIRED`,
  `MISSING_REVIEW_REASON`, `ANCHOR_VERSION_MISMATCH` y
  `MIME_VALIDATION_FAILED` durante creación a 422; y
  `IDEMPOTENCY_KEY_REQUIRED` a 400.

  | Código de revisión | Condición | Endpoint o capa | HTTP | Mensaje público sanitizado | Prueba prevista |
  |---|---|---|---:|---|---|
  | `REVIEW_NOT_FOUND` | No existe la revisión solicitada | current y operaciones `/reviews/{review_id}` / review service | 404 | `The requested review was not found.` | T059/T061 |
  | `COMMENT_NOT_FOUND` | No existe el comentario solicitado | PATCH comment / review service | 404 | `The requested review comment was not found.` | T059/T061 |
  | `INVALID_REVIEW_TRANSITION` | El estado actual no permite la mutación | submit, approve, request-changes y comment mutations / state machine | 409 | `The requested review transition is not allowed.` | T059/T061 |
  | `REVIEW_VERSION_MISMATCH` | `expected_version` no coincide con la revisión | mutaciones `/reviews/{review_id}` / review repository | 409 | `The review version does not match the expected version.` | T059/T061 |
  | `OPEN_BLOCKING_COMMENTS` | Existen comentarios blocking abiertos | submit, approve y finalize / review gate | 409 | `The review has unresolved blocking comments.` | T059/T061 |
  | `HUMAN_REVIEW_REQUIRED` | Falta confirmación humana explícita | approve / review service | 422 | `Human review confirmation is required.` | T059/T061 |
  | `MISSING_REVIEW_REASON` | Request-changes no incluye motivo válido | request-changes / review schema | 422 | `A reason is required to request changes.` | T059/T061 |
  | `ANCHOR_VERSION_MISMATCH` | El ancla no pertenece a `draft_version` revisada | POST comments / anchor validator | 422 | `The comment anchor does not match the reviewed draft version.` | T059/T061 |
  | `REVIEW_OPERATION_IN_PROGRESS` | Ya existe la misma operación idempotente activa | seis mutaciones de review / idempotency service | 409 | `A review operation with this idempotency key is already in progress.` | T059/T061 |

  El catálogo no define `REVIEW_ALREADY_EXISTS` ni `INVALID_REVIEW_STATUS`.
- **FR-032.2**: `EXPORT_SIZE_EXCEEDED` DEBE responder 413;
  `EXPORT_GENERATION_FAILED` y `FILESYSTEM_ERROR`, 500;
  `GENERATION_TIMEOUT`, 504; `EXPORT_STORAGE_UNAVAILABLE` y
  `DATABASE_ERROR`, 503. Durante descarga, cualquier fallo de hash, MIME,
  estructura, truncamiento o vacío DEBE responder únicamente
  `EXPORT_FILE_CORRUPTED` (409); `HASH_VALIDATION_FAILED` y
  `MIME_VALIDATION_FAILED` quedan como causas internas. `PATH_VALIDATION_FAILED` DEBE
  responder 500 sin exponer detalles internos. No se usa HTTP 507.
- **FR-033**: Intentar exportar una versión no aprobada DEBE responder 409
  `DRAFT_NOT_APPROVED` sin generar un archivo parcial; una finalización sin
  snapshot válido DEBE responder 409 `DRAFT_NOT_FINALIZED`.
- **FR-034**: Un fallo de generación ocurrido después de responder `202`
  DEBE registrar el export y el attempt como `FAILED`, persistir un código y
  mensaje sanitizados y quedar consultable por metadata/attempts; no puede
  cambiar la respuesta HTTP inicial. `EXPORT_GENERATION_FAILED` (500),
  `GENERATION_TIMEOUT` (504), `EXPORT_STORAGE_UNAVAILABLE` (503) o el error de
  validación específico solo pueden responderse antes de aceptar/programar la
  operación, cuando no se dejó un recurso activo válido.
- **FR-035**: Todas las respuestas DEBEN omitir `storage_path`, errores
  internos, contenido documental y cualquier secreto.

- **FR-019.1**: La finalizacion DEBE aceptar `expected_version`; si coincide,
  debe incrementar `document_drafts.version` y guardar `finalized_by`, `finalized_at`,
  `finalization_notes` y el snapshot final inmutable. El estado del borrador
  debe continuar siendo `APROBADO`.

- **FR-035.1**: El catálogo HTTP DEBE incluir `IDEMPOTENCY_CONFLICT` (409) y
  `EXPORT_IN_PROGRESS` (409) para los casos definidos en la política de
  idempotencia.
- **FR-035.2**: Las listas DEBEN usar `page`, `page_size`, filtros explícitos
  cuando correspondan y un orden estable por `created_at DESC, id DESC`.
  `page_size` no puede superar 100. `Idempotency-Key` es obligatorio en
  creación, retry y regeneración; `expected_version` es obligatorio en
  finalización, mutaciones de revisión y regeneración.
- **FR-036**: La migración 004 DEBE alterar `document_drafts`, crear
  `document_exports` y crear `export_attempts`, en ese orden; su downgrade DEBE
  eliminar `export_attempts`, luego `document_exports` y finalmente revertir
  los campos agregados a `document_drafts`. La migración depende exactamente de
  la revisión 003 y no modifica la migración 003.
- **FR-037**: La primera finalización solo puede ejecutarse desde un draft
  `APPROVED` cuya revisión esté cerrada y sin bloqueos abiertos. Requiere
  `expected_version`, fija el snapshot final y deja el draft sin mutaciones.
- **FR-037.1**: Una solicitud repetida con actor, notas, snapshot y versión
  coincidentes DEBE devolver `200` con el resultado existente. Un payload
  diferente DEBE devolver `409 DRAFT_ALREADY_FINALIZED`; un
  `expected_version` obsoleto DEBE devolver `409 CONCURRENT_MODIFICATION`.
- **FR-037.2**: Después de `finalized_at` no se permite editar contenido,
  modificar la revisión, rechazar, aprobar nuevamente ni regenerar el draft.
  Las regeneraciones posteriores solo pueden crear nuevas exportaciones y no
  modifican el snapshot final del draft.
- **FR-038**: El `storage_path` DEBE persistirse como ruta relativa con layout
  `{case_file_id}/{draft_id}/{format}/v{export_version}/{file_name}` bajo el root
  configurable `EXPORT_STORAGE_ROOT`. Nunca puede contener una ruta absoluta,
  `..`, PII, `case_number` ni datos personales.
- **FR-038.1**: Antes de abrir o mover un archivo, el backend DEBE resolver
  canónicamente el path y verificar que permanece dentro del root; cualquier
  segmento symlink debe rechazarse. Los formatos y extensiones se validan
  contra una allowlist de DOCX/PDF.
- **FR-038.2**: Los directorios deben crearse con `0700` y los archivos con
  `0600` cuando el sistema lo permita. Los temporales deben ser aleatorios,
  ubicarse en el mismo directorio de destino y publicarse mediante
  `os.replace` o rename atómico.
- **FR-039**: La creación de una exportación DEBE seguir exactamente dos
  transacciones cortas. Tx1 valida draft, idempotencia y concurrencia, reserva
  `export_version`, crea `document_export=PENDING` y `export_attempt=PENDING`,
  y confirma dentro de esa misma transacción las transiciones iniciales a
  `GENERATING` y `PROCESSING`. La generación, validación y rename ocurren fuera
  de PostgreSQL. Tx2 marca la exportación `GENERATED`, el intento `SUCCEEDED` y
  la exportación anterior `SUPERSEDED` solo después del rename exitoso; ante un
  fallo marca export y attempt `FAILED` y persiste el error sanitizado. No
  existe una transacción intermedia para marcar los estados activos.
- **FR-039.1**: Antes de Tx2 se validan tamaño, extensión, MIME y SHA-256. Un
  fallo de generación o validación elimina el temporal y Tx2 marca export y
  attempt como `FAILED` con error sanitizado. Si el rename ya ocurrió y Tx2 no
  puede confirmar, se intenta eliminar el archivo definitivo y no se abre una
  tercera transacción DB; el registro queda como incidencia incompleta para
  reconciliación manual. No se considera descargable ningún archivo sin
  confirmación DB en `GENERATED` o `SUPERSEDED`.
- **FR-039.2**: Debe existir reconciliación manual para detectar registros sin
  archivo, archivos huérfanos, temporales y estados incompletos. 004 no agrega
  scheduler, Redis ni colas para esta tarea.
- **FR-039.3**: `GENERATED` y `SUPERSEDED` DEBEN tener retención indefinida.
  Los metadatos de `document_exports` fallidos DEBEN conservarse. Los
  `export_attempts` fallidos DEBEN conservarse al menos 180 días; luego pueden
  ser candidatos a cleanup manual. Los temporales pueden limpiarse manualmente
  después de 24 horas y los archivos huérfanos después de 7 días desde su
  detección. Los registros sin archivo y los archivos corruptos no se eliminan
  automáticamente.
- **FR-039.4**: No DEBE existir endpoint público de DELETE ni scheduler, Redis o
  cola para cleanup. El comando administrativo lógico DEBE ser
  `document-exports reconcile`, con dry-run por defecto y eliminación efectiva
  solo mediante `--execute`. Debe aceptar filtros por `case_file_id`, `draft_id`,
  formato, tipo de incidencia y antigüedad, y devolver JSON con `run_id`,
  candidatos, eliminados, omitidos, conflictos y errores. Cada acción DEBE
  auditar actor, timestamp UTC, recurso, acción y resultado. El mismo `run_id`
  con los mismos filtros DEBE devolver el resultado existente; el mismo
  `run_id` con filtros diferentes DEBE producir `CLEANUP_CONFLICT`. Nunca se
  puede eliminar el último `GENERATED` válido ni un archivo asociado a un
  intento `PROCESSING` activo.
- **FR-039.5**: `POST /api/v1/exports/{export_id}/regenerate` DEBE aceptar solo
  `GENERATED` o `SUPERSEDED`, recibir `{expected_version, exported_by}` y exigir
  `Idempotency-Key`. Puede operar aunque falte o esté corrupto el archivo
  origen, porque DEBE regenerar exclusivamente desde `final_snapshot` y
  conservar el formato. DEBE crear un nuevo `document_export` y
  `export_attempt`, apuntar `parent_export_id` al origen, asignar
  `max(export_version) + 1` para `(draft_id, format)` y generar nuevo SHA-256 y
  `storage_path`. `expected_version` DEBE coincidir con la versión máxima
  actual; si no, devuelve `CONCURRENT_MODIFICATION`. La respuesta inicial es
  `202` con export `GENERATING` y attempt `PROCESSING`; una repetición idempotente con el
  mismo payload puede devolver `200`. La exportación `GENERATED` vigente solo
  pasa a `SUPERSEDED` tras el éxito de la nueva; un origen `SUPERSEDED` no
  cambia. Si falla, el artefacto anterior conserva estado y descargabilidad.
  `FAILED` se reintenta con
  `POST /api/v1/exports/{export_id}/retry`, la misma clave y un nuevo
  `export_attempt`, sin crear otro `document_export`.

## Modelo conceptual

### `document_reviews`

Representa una revisión de una versión inmutable del borrador.

- `id` UUID, clave primaria.
- `draft_id` UUID y `draft_version` entero, referencia lógica a 003.
- `status` enum de revisión.
- `opened_by`, `submitted_by`, `decided_by` son actores textuales auditables de
  hasta 100 caracteres; `opened_by` es obligatorio y los restantes son
  opcionales según la transición.
- `opened_at`, `submitted_at`, `decided_at` UTC.
- `review_snapshot` JSONB y `review_snapshot_sha256` CHAR(64), ambos
  obligatorios, con el snapshot canónico inmutable de `draft_version`.
- `version` entero para optimistic locking; no representa una `draft_version`
  ni una `export_version`.
- Restricción única `(draft_id, draft_version)`.

La operación `approve` registra la decisión `APPROVED` y deja la revisión en
`CLOSED` dentro de la misma transacción; no existe un endpoint público de
cierre separado y el evento conserva ambas partes de la transición.

El snapshot se fija al abrir la revisión y nunca se actualiza aunque el draft
cambie posteriormente. Submit, approve, request-changes y todos los anclajes
leen esta copia persistida; una nueva versión exige una nueva revisión.

### `review_comments`

Contiene observaciones y respuestas sin borrado físico.

- `id` UUID, `review_id` UUID, `parent_comment_id` opcional.
- `severity`, `status`, `body` y `anchor` JSON validado.
- `author` y `created_at` obligatorios; `resolved_by` y `resolved_at` son
  opcionales según el estado del comentario.
- `draft_version` obligatorio para impedir anclajes cruzados.
- Índices por `review_id`, estado y severidad.

La tabla existente `document_drafts` se extiende sin agregar un estado nuevo:

- `finalized_by VARCHAR(100) NULL`.
- `finalized_at TIMESTAMPTZ NULL`.
- `finalization_notes TEXT NULL`.
- `final_snapshot JSONB NULL`, con el contenido canónico y metadatos usados
  para exportar.
- `final_snapshot_sha256 CHAR(64) NULL`.
- Se reutiliza `document_drafts.version`; no se agrega otra versión de draft.
- Un CHECK exige coherencia entre los campos de finalización: si existe
  `finalized_at`, existen actor, snapshot y hash; si no existe, permanecen
  nulos. Las notas pueden ser nulas, pero no una cadena vacía cuando se
  informan.
- Los campos de finalización son write-once: una vez que `finalized_at` no es
  nulo, no se actualizan ni se limpian. La inmutabilidad se valida con
  optimistic locking y la regla de dominio de finalización.

### `document_exports`

Registra el artefacto generado y su reproducibilidad.

- `id` UUID, `draft_id`, `draft_version`, `review_id`.
- `format`, `status`, `storage_path`, `content_sha256`.
- `renderer_name`, `renderer_version`, `source_snapshot_sha256`.
- `exported_by`, `created_at`, `completed_at`, `error_code` opcional.
- La identidad idempotente (`idempotency_key` + `request_hash` + actor) se
  conserva en `export_attempts`; la unicidad se aplica a los intentos activos
  por actor y clave.
- No contiene el texto completo en columnas de auditoría; el binario vive en
  el adaptador de almacenamiento configurado.

Cada ejecucion de procesamiento se registra en `export_attempts` con su
resultado, error sanitizado, request ID, actor y timestamps. Un fallo no crea
un artefacto descargable ni una nueva `export_version` válida de `document_exports`.

`format` solo puede ser `DOCX` o `PDF`; HTML no crea un `DocumentExport` y se
mantiene como preview y representacion intermedia no persistida.

`export_attempts` debe conservar la `Idempotency-Key`, `request_hash`, estado,
timestamps, resultado, error sanitizado, actor y request ID de cada
procesamiento. La unicidad se aplica solo a intentos activos por actor y clave;
los intentos `FAILED` pueden coexistir para auditar reintentos y se conservan al
menos 180 días. La ventana de idempotencia es de 24 horas y `request_id` no
participa en la identidad idempotente.

`review_operation_requests` persiste la idempotencia de las mutaciones de
review cuando 003 no cubre scope y replay: operación, recurso principal,
clave, `request_hash`, `PROCESSING|SUCCEEDED|FAILED`, status/payload de
respuesta sanitizados, error, timestamps, `expires_at` y `request_id`, con
unicidad `(operation, resource_id, idempotency_key)`. Una fila expirada se
reutiliza bajo lock como una nueva ventana y nunca se usa para replay.

La tabla `document_exports` usa:

- `export_version INTEGER NOT NULL DEFAULT 1`, independiente por `draft_id + format`.
- `parent_export_id UUID NULL`, FK autorreferente para regeneración.
- `format` restringido a `DOCX` o `PDF`; `status` restringido a `PENDING`,
  `GENERATING`, `GENERATED`, `FAILED` o `SUPERSEDED`.
- `storage_path VARCHAR(500) NULL`, siempre relativo al root configurable y
  con layout `{case_file_id}/{draft_id}/{format}/v{export_version}/{file_name}`; el
  root real se obtiene exclusivamente de `EXPORT_STORAGE_ROOT`.
- `content_sha256 CHAR(64) NULL`, obligatorio antes de marcar `GENERATED`.
- `source_snapshot_sha256 CHAR(64) NOT NULL`, `renderer_name`,
  `renderer_version`, `exported_by`, `created_at`, `updated_at`,
  `completed_at`, `error_code` y `error_message` sanitizado.
- PK `id`; FK obligatoria a `document_drafts`; UNIQUE (`draft_id`, `format`,
  `export_version`); índices por (`draft_id`, `format`, `status`) y
  `parent_export_id`.

La entidad `export_attempts` registra cada procesamiento:

- `id UUID` PK; `draft_id UUID NOT NULL` FK a `document_drafts`.
- `export_id UUID NOT NULL` FK a `document_exports`; referencia la fila de
  `document_exports` creada en Tx1, incluso mientras el intento está pendiente
  o termina en fallo.
- `format` restringido a `DOCX` o `PDF`.
- `idempotency_key VARCHAR(100) NOT NULL` con CHECK de longitud 16–100.
- `request_hash CHAR(64) NOT NULL`.
- `attempt_number INTEGER NOT NULL DEFAULT 1`.
- `status` restringido a `PENDING`, `PROCESSING`, `SUCCEEDED` o `FAILED`.
- `started_at`, `completed_at`, `created_at` y `updated_at` UTC; `completed_at`
  es nulo mientras el intento está activo.
- `error_code` y `error_message` sanitizado, ambos anulables.
- `request_id VARCHAR(100) NOT NULL` solo para trazabilidad.
- `exported_by VARCHAR(100) NOT NULL`.
- Índice único parcial por (`exported_by`, `idempotency_key`) WHERE `status` IN
  (`PENDING`, `PROCESSING`), para impedir dos intentos activos.
- Índices por (`draft_id`, `format`), `status` y
  (`exported_by`, `idempotency_key`, `created_at`). Los intentos `FAILED` se
  conservan al menos 180 días y un retry crea el siguiente
  `attempt_number`.

### Transiciones

> El diagrama historico que sigue conserva nomenclatura del draft inicial. La
> maquina normativa vigente es la definida arriba (`PENDING`, `GENERATING`,
> `GENERATED`, `FAILED`, `SUPERSEDED`); el diagrama historico no debe usarse
> para implementar el incremento.

La maquina normativa de exportacion es `PENDING -> GENERATING -> GENERATED`,
con `GENERATING -> FAILED -> GENERATING` para reintentos. Una exportacion
`GENERATED` pasa a `SUPERSEDED` unicamente despues del exito de una nueva
exportacion compatible. Los artefactos `GENERATED` y `SUPERSEDED` se pueden
descargar; `PENDING`, `GENERATING` y `FAILED` no son descargables.

La representacion historica `REQUESTED/PROCESSING/COMPLETED` que pueda aparecer
en el diagrama de transiciones de este draft queda sustituida por la maquina
anterior y no debe usarse para implementar 004.

<!-- Legacy transition diagram retained for historical context only.
```text
Revisión: OPEN → SUBMITTED → APPROVED → CLOSED
                    └──────→ CHANGES_REQUESTED → OPEN

Exportación: REQUESTED → PROCESSING → COMPLETED
                         └──────────→ FAILED → PROCESSING
```

Una revisión con cambios solicitados puede abrirse nuevamente solo sobre una
nueva versión del borrador. Una exportación completada nunca vuelve a
`PROCESSING`; se crea otra exportación si cambia el renderer o el formato.

-->
<!-- End of legacy transition diagram. -->

## Contrato de API propuesto

- `POST /api/v1/drafts/{draft_id}/finalize` solo acepta un draft `APPROVED`
  con revisión cerrada; devuelve `200` si la finalización ya existe y coincide,
  `409 DRAFT_ALREADY_FINALIZED` si difiere y `409 CONCURRENT_MODIFICATION` si
  `expected_version` está obsoleto.

- `POST /api/v1/drafts/{draft_id}/exports`, `POST /api/v1/exports/{export_id}/retry`
  y `POST /api/v1/exports/{export_id}/regenerate` requieren `Idempotency-Key`;
  el payload se hashea para resolver repetición, conflicto, procesamiento
  activo y reintento fallido.

- El endpoint de exportación persistida solo acepta `DOCX` o `PDF`; el HTML
  se devuelve únicamente por preview y nunca se guarda como `DocumentExport`.

- `POST /api/v1/drafts/{draft_id}/finalize` — finaliza una `draft_version` `APROBADA`
  con `{expected_version, finalization_notes}` y el actor textual de la
  solicitud; devuelve los metadatos de finalizacion y el snapshot final.
- `POST /api/v1/exports/{export_id}/retry` — reintenta exclusivamente una
  exportacion `FAILED`; registra un nuevo `export_attempt` y no cambia el
  borrador ni la revision aprobada.

- `POST /api/v1/exports/{export_id}/regenerate` — crea una nueva exportación
  versionada desde `final_snapshot`, sin depender del archivo origen.

- `document-exports reconcile` — comando administrativo fuera de HTTP para
  detectar y, con `--execute`, limpiar únicamente temporales y huérfanos
  elegibles. Su salida es JSON y no expone rutas absolutas; los conflictos y
  errores se incluyen en el resumen y en los eventos de auditoría.

Los nombres son parte de la especificación funcional; los detalles de
autenticación quedan para el incremento de seguridad.

### Revisión

- `GET /api/v1/drafts/{draft_id}/reviews/current` — obtiene la revisión activa
  y el snapshot de la versión.
- `POST /api/v1/drafts/{draft_id}/reviews` — abre una revisión para una versión
  explícita; exige `Idempotency-Key` y persiste snapshot/hash inmutables.
- `POST /api/v1/reviews/{review_id}/comments` — crea comentario o respuesta y exige `Idempotency-Key`.
- `PATCH /api/v1/reviews/{review_id}/comments/{comment_id}` — cambia estado con
  `expected_version` e `Idempotency-Key`; el cuerpo original no se sobrescribe.
- `POST /api/v1/reviews/{review_id}/submit` — envía a decisión con `Idempotency-Key`.
- `POST /api/v1/reviews/{review_id}/approve` — aprueba con confirmación humana e `Idempotency-Key`.
- `POST /api/v1/reviews/{review_id}/request-changes` — solicita cambios con
  observación obligatoria e `Idempotency-Key`.
- `GET /api/v1/reviews/{review_id}/history` — lista eventos append-only.

### Previsualización y exportación

- Todas las respuestas JSON DEBEN incluir `request_id`. Las respuestas de lista
  DEBEN aceptar filtros explícitos, `page`, `page_size` máximo 100 y un orden
  estable `created_at DESC, id DESC`. Las mutaciones de revisión DEBEN recibir
  `expected_version`; finalización y regeneración también lo exigen. La
  creación, retry y regeneración DEBEN exigir `Idempotency-Key`.

- `POST /api/v1/drafts/{draft_id}/finalize` — recibe
  `{expected_version, finalized_by, finalization_notes}` y devuelve `200` con
  `FinalizationResponse`. Una repetición con actor, notas, snapshot y versión
  coincidentes devuelve el resultado existente; no requiere `Idempotency-Key`.

- `GET /api/v1/drafts/{draft_id}/preview?draft_version={n}` — devuelve HTML sanitizado
  solo para una versión `APPROVED`, con `Content-Type: text/html; charset=utf-8`,
  `ETag` SHA-256 y `Cache-Control: no-store`; no persiste, exporta ni cambia
  estado.
- `POST /api/v1/drafts/{draft_id}/exports` — solicita `{draft_version, format,
  exported_by}` con `Idempotency-Key` y devuelve `202` con
  `DocumentExportResponse` con export `GENERATING` y attempt `PROCESSING`; una
  repetición exitosa del mismo payload devuelve `200`, una repetición mientras
  sigue activo devuelve `EXPORT_IN_PROGRESS` (409), y si el export ya está
  `FAILED` devuelve sus metadatos sin crear otro attempt.
- `GET /api/v1/drafts/{draft_id}/exports` — lista exportaciones por `draft_version` y `export_version`,
  formato y estado, con filtros `draft_version`, `export_version`, `format`, `status`, `page`,
  `page_size` y `order`.
- `GET /api/v1/exports/{export_id}` — obtiene metadatos y errores seguros.
- `GET /api/v1/exports/{export_id}/download` — descarga el binario con
  `Content-Type`, `Content-Disposition: attachment`, `ETag` SHA-256 y
  `Cache-Control: private, no-store`; valida path y hash antes del streaming.
- `POST /api/v1/exports/{export_id}/retry` — reintenta exclusivamente estados
  `FAILED`, recibe `{exported_by}`, exige la misma `Idempotency-Key`, devuelve
  `202` con export `GENERATING` y attempt `PROCESSING`, crea un nuevo `export_attempt` con el mismo key/hash y no crea otro `document_export`.
- `POST /api/v1/exports/{export_id}/regenerate` — crea una nueva exportación
  versionada desde `final_snapshot`, sin depender del archivo origen; recibe
  `{expected_version, exported_by}`, exige `Idempotency-Key` y devuelve `202` o
  `200` de forma idempotente.
- `GET /api/v1/exports/{export_id}/attempts` — devuelve los intentos paginados
  con filtros `status`, `page`, `page_size` y `order`. Solo expone códigos y
  mensajes sanitizados; nunca expone `storage_path`, paths internos ni errores
  de librerías.

## Escenarios de aceptación

### Revisión

| ID | Escenario | Resultado esperado |
|---|---|---|
| RV-01 | Abrir revisión de una versión editable/en revisión | 201, revisión `OPEN`, versión fijada |
| RV-02 | Recuperar revisión existente | 200, misma revisión, sin duplicado |
| RV-03 | Crear comentario anclado válido | 201, ancla validada y evento registrado |
| RV-04 | Ancla de otra versión | 422 `ANCHOR_VERSION_MISMATCH` |
| RV-05 | Resolver comentario bloqueante | 200, evento append-only, contenido original intacto |
| RV-06 | Cerrar con bloqueo abierto | 409 `OPEN_BLOCKING_COMMENTS` |
| RV-07 | Aprobar sin confirmación humana | 422 `HUMAN_REVIEW_REQUIRED` |
| RV-08 | Solicitar cambios sin motivo | 422 `MISSING_REVIEW_REASON` |
| RV-09 | Editar con versión obsoleta | 409 `CONCURRENT_MODIFICATION` |
| RV-10 | Consultar historial | 200, eventos ordenados y sin secretos |

### Exportación

| ID | Escenario | Resultado esperado |
|---|---|---|
| EX-01 | Previsualizar versión aprobada | 200 HTML sanitizado, sin llamada a Ollama |
| EX-02 | Previsualizar HTML | 200, HTML sanitizado no persistido |
| EX-03 | Exportar a DOCX | 202, `Content-Type` correcto y texto equivalente |
| EX-04 | Exportar a PDF | 202, `Content-Type` correcto y texto equivalente |
| EX-05 | Exportar versión `EN_REVISION` | 409 `DRAFT_NOT_APPROVED`, sin archivo |
| EX-06 | Exportar con bloqueo abierto | 409 `OPEN_BLOCKING_COMMENTS`, sin archivo |
| EX-07 | Formato desconocido | 422 `EXPORT_FORMAT_UNSUPPORTED` |
| EX-08 | Repetir misma idempotency key | Mismo artefacto, sin duplicar registro |
| EX-09 | Renderer falla después de `202` | La respuesta inicial ya aceptó la operación; export y attempt quedan `FAILED`, con error sanitizado consultable por metadata/attempts y retry posible |
| EX-10 | Descargar exportación inexistente | 404 `EXPORT_NOT_FOUND` |
| EX-11 | Contenido editable supera el límite efectivo | 422 `CONTENT_TOO_LARGE`; la edición heredada de 003 conserva 100 KiB (102.400 bytes) aunque el techo de 004 sea 2 MiB (2.097.152 bytes) |
| EX-12 | Cambiar la versión después de exportar | Artefacto anterior inmutable y asociado a su versión |
| EX-13 | Regenerar `GENERATED` o `SUPERSEDED` | 202, nuevo export y attempt desde `final_snapshot`; `parent_export_id` correcto |
| EX-14 | Regenerar con archivo origen faltante o corrupto | 202, usa `final_snapshot`; el artefacto anterior conserva estado y descarga |
| EX-15 | Listar attempts de una exportación | 200, paginado, orden estable y sin paths ni errores internos |
| EX-16 | Respuesta JSON de error | Envelope público de 003 con `code`, `message`, `details`, `request_id` y `timestamp` sanitizados/validados |

## Requisitos no funcionales

### Seguridad y privacidad

- Los documentos, comentarios y artefactos permanecen en infraestructura propia.
- No se enviará contenido a proveedores externos ni a Ollama durante la
  exportación.
- Logs y métricas usarán IDs, tamaños, hashes y códigos; no texto jurídico
  completo, DNI, CUIL, tokens ni binarios.
- El almacenamiento debe aplicar permisos mínimos, volumen privado y políticas
  de retención configurables.
- HTML debe sanitizar atributos y URLs para prevenir XSS al previsualizar.

- El storage debe rechazar paths absolutos, `..`, escapes del root canónico y
  symlinks en cualquier segmento; los nombres deben usar UUIDs/versión y no
  PII. Directorios `0700`, archivos `0600`, temporales aleatorios y rename
  atómico son los valores normativos cuando el sistema los soporta.

### Rendimiento y límites

- Los benchmarks de A8 son informativos y no bloquean la suite local ni el CI
  estándar. Usan el dataset sintético versionado `004-benchmark-v1`, sin PII:
  100 drafts/reviews y 1.000 comentarios para revisión; un snapshot final
  canónico de exactamente 100 KiB para preview y aceptación; un DOCX válido y
  un PDF válido de exactamente 1 MiB (1.048.576 bytes) para descarga; y 1.000 registros de
  exportación con 1.000 entradas de filesystem, incluyendo 100 incidencias
  deterministas, para reconcile dry-run.
- Cada benchmark ejecuta 10 iteraciones de warm-up y 50 iteraciones medidas,
  secuenciales, con `time.perf_counter()`. El p95 es el rango más cercano
  `ceil(0.95 * N)` sobre milisegundos, e incluye la operación indicada hasta
  el punto de medición documentado. El entorno de referencia es Linux
  `linux/amd64` dentro de Docker Compose, Python 3.12, PostgreSQL 16, 4 vCPU,
  8 GiB RAM, filesystem local SSD, sin Ollama ni red externa; el resultado
  registra commit, lockfile, dataset y entorno real.
- El comando reproducible es:
  `cd apps/api && uv run python scripts/benchmark_004.py --dataset tests/fixtures/benchmark_004_dataset.json --warmup 10 --iterations 50 --output artifacts/benchmarks/004.json`.
- Los umbrales informativos son: lectura de revisión
  `GET /api/v1/drafts/{draft_id}/reviews/current` menor a 300 ms; preview HTML
  de 100 KiB menor a 2.000 ms; aceptación
  `POST /api/v1/drafts/{draft_id}/exports` hasta recibir `202` menor a 500 ms;
  descarga de 1 MiB (1.048.576 bytes) mediante
  `GET /api/v1/exports/{export_id}/download`, incluyendo validación y consumo
  del body, menor a 1.500 ms; y
  `document-exports reconcile` dry-run sobre el dataset completo menor a
  3.000 ms. La aceptación `202` usa un scheduler/renderer fake que termina
  después de la respuesta: no mide generación DOCX/PDF.
- El runner escribe JSON con muestras, p95, umbral, baseline opcional indicado
  por `--baseline`, dataset, entorno, timestamp, commit y `regression_alert`.
  Una superación del umbral o un p95 superior en 10% al baseline suministrado
  emite una alerta estructurada y no falla por sí sola el comando; errores de
  infraestructura o medición sí producen error del runner. Los resultados no
  se ejecutan en la suite unitaria ordinaria ni en el CI estándar. Un gate de
  release requiere una decisión posterior.
- Las solicitudes concurrentes sobre la misma versión no deben producir más de
  un artefacto por clave idempotente.

### Disponibilidad y resiliencia

- Un error de renderer no debe cambiar el estado del borrador ni de la revisión.
- Los artefactos parciales deben eliminarse o marcarse no descargables.
- Un timeout debe terminar el proceso hijo, ejecutar `join`, evitar zombis y
  eliminar el temporal sin publicar el artefacto vencido.
- Las operaciones de descarga deben poder reintentarse sin regenerar el archivo.
- Deben existir health/readiness checks para el almacenamiento y los renderers.

### Observabilidad

- Métricas: revisiones abiertas/cerradas, comentarios por severidad, tiempo de
  revisión, exportaciones por formato/estado, latencia, tamaño y fallos.
- Logs estructurados con request ID, export ID, draft ID, versión y código de
  error, sujetos a minimización.
- Cada exportación debe poder correlacionarse con su evento de aprobación.

- El renderer de PDF debe ejecutarse en Linux/contenedor en modo headless, sin
  acceso de red durante el renderizado y detrás de un puerto reemplazable.

La observabilidad debe registrar las fases Tx1, generación, validación, rename,
Tx2, compensación y reconciliación mediante IDs, estados y códigos
sanitizados; nunca mediante contenido jurídico o rutas absolutas.

## Compatibilidad con la constitución

- **Principio I**: datos locales, sanitización, límites y ausencia de secretos.
- **Principio II**: aprobación y exportación solo después de revisión humana.
- **Principio III**: eventos append-only y hash de snapshot/artefacto.
- **Principio V**: separación entre contenido aprobado y renderizadores.
- **Principio X**: puertos de almacenamiento y renderizado reemplazables.
- **Principios XV–XVII**: tipado, pruebas contractuales, health checks y errores
  diferenciados.
- **Principio XVIII**: versión de draft, renderer, formato y hash registrados.
- **Principios XIX–XX**: incremento acotado, sin firma, publicación ni servicios
  innecesarios.

## Criterios de aceptación del incremento

### Código y contrato

- [ ] Existen schemas versionados para revisión, comentarios, exportación,
      errores y eventos.
- [ ] Las transiciones inválidas y la concurrencia devuelven errores
      estructurados.
- [ ] HTML de preview, DOCX y PDF usan la misma representación canónica y
      preservan el texto aprobado; solo DOCX y PDF se persisten.
- [ ] No se altera el contrato de 003 para generación, regeneración o drafts.

### Seguridad y privacidad

- [ ] No se registran documentos completos, binarios ni secretos.
- [ ] Se bloquea exportación no aprobada o con comentarios bloqueantes.
- [ ] La previsualización HTML está sanitizada y no ejecuta contenido activo.
- [ ] El almacenamiento tiene permisos mínimos y no expone un volumen público.

### Pruebas

- [ ] Pruebas unitarias para máquina de estados, anclajes, sanitización, hashes
      e idempotencia.
- [ ] Pruebas contractuales para todos los endpoints y formatos.
- [ ] Pruebas de integración para persistencia, volumen local y renderizadores.
- [ ] Prueba de migración hacia adelante y rollback documentado.
- [ ] Smoke test Docker que abra una revisión, previsualice HTML mediante
      `GET /api/v1/drafts/{draft_id}/preview?draft_version={n}` y cree y
      descargue exportaciones DOCX y PDF; HTML no es descargable.
- [ ] Cobertura del incremento igual o superior al umbral vigente del proyecto.

### Operación

- [ ] `docker compose config --quiet` y build pasan.
- [ ] Alembic alcanza una revisión 004 identificable como head.
- [ ] Health/readiness reportan almacenamiento y renderizadores.
- [ ] Quickstart documenta previsualización, exportación y recuperación de
      artefactos fallidos.

## Supuestos

- La autorización por rol (editor, revisor, auditor) se implementará en un
  incremento posterior; 004 solo persiste actores textuales validados de
  1–100 caracteres: `finalized_by`, `exported_by` y los campos heredados reales
  de actor de los eventos de revisión. No tienen FK, unicidad ni semántica de
  autenticación/autorización, no aparecen en paths o `file_name`, y
  `request_id` permanece como trazabilidad técnica.
- PostgreSQL continúa siendo la fuente de verdad para estados, comentarios,
  eventos y metadatos.
- El volumen local es suficiente para el MVP y su retención se configura por
  entorno.
- El pipeline de 003 entrega un snapshot de texto estructurado y estable; 004
  no vuelve a llamar al modelo para corregirlo ni maquetarlo.
- La disponibilidad de dependencias nativas para DOCX/PDF se verifica en el
  plan técnico antes de fijar bibliotecas concretas.

## Fuera de alcance

- Autenticación, autorización y gestión de identidades.
- Frontend completo o editor WYSIWYG; se define únicamente el contrato backend.
- OCR, RAG, embeddings, búsqueda semántica o nuevas llamadas a Ollama.
- Firma digital, sellado de tiempo cualificado o publicación oficial.
- Envío por correo, expediente externo, impresora o portal ciudadano.
- Conversión masiva, programación de lotes o colas distribuidas.
- Edición del binario exportado; cualquier cambio requiere una nueva versión del
  borrador y una nueva revisión.
- Almacenamiento público, CDN, Kubernetes, Terraform y Helm específicos para
  exportaciones.

## Dependencias

- Incremento 002: empleados, expedientes, request IDs y persistencia base.
- Incremento 003: drafts, estados, snapshots, transición histórica y errores.
- PostgreSQL/Alembic para nuevas tablas e índices.
- Volumen privado administrado por Docker para el adaptador de almacenamiento
  local.
- Bibliotecas o procesos de renderizado DOCX/PDF que deberán quedar detrás de
  interfaces y validarse por seguridad.

El plan técnico debe elegir únicamente los renderers concretos detrás de los
puertos: DOCX desde la representación canónica y PDF desde el HTML canónico
en modo headless. La conversión DOCX→PDF y la dependencia obligatoria de
LibreOffice quedan fuera del pipeline funcional decidido.

## Notas para plan técnico posterior

El plan debe decidir, con evidencia reproducible, las bibliotecas de DOCX/PDF,
la estrategia de almacenamiento y si la exportación se ejecutará de forma
síncrona o mediante una cola local. Cualquier dependencia que introduzca
ejecución de HTML, acceso a red o binarios del sistema debe someterse a revisión
de seguridad y documentarse en un ADR. La implementación debe comenzar por el
modelo de revisión y la representación canónica, validar los gates de
exportabilidad y recién después añadir cada renderer.
