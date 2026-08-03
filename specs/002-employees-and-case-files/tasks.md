# Tasks: Empleados y Expedientes Administrativos

**Input**: Design documents from `/specs/002-employees-and-case-files/`
**Prerequisites**: plan.md (required), spec.md (required)

## Format: `[ID] [P?] Description`

- **[ID]**: Sequential task number (T001, T002, T003...)
- **[P]**: Can run in parallel (different files, no dependencies) - optional
- **Description**: Clear action with exact file path included

---

## Phase 1: Preparación y Estructura

**Purpose**: Definir enums, normalizadores y máquina de estados como base pura sin dependencias de BD.

- [X] T001 Create `apps/api/src/legal_ai/domain/enums.py` with `DocumentType(StrEnum)`, `CaseStatus(StrEnum)`, `CaseType(StrEnum)` — DocumentType: dni, lc, le, ci, pasaporte; CaseStatus: draft, under_review, in_process, submitted, approved, rejected, archived; CaseType: designacion, licencia, renuncia, contratacion, otro. Covers RF-001 (document_type enum), RF-011 (case_type StrEnum), RF-016 (CaseStatus)
- [X] T002 [P] Create `apps/api/src/legal_ai/domain/normalization.py` with pure functions: `normalize_document_number(doc_type, value)` (DNI=digits only; LC/LE/CI/passport=alphanumeric uppercase; trim; reject empty), `normalize_cuil(value)` (trim, remove separators, digits only, must be 11 digits), `normalize_email(value)` (trim, lowercase), `normalize_phone(value)` (trim, remove spaces), `normalize_text(value)` (trim, reject empty). Covers RF-008, RF-009
- [X] T003 [P] Create `apps/api/src/legal_ai/domain/case_file.py` with `VALID_TRANSITIONS: dict[CaseStatus, set[CaseStatus]]` (10 transitions: draft→under_review; under_review→{in_process,draft}; in_process→{submitted,under_review}; submitted→{approved,rejected}; rejected→{under_review,archived}; approved→archived; archived→empty), `can_transition(from_status, to_status) -> bool`, `TRANSITIONS_INITIAL_HISTORY_CHANGED_BY = "system"`. Covers RB-006 through RB-013, RF-016, RB-019 (health endpoints unchanged)
- [X] T004 [P] Create `apps/api/src/legal_ai/domain/__init__.py` if missing, and ensure `apps/api/src/legal_ai/ports/__init__.py`, `apps/api/src/legal_ai/adapters/database/__init__.py`, `apps/api/src/legal_ai/schemas/__init__.py`, `apps/api/src/legal_ai/application/__init__.py`, `apps/api/src/legal_ai/api/routes/__init__.py` exist. Covers project structure

---

## Phase 2: Dominio y Normalización

**Purpose**: Definir dataclasses de dominio Employee, CaseFile, CaseStatusHistory.

- [X] T005 Create `apps/api/src/legal_ai/domain/employee.py` with dataclass `Employee` (id: UUID, employee_number: str, first_name: str, last_name: str, document_type: DocumentType, document_number: str, cuil: str | None, email: str | None, phone: str | None, position: str | None, department: str | None, active: bool, created_at: datetime, updated_at: datetime). Covers RF-001, RF-006
- [X] T006 [P] Create `apps/api/src/legal_ai/domain/case_file.py` (extend with dataclass `CaseFile` in same file as T003): id: UUID, case_number: str, employee_id: UUID, title: str, description: str | None, case_type: CaseType, status: CaseStatus, version: int, opened_at: datetime, created_at: datetime, updated_at: datetime, closed_at: datetime | None. Covers RF-011, RF-011a
- [X] T007 [P] Create `apps/api/src/legal_ai/domain/case_status_history.py` with dataclass `CaseStatusHistory` (id: UUID, case_file_id: UUID, from_status: CaseStatus | None, to_status: CaseStatus, changed_at: datetime, changed_by: str, reason: str | None, request_id: str | None). Covers RF-017

---

## Phase 3: Modelos ORM y Migración

**Purpose**: Definir modelos SQLAlchemy y migración Alembic 002.

- [X] T008 Create `apps/api/src/legal_ai/adapters/database/models.py` with SQLAlchemy ORM models: `EmployeeModel` (employees table), `CaseFileModel` (case_files table), `CaseStatusHistoryModel` (case_status_history table). All columns, constraints (UNIQUE on employee_number; UNIQUE on document_type+document_number; UNIQUE on cuil; FK employee_id→employees; FK case_file_id→case_files; DEFAULT values for active, status, version, timestamps). Covers RNF-004 (constraints, FK, indexes)
- [X] T009 Create `apps/api/src/legal_ai/alembic/versions/002_employees_and_case_files.py` migration: `down_revision = "001"`, create tables employees→case_files→case_status_history (respecting FK order), create 14 indexes (ix_employees_employee_number UNIQUE, ix_employees_document UNIQUE, ix_employees_cuil UNIQUE partial WHERE cuil IS NOT NULL, ix_employees_active, ix_employees_department, ix_employees_created_at, ix_case_files_case_number UNIQUE, ix_case_files_employee_id, ix_case_files_status, ix_case_files_case_type, ix_case_files_opened_at, ix_case_files_created_at, ix_history_case_file_id, ix_history_changed_at), downgrade drops tables in reverse order. Covers RNF-004 (migration versionada)
- [X] T010 Update `apps/api/src/legal_ai/alembic/env.py` to import metadata from `adapters/database/models.py` for `target_metadata`. Verify `001_enable_pgvector.py` is still referenced correctly. Covers RNF-004

---

## Phase 4: Puertos y Unit of Work

**Purpose**: Definir interfaces de repositorio y Unit of Work para transacciones atómicas.

- [X] T011 Create `apps/api/src/legal_ai/ports/employee_repository.py` with `EmployeeRepository(Protocol)`: `create(employee) -> Employee`, `get_by_id(employee_id: UUID) -> Employee | None`, `get_by_employee_number(number: str) -> Employee | None`, `get_by_document(doc_type: str, doc_number: str) -> Employee | None`, `get_by_cuil(cuil: str) -> Employee | None`, `list(page, page_size, query, active, department) -> tuple[list[Employee], int]`, `update(employee) -> Employee`, `deactivate(employee_id: UUID) -> Employee | None`. Covers RF-001 through RF-010
- [X] T012 [P] Create `apps/api/src/legal_ai/ports/case_file_repository.py` with `CaseFileRepository(Protocol)`: `create(case_file) -> CaseFile`, `get_by_id(case_file_id: UUID) -> CaseFile | None`, `get_by_case_number(number: str) -> CaseFile | None`, `list(page, page_size, query, employee_id, status, case_type, opened_from, opened_to) -> tuple[list[CaseFile], int]`, `update(case_file) -> CaseFile`. Covers RF-011 through RF-019
- [X] T013 [P] Create `apps/api/src/legal_ai/ports/case_status_history_repository.py` with `CaseStatusHistoryRepository(Protocol)`: `create(entry) -> CaseStatusHistory`, `list_by_case_file(case_file_id: UUID) -> list[CaseStatusHistory]`. Covers RF-017
- [X] T014 Create `apps/api/src/legal_ai/adapters/database/unit_of_work.py` with `UnitOfWork` context manager: `__aenter__` creates AsyncSession, begins transaction; `__aexit__` commits or rollback; exposes `employees`, `case_files`, `case_status_history` properties returning repository instances sharing the same session. Covers RNF-003 (transacción atómica), RB-010 (atomicidad)

---

## Phase 5: Adaptadores SQLAlchemy

**Purpose**: Implementar repositorios concretos con SQLAlchemy 2.x async.

- [X] T015 Create `apps/api/src/legal_ai/adapters/database/employee_repository.py` implementing `EmployeeRepository`: SQLAlchemy 2.x async with `select()`, `await session.execute()`, `result.scalars().first()`. For `list()`: dynamic WHERE with ILIKE for query on employee_number/first_name/last_name/document_number, equality for active/department, COUNT(*) total, OFFSET/LIMIT pagination, ORDER BY created_at DESC, id DESC. For `get_by_document()`: query with normalized values. For `get_by_cuil()`: query with normalized value. Covers RF-003, RF-007, RF-008, RF-009
- [X] T016 [P] Create `apps/api/src/legal_ai/adapters/database/case_file_repository.py` implementing `CaseFileRepository`: same strategy as employee. For `list()`: ILIKE on case_number/title, equality on employee_id/status/case_type, date range on opened_at. Covers RF-013, RF-018
- [X] T017 [P] Create `apps/api/src/legal_ai/adapters/database/case_status_history_repository.py` implementing `CaseStatusHistoryRepository`: `create()` inserts entry; `list_by_case_file()` returns all ordered by `changed_at ASC, id ASC`. Covers RF-017

---

## Phase 6: Servicios de Aplicación

**Purpose**: Implementar lógica de negocio (normalización, validaciones, atomicidad).

- [X] T018 Create `apps/api/src/legal_ai/application/employee_service.py` with `EmployeeService`: `create()` normalizes document_number/cuil/email/phone, validates uniqueness (EMPLOYEE_NUMBER_CONFLICT, EMPLOYEE_DOCUMENT_CONFLICT with field="cuil" or "document_number"), returns EmployeeResponse 201. `get_by_id()` returns 404 if not found. `list()` returns paginated results. `update()` validates path (422) then body (at least one field, 422 if empty), applies partial update, returns 200. `deactivate()` idempotent: if active → set false + update updated_at; if already inactive → return current resource 200. Covers RF-001 through RF-010
- [X] T019 Create `apps/api/src/legal_ai/application/case_file_service.py` with `CaseFileService`: `create()` validates employee_id UUID (422), employee exists (404), employee active (422 EMPLOYEE_INACTIVE), generates `CF-{uuid4}` case_number, creates CaseFile + initial CaseStatusHistory atomically (from_status=null, to_status=draft, changed_by="system", reason=null, request_id from context), returns 201. `get_by_id()` returns 404 if not found. `list()` returns paginated results. `update()` validates archived (409 CASE_FILE_ARCHIVED), validates expected_version (409 CONCURRENT_MODIFICATION), updates title/description + version + updated_at, returns 200. `transition()` validates UUID (422), exists (404), archived (409), can_transition (409 INVALID_STATUS_TRANSITION), expected_version (409 CONCURRENT_MODIFICATION), updates status + version + updated_at + closed_at if archived, creates history atomically, returns 200. `get_history()` returns HistoryResponse with items ordered by changed_at ASC, id ASC. Covers RF-011 through RF-019, RB-001 through RB-015

---

## Phase 7: Schemas y Errores HTTP

**Purpose**: Definir schemas Pydantic v2 request/response y manejo de errores estructurados.

- [X] T020 Create `apps/api/src/legal_ai/schemas/employee.py` with `CreateEmployeeRequest(BaseModel)` (employee_number, first_name, last_name, document_type: DocumentType, document_number, cuil?, email?, phone?, position?, department?; extra="forbid"), `UpdateEmployeeRequest(BaseModel)` (first_name?, last_name?, email?, phone?, position?, department?; extra="forbid"), `EmployeeResponse(BaseModel)` (id: UUID, employee_number, first_name, last_name, document_type, document_number, cuil?, email?, phone?, position?, department?, active: bool, created_at: datetime, updated_at: datetime). Covers RF-001, RF-005, RF-006
- [X] T021 [P] Create `apps/api/src/legal_ai/schemas/case_file.py` with `CreateCaseFileRequest(BaseModel)` (employee_id: UUID, title, case_type: CaseType, description?; extra="forbid"), `UpdateCaseFileRequest(BaseModel)` (title?, description?, expected_version: int; extra="forbid"), `TransitionRequest(BaseModel)` (status: CaseStatus, expected_version: int, changed_by: str, reason?; extra="forbid"), `HistoryItem(BaseModel)` (id: UUID, case_file_id: UUID, from_status?: CaseStatus, to_status: CaseStatus, changed_at: datetime, changed_by: str, reason?: str, request_id?: str), `HistoryResponse(BaseModel)` (items: list[HistoryItem]), `CaseFileResponse(BaseModel)` (id: UUID, case_number, employee_id: UUID, title, description?, case_type: CaseType, status: CaseStatus, version: int, opened_at: datetime, created_at: datetime, updated_at: datetime, closed_at?: datetime). Covers RF-011, RF-011a, RF-015, RF-016, RF-017
- [X] T022 [P] Create `apps/api/src/legal_ai/schemas/pagination.py` with generic `PaginatedResponse(BaseModel, Generic[T])` (page: int, page_size: int, total: int, items: list[T]). Covers RF-020
- [X] T023 Update `apps/api/src/legal_ai/schemas/errors.py`: add `field: str | None = None` to ErrorResponse, add `errors: list[ValidationErrorDetail] | None = None` (only for VALIDATION_ERROR), add `ValidationErrorDetail(BaseModel)` (field: str, code: str, message: str). Covers RF-021 (VALIDATION_ERROR format)
- [X] T024 Create `apps/api/src/legal_ai/api/exceptions.py` with domain exception classes: `NotFoundError(error_code, message, field?)`, `ConflictError(error_code, message, field?)`, `DomainValidationError(error_code, message, errors: list[dict])`, `DatabaseError(error_code, message)`. Each maps to correct HTTP: NotFoundError→404, ConflictError→409, DomainValidationError→422, DatabaseError→500. Covers RF-021 (11 error codes, HTTP mapping)
- [X] T025 Update `apps/api/src/legal_ai/main.py`: register exception handlers for NotFoundError, ConflictError, DomainValidationError, DatabaseError that return JSON with ErrorResponse schema and correct HTTP status codes. Covers RF-021

---

## Phase 8: Endpoints Employees

**Purpose**: Implementar los 5 endpoints de empleados.

- [X] T026 Create `apps/api/src/legal_ai/api/routes/employees.py` with `router = APIRouter(prefix="/api/v1/employees", tags=["employees"])` and 5 endpoints:
  1. `POST /` → create employee, response 201, EmployeeResponse
  2. `GET /{employee_id}` → get by ID, 200 EmployeeResponse, 422 for invalid UUID, 404 if not found
  3. `GET /` → list employees with query params (page, page_size, query, active, department), 200 PaginatedResponse[EmployeeResponse], 422 for invalid params
  4. `PATCH /{employee_id}` → partial update, 200 EmployeeResponse, 422 for invalid UUID/empty body/unknown fields, 404 if not found
  5. `POST /{employee_id}/deactivate` → idempotent deactivate, 200 EmployeeResponse, 422 for invalid UUID, 404 if not found

  Covers RF-001, RF-002, RF-003, RF-005, RF-006b, RF-007, RF-008, RF-009, RF-010, RF-020, RF-021 (UUID validation, empty body, all 11 error codes)
- [X] T027 Update `apps/api/src/legal_ai/api/router.py`: add `from legal_ai.api.routes.employees import router as employees_router` and `router.include_router(employees_router)`. Covers employee endpoints registration

---

## Phase 9: Endpoints Case Files

**Purpose**: Implementar los 6 endpoints de expedientes.

- [X] T028 Create `apps/api/src/legal_ai/api/routes/case_files.py` with `router = APIRouter(prefix="/api/v1/case-files", tags=["case-files"])` and 6 endpoints:
  1. `POST /` → create case file, response 201, CaseFileResponse, 422 for invalid employee_id UUID, 404 if employee not found, 422 if employee inactive
  2. `GET /{case_file_id}` → get by ID, 200 CaseFileResponse, 422 for invalid UUID, 404 if not found
  3. `GET /` → list case files with query params (page, page_size, query, employee_id, status, case_type, opened_from, opened_to), 200 PaginatedResponse[CaseFileResponse], 422 for invalid params
  4. `PATCH /{case_file_id}` → partial update with expected_version, 200 CaseFileResponse, 422 for invalid UUID/empty body/unknown fields, 404 if not found, 409 if archived (CASE_FILE_ARCHIVED), 409 if version mismatch (CONCURRENT_MODIFICATION)
  5. `POST /{case_file_id}/transitions` → state transition, 200 CaseFileResponse, 422 for invalid UUID, 404 if not found, 409 if archived/invalid transition/version mismatch, creates history atomically
  6. `GET /{case_file_id}/history` → get history, 200 HistoryResponse, 422 for invalid UUID, 404 if not found

  Covers RF-011 through RF-019, RF-020, RF-021 (UUID validation, all error codes, empty body policy)
- [X] T029 Update `apps/api/src/legal_ai/api/router.py`: add `from legal_ai.api.routes.case_files import router as case_files_router` and `router.include_router(case_files_router)`. Covers case files endpoints registration

---

## Phase 10: Historial y Transiciones

**Purpose**: Integrar máquina de estados con endpoints y verificar atomicidad.

- [X] T030 Verify in `apps/api/src/legal_ai/application/case_file_service.py` that `transition()` implements the exact 10-state machine: validates `can_transition()` before any DB change, uses `from_status` from persisted state (not request), increments version atomically, creates CaseStatusHistory in same transaction, sets `closed_at` only when `to_status == CaseStatus.ARCHIVED`, rolls back completely on any failure. Verify `create()` for case files writes initial history with `changed_by="system"`, `from_status=null`, `to_status=draft`, `reason=null`. Covers RB-006 through RB-013, RF-016 (atomicidad 8 pasos), RF-019 (concurrencia), RF-011 (historial inicial)

---

## Phase 11: Pruebas Unitarias

**Purpose**: Pruebas de lógica pura: normalizadores, máquina de estados, schemas.

- [X] T031 Create `apps/api/tests/unit/test_normalization.py` with tests for all 5 normalization functions: `normalize_document_number` (DNI digits only, LC/LE/CI/passport alphanumeric uppercase, trim, reject empty), `normalize_cuil` (trim, remove separators, digits only, must be 11 digits, reject non-digits), `normalize_email` (trim, lowercase), `normalize_phone` (trim, remove spaces), `normalize_text` (trim, reject empty). Include edge cases: empty strings, whitespace-only, mixed case, special characters. Covers RF-008, RF-009
- [X] T032 [P] Create `apps/api/tests/unit/test_state_machine.py` with tests for complete state machine: all 10 valid transitions return True, same-state transition returns False, archived→any returns False, approved→draft returns False, random jumps return False. Test `closed_at` rules: only set when to_status=archived. Test `TRANSITIONS_INITIAL_HISTORY_CHANGED_BY` = "system". Covers RB-006 through RB-013, RF-016
- [X] T033 [P] Create `apps/api/tests/unit/test_schemas.py` (extend existing `test_schemas.py` or create new file) with tests for: CreateEmployeeRequest validation (required fields, extra fields forbidden), UpdateEmployeeRequest validation (at least one field, extra forbidden), CreateCaseFileRequest validation (required fields, case_type enum values), UpdateCaseFileRequest validation (expected_version required, at least title/description), TransitionRequest validation (status enum, expected_version, changed_by required), EmployeeResponse serialization, CaseFileResponse serialization, HistoryResponse serialization, PaginatedResponse serialization. Covers RF-001, RF-005, RF-006, RF-011, RF-011a, RF-015, RF-016, RF-017, RF-020

---

## Phase 12: Pruebas Contractuales

**Purpose**: Verificar schemas de respuesta de los 11 endpoints y estructura de errores.

- [X] T034 Create `apps/api/tests/contract/test_employee_endpoints.py` with contract tests using `httpx.AsyncClient` with `ASGITransport`: verify POST /employees returns 201 with exact EmployeeResponse schema; GET /employees/{id} returns 200 with EmployeeResponse; GET /employees returns 200 with PaginatedResponse[EmployeeResponse]; PATCH /employees/{id} returns 200 with EmployeeResponse; POST /employees/{id}/deactivate returns 200 with EmployeeResponse. Verify 422 for invalid UUID path, 404 for nonexistent, 409 for conflicts. Covers RF-001, RF-002, RF-003, RF-005, RF-006b
- [X] T035 [P] Create `apps/api/tests/contract/test_case_file_endpoints.py` with contract tests: POST /case-files returns 201 with CaseFileResponse; GET /case-files/{id} returns 200; GET /case-files returns 200 with PaginatedResponse; PATCH /case-files/{id} returns 200; POST /case-files/{id}/transitions returns 200; GET /case-files/{id}/history returns 200 with HistoryResponse. Verify all error codes: 404, 409 (CASE_FILE_ARCHIVED, CONCURRENT_MODIFICATION, INVALID_STATUS_TRANSITION, CASE_NUMBER_CONFLICT), 422, 500. Covers RF-011 through RF-019
- [X] T036 [P] Create `apps/api/tests/contract/test_error_response.py` with tests for: VALIDATION_ERROR format (error_code, message, errors array with field/code/message, request_id), unknown fields produce code="extra_forbidden", empty body produces errors for all required fields, no sensitive values in error messages, consistent HTTP mapping for all 11 error codes. Covers RF-021

---

## Phase 13: Pruebas de Integración PostgreSQL

**Purpose**: Verificar repositorios, UoW y migraciones con PostgreSQL real.

- [X] T037 Create `apps/api/tests/integration/test_employee_repository.py` with tests: create employee and retrieve by ID, uniqueness of employee_number (duplicate raises), uniqueness of document_type+document_number (duplicate raises), uniqueness of cuil (duplicate raises), list with pagination, list with filters (active, department, query), update employee fields, deactivate employee (idempotent: active→inactive, inactive→inactive returns same), document normalization persisted correctly. Covers RF-001, RF-003, RF-005, RF-006b, RF-007, RF-008, RF-009
- [X] T038 [P] Create `apps/api/tests/integration/test_case_file_repository.py` with tests: create case file, get by ID, get by case_number, list with filters (employee_id, status, case_type, date range, query), list pagination, update with version increment, case_number uniqueness. Covers RF-011, RF-013, RF-015, RF-018
- [X] T039 [P] Create `apps/api/tests/integration/test_case_status_history_repository.py` with tests: create history entry, list by case_file ordered by changed_at ASC id ASC, initial history entry has from_status=null. Covers RF-017
- [X] T040 Create `apps/api/tests/integration/test_uow_transactions.py` with tests: UoW commit persists changes, UoW rollback discards all changes (case file + history not persisted), atomic creation of case file + initial history (both succeed or both fail), transition atomicity (status + version + history in same transaction). Covers RNF-003 (atomicidad), RB-010 (atomicidad)

---

## Phase 14: Regresión del Incremento 001

**Purpose**: Verificar que los endpoints de health y pgvector no se modificaron.

- [X] T041 Run existing contract tests `tests/contract/test_health_live.py`, `tests/contract/test_health_ready.py`, `tests/contract/test_health_dependencies.py` and verify they pass unchanged. Verify no new health endpoints added, no changes to health response schemas, no changes to health status codes. Covers RB-016, RB-019
- [X] T042 Run existing integration test `tests/integration/test_postgres.py` and verify pgvector extension is still available. Run `tests/integration/test_migrations.py` and verify 001 migration still applies. Verify new 002 migration applies cleanly on top. Covers RB-018 (pgvector permanece instalado)

---

## Phase 15: Docker, Documentación y Validación Final

**Purpose**: Linting, type checking, cobertura, Docker Compose, validación completa.

- [X] T043 Run `ruff check apps/api/src/` and fix all linting errors. Run `ruff format apps/api/src/` and verify formatting. Run `mypy apps/api/src/` and fix all type errors. Verify zero errors in all three tools. Covers constitution XV (Calidad de Código)
- [X] T044 Run `pytest apps/api/tests/ -v --cov=legal_ai --cov-report=term-missing` and verify coverage >= 85%. Verify all tests pass: unit (test_normalization, test_state_machine, test_schemas), contract (test_employee_endpoints, test_case_file_endpoints, test_error_response, test_health_*), integration (test_employee_repository, test_case_file_repository, test_case_status_history_repository, test_uow_transactions, test_migrations, test_postgres). Covers RNF-007 (Testabilidad)
- [X] T045 Verify Docker Compose operational: `docker compose down --volumes --remove-orphans`, `docker compose up -d`, verify postgres and api containers healthy, run migration `docker compose exec api alembic upgrade head`, verify all 3 tables created (employees, case_files, case_status_history), verify pgvector still installed, verify health endpoints respond, run smoke test on a few endpoints. Covers RNF-006 (Compatibilidad)
- [X] T046 Final validation checklist: verify all 11 endpoints implemented and functional, verify all 11 error codes mapped correctly, verify state machine has exactly 10 transitions, verify health endpoints unchanged, verify no data personal real in tests/fixtures, verify case_type is StrEnum with 5 values, verify changed_by="system" for initial history, verify no DELETE endpoints exist, verify no authentication implemented, verify no frontend code, verify no Ollama/Redis/embeddings/OCR/PDF/DOCX/Kubernetes/Terraform/Helm tasks. Covers all RF, RB, RNF

---

## Dependencies & Execution Order

### Phase Dependencies

| Phase | Depends On | Blocks |
|-------|-----------|--------|
| Phase 1: Preparación y Estructura | None | Phase 2, 3, 4 |
| Phase 2: Dominio y Normalización | Phase 1 | Phase 3, 4, 5 |
| Phase 3: Modelos ORM y Migración | Phase 2 | Phase 4, 5 |
| Phase 4: Puertos y Unit of Work | Phase 2 | Phase 5, 6 |
| Phase 5: Adaptadores SQLAlchemy | Phase 3, 4 | Phase 6 |
| Phase 6: Servicios de Aplicación | Phase 4, 5 | Phase 7, 8, 9 |
| Phase 7: Schemas y Errores HTTP | Phase 2 | Phase 8, 9 |
| Phase 8: Endpoints Employees | Phase 6, 7 | Phase 10 |
| Phase 9: Endpoints Case Files | Phase 6, 7 | Phase 10 |
| Phase 10: Historial y Transiciones | Phase 8, 9 | Phase 11 |
| Phase 11: Pruebas Unitarias | Phase 1, 2, 7 | Phase 12 |
| Phase 12: Pruebas Contractuales | Phase 8, 9 | Phase 13 |
| Phase 13: Pruebas de Integración | Phase 5, 10 | Phase 14 |
| Phase 14: Regresión Incremento 001 | Phase 13 | Phase 15 |
| Phase 15: Docker y Validación Final | Phase 14 | None |

### Parallel Opportunities

- **T001, T002, T003, T004**: All create independent domain files, no dependencies
- **T005, T006, T007**: All create independent domain dataclasses
- **T011, T012, T013**: All create independent port protocols
- **T015, T016, T017**: All create independent repository adapters
- **T021, T022**: Create independent schema files
- **T032, T033**: Create independent unit test files
- **T035, T036**: Create independent contract test files
- **T038, T039**: Create independent integration test files

### Critical Path

T001 → T005 → T008 → T014 → T018 → T026 → T034 → T040 → T044 → T046

---

## Implementation Strategy

### MVP First (Phases 1-6)
Implement domain layer (enums, normalization, state machine, dataclasses), ORM models, migration, repositories, Unit of Work, and application services. This creates a testable backend without HTTP.

### API Layer (Phases 7-9)
Add schemas, error handling, and all 11 endpoints. The API is now callable via HTTP.

### Validation (Phases 10-15)
Integrate state machine verification, write all tests (unit, contract, integration), verify regression, run linting/type checking, verify Docker Compose, and perform final validation.

### Incremental Delivery
Each phase produces independently verifiable artifacts. Checkpoints at:
- Phase 1: Domain enums and normalization functions pass unit tests
- Phase 5: Repositories pass integration tests with PostgreSQL
- Phase 9: All 11 endpoints pass contract tests
- Phase 13: Full test suite passes with coverage >= 85%
- Phase 15: Docker Compose operational, all validation criteria met

---

## Notes

- [P] tasks = different files, no dependencies within same phase
- All tests use fictional data, never real personal data (RNF-001, RNF-002)
- Health endpoints remain unchanged (RB-016, RB-019)
- No DELETE endpoints for any entity (RB-014)
- No authentication in this increment (RB-017)
- No embeddings, vectors, Ollama for generation, Redis, PDF, DOCX, Kubernetes, Terraform, Helm (excluded scope)
- `case_type` is StrEnum with 5 fixed values, no admin endpoints
- `changed_by` = "system" for initial history, authenticated identity replaces in future increment
- `case_number` format: `CF-{uuid4}`, generated server-side, immutable
- `closed_at` only set on transition to archived, immutable once set
- Optimistic locking via `version` field on case_files only (employees have no version)
