# Tasks: 004 — Revisión humana y exportación de documentos

**Input**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `quickstart.md`,
`contracts/http-api.md`, `contracts/admin-reconcile-cli.md`,
`checklists/requirements.md`, y los artefactos cerrados de 003.

**Alcance**: implementar únicamente el incremento 004 sobre el backend existente.
No se modifican los incrementos 001–003, la constitución ni los principios. Todas
las tareas permanecen sin marcar hasta que la implementación y sus verificaciones
se hayan completado.

**Convenciones de rutas**: las rutas de código son relativas a la raíz del
repositorio `C:\Users\Uriel Sabugo\Desktop\GitHub\legal-AI-infraestructure`.
La API mantiene `/api/v1`, PostgreSQL 16, SQLAlchemy/Alembic, almacenamiento local
y transacciones PostgreSQL cortas. La compatibilidad con `DraftStatus` de 003
(`APROBADO` en el enum actual y `APPROVED` en el contrato normativo) y con el
envelope público exacto de 003 debe reutilizarse o extenderse, con
`request_id`/`timestamp` y sin serializer público separado para 004, sin cambiar
el comportamiento observable de 001–003.

## Phase 1: Preparación y dependencias

**Purpose**: preparar dependencias, runtime, configuración operativa y smoke tests
sin introducir servicios externos, colas, Redis, scheduler ni almacenamiento cloud.

- [X] T001 Inspeccionar y documentar en la tarea de implementación la configuración vigente de dependencias, entry points, imagen, Compose y variables en `apps/api/pyproject.toml`, `apps/api/Dockerfile`, `compose.yaml` y `.env.example`, verificando que no se dupliquen capacidades de 003.
- [X] T002 Actualizar `apps/api/pyproject.toml` para agregar `python-docx` y `weasyprint` con versiones compatibles con Python 3.12, declarar el entry point `document-exports` para la CLI y conservar los scripts actuales de Ruff, mypy y pytest.
- [X] T003 Regenerar `apps/api/uv.lock` desde el proyecto `apps/api` después de cambiar `pyproject.toml`, verificando que el lockfile contenga únicamente dependencias del proyecto y que no se instalen dependencias globales.
- [X] T004 Actualizar `apps/api/Dockerfile` con las bibliotecas nativas de Pango/Cairo y fuentes necesarias para WeasyPrint, manteniendo la ejecución con `appuser`, permisos mínimos y una imagen Linux reproducible.
- [X] T005 Actualizar `compose.yaml` para inyectar las variables de exportación, montar el volumen local de `EXPORT_STORAGE_ROOT` con permisos de escritura para el usuario de aplicación y mantener los servicios de 001–003 sin añadir Redis, workers ni scheduler.
- [X] T006 Documentar en `.env.example` `EXPORT_STORAGE_ROOT`, timeouts, límites, ventana de idempotencia y retenciones con sus valores por defecto definidos en `plan.md`, sin incluir secretos ni rutas dependientes de PII.
- [X] T007 Implementar la configuración tipada `ExportConfig` y su validación de límites, timeouts, retenciones, `EXPORT_PDF_EOF_TAIL_BYTES` y `MAX_PAGE_SIZE` en `apps/api/src/legal_ai/config.py`, integrándola en `Settings` sin romper la carga lazy de Ollama.
- [X] T008 Crear `apps/api/tests/unit/test_export_dependencies.py` para comprobar imports de `python-docx` y WeasyPrint, lectura de `ExportConfig`, valores por defecto y comportamiento explícito del renderer PDF reemplazable en Windows y Linux.
- [X] T009 Crear `apps/api/tests/unit/test_004_config.py` con casos de valores inválidos, límites máximos, root absoluto aceptado/canónico, root relativo rechazado y retenciones no positivas, esperando errores de configuración sanitizados.

## Phase 2: Migración y modelos fundacionales

**Purpose**: crear el modelo de dominio y la migración 004 compatible con los
datos existentes de 003 antes de agregar servicios o endpoints.

- [X] T010 Extender `apps/api/src/legal_ai/domain/enums.py` con los enums de review, severidad/status de comentarios, `DocumentExportStatus`, `ExportAttemptStatus`, `ReviewOperationStatus` y formatos persistibles DOCX/PDF, conservando exactamente los estados de `DraftStatus` de 003.
- [X] T011 Extender `apps/api/src/legal_ai/domain/draft.py` con `finalized_by`, `finalized_at`, `finalization_notes`, `final_snapshot` y `final_snapshot_sha256`, además de `can_finalize()`/`is_finalized()` y las invariantes write-once sin conocer SQLAlchemy ni filesystem.
- [X] T012 [P] Crear `apps/api/src/legal_ai/domain/review.py` con la entidad de revisión por `(draft_id, draft_version)`, transiciones explícitas, versionado optimista, timestamps UTC y reglas de cierre/aprobación.
- [X] T013 [P] Crear `apps/api/src/legal_ai/domain/review_comment.py` con comentarios generales/anclados y respuestas enlazadas, validación de anclaje a la misma versión, límite de 10.000 caracteres y status no destructivo.
- [X] T014 [P] Crear `apps/api/src/legal_ai/domain/review_event.py` con eventos append-only para review, finalización, exportación, descarga bloqueada y reconciliación, incluyendo actor, request/run ID, versión y resumen minimizado.
- [X] T015 [P] Crear `apps/api/src/legal_ai/domain/document_export.py` con el artefacto versionado, estados, formato, renderer, snapshot fuente, hash, ruta relativa y transiciones `PENDING → GENERATING → GENERATED → SUPERSEDED/FAILED`.
- [X] T016 [P] Crear `apps/api/src/legal_ai/domain/export_attempt.py` con estado de procesamiento, `idempotency_key`, `request_hash`, `attempt_number`, actor, timestamps, error sanitizado y reglas de retry.
- [X] T017 [P] Crear `apps/api/src/legal_ai/domain/canonical_document.py` con la representación canónica inmutable que comparten preview, DOCX y PDF, separando contenido aprobado, configuración institucional y snapshot final.
- [X] T018 Extender `apps/api/src/legal_ai/adapters/database/models.py` para mapear el draft finalizado, `DocumentReview` con `review_snapshot`/hash inmutables, `ReviewOperationRequest`, `ReviewComment`, `ReviewEvent`, `DocumentExport` con `export_version` y `ExportAttempt`, incluyendo relaciones, `attempt_id` con `ON DELETE SET NULL`, FKs, cascadas append-only y tipos PostgreSQL coherentes con `data-model.md`.
- [X] T019 Crear `apps/api/alembic/versions/004_document_review_and_export.py` con upgrade ordenado: alterar `document_drafts`, crear `document_exports` con `review_id` y FK diferida, crear `export_attempts` con FK obligatoria a export, crear reviews/comments, crear `review_operation_requests`, crear `review_events`, añadir la FK diferida y finalmente aplicar índices/checks/constraints.
- [X] T020 Completar en `apps/api/alembic/versions/004_document_review_and_export.py` el downgrade inverso y seguro: `review_events`, quitar la FK diferida, `review_operation_requests`, `review_comments`, `document_reviews`, `export_attempts`, `document_exports` y columnas nuevas de `document_drafts`, sin tocar las revisiones 001–003.
- [X] T021 Crear `apps/api/tests/integration/factories_004.py` con factories deterministas de drafts aprobados, reviews, comentarios, snapshots finales, exports, attempts, archivos y eventos, sin datos personales reales.
- [X] T022 Crear `apps/api/tests/integration/test_004_migrations.py` para ejecutar upgrade desde 003, comprobar tablas/columnas/enums/FKs/defaults y ejecutar downgrade hasta 003 en una base PostgreSQL efímera.
- [X] T023 Extender `apps/api/tests/integration/test_004_migrations.py` con pruebas de datos existentes de 003: drafts sin metadata de finalización siguen siendo legibles, los estados previos no cambian y no se exige backfill ficticio.
- [X] T024 Crear `apps/api/tests/integration/test_004_constraints.py` para verificar `CHECK` de longitudes/estados, `export_attempts.export_id NOT NULL`, `review_events.attempt_id ON DELETE SET NULL`, índice único parcial de `RECONCILIATION_RUN.run_id`, snapshot/hash de review NOT NULL, `review_operation_requests` scope/expiración/status y unique, unique `(draft_id, format, export_version)`, `parent_export_id`, índice parcial de un intento activo por actor+clave e índice parcial de una generación activa por draft+formato.

## Phase 3: Puertos, repositorios, schemas, errores y configuración HTTP

**Purpose**: fijar contratos internos y contratos de entrada/salida antes de las
historias de usuario.

- [X] T025 [P] Crear `apps/api/src/legal_ai/ports/review_repository.py` con operaciones de current/create, lock optimista y lecturas paginadas por draft/draft_version; crear `apps/api/src/legal_ai/ports/review_operation_request_repository.py` para claim/replay/conflict/expiry por operación+recurso+clave.
- [X] T026 [P] Crear `apps/api/src/legal_ai/ports/review_comment_repository.py` con operaciones de comentario/respuesta, cambios de status y consulta temporal por review.
- [X] T027 [P] Crear `apps/api/src/legal_ai/ports/review_event_repository.py` con append-only event creation, lectura ordenada y replay por `run_id`/request ID.
- [X] T028 [P] Crear `apps/api/src/legal_ai/ports/document_export_repository.py` con creación Tx1, consultas por draft/export, asignación segura de versión, transición Tx2 y filtros estables.
- [X] T029 [P] Crear `apps/api/src/legal_ai/ports/export_attempt_repository.py` con replay por clave/hash, attempt incremental, detección de active y consultas paginadas sin errores internos.
- [X] T030 [P] Crear `apps/api/src/legal_ai/ports/artifact_storage.py` con contrato de root, resolve relativo, temp, atomic replace, streaming, existencia, hash/lectura y eliminación compensatoria sin exponer path interno.
- [X] T031 [P] Crear `apps/api/src/legal_ai/ports/artifact_integrity.py` con contratos de validación general, DOCX, PDF y cálculo SHA-256.
- [X] T032 [P] Crear `apps/api/src/legal_ai/ports/renderers.py` con protocolos `CanonicalHtmlRenderer`, `DocxRenderer` y `PdfRenderer`, método estático `health()` en `PdfRenderer`, entradas/resultados serializables, timeouts y excepciones sanitizables; mantener los puertos independientes del ejecutor de procesos y de la DB.
- [X] T033 Crear `apps/api/src/legal_ai/adapters/database/review_repository.py` implementando el puerto de reviews con SQLAlchemy, snapshot/hash inmutables, locks acotados y orden estable por timestamp/id; adaptar `review_operation_requests` con unicidad y replay sanitizado.
- [X] T034 Crear `apps/api/src/legal_ai/adapters/database/review_comment_repository.py` implementando comentarios/respuestas, control de versión y rechazo de mutaciones sobre drafts finalizados.
- [X] T035 Crear `apps/api/src/legal_ai/adapters/database/review_event_repository.py` implementando append-only, almacenamiento UTC y replay idempotente de `run_id` con filtros hash.
- [X] T036 Crear `apps/api/src/legal_ai/adapters/database/document_export_repository.py` implementando consultas, versionado `(draft_id, format)`, estados descargables y traducción segura de `IntegrityError`.
- [X] T037 Crear `apps/api/src/legal_ai/adapters/database/export_attempt_repository.py` implementando request hash, mismo key/hash, attempt incremental y manejo de índice parcial de active.
- [X] T038 Extender `apps/api/src/legal_ai/adapters/database/unit_of_work.py` con repositories 004, idempotencia de review y métodos explícitos para Tx1, Tx2, retry, regeneración y rollback corto, sin mantener sesión durante render.
- [X] T039 Crear `apps/api/src/legal_ai/domain/errors.py` con excepciones de dominio y códigos estables del catálogo 004, status esperado y `details` seguros, sin importar FastAPI, SQLAlchemy ni librerías de render.
- [X] T040 Crear `apps/api/src/legal_ai/schemas/review.py` con request/response de reviews, comentarios, respuestas, acciones y los nombres contractuales heredados reales de actor (`opened_by`, `submitted_by`, `decided_by`, `author` o `actor`), `expected_version`, anclajes, severidad/status y `extra="forbid"`; documentar `Idempotency-Key` obligatorio y replay sanitizado sin inventar campos alternativos de identidad.
- [X] T041 Crear `apps/api/src/legal_ai/schemas/finalization.py` con `FinalizeDraftRequest/Response`, validación de `finalized_by`, notes, snapshot/hash visibles solo donde el contrato lo permite y `expected_version` obligatorio.
- [X] T042 Crear `apps/api/src/legal_ai/schemas/export.py` con requests de create/retry/regenerate, responses de export/attempt, formatos, `exported_by`, `Idempotency-Key`, filtros y paginación uniforme con `page_size <= 100`.
- [X] T043 Extender `apps/api/src/legal_ai/schemas/draft.py` para representar metadata de finalización sin exponer el snapshot documental salvo en los endpoints que lo requieren, manteniendo compatibilidad de respuestas de 003.
- [X] T044 Extender `apps/api/src/legal_ai/schemas/errors.py` reutilizando o extendiendo, sin serializer público separado para 004, el envelope público exacto de 003 `{error:{code,message,details,request_id,timestamp}}`, con `timestamp` obligatorio generado por el servidor en UTC, RFC 3339 y sufijo `Z`.
- [X] T045 Crear `apps/api/src/legal_ai/api/dependencies.py` para inyectar UoW/config, exigir `Idempotency-Key` en las seis mutaciones de review y en create/retry/regenerate, obtener `request_id` del middleware y validar headers sin inferir actores.
- [X] T046 Extender `apps/api/src/legal_ai/api/exceptions.py` con el mapping de excepciones 004 a status/código/mensaje sanitizado, incluyendo `REVIEW_OPERATION_IN_PROGRESS`, traduciendo `IntegrityError`, MIME/hash/filesystem/path/timeout/database y errores de revisión sin filtrar internos.
- [X] T047 Extender `apps/api/src/legal_ai/main.py` para registrar handlers 004 mediante el serializer público existente de 003, devolver `request_id` obligatorio en cada respuesta JSON y `timestamp` obligatorio en cada error, preservando handlers y clases de 001–003.
- [X] T048 Crear `apps/api/tests/unit/test_actor_validation.py` con casos de trim, Unicode, mayúsculas/minúsculas, longitud 1–100, caracteres permitidos, vacío/solo espacios y caracteres prohibidos para `finalized_by`, `exported_by` y los campos contractuales reales de review; verificar ausencia de FK/unicidad, uso exclusivo de auditoría y exclusión de paths/`file_name`.
- [X] T049 Crear `apps/api/tests/contract/test_004_error_response.py` para verificar el envelope público exacto de 003, `request_id`, `timestamp` obligatorio generado por servidor en UTC/RFC 3339 con `Z`, `INVALID_UUID` (422), códigos/status completos, `details` permitidos y ausencia de stack trace, paths, secretos, excepciones de librerías y contenido documental.
- [X] T050 Extender `apps/api/tests/unit/test_004_config.py` y `apps/api/tests/contract/test_004_error_response.py` con validación uniforme de `Idempotency-Key`, `page_size`, filtros, `extra=forbid`, reutilización del serializer público de 003 sin variante pública 004 y no regresión exacta de su envelope con `request_id`/`timestamp`.

## Phase 4: US1 — Revisión humana del draft

**Purpose**: abrir/recuperar una revisión versionada, gestionar comentarios y
cerrar/aprobar o solicitar cambios con auditoría y locking optimista.

- [X] T051 [US1] Inspeccionar antes de agregar código `apps/api/src/legal_ai/api/routes/drafts.py`, `apps/api/src/legal_ai/application/draft_service.py`, `apps/api/src/legal_ai/domain/draft.py`, `apps/api/src/legal_ai/adapters/database/models.py` y sus tests de 003, identificando qué transiciones/repositories se reutilizan y evitando duplicación.
- [X] T052 [US1] Crear primero `apps/api/tests/unit/test_review_state_machine.py` con transiciones válidas/ inválidas de review, comentarios blocking, resolución/dismissal, submit, approve, request-changes y rechazo de cualquier mutación con review/draft finalizado.
- [X] T053 [US1] Crear `apps/api/src/legal_ai/application/review_service.py` para current/create review por `(draft_id,draft_version)`, comentarios generales/anclados y respuestas, resolución/dismissal no destructivo y snapshot/hash de revisión inmutables y validación de actor/expected_version.
- [X] T054 [US1] Extender `apps/api/src/legal_ai/application/review_service.py` para submit, approve y request-changes: exigir revisión humana, impedir blocking abiertos, exigir motivo no vacío para cambios, actualizar el draft mediante la máquina de 003, usar el `review_snapshot` persistido, invalidar la review abierta de la versión anterior cuando 003 edite o regenere una nueva versión sin borrar historial y crear evento append-only por operación.
- [X] T055 [US1] Crear `apps/api/tests/unit/test_review_service.py` para current/create, comentarios/respuestas, blocking, submit, approve/request-changes, actores, replay, conflicto, operación activa, expiración y concurrencia de idempotencia, errores heredados de 003 y eventos producidos.
- [X] T056 [US1] Crear `apps/api/tests/integration/test_review_repositories.py` para CRUD, snapshot/hash, anclajes a draft_version, orden temporal, optimistic locking, FKs, eventos append-only y recuperación sin mezclar versiones.
- [X] T057 [US1] Crear `apps/api/src/legal_ai/api/routes/reviews.py` con los ocho endpoints contractuales: current, create, add comment, patch comment, submit, approve, request-changes e history, incluyendo Idempotency-Key, body/header/expected_version/status y errores definidos en `contracts/http-api.md`.
- [X] T058 [US1] Extender `apps/api/src/legal_ai/api/router.py` para registrar `reviews.py` bajo `/api/v1` sin alterar las rutas de 001–003.
- [X] T059 [US1] Crear `apps/api/tests/contract/test_reviews_endpoints.py` cubriendo los ocho endpoints, respuestas exitosas con request ID y errores con el envelope contractual `request_id`/`timestamp`, replay/conflicto/active/expiry por cada mutación, paginación de history, actores, blocking, ausencia de contenido interno y cada código/status/mensaje sanitizado del catálogo: `REVIEW_NOT_FOUND`, `COMMENT_NOT_FOUND`, `INVALID_REVIEW_TRANSITION`, `REVIEW_VERSION_MISMATCH`, `OPEN_BLOCKING_COMMENTS`, `HUMAN_REVIEW_REQUIRED`, `MISSING_REVIEW_REASON`, `ANCHOR_VERSION_MISMATCH` y `REVIEW_OPERATION_IN_PROGRESS`.
- [X] T060 [US1] Extender `apps/api/tests/integration/test_004_uow_transactions.py` para comprobar commit/rollback de cada transición de review y que una carrera con `expected_version` deje un solo ganador y que una repetición concurrente con la misma clave produzca un solo claim y un `CONCURRENT_MODIFICATION`.
- [X] T061 [US1] Extender `apps/api/tests/contract/test_reviews_endpoints.py` con repetición idempotente de cada mutación (replay, payload distinto, active, expiración), payload divergente y escenarios específicos de los nueve errores de revisión de FR-032.1 —incluidos not-found, transición/version/anchor mismatch, blocking, confirmación humana, motivo faltante y operación activa—, además de invalidación de la review al editar o regenerar una nueva versión y bloqueo después de finalización; confirmar que no existen `REVIEW_ALREADY_EXISTS` ni `INVALID_REVIEW_STATUS`.

## Phase 5: US2 — Finalización write-once

**Purpose**: convertir una versión aprobada y con revisión cerrada en un snapshot
final inmutable sin ampliar la máquina de estados de 003.

- [X] T062 [US2] Extender `apps/api/src/legal_ai/ports/draft_repository.py` y `apps/api/src/legal_ai/adapters/database/draft_repository.py` con lectura/actualización finalizable bajo `expected_version`, lock corto y guardas write-once para metadata/hash/snapshot.
- [X] T063 [US2] Crear `apps/api/tests/unit/test_canonical_document.py` para serialización canónica determinista, orden estable, límite de 2 MiB (2.097.152 bytes) serializado medido en bytes UTF-8, aceptación del límite exacto, rechazo de límite + 1 byte, contenido multibyte, preservación del límite histórico de 100 KiB de 003 donde corresponda, exclusión de PII innecesaria y SHA-256 idéntico para el mismo contenido.
- [X] T064 [US2] Crear `apps/api/src/legal_ai/application/canonical_document.py` para construir el snapshot desde contenido aprobado, configuración institucional y datos obligatorios, serializarlo de forma canónica y calcular `final_snapshot_sha256`.
- [X] T065 [US2] Crear `apps/api/src/legal_ai/application/finalization_service.py` para validar `APPROVED`/`APROBADO`, revisión CLOSED sin blocking, actor/notes/expected_version, persistir una sola vez e incrementar `document_drafts.version` dentro de una transacción corta.
- [X] T066 [US2] Extender `apps/api/src/legal_ai/application/finalization_service.py` con replay 200 cuando actor/notes/snapshot/draft_version coinciden, `DRAFT_ALREADY_FINALIZED` para payload distinto, `CONCURRENT_MODIFICATION` para `expected_version` stale y auditoría sin contenido completo.
- [X] T067 [US2] Crear `apps/api/tests/unit/test_finalization_service.py` para primer éxito, snapshot/hash, replay, payload diferente, draft no aprobado, review abierta/blocking, notes/actor inválidos, límite y errores sanitizados.
- [X] T068 [US2] Extender `apps/api/src/legal_ai/api/routes/drafts.py` con `POST /api/v1/drafts/{draft_id}/finalize`, body contractual, status 200/409/422, request ID y responses sin exponer datos no contractuales.
- [X] T069 [US2] Crear `apps/api/tests/contract/test_finalization_preview_endpoints.py` con finalización exitosa, doble finalización idempotente, payload divergente, draft/review inválidos, `expected_version` stale y request ID.
- [X] T070 [US2] Crear `apps/api/tests/integration/test_004_uow_transactions.py` con persistencia de snapshot/hash, incremento de versión, rollback atómico y dos finalizaciones concurrentes con un solo ganador.
- [X] T071 [US2] Extender `apps/api/src/legal_ai/application/draft_service.py` y `apps/api/src/legal_ai/api/routes/drafts.py` para validar por bytes que las superficies nuevas de 004 no superen 2 MiB (2.097.152 bytes) y que los endpoints heredados de 003 conserven el límite efectivo de 100 KiB (102.400 bytes), el error y cualquier límite más estricto heredado (`CONTENT_TOO_LARGE`), además de bloquear edición, rechazo, nueva aprobación y regeneración del draft cuando `is_finalized()` sea verdadero, conservando errores de 003.
- [X] T072 [US2] Extender `apps/api/src/legal_ai/application/review_service.py` y sus tests para rechazar comentarios, resolución, submit, approve y request-changes sobre un draft finalizado, sin borrar historial.
- [X] T073 [US2] Extender `apps/api/tests/contract/test_finalization_preview_endpoints.py` para verificar el límite heredado exacto de 100 KiB de 003 y el límite runtime 004 de 2 MiB (2.097.152 bytes), con aceptación exacta, rechazo de +1 byte y contenido multibyte, `CONTENT_TOO_LARGE` correspondiente, todos los bloqueos post-finalización y que las regeneraciones posteriores solo puedan ser de exports.

## Phase 6: US2 — HTML canónico y preview

**Purpose**: proporcionar preview HTML efímero, sanitizado y coherente con el
snapshot final, sin efectos laterales.

- [X] T074 [US2] Crear `apps/api/src/legal_ai/adapters/renderers/__init__.py` y `apps/api/src/legal_ai/adapters/renderers/canonical_html_renderer.py` con implementación del puerto HTML: representación autocontenida, escape/sanitización de scripts/iframes/referencias remotas y límite por bytes de 5 MiB (5.242.880 bytes).
- [X] T075 [US2] Extender `apps/api/tests/unit/test_renderers.py` para HTML válido, escape XSS, ausencia de scripts/iframes/recursos no declarados, determinismo, límite de preview 5 MiB (5.242.880 bytes) medido en UTF-8 con aceptación exacta/rechazo +1 byte/contenido multibyte, contenido sobredimensionado y excepciones sanitizadas.
- [X] T076 [US2] Crear `apps/api/src/legal_ai/application/preview_service.py` para exigir `draft_version` obligatorio y la versión aprobada/final actual, seleccionar contenido aprobado antes de finalizar y exclusivamente `final_snapshot` después, sin llamar Ollama ni persistir archivos/exports.
- [X] T077 [US2] Extender `apps/api/src/legal_ai/api/routes/drafts.py` con `GET /api/v1/drafts/{draft_id}/preview?draft_version={n}` y query `draft_version` obligatorio, `text/html; charset=utf-8`, ETag SHA-256, `Cache-Control: no-store`, límites y errores contractuales.
- [X] T078 [US2] Extender `apps/api/tests/contract/test_finalization_preview_endpoints.py` con preview antes/después de finalización, query `draft_version` obligatorio, rechazo de versión stale y uso de la versión actual, drafts no APPROVED, finalizados previsualizables, headers y respuesta sin persistencia.
- [X] T079 [US2] Extender `apps/api/tests/integration/test_004_uow_transactions.py` para demostrar que preview no crea filas, no escribe filesystem, no incrementa `document_drafts.version`, no cambia estado y no inicia exportaciones.

## Phase 7: US3 — Storage local seguro

**Purpose**: encapsular filesystem local bajo `EXPORT_STORAGE_ROOT`, con paths
relativos, permisos mínimos y rename atómico.

- [X] T080 [US3] Crear `apps/api/src/legal_ai/adapters/storage/__init__.py` y `apps/api/src/legal_ai/adapters/storage/local_artifact_storage.py` con `LocalArtifactStorage`, root canónico configurable, layout `{case_file_id}/{draft_id}/{format}/v{export_version}/{file_name}` y nombre determinista `{draft_id}_v{export_version}.{extension}`.
- [X] T081 [US3] Implementar en `apps/api/src/legal_ai/adapters/storage/local_artifact_storage.py` rechazo de path absoluto, `..`, doble extensión, caracteres/PII prohibidos, segmentos symlink y resolución fuera del root; persistir únicamente ruta relativa con longitud máxima 500.
- [X] T082 [US3] Implementar en `apps/api/src/legal_ai/adapters/storage/local_artifact_storage.py` creación de directorios 0700/archivos 0600 cuando el sistema lo soporte, temporales aleatorios en el mismo directorio, `os.replace`, lectura streaming, `health()` de root escribible sin exponer la ruta y eliminación compensatoria segura.
- [X] T083 [P] [US3] Crear `apps/api/tests/unit/test_local_artifact_storage.py` para traversal, root canónico, symlink en cada segmento, filename determinista, colisiones, longitud, permisos, temporal y rename atómico en Windows/Linux.
- [X] T084 [P] [US3] Crear `apps/api/tests/integration/test_storage_integration.py` para escritura/lectura/streaming en `tmp_path`, resolución del root, creación segura de directorios, reemplazo atómico, archivo faltante y compensación tras error.
- [X] T085 [US3] Crear `apps/api/tests/integration/test_storage_integration.py` para carreras de la misma combinación draft/formato/export_version, garantizar no colisión y verificar que ningún actor, case number, document type o fecha aparezca en el path.

## Phase 8: US3 — Validación de integridad

**Purpose**: validar tamaño, MIME, estructura y SHA-256 antes de confirmar un
artefacto y antes de cada descarga.

- [X] T086 [US3] Crear `apps/api/src/legal_ai/application/artifact_integrity.py` con SHA-256 streaming, rechazo de archivo vacío, tamaño general y límites DOCX/PDF, devolviendo errores de dominio sin exponer excepciones de librería.
- [X] T087 [US3] Implementar en `apps/api/src/legal_ai/application/artifact_integrity.py` validación DOCX de extensión/MIME exactos, ZIP válido, `[Content_Types].xml`, `word/document.xml`, máximo 500 entradas, 50 MiB (52.428.800 bytes) descomprimidos y ratio máximo 100:1.
- [X] T088 [US3] Implementar en `apps/api/src/legal_ai/application/artifact_integrity.py` validación PDF de extensión/MIME exactos, header `%PDF-`, `%%EOF` en el tramo configurable final, MIME spoofing y hash esperado.
- [X] T089 [P] [US3] Crear `apps/api/tests/unit/test_artifact_integrity.py` con DOCX/PDF válidos, vacío, corrupto, MIME/extension mismatch, doble extensión, hash incorrecto, 501 entradas, ratio >100:1 y EOF ausente; probar en bytes aceptación exacta y rechazo +1 para DOCX 20 MiB (20.971.520), PDF 30 MiB (31.457.280) y DOCX descomprimido 50 MiB (52.428.800), incluyendo metadata/contenido multibyte donde aplique.
- [X] T090 [P] [US3] Crear `apps/api/tests/fixtures/canonical_document.json`, `apps/api/tests/fixtures/valid_document.docx`, `apps/api/tests/fixtures/valid_document.pdf`, `apps/api/tests/fixtures/corrupt_document.pdf` y `apps/api/tests/fixtures/zip_bomb_metadata.json` con contenido sintético sin PII para los validadores.
- [X] T091 [US3] Extender `apps/api/tests/integration/test_storage_integration.py` y `apps/api/tests/unit/test_artifact_integrity.py` para confirmar cálculo al crear, recálculo al descargar y que corrupción no cambie automáticamente `GENERATED` a `FAILED`.

## Phase 9: US3 — Renderers DOCX y PDF

**Purpose**: implementar adaptadores reemplazables que reciban el documento
canónico, escriban únicamente en el temporal proporcionado y devuelvan metadata
del resultado, sin tocar DB ni publicar/eliminar artefactos finales.

- [X] T092 [US3] Crear `apps/api/src/legal_ai/adapters/renderers/docx_renderer.py` con implementación `python-docx`, validación de campos obligatorios y deadline de 30 s; escribir solo en el temporal proporcionado, sin publicar después del vencimiento, y hacer que la operación sea invocable en el proceso hijo aislado sin sesiones DB, objetos ORM ni request context.
- [X] T093 [US3] Implementar en `apps/api/src/legal_ai/adapters/renderers/docx_renderer.py` A4 vertical, márgenes 2,5/2,5/3/2 cm, Arial 11, título Arial 12 negrita centrado, justificado, interlineado 1,5, 6 pt posterior, header configurable, VISTO/CONSIDERANDO/POR ELLO, artículos `ARTÍCULO n°`, firmas configurables, pie solo con numeración y locale es-AR.
- [X] T094 [US3] Crear `apps/api/src/legal_ai/adapters/renderers/pdf_renderer.py` con implementación WeasyPrint desde HTML canónico, escribiendo solo en el temporal proporcionado, método estático `health()` para el smoke operativo, deadline de 60 s, sin publicar después del vencimiento, aislamiento de excepciones y puerto headless reemplazable sin conversión DOCX→PDF; hacer que la operación sea invocable en el proceso hijo aislado sin acceso DB ni filesystem fuera del temporal seguro.
- [X] T095 [P] [US3] Extender `apps/api/tests/unit/test_renderers.py` con fakes de DOCX/PDF, health/readiness, datos obligatorios faltantes, HTML de entrada común, metadata sin PII, aislamiento de errores y ausencia de acceso a DB/storage; probar timeout, solicitud de terminación, gracia, `kill`, `join`, cleanup, no reutilización del hijo y ausencia de publicación vencida.
- [X] T096 [P] [US3] Crear `apps/api/tests/integration/test_renderer_integration.py` para inspeccionar DOCX real como ZIP/XML y PDF real en Linux/Docker cuando las dependencias nativas estén disponibles; marcar el test real como opcional en Windows, mantener el fake determinista y verificar proceso hijo `spawn`, finalización sin zombis y timeout aislado.
- [X] T097 [US3] Extender `apps/api/tests/unit/test_renderers.py` con comprobaciones de requisitos DOCX mediante el validador de integridad y con el contrato PDF `%PDF-`/`%%EOF`, sin depender de LibreOffice.

## Phase 10: US3 — Exportación inicial

**Purpose**: crear DOCX/PDF versionados con idempotencia, Tx1/Tx2, generación
fuera de transacción, integridad, rename atómico y compensación.

- [X] T098 [US3] Crear `apps/api/tests/unit/test_export_idempotency.py` con request hash canónico, misma clave+payload, intento activo, export FAILED sin nuevo attempt desde creación, retry posterior, clave+payload distinto, ventana de 24 horas y replay de resultado.
- [X] T099 [US3] Crear `apps/api/tests/unit/test_export_service.py` con escenarios Tx1 PENDING→GENERATING/PROCESSING en la misma transacción, render diferido después de 202, validación, éxito, fallo de renderer/timeout/MIME/hash/size/storage y errores sanitizados; verificar que el timeout ejecuta terminación→gracia→`kill`→`join`, elimina temporales, registra `GENERATION_TIMEOUT` y no publica ni reutiliza el proceso.
- [X] T100 [US3] Extender `apps/api/tests/integration/test_export_repositories.py` para asignación de `export_version`, unique `(draft_id,format,export_version)`, intento activo, export/attempt separados, request hash y transiciones de estado.
- [X] T101 [US3] Crear `apps/api/src/legal_ai/application/export_service.py` con la fase de validación de draft finalizado/revisión aprobada, formato DOCX/PDF, actor, key y request hash, replay/conflicto/active y asignación segura de `export_version`.
- [X] T102 [US3] Implementar en `apps/api/src/legal_ai/application/export_service.py` Tx1 que inserte `DocumentExport=PENDING` y `ExportAttempt=PENDING`, cambie en esa misma transacción a `GENERATING`/`PROCESSING`, cierre la transacción y exponga una operación de procesamiento framework-agnostic; programar ese callable desde `apps/api/src/legal_ai/api/routes/exports.py` mediante `BackgroundTasks` local, sin importar FastAPI en la capa de aplicación y sin convertirlo en cola durable; renderizar únicamente fuera de PostgreSQL y delegar DOCX/PDF a un proceso hijo `spawn` por operación.
- [X] T103 [US3] Implementar en `apps/api/src/legal_ai/application/export_service.py` el render desde el snapshot final, preparando únicamente datos serializables y un temporal seguro para el hijo, aplicando los timeouts 30/60 s y la secuencia terminación→gracia→`kill`→`join`; después validar tamaño/extensión/MIME/estructura/SHA-256, eliminar temporales ante fallo y ejecutar rename atómico solo si el proceso terminó dentro del deadline.
- [X] T104 [US3] Implementar en `apps/api/src/legal_ai/application/export_service.py` Tx2 (única segunda transacción) que marque export GENERATED, attempt SUCCEEDED y versión anterior SUPERSEDED solo tras éxito; ante fallo de generación, timeout o validación usar Tx2 para dejar export y attempt FAILED con error sanitizado, registrar `GENERATION_TIMEOUT` en timeout, no publicar artefactos vencidos y, si Tx2 no puede confirmar tras el rename, compensar el archivo sin abrir una tercera transacción y dejar la incidencia para reconcile.
- [X] T105 [US3] Extender `apps/api/src/legal_ai/api/routes/exports.py` con `POST /api/v1/drafts/{draft_id}/exports`, body `{draft_version, format, exported_by}` header obligatorio, respuesta inicial 202 con export `GENERATING` y attempt `PROCESSING` y replay 200 sin exponer storage_path.
- [X] T106 [US3] Extender `apps/api/src/legal_ai/api/router.py` para registrar `exports.py` sin modificar rutas de 001–003.
- [X] T107 [US3] Crear `apps/api/tests/contract/test_exports_endpoints.py` para creación DOCX/PDF, rechazo HTML/formatos desconocidos, key ausente/inválida, actor inválido, draft no finalizado, respuesta 202, fallo posterior consultable como FAILED, replay 200, fallo síncrono previo a aceptación y todos los errores de creación.
- [X] T108 [US3] Crear `apps/api/tests/integration/test_export_pipeline.py` para flujo feliz completo, exactamente dos transacciones cortas, ausencia de sesión durante render, proceso hijo `spawn` por operación, archivo confirmado solo después de Tx2, hash/metadata, FAILED histórico y compensación Tx2/rename/storage.
- [X] T109 [US3] Extender `apps/api/tests/integration/test_export_pipeline.py` con dos solicitudes concurrentes, una sola generación activa, versionado sin colisión, traducción de `IntegrityError`, timeout que termina/gracia/`kill`/`join` sin zombis, fallo posterior a 202 consultable como FAILED, ningún artefacto vencido descargable y conservación del estado anterior ante fallo.

## Phase 11: US4 — Consulta, auditoría y descarga

**Purpose**: exponer metadata e intentos paginados y descargar solo artefactos
válidos `GENERATED`/`SUPERSEDED` con integridad comprobada.

- [X] T110 [US4] Extender `apps/api/src/legal_ai/application/export_service.py` con listados por draft, get por export y filtros de formato/status/draft_version/export_version, orden estable y paginación `page/page_size` máxima 100 sin storage_path.
- [X] T111 [US4] Extender `apps/api/src/legal_ai/api/routes/exports.py` con `GET /api/v1/drafts/{draft_id}/exports` y `GET /api/v1/exports/{export_id}`, incluyendo filtros, orden/paginación, metadata permitida, errores y request ID.
- [X] T112 [US4] Crear `apps/api/tests/contract/test_exports_endpoints.py` para list/get, filtros AND, page_size inválido, orden estable, estados, hash/renderer/actor/timestamps y exclusión de snapshot, rutas y errores internos.
- [X] T113 [US4] Extender `apps/api/src/legal_ai/application/export_service.py` con consulta paginada de attempts y sanitización de `error_message`, excluyendo stack traces, secrets, storage_path y contenido documental.
- [X] T114 [US4] Extender `apps/api/src/legal_ai/api/routes/exports.py` con `GET /api/v1/exports/{export_id}/attempts`, paginación uniforme y respuesta de auditoría sin campos sensibles.
- [X] T115 [US4] Extender `apps/api/tests/contract/test_exports_endpoints.py` con intentos ordenados, attempt_number, historial FAILED, sanitización, page_size máximo y `EXPORT_NOT_FOUND`.
- [X] T116 [US4] Implementar en `apps/api/src/legal_ai/application/export_service.py` descarga validando estado descargable, ruta canónica, extensión/MIME/estructura y SHA-256 justo antes de iniciar el streaming, registrando evento de integridad bloqueada con respuesta única `EXPORT_FILE_CORRUPTED` sin mutar el status.
- [X] T117 [US4] Extender `apps/api/src/legal_ai/api/routes/exports.py` con `GET /api/v1/exports/{export_id}/download`, streaming binario, `Content-Type`, `Content-Disposition: attachment`, `Content-Length`, ETag SHA-256, `Cache-Control: private, no-store`, `If-None-Match`, `Accept-Ranges: none` y rechazo temprano de cualquier header `Range` con `416 RANGE_NOT_SUPPORTED`, sin abrir/leer el archivo ni iniciar streaming.
- [X] T118 [US4] Crear `apps/api/tests/contract/test_download_endpoints.py` para GENERATED/SUPERSEDED, 304 condicional si corresponde, headers, streaming, `Accept-Ranges: none`, Range rechazado con `416` antes de `If-None-Match`, envelope público de 003 con `request_id`/`timestamp`, ausencia de `Content-Range` y de lectura del archivo, missing 410, corrupt/hash/MIME/truncado/vacío como `EXPORT_FILE_CORRUPTED` 409 y no exposición de path/contenido en errores.
- [X] T119 [US4] Crear `apps/api/tests/integration/test_download_endpoints.py` para path traversal/symlink antes de respuesta, hash recalculado, archivo faltante, corrupción DOCX/PDF, evento auditado, permisos y no transición automática a FAILED.
- [X] T120 [US4] Extender `apps/api/tests/unit/test_export_service.py` con paginación/orden estable, selección de estados descargables, validación previa al stream y rechazo de metadata sensible; no se agregan mutaciones a lecturas.

## Phase 12: US5 — Retry de exportaciones FAILED

**Purpose**: reintentar el mismo artefacto lógico conservando su historial y
creando un `ExportAttempt` nuevo por cada procesamiento.

- [X] T121 [US5] Extender `apps/api/src/legal_ai/application/export_service.py` con `retry_failed`: exigir export FAILED, validar actor/payload contra la solicitud inicial, conservar la misma `Idempotency-Key` y `request_hash`, crear un attempt incremental en el mismo `DocumentExport`, impedir otra active y aplicar semántica retry posterior a fallo.
- [X] T122 [US5] Implementar en `apps/api/src/legal_ai/application/export_service.py` el pipeline de retry FAILED→GENERATING/PROCESSING→GENERATED/FAILED en Tx1/Tx2, preservando todos los attempts FAILED, realizando Tx1/Tx2/compensación, ejecutando el renderer en un proceso hijo `spawn` nuevo por operación y evitando crear otro export.
- [X] T123 [US5] Extender `apps/api/src/legal_ai/api/routes/exports.py` con `POST /api/v1/exports/{export_id}/retry`, body `{"exported_by":"..."}`, `Idempotency-Key` obligatorio, status 202, replay 200 y metadata FAILED sin crear attempt desde creación y errores de transición/active/conflict.
- [X] T124 [US5] Extender `apps/api/tests/unit/test_export_service.py` y `apps/api/tests/unit/test_export_idempotency.py` con retry válido, intento activo, reintentos sucesivos tras fallo, attempt_number, key/hash, replay, payload conflict, active, export no FAILED, éxito y fallo.
- [X] T125 [US5] Extender `apps/api/tests/contract/test_exports_endpoints.py` con respuesta 202/replay 200, metadata FAILED y error del endpoint retry, mismo export id, nuevo attempt id, request ID y fields sensibles ausentes.
- [X] T126 [US5] Extender `apps/api/tests/integration/test_export_pipeline.py` para varios retries sucesivos, attempts FAILED conservados, concurrencia/índice partial, rollback y descarga solo después de GENERATED.

## Phase 13: US5 — Regeneración desde final_snapshot

**Purpose**: producir una nueva versión del mismo formato sin depender del
archivo origen, y superseder el artefacto anterior solo después del éxito.

- [X] T127 [US5] Extender `apps/api/src/legal_ai/application/export_service.py` con regeneración solo desde `GENERATED`/`SUPERSEDED`, lectura exclusiva de `final_snapshot`, validación de `expected_version == max(export_version)`, formato heredado y `parent_export_id`.
- [X] T128 [US5] Implementar en `apps/api/src/legal_ai/application/export_service.py` la asignación `max(export_version)+1`, nuevo export/attempt/path/SHA-256, ejecución de dos transacciones, renderer en un proceso hijo `spawn` nuevo por operación y supersede posterior al éxito, preservando el origen SUPERSEDED y el artefacto anterior ante fallo.
- [X] T129 [US5] Extender `apps/api/src/legal_ai/api/routes/exports.py` con `POST /api/v1/exports/{export_id}/regenerate`, body `{expected_version, exported_by}`, header obligatorio y status 202 con export `GENERATING` y attempt `PROCESSING` o replay 200.
- [X] T130 [US5] Crear `apps/api/tests/unit/test_export_service.py` y `apps/api/tests/unit/test_export_idempotency.py` para origen GENERATED/SUPERSEDED, snapshot inmutable, key/hash, `export_version` stale, parent, formato, replay/conflict/active y fallo aislado.
- [X] T131 [US5] Extender `apps/api/tests/contract/test_exports_endpoints.py` con regeneración, `CONCURRENT_MODIFICATION`, `INVALID_EXPORT_TRANSITION`, actor/key inválidos, respuesta 202/200 y metadata sin path.
- [X] T132 [US5] Crear `apps/api/tests/integration/test_export_pipeline.py` para regenerar origen sin archivo, origen corrupto, archivo previo descargable hasta el éxito, superseded posterior, max(export_version)+1, carreras de versión y fallo de Tx2/compensación.

## Phase 14: US6 — Reconciliación administrativa y cleanup manual

**Purpose**: detectar y, solo con `--execute`, limpiar temporales/huérfanos o
attempts expirados con auditoría, dry-run e idempotencia por `run_id`.

- [X] T133 [US6] Crear primero `apps/api/tests/unit/test_reconcile_service.py` con normalización de filtros, cálculo de `filters_hash`, incidentes, umbrales 24h/7d/180d, dry-run, exclusions y resultados JSON.
- [X] T134 [US6] Crear `apps/api/src/legal_ai/application/reconcile_service.py` para detectar TEMPORARY_FILE, ORPHAN_FILE, FAILED_ATTEMPT, MISSING_FILE, CORRUPT_FILE e INCOMPLETE_DB, aplicar filtros AND, persistir en el primer hallazgo de cada huérfano un evento `ORPHAN_DETECTED` con fingerprint opaco y usar su `created_at` para el umbral de 7 días, produciendo candidatos sin eliminar por defecto.
- [X] T135 [US6] Implementar en `apps/api/src/legal_ai/application/reconcile_service.py` `--execute`, retención indefinida de GENERATED/SUPERSEDED y metadata de exports fallidos, exclusión del último GENERATED válido, del attempt con mayor `attempt_number` por export y de PROCESSING activo, omisión de registros sin archivo/corruptos, eliminación compensable de temporales/huérfanos/attempts FAILED elegibles y auditoría de actor/timestamp/recurso/acción/resultado.
- [X] T136 [US6] Implementar en `apps/api/src/legal_ai/application/reconcile_service.py` idempotencia concurrente por `run_id` usando el índice único parcial de `RECONCILIATION_RUN`: mismo run+hash devuelve exactamente el resumen guardado; filtros/actor/modo distintos devuelven `CLEANUP_CONFLICT` sin repetir eliminaciones.
- [X] T137 [US6] Crear `apps/api/src/legal_ai/cli.py` con `document-exports reconcile [--actor] [--run-id] [--execute] [--case-file-id] [--draft-id] [--format] [--incident-type] [--older-than]`, salida JSON contractual, validación de actor y códigos 0/2/3/4.
- [X] T138 [P] [US6] Crear `apps/api/tests/contract/test_admin_reconcile_cli.py` para sintaxis, actor obligatorio, filtros, dry-run por defecto, `--execute`, run-id replay/conflict, JSON sin paths/PII y códigos de salida.
- [X] T139 [P] [US6] Crear `apps/api/tests/integration/test_reconcile_filesystem.py` para temporales de 24h, persistencia de primera detección y cleanup de huérfanos detectados hace 7d, symlink/path inseguro, execute idempotente y preservación del último GENERATED/PROCESSING.
- [X] T140 [P] [US6] Crear `apps/api/tests/integration/test_reconcile_database.py` para attempts FAILED de 180d, preservación del attempt con mayor `attempt_number`, metadata document_exports fallida, registros sin archivo, corruptos, INCOMPLETE_DB, evento único bajo carreras del mismo `run_id` y conflicto de filtros.
- [X] T141 [US6] Extender `apps/api/tests/unit/test_reconcile_service.py` para que cada candidato se contabilice en `candidates/deleted/omitted/conflicts/errors`, errores individuales no aborten la corrida y no exista endpoint DELETE público.

## Phase 15: Observabilidad, seguridad y salud operativa

**Purpose**: hacer trazable el ciclo completo sin registrar documentos, secretos,
actores fuera del contexto de auditoría ni paths absolutos.

- [X] T142 Extender `apps/api/src/legal_ai/observability/logging.py` con logs estructurados para request/tx1/state_transition/render/validate/rename/tx2/compensation/download_integrity/reconcile usando solo campos permitidos del plan.
- [X] T143 Integrar en `apps/api/src/legal_ai/application/*.py` y `apps/api/src/legal_ai/adapters/database/review_event_repository.py` `request_id`, `run_id`, `draft_id`, `review_id`, `export_id`, `attempt_id`, renderer, duración, tamaño, hashes y códigos en servicios 004 y auditoría, evitando contenido, prompts, secretos, root absoluto y excepciones de librería.
- [X] T144 Verificar en `apps/api/src/legal_ai/adapters/storage/local_artifact_storage.py` y `apps/api/src/legal_ai/adapters/renderers/pdf_renderer.py` que los métodos `health()`/readiness devuelvan solo estado sanitizado de disponibilidad para 004, sin modificar `apps/api/src/legal_ai/api/routes/health.py`, `apps/api/src/legal_ai/application/health_service.py` ni contratos de 001–003.
- [X] T145 Crear `apps/api/tests/unit/test_004_observability.py` para campos obligatorios, request/run correlation, duración/tamaño, fases, errores sanitizados y ausencia de contenido documental, paths absolutos y secretos.
- [X] T146 Crear `apps/api/tests/unit/test_004_security.py` para permisos 0700/0600 donde aplique, symlink/traversal, MIME spoofing, zip bomb, filename determinista sin PII, no exposición HTTP y ausencia de módulos de autenticación/autorización nuevos.
- [X] T147 Crear `apps/api/tests/contract/test_004_health.py` y `apps/api/tests/unit/test_004_health.py` para health/readiness con root no escribible y renderer no disponible; ejecutar además la regresión existente de health de 003 sin modificarla.

## Phase 16: Benchmarks informativos A8

**Purpose**: medir de forma reproducible cinco superficies de 004 sin
convertir sus umbrales en un gate local o de CI estándar.

- [X] T148 Crear `apps/api/tests/fixtures/benchmark_004_dataset.json` con el dataset sintético versionado `004-benchmark-v1`: 100 drafts/reviews, 1.000 comentarios, snapshot canónico de 100 KiB (102.400 bytes), artefactos DOCX/PDF válidos de 1 MiB (1.048.576 bytes) y 1.000 registros/entradas con 100 incidencias para reconcile, sin PII y con hashes deterministas.
- [X] T149 Crear `apps/api/scripts/benchmark_004.py` con el comando documentado, parámetros `--dataset`, `--warmup`, `--iterations`, `--output` y `--baseline` opcional, warm-up 10, 50 iteraciones secuenciales, `time.perf_counter()`, p95 `ceil(0.95 * N)`, entorno/commit/lockfile/dataset, cinco casos y umbrales `<300 ms`, `<2.000 ms`, `<500 ms`, `<1.500 ms` y `<3.000 ms`; la aceptación `202` debe usar fake después de Tx1 y excluir generación DOCX/PDF completa.
- [X] T150 Crear `apps/api/tests/benchmark/test_benchmark_004.py` fuera de `tests/unit` para verificar dataset/hash, cálculo p95, umbrales, JSON de resultados, alerta ante exceso o regresión mayor al 10% y que una alerta informativa no cambie el código de salida exitoso; los errores de infraestructura/medición sí deben fallar el runner.
- [X] T151 Ejecutar `cd apps/api && uv run python scripts/benchmark_004.py --dataset tests/fixtures/benchmark_004_dataset.json --warmup 10 --iterations 50 --output artifacts/benchmarks/004.json` en Docker/Linux de referencia y verificar que los resultados se registran como evidencia informativa sin incorporarse a pytest/CI estándar ni convertirse en gate de release.

## Phase 17: Documentación final

**Purpose**: documentar el uso operativo después de obtener resultados
funcionales y benchmarks reproducibles.

- [X] T152 Crear `README.md` en la raíz solo para documentar el incremento implementado: endpoints 004, límites, preview HTML no persistido, DOCX/PDF exportables, storage local, retención, `document-exports reconcile`, dry-run/execute y restricciones operativas, enlazando al quickstart sin incluir secretos.
- [X] T153 Actualizar `specs/004-document-review-and-export/quickstart.md` únicamente si la implementación introduce diferencias necesarias en comandos, rutas, variables, native dependencies de WeasyPrint o ejemplos de CLI; justificar cada cambio y conservar las decisiones cerradas.
- [X] T154 Verificar que `apps/api/pyproject.toml`, `apps/api/Dockerfile`, `compose.yaml` y `.env.example` documenten python-docx/WeasyPrint, Pango, volumen writable, límites binarios exactos/timeouts/retenciones, proceso hijo `spawn`/cleanup y que no exista dependencia de LibreOffice real para la suite normal.
- [X] T155 Actualizar `specs/004-document-review-and-export/quickstart.md` y `README.md` con el comando de benchmarks, dataset, entorno de referencia, protocolo, umbrales, formato JSON, alerta no bloqueante y regla de no medir generación completa dentro de `202`.

## Phase 18: Validación final

**Purpose**: ejecutar todos los checkpoints después de benchmarks y
documentación, sin marcar tareas como completadas hasta contar con evidencia.

- [X] T156 Ejecutar Ruff sobre `apps/api/src`, `apps/api/tests` y revisar/importar el entry point de `apps/api/pyproject.toml`, corrigiendo únicamente problemas del incremento 004.
- [X] T157 Ejecutar `mypy apps/api/src/legal_ai` como gate obligatorio de aceptación de 004, verificando protocolos de render/storage, schemas, repositorios y compatibilidad de tipos con 003. El comando `mypy apps/api/src/legal_ai apps/api/tests` queda únicamente como diagnóstico informativo: sus errores preexistentes en tests son deuda técnica heredada, no se declaran resueltos, no se ocultan con ignores globales y quedan fuera del alcance de 004.
- [X] T158 Ejecutar la suite unitaria, integración y contractual con cobertura configurada en `apps/api/pytest.ini`/`apps/api/pyproject.toml`, incluyendo tests reales de WeasyPrint solo en el entorno Linux/Docker que los soporte y manteniendo cobertura mínima existente.
- [X] T159 Ejecutar upgrade/downgrade de `apps/api/alembic/versions/004_document_review_and_export.py` desde una base en estado 003 y validar que los tests de migración/constraints pasan en PostgreSQL 16.
- [X] T160 Ejecutar `docker build` de `apps/api/Dockerfile`, `docker compose config --quiet` y un smoke con `compose.yaml` que verifique health, preview HTML por `GET /api/v1/drafts/{draft_id}/preview?draft_version={n}`, creación y descarga DOCX y creación y descarga PDF; HTML no se persiste ni descarga, y no se levantan Redis, scheduler, cola ni servicio cloud.
- [X] T161 Ejecutar `git diff --check` sobre el repositorio y revisar que todas las líneas de `specs/004-document-review-and-export/tasks.md` siguen el formato de checklist y no contienen identificadores duplicados.
- [X] T162 Verificar con `git diff --name-only` y `git status --short` que no se modificaron `specs/001-*`, `specs/002-*`, ningún artefacto de 003, revisiones Alembic 001–003, `.specify/memory/constitution.md` ni `.specify/memory/principles.md`.
- [X] T163 Confirmar mediante el estado de Git en `C:\Users\Uriel Sabugo\Desktop\GitHub\legal-AI-infraestructure` que no se creó ningún `tasks.md` nuevo fuera de `specs/004-document-review-and-export/tasks.md`, sin contar los artefactos de 003 ya existentes, y que no se implementó código durante la planificación ni se creó ningún commit.

## Dependencias y orden de ejecución

### Grafo de dependencias crítico

1. T001–T009 preparan runtime, lockfile, contenedor y configuración.
2. T010–T024 fijan enums, dominio, ORM, migración, constraints y fixtures.
3. T025–T050 fijan puertos, repositorios, UoW, schemas, errores y headers.
4. T051–T061 implementan US1; T062–T073 implementan finalización US2; T074–T079 implementan preview US2.
5. T080–T097 habilitan storage, integridad y renderers de US3.
6. T098–T109 implementan exportación inicial US3; solo después T110–T120 implementan consulta/descarga US4.
7. T121–T132 implementan retry y regeneración US5 después de la exportación inicial.
8. T133–T141 implementan reconciliación US6 después de storage, modelos e integridad.
9. T142–T147 consolidan observabilidad/seguridad; T148–T151 ejecutan benchmarks informativos; T152–T155 cierran documentación; T156–T163 ejecutan la validación final.

### Reglas de bloqueo

- Ningún repository usa modelos antes de T018/T019 ni se integra al UoW antes de T038.
- Ninguna route se registra antes de sus schemas, errores, servicio y pruebas contractuales correspondientes.
- Preview y PDF usan la salida de T074; DOCX/PDF y exportación usan storage/integridad de T080–T091 y renderers de T092–T097.
- Retry/regeneración esperan el pipeline inicial y metadata/listados; reconcile espera storage, integridad, exports/attempts y eventos.
- Las tareas que editan `routes/drafts.py`, `routes/exports.py`, `api/router.py`, `export_service.py`, `review_service.py`, `models.py` o una migración no se ejecutan en paralelo entre sí.
- No se agrega un límite funcional de versiones; la única protección de concurrencia es optimistic locking, constraints/índices parciales y transacciones cortas.

## Oportunidades de paralelismo seguras

- T012–T017 pueden ejecutarse en paralelo después de T010/T011 porque cada entidad nueva usa un archivo de dominio distinto.
- T025–T032 pueden ejecutarse en paralelo porque cada puerto es un archivo nuevo independiente.
- T033–T037 pueden paralelizarse por repository después de T018/T025–T029, sin editar el mismo archivo.
- T040–T044 pueden paralelizarse después de T039 si cada schema mantiene su archivo; T045–T047 deben esperar el contrato de schemas/errores.
- T083, T089, T095 y T096 pueden dividirse por archivo/test y entorno después de sus implementaciones, sin compartir fixtures mutables.
- T138–T140 pueden ejecutarse en paralelo tras T133–T137 porque separan CLI, filesystem y DB, siempre que no modifiquen el mismo fixture.
- T156–T157 pueden ejecutarse en paralelo únicamente en modo diagnóstico; si requieren correcciones, deben serializarse para evitar editar los mismos archivos. T158–T160 deben ejecutarse después de resolver fallos de tipos/dependencias del runtime.

## Estrategia de implementación

- **MVP recomendado**: completar T001–T109 para obtener revisión humana, finalización write-once, preview HTML, storage, integridad, renderers y creación DOCX/PDF. No incluye retry/regeneración/reconcile hasta sus fases posteriores.
- **Criterio por historia**: una historia solo se considera lista cuando sus unit tests, tests de integración, tests contract/API y escenarios de error/concurrencia/idempotencia aplicables pasan.
- **Renderers**: la suite normal usa fakes deterministas; WeasyPrint/python-docx reales se verifican en el test opcional Linux/Docker, sin LibreOffice.
- **Filesystem/DB**: ningún archivo es descargable antes de la confirmación Tx2; los fallos conservan auditoría y se resuelven mediante compensación/reconciliación manual.

## Trazabilidad

| Historia | Tareas principales | Endpoints | Modelos/puertos | Tests principales |
|---|---|---|---|---|
| US1 — Revisión humana | T051–T061 | current/create review, comment, patch comment, submit, approve, request-changes, history | `DocumentReview`, `ReviewComment`, `ReviewEvent`; T025–T027, T033–T035 | `test_review_state_machine.py`, `test_review_service.py`, `test_review_repositories.py`, `test_reviews_endpoints.py`, T060–T061 |
| US2 — Finalización y preview | T062–T079 | finalize, preview | `DocumentDraft.final_*`, `CanonicalDocument`; T039–T046, T062–T077 | `test_canonical_document.py`, `test_finalization_service.py`, `test_finalization_preview_endpoints.py`, T070/T073/T079 |
| US3 — Exportación inicial | T080–T109 | create export | `DocumentExport`, `ExportAttempt`; storage/integrity/renderer ports T029–T032; proceso hijo `spawn` | `test_local_artifact_storage.py`, `test_artifact_integrity.py`, `test_renderers.py`, `test_export_idempotency.py`, `test_export_pipeline.py` |
| US4 — Consulta y descarga | T110–T120 | list exports, get export, download, attempts | export read/download services and schemas | `test_exports_endpoints.py`, `test_download_endpoints.py`, `test_export_service.py`, integration download |
| US5 — Retry y regeneración | T121–T132 | retry, regenerate | `ExportAttempt`, `parent_export_id`, `export_version`/active constraints | idempotency/service/pipeline/contract tests T124–T132 |
| US6 — Reconciliación | T133–T141 | `document-exports reconcile` (CLI administrativo; sin DELETE HTTP) | reconcile service, `ReviewEvent` audit, storage/integrity | `test_reconcile_service.py`, CLI contract, filesystem/DB integration |

| A8 — Benchmarks informativos | T148–T151 | comando separado, dataset, resultados y alertas | `benchmark_004.py`, fixture versionado | `test_benchmark_004.py`, ejecución Docker/Linux documentada |
| A9 — Aislamiento de timeout | T032, T092–T096, T099, T102–T104, T108–T109 | proceso hijo por operación, terminación/gracia/`kill`/`join`, cleanup y `GENERATION_TIMEOUT` | puertos reemplazables, orquestación fuera de Tx1/Tx2 | unit/integration renderer y pipeline sin zombis ni publicación vencida |
| A10 — Range en descarga | T117–T120 | `416 RANGE_NOT_SUPPORTED`, envelope público de 003, `request_id`, `timestamp`, `Accept-Ranges: none`, rechazo antes de file access | ruta de descarga | tests contract/API sin streaming, lectura completa ni `Content-Range` |

### Conteo actualizado por fase

| Fase | Rango | Cantidad |
|---:|---|---:|
| 1 | T001–T009 | 9 |
| 2 | T010–T024 | 15 |
| 3 | T025–T050 | 26 |
| 4 | T051–T061 | 11 |
| 5 | T062–T073 | 12 |
| 6 | T074–T079 | 6 |
| 7 | T080–T085 | 6 |
| 8 | T086–T091 | 6 |
| 9 | T092–T097 | 6 |
| 10 | T098–T109 | 12 |
| 11 | T110–T120 | 11 |
| 12 | T121–T126 | 6 |
| 13 | T127–T132 | 6 |
| 14 | T133–T141 | 9 |
| 15 | T142–T147 | 6 |
| 16 — benchmarks | T148–T151 | 4 |
| 17 — documentación | T152–T155 | 4 |
| 18 — validación final | T156–T163 | 8 |
| **Total** | **T001–T163** | **163** |

### Trazabilidad por requisito funcional

Los rangos siguientes son una cobertura semántica y pueden repetirse cuando
un requisito es transversal; los tests indicados en cada bloque verifican el
contrato correspondiente.

| Requisitos de `spec.md` | Tareas de implementación y tests |
|---|---|
| FR-001–FR-017 | T025–T027, T033–T061 (review, comentarios, locking, auditoría e idempotencia de review) |
| FR-018–FR-018.1 | T074–T079 (HTML canónico, preview, sanitización, ETag y ausencia de efectos) |
| FR-019–FR-030.1 | T071–T073, T076, T080–T109 (elegibilidad, edición limitada, formatos, pipeline, storage, integridad, renderers, límites y timeouts) |
| FR-031–FR-035.2 | T039–T050, T110–T120, T142–T147 (errores, request ID, schemas, metadata, descarga, seguridad y observabilidad) |
| FR-036 | T019–T024 (migración, rollback, constraints y compatibilidad con 003) |
| FR-037–FR-037.2 | T062–T073 (finalización write-once, snapshot, hash, replay y bloqueo posterior) |
| FR-038–FR-038.2 | T080–T091, T110–T119 (storage relativo, path safety, atomicidad e integridad al descargar) |
| FR-039–FR-039.5 | T098–T141 (pipeline, compensación, retry, regeneración, retención y reconcile) |

### Catálogo HTTP cubierto

- Review: `GET /api/v1/drafts/{draft_id}/reviews/current`, `POST /api/v1/drafts/{draft_id}/reviews`, `POST /api/v1/reviews/{review_id}/comments`, `PATCH /api/v1/reviews/{review_id}/comments/{comment_id}`, `POST /api/v1/reviews/{review_id}/submit`, `POST /api/v1/reviews/{review_id}/approve`, `POST /api/v1/reviews/{review_id}/request-changes`, `GET /api/v1/reviews/{review_id}/history` — T057/T059.
- Finalización/preview: `POST /api/v1/drafts/{draft_id}/finalize`, `GET /api/v1/drafts/{draft_id}/preview` — T068/T077/T069/T078.
- Exports: `POST /api/v1/drafts/{draft_id}/exports`, `GET /api/v1/drafts/{draft_id}/exports`, `GET /api/v1/exports/{export_id}`, `GET /api/v1/exports/{export_id}/download`, `POST /api/v1/exports/{export_id}/retry`, `POST /api/v1/exports/{export_id}/regenerate`, `GET /api/v1/exports/{export_id}/attempts` — T105/T111/T114/T117/T123/T129 y sus tests.
- No se crea endpoint `DELETE`; cleanup es exclusivamente CLI manual.

## Validación de formato de tasks.md

- 163 identificadores secuenciales, todas las tareas marcadas `[X]`, sin tareas pendientes ni identificadores duplicados.
- Cada tarea incluye al menos una ruta concreta; las rutas compartidas se serializan para impedir conflictos.
- `[P]` solo se usa para archivos distintos sin dependencia mutua; las modificaciones sucesivas del mismo router/service/migración no se marcan paralelas.
- Cada historia incluye implementación, unit tests, integración, API/CLI y errores/concurrencia o idempotencia aplicables.
- Migración upgrade/downgrade, configuración, Docker/Compose, storage, integridad, seguridad, observabilidad, documentación, benchmarks informativos, aislamiento de timeout, rechazo Range y validación final están cubiertos.
- La implementación y las validaciones finales están completadas; este cierre solo registra el estado documental, no modifica el comportamiento de runtime y no crea commit.

## Veredicto

**READY_FOR_REANALYSIS** — T001–T163 son continuas, únicas y están marcadas `[X]`; la implementación y las validaciones finales fueron ejecutadas. T157 usa `mypy apps/api/src/legal_ai` como gate obligatorio; `mypy apps/api/src/legal_ai apps/api/tests` queda documentado como diagnóstico informativo con deuda técnica heredada en tests. Queda pendiente únicamente el reanálisis posterior a estas correcciones documentales.
