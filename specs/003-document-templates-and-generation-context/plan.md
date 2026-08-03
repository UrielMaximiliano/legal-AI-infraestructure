# Plan Técnico: Incremento 003 — Plantillas, Contexto de Generación y Borradores

## 1. Resumen Ejecutivo

Este incremento construye la capa de generación de documentos jurídicos: entidades **DocumentTemplate**, **DocumentDraft**, **DraftTransition**, **GenerationAttempt** y **DesignationData** con CRUD completo, máquina de estados de borradores, control de concurrencia optimista, renderizado seguro de plantillas, integración con Ollama para generación de contenido, idempotencia de generación y 17 endpoints de negocio. Se apoya en la arquitectura hexagonal existente (adapters/ports/domain/application/schemas) y extiende el patrón de migraciones Alembic sin alterar los contratos de incrementos 001 y 002.

---

## 2. Modelo de Datos

### 2.1 Enums (StrEnum, Python puro)

```python
class DocumentType(StrEnum):
    RESOLUCION = "resolucion"
    INFORME = "informe"
    OFICIO = "oficio"
    SOLICITUD = "solicitud"
    ACUERDO = "acuerdo"
    OTROS = "otros"

class DraftStatus(StrEnum):
    GENERADO = "generado"
    EN_REVISION = "en_revision"
    APROBADO = "aprobado"
    RECHAZADO = "rechazado"
    SUPERSEDED = "superseded"

class TransitionAction(StrEnum):
    SEND_TO_REVIEW = "send_to_review"
    APPROVE = "approve"
    REJECT = "reject"
    EDIT_CONTENT = "edit_content"

class GenerationStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
```

Ubicación: `domain/enums.py`

### 2.2 Tabla `document_templates`

| Columna | Tipo SQL | Constraints |
|---|---|---|
| `id` | `UUID` DEFAULT gen_random_uuid() | PK |
| `name` | `VARCHAR(200)` | NOT NULL |
| `document_type` | `VARCHAR(50)` | NOT NULL |
| `version` | `INTEGER` | NOT NULL, DEFAULT 1 |
| `organ_emisor` | `VARCHAR(200)` | NULL |
| `normativa` | `TEXT` | NULL |
| `description` | `TEXT` | NULL |
| `body_template` | `TEXT` | NOT NULL |
| `variables` | `JSONB` | DEFAULT '[]'::jsonb |
| `is_active` | `BOOLEAN` | DEFAULT true |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT now() |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT now() |

**Constraint compuesta**: `uq_template_name_type_version` UNIQUE (`name`, `document_type`, `version`)

### 2.3 Tabla `designation_data`

| Columna | Tipo SQL | Constraints |
|---|---|---|
| `id` | `UUID` DEFAULT gen_random_uuid() | PK |
| `case_file_id` | `UUID` | NOT NULL, UNIQUE, FK → case_files(id) |
| `position_name` | `VARCHAR(200)` | NOT NULL |
| `organizational_unit` | `VARCHAR(200)` | NULL |
| `start_date` | `DATE` | NULL |
| `legal_basis` | `TEXT` | NULL |
| `appointing_authority` | `VARCHAR(200)` | NULL |
| `salary_category` | `VARCHAR(100)` | NULL |
| `work_schedule` | `VARCHAR(100)` | NULL |
| `observations` | `TEXT` | NULL |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT now() |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT now() |

**FK**: `fk_designation_case_file` FOREIGN KEY (`case_file_id`) REFERENCES `case_files(id)`

### 2.4 Tabla `document_drafts`

| Columna | Tipo SQL | Constraints |
|---|---|---|
| `id` | `UUID` DEFAULT gen_random_uuid() | PK |
| `template_id` | `UUID` | NOT NULL, FK → document_templates(id) |
| `case_file_id` | `UUID` | NOT NULL, FK → case_files(id) |
| `title` | `VARCHAR(300)` | NOT NULL |
| `content` | `TEXT` | NULL |
| `status` | `VARCHAR(20)` | NOT NULL, DEFAULT 'generado' |
| `version` | `INTEGER` | NOT NULL, DEFAULT 1 |
| `generation_number` | `INTEGER` | NOT NULL, DEFAULT 1 |
| `context_snapshot` | `JSONB` | NOT NULL |
| `context_hash` | `VARCHAR(64)` | NOT NULL |
| `variables_used` | `JSONB` | DEFAULT '{}'::jsonb |
| `parent_draft_id` | `UUID` | NULL, FK → document_drafts(id) |
| `observations` | `TEXT` | NULL |
| `request_id` | `VARCHAR(100)` | NULL |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT now() |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT now() |

**FK**: `fk_drafts_template` FOREIGN KEY (`template_id`) REFERENCES `document_templates(id)`
**FK**: `fk_drafts_case_file` FOREIGN KEY (`case_file_id`) REFERENCES `case_files(id)`
**FK**: `fk_drafts_parent` FOREIGN KEY (`parent_draft_id`) REFERENCES `document_drafts(id)`

### 2.5 Tabla `draft_transitions`

| Columna | Tipo SQL | Constraints |
|---|---|---|
| `id` | `UUID` DEFAULT gen_random_uuid() | PK |
| `draft_id` | `UUID` | NOT NULL, FK → document_drafts(id) |
| `from_status` | `VARCHAR(20)` | NOT NULL |
| `to_status` | `VARCHAR(20)` | NOT NULL |
| `action` | `VARCHAR(50)` | NOT NULL |
| `observations` | `TEXT` | NULL |
| `performed_by` | `VARCHAR(100)` | NULL |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT now() |

**FK**: `fk_transitions_draft` FOREIGN KEY (`draft_id`) REFERENCES `document_drafts(id)`

### 2.6 Tabla `generation_attempts`

| Columna | Tipo SQL | Constraints |
|---|---|---|
| `id` | `UUID` DEFAULT gen_random_uuid() | PK |
| `case_file_id` | `UUID` | NOT NULL, FK → case_files(id) |
| `template_id` | `UUID` | NOT NULL, FK → document_templates(id) |
| `idempotency_key` | `VARCHAR(100)` | UNIQUE, NULL |
| `model` | `VARCHAR(100)` | NOT NULL |
| `prompt_hash` | `VARCHAR(64)` | NOT NULL |
| `prompt_content` | `TEXT` | NOT NULL |
| `status` | `VARCHAR(20)` | NOT NULL, DEFAULT 'in_progress' |
| `started_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT now() |
| `completed_at` | `TIMESTAMPTZ` | NULL |
| `error_code` | `VARCHAR(50)` | NULL |
| `error_message` | `TEXT` | NULL |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT now() |

**FK**: `fk_attempts_case_file` FOREIGN KEY (`case_file_id`) REFERENCES `case_files(id)`
**FK**: `fk_attempts_template` FOREIGN KEY (`template_id`) REFERENCES `document_templates(id)`

---

## 3. Migración Alembic

**Archivo**: `alembic/versions/003_templates_drafts_and_generation.py`
**Revisión**: `003`
**Depende de**: `002`

### Estrategia:
- Crear tablas en orden: `document_templates` → `designation_data` → `document_drafts` → `draft_transitions` → `generation_attempts` (respetando FKs)
- Usar `op.create_table()` con definición completa de columnas y constraints
- Crear índices en la misma migración
- En `downgrade()`: eliminar tablas en orden inverso (`generation_attempts` → `draft_transitions` → `document_drafts` → `designation_data` → `document_templates`)
- No alterar tablas existentes de incrementos anteriores

### Índices a crear:

| Tabla | Índice | Columnas | Tipo |
|---|---|---|---|
| `document_templates` | `ix_templates_document_type` | `document_type` | B-tree |
| `document_templates` | `ix_templates_is_active` | `is_active` | B-tree |
| `document_templates` | `ix_templates_name` | `name` | B-tree |
| `designation_data` | `ix_designation_data_case_file_id` | `case_file_id` | B-tree |
| `document_drafts` | `ix_drafts_case_file_id` | `case_file_id` | B-tree |
| `document_drafts` | `ix_drafts_status` | `status` | B-tree |
| `document_drafts` | `ix_drafts_parent_draft_id` | `parent_draft_id` | B-tree |
| `document_drafts` | `ix_drafts_template_id` | `template_id` | B-tree |
| `document_drafts` | `ix_drafts_context_hash` | `context_hash` | B-tree |
| `draft_transitions` | `ix_draft_transitions_draft_id` | `draft_id` | B-tree |
| `generation_attempts` | `ix_generation_attempts_idempotency_key` | `idempotency_key` | UNIQUE |
| `generation_attempts` | `ix_generation_attempts_case_file_id` | `case_file_id` | B-tree |
| `generation_attempts` | `ix_generation_attempts_status` | `status` | B-tree |

---

## 4. Repositories

Patrón Repository async con interfaz (Puerto) y adaptador concreto:

### 4.1 TemplateRepository

**Puerto** (`ports/template_repository.py`):
```python
class TemplateRepository(Protocol):
    async def create(self, template: Template) -> Template: ...
    async def get_by_id(self, template_id: UUID) -> Template | None: ...
    async def get_active_version(self, name: str, document_type: str) -> Template | None: ...
    async def list_active(self, document_type: str | None, search: str | None, skip: int, limit: int) -> tuple[list[Template], int]: ...
    async def update(self, template: Template) -> Template: ...
    async def deactivate_all_versions(self, name: str, document_type: str) -> None: ...
```

**Adaptador** (`adapters/database/template_repository.py`):
- Implementación con SQLAlchemy 2.x async
- `list_active()`: filtros por document_type (exacto), search (parcial sobre name), paginación, orden `created_at DESC, id DESC`
- `get_active_version()`: WHERE name=:name AND document_type=:type AND is_active=true ORDER BY version DESC LIMIT 1
- `deactivate_all_versions()`: UPDATE SET is_active=false WHERE name=:name AND document_type=:type

### 4.2 DraftRepository

**Puerto** (`ports/draft_repository.py`):
```python
class DraftRepository(Protocol):
    async def create(self, draft: Draft) -> Draft: ...
    async def get_by_id(self, draft_id: UUID) -> Draft | None: ...
    async def list_by_case_file(self, case_file_id: UUID, status: str | None, skip: int, limit: int) -> tuple[list[Draft], int]: ...
    async def update_with_optimistic_lock(self, draft: Draft, expected_version: int) -> Draft | None: ...
    async def update_status(self, draft_id: UUID, new_status: str, version: int) -> Draft | None: ...
```

**Adaptador** (`adapters/database/draft_repository.py`):
- `update_with_optimistic_lock()`: UPDATE ... WHERE id=:id AND version=:expected_version, retorna None si 0 filas
- `update_status()`: actualiza status + incrementa version en una sola operación

### 4.3 DraftTransitionRepository

**Puerto** (`ports/draft_transition_repository.py`):
```python
class DraftTransitionRepository(Protocol):
    async def create(self, transition: DraftTransition) -> DraftTransition: ...
    async def list_by_draft(self, draft_id: UUID) -> list[DraftTransition]: ...
```

### 4.4 GenerationAttemptRepository

**Puerto** (`ports/generation_attempt_repository.py`):
```python
class GenerationAttemptRepository(Protocol):
    async def create(self, attempt: GenerationAttempt) -> GenerationAttempt: ...
    async def get_by_idempotency_key(self, key: str) -> GenerationAttempt | None: ...
    async def get_by_id(self, attempt_id: UUID) -> GenerationAttempt | None: ...
    async def list_by_case_file(self, case_file_id: UUID) -> list[GenerationAttempt]: ...
    async def update(self, attempt: GenerationAttempt) -> GenerationAttempt: ...
    async def delete_by_idempotency_key(self, key: str) -> None: ...
    async def cleanup_expired(self, window_hours: int = 24) -> int: ...
```

### 4.5 DesignationRepository

**Puerto** (`ports/designation_repository.py`):
```python
class DesignationRepository(Protocol):
    async def create(self, designation: DesignationData) -> DesignationData: ...
    async def get_by_case_file_id(self, case_file_id: UUID) -> DesignationData | None: ...
    async def update(self, designation: DesignationData) -> DesignationData: ...
```

### 4.6 Unit of Work

Extender Unit of Work existente con nuevos repositorios:

```python
class UnitOfWork:
    async def __aenter__(self) -> "UnitOfWork": ...
    async def __aexit__(self, ...): ...
    async def commit(self): ...
    async def rollback(self): ...

    @property
    def templates(self) -> TemplateRepository: ...
    @property
    def drafts(self) -> DraftRepository: ...
    @property
    def draft_transitions(self) -> DraftTransitionRepository: ...
    @property
    def generation_attempts(self) -> GenerationAttemptRepository: ...
    @property
    def designations(self) -> DesignationRepository: ...
```

Mantiene los repositorios existentes de empleados y expedientes.

---

## 5. Máquina de Estados del Borrador

### Transiciones permitidas (diccionario):

```python
VALID_TRANSITIONS: dict[DraftStatus, set[DraftStatus]] = {
    DraftStatus.GENERADO: {DraftStatus.EN_REVISION},
    DraftStatus.EN_REVISION: {DraftStatus.APROBADO, DraftStatus.RECHAZADO},
    DraftStatus.RECHAZADO: {DraftStatus.EN_REVISION},
    DraftStatus.APROBADO: set(),    # terminal para este incremento
    DraftStatus.SUPERSEDED: set(),  # terminal, se asigna automáticamente al regenerar
}
```

### Mapping de acciones:

```python
ACTION_MAP: dict[TransitionAction, tuple[DraftStatus, DraftStatus]] = {
    TransitionAction.SEND_TO_REVIEW: (DraftStatus.GENERADO, DraftStatus.EN_REVISION),
    TransitionAction.APPROVE: (DraftStatus.EN_REVISION, DraftStatus.APROBADO),
    TransitionAction.REJECT: (DraftStatus.EN_REVISION, DraftStatus.RECHAZADO),
}
```

### Función de validación:
```python
def can_transition(from_status: DraftStatus, to_status: DraftStatus) -> bool:
    return to_status in VALID_TRANSITIONS.get(from_status, set())
```

### Regla de regeneración:
- Al regenerar, el borrador actual se marca `SUPERSEDED` (solo si existe y tiene éxito)
- El nuevo borrador se crea con `parent_draft_id` apuntando al original
- `generation_number` se incrementa en 1

---

## 6. Concurrencia Optimista

- Campo `version` (INTEGER, DEFAULT 1) en `document_drafts`
- Cada operación de escritura (edit content, transition, regenerate) recibe `expected_version` en el request
- En el repositorio/adaptador: `UPDATE ... SET ... WHERE id = :id AND version = :expected_version`
- Si 0 filas afectadas → `CONCURRENT_MODIFICATION` (409)
- Si 1 fila afectada → incrementar `version += 1` en el UPDATE
- Aplica a: edit content, transition, regenerate

---

## 7. Contratos de Endpoints (17 endpoints)

### 7.1 Plantillas (5 endpoints)

| # | Método | Ruta | Request Body | Response | Status |
|---|---|---|---|---|---|
| 1 | `POST` | `/api/v1/templates` | `CreateTemplateRequest` | `TemplateResponse` | 201 |
| 2 | `GET` | `/api/v1/templates` | Query: document_type, search, skip, limit | `PaginatedResponse[TemplateResponse]` | 200 |
| 3 | `GET` | `/api/v1/templates/{template_id}` | — | `TemplateResponse` | 200 |
| 4 | `PATCH` | `/api/v1/templates/{template_id}` | `UpdateTemplateRequest` | `TemplateResponse` | 200 |
| 5 | `POST` | `/api/v1/templates/{template_id}/deactivate` | — | `TemplateResponse` | 200 |

### 7.2 Datos de Designación (3 endpoints)

| # | Método | Ruta | Request Body | Response | Status |
|---|---|---|---|---|---|
| 6 | `POST` | `/api/v1/case-files/{case_file_id}/designation` | `CreateDesignationDataRequest` | `DesignationDataResponse` | 201 |
| 7 | `GET` | `/api/v1/case-files/{case_file_id}/designation` | — | `DesignationDataResponse` | 200 |
| 8 | `PUT` | `/api/v1/case-files/{case_file_id}/designation` | `CreateDesignationDataRequest` | `DesignationDataResponse` | 200 |

### 7.3 Borradores (7 endpoints)

| # | Método | Ruta | Request Body | Response | Status |
|---|---|---|---|---|---|
| 9 | `POST` | `/api/v1/drafts/generate` | `GenerateDraftRequest` + Header `Idempotency-Key` | `DraftResponse` | 201 |
| 10 | `GET` | `/api/v1/case-files/{case_file_id}/drafts` | Query: status, skip, limit | `PaginatedResponse[DraftResponse]` | 200 |
| 11 | `GET` | `/api/v1/drafts/{draft_id}` | — | `DraftResponse` | 200 |
| 12 | `PATCH` | `/api/v1/drafts/{draft_id}/content` | `EditDraftContentRequest` | `DraftResponse` | 200 |
| 13 | `POST` | `/api/v1/drafts/{draft_id}/transitions` | `TransitionDraftRequest` | `DraftResponse` | 200 |
| 14 | `POST` | `/api/v1/drafts/{draft_id}/regenerate` | `RegenerateDraftRequest` | `DraftResponse` | 201 |
| 15 | `GET` | `/api/v1/drafts/{draft_id}/history` | — | `list[DraftTransitionResponse]` | 200 |

### 7.4 Intentos de Generación (2 endpoints)

| # | Método | Ruta | Request Body | Response | Status |
|---|---|---|---|---|---|
| 16 | `GET` | `/api/v1/generation-attempts/{attempt_id}` | — | `GenerationAttemptResponse` | 200 |
| 17 | `GET` | `/api/v1/case-files/{case_file_id}/generation-attempts` | — | `list[GenerationAttemptResponse]` | 200 |

### Errores por endpoint:

| Endpoint | Errores posibles |
|---|---|
| `POST /templates` | `TEMPLATE_NAME_CONFLICT` (409), `VALIDATION_ERROR` (422), `DATABASE_ERROR` (500) |
| `GET /templates` | `VALIDATION_ERROR` (422) — query params inválidos |
| `GET /templates/{id}` | `TEMPLATE_NOT_FOUND` (404), `VALIDATION_ERROR` (422) — UUID inválido |
| `PATCH /templates/{id}` | `TEMPLATE_NOT_FOUND` (404), `TEMPLATE_VERSION_CONFLICT` (409), `VALIDATION_ERROR` (422) |
| `POST /templates/{id}/deactivate` | `TEMPLATE_NOT_FOUND` (404), `TEMPLATE_INACTIVE` (409) |
| `POST /designation` | `CASE_FILE_NOT_FOUND` (404), `DESIGNATION_EXISTS` (409), `VALIDATION_ERROR` (422) |
| `GET /designation` | `CASE_FILE_NOT_FOUND` (404), `DESIGNATION_NOT_FOUND` (404) |
| `PUT /designation` | `CASE_FILE_NOT_FOUND` (404), `VALIDATION_ERROR` (422) |
| `POST /drafts/generate` | `TEMPLATE_NOT_FOUND` (404), `TEMPLATE_INACTIVE` (409), `CASE_FILE_NOT_FOUND` (404), `OLLAMA_UNAVAILABLE` (503), `OLLAMA_TIMEOUT` (504), `GENERATION_FAILED` (500), `IDEMPOTENCY_KEY_MISMATCH` (409), `GENERATION_IN_PROGRESS` (409), `VALIDATION_ERROR` (422) |
| `GET /case-files/{id}/drafts` | `CASE_FILE_NOT_FOUND` (404) |
| `GET /drafts/{id}` | `DRAFT_NOT_FOUND` (404), `VALIDATION_ERROR` (422) |
| `PATCH /drafts/{id}/content` | `DRAFT_NOT_FOUND` (404), `CONCURRENT_MODIFICATION` (409), `DRAFT_READ_ONLY` (409) — aprobado/superseded, `VALIDATION_ERROR` (422) |
| `POST /drafts/{id}/transitions` | `DRAFT_NOT_FOUND` (404), `INVALID_STATUS_TRANSITION` (409), `CONCURRENT_MODIFICATION` (409), `VALIDATION_ERROR` (422) |
| `POST /drafts/{id}/regenerate` | `DRAFT_NOT_FOUND` (404), `CONCURRENT_MODIFICATION` (409), `OLLAMA_UNAVAILABLE` (503), `OLLAMA_TIMEOUT` (504), `GENERATION_FAILED` (500), `VALIDATION_ERROR` (422) |
| `GET /drafts/{id}/history` | `DRAFT_NOT_FOUND` (404), `VALIDATION_ERROR` (422) |
| `GET /generation-attempts/{id}` | `GENERATION_ATTEMPT_NOT_FOUND` (404), `VALIDATION_ERROR` (422) |
| `GET /case-files/{id}/generation-attempts` | `CASE_FILE_NOT_FOUND` (404) |

### Schemas de Request (Pydantic v2):

```python
class CreateTemplateRequest(BaseModel):
    name: str
    document_type: DocumentType
    organ_emisor: str | None = None
    normativa: str | None = None
    description: str | None = None
    body_template: str
    variables: list[str] = []

class UpdateTemplateRequest(BaseModel):
    body_template: str | None = None
    organ_emisor: str | None = None
    normativa: str | None = None
    description: str | None = None
    variables: list[str] | None = None
    model_config = ConfigDict(extra="forbid")

class CreateDesignationDataRequest(BaseModel):
    position_name: str
    organizational_unit: str | None = None
    start_date: date | None = None
    legal_basis: str | None = None
    appointing_authority: str | None = None
    salary_category: str | None = None
    work_schedule: str | None = None
    observations: str | None = None

class GenerateDraftRequest(BaseModel):
    template_id: UUID
    case_file_id: UUID
    variables: dict[str, str] = {}

class EditDraftContentRequest(BaseModel):
    content: str
    expected_version: int
    model_config = ConfigDict(extra="forbid")

class TransitionDraftRequest(BaseModel):
    action: TransitionAction
    expected_version: int
    observations: str | None = None
    model_config = ConfigDict(extra="forbid")

class RegenerateDraftRequest(BaseModel):
    observations: str | None = None
    expected_version: int
    model_config = ConfigDict(extra="forbid")
```

### Schemas de Response:

```python
class TemplateResponse(BaseModel):
    id: UUID
    name: str
    document_type: DocumentType
    version: int
    organ_emisor: str | None = None
    normativa: str | None = None
    description: str | None = None
    body_template: str
    variables: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

class DesignationDataResponse(BaseModel):
    id: UUID
    case_file_id: UUID
    position_name: str
    organizational_unit: str | None = None
    start_date: date | None = None
    legal_basis: str | None = None
    appointing_authority: str | None = None
    salary_category: str | None = None
    work_schedule: str | None = None
    observations: str | None = None
    created_at: datetime
    updated_at: datetime

class DraftResponse(BaseModel):
    id: UUID
    template_id: UUID
    case_file_id: UUID
    title: str
    content: str | None = None
    status: DraftStatus
    version: int
    generation_number: int
    variables_used: dict[str, str]
    parent_draft_id: UUID | None = None
    observations: str | None = None
    request_id: str | None = None
    created_at: datetime
    updated_at: datetime

class DraftTransitionResponse(BaseModel):
    id: UUID
    draft_id: UUID
    from_status: DraftStatus
    to_status: DraftStatus
    action: TransitionAction
    observations: str | None = None
    performed_by: str | None = None
    created_at: datetime

class GenerationAttemptResponse(BaseModel):
    id: UUID
    case_file_id: UUID
    template_id: UUID
    idempotency_key: str | None = None
    model: str
    prompt_hash: str
    status: GenerationStatus
    started_at: datetime
    completed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime

class PaginatedResponse(BaseModel, Generic[T]):
    page: int
    page_size: int
    total: int
    items: list[T]
```

---

## 8. Servicios de Aplicación

### 8.1 TemplateService

**Archivo**: `application/template_service.py`

| Método | Descripción |
|---|---|
| `create_template(data)` | Valida unicidad (name + document_type), crea con version=1 |
| `get_template(template_id)` | Retorna template o NotFound |
| `list_templates(document_type, search, skip, limit)` | Paginación con filtros |
| `update_template(template_id, data)` | Si cambia body_template o variables → crea nueva versión (version+1), desactiva anteriores |
| `deactivate_template(template_id)` | Marca is_active=false, valida que esté activo |
| `get_active_version(name, document_type)` | Retorna versión activa más reciente |

### 8.2 DraftService

**Archivo**: `application/draft_service.py`

| Método | Descripción |
|---|---|
| `generate_draft(request, idempotency_key)` | Flujo completo: busca template activo, construye contexto, renderiza prompt, llama Ollama, crea draft, registra intento |
| `get_draft(draft_id)` | Retorna draft o NotFound |
| `list_drafts(case_file_id, status, skip, limit)` | Paginación con filtros |
| `edit_content(draft_id, content, expected_version)` | Optimistic locking, solo si status ∈ {GENERADO, EN_REVISION, RECHAZADO} |
| `transition_draft(draft_id, action, observations, expected_version)` | Validar máquina de estados, crear transición, optimist lock |
| `regenerate_draft(draft_id, observations, expected_version)` | Marcar actual SUPERSEDED, crear nuevo draft, mismo flujo que generate_draft |
| `get_history(draft_id)` | Retorna transiciones ordenadas ASC |

### 8.3 GenerationContext

**Archivo**: `application/generation_context.py`

| Método | Descripción |
|---|---|
| `build_context(template_id, case_file_id)` | Construye snapshot completo: template, case_file, employee, designation (si existe), variables del usuario, metadata |
| `validate_variables(template, user_variables)` | Verifica que todas las variables del template estén en user_variables |
| `compute_hash(context_snapshot)` | SHA-256 del JSON serializado del snapshot |

### 8.4 PromptBuilder

**Archivo**: `application/prompt_builder.py`

| Método | Descripción |
|---|---|
| `render_template(body_template, context)` | Renderizado seguro tipo Jinja2 (sin ejecución de código, solo sustitución de variables con namespace) |
| `build_prompt(rendered_template, context)` | Agrega prefijo de instrucciones del sistema |
| `validate_syntax(body_template)` | Retorna lista de variables desconocidas (para validación) |

### 8.5 DesignationService

**Archivo**: `application/designation_service.py`

| Método | Descripción |
|---|---|
| `create_designation(case_file_id, data)` | Verifica que no exista, crea, valida case_file existe |
| `get_designation(case_file_id)` | Retorna datos o NotFound |
| `update_designation(case_file_id, data)` | Actualiza existente |

### 8.6 OllamaClient

**Archivo**: `application/ollama_client.py` (reutiliza o extiende el cliente existente de increment 001)

| Método | Descripción |
|---|---|
| `generate(prompt, model, timeout)` | Retorna `OllamaResponse` con contenido generado |
| Configuración | `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_TIMEOUT` |
| Errores manejados | timeout, 401, 403, 404, 429, 5xx, JSON inválido, respuesta vacía, desconexión |

---

## 9. Seguridad del Prompt

- `prompt_content` se almacena en `generation_attempts` (columna TEXT, NOT NULL)
- **Tamaño máximo**: 500KB (CHECK constraint o validación en aplicación)
- **NUNCA** loggear `prompt_content` completo en logs estructurados
- **NUNCA** incluir `prompt_content` en respuestas de error
- **NUNCA** exponer `prompt_content` via endpoints API (solo metadata de generation_attempts)
- Hash almacenado por separado (`prompt_hash VARCHAR(64)`) para verificación de integridad
- Sanitización: excluir headers Authorization, tokens, `OLLAMA_API_TOKEN` del contenido del prompt
- Retención: `generation_attempts` mayores a 90 días pueden limpiarse (job separado, no en este incremento)
- Tests de privacidad: verificar que prompt no aparece en logs, respuestas de error ni métricas

---

## 10. Idempotencia

- **Header**: `Idempotency-Key` (string, max 100 chars)
- **Storage**: `generation_attempts.idempotency_key` (constraint UNIQUE)
- **Window**: 24 horas (limpieza a nivel de aplicación)
- **Comportamiento**:

| Escenario | Resultado |
|---|---|
| Misma key + mismo payload | Retornar resultado cacheado (200 si éxito, 503 si fallo previo) |
| Misma key + payload diferente | 409 `IDEMPOTENCY_KEY_MISMATCH` |
| Key existe, status=IN_PROGRESS | 409 `GENERATION_IN_PROGRESS` |
| Key existe, status=COMPLETED | Retornar draft cacheado |
| Key existe, status=FAILED | Eliminar intento antiguo, permitir reintento |
| Key expirada (>24h) | Tratar como nueva solicitud |

- `request_id` es independiente, solo para trazabilidad

---

## 11. Context Snapshot

### Formato:

```json
{
  "template": {
    "id": "uuid",
    "name": "string",
    "document_type": "string",
    "version": 1,
    "body_template": "string",
    "variables": ["var1", "var2"]
  },
  "case_file": {
    "id": "uuid",
    "case_number": "CF-xxx",
    "title": "string",
    "description": "string",
    "case_type": "string",
    "status": "string"
  },
  "employee": {
    "id": "uuid",
    "first_name": "string",
    "last_name": "string",
    "department": "string"
  },
  "designation": {
    "position_name": "string",
    "organizational_unit": "string",
    "start_date": "2026-01-01",
    "legal_basis": "string",
    "appointing_authority": "string",
    "salary_category": "string",
    "work_schedule": "string",
    "observations": "string"
  },
  "variables": {
    "key": "value"
  },
  "metadata": {
    "generated_at": "2026-01-01T00:00:00Z",
    "model": "string",
    "attempt_id": "uuid"
  }
}
```

- Columna JSONB en `document_drafts`
- **Inmutable una vez creado** (nunca se actualiza)
- Hash SHA-256 almacenado en columna `context_hash`
- **Tamaño máximo**: 50KB (validación en aplicación)
- No secretos, no DNI, no CUIL en texto plano en respuesta (enmascarado en API)

---

## 12. Seguridad y Privacidad

| Regla | Implementación |
|---|---|
| No loggear prompt_content completo | Filtro en logger, truncar a 200 chars o excluir |
| No loggear context_snapshot completo | Mismo filtro, solo metadata |
| No loggear datos sensibles | DNI, CUIL, email, phone excluidos de logs |
| No exponer OLLAMA_API_TOKEN | Nunca en errores, headers ni responses |
| Errores sanitizados | Sin stack traces, sin SQL en respuestas |
| Datos ficticios en tests | Fixtures con UUIDs y nombres fake |
| Payload limits | content ≤ 100KB, body_template ≤ 500KB, context_snapshot ≤ 50KB |
| Prompt almacenado pero protegido | No via API, no en logs, no en métricas |

---

## 13. Archivos Previstos

### Nuevos archivos:

```
apps/api/src/legal_ai/
├── domain/
│   ├── template.py
│   ├── draft.py
│   ├── generation_attempt.py
│   ├── designation_data.py
│   └── enums.py                          (extender con nuevos enums)
├── ports/
│   ├── template_repository.py
│   ├── draft_repository.py
│   ├── draft_transition_repository.py
│   ├── generation_attempt_repository.py
│   └── designation_repository.py
├── application/
│   ├── template_service.py
│   ├── draft_service.py
│   ├── designation_service.py
│   ├── generation_context.py
│   └── prompt_builder.py
├── adapters/
│   └── database/
│       ├── template_repository.py
│       ├── draft_repository.py
│       ├── draft_transition_repository.py
│       ├── generation_attempt_repository.py
│       ├── designation_repository.py
│       └── unit_of_work.py              (extender)
├── api/
│   ├── routes/
│   │   ├── templates.py
│   │   ├── drafts.py
│   │   ├── designation.py
│   │   └── generation.py
│   └── schemas/
│       ├── template.py
│       ├── draft.py
│       ├── designation.py
│       └── generation.py
└── migrations/
    └── versions/
        └── 003_templates_drafts_and_generation.py

apps/api/tests/
├── unit/
│   ├── test_template_service.py
│   ├── test_draft_service.py
│   ├── test_generation_context.py
│   ├── test_prompt_builder.py
│   ├── test_generation_attempt.py
│   └── test_designation_service.py
├── integration/
│   ├── test_template_repository.py
│   ├── test_draft_repository.py
│   ├── test_generation_attempt_repository.py
│   └── test_designation_repository.py
└── contract/
    ├── test_templates_endpoints.py
    ├── test_drafts_endpoints.py
    ├── test_designation_endpoints.py
    └── test_generation_endpoints.py
```

### Archivos modificados:

```
apps/api/src/legal_ai/
├── domain/enums.py                        (agregar DocumentType, DraftStatus, TransitionAction, GenerationStatus)
├── adapters/database/unit_of_work.py      (agregar repositorios nuevos)
├── api/router.py                          (incluir templates, drafts, designation, generation routers)
├── main.py                                (registrar exception handlers nuevos)

apps/api/tests/
├── conftest.py                            (agregar fixtures de BD para tests nuevos)
```

---

## 14. Pruebas

### 14.1 Unitarias (35+ tests)

| Categoría | Tests |
|---|---|
| Template versioning | crear template, actualizar crea nueva versión, desactivar |
| Validación de variables | variable requerida faltante, variables desconocidas, validación de sintaxis |
| Renderizado seguro | Jinja2-like, sin ejecución de código, resolución de namespace |
| Context builder | contexto completo, template faltante, case_file faltante, designation |
| Cálculo de hash | determinístico, mismo input = mismo hash |
| Máquina de estados | todas las transiciones válidas, todas las transiciones inválidas |
| Concurrencia optimista | versión no coincide → CONCURRENT_MODIFICATION |
| Idempotencia | misma key mismo payload, misma key payload diferente, key expirada |
| Sanitización | prompt no en logs, datos sensibles enmascarados |
| Mapeo de errores | cada código de error → HTTP correcto |

### 14.2 Integración (20+ tests)

| Categoría | Tests |
|---|---|
| Constraints reales | unique name+type+version, unique case_file_id en designation |
| Template versioning | crear v1, actualizar → v2, v1 consultable |
| Designation data | crear, leer, actualizar, validación case_type |
| Generation attempt | crear, idempotency key, cleanup |
| Draft + transiciones | ciclo de vida completo |
| Rollback | fallo transacción no deja estado parcial |
| Edits concurrentes | detección de versión no coincide |
| Regeneración | superseded solo en éxito |
| Migration 003 | upgrade desde 002, downgrade de vuelta |

### 14.3 Contractuales (17 endpoints × casos de error)

- Cada endpoint: validación de schema de respuesta exitosa
- 404: UUID inválido → 422, UUID válido no encontrado → 404
- 409: concurrencia, template inactivo, transición inválida, idempotencia
- 422: campos requeridos faltantes, contenido demasiado grande, variables faltantes
- 502/503/504: fallos de Ollama
- Idempotency-Key: presente, ausente, duplicada, incompatible
- expected_version: correcto, incompatible

### 14.4 Ollama (mock-based)

| Escenario | Resultado esperado |
|---|---|
| Éxito | Flujo completo de generación |
| Timeout | 504, sin draft creado |
| 401/403 | Error de autenticación |
| 404 | Modelo no encontrado |
| 429 | Rate limited |
| 5xx | Error del servidor |
| JSON inválido | Error de parseo |
| Respuesta vacía | Sin contenido |
| Desconexión | Connection reset |
| Token expuesto | Nunca en ningún error |

### 14.5 Regresión

- Todos los 245+ tests existentes de 001+002 deben pasar
- Endpoints de empleados sin cambios
- Endpoints de expedientes sin cambios
- Endpoints de health sin cambios
- pgvector intacto
- Docker Compose funcional

---

## 15. Dependencias Nuevas

| Dependencia | Uso | Notas |
|---|---|---|
| `jinja2` | Renderizado seguro de plantillas | Ya disponible en ecosistema Python |
| `hashlib` | SHA-256 para hashes | stdlib, sin instalación |

No se requieren nuevas dependencias externas significativas.

---

## 16. Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Ollama unavailable durante generación | Alto | No crear draft, registrar intento, reintento idempotente |
| Tamaño de prompt excede storage | Medio | Validación de tamaño (500KB max), CHECK constraint |
| Race condition en regeneración concurrente | Medio | Optimistic locking + constraint de idempotencia |
| Proliferación de versiones de template | Bajo | Sin DELETE, pero cleanup job futuro |
| Context snapshot demasiado grande | Medio | Límite 50KB, validación antes de almacenar |

---

## 17. Decisiones Abiertas

- **Cleanup job** para generation_attempts antiguos (90 días) → pendiente para incremento posterior
- **Autenticación y roles** → excluido de 003
- **Publicación oficial** → excluido de 003

---

## 18. Excluido del Incremento

Según la spec (sección "Alcance Excluido"), NO se implementa:

- Documentos jurídicos (PDF, DOCX)
- Firma digital
- OCR
- Embeddings y columnas vectoriales
- RAG (Retrieval-Augmented Generation)
- Pases y adjuntos
- Frontend
- Login y autenticación
- Roles y permisos
- Kubernetes / Terraform / Helm
- Redis / Colas / Workers
- Exportación de documentos
