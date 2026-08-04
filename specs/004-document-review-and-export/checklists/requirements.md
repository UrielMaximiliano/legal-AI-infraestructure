# Checklist de Requisitos — 004-document-review-and-export

**Propósito**: validar que la revisión humana y la exportación de documentos
queden especificadas de forma completa, medible, auditable y compatible con
003. Este checklist valida requisitos; no implica que la implementación esté
realizada.

**Especificación**: [../spec.md](../spec.md)
**Estado de la matriz**: sus filas detalladas conservan el estado de
implementación/verificación. El checklist GitHub superior mide la calidad y
completitud de la especificación.

**Decisión integrada — finalización**: el draft conserva `APPROVED`; la
finalización exige `expected_version`, incrementa `document_drafts.version`
(expuesto como `draft_version` en los contratos) y registra `finalized_by`,
`finalized_at`, `finalization_notes` y un snapshot final inmutable. Esta nota
describe especificación, no implementación.

**Decisión integrada — estados de exportación**: el contrato usa `PENDING`,
`GENERATING`, `GENERATED`, `FAILED` y `SUPERSEDED`; los reintentos de `FAILED`
se auditan en `export_attempts`, y `GENERATED`/`SUPERSEDED` son descargables.
Esta nota describe especificación, no implementación.

**Decisión integrada — HTML**: HTML es preview y representación intermedia no
persistida; `DocumentExport` solo admite DOCX y PDF.

**Decisión integrada — pipeline PDF**: PDF se renderiza desde el HTML canónico
mediante un renderer headless reemplazable en Linux/contenedor; no se define
conversión DOCX→PDF ni biblioteca concreta en esta fase.

**Decisión integrada — idempotencia**: `Idempotency-Key` obligatorio de 16–100
caracteres seguros, ventana de 24 horas y `request_hash`; payload distinto,
intento activo y fallo reintentable tienen respuestas diferenciadas.

**Decisión integrada — modelo de datos y migración 004**: `document_drafts` se
extiende con metadatos y snapshot de finalización; `document_exports` conserva
artefactos válidos versionados; `export_attempts` conserva todos los intentos.
El orden es drafts → exports → attempts y el downgrade es inverso.

**Decisión integrada — doble finalización**: la primera finalización fija un
snapshot write-once; una repetición idéntica es 200 idempotente, una divergente
es `DRAFT_ALREADY_FINALIZED` y una versión obsoleta es
`CONCURRENT_MODIFICATION`. El draft finalizado no admite mutaciones.

**Decisión integrada — reintentos de exportación**: cada retry crea una fila
nueva en `export_attempts`, conserva clave y hash, incrementa
`attempt_number` y permite solo un intento activo por actor y clave mediante
un índice único parcial.

**Decisión integrada — storage layout**: `storage_path` es relativo a
`EXPORT_STORAGE_ROOT`, usa UUIDs/versión, rechaza traversal y symlinks, aplica
`0700`/`0600` cuando sea posible y publica temporales mediante rename atómico.

**Decisión integrada — consistencia filesystem/DB**: Tx1 registra `PENDING`, la
transiciona en esa misma transacción a `GENERATING`/`PROCESSING` antes del
commit; la generación, validación y rename ocurren fuera de PostgreSQL. Tx2
confirma `GENERATED`/`SUCCEEDED`/`SUPERSEDED` o marca `FAILED`. No existe una
transacción intermedia para publicar estados activos. Si Tx2 no puede confirmar
tras el rename, no se abre una tercera transacción y la incidencia queda para
reconciliación manual; los fallos compensan el filesystem.

**Decisión integrada — idempotencia de revisión**: las seis mutaciones de
review exigen `Idempotency-Key`, `request_hash` canónico y una ventana de 24
horas con scope por operación, recurso principal y clave. Replay, conflicto y
operación activa usan, respectivamente, la respuesta previa,
`IDEMPOTENCY_CONFLICT` y `REVIEW_OPERATION_IN_PROGRESS`; `request_id` solo da
trazabilidad. La persistencia usa `review_operation_requests` cuando 003 no
ofrece ese scope.

**Decisión integrada — snapshot de revisión**: `document_reviews` persiste
`review_snapshot`, `review_snapshot_sha256` y `draft_version` como campos
obligatorios. El snapshot y su hash son canónicos e inmutables; comentarios,
anclas y transiciones se interpretan contra esa versión.

**Decisión integrada — nombres de versión**: `draft_version` identifica el
contenido revisado y solicitado; `export_version` es el contador independiente
por `(draft_id, format)` y se usa en filtros, nombres, rutas y regeneración.

**Decisión integrada — preview**: `GET /api/v1/drafts/{draft_id}/preview?draft_version={n}`
solo acepta drafts `APPROVED`; usa el contenido aprobado solicitado antes de
finalizar y exclusivamente `final_snapshot` después. Los drafts finalizados
siguen siendo previsualizables. Responde HTML con `ETag` SHA-256 y
`Cache-Control: no-store`, sin persistencia, exportación, cambio de estado ni
incremento de versión.

**Decisión integrada — descarga**: `GET /api/v1/exports/{export_id}/download`
solo admite `GENERATED` y `SUPERSEDED`, transmite el binario como attachment,
usa `ETag` SHA-256 y `Cache-Control: private, no-store`, y no implementa Range
requests en 004. Valida ruta canónica y hash antes de iniciar; no expone
`storage_path` y diferencia `EXPORT_FILE_NOT_FOUND` de
`EXPORT_FILE_CORRUPTED`.

**Decisión integrada — integridad**: SHA-256 se calcula al crear y se recalcula
antes de cada descarga. DOCX exige MIME, ZIP válido, entradas estructurales
requeridas y límites de 500 entradas, 50 MiB (52.428.800 bytes) descomprimidos
y ratio 100:1; PDF
exige MIME, `%PDF-` y `%%EOF` en el tramo final. La corrupción bloquea la
descarga, registra evento y devuelve `EXPORT_FILE_CORRUPTED`, sin marcar
automáticamente `GENERATED` como `FAILED`; requiere regeneración explícita.

**Decisión integrada — DOCX institucional**: el documento es A4 vertical con
márgenes 2,5/2,5/3/2 cm, Arial 11 para cuerpo, título Arial 12 negrita
centrado, justificado, interlineado 1,5 y 6 pt posteriores. Incluye encabezado,
secciones administrativas, artículos numerados y firmas configurables; no tiene
pie salvo número de página. Usa locale `es-AR`, minimiza metadatos personales y
falla validación si faltan datos obligatorios.

**Decisión integrada — límites y nombres**: se fija un techo de 2 MiB
(2.097.152 bytes) para
contenido nuevo de 004 y para `final_snapshot`, pero los endpoints de edición
heredados de 003 conservan su límite efectivo más estricto de 100 KiB y
`CONTENT_TOO_LARGE`; 004 eleva el límite efectivo de runtime sin modificar los
artefactos documentales de 003. También se fijan 5 MiB (5.242.880 bytes) para
preview, 20 MiB (20.971.520 bytes) para DOCX y 30 MiB (31.457.280 bytes) para
PDF; las validaciones usan bytes y prueban límite exacto, límite + 1 byte y
contenido multibyte; timeouts de 30/60 s; límites para
nombre, ruta, notas, actor y paginación; y una sola generación activa por
`draft_id + format`. El nombre es
`{draft_id}_v{export_version}.{extension}`, en minúsculas, sin espacios, doble
extensión, PII, `case_number`, personas, `document_type` ni fechas.

**Decisión integrada — retención y cleanup**: `GENERATED`/`SUPERSEDED` y los
metadatos fallidos de `document_exports` se conservan indefinidamente;
`export_attempts` fallidos se retienen al menos 180 días. Temporales y
huérfanos solo son elegibles para cleanup manual después de 24 horas y 7 días
desde detección, respectivamente. `document-exports reconcile` es dry-run por
defecto, requiere `--execute` para borrar, devuelve resumen JSON con `run_id` y
audita cada acción; no existe DELETE público ni cleanup automático.

**Decisión integrada — identidad textual**: `finalized_by` y `exported_by` son
actores textuales obligatorios, con trim y longitud de 1–100 caracteres, sin
vacíos ni solo espacios. Se permiten letras Unicode, números, espacios, punto,
guion, guion bajo y `@`; se conserva el casing, no se exige unicidad ni se usan
para autenticación/autorización y no tienen FK. Llegan en el body de sus
operaciones, nunca en paths o `file_name`, y los valores inválidos devuelven
`VALIDATION_ERROR`; los eventos de revisión conservan sus campos contractuales
reales sin introducir otra identidad; `request_id` queda
solo para trazabilidad.

**Decisión integrada — regeneración**: `POST /api/v1/exports/{export_id}/regenerate`
acepta `GENERATED`/`SUPERSEDED`, exige `expected_version`, `exported_by` e
`Idempotency-Key`, y crea un nuevo `document_export`/`export_attempt` desde
`final_snapshot`, con `parent_export_id`, nueva versión, hash y ruta. Responde
`202` inicialmente o `200` de forma idempotente. El export vigente solo pasa a
`SUPERSEDED` tras éxito; un fallo conserva el anterior. `FAILED` usa `/retry`
con la misma clave y nuevo intento, sin crear otro export.

**Decisión integrada — catálogo HTTP y errores**: todas las respuestas JSON
incluyen `request_id`; los errores reutilizan exactamente el envelope público
de 003 con `timestamp` obligatorio generado por el servidor en UTC, RFC 3339 y
sufijo `Z`; creación, retry y regeneración exigen `Idempotency-Key`;
finalización, mutaciones de revisión y regeneración exigen `expected_version`;
las listas son paginadas con `page_size` máximo 100 y orden estable. Se incluye
`GET /api/v1/exports/{export_id}/attempts`. El envelope de error usa `code`,
`message`, `details`, `request_id` y `timestamp`, siempre sanitizados; no expone
`storage_path`, paths internos, stack traces, secretos ni contenido documental.

**Decisión integrada — benchmarks A8**: son métricas informativas no
bloqueantes con dataset `004-benchmark-v1`, 10 warm-up, 50 iteraciones,
entorno Linux/Docker de referencia, p95 y umbrales explícitos para revisión,
preview, aceptación `202`, descarga y reconcile dry-run. Se ejecutan mediante
un comando separado de pytest/CI estándar, registran JSON y alertan
regresiones; la aceptación `202` no mide generación completa DOCX/PDF.

**Decisión integrada — aislamiento de renderer A9**: DOCX y PDF se ejecutan en
procesos hijos aislados y terminables, uno por operación, con contexto `spawn`.
Al vencer 30 s/60 s se aplica terminación, gracia breve, `kill` si es necesario,
`join`, cleanup y `GENERATION_TIMEOUT`; no se reutiliza el hijo, no se dejan
zombis ni se publican artefactos vencidos.

## Checklist de calidad de la especificación

- [x] La finalización conserva `APPROVED` y fija un snapshot write-once.
- [x] Los estados de exportación y sus transiciones están definidos.
- [x] HTML es preview/intermedio no persistido; DOCX y PDF son persistidos.
- [x] El pipeline PDF usa HTML canónico y renderer headless reemplazable.
- [x] La idempotencia define clave, hash, ventana y conflictos.
- [x] El modelo separa `document_exports` de `export_attempts`.
- [x] La migración 004 y su downgrade tienen orden explícito.
- [x] La doble finalización y la mutabilidad posterior están definidas.
- [x] Los retries crean nuevos `export_attempts` auditables.
- [x] El storage layout y sus controles contra traversal/symlinks están definidos.
- [x] La compensación filesystem/PostgreSQL y la reconciliación manual están definidas.
- [x] El contrato exacto de preview está completamente definido.
- [x] El contrato exacto de descarga y Range requests está definido.
- [x] Hash, MIME, corrupción y zip bombs tienen tratamiento completo.
- [x] Los requisitos institucionales de DOCX están cuantificados.
- [x] Límites, timeouts y tamaños máximos están cerrados.
- [x] Los benchmarks de rendimiento informativos son reproducibles y tienen umbrales explícitos.
- [x] Retención y cleanup están cerrados.
- [x] Identidad textual de `finalized_by` y `exported_by` está cerrada.
- [x] Regeneración de exportaciones está completamente definida.
- [x] El catálogo HTTP y todos los endpoints tienen mapeo final.

No quedan casillas pendientes en este checklist de decisiones.

### Clarificaciones resueltas de esta sesión

- [x] A9: aislamiento/cancelación efectiva al agotar un timeout de renderer.
- [x] A10: status `416`, código `RANGE_NOT_SUPPORTED`, envelope, `request_id`, `timestamp`,
  `Accept-Ranges: none` y rechazo previo al acceso del archivo para Range.

### Matriz detallada de requisitos

| ID | Criterio | Estado | Observaciones |
|----|----------|--------|---------------|
| Q-01 | Cada requisito tiene identificador único y resultado verificable | ☐ Pendiente | |
| Q-02 | La unidad revisable está fijada a `draft_id` + `draft_version` | ☐ Pendiente | |
| Q-03 | La exportación exige aprobación humana y ausencia de bloqueos | ☐ Pendiente | |
| Q-04 | El contrato distingue estado actual, historial y artefacto inmutable | ☐ Pendiente | |
| Q-05 | Los límites, errores, concurrencia e idempotencia están definidos | ☐ Pendiente | Incluye finalización, estados de exportación, pipeline PDF e idempotencia |
| Q-06 | El alcance no introduce autenticación, RAG, firma ni publicación | ☐ Pendiente | |
| Q-07 | Los benchmarks informativos tienen dataset, protocolo, p95, umbral y comando reproducibles | ☐ Pendiente | No bloquean CI ni la ejecución local estándar |

## Requisitos funcionales — revisión

| ID | Requisito | Estado | Observaciones |
|----|-----------|--------|---------------|
| RF-01.1 | Crear o recuperar una revisión por borrador y versión | ☐ Pendiente | `draft_id` + `draft_version` |
| RF-01.2 | Mantener estados OPEN, SUBMITTED, CHANGES_REQUESTED, APPROVED y CLOSED | ☐ Pendiente | Máquina de estados explícita |
| RF-01.3 | Impedir transiciones inválidas | ☐ Pendiente | Error estructurado 409 |
| RF-01.4 | Invalidar exportabilidad al crear una nueva versión del borrador | ☐ Pendiente | Historial anterior intacto |
| RF-02.1 | Crear comentario general | ☐ Pendiente | |
| RF-02.2 | Crear comentario anclado a sección o rango | ☐ Pendiente | Ancla validada contra snapshot |
| RF-02.3 | Guardar autor, timestamp, severidad y cuerpo | ☐ Pendiente | |
| RF-02.4 | Validar severidad INFO, SUGGESTION, WARNING o BLOCKING | ☐ Pendiente | |
| RF-02.5 | Limitar comentario/respuesta a 10.000 caracteres | ☐ Pendiente | `CONTENT_TOO_LARGE` |
| RF-02.6 | Crear respuestas enlazadas sin reescribir el comentario original | ☐ Pendiente | `parent_comment_id` |
| RF-03.1 | Marcar comentario como OPEN, RESOLVED o DISMISSED | ☐ Pendiente | Evento append-only |
| RF-03.2 | Impedir borrado físico de comentario o respuesta | ☐ Pendiente | Auditoría |
| RF-03.3 | Impedir cierre con comentarios BLOCKING abiertos | ☐ Pendiente | `OPEN_BLOCKING_COMMENTS` |
| RF-03.4 | Enviar revisión a decisión | ☐ Pendiente | Estado SUBMITTED |
| RF-03.5 | Aprobar con confirmación explícita de revisión humana | ☐ Pendiente | `HUMAN_REVIEW_REQUIRED` |
| RF-03.6 | Solicitar cambios con motivo obligatorio | ☐ Pendiente | Reapertura sobre nueva versión |

## Requisitos funcionales — auditoría y concurrencia

| ID | Requisito | Estado | Observaciones |
|----|-----------|--------|---------------|
| RF-04.1 | Aplicar optimistic locking con `expected_version` o `If-Match` | ☐ Pendiente | |
| RF-04.2 | Devolver `CONCURRENT_MODIFICATION` ante versión obsoleta | ☐ Pendiente | HTTP 409 |
| RF-04.3 | Registrar eventos para comentarios, transiciones y decisiones | ☐ Pendiente | Append-only |
| RF-04.4 | Incluir actor, recurso, versión, timestamp UTC y request ID | ☐ Pendiente | Minimización |
| RF-04.5 | Consultar historial ordenado sin modificar registros | ☐ Pendiente | |
| RF-04.6 | Aplicar idempotencia a las seis mutaciones de review | ☐ Pendiente | `Idempotency-Key`, `request_hash`, ventana 24 h, replay/conflicto/active |
| RF-04.7 | No registrar texto jurídico completo, secretos ni binarios en logs | ☐ Pendiente | Seguridad |

## Requisitos funcionales — previsualización y exportación

| ID | Requisito | Estado | Observaciones |
|----|-----------|--------|---------------|
| RF-05.1 | Renderizar previsualización HTML del snapshot exacto | ☐ Pendiente | Sin Ollama |
| RF-05.2 | Sanitizar HTML y bloquear scripts, iframes y referencias remotas | ☐ Pendiente | Prevención XSS |
| RF-05.3 | Verificar aprobación y revisión cerrada en backend | ☐ Pendiente | Cada solicitud |
| RF-05.4 | Bloquear comentarios BLOCKING abiertos | ☐ Pendiente | |
| RF-05.5 | Previsualizar HTML no persistido | ☐ Pendiente | Preview sanitizado y representación intermedia |
| RF-05.6 | Exportar DOCX | ☐ Pendiente | Adaptador reemplazable |
| RF-05.7 | Exportar PDF | ☐ Pendiente | Adaptador reemplazable |
| RF-05.8 | Rechazar formato desconocido | ☐ Pendiente | `EXPORT_FORMAT_UNSUPPORTED` |
| RF-05.9 | Derivar DOCX/PDF de la misma representación canónica | ☐ Pendiente | Texto equivalente |
| RF-05.10 | Guardar hash SHA-256 de fuente y artefacto | ☐ Pendiente | Reproducibilidad |
| RF-05.11 | Guardar versión de renderer y formato | ☐ Pendiente | |
| RF-05.12 | Mantener artefactos completados inmutables | ☐ Pendiente | |
| RF-05.13 | Reintentar únicamente exportaciones FAILED | ☐ Pendiente | Sin cambiar borrador |
| RF-05.14 | Aplicar idempotencia por actor y solicitud | ☐ Pendiente | 16–100 chars, 24 h, request_hash y reintento FAILED |
| RF-05.15 | Descargar binario con Content-Type y Content-Disposition correctos | ☐ Pendiente | Hash verificable |
| RF-05.16 | No invocar Ollama, embeddings ni RAG durante exportación | ☐ Pendiente | Aislamiento |

## Límites y reglas de negocio

| ID | Regla | Estado | Observaciones |
|----|-------|--------|---------------|
| RN-01 | Contenido nuevo de 004 máximo 2 MiB (2.097.152 bytes); edición heredada de 003 efectiva a 100 KiB | ☐ Pendiente | `CONTENT_TOO_LARGE`; 004 eleva runtime sin modificar 003; probar exacto/+1/multibyte |
| RN-02 | DOCX máximo 20 MiB (20.971.520 bytes) y PDF máximo 30 MiB (31.457.280 bytes) | ☐ Pendiente | `EXPORT_SIZE_EXCEEDED`; validación por bytes |
| RN-03 | Un ancla pertenece a una única `draft_version` | ☐ Pendiente | `ANCHOR_VERSION_MISMATCH` |
| RN-04 | Una exportación GENERATED no vuelve a GENERATING | ☐ Pendiente | FAILED reintentable; GENERATED pasa a SUPERSEDED solo tras éxito |
| RN-05 | Error de renderer no cambia draft ni review | ☐ Pendiente | Estado FAILED |
| RN-06 | Artefactos parciales no son descargables | ☐ Pendiente | Limpieza o marcado seguro |
| RN-07 | Exportar no modifica el estado jurídico del documento | ☐ Pendiente | No es publicación |

## Endpoints

| Método | Ruta | Estado | Observaciones |
|--------|------|--------|---------------|
| GET | `/api/v1/drafts/{draft_id}/reviews/current` | ☐ Pendiente | Revisión y snapshot |
| POST | `/api/v1/drafts/{draft_id}/reviews` | ☐ Pendiente | Abrir revisión |
| POST | `/api/v1/reviews/{review_id}/comments` | ☐ Pendiente | Comentario/respuesta |
| PATCH | `/api/v1/reviews/{review_id}/comments/{comment_id}` | ☐ Pendiente | Estado + optimistic locking |
| POST | `/api/v1/reviews/{review_id}/submit` | ☐ Pendiente | Enviar a decisión |
| POST | `/api/v1/reviews/{review_id}/approve` | ☐ Pendiente | Confirmación humana |
| POST | `/api/v1/reviews/{review_id}/request-changes` | ☐ Pendiente | Motivo obligatorio |
| GET | `/api/v1/reviews/{review_id}/history` | ☐ Pendiente | Eventos ordenados |
| GET | `/api/v1/drafts/{draft_id}/preview?draft_version={n}` | ☐ Pendiente | HTML sanitizado, `request_id` va en header |
| POST | `/api/v1/drafts/{draft_id}/finalize` | ☐ Pendiente | `expected_version`, `finalized_by`, snapshot final |
| POST | `/api/v1/drafts/{draft_id}/exports` | ☐ Pendiente | `exported_by` + `Idempotency-Key`, 202 |
| GET | `/api/v1/drafts/{draft_id}/exports` | ☐ Pendiente | Filtros, page/page_size/order |
| GET | `/api/v1/exports/{export_id}` | ☐ Pendiente | Metadatos sin `storage_path` |
| GET | `/api/v1/exports/{export_id}/download` | ☐ Pendiente | Streaming, hash, sin Range |
| POST | `/api/v1/exports/{export_id}/retry` | ☐ Pendiente | `FAILED`, misma clave, nuevo attempt |
| POST | `/api/v1/exports/{export_id}/regenerate` | ☐ Pendiente | `expected_version`, desde `final_snapshot` |
| GET | `/api/v1/exports/{export_id}/attempts` | ☐ Pendiente | Auditoría paginada, sin error interno |

## Modelos de dominio y persistencia

| Modelo/tabla | Estado | Observaciones |
|--------------|--------|---------------|
| DocumentReview | ☐ Pendiente | draft_id, draft_version, review_snapshot, snapshot hash, status, version |
| ReviewOperationRequest | ☐ Pendiente | operación/recurso/key/hash, replay sanitizado, estado y expiración |
| DocumentDraft (finalización) | ☐ Pendiente | finalized_by, finalized_at, finalization_notes, final_snapshot, hash |
| ReviewComment | ☐ Pendiente | ancla, severidad, estado, parent |
| ReviewEvent | ☐ Pendiente | Append-only, request ID |
| DocumentExport | ☐ Pendiente | formato DOCX/PDF, estado, draft_version/export_version, hashes, renderer, storage_path relativo |
| ExportAttempt | ☐ Pendiente | Idempotency-Key, request_hash, attempt_number, estado, resultado y error sanitizado |
| ExportStatus | ☐ Pendiente | PENDING, GENERATING, GENERATED, FAILED, SUPERSEDED |
| ReviewStatus | ☐ Pendiente | OPEN, SUBMITTED, CHANGES_REQUESTED, APPROVED, CLOSED |
| CommentSeverity | ☐ Pendiente | INFO, SUGGESTION, WARNING, BLOCKING |
| CommentStatus | ☐ Pendiente | OPEN, RESOLVED, DISMISSED |
| Migración Alembic 004 | ☐ Pendiente | Tablas, índices, constraints y rollback |

## Schemas y puertos

| Componente | Estado | Observaciones |
|------------|--------|---------------|
| ReviewResponse | ☐ Pendiente | Estado, versión y snapshot |
| CreateReviewRequest | ☐ Pendiente | draft_version |
| CreateCommentRequest | ☐ Pendiente | body, severity, anchor |
| UpdateCommentStatusRequest | ☐ Pendiente | expected_version |
| ReviewDecisionRequest | ☐ Pendiente | confirmación o motivo |
| ExportRequest | ☐ Pendiente | draft_version, format, exported_by; `Idempotency-Key` en header |
| RegenerateExportRequest | ☐ Pendiente | expected_version, exported_by; `Idempotency-Key` en header |
| ExportResponse | ☐ Pendiente | estado, hash, renderer, errores |
| ReviewEventResponse | ☐ Pendiente | Evento minimizado |
| DocumentReviewRepository | ☐ Pendiente | Puerto de persistencia |
| ReviewCommentRepository | ☐ Pendiente | Puerto de persistencia |
| ReviewEventRepository | ☐ Pendiente | Solo append |
| DocumentExportRepository | ☐ Pendiente | Metadatos e idempotencia |
| DocumentRenderer | ☐ Pendiente | HTML/DOCX/PDF detrás de interfaz |
| ArtifactStorage | ☐ Pendiente | Volumen local privado |

## Errores estructurados

Todas las respuestas JSON incluyen `request_id`. El envelope uniforme es
`{"error":{"code":"...","message":"...","details":{},"request_id":"..."}}`;
`code` es estable y `message`/`details` se sanitizan sin paths internos, stack
traces, excepciones de librerías, secretos ni contenido documental. No se usa
HTTP 507.

| Código | HTTP | Estado | Observaciones |
|--------|------|--------|---------------|
| REVIEW_NOT_FOUND | 404 | ☐ Pendiente | |
| REVIEW_VERSION_MISMATCH | 409 | ☐ Pendiente | |
| INVALID_REVIEW_TRANSITION | 409 | ☐ Pendiente | |
| COMMENT_NOT_FOUND | 404 | ☐ Pendiente | |
| ANCHOR_VERSION_MISMATCH | 422 | ☐ Pendiente | |
| OPEN_BLOCKING_COMMENTS | 409 | ☐ Pendiente | |
| HUMAN_REVIEW_REQUIRED | 422 | ☐ Pendiente | |
| MISSING_REVIEW_REASON | 422 | ☐ Pendiente | |
| DRAFT_NOT_FOUND | 404 | ☐ Pendiente | |
| INVALID_UUID | 422 | ☐ Pendiente | Validación de parámetros UUID |
| DRAFT_NOT_APPROVED | 409 | ☐ Pendiente | |
| DRAFT_NOT_FINALIZED | 409 | ☐ Pendiente | |
| DRAFT_ALREADY_FINALIZED | 409 | ☐ Pendiente | |
| INVALID_FINALIZATION | 422 | ☐ Pendiente | |
| EXPORT_FORMAT_UNSUPPORTED | 422 | ☐ Pendiente | |
| EXPORT_NOT_FOUND | 404 | ☐ Pendiente | |
| EXPORT_GENERATION_FAILED | 500 | ☐ Pendiente | Solo fallo síncrono previo a 202 |
| EXPORT_IN_PROGRESS | 409 | ☐ Pendiente | |
| REVIEW_OPERATION_IN_PROGRESS | 409 | ☐ Pendiente | Idempotencia de mutaciones de review |
| EXPORT_ALREADY_EXISTS | 409 | ☐ Pendiente | |
| EXPORT_FILE_NOT_FOUND | 410 | ☐ Pendiente | |
| EXPORT_FILE_CORRUPTED | 409 | ☐ Pendiente | |
| RANGE_NOT_SUPPORTED | 416 | ☐ Pendiente | Rechazo temprano, sin streaming, lectura completa ni `Content-Range` |
| EXPORT_STORAGE_UNAVAILABLE | 503 | ☐ Pendiente | |
| EXPORT_SIZE_EXCEEDED | 413 | ☐ Pendiente | |
| INVALID_EXPORT_TRANSITION | 409 | ☐ Pendiente | |
| PATH_VALIDATION_FAILED | 500 | ☐ Pendiente | Sin detalles internos |
| IDEMPOTENCY_KEY_REQUIRED | 400 | ☐ Pendiente | |
| IDEMPOTENCY_CONFLICT | 409 | ☐ Pendiente | |
| CONCURRENT_MODIFICATION | 409 | ☐ Pendiente | Reutilizar contrato vigente |
| VALIDATION_ERROR | 422 | ☐ Pendiente | |
| DATABASE_ERROR | 503 | ☐ Pendiente | |
| FILESYSTEM_ERROR | 500 | ☐ Pendiente | |
| GENERATION_TIMEOUT | 504 | ☐ Pendiente | |
| MIME_VALIDATION_FAILED | 422 / interno | ☐ Pendiente | Creación; en descarga se publica `EXPORT_FILE_CORRUPTED` |
| HASH_VALIDATION_FAILED | interno | ☐ Pendiente | En descarga se publica `EXPORT_FILE_CORRUPTED` |
| ACTIVE_GENERATION_EXISTS | 409 | ☐ Pendiente | |
| CLEANUP_CONFLICT | 409 | ☐ Pendiente | |
| CONTENT_TOO_LARGE | 422 | ☐ Pendiente | Reutilizar contrato vigente |

## Pruebas mínimas

| Tipo | Cantidad mínima | Estado | Observaciones |
|------|-----------------|--------|---------------|
| Unitarias de estados y reglas | 20+ | ☐ Pendiente | |
| Unitarias de sanitización y hashes | 10+ | ☐ Pendiente | |
| Contractuales de revisión | 15+ | ☐ Pendiente | |
| Contractuales de HTML/DOCX/PDF | 12+ | ☐ Pendiente | |
| Integración PostgreSQL/migración | 8+ | ☐ Pendiente | |
| Integración almacenamiento/renderers | 8+ | ☐ Pendiente | |
| Seguridad, límites y concurrencia | 10+ | ☐ Pendiente | |
| Smoke Docker y descarga | 1 | ☐ Pendiente | Preview HTML no persistido y descarga DOCX/PDF |
| **Total orientativo** | **84+** | ☐ Pendiente | Ajustar en plan técnico |

## Validación final

| Verificación | Estado | Observaciones |
|--------------|--------|---------------|
| `specify check` OK | ☒ Verificado | CLI disponible en el entorno |
| `git diff --check` OK | ☒ Verificado | Sin errores de whitespace |
| Constitución y principios preservados | ☒ Verificado | Sin cambios en archivos protegidos |
| Ruff check/format OK | ☐ Pendiente | Implementación |
| Mypy OK | ☐ Pendiente | Implementación |
| Cobertura dentro del umbral del proyecto | ☐ Pendiente | Implementación |
| Migración 004 aplicada y reversible | ☐ Pendiente | Implementación |
| Docker build/config OK | ☐ Pendiente | Implementación |
| Health/readiness de storage y renderers OK | ☐ Pendiente | Implementación |
| Smoke de revisión, preview HTML y descarga DOCX/PDF OK | ☐ Pendiente | Implementación |
| Working tree sin pérdidas de incrementos previos | ☒ Verificado | 001–003 sin cambios |
