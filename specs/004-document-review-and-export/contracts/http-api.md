# Contrato HTTP — 004-document-review-and-export

## Convenciones comunes

- Base path: `/api/v1`.
- `X-Request-ID` es opcional en la solicitud; el middleware lo valida/genera,
  lo devuelve en el header y lo incluye en todas las respuestas JSON nuevas.
- Las mutaciones de revisión reciben `expected_version` en el body. No se
  acepta `request_id` como identidad de actor o de idempotencia.
- Los actores son strings textuales validados de 1–100 caracteres. Finalización
  usa `finalized_by`; creación/retry/regeneración usan `exported_by`; revisión
  conserva sus nombres contractuales `opened_by`, `submitted_by`, `decided_by`,
  `author` o `actor`. No tienen FK ni unicidad, no representan autenticación o
  autorización y no aparecen en paths ni `file_name`. No existe un campo de
  identidad de actor alternativo.
- `Idempotency-Key` es obligatorio en las seis mutaciones de review y en la
  creación, retry y regeneración de exportaciones. Debe tener 16–100
  caracteres seguros (`A-Z`, `a-z`, dígitos, `.`, `_`, `-`, `~`); el scope es
  operación + recurso principal + clave y el `request_hash` es canónico.
  Dentro de 24 horas, mismo payload devuelve replay, payload distinto devuelve
  `IDEMPOTENCY_CONFLICT` y una operación de review `PROCESSING` devuelve
  `REVIEW_OPERATION_IN_PROGRESS`.

Para las seis mutaciones de review, el claim idempotente se persiste en
`review_operation_requests` antes de ejecutar el cambio. El replay devuelve
el mismo status/payload sanitizado (`201` para create/comment o `200` para
patch/submit/approve/request-changes); una fila `PROCESSING` devuelve 409 y
una fila expirada puede reutilizarse como una nueva ventana. No se almacena
el contenido documental completo en el payload de replay.
- Las listas usan `page` (base 1), `page_size` (1–100) y `order`. El único
  orden permitido inicialmente es `created_at_desc` y se materializa como
  `created_at DESC, id DESC`, evitando SQL construido desde el cliente.
- Las respuestas JSON de 004 incluyen `request_id` como campo de metadata de
  respuesta. Las respuestas binarias/HTML llevan el request ID en el header
  de trazabilidad, no dentro del cuerpo.
- Ninguna respuesta expone `storage_path`, rutas absolutas, excepciones de
  librerías, stack traces, secretos o contenido documental en endpoints de
  metadata/listado. El endpoint de finalización devuelve únicamente el
  snapshot explícitamente solicitado por su contrato; listados y exportación
  no lo repiten.

### Envelope de error

```json
{
  "error": {
    "code": "EXPORT_FILE_CORRUPTED",
    "message": "The exported file failed integrity validation.",
    "details": {},
    "request_id": "req-01H...",
    "timestamp": "2026-08-03T21:00:00Z"
  }
}
```

004 reutiliza o extiende exactamente el serializer público de 003; no crea un
serializer público separado. `timestamp` es obligatorio, lo genera el servidor
en UTC y usa RFC 3339 con sufijo `Z`. `code` es estable. `message` y `details`
son sanitizados por la capa API; los
details permitidos son IDs, campos, estados esperados/actuales, límites,
hashes públicos de integridad y paginación. Nunca contienen paths, secretos,
contenido documental, stack traces ni excepciones internas.

## Revisión

### `GET /api/v1/drafts/{draft_id}/reviews/current`

Obtiene la revisión para la versión actual o la respuesta `REVIEW_NOT_FOUND`.
No cambia estado. Responde `200 ReviewResponse`.

### `POST /api/v1/drafts/{draft_id}/reviews`

Header obligatorio: `Idempotency-Key`.

Body:

```json
{"draft_version": 3, "expected_version": 3, "opened_by": "reviewer-01"}
```

`draft_version` debe coincidir con la versión editable y el actor no puede ser
vacío. `expected_version` es obligatorio y protege la mutación del draft.
Crea la revisión `OPEN` (`201`) o recupera la existente para la misma
combinación (`200`). La revisión fija `review_snapshot` y
`review_snapshot_sha256` mediante JSON canónico; ambos son inmutables. Errores:
`DRAFT_NOT_FOUND` (404), `CONCURRENT_MODIFICATION` (409), `VALIDATION_ERROR`
(422).

### `POST /api/v1/reviews/{review_id}/comments`

Header obligatorio: `Idempotency-Key`.

Body:

```json
{
  "author": "reviewer-01",
  "expected_version": 1,
  "body": "Verificar el fundamento citado.",
  "severity": "BLOCKING",
  "draft_version": 3,
  "anchor": {"kind": "section", "section": "CONSIDERANDO"},
  "parent_comment_id": null
}
```

`expected_version` es la versión actual de la revisión y es obligatorio.
`anchor` es opcional; una respuesta usa `parent_comment_id` y hereda la
revisión; el anclaje se valida contra el snapshot persistido. Responde
`201 CommentResponse` y crea un evento append-only. Errores:
`REVIEW_NOT_FOUND`/`COMMENT_NOT_FOUND` (404), `ANCHOR_VERSION_MISMATCH` o
`VALIDATION_ERROR` (422), `INVALID_REVIEW_TRANSITION` (409),
`CONTENT_TOO_LARGE` (422).

### `PATCH /api/v1/reviews/{review_id}/comments/{comment_id}`

Header obligatorio: `Idempotency-Key`.

Body:

```json
{"expected_version": 2, "status": "RESOLVED", "resolved_by": "reviewer-01"}
```

Solo cambia estado/resolución, no cuerpo ni anclaje. Responde `200`. Errores:
`REVIEW_NOT_FOUND`/`COMMENT_NOT_FOUND` (404), `CONCURRENT_MODIFICATION` o
`REVIEW_VERSION_MISMATCH` (409), `VALIDATION_ERROR` (422).

### `POST /api/v1/reviews/{review_id}/submit`

Header obligatorio: `Idempotency-Key`.

Body: `{"expected_version": 4, "submitted_by": "reviewer-01"}`. Exige que no
haya comentarios `BLOCKING` abiertos, cambia a `SUBMITTED`, registra evento y
responde `200`. Errores: `OPEN_BLOCKING_COMMENTS` o
`INVALID_REVIEW_TRANSITION` (409), `CONCURRENT_MODIFICATION` (409),
`VALIDATION_ERROR` (422).

### `POST /api/v1/reviews/{review_id}/approve`

Header obligatorio: `Idempotency-Key`.

Body:

```json
{
  "expected_version": 5,
  "decided_by": "reviewer-01",
  "human_review_confirmed": true
}
```

Exige revisión humana explícita y cero bloqueos. En una transacción pasa por
la decisión `APPROVED`, cierra la revisión (`status=CLOSED`, `closed_at`),
actualiza el draft a `APROBADO` mediante el servicio de 003 y registra ambos
eventos. Responde `200`. Errores: `HUMAN_REVIEW_REQUIRED` (422),
`OPEN_BLOCKING_COMMENTS`/`INVALID_REVIEW_TRANSITION` (409),
`CONCURRENT_MODIFICATION` (409).

### `POST /api/v1/reviews/{review_id}/request-changes`

Header obligatorio: `Idempotency-Key`.

Body: `{"expected_version": 5, "decided_by": "reviewer-01", "reason": "..."}`.
`reason` es obligatorio y no vacío. Cambia la revisión a
`CHANGES_REQUESTED`, mueve el draft al equivalente `RECHAZADO` de 003 y
registra un evento. Responde `200`. Errores: `MISSING_REVIEW_REASON` (422),
`INVALID_REVIEW_TRANSITION` o `CONCURRENT_MODIFICATION` (409).

### `GET /api/v1/reviews/{review_id}/history`

Query: `page`, `page_size`, `order=created_at_desc`. Responde `200` con
`PaginatedResponse[ReviewEventResponse]`, ordenado estable y sin texto
documental completo.

## Finalización y preview

### `POST /api/v1/drafts/{draft_id}/finalize`

Body:

```json
{
  "expected_version": 6,
  "finalized_by": "legal.editor@organismo",
  "finalization_notes": "Versión lista para exportar."
}
```

La primera solicitud exige estado aprobado, revisión `CLOSED`, ausencia de
`BLOCKING` abierto y `expected_version` actual. Dentro de una transacción corta
con lock del draft construye/valida el snapshot, calcula SHA-256, guarda los
metadatos e incrementa `document_drafts.version` de 6 a 7; en los contratos de
004 el nuevo valor se expone como `draft_version`. Responde `200
FinalizationResponse`.

Una repetición con el actor, notas y hash/snapshot de la solicitud original
devuelve `200` sin otro incremento. Un payload divergente devuelve
`DRAFT_ALREADY_FINALIZED` (409); una solicitud no repetible con versión vieja
devuelve `CONCURRENT_MODIFICATION` (409). Errores adicionales:
`DRAFT_NOT_FOUND` (404), `DRAFT_NOT_APPROVED`/`INVALID_FINALIZATION` (409/422),
`OPEN_BLOCKING_COMMENTS` (409), `VALIDATION_ERROR` (422).

### `GET /api/v1/drafts/{draft_id}/preview?draft_version={n}`

Solo acepta drafts aprobados. Antes de finalizar, `draft_version` debe ser la
versión aprobada actual; después de finalizar, `draft_version` debe ser la versión
final actual y el renderer ignora el contenido vivo y usa exclusivamente
`final_snapshot`. El draft finalizado continúa previsualizable.

Respuesta `200`:

- `Content-Type: text/html; charset=utf-8`;
- `ETag: "sha256:<64-hex>"`;
- `Cache-Control: no-store`;
- `X-Request-ID` de trazabilidad.

El endpoint no define respuesta condicional `304`; no crea exportación, no
escribe filesystem, no cambia estados/versiones y
devuelve `DRAFT_NOT_FOUND` (404), `DRAFT_NOT_APPROVED` (409),
`CONCURRENT_MODIFICATION` (409), `EXPORT_SIZE_EXCEEDED` (413) o
`VALIDATION_ERROR` (422) según corresponda.

## Exportaciones

### `POST /api/v1/drafts/{draft_id}/exports`

Headers: `Idempotency-Key`, `X-Request-ID` opcional. Body:

```json
{"draft_version": 7, "format": "DOCX", "exported_by": "legal.editor@organismo"}
```

Exige draft finalizado, versión actual, revisión cerrada y snapshot válido.
Tx1 crea `DocumentExport(PENDING)` y `ExportAttempt(PENDING)`, confirma en la
misma transacción `GENERATING` y `PROCESSING`, y la respuesta inicial es `202
DocumentExportResponse` con esos estados activos. El procesamiento local
posterior ocurre fuera de PostgreSQL y luego confirma Tx2.

La misma clave y hash con un resultado exitoso devuelve `200` con el resultado
existente. Si el intento sigue activo devuelve `EXPORT_IN_PROGRESS` (409).
Payload distinto devuelve `IDEMPOTENCY_CONFLICT` (409). Un registro fallido se conserva y esta operación
devuelve sus metadatos sin crear otro attempt; se recupera con `POST /retry`
usando la misma clave. Errores: `DRAFT_NOT_APPROVED`,
`DRAFT_NOT_FINALIZED`, `EXPORT_FORMAT_UNSUPPORTED` (422),
`ACTIVE_GENERATION_EXISTS`/`EXPORT_ALREADY_EXISTS` (409),
`IDEMPOTENCY_KEY_REQUIRED` (400), `VALIDATION_ERROR` (422).

### `GET /api/v1/drafts/{draft_id}/exports`

Query: `draft_version`, `export_version`, `format`, `status`, `page`, `page_size`, `order`.
Responde `200 PaginatedResponse[DocumentExportResponse]`. Solo metadata,
hashes, estados, renderer, actores y errores sanitizados; no `storage_path` ni
contenido. `DRAFT_NOT_FOUND` es 404 y filtros inválidos producen
`VALIDATION_ERROR` 422.

### `GET /api/v1/exports/{export_id}`

Responde `200 DocumentExportResponse` con el estado actual, hashes, `draft_version` y `export_version`,
renderer, timestamps, `parent_export_id` y error sanitizado. No incluye ruta,
binario ni snapshot. `EXPORT_NOT_FOUND` es 404.

### `GET /api/v1/exports/{export_id}/download`

Solo permite estados `GENERATED` y `SUPERSEDED`. Antes de crear el
`StreamingResponse` valida la ruta canónica, ausencia de symlink, extensión,
MIME/estructura y SHA-256 almacenado.

Respuesta `200`:

- `Content-Type` allowlist según formato;
- `Content-Disposition: attachment; filename="<deterministic-name>"`;
- `Content-Length` conocido;
- `ETag: "sha256:<64-hex>"`;
- `Cache-Control: private, no-store`;
- `Accept-Ranges: none`.

Si la solicitud incluye el header `Range`, responde `416 Range Not Satisfiable`
con el código estable `RANGE_NOT_SUPPORTED` y el envelope JSON uniforme con
`request_id` y `timestamp`. La respuesta conserva `Accept-Ranges: none`; no inicia streaming,
no abre ni lee el archivo completo y no devuelve `Content-Range` de un recurso
parcial inexistente. Este rechazo tiene precedencia sobre `If-None-Match`.

`If-None-Match` coincidente responde `304` sin iniciar el stream. Archivo
ausente: `EXPORT_FILE_NOT_FOUND` (410). Cualquier fallo de integridad:
`EXPORT_FILE_CORRUPTED` (409), se registra evento y el estado de la
exportación no cambia automáticamente a `FAILED`. Los códigos
`HASH_VALIDATION_FAILED` y `MIME_VALIDATION_FAILED` son causas internas y no
se exponen como alternativas públicas de descarga. Los fallos de hash, MIME,
estructura DOCX/PDF, truncamiento y archivo vacío usan este mismo código.

### `POST /api/v1/exports/{export_id}/retry`

Headers: `Idempotency-Key`. Body:
`{"exported_by":"legal.editor@organismo"}`.

Solo acepta `DocumentExport.status=FAILED`. Tx1 conserva el mismo export,
comprueba que el actor y el payload coincidan con la solicitud original y
reutiliza el mismo `request_hash`,
crea un nuevo attempt con `attempt_number + 1` y confirma en la misma Tx1 el
export en `GENERATING` y el attempt en `PROCESSING`; responde `202`. El
attempt anterior permanece `FAILED`. La generación exitosa lleva el export a
`GENERATED`; no crea otro `document_export`.

La creación inicial no crea otro attempt desde este endpoint. Un retry con
attempt activo devuelve `409 EXPORT_IN_PROGRESS`; un retry ya exitoso devuelve
`200` replay; si el retry anterior falló, una nueva invocación crea otro
attempt con el mismo key/hash y `attempt_number` incremental. Una clave/hash
diferente devuelve `IDEMPOTENCY_CONFLICT`; origen no FAILED devuelve
`INVALID_EXPORT_TRANSITION`.

### `POST /api/v1/exports/{export_id}/regenerate`

Headers: `Idempotency-Key`. Body:

```json
{"expected_version": 3, "exported_by":"legal.editor@organismo"}
```

Acepta origen `GENERATED` o `SUPERSEDED`, conserva el formato y no abre el
archivo origen. Requiere que `expected_version` represente el `export_version` máximo actual
para `(draft_id, format)`. Tx1 crea un nuevo export y attempt con
`parent_export_id` al origen, `export_version = max(export_version)+1` y
estado `GENERATING` con el attempt en `PROCESSING`. El
snapshot final inmutable es la única fuente de contenido.

Respuesta inicial `202`; replay de la misma clave/hash `200`. La exportación
`GENERATED` vigente pasa a `SUPERSEDED` solamente en Tx2 después de que la
nueva llegue a `GENERATED`; un origen ya `SUPERSEDED` no cambia. Ante fallo,
el artefacto anterior conserva estado y descargabilidad. Errores:
`EXPORT_NOT_FOUND` (404), `INVALID_EXPORT_TRANSITION`/`ACTIVE_GENERATION_EXISTS`/
`CONCURRENT_MODIFICATION`/`EXPORT_IN_PROGRESS`/`IDEMPOTENCY_CONFLICT` (409),
`IDEMPOTENCY_KEY_REQUIRED` (400), `VALIDATION_ERROR` (422).

### `GET /api/v1/exports/{export_id}/attempts`

Query: `status`, `page`, `page_size`, `order`. Responde `200` con intentos
paginados, `attempt_number`, estado, key/hash, actor, request ID, timestamps
y error sanitizado. Nunca incluye `storage_path`, stack trace o contenido.

## Catálogo de errores 004

| Código | HTTP | Capa |
|---|---:|---|
| `REVIEW_NOT_FOUND` | 404 | review service |
| `COMMENT_NOT_FOUND` | 404 | review service |
| `DRAFT_NOT_FOUND` | 404 | draft/export service |
| `INVALID_UUID` | 422 | request validation |
| `EXPORT_NOT_FOUND` | 404 | export repository |
| `EXPORT_FILE_NOT_FOUND` | 410 | storage/integrity |
| `DRAFT_NOT_APPROVED` | 409 | eligibility gate |
| `DRAFT_NOT_FINALIZED` | 409 | eligibility gate |
| `DRAFT_ALREADY_FINALIZED` | 409 | finalization service |
| `INVALID_FINALIZATION` | 422 | snapshot/actor validation |
| `INVALID_REVIEW_TRANSITION` | 409 | review state machine |
| `REVIEW_VERSION_MISMATCH` | 409 | review repository |
| `OPEN_BLOCKING_COMMENTS` | 409 | review gate |
| `HUMAN_REVIEW_REQUIRED` | 422 | review service |
| `MISSING_REVIEW_REASON` | 422 | review schema |
| `ANCHOR_VERSION_MISMATCH` | 422 | anchor validator |
| `EXPORT_FORMAT_UNSUPPORTED` | 422 | export schema |
| `EXPORT_IN_PROGRESS` | 409 | idempotency/active index |
| `REVIEW_OPERATION_IN_PROGRESS` | 409 | review idempotency/active request |
| `EXPORT_ALREADY_EXISTS` | 409 | export repository |
| `EXPORT_FILE_CORRUPTED` | 409 | integrity validator |
| `EXPORT_STORAGE_UNAVAILABLE` | 503 | storage adapter |
| `EXPORT_SIZE_EXCEEDED` | 413 | renderer/integrity |
| `INVALID_EXPORT_TRANSITION` | 409 | export state machine |
| `IDEMPOTENCY_KEY_REQUIRED` | 400 | API dependency |
| `IDEMPOTENCY_CONFLICT` | 409 | idempotency service |
| `CONCURRENT_MODIFICATION` | 409 | optimistic locking |
| `VALIDATION_ERROR` | 422 | Pydantic/domain validation |
| `DATABASE_ERROR` | 503 | repository/UoW |
| `FILESYSTEM_ERROR` | 500 | storage adapter |
| `PATH_VALIDATION_FAILED` | 500 | storage adapter |
| `GENERATION_TIMEOUT` | 504 | render execution |
| `EXPORT_GENERATION_FAILED` | 500 | renderer orchestration before 202 |
| `RANGE_NOT_SUPPORTED` | 416 | download route before file access |
| `MIME_VALIDATION_FAILED` | 422 create / internal download cause | integrity validator |
| `HASH_VALIDATION_FAILED` | internal generation cause | integrity validator/logs |
| `ACTIVE_GENERATION_EXISTS` | 409 | partial unique index |
| `CLEANUP_CONFLICT` | 409 | reconcile service |
| `CONTENT_TOO_LARGE` | 422 | existing/shared validation |

No endpoint in this contract returns HTTP 507.

### Detalle contractual de errores de revisión

| Código | Condición | Endpoint o capa | HTTP | Message sanitizado | Test previsto |
|---|---|---|---:|---|---|
| `REVIEW_NOT_FOUND` | La revisión solicitada no existe | current y operaciones `/reviews/{review_id}` / review service | 404 | `The requested review was not found.` | T059/T061 |
| `COMMENT_NOT_FOUND` | El comentario solicitado no existe | PATCH comment / review service | 404 | `The requested review comment was not found.` | T059/T061 |
| `INVALID_REVIEW_TRANSITION` | El estado actual no permite la mutación | submit, approve, request-changes y comment mutations / state machine | 409 | `The requested review transition is not allowed.` | T059/T061 |
| `REVIEW_VERSION_MISMATCH` | `expected_version` no coincide con la revisión | mutaciones `/reviews/{review_id}` / review repository | 409 | `The review version does not match the expected version.` | T059/T061 |
| `OPEN_BLOCKING_COMMENTS` | Existen comentarios blocking abiertos | submit, approve y finalize / review gate | 409 | `The review has unresolved blocking comments.` | T059/T061 |
| `HUMAN_REVIEW_REQUIRED` | Falta confirmación humana explícita | approve / review service | 422 | `Human review confirmation is required.` | T059/T061 |
| `MISSING_REVIEW_REASON` | Request-changes no incluye motivo válido | request-changes / review schema | 422 | `A reason is required to request changes.` | T059/T061 |
| `ANCHOR_VERSION_MISMATCH` | El ancla no corresponde a la versión revisada | POST comments / anchor validator | 422 | `The comment anchor does not match the reviewed draft version.` | T059/T061 |
| `REVIEW_OPERATION_IN_PROGRESS` | La misma operación idempotente está activa | seis mutaciones de review / idempotency service | 409 | `A review operation with this idempotency key is already in progress.` | T059/T061 |

Este contrato no define `REVIEW_ALREADY_EXISTS` ni `INVALID_REVIEW_STATUS`.
