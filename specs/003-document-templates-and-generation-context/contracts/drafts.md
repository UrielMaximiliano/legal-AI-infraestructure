# Drafts API Contract

## POST /api/v1/drafts/generate

Generar un borrador de documento a partir de una plantilla y datos de un expediente.

**Headers**

| Header | Tipo | Requerido | Descripción |
|--------|------|-----------|-------------|
| Idempotency-Key | string \| null | No | Clave de idempotencia para reintentos seguros |

**Request**

```json
{
  "template_id": "uuid",
  "case_file_id": "uuid",
  "variables": {
    "key": "value"
  }
}
```

```python
# Pydantic v2
class GenerateDraftRequest(BaseModel):
    template_id: UUID
    case_file_id: UUID
    variables: dict[str, Any]
```

**Response 201**

```json
{
  "id": "uuid",
  "template_id": "uuid",
  "case_file_id": "uuid",
  "title": "string",
  "content": "string",
  "status": "enum[generating, pending_review, approved, rejected, finalized]",
  "version": "int",
  "generation_metadata": {
    "attempt_id": "uuid",
    "model_used": "string",
    "tokens_input": "int",
    "tokens_output": "int",
    "duration_ms": "int"
  },
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

```python
# Pydantic v2
class GenerationMetadata(BaseModel):
    attempt_id: UUID
    model_used: str
    tokens_input: int
    tokens_output: int
    duration_ms: int

class DraftResponse(BaseModel):
    id: UUID
    template_id: UUID
    case_file_id: UUID
    title: str
    content: str
    status: DraftStatus
    version: int
    generation_metadata: GenerationMetadata | None = None
    created_at: datetime
    updated_at: datetime
```

**Status Codes**

| Code | Descripción |
|------|-------------|
| 201 | Borrador generado exitosamente |
| 404 | DOCUMENT_TEMPLATE_NOT_FOUND - Plantilla no encontrada |
| 404 | CASE_FILE_NOT_FOUND - Expediente no encontrado |
| 409 | DOCUMENT_TEMPLATE_INACTIVE - Plantilla desactivada |
| 409 | IDEMPOTENCY_KEY_MISMATCH - Key diferente para mismo request |
| 409 | GENERATION_IN_PROGRESS - Ya hay una generación en curso |
| 422 | VALIDATION_ERROR - Error de validación |
| 422 | MISSING_REQUIRED_VARIABLES - Variables requeridas faltantes |
| 422 | DESIGNATION_DATA_INCOMPLETE - Datos de_designación incompletos |
| 500 | CONTEXT_BUILD_FAILED - Error al construir contexto |
| 502 | GENERATION_FAILED - Error en la generación del modelo |
| 503 | OLLAMA_UNAVAILABLE - Servicio Ollama no disponible |
| 504 | OLLAMA_TIMEOUT - Timeout en respuesta de Ollama |

**Idempotency**: Sí. Si se envía `Idempotency-Key` header:
- Misma key + mismo request → retorna respuesta cacheada (201)
- Misma key + request diferente → 409 IDEMPOTENCY_KEY_MISMATCH
- Sin key → comportamiento normal (no idempotente)

**Concurrency**: 
- Solo una generación activa por case_file_id a la vez.
- `GENERATION_IN_PROGRESS` se verifica antes de iniciar la tarea.
- La generación corre async; el endpoint retorna 201 inmediatamente con status `generating`.

---

## GET /api/v1/case-files/{case_file_id}/drafts

Listar borradores de un expediente.

**Path Parameters**

| Param | Tipo | Descripción |
|-------|------|-------------|
| case_file_id | UUID | ID del expediente |

**Query Parameters**

| Param | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| status | string \| null | null | Filtrar por estado del borrador |
| skip | int | 0 | Offset para paginación |
| limit | int | 20 | Máximo de resultados |

**Response 200**

```json
{
  "items": [
    {
      "id": "uuid",
      "template_id": "uuid",
      "case_file_id": "uuid",
      "title": "string",
      "content": "string",
      "status": "enum",
      "version": "int",
      "generation_metadata": {
        "attempt_id": "uuid",
        "model_used": "string",
        "tokens_input": "int",
        "tokens_output": "int",
        "duration_ms": "int"
      },
      "created_at": "datetime",
      "updated_at": "datetime"
    }
  ],
  "total": "int",
  "skip": "int",
  "limit": "int"
}
```

```python
# Pydantic v2
class DraftListResponse(BaseModel):
    items: list[DraftResponse]
    total: int
    skip: int
    limit: int
```

**Status Codes**

| Code | Descripción |
|------|-------------|
| 200 | Lista de borradores |
| 404 | CASE_FILE_NOT_FOUND - Expediente no encontrado |
| 422 | VALIDATION_ERROR - Parámetros de query inválidos |

**Idempotency**: Lectura idempotente por definición.

**Concurrency**: Sin conflictos. Lectura de snapshot consistente.

---

## GET /api/v1/drafts/{draft_id}

Obtener un borrador por ID.

**Path Parameters**

| Param | Tipo | Descripción |
|-------|------|-------------|
| draft_id | UUID | ID del borrador |

**Response 200**

```json
{
  "id": "uuid",
  "template_id": "uuid",
  "case_file_id": "uuid",
  "title": "string",
  "content": "string",
  "status": "enum",
  "version": "int",
  "generation_metadata": {
    "attempt_id": "uuid",
    "model_used": "string",
    "tokens_input": "int",
    "tokens_output": "int",
    "duration_ms": "int"
  },
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

**Status Codes**

| Code | Descripción |
|------|-------------|
| 200 | Borrador encontrado |
| 404 | DRAFT_NOT_FOUND - Borrador no existe |
| 422 | VALIDATION_ERROR - UUID inválido |

**Idempotency**: Lectura idempotente por definición.

**Concurrency**: Sin conflictos. Lectura de snapshot consistente.

---

## PATCH /api/v1/drafts/{draft_id}/content

Editar el contenido de un borrador (solo en estado `pending_review`).

**Path Parameters**

| Param | Tipo | Descripción |
|-------|------|-------------|
| draft_id | UUID | ID del borrador |

**Request**

```json
{
  "content": "string",
  "expected_version": "int"
}
```

```python
# Pydantic v2
class EditDraftContentRequest(BaseModel):
    content: str
    expected_version: int
```

**Response 200**

```json
{
  "id": "uuid",
  "template_id": "uuid",
  "case_file_id": "uuid",
  "title": "string",
  "content": "string",
  "status": "enum",
  "version": "int",
  "generation_metadata": {
    "attempt_id": "uuid",
    "model_used": "string",
    "tokens_input": "int",
    "tokens_output": "int",
    "duration_ms": "int"
  },
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

**Status Codes**

| Code | Descripción |
|------|-------------|
| 200 | Contenido actualizado |
| 404 | DRAFT_NOT_FOUND - Borrador no existe |
| 409 | INVALID_DRAFT_TRANSITION - Estado no permite edición |
| 409 | CONCURRENT_MODIFICATION - expected_version no coincide |
| 422 | VALIDATION_ERROR - Error de validación |
| 422 | CONTENT_TOO_LARGE - Contenido excede límite (50KB) |

**Idempotency**: Idempotente si se envía el mismo contenido con la misma versión.

**Concurrency**: 
- Optimistic locking via `expected_version`.
- Si `expected_version` != versión actual en BD → 409 CONCURRENT_MODIFICATION.
- Se incrementa `version` en cada edición exitosa.

---

## POST /api/v1/drafts/{draft_id}/transitions

Cambiar el estado de un borrador (review → approve/reject/finalize).

**Path Parameters**

| Param | Tipo | Descripción |
|-------|------|-------------|
| draft_id | UUID | ID del borrador |

**Request**

```json
{
  "action": "enum[approve, reject, finalize]",
  "observations": "string | null",
  "expected_version": "int"
}
```

```python
# Pydantic v2
class TransitionDraftRequest(BaseModel):
    action: TransitionAction
    observations: str | None = None
    expected_version: int
```

**Response 200**

```json
{
  "id": "uuid",
  "template_id": "uuid",
  "case_file_id": "uuid",
  "title": "string",
  "content": "string",
  "status": "enum",
  "version": "int",
  "generation_metadata": {
    "attempt_id": "uuid",
    "model_used": "string",
    "tokens_input": "int",
    "tokens_output": "int",
    "duration_ms": "int"
  },
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

**Status Codes**

| Code | Descripción |
|------|-------------|
| 200 | Transición realizada |
| 404 | DRAFT_NOT_FOUND - Borrador no existe |
| 409 | INVALID_DRAFT_TRANSITION - Transición no válida desde estado actual |
| 409 | CONCURRENT_MODIFICATION - expected_version no coincide |
| 409 | DRAFT_ALREADY_APPROVED - Borrador ya aprobado |
| 422 | VALIDATION_ERROR - Error de validación |

**Matriz de transiciones**

| Estado Actual | approve | reject | finalize |
|---------------|---------|--------|----------|
| generating | ✗ | ✗ | ✗ |
| pending_review | ✓ → approved | ✓ → rejected | ✗ |
| approved | ✗ | ✗ | ✓ → finalized |
| rejected | ✓ → pending_review | ✗ | ✗ |
| finalized | ✗ | ✗ | ✗ |

**Idempotency**: Idempotente. Si la transición resulta en el mismo estado (ej. approve sobre approved), retorna 200 sin cambios.

**Concurrency**: 
- Optimistic locking via `expected_version`.
- Si `expected_version` != versión actual en BD → 409 CONCURRENT_MODIFICATION.

---

## POST /api/v1/drafts/{draft_id}/regenerate

Regenerar un borrador creando una nueva versión. Genera un nuevo borrador con status `generating`.

**Path Parameters**

| Param | Tipo | Descripción |
|-------|------|-------------|
| draft_id | UUID | ID del borrador original |

**Request**

```json
{
  "observations": "string",
  "expected_version": "int"
}
```

```python
# Pydantic v2
class RegenerateDraftRequest(BaseModel):
    observations: str
    expected_version: int
```

**Response 201**

```json
{
  "id": "uuid",
  "template_id": "uuid",
  "case_file_id": "uuid",
  "title": "string",
  "content": "string",
  "status": "generating",
  "version": "int",
  "generation_metadata": null,
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

**Status Codes**

| Code | Descripción |
|------|-------------|
| 201 | Nuevo borrador creado para regeneración |
| 404 | DRAFT_NOT_FOUND - Borrador no existe |
| 409 | INVALID_DRAFT_TRANSITION - Estado no permite regeneración |
| 409 | CONCURRENT_MODIFICATION - expected_version no coincide |
| 422 | VALIDATION_ERROR - Error de validación |
| 502 | GENERATION_FAILED - Error en la generación del modelo |
| 503 | OLLAMA_UNAVAILABLE - Servicio Ollama no disponible |
| 504 | OLLAMA_TIMEOUT - Timeout en respuesta de Ollama |

**Reglas de transición para regeneración**

| Estado Actual | Regenerate |
|---------------|------------|
| generating | ✗ |
| pending_review | ✓ |
| approved | ✓ |
| rejected | ✓ |
| finalized | ✗ |

**Idempotency**: No idempotente. Cada regeneración crea un nuevo borrador.

**Concurrency**: 
- Optimistic locking via `expected_version`.
- La regeneración corre async; el endpoint retorna 201 inmediatamente.

---

## GET /api/v1/drafts/{draft_id}/history

Obtener el historial de transiciones de un borrador.

**Path Parameters**

| Param | Tipo | Descripción |
|-------|------|-------------|
| draft_id | UUID | ID del borrador |

**Response 200**

```json
[
  {
    "id": "uuid",
    "draft_id": "uuid",
    "from_status": "enum | null",
    "to_status": "enum",
    "action": "enum",
    "observations": "string | null",
    "created_at": "datetime"
  }
]
```

```python
# Pydantic v2
class DraftTransitionResponse(BaseModel):
    id: UUID
    draft_id: UUID
    from_status: DraftStatus | None = None
    to_status: DraftStatus
    action: TransitionAction
    observations: str | None = None
    created_at: datetime
```

**Status Codes**

| Code | Descripción |
|------|-------------|
| 200 | Historial de transiciones |
| 404 | DRAFT_NOT_FOUND - Borrador no existe |
| 422 | VALIDATION_ERROR - UUID inválido |

**Idempotency**: Lectura idempotente por definición.

**Concurrency**: Sin conflictos. Lectura de snapshot consistente.
