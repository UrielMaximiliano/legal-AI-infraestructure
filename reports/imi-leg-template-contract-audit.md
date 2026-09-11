# Auditoría read-only — Contrato único de plantillas IMI LEG

> Scope: worker supervisado `task_738b8744266f / ctx_2872cf7b49de`. Solo lectura en repos exactos, sin tocar código ni contratos compartidos. Único archivo creado en este worktree hijo: `reports/imi-leg-template-contract-audit.md`.

- Fecha (UTC): 2026-09-11
- Worktree hijo: `C:/Users/Uriel Sabugo/orca/workspaces/legal-AI-infraestructure/imi-leg-contract-audit-opencode` @ `1201caf` (`UrielMaximiliano/imi-leg-contract-audit-opencode`, `origin=https://github.com/UrielMaximiliano/legal-AI-infraestructure.git`, `git status --short` limpio antes del informe)
- Repo A frontend/BFF: `C:/Users/Uriel Sabugo/Desktop/GitHub/gestor-expedientes-imi` @ `15a734262169616886f945bd132a0628703f1225` (`15a7342 fix(web): corrige accesibilidad del campo fecha`)
- Repo B backend: `C:/Users/Uriel Sabugo/Desktop/GitHub/legal-AI-infraestructure` @ `c3a96ba4ef9c737b3d21b2a9b4b29e60d` (`c3a96ba fix(api): avoid converting legal references to fields`)
- Método: inspección estática read-only (`read`/`glob`/`grep` + `git log/rev-parse/status`), sin migraciones, sin escritura en repos auditados, sin push/despliegue.

---

## 1. Requests frontend (gestor-expedientes-imi)

### 1.1 Capa de transporte BFF

`src/lib/legal-ai-client.ts:72-190` (`forwardLegalAiRequest`, `server-only`):

- Requiere sesión Better-Auth (`getRequestSession`): `401 {code:UNAUTHENTICATED}` si falta.
- Requiere `LEGAL_AI_BASE_URL` + `LEGAL_AI_SERVICE_TOKEN`, si no `503 LEGAL_AI_CONFIGURATION_MISSING`.
- Destino canónico: `api/v1/{safePath}` con `TRAILING_SLASH_PATHS={'employees','case-files'}` (`legal-ai-client.ts:25,83-88`).
- Forward query-string intacto, `Accept` passthrough, `Authorization: Bearer <service-token>`.
- `X-Actor: session.user.username || email || name` (`legal-ai-client.ts:93-94`).
- `X-Request-ID` passthrough o `crypto.randomUUID()`; propaga `Idempotency-Key`, `Range`, `If-None-Match`.
- Reescritura de actores: `ACTOR_FIELDS={opened_by,submitted_by,decided_by,finalized_by,exported_by,author,resolved_by,actor,changed_by}` → valor de sesión (`legal-ai-client.ts:5-15,46-54`). Riesgo: el backend confía en `X-Actor`/body como auditoría, no como identidad verificada.
- Multipart: reconstruye `request.formData()` para regenerar boundary (`legal-ai-client.ts:106-112`).
- Timeout `LEGAL_AI_REQUEST_TIMEOUT_MS` default `360_000` ms con `AbortController`; mapea a `504 LEGAL_AI_REQUEST_TIMEOUT` o `503 LEGAL_AI_UNAVAILABLE`, `retryable:true` (`legal-ai-client.ts:24,120-144`).
- Streaming passthrough (`upstream.ok||304`): preserva headers + `X-Request-ID`, `Cache-Control:no-store` + `X-Accel-Buffering:no` para `text/event-stream`; bridge `ReadableStream` con limpieza de timeout (`legal-ai-client.ts:146-183`).
- Errores normalizados a `{code,message,requestId,details,retryable}` vía `normalizedError()`; `retryable = 408/425/429/5xx` (`legal-ai-client.ts:56-70`).
- Proxy Next: `src/app/api/legal-ai/[...path]/route.ts` delega todo a `forwardLegalAiRequest`; `src/app/api/disposiciones/docx/route.ts:52` genera DOCX local (no backend); `src/app/api/digestos/*` es dominio separado (SQLite local, no IMI Core).

### 1.2 Cliente tipado

`src/services/disposiciones.service.ts:58-101` (`request<T>`):

- `GET/HEAD`: `cache:no-store`, `Accept:application/json`, reintento `maxAttempts=3` con backoff `attempt*200ms`; solo reintenta excepciones de red o `status>=500`. `POST/PATCH/DELETE`: 1 intento.
- Error → `LegalApiError {code,message,requestId,details,retryable}`.

| Función frontend | Método + path BFF (`/api/legal-ai/...`) | Body / query | `Idempotency-Key` |
|---|---|---|---|
| `getAll(query,documentType)` | `GET drafts?page=1&page_size=100&query&document_type` | — | no |
| `getById/getDocument` | `GET drafts/{id}`, `GET drafts/{id}/document` | — | no |
| `getTemplates(documentType)` | `GET templates?skip=0&limit=100&status=PUBLISHED&document_type?` | — | no |
| `listManagedTemplates` | `GET templates?skip=0&limit=100&search?&document_type?&status?` | — | no |
| `getTemplate/listTemplateVersions` | `GET templates/{id}`, `GET templates/{id}/versions` | — | no |
| `createTemplate` | `POST templates` | `{name,document_type,organ_emisor?,normativa?,description?,body_template,fields,rules,instructions?,blocks?,revision?,variables:=fields[].key}` | sí (caller) |
| `createTemplateVersion` | `POST templates/{tid}/versions` | `{body_template,fields,rules,instructions?,blocks?,revision?,variables}` | sí |
| `updateTemplateVersion` | `PATCH templates/{tid}/versions/{vid}` | `{...same, revision}` | sí |
| `publishTemplateVersion` | `POST templates/{tid}/versions/{vid}/publish` | `{revision, confirm_warnings?}` | sí |
| `deactivateTemplate` | `POST templates/{id}/deactivate` | `{}` | sí |
| `startTemplateImport(file,meta)` | `POST template-imports` (multipart) | `FormData{file,name,document_type}` | sí |
| `getTemplateImport/retry/cancel` | `GET template-imports/{id}`, `POST .../retry`, `POST .../cancel` | — / — | no / sí / sí |
| `analyzeTemplate/getTemplateAnalysis` | `POST template-analyses`, `GET template-analyses/{id}` | `{body_template,fields,document_type}` | sí / no |
| `previewTemplate` | `POST template-previews` | `{document_type,name,body_template,fields,rules,values}` | **no** |
| `getCaseFiles/createCaseFile` | `GET case-files?page=1&page_size=100...`, `POST case-files` | `case_number,employee_id?,title,case_type,description?` | no |
| `createManual` | `POST drafts` | `{template_id,template_version_id?,case_file_id,variables,document}` | sí |
| `rewriteConcept` | `POST rag/text/rewrite` | `{template_id,text,retrieval:{top_k:8,minimum_score:0,language:'es',organization:'IMI'}}` | sí (sessionStorage por template) |
| `updateDocument` | `PATCH drafts/{id}/document` | `{expected_version,document}` | sí |
| `createReview/submit/approve/requestChanges` | `POST drafts/{id}/reviews`, `POST reviews/{id}/submit|approve|request-changes` | `{draft_version,expected_version,opened_by:'session'}` etc.; approve añade `human_review_confirmed:true` | sí |
| `finalize` | `POST drafts/{id}/finalize` | `{expected_version,finalized_by:'session',official_number,issued_on}` | sí |
| `createExport/getExport/downloadUrl` | `POST drafts/{id}/exports`, `GET exports/{id}`, `GET /api/legal-ai/exports/{id}/download` | `{draft_version,format,exported_by:'session'}` | sí / no / no |

`src/services/generation.service.ts:85-137` (`streamGeneration`):

- `POST /api/legal-ai/rag/drafts/generate/stream`, `Accept:text/event-stream`, `Idempotency-Key` por fingerprint `FNV-1a(template_version_id,document_type,variables ordenadas)` persistido en `sessionStorage` (`generation.service.ts:53-83`).
- Payload incluye `retrieval:{top_k:8,minimum_score:0,language:'es',organization:'IMI'}` (duplicado con `rewriteConcept`).
- Eventos SSE `started|progress|complete|error|cancelled`; tolera `result` vs `{draft,structured_draft}` (`generation.service.ts:18-33`); limpia la clave solo en terminal; `cancelGeneration` → `DELETE /api/legal-ai/rag/runs/{ragRunId}`.

Tipos: `src/lib/legal-ai-types.ts:1-206` (`DocumentType`, `LegalDocument schema_version:1`, `DraftSummary`, `DraftDocumentResponse`, `Template`, `Review`, `ExportItem`, `Paginated`, `ApiError`, `RagTextRewriteResponse`, `emptyLegalDocument()`); `src/lib/template-types.ts:1-143` (`TemplateFieldType`, `TemplateRule`, `TemplateBlock`, `TemplateStatus DRAFT|PUBLISHED|INACTIVE|ARCHIVED`, `TemplateCandidate`, `TemplateVersionDraft`, `TemplateImportJob {status QUEUED|RUNNING|SUCCEEDED|FAILED|CANCELLED, stage uploading|extracting|ocr|analyzing|complete}`, `TemplateAnalysisJob`).

Validación/preview local espejo del backend: `src/lib/template-utils.ts:184-415` (`normalizeNumber` es-AR, `resolveTemplateValues` derived `amount_words|year_from_date`, `validateTemplateValues`, `validateTemplateDraft`, `isValidCuit` con checksum, `extractTemplateCandidates` con inferencia `cuit|email|date|currency|number`).

---

## 2. Endpoints / schemas / modelos / migraciones backend

### 2.1 Router plantillas

`apps/api/src/legal_ai/api/routes/templates.py:55-667`, prefijo `/api/v1/templates` + `template_jobs_router`:

- `POST /api/v1/templates` → `201` si creado, `200` si replay idempotente. Perfil `imi_leg_06b` → `ImiCoreUnitOfWork.create_template(...)` con `request_hash=sha256(json sorted)`; si no, legacy `TemplateService` (solo `name,document_type,body_template,organ_emisor,normativa,description,variables`).
- `GET /api/v1/templates?document_type&search&status&skip&limit` → `PaginatedResponse` (`page=skip//limit+1`).
- `GET|POST /{template_id}/versions`, `GET|PATCH /{template_id}/versions/{version_id}`, `POST .../publish`, `GET /{template_id}`, `PATCH /{template_id}` (rechazado en IMI con `501 IMI_CORE_WRITE_NOT_IMPLEMENTED`), `POST /{template_id}/deactivate`.
- `POST /api/v1/template-imports` → `202` multipart `file+name+document_type`, límite `20 MiB`, `extract_file_content()` DOCX/PDF, `request_hash(name,document_type,filename,content_type,sha256)`; `GET /{import_id}`, `POST /{import_id}/retry` (relee `source_bytes` persistido), `POST /{import_id}/cancel`.
- `POST /api/v1/template-analyses` → `202` (`suggestions_for_body` + persistencia), `GET /{analysis_id}`.
- `POST /api/v1/template-previews` → `200` síncrono, sin idempotencia, sin persistencia.

### 2.2 Schemas Pydantic

- `schemas/template.py:11-244`: `TemplateFieldType=text|textarea|date|number|currency|boolean|select`; `key ^[A-Za-z_][A-Za-z0-9_.-]*$ 1..100`; `TemplateRule {type:validation|visibility|derived, format:email|cuit, derive:amount_words|year_from_date, min/max_length, min/max_value, conditions[], match:all|any}`; `TemplateBlock {id,type:heading|paragraph|list|separator,content≤20k}`; `CreateTemplateRequest`, `TemplateVersionRequest{revision≥1}`, `PublishTemplateRequest{revision≥1,confirm_warnings=false}`, `TemplateResponse{status,revision,fields,rules,blocks,...}`, `TemplateVersionResponse`, `TemplateImportResponse{status,stage,progress 0..100,pages_total,pages_processed,body_template,blocks,warnings,error,retryable,template_version}`, `TemplatePreviewRequest{values:dict}`, `TemplatePreviewResponse{document,errors,warnings}`.
- `schemas/document.py:19-178`: `DraftParagraph/DraftArticle {text 0..20k, citation_ids: SRC-[0-9]{3} únicas}`; `DraftDocument {schema_version==1, warnings debe contener NO VINCULANTE}`; `LegalDocument{document_type,locale,header,blocks}` + `validate_for_approval()` (`nota_inicio` exige título+párrafos no vacíos; resto exige título+intro+closing+authority+signature+artículos no vacíos); `CreateManualDraftRequest{template_id,template_version_id?,case_file_id,variables,document}`, `UpdateDraftDocumentRequest{expected_version>0,document}`.
- `schemas/draft.py:13-87`, `schemas/review.py:15-68` (`ReviewCreateRequest{draft_version>0,expected_version>0,opened_by}`, `Submit/Approve(human_review_confirmed)/RequestChanges(reason 1..2k)`), `schemas/finalization.py:14-20` (`FinalizeDraftRequest{expected_version>0,finalized_by,official_number 1..999999,issued_on:date}`), `schemas/export.py:15-57` (`CreateExportRequest{draft_version>0,format,exported_by}`), `schemas/validation.py:11-37` (`SAFE_IDEMPOTENCY_KEY ^[A-Za-z0-9._~-]{16,100}$`, `validate_actor 1..100`).
- `schemas/generation.py:13-28` (`GenerationAttemptResponse`), `domain/enums.py:6-140` (estados; ver §4).

### 2.3 Modelos / persistencia IMI Core

`apps/api/src/legal_ai/adapters/database/imi_core.py:131-~1050` (esquema `imi.*`, no `public.document_*` legacy cuando `rag_profile==imi_leg_06b`):

- `document_template_versions{id,template_id,version,body_template,...}` + `template_version_configs{template_version_id,status:DRAFT|PUBLISHED|ARCHIVED,revision,fields_json,rules_json,blocks_json,instructions,organ_emisor,normativa,extraction_warnings,published_at}`.
- `template_import_jobs{id,status,stage,progress,body_template,blocks_json,warnings_json,error,retryable,template_version_id,source_bytes,filename,content_type,...}`; `get_template_import_source()` conserva bytes para `retry`.
- `template_analysis_jobs`, tablas de idempotencia por `(idempotency_key,request_hash)` → `(payload, created:bool)`.
- Drafts manual/documento vía `create_manual_draft/update_document/get_draft/list_drafts` con `context_snapshot/context_hash`, `document_json`, `idempotency_key UQ`.
- Reglas de escritura: `update_template_version` solo si `status==DRAFT`, `payload.revision == row.revision`, `next_revision=row.revision+1`; `publish_template_version` solo `DRAFT→PUBLISHED`, archiva `PUBLISHED` previas del mismo `template_id` a `ARCHIVED`, `ON CONFLICT(template_version_id) DO UPDATE`; replay idempotente retorna `(existing, False)` → `200`.

### 2.4 Migraciones Alembic

`apps/api/alembic/versions/001..010`:

- `001` pgvector; `002` employees/case_files; `003` (`003_templates_drafts_and_generation.py:19-264`) `document_templates(name,document_type,version UQ,organ_emisor,normativa,description,body_template,variables[])`, `designation_data`, `document_drafts(template_id,case_file_id,title,content,status~generado,version,generation_number,context_snapshot,context_hash,variables_used...)`, `draft_transitions`, `generation_attempts(idempotency_key UQ)`.
- `004` review/export (`document_reviews`, comentarios, `document_exports`); `005` corpus/ingesta; `006` embeddings `qwen3:4b halfvec 2560`; `007` auditoría RAG (`rag_runs`, intentos); `008` (`008_structured_documents_and_official_numbering.py:15-126`) `document_type+document_json+idempotency_key UQ` en drafts, `draft_document_versions(draft_id,version UQ,document JSON object,content,content_sha256 ^[0-9a-fA-F]{64}$,source IN(AI_GENERATED,MANUAL,HUMAN_EDIT))`, `official_document_identifiers(draft_id UQ,(document_type,number,year) UQ,number>0,year 1900..2200)`; `009` cancelación RAG/filter policy; `010` metadata oficial draft.
- Divergencia: migraciones versionan `public.*` legacy; el runtime IMI usa esquema `imi.*` (creado fuera de Alembic o por bootstrap de `ImiCoreUnitOfWork`). La auditoría no encontró migración Alembic que cree `imi.document_template_versions/template_version_configs/template_import_jobs`; debe documentarse como deuda de trazabilidad.

---

## 3. Sincronía

| Flujo | Mecanismo | Evidencia | Observación |
|---|---|---|---|
| Generación RAG | SSE `POST rag/drafts/generate/stream`, eventos `started/progress/complete/error/cancelled`, cancel `DELETE rag/runs/{id}` | `generation.service.ts:85-137`, `legal-ai-client.ts:149-183` | Único flujo realmente asíncrono streaming; idempotencia por fingerprint en `sessionStorage` (se pierde al cerrar pestaña). |
| Importación plantilla | Polling `GET template-imports/{id}` cada `1800ms` con `setTimeout` recursivo hasta terminal | `TemplateEditorPage.tsx:286-317` | Sin `Retry-After`/`ETag`/`SSE`; intervalo fijo; rehidrata `body/blocks/candidates/template_version/warnings` en cada tick. |
| Análisis plantilla | Polling análogo `GET template-analyses/{id}` (mismo patrón) | `disposiciones.service.ts:250-252`, `TemplateEditorPage` | `202` inicial + `GET`; sin push. |
| Rewrite concepto | Request/response `POST rag/text/rewrite`, timeout cliente `180s`, `AbortController`, telemetría `imi-leg:rag-rewrite` | `disposiciones.service.ts:303-372` | `Idempotency-Key` por template en `sessionStorage`, se borra en `finally` (reintento genera clave nueva → no deduplica). |
| Lecturas | `GET` con `cache:no-store`, retry `3x` solo red/`5xx` | `disposiciones.service.ts:58-101` | `POST/PATCH` sin retry (correcto para no duplicar sin clave). |
| Finalize/export/review | Síncronos con `Idempotency-Key` obligatorio en backend IMI | `routes/templates.py:67-78`, `routes/drafts.py:161-185` | Bien; falta `Idempotency-Key` en `previewTemplate` (stateless, aceptable) pero inconsistente con el resto de escrituras. |

Riesgo: doble fuente de verdad temporal — SSE para generación vs polling para imports. Unificar bajo el contrato §7 (`estado/resultado` + `Retry-After` o SSE opcional).

---

## 4. Almacenamiento

- Artefactos exportados: `adapters/storage/local_artifact_storage.py:28-254` — raíz canónica anti-symlink, path determinista `{case_id}/{draft_id}/{docx|pdf}/v{version}/{draft}_v{version}.{ext}`, validación UUID v1-5 + regex nombre, límites `max_file_name_length/max_relative_path_length`, `0700` dirs/`0600` files, `create_temp` + `os.replace` atómico, `stream` por chunks, `scan_files/delete_scanned/health`. Metadatos en DB con `source_snapshot_sha256/content_sha256` (`schemas/export.py:36-57`).
- Integridad documental: `application/artifact_integrity.py:29-125` (`sha256(path)`), `domain/rag.py:74-79` (`sha256_json/sha256_text`), `finalization_service.py:41-282` (snapshot + `final_snapshot_sha256`, verificación `expected.sha256 == draft.final_snapshot_sha256`), `draft_document.py:18-26` (`content_sha256`).
- Imports: `source_bytes` persistidos permiten `retry` sin re-subir el archivo (`routes/templates.py:551-575`); `request_hash` incluye `sha256(data)` para detectar reemplazo de archivo bajo la misma clave.
- Drafts: `context_snapshot/context_hash`, `variables_used`, `document_json`, `draft_document_versions` inmutables por `(draft_id,version)` (`008`), `official_document_identifiers` UQ por `(document_type,number,year)`.
- Frontend: `sessionStorage` para claves de idempotencia (`generation.service.ts:67-83`, `rewriteConcept`), `localStorage` no usado para documentos; previsualización DOCX local sin persistencia.

---

## 5. Autorización

- Frontend/BFF: Better-Auth (`lib/auth.ts`, `lib/auth-guards.ts:9-53`); `requireSession` redirige a `/login`; roles `admin|revisor|firmante|redactor` (`getUserRole`, default `redactor`); `toClientSession` deriva `username`. El BFF inyecta `X-Actor` y reescribe campos de auditoría; **no** propaga rol ni firma al backend.
- Backend: `api/middleware.py:15-41` (`ServiceTokenMiddleware`) exige `Authorization: Bearer <service.service_token>` para todo `/api/v1/*` (`401 SERVICE_AUTH_REQUIRED` / `403 SERVICE_AUTH_INVALID` con `hmac.compare_digest`); `ImiRuntimeBoundaryMiddleware:44-114` fail-closed a `501 IMI_CORE_ROUTE_NOT_IMPLEMENTED` para rutas legacy (`/drafts` salvo lecturas colección/detalle/documento + `POST /drafts` manual + `PATCH document`, `/generation-attempts`, `/reviews`, `/semantic-search`, `/exports`, `case-files/*/designation|generation-attempts`); `RagSecurityMiddleware:117-155` exige `application/json` y `≤ max_request_bytes` en `POST /api/v1/rag/*`.
- Validación: `validate_actor` (texto 1..100, sin autenticar) + `validate_idempotency_key` en `schemas/validation.py`, `api/dependencies.py:14-25` (`required_idempotency_key`).
- Brecha: sin RBAC servidor (cualquiera con service-token puede publicar/desactivar/finalizar como cualquier `X-Actor`); `X-Actor` es afirmación del BFF, no identidad verificada extremo a extremo. Propuesta §7 exige `X-Role` + policy `redactor|revisor|firmante|admin`.

---

## 6. Hardcodes fecha / CUIT / monto_numérico

### Fecha

- Fallbacks `'2026-__-__'` y `'2026'` en `imi-disposition-template.ts:11-14`, `imi-disposition-docx.ts:45-46`, `imi-note-docx.ts:29`; `expediente '139-00____'`, `DispositionPreview.tsx:40-48` (`'139-0_________/2026'`, `slice(0,4)||'2026'`); `route.ts:52` (`slice(0,4)||'2026'`); muestra fija `'2026-09-10'` en `TemplateEditorPage.tsx:80`.
- Formato canónico real: ISO `YYYY-MM-DD` en backend (`FinalizeDraftRequest.issued_on:date`, `official_identifiers.issued_on`) y `parseImiDateInput/formatImiDateInput/formatImiLegalDate` (`imi-legal-date.ts:16-101`, soporta `DD/MM/YYYY` ↔ ISO, valida calendario UTC, render `28 de agosto de 2026`). Reglas `year_from_date` asumen `^\d{4}-` (`template_management.py:381-384`, `template-utils.ts:235`).
- Hallazgo: hardcodes de año `2026` y expediente `139-` contaminan previews y tests como si fueran valores reales; deben moverse a `config/institución` o `seed` y marcarse `placeholder`, nunca default silencioso.

### CUIT

- Backend: `schemas/template.py:74` (`format:cuit`), `template_management.py:447-450` (`re.sub(r"[-\s]","",v)` debe ser `^\d{11}$` — valida longitud/dígitos, **no** dígito verificador).
- Frontend: `template-types.ts:50,82,117`, `legal-ai-openapi.generated.ts:2939`, `template-utils.ts:39` (inferencia por etiqueta `cuit|cuil`), `template-utils.ts:260-268,322` (`isValidCuit` con pesos `[5,4,3,2,7,6,5,4,3,2]` y `(11-sum%11)%11` — valida checksum), `imi-disposition-template.ts:43,68,82` / `imi-disposition-docx.ts:13,65,87,95` (`CUIT N° ${cuit}`, zod `min(1)`).
- Divergencia bloqueante: un CUIT de 11 dígitos inválido pasa el backend pero falla en frontend (o viceversa si el usuario bypasea el BFF). Unificar en checksum AFIP en ambos lados (§7).

### monto_numérico / montos

- Claves fijas `monto_numerico|monto_letras|beneficiario|concepto|expediente|factura|...` en `imi-disposition-template.ts:36-56`, `imi-disposition-docx.ts:61-69`; render `PESOS ${words} (${numbers})`, `$`-prefijo, `amountWordsForLegalDocument` (`amount-in-words.ts:272-278`, `backend template_management.py:294-355` con conversor propio limitado a `<1_000_000` y minúsculas vs frontend `MAYÚSCULAS CON NN/100` completo hasta billones).
- Normalización es-AR duplicada y divergente: frontend `normalizeNumber` (`template-utils.ts:184-197`, `amount-in-words.ts:84-112`) vs backend `_bound/normalize_values` (`template_management.py:103-119,271-291`, `,` decimal, `.` miles, `$`/espacios). Riesgo de `1.250` → `1250` vs `1.25`.
- Propuesta §7: tipo canónico `currency_ar` = `{raw, numeric:string es-AR, amount_minor:int64 centavos, words:string MAYÚS CON NN/100}` + `derive:amount_words` único servidor.

Otros hardcodes institucionales (no parametrizables hoy): `INSTITUTION(_UPPER)`, `Decreto 3.055/2004, 798/2026, 1.674/2026`, `Ley 5.571/3.460`, `Fondo Permanente`, `locale es-AR`, `header INSTITUTO...`, `DISPONE:/DECRETA:`, `Comuníquese...`, `warnings BORRADOR...`, `retrieval{top_k:8,minimum_score:0,language:'es',organization:'IMI'}`.

---

## 7. Propuesta de contrato único de importación (vinculante)

> Objetivo: una sola forma de importar → revisar → validar → publicar → versionar, idempotente e inmutable, sin hardcodes de dominio en código.

### 7.1 Principios

1. `template_version_id` (UUID v7) es la única referencia estable; `template_id` es agrupador.
2. Toda mutación exige `Idempotency-Key: ^[A-Za-z0-9._~-]{16,100}$` + `X-Actor` (+ `X-Role` futuro); replay con mismo `request_hash` → `200` + recurso existente; distinto `request_hash` → `409 IDEMPOTENCY_CONFLICT`.
3. `revision:int≥1` es bloqueo optimista; el servidor incrementa (`next=row+1`); el cliente nunca lo calcula.
4. Versión `PUBLISHED` es inmutable; `ARCHIVED` es terminal; solo `DRAFT` admite `PATCH`.
5. Fechas siempre ISO `YYYY-MM-DD`; montos siempre objeto `currency_ar`; CUIT siempre 11 dígitos con checksum.
6. Errores siempre `{code,message,requestId,details,retryable}`; `requestId ≡ X-Request-ID`.

### 7.2 Importación `POST /api/v1/template-imports`

- Request: `multipart/form-data {file: .docx|.pdf ≤20MiB, name:1..200, document_type:disposicion|nota_inicio, idempotency_key?, actor?}`. Headers: `Authorization: Bearer`, `X-Actor`, `Idempotency-Key!`, `X-Request-ID?`.
- Comportamiento: `202 {job}` + `Retry-After: 2` + `Location: /api/v1/template-imports/{id}`. `request_hash=sha256(name|document_type|filename|content_type|sha256(bytes))`. Persiste `source_bytes` para `retry` sin re-upload.
- `GET /{id}` → `TemplateImportJob`:

```json
{
  "id": "0193...",
  "status": "QUEUED|RUNNING|SUCCEEDED|FAILED|CANCELLED",
  "stage": "uploading|extracting|ocr|analyzing|complete",
  "progress": 0,
  "pages_total": 3, "pages_processed": 1,
  "body_template": "{{expediente}} ...",
  "blocks": [{"id":"block-1","type":"paragraph","content":"..."}],
  "candidates": [{"id":"candidate-cuit","key":"cuit","label":"CUIT","type":"text","format":"cuit","fragment":"____","origin":"blank","status":"suggested","confidence":0.65,"occurrences":[{"start":0,"end":4,"text":"____"}]}],
  "warnings": ["El archivo contiene tablas; revisá su representación."],
  "error": null, "retryable": false,
  "template_version": null
}
```

- Terminal `SUCCEEDED` materializa `template_version:{id,version,status:DRAFT,revision:1,body_template,fields,rules,blocks}`; `FAILED` fija `error+retryable`; `POST /{id}/retry` (misma clave nueva) y `POST /{id}/cancel` mantienen semántica actual.
- Frontend: reemplazar `setTimeout 1800ms` por `Retry-After` + backoff `2s→5s→10s` + `If-None-Match/ETag`; opcional SSE `GET .../events`.

### 7.3 Estado / resultado (único sobre)

```ts
type JobStatus = "QUEUED"|"RUNNING"|"SUCCEEDED"|"FAILED"|"CANCELLED";
interface JobResult<T> { id:string; status:JobStatus; progress:0|...|100; error:string|null; retryable:boolean; result:T|null; warnings:string[]; request_id:string; updated_at:string; }
```

- Import: `result:TemplateVersionDraft|null`. Análisis: `result:{suggestions:TemplateSuggestion[]}|null`. Generación SSE: mapear `started→RUNNING`, `complete→SUCCEEDED{result:{draft,structured_draft}}`, `error/cancelled→FAILED/CANCELLED`. Export/finalize síncronos devuelven `result` directo pero con el mismo sobre en `details` ante `202`.
- Regla: nunca `body_template` y `template_version` divergentes; si `template_version!=null`, el cliente debe hidratar desde `template_version`.

### 7.4 Revisión / esquema (`template_version`)

```json
{
  "id": "uuid", "template_version_id": "uuid", "version": 3, "status": "DRAFT",
  "revision": 4, "body_template": "...{{cuit}}...",
  "fields": [{"key":"cuit","label":"CUIT","type":"text","required":true,"order":0}],
  "rules": [{"type":"validation","field":"cuit","format":"cuit"}],
  "blocks": [{"id":"block-1","type":"paragraph","content":"..."}],
  "instructions": null, "extraction_warnings": []
}
```

- `GET /templates/{tid}/versions?page&page_size` paginado servidor (hoy slice en memoria).
- `POST /{tid}/versions {body_template,fields,rules,blocks?,instructions?}` → `201 DRAFT revision:1`.
- `PATCH /{tid}/versions/{vid} {mismos + revision}` exige `revision==actual`, retorna `revision+1`.
- `POST /{tid}/versions/{vid}/publish {revision, confirm_warnings:false}` → `PUBLISHED`; archiva `PUBLISHED` previas; `confirm_warnings` obligatorio si `extraction_warnings≠[]`; doble `POST` idempotente → `200`.

### 7.5 Validación (servidor manda, frontend espeja)

- Definición: nombre/body no vacíos, `key` regex, unicidad (incluye `normalizeTemplateKey`), `referenced-keys ⊆ fields`, `block_ids` únicos, `select→options≠[]`, reglas con destino/bloque/fuente existentes, `min≤max` (texto y numérico/fecha), condiciones con valor salvo `present|not_present`, sin ciclos `derived`.
- Valores: `required∧¬read_only`, `select∈options`, `number|currency` parse es-AR, `date=YYYY-MM-DD` calendario válido, `boolean∈{true,false,sí,no,1,0}`, `email` RFC-simple, **`cuit` 11 dígitos + checksum AFIP (unificar)**.
- Derivadas: `amount_words(source:currency_ar)→words MAYÚS CON NN/100`, `year_from_date(source:date)→YYYY`.
- `POST /template-previews {document_type,name,body_template,fields,rules,blocks?,values}` → `{document:LegalDocument, errors:[], warnings:["La previsualización no crea expediente ni numeración oficial."]}`; sin persistencia, sin idempotencia.
- `validateTemplateDraft(checkUnusedFields:true)` es gate de publicación: bloquea `suggested|unresolved` y `ignored+marker` aún referenciado.

### 7.5b Tipos canónicos fecha/CUIT/monto (corrección de hardcodes)

```json
{
  "fecha": {"type":"date","value":"2026-09-10","display":"10/09/2026","legal":"10 de septiembre de 2026"},
  "cuit": {"type":"text","format":"cuit","value":"30712345678","display":"30-71234567-8"},
  "monto": {"type":"currency_ar","raw":"1.250.000,00","numeric":"1.250.000,00","amount_minor":125000000,"words":"UN MILLÓN DOSCIENTOS CINCUENTA MIL CON 00/100"}
}
```

- Transportar `YYYY-MM-DD` + `amount_minor` + `words`; formatear solo en presentación (`imi-legal-date.ts`, `amount-in-words.ts` unificados con backend).
- Eliminar defaults `'2026'/'139-00____'/'____'`; usar `placeholder` + `required:true` + error `Falta completar`.

### 7.6 Publicación idempotente + versión inmutable

```
create (Idempotency-Key K1, hash H1) → 201 DRAFT vN rev1
PATCH  (K2, rev1)                    → 200 DRAFT rev2   (rev3 si otro PATCH con rev2)
publish(K3, rev2)                    → 201 PUBLISHED     (replay K3/H3 → 200 mismo recurso)
publish(K3, rev2')≠H3                 → 409 IDEMPOTENCY_CONFLICT
PATCH PUBLISHED                       → 409 TEMPLATE_VERSION_IMMUTABLE
deactivate(K4)                        → 200 INACTIVE (plantilla; versiones intactas)
```

- Clave: `16..100 [A-Za-z0-9._~-]` en ambos lados (hoy frontend acepta `16..128` → alinear a `100`).
- Respuesta replay: mismo `ETag: "sha256:<request_hash>"` + `Idempotent-Replayed:true`.

---

## 8. Deltas de contrato (frontend ↔ backend) y acción

| # | Delta | Severidad | Acción |
|---|---|---|---|
| D1 | `Idempotency-Key` frontend `16..128` vs backend `16..100` (`disposiciones.service`/`generation.service` vs `validation.py:11`) | Alta | Alinear a `16..100` en `request()`, `getIdempotencyKey`, `rewriteConcept`. |
| D2 | CUIT sin checksum en backend vs con checksum en frontend | Alta | Portar `isValidCuit` al backend (`validate_values`), test cruzado `30-71234567-8` válido / `30-71234567-9` inválido. |
| D3 | `amount_words` backend minúsculas `<1M` vs frontend `MAYÚS` hasta billones | Alta | Extraer tabla única + test dorado `1.250.000,00 ↔ UN MILLÓN... CON 00/100`. |
| D4 | Parse `number/currency` es-AR duplicado con bordes (`1.250` ambiguo) | Alta | Tipo `currency_ar` + `amount_minor`; fuzz `normalizeNumber` vs `_bound`. |
| D5 | `GET templates/{id}/versions` pagina en memoria (`templates.py:219-229`) | Media | Paginar en SQL (`LIMIT/OFFSET`), devolver `request_id`. |
| D6 | Polling fijo `1800ms` sin `Retry-After/ETag` | Media | Backend emite `Retry-After:2` + `ETag`; frontend backoff. |
| D7 | `previewTemplate` sin `Idempotency-Key` (única escritura aparente sin clave) | Baja | Documentar como stateless o exigir clave opcional. |
| D8 | `X-Actor` sin `X-Role`/RBAC; `author/opened_by/...:'session'` literal desde frontend | Alta | BFF resuelve `username+role`, backend valida `role∈{redactor,revisor,firmante,admin}` y autoriza `publish/finalize/deactivate` solo `revisor|firmante|admin`. |
| D9 | Esquema `imi.*` sin migración Alembic | Media | Añadir migración `011_imi_template_core` que cree `imi.document_template_versions/template_version_configs/template_import_jobs` o documentar bootstrap. |
| D10 | `variables` derivado `fields[].key` en cliente pero validado `referenced⊆fields` en servidor | Media | Enviar `variables` solo servidor-derivado; cliente no lo calcula. |
| D11 | `LegalDocument.blocks` y `content` solo en preview/import, no en `DraftDocument` persistido | Baja | Incluir `blocks` en `LegalDocument` siempre o separar `preview_blocks`. |
| D12 | `document_type` abierto `string` en frontend vs `TemplateDocumentType` cerrado + `IMI_DOCUMENT_TYPES=[disposicion,nota_inicio]` | Media | Cerrar a `disposicion|nota_inicio` (+`decreto` solo lectura histórica). |

---

## 9. Riesgos

1. **Divergencia de validación** (D2-D4): documentos publicables en un lado y rechazados en otro; impacto legal directo (CUIT/monto/fecha). Mitigar con suite dorada compartida antes de cualquier cambio funcional.
2. **Publicación no autorizada**: sin RBAC servidor, cualquier poseedor del service-token publica. Mitigar con `X-Role` + policy + auditoría `review_snapshot_sha256`.
3. **Pérdida de idempotencia**: claves en `sessionStorage` + `rewriteConcept` que rota clave en `finally`; reintento tras cierre de pestaña duplica. Mitigar con claves persistentes por `draftFingerprint` + `409` con `request_hash`.
4. **Inmutabilidad parcial**: `PATCH` bloqueado solo por `status!=DRAFT` en `imi_core.py:740`; falta constraint DB `CHECK(status='DRAFT' → mutable)`. Añadir trigger/constraint + test `PATCH PUBLISHED → 409`.
5. **Trazabilidad migratoria**: `imi.*` fuera de Alembic impide reproducibilidad. Bloquea despliegue limpio; resolver D9.
6. **Hardcodes institucionales**: año `2026`, expediente `139-`, decretos y `Fondo Permanente` en código impiden reutilización y contaminan tests. Externalizar a `institución.json` versionado.

---

## 10. Checks read-only ejecutados (este worktree, sin mutar repos auditados)

```text
# worktree hijo
git status --short            → limpio (antes del informe)
git branch --show-current      → UrielMaximiliano/imi-leg-contract-audit-opencode
git log --oneline -5           → 1201caf refactor(api): share database resources...
git remote -v                  → origin https://github.com/UrielMaximiliano/legal-AI-infraestructure.git
# repos auditados (solo log/rev-parse)
gestor-expedientes-imi         → 15a734262169616886f945bd132a0628703f1225
legal-AI-infraestructure       → c3a96ba4ef9c737b3d21b2a9b4b29e60d
# búsquedas read-only
rg "cuit|monto_numerico|fecha_" apps/api/src          → schemas/template.py:74, template_management.py:447
rg "cuit|monto_numerico|fecha_|CUIT" gestor/src       → imi-disposition-{template,docx}.ts, template-utils.ts, amount-in-words.ts, imi-legal-date.ts
rg "class ImiCore|template_import|PUBLISHED|revision" → imi_core.py + templates.py (idempotencia/revisión)
```

No se ejecutaron linters/tests con escritura (`tsc`, `pytest`, `alembic upgrade`) por ser worker read-only y para no mutar `node_modules/.pytest_cache`; la verificación es estática + `git` de solo lectura. Recomendado al coordinador: `npx tsc --noEmit` (gestor) y `pytest apps/api/tests/unit/test_template_management.py apps/api/tests/contract/test_templates_endpoints.py -q` (backend) en CI.

---

## 11. Anexos — referencias exactas

- Frontend transporte: `gestor-expedientes-imi/src/lib/legal-ai-client.ts:5-190`, `src/services/disposiciones.service.ts:58-432`, `src/services/generation.service.ts:53-137`, `src/lib/sse.ts`, `src/app/api/legal-ai/[...path]/route.ts`.
- Tipos/validación FE: `src/lib/legal-ai-types.ts:1-206`, `src/lib/template-types.ts:1-143`, `src/lib/template-utils.ts:1-415`, `src/lib/amount-in-words.ts:1-278`, `src/lib/imi-legal-date.ts:1-101`, `src/lib/imi-disposition-template.ts:1-95`, `src/lib/imi-disposition-docx.ts:1-~130`, `src/lib/auth-guards.ts:1-53`.
- UI sincronía: `src/components/pages/TemplateEditorPage.tsx:286-317` (polling import), `src/components/pages/NewDisposicionPage.tsx:252-258` (timer rewrite), `src/components/DispositionPreview.tsx:40-82`.
- Backend routes/schemas: `legal-AI-infraestructure/apps/api/src/legal_ai/api/routes/templates.py:55-667`, `api/routes/drafts.py:54-506`, `api/middleware.py:15-155`, `api/dependencies.py:14-25`, `schemas/template.py:11-244`, `schemas/document.py:19-178`, `schemas/review.py:15-118`, `schemas/finalization.py:14-43`, `schemas/export.py:15-86`, `schemas/validation.py:1-54`, `domain/enums.py:6-140`.
- Dominio/almacenamiento: `application/template_management.py:1-724`, `adapters/database/imi_core.py:131-~1050`, `adapters/storage/local_artifact_storage.py:28-254`, `application/finalization_service.py:41-282`, `application/artifact_integrity.py:29-125`.
- Migraciones: `apps/api/alembic/versions/001_enable_pgvector.py`, `002_employees_and_case_files.py`, `003_templates_drafts_and_generation.py:19-271`, `004_document_review_and_export.py`, `005..007`, `008_structured_documents_and_official_numbering.py:15-142`, `009_rag_cancellation_and_filter_policy.py`, `010_draft_official_metadata.py`.
- Generado: `gestor-expedientes-imi/src/lib/legal-ai-openapi.generated.ts:2939` (`format email|cuit`).

---

*Fin del informe. Sin cambios de código, contratos ni migraciones. Solo se crea este archivo y su commit en el worktree hijo, sin push ni despliegue.*
