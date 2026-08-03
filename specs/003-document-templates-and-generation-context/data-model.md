# Modelo de Datos — Incremento 003: Plantillas de Documentos y Contexto de Generación

## Descripción General

Este documento define el modelo de datos para el sistema de generación de documentos legales con IA. Se introducen 5 tablas nuevas que cubren plantillas, datos de designación, borradores, transiciones de estado y tracking de intentos de generación.

---

## Tablas

### 1. `document_templates`

Almacena las plantillas de documentos legales con sus variables, tipo de documento y versión.

```sql
CREATE TABLE document_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    document_type VARCHAR(50) NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    organ_emisor VARCHAR(200),
    normativa TEXT,
    description TEXT,
    body_template TEXT NOT NULL,
    variables JSONB DEFAULT '[]'::jsonb,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    CONSTRAINT uq_template_name_type_version UNIQUE (name, document_type, version)
);
```

**Restricciones:**

| Nombre | Tipo | Columnas | Descripción |
|--------|------|----------|-------------|
| `uq_template_name_type_version` | UNIQUE | `(name, document_type, version)` | Evita duplicados de plantilla por nombre, tipo y versión |

**Índices:**

```sql
CREATE INDEX ix_templates_document_type ON document_templates(document_type);
CREATE INDEX ix_templates_is_active ON document_templates(is_active);
CREATE INDEX ix_templates_name ON document_templates(name);
```

---

### 2. `designation_data`

Datos específicos de designación vinculados a un expediente. Relación uno a uno con `case_files`.

```sql
CREATE TABLE designation_data (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_file_id UUID NOT NULL REFERENCES case_files(id) UNIQUE,
    position_name VARCHAR(200) NOT NULL,
    organizational_unit VARCHAR(200),
    start_date DATE,
    legal_basis TEXT,
    appointing_authority VARCHAR(200),
    salary_category VARCHAR(100),
    work_schedule VARCHAR(100),
    observations TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);
```

**Restricciones:**

| Nombre | Tipo | Columnas | Descripción |
|--------|------|----------|-------------|
| `designation_data_case_file_id_key` | UNIQUE | `(case_file_id)` | Garantiza relación uno a uno con expediente |

**Índices:**

```sql
CREATE INDEX ix_designation_data_case_file_id ON designation_data(case_file_id);
```

---

### 3. `document_drafts`

Borradores generados a partir de plantillas. Cada borrador puede tener versiones sucesivas mediante auto-referencia (`parent_draft_id`).

```sql
CREATE TABLE document_drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id UUID NOT NULL REFERENCES document_templates(id),
    case_file_id UUID NOT NULL REFERENCES case_files(id),
    title VARCHAR(300) NOT NULL,
    content TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'GENERADO',
    version INTEGER NOT NULL DEFAULT 1,
    generation_number INTEGER NOT NULL DEFAULT 1,
    context_snapshot JSONB NOT NULL,
    context_hash VARCHAR(64) NOT NULL,
    variables_used JSONB DEFAULT '{}'::jsonb,
    parent_draft_id UUID REFERENCES document_drafts(id),
    observations TEXT,
    request_id VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);
```

**Estados posibles (`status`):**

| Valor | Descripción |
|-------|-------------|
| `GENERADO` | Borrador recién generado por la IA |
| `REVISADO` | Borrador revisado por un usuario |
| `APROBADO` | Borrador aprobado para envío |
| `ENVIADO` | Borrador enviado al organismo |
| `RECHAZADO` | Borrador rechazado |

**Índices:**

```sql
CREATE INDEX ix_drafts_case_file_id ON document_drafts(case_file_id);
CREATE INDEX ix_drafts_status ON document_drafts(status);
CREATE INDEX ix_drafts_parent_draft_id ON document_drafts(parent_draft_id);
CREATE INDEX ix_drafts_template_id ON document_drafts(template_id);
CREATE INDEX ix_drafts_context_hash ON document_drafts(context_hash);
```

---

### 4. `draft_transitions`

Registro de auditoría de cada cambio de estado en un borrador.

```sql
CREATE TABLE draft_transitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id UUID NOT NULL REFERENCES document_drafts(id),
    from_status VARCHAR(20) NOT NULL,
    to_status VARCHAR(20) NOT NULL,
    action VARCHAR(50) NOT NULL,
    observations TEXT,
    performed_by VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);
```

**Índices:**

```sql
CREATE INDEX ix_draft_transitions_draft_id ON draft_transitions(draft_id);
```

---

### 5. `generation_attempts`

Tracking de cada intento de generación de documento con IA, incluyendo idempotencia y manejo de errores.

```sql
CREATE TABLE generation_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_file_id UUID NOT NULL REFERENCES case_files(id),
    template_id UUID NOT NULL REFERENCES document_templates(id),
    idempotency_key VARCHAR(100) UNIQUE,
    model VARCHAR(100) NOT NULL,
    prompt_hash VARCHAR(64) NOT NULL,
    prompt_content TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'IN_PROGRESS',
    started_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    completed_at TIMESTAMP WITH TIME ZONE,
    error_code VARCHAR(50),
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);
```

**Estados posibles (`status`):**

| Valor | Descripción |
|-------|-------------|
| `IN_PROGRESS` | Generación en curso |
| `COMPLETED` | Generación exitosa |
| `FAILED` | Generación fallida |
| `TIMEOUT` | Tiempo de espera agotado |

**Restricciones:**

| Nombre | Tipo | Columnas | Descripción |
|--------|------|----------|-------------|
| `generation_attempts_idempotency_key_key` | UNIQUE | `(idempotency_key)` | Garantiza procesamiento idempotente |

**Índices:**

```sql
CREATE INDEX ix_generation_attempts_idempotency_key ON generation_attempts(idempotency_key);
CREATE INDEX ix_generation_attempts_case_file_id ON generation_attempts(case_file_id);
CREATE INDEX ix_generation_attempts_status ON generation_attempts(status);
```

---

## Relaciones

| Tabla Origen | Columna FK | Tabla Destino | Cardinalidad | Descripción |
|--------------|------------|---------------|--------------|-------------|
| `document_drafts` | `template_id` | `document_templates` | N:1 | Cada borrador usa una plantilla |
| `document_drafts` | `case_file_id` | `case_files` | N:1 | Cada borrador pertenece a un expediente |
| `document_drafts` | `parent_draft_id` | `document_drafts` | N:1 (auto-ref) | Versiones encadenadas de un borrador |
| `designation_data` | `case_file_id` | `case_files` | 1:1 | Datos de designación por expediente |
| `draft_transitions` | `draft_id` | `document_drafts` | N:1 | Historial de transiciones por borrador |
| `generation_attempts` | `case_file_id` | `case_files` | N:1 | Intentos de generación por expediente |
| `generation_attempts` | `template_id` | `document_templates` | N:1 | Intentos de generación por plantilla |

---

## Diagrama ER (texto)

```
case_files (002) ──┬──< document_drafts
                   ├──< designation_data (1:1)
                   ├──< generation_attempts
                   │
document_templates ──┬──< document_drafts
                     └──< generation_attempts
                     │
document_drafts ──< document_drafts (self-ref: parent_draft_id)
document_drafts ──< draft_transitions
```

**Leyenda:**

- `──<` = relación uno a muchos (FK en el lado `<`)
- `(1:1)` = relación uno a uno
- `(self-ref)` = auto-referencia

---

## Orden de Migración

Las tablas se crean en el siguiente orden para respetar las dependencias de claves foráneas:

| Paso | Tabla | Dependencias FK |
|------|-------|-----------------|
| 1 | `document_templates` | Ninguna (tabla base) |
| 2 | `designation_data` | `case_files` (incremento 002) |
| 3 | `document_drafts` | `document_templates`, `case_files`, auto-ref |
| 4 | `draft_transitions` | `document_drafts` |
| 5 | `generation_attempts` | `case_files`, `document_templates` |

---

## Orden de Eliminación (inverso)

Para eliminar las tablas sin errores de integridad referencial, se usa el orden inverso:

| Paso | Tabla |
|------|-------|
| 1 | `generation_attempts` |
| 2 | `draft_transitions` |
| 3 | `document_drafts` |
| 4 | `designation_data` |
| 5 | `document_templates` |

---

## Notas sobre Campos JSONB

### `document_templates.variables`

```json
[
  {
    "name": "nombre_completo",
    "type": "string",
    "required": true,
    "description": "Nombre completo del designado"
  },
  {
    "name": "fecha_designacion",
    "type": "date",
    "required": true,
    "description": "Fecha de la designación"
  }
]
```

### `document_drafts.context_snapshot`

Copia completa del contexto utilizado al momento de generar el borrador. Incluye datos del expediente, datos de designación y variables resueltas.

```json
{
  "case_file": { "..." },
  "designation": { "..." },
  "resolved_variables": { "nombre_completo": "Juan Pérez" },
  "generated_at": "2026-07-31T10:00:00Z"
}
```

### `document_drafts.variables_used`

Valores efectivamente utilizados durante la generación del documento.

```json
{
  "nombre_completo": "Juan Pérez",
  "fecha_designacion": "2026-07-31",
  "cargo": "Director de Administración"
}
```
