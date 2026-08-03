# Templates API Contract

## POST /api/v1/templates

Crear una nueva plantilla de documento.

**Request**

```json
{
  "name": "string",
  "document_type": "enum[DocumentoGenerico, ResolucionDesignacion, ResolucionOtros, Oficio, MemoriaAnual, OTROS]",
  "organ_emisor": "string | null",
  "normativa": "string | null",
  "description": "string | null",
  "body_template": "string",
  "variables": [
    {
      "name": "string",
      "type": "enum[str, int, float, bool, date, list[str]]",
      "description": "string | null",
      "default_value": "any | null",
      "required": "bool",
      "validation_regex": "string | null"
    }
  ]
}
```

```python
# Pydantic v2
class CreateTemplateRequest(BaseModel):
    name: str
    document_type: DocumentType
    organ_emisor: str | None = None
    normativa: str | None = None
    description: str | None = None
    body_template: str
    variables: list[TemplateVariableSchema]
```

**Response 201**

```json
{
  "id": "uuid",
  "name": "string",
  "document_type": "enum",
  "organ_emisor": "string | null",
  "normativa": "string | null",
  "description": "string | null",
  "body_template": "string",
  "variables": [
    {
      "name": "string",
      "type": "enum",
      "description": "string | null",
      "default_value": "any | null",
      "required": "bool",
      "validation_regex": "string | null"
    }
  ],
  "is_active": "bool",
  "created_at": "datetime",
  "updated_at": "datetime",
  "version": "int"
}
```

```python
# Pydantic v2
class TemplateResponse(BaseModel):
    id: UUID
    name: str
    document_type: DocumentType
    organ_emisor: str | None = None
    normativa: str | None = None
    description: str | None = None
    body_template: str
    variables: list[TemplateVariableSchema]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    version: int
```

**Status Codes**

| Code | Descripción |
|------|-------------|
| 201 | Plantilla creada exitosamente |
| 409 | DOCUMENT_TEMPLATE_NAME_EXISTS - Nombre de plantilla ya registrado |
| 422 | VALIDATION_ERROR - Error de validación en campos |
| 500 | DATABASE_ERROR - Error de base de datos |

**Idempotency**: No. Cada POST crea un nuevo recurso.

**Concurrency**: Sin conflictos de concurrencia en creación.

---

## GET /api/v1/templates

Listar plantillas con filtros opcionales.

**Query Parameters**

| Param | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| document_type | string \| null | null | Filtrar por tipo de documento |
| search | string \| null | null | Buscar por nombre (parcial) |
| skip | int | 0 | Offset para paginación |
| limit | int | 20 | Máximo de resultados |

**Response 200**

```json
{
  "items": [
    {
      "id": "uuid",
      "name": "string",
      "document_type": "enum",
      "organ_emisor": "string | null",
      "normativa": "string | null",
      "description": "string | null",
      "body_template": "string",
      "variables": [
        {
          "name": "string",
          "type": "enum",
          "description": "string | null",
          "default_value": "any | null",
          "required": "bool",
          "validation_regex": "string | null"
        }
      ],
      "is_active": "bool",
      "created_at": "datetime",
      "updated_at": "datetime",
      "version": "int"
    }
  ],
  "total": "int",
  "skip": "int",
  "limit": "int"
}
```

```python
# Pydantic v2
class TemplateListResponse(BaseModel):
    items: list[TemplateResponse]
    total: int
    skip: int
    limit: int
```

**Status Codes**

| Code | Descripción |
|------|-------------|
| 200 | Lista de plantillas |
| 422 | VALIDATION_ERROR - Parámetros de query inválidos |

**Idempotency**: Lectura idempotente por definición.

**Concurrency**: Sin conflictos. Lectura de snapshot consistente.

---

## GET /api/v1/templates/{template_id}

Obtener una plantilla por ID.

**Path Parameters**

| Param | Tipo | Descripción |
|-------|------|-------------|
| template_id | UUID | ID de la plantilla |

**Response 200**

```json
{
  "id": "uuid",
  "name": "string",
  "document_type": "enum",
  "organ_emisor": "string | null",
  "normativa": "string | null",
  "description": "string | null",
  "body_template": "string",
  "variables": [
    {
      "name": "string",
      "type": "enum",
      "description": "string | null",
      "default_value": "any | null",
      "required": "bool",
      "validation_regex": "string | null"
    }
  ],
  "is_active": "bool",
  "created_at": "datetime",
  "updated_at": "datetime",
  "version": "int"
}
```

**Status Codes**

| Code | Descripción |
|------|-------------|
| 200 | Plantilla encontrada |
| 404 | DOCUMENT_TEMPLATE_NOT_FOUND - Plantilla no existe |
| 422 | VALIDATION_ERROR - UUID inválido |

**Idempotency**: Lectura idempotente por definición.

**Concurrency**: Sin conflictos. Lectura de snapshot consistente.

---

## PATCH /api/v1/templates/{template_id}

Actualizar parcialemente una plantilla existente.

**Path Parameters**

| Param | Tipo | Descripción |
|-------|------|-------------|
| template_id | UUID | ID de la plantilla |

**Request**

```json
{
  "name": "string | null",
  "organ_emisor": "string | null",
  "normativa": "string | null",
  "description": "string | null",
  "body_template": "string | null",
  "variables": [
    {
      "name": "string",
      "type": "enum",
      "description": "string | null",
      "default_value": "any | null",
      "required": "bool",
      "validation_regex": "string | null"
    }
  ] | null
}
```

```python
# Pydantic v2
class UpdateTemplateRequest(BaseModel):
    name: str | None = None
    organ_emisor: str | None = None
    normativa: str | None = None
    description: str | None = None
    body_template: str | None = None
    variables: list[TemplateVariableSchema] | None = None
```

**Response 200**

```json
{
  "id": "uuid",
  "name": "string",
  "document_type": "enum",
  "organ_emisor": "string | null",
  "normativa": "string | null",
  "description": "string | null",
  "body_template": "string",
  "variables": [
    {
      "name": "string",
      "type": "enum",
      "description": "string | null",
      "default_value": "any | null",
      "required": "bool",
      "validation_regex": "string | null"
    }
  ],
  "is_active": "bool",
  "created_at": "datetime",
  "updated_at": "datetime",
  "version": "int"
}
```

**Status Codes**

| Code | Descripción |
|------|-------------|
| 200 | Plantilla actualizada |
| 404 | DOCUMENT_TEMPLATE_NOT_FOUND - Plantilla no existe |
| 409 | DOCUMENT_TEMPLATE_NAME_EXISTS - Nombre duplicado en otra plantilla |
| 422 | VALIDATION_ERROR - Error de validación en campos |

**Idempotency**: Patch idempotente si se envían los mismos campos.

**Concurrency**: Control de concurrencia mediante campo `version`. Si la versión en BD difiere de la enviada, retorna 409 CONCURRENT_MODIFICATION.

---

## POST /api/v1/templates/{template_id}/deactivate

Desactivar una plantilla (soft delete lógico).

**Path Parameters**

| Param | Tipo | Descripción |
|-------|------|-------------|
| template_id | UUID | ID de la plantilla |

**Response 200**

```json
{
  "id": "uuid",
  "name": "string",
  "document_type": "enum",
  "organ_emisor": "string | null",
  "normativa": "string | null",
  "description": "string | null",
  "body_template": "string",
  "variables": [
    {
      "name": "string",
      "type": "enum",
      "description": "string | null",
      "default_value": "any | null",
      "required": "bool",
      "validation_regex": "string | null"
    }
  ],
  "is_active": "bool",
  "created_at": "datetime",
  "updated_at": "datetime",
  "version": "int"
}
```

**Status Codes**

| Code | Descripción |
|------|-------------|
| 200 | Plantilla desactivada |
| 404 | DOCUMENT_TEMPLATE_NOT_FOUND - Plantilla no existe |
| 422 | VALIDATION_ERROR - UUID inválido |

**Idempotency**: Idempotente. Desactivar una plantilla ya desactivada retorna 200 sin cambios.

**Concurrency**: Control de concurrencia mediante campo `version`.
