# Generation Attempts API Contract

## GET /api/v1/generation-attempts/{attempt_id}

Obtener un intento de generación por ID.

**Path Parameters**

| Param | Tipo | Descripción |
|-------|------|-------------|
| attempt_id | UUID | ID del intento de generación |

**Response 200**

```json
{
  "id": "uuid",
  "draft_id": "uuid | null",
  "template_id": "uuid",
  "case_file_id": "uuid",
  "model_used": "string",
  "prompt_tokens": "int",
  "completion_tokens": "int",
  "total_tokens": "int",
  "duration_ms": "int",
  "status": "enum[pending, completed, failed]",
  "error_message": "string | null",
  "context_metadata": {
    "template_applied": "bool",
    "designation_included": "bool",
    "variables_resolved": "int",
    "variables_missing": "list[string]"
  },
  "created_at": "datetime",
  "completed_at": "datetime | null"
}
```

```python
# Pydantic v2
class ContextMetadata(BaseModel):
    template_applied: bool
    designation_included: bool
    variables_resolved: int
    variables_missing: list[str]

class GenerationAttemptResponse(BaseModel):
    id: UUID
    draft_id: UUID | None = None
    template_id: UUID
    case_file_id: UUID
    model_used: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    duration_ms: int
    status: GenerationAttemptStatus
    error_message: str | None = None
    context_metadata: ContextMetadata | None = None
    created_at: datetime
    completed_at: datetime | None = None
```

**Status Codes**

| Code | Descripción |
|------|-------------|
| 200 | Intento de generación encontrado |
| 404 | GENERATION_ATTEMPT_NOT_FOUND - Intento no encontrado |
| 422 | VALIDATION_ERROR - UUID inválido |

**Idempotency**: Lectura idempotente por definición.

**Concurrency**: Sin conflictos. Lectura de snapshot consistente.

---

## GET /api/v1/case-files/{case_file_id}/generation-attempts

Listar todos los intentos de generación de un expediente.

**Path Parameters**

| Param | Tipo | Descripción |
|-------|------|-------------|
| case_file_id | UUID | ID del expediente |

**Response 200**

```json
[
  {
    "id": "uuid",
    "draft_id": "uuid | null",
    "template_id": "uuid",
    "case_file_id": "uuid",
    "model_used": "string",
    "prompt_tokens": "int",
    "completion_tokens": "int",
    "total_tokens": "int",
    "duration_ms": "int",
    "status": "enum[pending, completed, failed]",
    "error_message": "string | null",
    "context_metadata": {
      "template_applied": "bool",
      "designation_included": "bool",
      "variables_resolved": "int",
      "variables_missing": "list[string]"
    },
    "created_at": "datetime",
    "completed_at": "datetime | null"
  }
]
```

```python
# Pydantic v2
# Mismo schema que GenerationAttemptResponse
class GenerationAttemptResponse(BaseModel):
    id: UUID
    draft_id: UUID | None = None
    template_id: UUID
    case_file_id: UUID
    model_used: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    duration_ms: int
    status: GenerationAttemptStatus
    error_message: str | None = None
    context_metadata: ContextMetadata | None = None
    created_at: datetime
    completed_at: datetime | None = None
```

**Status Codes**

| Code | Descripción |
|------|-------------|
| 200 | Lista de intentos de generación |
| 404 | CASE_FILE_NOT_FOUND - Expediente no encontrado |
| 422 | VALIDATION_ERROR - UUID inválido |

**Idempotency**: Lectura idempotente por definición.

**Concurrency**: Sin conflictos. Lectura de snapshot consistente.
