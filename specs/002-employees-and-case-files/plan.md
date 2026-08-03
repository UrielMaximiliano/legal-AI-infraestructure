# Plan Técnico: Incremento 002 — Empleados y Expedientes

## 1. Resumen Ejecutivo

Este incremento construye el núcleo transaccional del sistema: entidades **Employee**, **CaseFile** y **CaseStatusHistory** con CRUD completo, máquina de estados, control de concurrencia optimista, historial append-only, normalización de datos y 11 endpoints de negocio. Se apoya en la arquitectura hexagonal existente (adapters/ports/domain/application/schemas) y extiende el patrón de migraciones Alembic sin alterar los contratos de health check del incremento 001.

---

## 2. Modelo de Datos

### 2.1 Enums (StrEnum, Python puro)

```python
class DocumentType(StrEnum):
    DNI = "dni"
    LC = "lc"
    LE = "le"
    CI = "ci"
    PASSPORT = "pasaporte"

class CaseStatus(StrEnum):
    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    IN_PROCESS = "in_process"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"

class CaseType(StrEnum):
    DESIGNACION = "designacion"
    LICENCIA = "licencia"
    RENUNCIA = "renuncia"
    CONTRATACION = "contratacion"
    OTRO = "otro"
```

Ubicación: `domain/enums.py`

### 2.2 Tabla `employees`

| Columna | Tipo SQL | Constraints |
|---|---|---|
| `id` | `UUID` DEFAULT gen_random_uuid() | PK |
| `employee_number` | `VARCHAR(50)` | NOT NULL, UNIQUE |
| `first_name` | `VARCHAR(200)` | NOT NULL |
| `last_name` | `VARCHAR(200)` | NOT NULL |
| `document_type` | `VARCHAR(20)` | NOT NULL (enum string) |
| `document_number` | `VARCHAR(100)` | NOT NULL, UNIQUE con document_type |
| `cuil` | `VARCHAR(11)` | NULL, UNIQUE |
| `email` | `VARCHAR(320)` | NULL |
| `phone` | `VARCHAR(50)` | NULL |
| `position` | `VARCHAR(200)` | NULL |
| `department` | `VARCHAR(200)` | NULL |
| `active` | `BOOLEAN` | NOT NULL, DEFAULT true |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT now() |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT now() |

**Constraint compuesta**: `uq_employee_document` UNIQUE (`document_type`, `document_number`)
**Constraint individual**: `uq_employee_cuil` UNIQUE (`cuil`) — solo aplica cuando cuil IS NOT NULL (manejado en aplicación)

### 2.3 Tabla `case_files`

| Columna | Tipo SQL | Constraints |
|---|---|---|
| `id` | `UUID` DEFAULT gen_random_uuid() | PK |
| `case_number` | `VARCHAR(50)` | NOT NULL, UNIQUE |
| `employee_id` | `UUID` | NOT NULL, FK → employees(id) |
| `title` | `VARCHAR(500)` | NOT NULL |
| `description` | `TEXT` | NULL |
| `case_type` | `VARCHAR(50)` | NOT NULL (enum string) |
| `status` | `VARCHAR(30)` | NOT NULL, DEFAULT 'draft' |
| `version` | `INTEGER` | NOT NULL, DEFAULT 1 |
| `opened_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT now() |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT now() |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT now() |
| `closed_at` | `TIMESTAMPTZ` | NULL |

**FK**: `fk_case_files_employee` FOREIGN KEY (`employee_id`) REFERENCES `employees(id)`

### 2.4 Tabla `case_status_history`

| Columna | Tipo SQL | Constraints |
|---|---|---|
| `id` | `UUID` DEFAULT gen_random_uuid() | PK |
| `case_file_id` | `UUID` | NOT NULL, FK → case_files(id) |
| `from_status` | `VARCHAR(30)` | NULL (solo null en creación inicial) |
| `to_status` | `VARCHAR(30)` | NOT NULL |
| `changed_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT now() |
| `changed_by` | `VARCHAR(200)` | NOT NULL |
| `reason` | `TEXT` | NULL |
| `request_id` | `VARCHAR(128)` | NULL |

**FK**: `fk_history_case_file` FOREIGN KEY (`case_file_id`) REFERENCES `case_files(id)`

---

## 3. Migración Alembic

**Archivo**: `alembic/versions/002_employees_and_case_files.py`
**Revisión**: `002`
**Depende de**: `001`

### Estrategia:
- Crear tablas en orden: `employees` → `case_files` → `case_status_history` (respetando FKs)
- Usar `op.create_table()` con definición completa de columnas y constraints
- Crear índices en la misma migración
- En `downgrade()`: eliminar tablas en orden inverso (`case_status_history` → `case_files` → `employees`)
- No usar SQLAlchemy `MetaData` automático; definición explícita via `op`

### Índices a crear:

| Tabla | Índice | Columnas | Tipo |
|---|---|---|---|
| `employees` | `ix_employees_employee_number` | `employee_number` | UNIQUE |
| `employees` | `ix_employees_document` | (`document_type`, `document_number`) | UNIQUE |
| `employees` | `ix_employees_cuil` | `cuil` | UNIQUE WHERE cuil IS NOT NULL (partial) |
| `employees` | `ix_employees_active` | `active` | B-tree |
| `employees` | `ix_employees_department` | `department` | B-tree |
| `employees` | `ix_employees_created_at` | `created_at` | B-tree |
| `case_files` | `ix_case_files_case_number` | `case_number` | UNIQUE |
| `case_files` | `ix_case_files_employee_id` | `employee_id` | B-tree |
| `case_files` | `ix_case_files_status` | `status` | B-tree |
| `case_files` | `ix_case_files_case_type` | `case_type` | B-tree |
| `case_files` | `ix_case_files_opened_at` | `opened_at` | B-tree |
| `case_files` | `ix_case_files_created_at` | `created_at` | B-tree |
| `case_status_history` | `ix_history_case_file_id` | `case_file_id` | B-tree |
| `case_status_history` | `ix_history_changed_at` | `changed_at` | B-tree |

---

## 4. Normalización

Se implementa un módulo `domain/normalization.py` con funciones puras (sin dependencias de BD):

| Función | Regla |
|---|---|
| `normalize_document_number(doc_type, value)` | Trim. DNI: solo dígitos, rechazar vacío. LC/LE/CI/Pasaporte: alfanumérico, mayúsculas, rechazar vacío. No completar ceros. No inferir. |
| `normalize_cuil(value)` | Trim. Eliminar guiones y espacios. Solo dígitos. Debe tener 11 dígitos. |
| `normalize_email(value)` | Trim. Minúsculas. Validar formato básico. |
| `normalize_phone(value)` | Trim. Eliminar espacios. Formato consistente cuando sea posible. |
| `normalize_text(value)` | Trim. Rechazar vacío. |

---

## 5. Repositories

Patrón Repository async con interfaz (Puerto) y adaptador concreto:

### 5.1 EmployeeRepository

**Puerto** (`ports/employee_repository.py`):
```python
class EmployeeRepository(Protocol):
    async def create(self, employee: Employee) -> Employee: ...
    async def get_by_id(self, employee_id: UUID) -> Employee | None: ...
    async def get_by_employee_number(self, number: str) -> Employee | None: ...
    async def get_by_document(self, doc_type: str, doc_number: str) -> Employee | None: ...
    async def get_by_cuil(self, cuil: str) -> Employee | None: ...
    async def list(self, ...) -> tuple[list[Employee], int]: ...
    async def update(self, employee: Employee) -> Employee: ...
    async def deactivate(self, employee_id: UUID) -> Employee | None: ...
```

**Adaptador** (`adapters/database/employee_repository.py`):
- Implementación con SQLAlchemy 2.x async
- Usa `select()`, `await session.execute()`, `result.scalars().first()`
- Para `list()`: construye query dinámica con filtros, cuenta total, aplica paginación con `offset/limit`
- Orden: `created_at DESC, id DESC` determinista

### 5.2 CaseFileRepository

**Puerto** (`ports/case_file_repository.py`):
```python
class CaseFileRepository(Protocol):
    async def create(self, case_file: CaseFile) -> CaseFile: ...
    async def get_by_id(self, case_file_id: UUID) -> CaseFile | None: ...
    async def get_by_case_number(self, number: str) -> CaseFile | None: ...
    async def list(self, ...) -> tuple[list[CaseFile], int]: ...
    async def update(self, case_file: CaseFile) -> CaseFile: ...
```

**Adaptador** (`adapters/database/case_file_repository.py`):
- Misma estrategia que employee
- Para `list()`: filtros por employee_id, status, case_type, rango de opened_at, query parcial sobre case_number/title

### 5.3 CaseStatusHistoryRepository

**Puerto** (`ports/case_status_history_repository.py`):
```python
class CaseStatusHistoryRepository(Protocol):
    async def create(self, entry: CaseStatusHistory) -> CaseStatusHistory: ...
    async def list_by_case_file(self, case_file_id: UUID) -> list[CaseStatusHistory]: ...
```

**Adaptador** (`adapters/database/case_status_history_repository.py`):
- `create()`: inserta registro individual
- `list_by_case_file()`: retorna todos los registros ordenados por `changed_at ASC, id ASC`

---

## 6. Unit of Work

**Ubicación**: `adapters/database/unit_of_work.py`

El Unit of Work gestiona una transacción asíncrona que contiene las tres instancias de repositorio:

```python
class UnitOfWork:
    async def __aenter__(self) -> "UnitOfWork": ...  # begin transaction
    async def __aexit__(self, ...): ...              # commit o rollback
    async def commit(self): ...
    async def rollback(self): ...
    @property
    def employees(self) -> EmployeeRepository: ...
    @property
    def case_files(self) -> CaseFileRepository: ...
    @property
    def case_status_history(self) -> CaseStatusHistoryRepository: ...
```

**Implementación**:
- Usa `AsyncSession` de SQLAlchemy con `expire_on_commit=False`
- Crea repositorios pasando la sesión compartida
- En `__aenter__`: crea sesión, inicia transacción, retorna UoW
- En `__aexit__`: si hubo excepción → `rollback()`, si no → `commit()`
- Repositorios se crean lazy dentro de la sesión del UoW

---

## 7. Máquina de Estados

**Ubicación**: `domain/case_file.py` o `domain/state_machine.py`

### Transiciones permitidas (diccionario):

```python
VALID_TRANSITIONS: dict[CaseStatus, set[CaseStatus]] = {
    CaseStatus.DRAFT: {CaseStatus.UNDER_REVIEW},
    CaseStatus.UNDER_REVIEW: {CaseStatus.IN_PROCESS, CaseStatus.DRAFT},
    CaseStatus.IN_PROCESS: {CaseStatus.SUBMITTED, CaseStatus.UNDER_REVIEW},
    CaseStatus.SUBMITTED: {CaseStatus.APPROVED, CaseStatus.REJECTED},
    CaseStatus.APPROVED: {CaseStatus.ARCHIVED},
    CaseStatus.REJECTED: {CaseStatus.UNDER_REVIEW, CaseStatus.ARCHIVED},
    CaseStatus.ARCHIVED: set(),  # terminal
}
```

### Función de validación:
```python
def can_transition(from_status: CaseStatus, to_status: CaseStatus) -> bool:
    return to_status in VALID_TRANSITIONS.get(from_status, set())
```

### Reglas de `closed_at`:
- Solo se actualiza cuando `to_status == CaseStatus.ARCHIVED`
- Se asigna el timestamp UTC de la transición
- Una vez asignado, no puede modificarse

---

## 8. Concurrencia Optimista

- Campo `version` (INTEGER, DEFAULT 1) en `case_files`
- Cada `update()` o `transition()` recibe `expected_version` en el request
- En el repositorio/adaptador: `UPDATE ... SET ... WHERE id = :id AND version = :expected_version`
- Si 0 filas afectadas → `CONCURRENT_MODIFICATION` (409)
- Si 1 fila afectada → incrementar `version += 1` en el UPDATE

---

## 9. Contratos de Endpoints (11 endpoints)

### 9.1 Empleados

| # | Método | Ruta | Request Body | Response | Status |
|---|---|---|---|---|---|
| 1 | `POST` | `/api/v1/employees` | `CreateEmployeeRequest` | `EmployeeResponse` | 201 |
| 2 | `GET` | `/api/v1/employees/{employee_id}` | — | `EmployeeResponse` | 200 |
| 3 | `GET` | `/api/v1/employees` | Query params: page, page_size, query, active, department | `PaginatedResponse[EmployeeResponse]` | 200 |
| 4 | `PATCH` | `/api/v1/employees/{employee_id}` | `UpdateEmployeeRequest` | `EmployeeResponse` | 200 |
| 5 | `POST` | `/api/v1/employees/{employee_id}/deactivate` | — | `EmployeeResponse` | 200 |

### 9.2 Expedientes

| # | Método | Ruta | Request Body | Response | Status |
|---|---|---|---|---|---|
| 6 | `POST` | `/api/v1/case-files` | `CreateCaseFileRequest` | `CaseFileResponse` | 201 |
| 7 | `GET` | `/api/v1/case-files/{case_file_id}` | — | `CaseFileResponse` | 200 |
| 8 | `GET` | `/api/v1/case-files` | Query params: page, page_size, query, employee_id, status, case_type, opened_from, opened_to | `PaginatedResponse[CaseFileResponse]` | 200 |
| 9 | `PATCH` | `/api/v1/case-files/{case_file_id}` | `UpdateCaseFileRequest` | `CaseFileResponse` | 200 |
| 10 | `POST` | `/api/v1/case-files/{case_file_id}/transitions` | `TransitionRequest` | `CaseFileResponse` | 200 |
| 11 | `GET` | `/api/v1/case-files/{case_file_id}/history` | — | `HistoryResponse` | 200 |

### Schemas de Request (Pydantic v2):

```python
class CreateEmployeeRequest(BaseModel):
    employee_number: str
    first_name: str
    last_name: str
    document_type: DocumentType
    document_number: str
    cuil: str | None = None
    email: str | None = None
    phone: str | None = None
    position: str | None = None
    department: str | None = None

class UpdateEmployeeRequest(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    position: str | None = None
    department: str | None = None
    model_config = ConfigDict(extra="forbid")

class CreateCaseFileRequest(BaseModel):
    employee_id: UUID
    title: str
    case_type: CaseType
    description: str | None = None

class UpdateCaseFileRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    expected_version: int
    model_config = ConfigDict(extra="forbid")

class TransitionRequest(BaseModel):
    status: CaseStatus
    expected_version: int
    changed_by: str
    reason: str | None = None
    model_config = ConfigDict(extra="forbid")
```

### Schemas de Response:

```python
class EmployeeResponse(BaseModel):
    id: UUID
    employee_number: str
    first_name: str
    last_name: str
    document_type: DocumentType
    document_number: str
    cuil: str | None = None
    email: str | None = None
    phone: str | None = None
    position: str | None = None
    department: str | None = None
    active: bool
    created_at: datetime
    updated_at: datetime

class CaseFileResponse(BaseModel):
    id: UUID
    case_number: str
    employee_id: UUID
    title: str
    description: str | None = None
    case_type: CaseType
    status: CaseStatus
    version: int
    opened_at: datetime
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None

class HistoryItem(BaseModel):
    id: UUID
    case_file_id: UUID
    from_status: CaseStatus | None = None
    to_status: CaseStatus
    changed_at: datetime
    changed_by: str
    reason: str | None = None
    request_id: str | None = None

class HistoryResponse(BaseModel):
    items: list[HistoryItem]

class PaginatedResponse(BaseModel, Generic[T]):
    page: int
    page_size: int
    total: int
    items: list[T]
```

---

## 10. Manejo de Errores

### 10.1 Códigos de error y mapeo HTTP (uniforme)

| error_code | HTTP | Descripción |
|---|---|---|
| `EMPLOYEE_NOT_FOUND` | 404 | Empleado inexistente |
| `CASE_FILE_NOT_FOUND` | 404 | Expediente inexistente |
| `EMPLOYEE_NUMBER_CONFLICT` | 409 | Legajo duplicado |
| `EMPLOYEE_DOCUMENT_CONFLICT` | 409 | Documento duplicado |
| `CASE_NUMBER_CONFLICT` | 409 | Número de expediente duplicado |
| `INVALID_STATUS_TRANSITION` | 409 | Transición no permitida |
| `CASE_FILE_ARCHIVED` | 409 | Expediente en estado terminal |
| `CONCURRENT_MODIFICATION` | 409 | Versión no coincide |
| `EMPLOYEE_INACTIVE` | 422 | Empleado inactivo |
| `VALIDATION_ERROR` | 422 | Payload inválido |
| `DATABASE_ERROR` | 500 | Error interno |

### 10.2 Implementación

**Archivo**: `schemas/errors.py` (extendido)

```python
class ValidationErrorDetail(BaseModel):
    field: str
    code: str
    message: str

class ErrorResponse(BaseModel):
    error_code: str
    message: str
    field: str | None = None
    request_id: str | None = None
    errors: list[ValidationErrorDetail] | None = None  # solo para VALIDATION_ERROR
```

**Manejador global de excepciones**:
- Crear `api/exceptions.py` con clases de excepción de dominio:
  - `NotFoundError`, `ConflictError`, `ValidationError`, `DatabaseError`
- En `main.py`, registrar exception handlers que mapean estas excepciones a `ErrorResponse` con el HTTP correcto
- Para `VALIDATION_ERROR` con múltiples campos: serializar lista de `errors`

### 10.3 Criterio UUID inválido vs. recurso inexistente

El path `{id}` se valida como `UUID` con Pydantic. Si el formato es inválido, FastAPI retorna 422 automáticamente (con `detail` de Pydantic). Para convertir esto a nuestro `VALIDATION_ERROR` uniforme, se usa un custom validator o se intercepta el 422 de FastAPI.

---

## 11. Paginación y Filtros

### Empleados — Query params:
| Parámetro | Tipo | Default | Descripción |
|---|---|---|---|
| `page` | int | 1 | >= 1 |
| `page_size` | int | 20 | 1-100 |
| `query` | str | None | Búsqueda parcial case-insensitive sobre employee_number, first_name, last_name, document_number |
| `active` | bool | None | Filtrar por activo/inactivo |
| `department` | str | None | Filtrar por departamento (case-insensitive) |

### Expedientes — Query params:
| Parámetro | Tipo | Default | Descripción |
|---|---|---|---|
| `page` | int | 1 | >= 1 |
| `page_size` | int | 20 | 1-100 |
| `query` | str | None | Búsqueda parcial sobre case_number, title |
| `employee_id` | UUID | None | Filtrar por empleado |
| `status` | CaseStatus | None | Filtrar por estado |
| `case_type` | CaseType | None | Filtrar por tipo |
| `opened_from` | datetime | None | Fecha desde |
| `opened_to` | datetime | None | Fecha hasta |

### Implementación en repositorios:
- Construir filtros dinámicos con `WHERE` condicionales
- Para `query`: usar `ILIKE '%query%'` sobre campos relevantes
- Para fechas: `opened_at >= opened_from AND opened_at <= opened_to`
- Para `employee_id`: `employee_id = :uuid`
- Contar total con `SELECT COUNT(*)` antes de paginar
- Si `page` excede rango: devolver `items=[], total=correcto`

---

## 12. Orden de Implementación (Fases)

### Fase 0: Infraestructura base
1. Crear `domain/enums.py` con `DocumentType`, `CaseStatus`, `CaseType`
2. Crear `domain/normalization.py` con funciones de normalización
3. Crear `domain/case_file.py` con máquina de estados (`VALID_TRANSITIONS`, `can_transition`)

### Fase 1: Modelo de dominio + ORM
4. Crear `domain/employee.py` con dataclass `Employee`
5. Crear `domain/case_file.py` (extender con dataclass `CaseFile`)
6. Crear `domain/case_status_history.py` con dataclass `CaseStatusHistory`
7. Crear `adapters/database/models.py` con modelos SQLAlchemy ORM (tablas)

### Fase 2: Migración
8. Crear migración `002_employees_and_case_files.py` con tablas, constraints, índices
9. Actualizar `alembic/env.py` para importar metadata de los modelos ORM

### Fase 3: Repositorios + Unit of Work
10. Crear puertos `ports/employee_repository.py`, `ports/case_file_repository.py`, `ports/case_status_history_repository.py`
11. Crear adaptadores `adapters/database/employee_repository.py`, `adapters/database/case_file_repository.py`, `adapters/database/case_status_history_repository.py`
12. Crear `adapters/database/unit_of_work.py`

### Fase 4: Schemas
13. Crear schemas de request y response en `schemas/employee.py`, `schemas/case_file.py`
14. Actualizar `schemas/errors.py` con `ValidationErrorDetail` y campo `errors`

### Fase 5: Application Services
15. Crear `application/employee_service.py` con lógica de negocio (normalización, validaciones, llamadas a repositorios)
16. Crear `application/case_file_service.py` con lógica de creación, actualización, transiciones

### Fase 6: API Endpoints
17. Crear `api/routes/employees.py` con 5 endpoints
18. Crear `api/routes/case_files.py` con 6 endpoints
19. Actualizar `api/router.py` para incluir los nuevos routers

### Fase 7: Manejo de errores
20. Crear `api/exceptions.py` con excepciones de dominio
21. Registrar exception handlers en `main.py`

### Fase 8: Tests
22. Tests unitarios: normalización, máquina de estados, schemas
23. Tests de integración: repositorios con PostgreSQL real
24. Tests contractuales: schemas de respuesta de los 11 endpoints
25. Tests de regresión: health endpoints existentes no modificados

### Fase 9: Validación final
26. `ruff check`, `ruff format`, `mypy`
27. `pytest` con cobertura >= 85%
28. Docker Compose operativo

---

## 13. Estrategia de Tests

### 13.1 Unit tests (`tests/unit/`)
- `test_normalization.py`: funciones de normalización con casos límite
- `test_state_machine.py`: transiciones válidas/inválidas, closed_at
- `test_schemas.py` (extendido): validación de request/response schemas
- `test_validation_error_format.py`: formato de VALIDATION_ERROR con múltiples campos

### 13.2 Integration tests (`tests/integration/`)
- `test_employee_repository.py`: CRUD completo con PostgreSQL real
- `test_case_file_repository.py`: CRUD + filtros + paginación
- `test_case_status_history_repository.py`: creación + consulta
- `test_uow_transactions.py`: atomicidad de UoW (commit, rollback)
- `test_migrations.py` (extendido): verificación de tablas, constraints, índices
- `test_postgres.py` (regresión): conexiones existentes sin cambios

### 13.3 Contract tests (`tests/contract/`)
- `test_employee_endpoints.py`: schemas de respuesta de los 5 endpoints
- `test_case_file_endpoints.py`: schemas de respuesta de los 6 endpoints
- `test_error_response.py`: estructura de errores uniformes
- `test_health_*.py` (regresión): health endpoints sin cambios

### 13.4 Patrones de test
- Usar `httpx.AsyncClient` con `ASGITransport` para tests HTTP
- Para tests de BD: crear engine directo, sesiones, tablas temporales o transacciones rollback
- Fixtures: `@pytest.fixture` con datos ficticios (nunca datos reales)
- Marcar tests con `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.contract`

---

## 14. Docker Compose

**No se requieren cambios** a `compose.yaml`. Los servicios existentes (`postgres` y `api`) son suficientes. La migración se ejecuta como parte del startup o manualmente.

**Consideración**: Si se desea auto-migrar al iniciar, se puede agregar un script de entrypoint que ejecute `alembic upgrade head` antes de levantar uvicorn, pero esto es opcional y no está especificado.

---

## 15. Excluido del Incremento

Según la spec (sección "Alcance Excluido"), NO se implementa:

- Ollama para generación de contenido
- Prompts y few-shot
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

---

## 16. Áreas de Riesgo

| Riesgo | Mitigación |
|---|---|
| **Atomicidad creación expediente + historial**: si falla uno pero no el otro, datos inconsistentes | Unit of Work con transacción explícita; rollback completo en excepción |
| **Concurrencia optimista**: implementación con UPDATE...WHERE version puede tener race conditions | Usar `SELECT ... FOR UPDATE` previo al UPDATE para serializar accesos; o bien confiar en el WHERE + retry |
| **CUIL parcialmente nulo + UNIQUE**: PostgreSQL permite múltiples NULL en UNIQUE, pero el spec requiere unicidad | Validar duplicidad de CUIL en la capa de aplicación antes de insertar; índice parcial `WHERE cuil IS NOT NULL` |
| **Migración 002 dependiente de 001**: si 001 no fue ejecutada, falla | Verificar `down_revision = "001"` en la migración |
| **UUID inválido en path vs 404**: FastAPI retorna 422 automático para UUID inválido | Aprovechar el comportamiento de FastAPI; el spec requiere exactamente esto (422 para sintaxis, 404 para inexistencia) |
| **Validación de body vacío**: el spec exige errores para cada campo obligatorio faltante, no error genérico | Usar `model_validate()` con validadores customizados o manejar el caso vacío explícitamente |
| **Health endpoints sin cambios**: riesgo de que la adición de modelos ORM rompa el `target_metadata` de Alembic | Mantener `target_metadata = None` en `env.py` hasta que se decida usar autogenerate; o importar metadata de modelos solo en migraciones |

---

## 17. Archivos a Crear/Modificar

### Nuevos archivos:
```
src/legal_ai/
  domain/enums.py
  domain/normalization.py
  domain/employee.py
  domain/case_file.py
  domain/case_status_history.py
  ports/employee_repository.py
  ports/case_file_repository.py
  ports/case_status_history_repository.py
  adapters/database/models.py
  adapters/database/employee_repository.py
  adapters/database/case_file_repository.py
  adapters/database/case_status_history_repository.py
  adapters/database/unit_of_work.py
  schemas/employee.py
  schemas/case_file.py
  schemas/pagination.py
  application/employee_service.py
  application/case_file_service.py
  api/routes/employees.py
  api/routes/case_files.py
  api/exceptions.py

tests/
  unit/test_normalization.py
  unit/test_state_machine.py
  unit/test_employee_schemas.py
  unit/test_case_file_schemas.py
  integration/test_employee_repository.py
  integration/test_case_file_repository.py
  integration/test_case_status_history_repository.py
  integration/test_uow_transactions.py
  contract/test_employee_endpoints.py
  contract/test_case_file_endpoints.py
  contract/test_error_response.py

alembic/versions/
  002_employees_and_case_files.py
```

### Archivos modificados:
```
src/legal_ai/
  schemas/errors.py         (agregar ValidationErrorDetail, campo errors)
  api/router.py             (incluir employees y case_files routers)
  main.py                   (registrar exception handlers)
  config.py                 (sin cambios necesarios)

tests/
  conftest.py               (agregar fixtures de BD para tests)
  integration/test_postgres.py (regresión, sin cambios)
  contract/test_health_*.py    (regresión, sin cambios)

alembic/env.py               (opcional: importar metadata de modelos)
```

---

## 18. Dependencias entre Módulos

```
domain/enums.py          ← raíz (sin dependencias)
domain/normalization.py  ← raíz (sin dependencias)
domain/employee.py       ← domain/enums.py
domain/case_file.py      ← domain/enums.py
domain/case_status_history.py ← domain/enums.py

schemas/errors.py        ← raíz
schemas/pagination.py    ← schemas (Generic[T])
schemas/employee.py      ← schemas/errors.py, domain/enums.py
schemas/case_file.py     ← schemas/errors.py, domain/enums.py

ports/*_repository.py    ← domain/*.py

adapters/database/models.py      ← domain/enums.py
adapters/database/*_repository.py ← ports/*_repository.py, adapters/database/models.py
adapters/database/unit_of_work.py ← adapters/database/*_repository.py

application/employee_service.py   ← ports/*_repository.py, domain/normalization.py
application/case_file_service.py  ← ports/*_repository.py, domain/case_file.py

api/routes/employees.py  ← application/employee_service.py, schemas/employee.py
api/routes/case_files.py ← application/case_file_service.py, schemas/case_file.py
api/exceptions.py        ← schemas/errors.py
main.py                  ← api/exceptions.py (handler registration)
```

---

## 19. Notas de Implementación

1. **`case_number`**: se genera como `CF-{uuid4}` en el servicio de aplicación, no en el endpoint. El UUID se genera con Python `uuid.uuid4()`.
2. **`employee_number`**: lo proporciona el cliente, es inmutable. No se normaliza más allá de trim.
3. **`document_number`**: se normaliza antes de persistir y antes de verificar unicidad.
4. **`cuil`**: se almacena solo dígitos (11 caracteres). Se valida en aplicación antes de UNIQUE constraint.
5. **`closed_at`**: solo se actualiza en transición hacia `archived`. Una vez asignado, inmutable.
6. **`changed_by`**: se obtiene del request body, no de autenticación (no hay auth en este incremento).
7. **`request_id`**: se obtiene de `request.state.request_id` (middleware existente).
8. **Orden determinista**: `created_at DESC, id DESC` para listados.
9. **No DELETE físico**: no se implementa endpoint DELETE para ninguna entidad.
10. **Privacy**: los tests usan datos ficticios. No registrar documentos completos en logs.

---

## 20. Checklist de Validación

- [ ] Migración Alembic 002 ejecutable desde base vacía
- [ ] 11 endpoints funcionando con contratos exactos
- [ ] Máquina de estados respetada (transiciones válidas/inválidas)
- [ ] Concurrencia optimista detectando conflictos
- [ ] Historial append-only con atomicidad
- [ ] Normalización de datos según spec
- [ ] Errores estructurados con 11 códigos estables
- [ ] Paginación con total exacto y empty page handling
- [ ] Health endpoints sin cambios (regresión)
- [ ] `ruff check`, `ruff format`, `mypy` aprobados
- [ ] Cobertura >= 85%
- [ ] Docker Compose operativo
- [ ] Sin datos personales reales en tests/fixtures
