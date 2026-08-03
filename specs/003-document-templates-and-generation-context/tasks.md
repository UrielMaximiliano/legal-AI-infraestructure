# Tasks: Plantillas, Contexto de Generación y Borradores

**Input**: Design documents from `/specs/003-document-templates-and-generation-context/`
**Prerequisites**: plan.md (required), spec.md (required), contracts/ (required)

## Format: `[ID] [P?] Description`

- **[ID]**: Sequential task number (T001, T002, T003...)
- **[P]**: Can run in parallel (different files, no dependencies) - optional
- **Description**: Clear action with exact file path included

---

## Phase 1: Enums y Dominio Puro

**Purpose**: Definir enums, máquina de estados y modelos de dominio como base pura sin dependencias de BD.

- [x] T001 Extend `apps/api/src/legal_ai/domain/enums.py` with new enums: `TemplateDocumentType(StrEnum)` — resolucion, informe, oficio, solicitud, acuerdo, otros; `DraftStatus(StrEnum)` — generado, en_revision, aprobado, rechazado, superseded; `TransitionAction(StrEnum)` — send_to_review, approve, reject, edit_content; `GenerationStatus(StrEnum)` — in_progress, completed, failed. NOTE: `TemplateDocumentType` uses different name than existing `DocumentType` (employee documents) to avoid conflict. Covers RF-01.1 (document_type enum), RF-04.1 (DraftStatus), RF-05.1 (TransitionAction), RF-03.1 (GenerationStatus)
- [x] T002 [P] Create `apps/api/src/legal_ai/domain/template.py` with dataclass `Template` (id: UUID, name: str, document_type: TemplateDocumentType, version: int, organ_emisor: str | None, normativa: str | None, description: str | None, body_template: str, variables: list[str], is_active: bool, created_at: datetime, updated_at: datetime) and `TemplateVariable` dataclass if needed. Covers RF-01.1, RF-01.2, RF-01.6
- [x] T003 [P] Create `apps/api/src/legal_ai/domain/draft.py` with dataclass `Draft` (id: UUID, template_id: UUID, case_file_id: UUID, title: str, content: str | None, status: DraftStatus, version: int, generation_number: int, context_snapshot: dict, context_hash: str, variables_used: dict, parent_draft_id: UUID | None, observations: str | None, request_id: str | None, created_at: datetime, updated_at: datetime), dataclass `DraftTransition` (id: UUID, draft_id: UUID, from_status: DraftStatus, to_status: DraftStatus, action: TransitionAction, observations: str | None, performed_by: str | None, created_at: datetime), `VALID_TRANSITIONS` dict, `ACTION_MAP` dict, `can_transition()` function. Covers RF-04.1, RF-04.2, RF-08.1
- [x] T004 [P] Create `apps/api/src/legal_ai/domain/generation_attempt.py` with dataclass `GenerationAttempt` (id: UUID, case_file_id: UUID, template_id: UUID, idempotency_key: str | None, model: str, prompt_hash: str, prompt_content: str, status: GenerationStatus, started_at: datetime, completed_at: datetime | None, error_code: str | None, error_message: str | None, created_at: datetime). Covers RF-03.1, RF-03.3
- [x] T005 [P] Create `apps/api/src/legal_ai/domain/designation_data.py` with dataclass `DesignationData` (id: UUID, case_file_id: UUID, position_name: str, organizational_unit: str | None, start_date: date | None, legal_basis: str | None, appointing_authority: str | None, salary_category: str | None, work_schedule: str | None, observations: str | None, created_at: datetime, updated_at: datetime). Covers RF-02.1 (designation snapshot)

---

## Phase 2: Modelos ORM y Migración

**Purpose**: Definir modelos SQLAlchemy y migración Alembic 003.

- [x] T006 Extend `apps/api/src/legal_ai/adapters/database/models.py` with 5 new ORM models: `DocumentTemplateModel` (document_templates table), `DesignationDataModel` (designation_data table), `DocumentDraftModel` (document_drafts table), `DraftTransitionModel` (draft_transitions table), `GenerationAttemptModel` (generation_attempts table). All columns, constraints (UNIQUE name+document_type+version, UNIQUE case_file_id in designation, FKs), DEFAULT values, JSONB columns. Covers RNF-02 (5 tablas, JSONB, índices)
- [x] T007 Create `apps/api/src/legal_ai/alembic/versions/003_templates_drafts_and_generation.py` migration: `down_revision = "002"`, create tables in FK order: document_templates → designation_data → document_drafts → draft_transitions → generation_attempts, create 14 indexes (ix_templates_document_type, ix_templates_is_active, ix_templates_name, ix_designation_data_case_file_id, ix_drafts_case_file_id, ix_drafts_status, ix_drafts_parent_draft_id, ix_drafts_template_id, ix_drafts_context_hash, ix_draft_transitions_draft_id, ix_generation_attempts_idempotency_key UNIQUE, ix_generation_attempts_case_file_id, ix_generation_attempts_status). Downgrade drops tables in reverse order. Covers RNF-02 (migration versionada)

---

## Phase 3: Puertos y Unit of Work

**Purpose**: Definir interfaces de repositorio y extender Unit of Work.

- [x] T008 Create `apps/api/src/legal_ai/ports/template_repository.py` with `TemplateRepository(Protocol)`: `create(template) -> Template`, `get_by_id(template_id: UUID) -> Template | None`, `get_active_version(name: str, document_type: str) -> Template | None`, `list_active(document_type: str | None, search: str | None, skip: int, limit: int) -> tuple[list[Template], int]`, `update(template: Template) -> Template`, `deactivate_all_versions(name: str, document_type: str) -> None`. Covers RF-01.1 through RF-01.6
- [x] T009 [P] Create `apps/api/src/legal_ai/ports/draft_repository.py` with `DraftRepository(Protocol)`: `create(draft: Draft) -> Draft`, `get_by_id(draft_id: UUID) -> Draft | None`, `list_by_case_file(case_file_id: UUID, status: str | None, skip: int, limit: int) -> tuple[list[Draft], int]`, `update_with_optimistic_lock(draft: Draft, expected_version: int) -> Draft | None`, `update_status(draft_id: UUID, new_status: str, version: int) -> Draft | None`. Covers RF-04.1, RF-06.1, RF-07.1, RF-07.2
- [x] T010 [P] Create `apps/api/src/legal_ai/ports/draft_transition_repository.py` with `DraftTransitionRepository(Protocol)`: `create(transition: DraftTransition) -> DraftTransition`, `list_by_draft(draft_id: UUID) -> list[DraftTransition]`. Covers RF-04.2, RF-08.1
- [x] T011 [P] Create `apps/api/src/legal_ai/ports/generation_attempt_repository.py` with `GenerationAttemptRepository(Protocol)`: `create(attempt: GenerationAttempt) -> GenerationAttempt`, `get_by_idempotency_key(key: str) -> GenerationAttempt | None`, `get_by_id(attempt_id: UUID) -> GenerationAttempt | None`, `list_by_case_file(case_file_id: UUID) -> list[GenerationAttempt]`, `update(attempt: GenerationAttempt) -> GenerationAttempt`, `delete_by_idempotency_key(key: str) -> None`, `cleanup_expired(window_hours: int = 24) -> int`. Covers RF-03.1, RF-03.3, idempotencia
- [x] T012 [P] Create `apps/api/src/legal_ai/ports/designation_repository.py` with `DesignationRepository(Protocol)`: `create(designation: DesignationData) -> DesignationData`, `get_by_case_file_id(case_file_id: UUID) -> DesignationData | None`, `update(designation: DesignationData) -> DesignationData`. Covers RF-02.1 (designation CRUD)
- [x] T013 Extend `apps/api/src/legal_ai/adapters/database/unit_of_work.py` with new repository properties: `templates`, `drafts`, `draft_transitions`, `generation_attempts`, `designations`. Initialize in `__aenter__` with shared session. Maintain existing `employees`, `case_files`, `case_status_history`. Covers RNF-003 (transacción atómica)

---

## Phase 4: Adaptadores SQLAlchemy

**Purpose**: Implementar repositorios concretos con SQLAlchemy 2.x async.

- [x] T014 Create `apps/api/src/legal_ai/adapters/database/template_repository.py` implementing `TemplateRepository`: SQLAlchemy 2.x async. `create()` inserts template. `get_by_id()` returns template or None. `get_active_version()` WHERE name=:name AND document_type=:type AND is_active=true ORDER BY version DESC LIMIT 1. `list_active()` dynamic WHERE with document_type equality, search ILIKE on name, pagination with skip/limit, ORDER BY created_at DESC id DESC. `update()` persists changes. `deactivate_all_versions()` UPDATE SET is_active=false WHERE name=:name AND document_type=:type. Covers RF-01.1 through RF-01.6
- [x] T015 [P] Create `apps/api/src/legal_ai/adapters/database/draft_repository.py` implementing `DraftRepository`. `update_with_optimistic_lock()` UPDATE ... WHERE id=:id AND version=:expected_version, returns None if 0 rows affected. `update_status()` updates status + increments version atomically. `list_by_case_file()` with status filter, pagination, ORDER BY created_at DESC. Covers RF-04.1, RF-06.1, RF-07.1, RF-07.2, concurrencia optimista
- [x] T016 [P] Create `apps/api/src/legal_ai/adapters/database/draft_transition_repository.py` implementing `DraftTransitionRepository`. `create()` inserts transition. `list_by_draft()` returns all ordered by created_at ASC id ASC. Covers RF-04.2, RF-08.1
- [x] T017 [P] Create `apps/api/src/legal_ai/adapters/database/generation_attempt_repository.py` implementing `GenerationAttemptRepository`. `get_by_idempotency_key()` for idempotency. `cleanup_expired()` deletes attempts older than window_hours. Covers RF-03.1, RF-03.3, idempotencia
- [x] T018 [P] Create `apps/api/src/legal_ai/adapters/database/designation_repository.py` implementing `DesignationRepository`. `get_by_case_file_id()` for case file lookup. Covers RF-02.1

---

## Phase 5: Servicios de Aplicación

**Purpose**: Implementar lógica de negocio (servicios, contexto, prompt builder, Ollama client).

- [x] T019 Create `apps/api/src/legal_ai/application/template_service.py` with `TemplateService`: `create_template()` validates name uniqueness per document_type (DOCUMENT_TEMPLATE_NAME_EXISTS 409), creates with version=1. `get_template()` returns 404 if not found. `list_templates()` returns paginated active templates with filters. `update_template()` if body_template or variables change → deactivate current + create new version (version+1); if only metadata changes → update in place. `deactivate_template()` sets is_active=false, validates was active. Covers RF-01.1 through RF-01.6
- [x] T020 Create `apps/api/src/legal_ai/application/designation_service.py` with `DesignationService`: `create_designation()` verifies case_file exists (404), validates case_type=designacion (409 CASE_FILE_TYPE_INCOMPATIBLE), checks no existing designation (409 DESIGNATION_EXISTS), creates. `get_designation()` returns 404 if not found. `update_designation()` updates existing. Covers designation CRUD, RF-02.1
- [x] T021 Create `apps/api/src/legal_ai/application/generation_context.py` with `GenerationContext`: `build_context(template_id, case_file_id)` retrieves template, case_file, employee, designation (if case_type=designacion), serializes snapshot with template/case_file/employee/designation/variables/metadata sub-objects, computes SHA-256 hash. `validate_variables(template, user_variables)` checks all required variables present, returns 422 MISSING_REQUIRED_VARIABLES if not. `compute_hash(snapshot)` deterministic SHA-256. Covers RF-02.1, RF-02.2, RF-08.2
- [x] T022 Create `apps/api/src/legal_ai/application/prompt_builder.py` with `PromptBuilder`: `render_template(body_template, context)` safe Jinja2-like rendering with namespace resolution (employee.*, case_file.*, designation.*, variables.*), no code execution. `build_prompt(rendered_template, context)` adds system instruction prefix. `validate_syntax(body_template)` returns list of unknown variables for validation. Covers RF-03.2, prompt security
- [x] T023 Create `apps/api/src/legal_ai/application/ollama_client.py` (extend or create new) with `OllamaClient`: `generate(prompt, model, timeout) -> OllamaResponse`. Config via OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT. Handles: timeout, 401, 403, 404, 429, 5xx, JSON invalid, empty response, connection reset. NEVER exposes OLLAMA_API_TOKEN in errors. Covers RF-03.1 (Ollama integration)
- [ ] T024 Create `apps/api/src/legal_ai/application/draft_service.py` with `DraftService`: `generate_draft(request, idempotency_key)` full flow: validate inputs → check idempotency → validate template active → validate case_file exists → build context → validate variables → register generation_attempt IN_PROGRESS → release transaction → call Ollama → if success: create draft + update attempt COMPLETED + cache; if fail: update attempt FAILED + return error. `get_draft()` 404 if not found. `list_drafts()` paginated with status filter. `edit_content()` optimistic locking + validate status allows editing (EN_REVISION or RECHAZADO). `transition_draft()` validate machine of states + optimistic lock + create transition record. `regenerate_draft()` validate state (EN_REVISION or RECHAZADO) + optimistic lock → mark SUPERSEDED on success → create new draft with parent_draft_id. `get_history()` returns transitions ordered ASC. Covers RF-03.1, RF-04.1, RF-05.1, RF-06.1, RF-07.1, RF-07.2, RF-08.3, idempotency, optimistic locking

---

## Phase 6: Schemas y Errores HTTP

**Purpose**: Definir schemas Pydantic v2 request/response y extender manejo de errores.

- [x] T025 Create `apps/api/src/legal_ai/schemas/template.py` with `CreateTemplateRequest(BaseModel)` (name, document_type: TemplateDocumentType, organ_emisor?, normativa?, description?, body_template, variables: list[str]; extra="forbid"), `UpdateTemplateRequest(BaseModel)` (body_template?, organ_emisor?, normativa?, description?, variables?; extra="forbid"), `TemplateResponse(BaseModel)` (id: UUID, name, document_type, version, organ_emisor?, normativa?, description?, body_template, variables: list[str], is_active, created_at, updated_at). Covers RF-01.1 through RF-01.6
- [x] T026 [P] Create `apps/api/src/legal_ai/schemas/draft.py` with `GenerateDraftRequest(BaseModel)` (template_id: UUID, case_file_id: UUID, variables: dict[str, str] = {}), `EditDraftContentRequest(BaseModel)` (content: str, expected_version: int; extra="forbid"), `TransitionDraftRequest(BaseModel)` (action: TransitionAction, expected_version: int, observations?: str; extra="forbid"), `RegenerateDraftRequest(BaseModel)` (observations?: str, expected_version: int; extra="forbid"), `DraftResponse(BaseModel)` (id: UUID, template_id, case_file_id, title, content?, status: DraftStatus, version, generation_number, variables_used: dict, parent_draft_id?, observations?, request_id?, created_at, updated_at), `DraftTransitionResponse(BaseModel)` (id: UUID, draft_id, from_status, to_status, action, observations?, performed_by?, created_at). Covers RF-03.1, RF-04.1, RF-05.1, RF-06.1, RF-07.1
- [x] T027 [P] Create `apps/api/src/legal_ai/schemas/designation.py` with `CreateDesignationDataRequest(BaseModel)` (position_name, organizational_unit?, start_date?: date, legal_basis?, appointing_authority?, salary_category?, work_schedule?, observations?; extra="forbid"), `DesignationDataResponse(BaseModel)` (id: UUID, case_file_id, position_name, organizational_unit?, start_date?, legal_basis?, appointing_authority?, salary_category?, work_schedule?, observations?, created_at, updated_at). Covers designation CRUD
- [x] T028 [P] Create `apps/api/src/legal_ai/schemas/generation.py` with `GenerationAttemptResponse(BaseModel)` (id: UUID, case_file_id, template_id, idempotency_key?, model, prompt_hash, status: GenerationStatus, started_at, completed_at?, error_code?, error_message?, created_at). Covers RF-03.3
- [ ] T029 Extend `apps/api/src/legal_ai/api/exceptions.py` with new exception classes and handlers: `TemplateNotFoundError`, `TemplateConflictError`, `TemplateInactiveError`, `DraftNotFoundError`, `DraftReadOnlyError`, `InvalidDraftTransitionError`, `ConcurrentModificationError` (reusable from 002), `OllamaUnavailableError`, `OllamaTimeoutError`, `GenerationFailedError`, `IdempotencyKeyMismatchError`, `GenerationInProgressError`, `DesignationNotFoundError`, `DesignationExistsError`, `CaseFileTypeIncompatibleError`, `MissingRequiredVariablesError`, `ContentTooLargeError`, `ContextBuildFailedError`. Each maps to correct HTTP status. Update not_found_error_handler, conflict_error_handler, validation_error_handler with new cases. Covers 22 error codes from spec

---

## Phase 7: Endpoints Templates

**Purpose**: Implementar los 5 endpoints de plantillas.

- [x] T030 Create `apps/api/src/legal_ai/api/routes/templates.py` with `router = APIRouter(prefix="/api/v1/templates", tags=["templates"])` and 5 endpoints:
  1. `POST /` → create template, 201 TemplateResponse, 409 DOCUMENT_TEMPLATE_NAME_EXISTS, 422 validation
  2. `GET /` → list active templates with query params (document_type, search, skip, limit), 200 PaginatedResponse[TemplateResponse]
  3. `GET /{template_id}` → get by ID, 200 TemplateResponse, 404 DOCUMENT_TEMPLATE_NOT_FOUND, 422 invalid UUID
  4. `PATCH /{template_id}` → update/create new version, 200 TemplateResponse, 404, 409 name conflict
  5. `POST /{template_id}/deactivate` → deactivate, 200 TemplateResponse, 404, 409 TEMPLATE_INACTIVE

  Covers RF-01.1 through RF-01.6
- [x] T031 Update `apps/api/src/legal_ai/api/router.py`: add `from legal_ai.api.routes.templates import router as templates_router` and `router.include_router(templates_router)`. Covers template endpoints registration

---

## Phase 8: Endpoints Designation

**Purpose**: Implementar los 3 endpoints de datos de designación.

- [x] T032 Create `apps/api/src/legal_ai/api/routes/designation.py` with `router = APIRouter(tags=["designation"])` and 3 endpoints:
  1. `POST /api/v1/case-files/{case_file_id}/designation` → create designation, 201 DesignationDataResponse, 404 CASE_FILE_NOT_FOUND, 409 CASE_FILE_TYPE_INCOMPATIBLE / DESIGNATION_EXISTS
  2. `GET /api/v1/case-files/{case_file_id}/designation` → get designation, 200 DesignationDataResponse, 404 CASE_FILE_NOT_FOUND / DESIGNATION_DATA_NOT_FOUND
  3. `PUT /api/v1/case-files/{case_file_id}/designation` → update designation, 200 DesignationDataResponse, 404

  Covers designation CRUD, RF-02.1
- [x] T033 Update `apps/api/src/legal_ai/api/router.py`: add designation router. Covers designation endpoints registration

---

## Phase 9: Endpoints Drafts y Generación

**Purpose**: Implementar los 7 endpoints de borradores y 2 de intentos de generación.

- [x] T034 Create `apps/api/src/legal_ai/api/routes/drafts.py` with `router = APIRouter(tags=["drafts"])` and 7 endpoints:
  1. `POST /api/v1/drafts/generate` → generate draft with Idempotency-Key header, 201 DraftResponse, 404/409/422/502/503/504 errors
  2. `GET /api/v1/case-files/{case_file_id}/drafts` → list drafts with status filter, 200 PaginatedResponse[DraftResponse], 404 CASE_FILE_NOT_FOUND
  3. `GET /api/v1/drafts/{draft_id}` → get by ID, 200 DraftResponse, 404 DRAFT_NOT_FOUND
  4. `PATCH /api/v1/drafts/{draft_id}/content` → edit content with expected_version, 200 DraftResponse, 404/409 CONCURRENT_MODIFICATION/DRAFT_READ_ONLY
  5. `POST /api/v1/drafts/{draft_id}/transitions` → state transition with expected_version, 200 DraftResponse, 404/409 INVALID_STATUS_TRANSITION/CONCURRENT_MODIFICATION
  6. `POST /api/v1/drafts/{draft_id}/regenerate` → regenerate with expected_version, 201 DraftResponse, 404/409/502/503/504
  7. `GET /api/v1/drafts/{draft_id}/history` → get transitions, 200 list[DraftTransitionResponse], 404

  Covers RF-03.1, RF-04.1, RF-05.1, RF-06.1, RF-07.1, RF-07.2, RF-08.1
- [x] T035 Create `apps/api/src/legal_ai/api/routes/generation.py` with `router = APIRouter(tags=["generation"])` and 2 endpoints:
  1. `GET /api/v1/generation-attempts/{attempt_id}` → get by ID, 200 GenerationAttemptResponse, 404 GENERATION_ATTEMPT_NOT_FOUND
  2. `GET /api/v1/case-files/{case_file_id}/generation-attempts` → list by case file, 200 list[GenerationAttemptResponse], 404 CASE_FILE_NOT_FOUND

  Covers RF-03.3
- [x] T036 Update `apps/api/src/legal_ai/api/router.py`: add drafts and generation routers. Covers all endpoint registration
- [ ] T037 Update `apps/api/src/legal_ai/main.py`: register exception handlers for all new domain exceptions (TemplateNotFoundError, DraftNotFoundError, etc.) in not_found_error_handler, conflict_error_handler, validation_error_handler. Covers error handling for 22 error codes

---

## Phase 10: Pruebas Unitarias

**Purpose**: Pruebas de lógica pura: máquina de estados, templates, contexto, prompt builder, idempotencia.

- [x] T038 Create `apps/api/tests/unit/test_draft_state_machine.py` with tests: all 4 valid transitions return True (GENERADO→EN_REVISION, EN_REVISION→APROBADO, EN_REVISION→RECHAZADO, RECHAZADO→EN_REVISION), same-state transition returns False, APROBADO→any returns False (terminal), SUPERSEDED→any returns False (terminal), random jumps return False, ACTION_MAP correctness, can_transition function covers all cases. Covers RF-04.1 (10 transitions)
- [x] T039 [P] Create `apps/api/tests/unit/test_template_service.py` with tests: create template with version=1, duplicate name+type raises CONFLICT, update with content change creates new version (version=2, old deactivated), update metadata only updates in place, deactivate sets is_active=false, get_active_version returns latest active, list with filters. Covers RF-01.1 through RF-01.6
- [x] T040 [P] Create `apps/api/tests/unit/test_generation_context.py` with tests: build_context with all data, template not found raises 404, case_file not found raises 404, designation data included when case_type=designacion, context_hash is deterministic (same input = same hash), context_snapshot size < 50KB, variables validation (required missing → 422), extra variables ignored. Covers RF-02.1, RF-02.2, RF-08.2
- [x] T041 [P] Create `apps/api/tests/unit/test_prompt_builder.py` with tests: render_template resolves {{employee.first_name}}, {{case_file.case_number}}, {{designation.position_name}}, {{variables.custom}}, namespace resolution, unknown variable detection, syntax validation, no code execution in templates, system instruction prefix. Covers RF-03.2
- [x] T042 [P] Create `apps/api/tests/unit/test_draft_service.py` with tests: generate_draft happy path, edit_content optimistic locking (version mismatch → CONCURRENT_MODIFICATION), edit_content read-only status (APPROBED → DRAFT_READ_ONLY), transition_draft valid/invalid, regenerate_draft marks SUPERSEDED + creates new draft with parent_draft_id, regenerate from invalid state (APPROVED) → error. Covers RF-04.1, RF-05.1, RF-06.1, concurrencia
- [ ] T043 [P] Create `apps/api/tests/unit/test_idempotency.py` with tests: same key + same payload → cached response, same key + different payload → IDEMPOTENCY_KEY_MISMATCH, key exists IN_PROGRESS → GENERATION_IN_PROGRESS, key exists COMPLETED → return cached draft, key exists FAILED → delete old + allow retry, key expired (>24h) → treat as new. Covers idempotencia
- [x] T044 [P] Create `apps/api/tests/unit/test_generation_attempt.py` with tests: create attempt, get by idempotency_key, cleanup_expired removes old attempts, prompt_content stored but not exposed via API. Covers RF-03.1, RF-03.3, prompt security

---

## Phase 11: Pruebas Contractuales

**Purpose**: Verificar schemas de respuesta de los 17 endpoints y estructura de errores.

- [ ] T045 Create `apps/api/tests/contract/test_templates_endpoints.py` with contract tests: POST /templates → 201 TemplateResponse; GET /templates → 200 PaginatedResponse; GET /templates/{id} → 200; PATCH /templates/{id} → 200; POST /templates/{id}/deactivate → 200. Error cases: 404, 409 name conflict, 422 invalid UUID/missing fields. Covers RF-01.1 through RF-01.6
- [ ] T046 [P] Create `apps/api/tests/contract/test_designation_endpoints.py` with contract tests: POST /case-files/{id}/designation → 201; GET → 200; PUT → 200. Error cases: 404, 409 type incompatible/exists, 422. Covers designation CRUD
- [ ] T047 [P] Create `apps/api/tests/contract/test_drafts_endpoints.py` with contract tests: POST /drafts/generate → 201 with Idempotency-Key; GET /case-files/{id}/drafts → 200 PaginatedResponse; GET /drafts/{id} → 200; PATCH /drafts/{id}/content → 200; POST /drafts/{id}/transitions → 200; POST /drafts/{id}/regenerate → 201; GET /drafts/{id}/history → 200. Error cases: 404, 409 CONCURRENT_MODIFICATION/INVALID_TRANSITION/DRAFT_READ_ONLY/TEMPLATE_INACTIVE, 422, 503 OLLAMA_UNAVAILABLE. Covers RF-03.1, RF-04.1, RF-05.1, RF-06.1, RF-07.1, RF-07.2
- [ ] T048 [P] Create `apps/api/tests/contract/test_generation_endpoints.py` with contract tests: GET /generation-attempts/{id} → 200; GET /case-files/{id}/generation-attempts → 200. Error cases: 404. Covers RF-03.3
- [ ] T049 [P] Create `apps/api/tests/contract/test_003_error_response.py` with tests for: all 22 error codes map to correct HTTP status, error response format (error_code, message, request_id), no sensitive values in error messages, IDEMPOTENCY_KEY_MISMATCH format, CONCURRENT_MODIFICATION format. Covers 22 error codes

---

## Phase 12: Pruebas de Integración PostgreSQL

**Purpose**: Verificar repositorios, UoW y migraciones con PostgreSQL real.

- [x] T050 Create `apps/api/tests/integration/test_template_repository.py` with tests: create template, get by ID, get active version, list with filters (document_type, search), list pagination, update template, deactivate all versions, unique constraint (name+type+version). Covers RF-01.1 through RF-01.6
- [x] T051 [P] Create `apps/api/tests/integration/test_draft_repository.py` with tests: create draft, get by ID, list by case_file with status filter, optimistic locking (version mismatch → None), update_status increments version. Covers RF-04.1, RF-06.1, RF-07.1, RF-07.2
- [x] T052 [P] Create `apps/api/tests/integration/test_generation_attempt_repository.py` with tests: create attempt, get by idempotency_key, list by case_file, update attempt, delete by idempotency_key, cleanup_expired. Covers RF-03.1, RF-03.3, idempotencia
- [x] T053 [P] Create `apps/api/tests/integration/test_designation_repository.py` with tests: create designation, get by case_file_id, update designation, unique constraint on case_file_id. Covers designation CRUD
- [ ] T054 Create `apps/api/tests/integration/test_003_uow_transactions.py` with tests: UoW commit persists across 5 new tables, UoW rollback discards all, atomic draft creation + transition record, template versioning atomicity. Covers RNF-003 (atomicidad)
- [ ] T055 Create `apps/api/tests/integration/test_003_migrations.py` with tests: upgrade from 002 to 003 applies cleanly, all 5 new tables created, downgrade back to 002 drops all 5 tables, verify existing 001/002 tables unchanged. Covers RNF-02 (migration)

---

## Phase 13: Regresión de Incrementos Anteriores

**Purpose**: Verificar que los endpoints y modelos existentes no se modificaron.

- [x] T056 Run existing contract tests `tests/contract/test_health_live.py`, `tests/contract/test_health_ready.py`, `tests/contract/test_health_dependencies.py` and verify they pass unchanged. Covers RB-019 (health endpoints unchanged)
- [x] T057 Run existing tests `tests/contract/test_employee_endpoints.py`, `tests/contract/test_case_file_endpoints.py`, `tests/contract/test_error_response.py` and verify they pass unchanged. Verify no changes to employee or case_file endpoints. Covers backward compatibility
- [x] T058 Run existing integration tests `tests/integration/test_employee_repository.py`, `tests/integration/test_case_file_repository.py`, `tests/integration/test_migrations.py`, `tests/integration/test_postgres.py` and verify pgvector still available, 001/002 migrations still apply. Covers RB-018 (pgvector), backward compatibility

---

## Phase 14: Pruebas Ollama (Mock-Based)

**Purpose**: Verificar integración Ollama con mocks para todos los escenarios de error.

- [ ] T059 Create `apps/api/tests/integration/test_ollama_integration.py` with mock-based tests: Ollama success → draft created + generation_attempt COMPLETED, Ollama timeout → 504 OLLAMA_TIMEOUT + no draft + attempt FAILED, Ollama 401/403 → error + no draft, Ollama 404 model not found → error, Ollama 429 rate limited → error, Ollama 5xx → error, Ollama invalid JSON → error, Ollama empty response → error, Ollama connection reset → error, OLLAMA_API_TOKEN never in error messages. Covers RF-03.1 (Ollama scenarios)

---

## Phase 15: Docker, Documentación y Validación Final

**Purpose**: Linting, type checking, cobertura, Docker Compose, validación completa.

- [x] T060 Run `ruff check apps/api/src/` and fix all linting errors. Run `ruff format apps/api/src/` and verify formatting. Run `mypy apps/api/src/` and fix all type errors. Verify zero errors in all three tools. Covers constitution XV (Calidad de Código)
- [x] T061 Run `pytest apps/api/tests/ -v --cov=legal_ai --cov-report=term-missing` and verify coverage >= 85%. Verify all tests pass: unit (test_draft_state_machine, test_template_service, test_generation_context, test_prompt_builder, test_draft_service, test_idempotency, test_generation_attempt), contract (test_templates_endpoints, test_designation_endpoints, test_drafts_endpoints, test_generation_endpoints, test_003_error_response, test_health_*), integration (test_template_repository, test_draft_repository, test_generation_attempt_repository, test_designation_repository, test_003_uow_transactions, test_003_migrations, test_ollama_integration). Covers RNF-005 (Testabilidad)
- [x] T062 Verify Docker Compose operational: `docker compose down --volumes --remove-orphans`, `docker compose up -d`, verify postgres and api containers healthy, run migration `docker compose exec api alembic upgrade head`, verify all 5 new tables created (document_templates, designation_data, document_drafts, draft_transitions, generation_attempts), verify existing tables unchanged, verify pgvector still installed, verify health endpoints respond. Covers RNF-006 (Compatibilidad)
- [ ] T063 Final validation checklist: verify all 17 endpoints implemented and functional, verify all 22 error codes mapped correctly, verify draft state machine has exactly 4 transitions, verify template versioning creates new versions on content change, verify optimistic locking returns 409 on version mismatch, verify idempotency with Idempotency-Key header, verify context_snapshot is immutable after creation, verify prompt_content never exposed via API or logs, verify health endpoints unchanged, verify no real personal data in tests/fixtures, verify no DELETE endpoints, verify no authentication implemented, verify no frontend code, verify no embeddings/Redis/PDF/DOCX/Kubernetes/Terraform/Helm tasks. Covers all RF, RNF

---

## Dependencies & Execution Order

### Phase Dependencies

| Phase | Depends On | Blocks |
|-------|-----------|--------|
| Phase 1: Enums y Dominio Puro | None | Phase 2, 3, 4, 5 |
| Phase 2: Modelos ORM y Migración | Phase 1 | Phase 4 |
| Phase 3: Puertos y Unit of Work | Phase 1 | Phase 4, 5 |
| Phase 4: Adaptadores SQLAlchemy | Phase 2, 3 | Phase 5 |
| Phase 5: Servicios de Aplicación | Phase 4 | Phase 6, 7, 8, 9 |
| Phase 6: Schemas y Errores HTTP | Phase 1 | Phase 7, 8, 9 |
| Phase 7: Endpoints Templates | Phase 5, 6 | Phase 10 |
| Phase 8: Endpoints Designation | Phase 5, 6 | Phase 10 |
| Phase 9: Endpoints Drafts y Generación | Phase 5, 6 | Phase 10 |
| Phase 10: Pruebas Unitarias | Phase 1, 5, 6 | Phase 11 |
| Phase 11: Pruebas Contractuales | Phase 7, 8, 9 | Phase 12 |
| Phase 12: Pruebas de Integración | Phase 4, 5 | Phase 13 |
| Phase 13: Regresión | Phase 12 | Phase 14 |
| Phase 14: Pruebas Ollama | Phase 13 | Phase 15 |
| Phase 15: Docker y Validación Final | Phase 14 | None |

### Parallel Opportunities

- **T002, T003, T004, T005**: All create independent domain dataclasses
- **T009, T010, T011, T012**: All create independent port protocols
- **T015, T016, T017, T018**: All create independent repository adapters
- **T026, T027, T028**: Create independent schema files
- **T039, T040, T041, T042, T043, T044**: Create independent unit test files
- **T046, T047, T048, T049**: Create independent contract test files
- **T051, T052, T053**: Create independent integration test files

### Critical Path

T001 → T002 → T006 → T013 → T019 → T030 → T045 → T055 → T061 → T063

---

## Implementation Strategy

### Domain Layer First (Phases 1-4)
Implement enums, domain dataclasses, ORM models, migration, ports, repositories, and Unit of Work. This creates a testable data layer without HTTP or business logic.

### Business Logic (Phase 5)
Implement all services: template versioning, designation CRUD, context building, prompt rendering, Ollama client, and draft lifecycle management. This is the core of the increment.

### API Layer (Phases 6-9)
Add schemas, error handling, and all 17 endpoints. The API is now callable via HTTP.

### Validation (Phases 10-15)
Write all tests (unit, contract, integration), verify regression, test Ollama integration with mocks, run linting/type checking, verify Docker Compose, and perform final validation.

### Incremental Delivery
Each phase produces independently verifiable artifacts. Checkpoints at:
- Phase 1: Domain enums and state machine pass unit tests
- Phase 4: Repositories pass integration tests with PostgreSQL
- Phase 9: All 17 endpoints pass contract tests
- Phase 12: Full test suite passes with coverage >= 85%
- Phase 15: Docker Compose operational, all validation criteria met

---

## Notes

- [P] tasks = different files, no dependencies within same phase
- All tests use fictional data, never real personal data
- Health endpoints remain unchanged from 001/002
- No DELETE endpoints for any entity (immutable by design)
- No authentication in this increment
- No embeddings, vectors, RAG, Redis, PDF, DOCX, Kubernetes, Terraform, Helm (excluded scope)
- `TemplateDocumentType` uses different name than existing `DocumentType` (employee documents) to avoid naming conflict
- `case_number` format `CF-{uuid4}` unchanged from 002
- `closed_at` only set on transition to archived (unchanged from 002)
- Optimistic locking via `version` field on drafts (same pattern as case_files in 002)
- Ollama transaction pattern: register attempt → release transaction → call Ollama → persist result (never hold DB during HTTP)
- Context snapshot is immutable once created (SHA-256 hash for verification)
- Idempotency via `Idempotency-Key` header with 24-hour window
- `prompt_content` stored but NEVER exposed via API, logs, or error messages
