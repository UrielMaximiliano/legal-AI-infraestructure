# Designation API Contract

## POST /api/v1/case-files/{case_file_id}/designation

Crear datos de_designación para un expediente (solo uno por expediente).

**Path Parameters**

| Param | Tipo | Descripción |
|-------|------|-------------|
| case_file_id | UUID | ID del expediente |

**Request**

```json
{
  "position_name": "string",
  "organizational_unit": "string | null",
  "start_date": "date | null",
  "legal_basis": "string | null",
  "appointing_authority": "string | null",
  "salary_category": "string | null",
  "work_schedule": "string | null",
  "observations": "string | null"
}
```

```python
# Pydantic v2
class CreateDesignationDataRequest(BaseModel):
    position_name: str
    organizational_unit: str | None = None
    start_date: date | None = None
    legal_basis: str | None = None
    appointing_authority: str | None = None
    salary_category: str | None = None
    work_schedule: str | None = None
    observations: str | None = None
```

**Response 201**

```json
{
  "id": "uuid",
  "case_file_id": "uuid",
  "position_name": "string",
  "organizational_unit": "string | null",
  "start_date": "date | null",
  "legal_basis": "string | null",
  "appointing_authority": "string | null",
  "salary_category": "string | null",
  "work_schedule": "string | null",
  "observations": "string | null",
  "created_at": "datetime",
  "updated_at": "datetime",
  "version": "int"
}
```

```python
# Pydantic v2
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
    version: int
```

**Status Codes**

| Code | Descripción |
|------|-------------|
| 201 | Designación creada exitosamente |
| 404 | CASE_FILE_NOT_FOUND - Expediente no encontrado |
| 409 | CASE_FILE_TYPE_INCOMPATIBLE - Tipo de expediente no admite designación |
| 409 | DOCUMENT_TEMPLATE_CONFLICT - Ya existe designación para este expediente |
| 422 | VALIDATION_ERROR - Error de validación en campos |

**Idempotency**: No idempotente por defecto. Reintentos con mismo payload crean duplicados.

**Concurrency**: Validación de unicidad case_file_id en repository layer.

---

## GET /api/v1/case-files/{case_file_id}/designation

Obtener datos de_designación de un expediente.

**Path Parameters**

| Param | Tipo | Descripción |
|-------|------|-------------|
| case_file_id | UUID | ID del expediente |

**Response 200**

```json
{
  "id": "uuid",
  "case_file_id": "uuid",
  "position_name": "string",
  "organizational_unit": "string | null",
  "start_date": "date | null",
  "legal_basis": "string | null",
  "appointing_authority": "string | null",
  "salary_category": "string | null",
  "work_schedule": "string | null",
  "observations": "string | null",
  "created_at": "datetime",
  "updated_at": "datetime",
  "version": "int"
}
```

**Status Codes**

| Code | Descripción |
|------|-------------|
| 200 | Designación encontrada |
| 404 | CASE_FILE_NOT_FOUND - Expediente no encontrado |
| 404 | DESIGNATION_DATA_NOT_FOUND - No hay designación registrada |
| 422 | VALIDATION_ERROR - UUID inválido |

**Idempotency**: Lectura idempotente por definición.

**Concurrency**: Sin conflictos. Lectura de snapshot consistente.

---

## PUT /api/v1/case-files/{case_file_id}/designation

Reemplazar completamente los datos de_designación de un expediente.

**Path Parameters**

| Param | Tipo | Descripción |
|-------|------|-------------|
| case_file_id | UUID | ID del expediente |

**Request**

```json
{
  "position_name": "string",
  "organizational_unit": "string | null",
  "start_date": "date | null",
  "legal_basis": "string | null",
  "appointing_authority": "string | null",
  "salary_category": "string | null",
  "work_schedule": "string | null",
  "observations": "string | null"
}
```

```python
# Pydantic v2
# Mismo schema que CreateDesignationDataRequest
class CreateDesignationDataRequest(BaseModel):
    position_name: str
    organizational_unit: str | None = None
    start_date: date | None = None
    legal_basis: str | None = None
    appointing_authority: str | None = None
    salary_category: str | None = None
    work_schedule: str | None = None
    observations: str | None = None
```

**Response 200**

```json
{
  "id": "uuid",
  "case_file_id": "uuid",
  "position_name": "string",
  "organizational_unit": "string | null",
  "start_date": "date | null",
  "legal_basis": "string | null",
  "appointing_authority": "string | null",
  "salary_category": "string | null",
  "work_schedule": "string | null",
  "observations": "string | null",
  "created_at": "datetime",
  "updated_at": "datetime",
  "version": "int"
}
```

**Status Codes**

| Code | Descripción |
|------|-------------|
| 200 | Designación actualizada |
| 404 | CASE_FILE_NOT_FOUND - Expediente no encontrado |
| 409 | CASE_FILE_TYPE_INCOMPATIBLE - Tipo de expediente no admite designación |
| 422 | VALIDATION_ERROR - Error de validación en campos |

**Idempotency**: Idempotente si se envía el mismo payload. PUT reemplaza recurso completo.

**Concurrency**: Control de concurrencia mediante campo `version`. Si la versión en BD difiere, retorna 409 CONCURRENT_MODIFICATION.
