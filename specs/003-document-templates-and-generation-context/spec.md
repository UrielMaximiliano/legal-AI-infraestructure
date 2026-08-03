# Especificación: Plantillas de Documentos y Contexto de Generación

**ID de Especificación**: `003-document-templates-and-generation-context`
**Creada**: 2026-07-31
**Estado**: Borrador
**Entrada**: Descripción del usuario: "Plantillas de documentos y contexto de generación con integración Ollama, ciclo de vida de borradores y revisión humana obligatoria"

## Clarifications

### Session 2026-07-31

- Q: Should the prompt be stored in full or only as a hash in generation_attempts? → A: Full prompt stored (conscious decision, trade-off with Principle I noted).
- Q: When content is updated, should templates create a new immutable version or overwrite? → A: Immutable versioning by content. Each modification creates a new version. Previous versions immutable. Only one active version per template_name.
- Q: When Ollama fails during draft generation, what should the system create? → A: No draft. Only register failed attempt in generation_attempts. Return structured error. Allow idempotent retry.
- Q: When should the previous draft change to SUPERSEDED during regeneration? → A: Only after successful new generation. If Ollama fails, previous draft remains in its current state.
- Q: Where should designation data be stored and how linked to case files? → A: Separate `designation_data` table linked to case_file. Snapshot serialized in context_snapshot. Only applies to case_type=designacion.
- Q: What syntax for template variables in body_template? → A: Jinja2-like `{{namespace.field}}` syntax. Namespaces: employee, case_file, designation, variables. No arbitrary expressions.

## Resumen Ejecutivo

Este incremento construye la primera capacidad de negocio jurídico-administrativa
del Gestor de Expedientes IMI. Permite definir plantillas de documentos versionadas
con datos de designación, gestionar el contexto de generación (datos del expediente,
datos del empleado, variables de plantilla), invocar Ollama para generar borradores
asociados a expedientes, y gestionar el ciclo de vida completo del borrador:
generación → revisión → aprobación → superseded, con regeneración controlada
y revisión humana obligatoria en cada paso de decisión.

La plataforma ya dispone de FastAPI, PostgreSQL 16, pgvector, SQLAlchemy async,
Alembic, Docker Compose, health checks, integración con Ollama, request ID,
logging, pruebas y cobertura >= 95% del incremento 002 (empleados y expedientes).

**Declaración de alcance**: Este incremento gestiona plantillas, contexto de
generación, borradores y su ciclo de vida. No implementa embeddings semánticos,
RAG, búsqueda vectorial ni indexes de pgvector. La integración con Ollama es
exclusivamente para generación de texto plano (completion), no para embeddings.

## Declaración del Problema

### Estado Actual

El sistema permite registrar empleados y gestionar expedientes administrativos
con estados controlados (Borrador → En revisión → Aprobado → Desestimado,
Archivado). Sin embargo, no existe forma de generar documentos asociados a
estos expedientes. El personal de Legal y Técnica debe crear cada documento
manualmente desde cero, sin reutilización de formatos ni automatización.

### Estado Deseado

El personal de Legal y Técnica del IMI puede:

1. Definir y administrar plantillas de documentos con campos variables y datos
   de designación (tipo de documento, órgano emisor, normativa aplicable).
2. Consultar el contexto completo de generación (expediente, empleado, variables)
   antes de invocar la generación.
3. Generar borradores de documentos asistidos por IA (Ollama) a partir de una
   plantilla y su contexto.
4. Revisar, editar, aprobar o solicitar regeneración de borradores con
   control de versiones y auditoría completa.
5. Mantener historial completo de versiones mediante cadena de regeneraciones.

### Impacto del Negocio

Sin este incremento, la generación de documentos administrativos sigue siendo
un proceso completamente manual y sin estandarización. Este incremento reduce
el tiempo de redacción, estandariza formatos, y establece las bases para
capacidades avanzadas (RAG, embeddings) en incrementos futuros. La revisión
humana obligatoria (Principio II de la constitución) se implementa desde
el primer momento como requisito no negociable.

## Escenarios de Usuario y Pruebas

### Historia de Usuario Principal

Como personal de Legal y Técnica del IMI,
 quiero crear plantillas de documentos con datos de designación,
 generar borradores asistidos por IA a partir de expedientes existentes,
 y gestionar su ciclo de vida completo (revisión → aprobación),
 para reducir el tiempo de redacción y estandarizar los formatos administrativos.

### Historias de Usuario Secundarias

**HU-01: Crear plantilla de documento**
Como administrador de plantillas,
 quiero definir plantillas con nombre, tipo de documento, órgano emisor,
 normativa, campos variables y contenido Markdown,
 para que el sistema pueda generar documentos estandarizados.

**HU-02: Consultar plantilla por ID**
Como usuario autorizado,
 quiero recuperar una plantilla específica por su UUID,
 para revisar su contenido y configuración.

**HU-03: Listar plantillas activas**
Como usuario autorizado,
 quiero listar todas las plantillas activas con filtros por tipo de documento
 y búsqueda por nombre,
 para encontrar rápidamente la plantilla adecuada.

**HU-04: Actualizar plantilla**
Como administrador de plantillas,
 quiero modificar el contenido, campos variables o metadatos de una plantilla,
 para mantenerla actualizada con los requerimientos legales.

**HU-05: Desactivar plantilla**
Como administrador de plantillas,
 quiero desactivar una plantilla que ya no se utilizará,
 sin eliminar su historial de uso en borradores.

**HU-06: Consultar contexto de generación**
Como usuario autorizado,
 quiero ver el contexto completo de generación de un borrador
 (expediente, empleado, variables de plantilla),
 antes de invocar la generación para verificar que los datos son correctos.

**HU-07: Generar borrador**
Como usuario autorizado,
 quiero invocar la generación de un borrador a partir de una plantilla
 y el contexto de un expediente,
 para obtener un borrador asistido por IA listo para revisar.

**HU-08: Consultar borrador por ID**
Como usuario autorizado,
 quiero recuperar un borrador específico por su UUID,
 para revisar su contenido, estado y versiones.

**HU-09: Listar borradores de un expediente**
Como usuario autorizado,
 quiero listar todos los borradores asociados a un expediente específico,
 con filtros por estado,
 para gestionar el seguimiento de documentos en proceso.

**HU-10: Revisar y aprobar borrador**
Como revisor autorizado,
 quiero aprobar un borrador revisado,
 para avanzarlo al siguiente estado del ciclo de vida.

**HU-11: Solicitar regeneración de borrador**
Como revisor autorizado,
 quiero solicitar la regeneración de un borrador con observaciones específicas,
 para obtener una versión mejorada que atienda las observaciones.

**HU-12: Editar contenido del borrador**
Como editor autorizado,
 quiero modificar manualmente el contenido de un borrador en estado
 "En revisión" o "Rechazado",
 para hacer correcciones antes de la siguiente revisión.

**HU-13: Gestionar historial de versiones**
Como usuario autorizado,
 quiero consultar la cadena completa de versiones de un borrador
 (regeneraciones, ediciones, aprobaciones),
 para entender la evolución del documento a lo largo del tiempo.

### Flujos de Estados del Borrador

```
 Generado → En revisión → Aprobado
    ↓            ↓
  Regenerado   Rechazado → En revisión (re-apertura)
    ↓
  Superseded (cuando nueva generación es exitosa)
```

**Transiciones válidas:**
- `GENERADO` → `EN_REVISION` (automático al crear, o manual al enviar a revisión)
- `EN_REVISION` → `APROBADO` (revisor aprueba)
- `EN_REVISION` → `RECHAZADO` (revisor rechaza con observaciones)
- `RECHAZADO` → `EN_REVISION` (re-apertura tras edición o regeneración)
- Cualquier estado → `SUPERSEDED` (automático cuando una regeneración crea nuevo borrador con éxito)

**Nota**: El estado `PUBLICADO` queda excluido de este incremento para mantener el alcance acotado. La publicación oficial de documentos se implementará en un incremento posterior.

### Escenarios de Prueba (Criterios de Aceptación)

#### Borrador: Generación

| # | Escenario | Dato | Resultado esperado |
|---|-----------|------|---------------------|
| G-01 | Generar borrador con plantilla y contexto válidos | UUID plantilla, UUID expediente, variables | 201, borrador con estado GENERADO, contenido generado por Ollama, asociado al expediente |
| G-02 | Generar borrador con plantilla inexistente | UUID plantilla inexistente | 404, error `TEMPLATE_NOT_FOUND` |
| G-03 | Generar borrador con expediente inexistente | UUID expediente inexistente | 404, error `CASE_FILE_NOT_FOUND` |
| G-04 | Generar borrador con plantilla desactivada | UUID plantilla desactivada | 409, error `TEMPLATE_INACTIVE` |
| G-05 | Generar borrador sin variables requeridas | Faltan variables obligatorias | 422, error `MISSING_REQUIRED_VARIABLES` |
| G-06 | Generar borrador con variables adicionales | Variables extra no definidas en plantilla | 201, se ignoran variables no definidas |
| G-07 | Generar borrador con Ollama no disponible | Ollama timeout | 503, error `OLLAMA_UNAVAILABLE`, no se crea borrador, intento registrado en `generation_attempts` |
| G-08 | Generar borrador con contexto completo | Expediente + empleado + variables | 201, borrador con contexto serializado en `context_snapshot` |
| G-09 | Generar borrador — idempotencia | Misma request idempotente | 201, un solo borrador creado |

#### Borrador: Ciclo de vida

| # | Escenario | Dato | Resultado esperado |
|---|-----------|------|---------------------|
| V-01 | Avanzar GENERADO → EN_REVISION | UUID borrador | 200, estado actualizado |
| V-02 | Avanzar EN_REVISION → APROBADO | UUID borrador | 200, estado actualizado |
| V-03 | Avanzar EN_REVISION → RECHAZADO | UUID borrador + observaciones | 200, estado actualizado, observaciones registradas |
| V-04 | Avanzar RECHAZADO → EN_REVISION | UUID borrador | 200, estado actualizado (re-apertura) |
| V-05 | Transición inválida | Transición no permitida | 409, error `INVALID_TRANSITION` |
| V-06 | Avanzar borrador inexistente | UUID inexistente | 404, error `DRAFT_NOT_FOUND` |

#### Borrador: Regeneración

| # | Escenario | Dato | Resultado esperado |
|---|-----------|------|---------------------|
| R-01 | Regenerar borrador con observaciones | UUID borrador + observaciones | 201, nuevo borrador con estado GENERADO, `previous_draft_id` apunta al original |
| R-02 | Regenerar borrador inexistente | UUID inexistente | 404, error `DRAFT_NOT_FOUND` |
| R-03 | Regenerar borrador en estado inválido | Borrador APROBADO | 409, error `INVALID_TRANSITION` |
| R-04 | Regenerar mantiene cadena de historial | UUID borrador original | Nuevo borrador tiene `previous_draft_id` correcto |
| R-05 | Regenerar con Ollama no disponible | Ollama timeout | 503, error `OLLAMA_UNAVAILABLE`, no se crea nuevo borrador, borrador anterior permanece en su estado actual |

#### Borrador: Edición manual

| # | Escenario | Dato | Resultado esperado |
|---|-----------|------|---------------------|
| E-01 | Editar contenido en estado EN_REVISION | UUID borrador + nuevo contenido | 200, contenido actualizado |
| E-02 | Editar contenido en estado RECHAZADO | UUID borrador + nuevo contenido | 200, contenido actualizado |
| E-03 | Editar contenido en estado GENERADO | UUID borrador | 409, error `INVALID_TRANSITION` |
| E-04 | Editar borrador inexistente | UUID inexistente | 404, error `DRAFT_NOT_FOUND` |

#### Borrador: Consultas

| # | Escenario | Dato | Resultado esperado |
|---|-----------|------|---------------------|
| Q-01 | Listar borradores de expediente | UUID expediente | 200, lista de borradores del expediente |
| Q-02 | Listar borradores con filtro por estado | UUID expediente + estado | 200, lista filtrada |
| Q-03 | Listar borradores de expediente inexistente | UUID inexistente | 404, error `CASE_FILE_NOT_FOUND` |
| Q-04 | Obtener borrador por ID | UUID borrador | 200, borrador con contexto serializado |
| Q-05 | Obtener borrador inexistente | UUID inexistente | 404, error `DRAFT_NOT_FOUND` |

#### Datos de Designación

| # | Escenario | Dato | Resultado esperado |
|---|-----------|------|---------------------|
| D-01 | Crear datos de designación para expediente designación | UUID case_file + datos válidos | 201, designación creada |
| D-02 | Crear datos de designación para expediente no designación | UUID case_file con case_type=otro | 409, error `CASE_FILE_TYPE_INCOMPATIBLE` |
| D-03 | Consultar datos de designación | UUID case_file | 200, designación completa |
| D-04 | Consultar datos de designación inexistente | UUID case_file sin designación | 404, error `DESIGNATION_DATA_NOT_FOUND` |
| D-05 | Actualizar datos de designación | UUID case_file + campos actualizados | 200, designación actualizada |
| D-06 | Crear designación duplicada | UUID case_file ya con designación | 409, error `DOCUMENT_TEMPLATE_CONFLICT` |

#### Intentos de Generación

| # | Escenario | Dato | Resultado esperado |
|---|-----------|------|---------------------|
| GA-01 | Consultar intento exitoso | UUID attempt | 200, intento con estado COMPLETED |
| GA-02 | Consultar intento fallido | UUID attempt | 200, intento con estado FAILED + error_code |
| GA-03 | Consultar intento inexistente | UUID inexistente | 404 |
| GA-04 | Listar intentos de expediente | UUID case_file | 200, lista de intentos |

### Condiciones de Frontera

- UUIDs inválidos → 422 con `INVALID_UUID`
- Campos vacíos en campos requeridos → 422 con `MISSING_REQUIRED_FIELD`
- Nombres de plantilla duplicados → 409 con `TEMPLATE_NAME_EXISTS`
- Variables de plantilla vacías (array) → Permitido (plantilla sin variables)
- Contenido de borrador > 100KB → 422 con `CONTENT_TOO_LARGE`
- Concurrent requests de edición → Optimistic locking con `version`, error `CONCURRENT_MODIFICATION` si desfase
- Generación concurrente del mismo template+expediente → Constraint único o lock corto, último en completar gana
- Request ID siempre presente en todas las respuestas

### Errores Estructurados

Todos los errores HTTP siguen el estándar del incremento 001:

```json
{
  "error": {
    "code": "TEMPLATE_NOT_FOUND",
    "message": "Plantilla no encontrada con el ID proporcionado",
    "details": {},
    "timestamp": "2026-07-31T12:00:00Z",
    "request_id": "req-abc123"
  }
}
```

Códigos de error nuevos (extensión del catálogo del incremento 001):

| Código | HTTP | Descripción |
|--------|------|-------------|
| `DOCUMENT_TEMPLATE_NOT_FOUND` | 404 | Plantilla no encontrada |
| `DOCUMENT_TEMPLATE_NAME_EXISTS` | 409 | Nombre de plantilla duplicado |
| `DOCUMENT_TEMPLATE_INACTIVE` | 409 | Plantilla desactivada, no se puede usar |
| `DOCUMENT_TEMPLATE_CONFLICT` | 409 | Conflicto de versión de plantilla |
| `CASE_FILE_NOT_FOUND` | 404 | Expediente no encontrado (reutilizar de 002) |
| `DESIGNATION_DATA_NOT_FOUND` | 404 | Datos de designación no encontrados |
| `DESIGNATION_DATA_INCOMPLETE` | 422 | Datos de designación incompletos para generación |
| `CASE_FILE_TYPE_INCOMPATIBLE` | 409 | Tipo de expediente incompatible con la operación |
| `DRAFT_NOT_FOUND` | 404 | Borrador no encontrado |
| `INVALID_DRAFT_TRANSITION` | 409 | Transición de estado no válida |
| `DRAFT_ALREADY_APPROVED` | 409 | Borrador ya aprobado, no se puede re-aprobar |
| `GENERATION_IN_PROGRESS` | 409 | Generación ya en progreso para esta idempotency_key |
| `GENERATION_FAILED` | 502 | Error en la generación de contenido por Ollama |
| `OLLAMA_UNAVAILABLE` | 503 | Servicio Ollama no disponible o timeout |
| `OLLAMA_TIMEOUT` | 504 | Timeout en la llamada a Ollama |
| `CONCURRENT_MODIFICATION` | 409 | Conflicto de concurrencia (optimistic locking) |
| `VALIDATION_ERROR` | 422 | Error de validación de entrada |
| `DATABASE_ERROR` | 500 | Error interno de base de datos |
| `MISSING_REQUIRED_VARIABLES` | 422 | Faltan variables requeridas por la plantilla |
| `CONTENT_TOO_LARGE` | 422 | Contenido excede el límite de 100KB |
| `CONTEXT_BUILD_FAILED` | 500 | Error al construir el contexto de generación |
| `IDEMPOTENCY_KEY_MISMATCH` | 409 | Idempotency-Key existe pero con payload diferente |

### Restricciones No Funcionales

- Rendimiento: Generación de borrador ≤ 30 segundos (timeout Ollama configurable, default 30s)
- Concurrencia: Optimistic locking con campo `version` en borradores; error `CONCURRENT_MODIFICATION` si desfase
- Auditoría: Cada transición de estado registra timestamp, usuario y observaciones en `draft_transitions`
- Trazabilidad: Cada borrador tiene `request_id` de creación y `parent_draft_id` para regeneraciones
- Persistencia: Borradores y plantillas almacenan `context_snapshot` como JSON serializado
- Idempotencia: Header `Idempotency-Key` con constraint único; ventana de 24 horas; respuesta cacheada
- Generación fallida: No se crea borrador; se registra intento en `generation_attempts`; error estructurado; reintento idempotente
- Regeneración: Borrador anterior pasa a SUPERSEDED solo tras éxito de nueva generación
- Backward-compatible: No se modifican endpoints ni modelos existentes del incremento 002

## Requisitos Funcionales

### RF-01: Gestión de Plantillas

**RF-01.1: Crear plantilla**
- **Entrada**: `CreateTemplateRequest` con `name`, `document_type` (enum), `organ_emisor`, `normativa`, `description`, `body_template` (Markdown), `variables` (array de `{name, label, type, required, default_value}`)
- **Validaciones**: `name` unique por `document_type`, `body_template` no vacío, `document_type` válido, cada variable tiene `name` y `type`, variables usan sintaxis `{{namespace.field}}`
- **Salida**: 201 con `TemplateResponse` completa, `created_at` UTC, `version` = 1
- **Persistencia**: Tabla `templates` con JSONB para `variables`; constraint UNIQUE en `(name, document_type, version)`

**RF-01.2: Consultar plantilla por ID**
- **Entrada**: UUID de plantilla
- **Salida**: 200 con `TemplateResponse` completa
- **Errores**: 404 `DOCUMENT_TEMPLATE_NOT_FOUND`

**RF-01.3: Listar plantillas activas**
- **Entrada**: Query params opcionales: `document_type`, `search` (búsqueda por nombre), `skip`, `limit`
- **Salida**: 200 con `{items: [TemplateResponse], total: int, skip: int, limit: int}`
- **Filtros**: Solo plantillas `is_active = true` por defecto; `search` case-insensitive LIKE

**RF-01.4: Actualizar plantilla (crear nueva versión)**
- **Entrada**: UUID + campos a actualizar
- **Validaciones**: Mismas que creación para campos presentes; si `body_template` o `variables` cambian, crear nueva versión
- **Proceso**: Si el contenido (`body_template` o `variables`) cambia:
  1. Marcar versión actual como `is_active = false`
  2. Crear nueva versión con `version` = versión_actual + 1, `is_active = true`
  3. Si solo cambian metadatos (name, organ_emisor, etc.), actualizar en la versión actual
- **Salida**: 200 con `TemplateResponse` actualizada (nueva versión si aplica)
- **Errores**: 404 `DOCUMENT_TEMPLATE_NOT_FOUND`, 409 `DOCUMENT_TEMPLATE_NAME_EXISTS`

**RF-01.5: Desactivar plantilla**
- **Entrada**: UUID de plantilla
- **Efecto**: `is_active = false` en todas las versiones activas de ese nombre, `updated_at` = now
- **Salida**: 200 con `TemplateResponse` actualizada
- **Errores**: 404 `DOCUMENT_TEMPLATE_NOT_FOUND`
- **Nota**: No elimina la plantilla ni sus versiones; borradores existentes mantienen referencia

**RF-01.6: Obtener versión activa de plantilla**
- **Entrada**: `document_type` + `name` (o `template_id`)
- **Proceso**: Retorna la versión con `is_active = true` para ese nombre
- **Salida**: 200 con `TemplateResponse` de la versión activa
- **Nota**: Las versiones anteriores son inmutables y consultables pero no activas

### RF-02: Contexto de Generación

**RF-02.1: Construir contexto completo**
- **Entrada**: UUID de plantilla + UUID de expediente
- **Proceso**:
  1. Recuperar plantilla versión activa → `body_template`, `variables`
  2. Recuperar expediente → `title`, `description`, `case_type`, `status`
  3. Recuperar empleado asociado al expediente → `first_name`, `last_name`, `cuil`, `department`
  4. Si `case_type` = `designacion`: recuperar `designation_data` → `position_name`, `organizational_unit`, `start_date`, `legal_basis`, `appointing_authority`, `salary_category`, `work_schedule`, `observations`
  5. Serializar todo en `context_snapshot` (JSON) con sub-objetos: `template`, `case_file`, `employee`, `designation` (si aplica), `variables`
  6. Calcular `context_hash` = SHA-256 del `context_snapshot`
- **Salida**: `GenerationContext` serializable
- **Errores**: 404 si plantilla o expediente no existen; 422 `DESIGNATION_DATA_INCOMPLETE` si faltan datos requeridos de designación; 500 `CONTEXT_BUILD_FAILED` si falla

**RF-02.2: Validar variables**
- **Entrada**: Variables de plantilla + variables proporcionadas por el usuario
- **Proceso**: Verificar que todas las variables `required = true` estén presentes en el namespace `variables`
- **Salida**: Ok o 422 `MISSING_REQUIRED_VARIABLES` con lista de faltantes
- **Validación de sintaxis**: Verificar que todas las variables en `body_template` usen sintaxis `{{namespace.field}}` válida; detectar variables desconocidas o sintaxis inválida antes de llamar a Ollama

### RF-03: Generación de Borradores

**RF-03.1: Generar borrador**
- **Entrada**: `GenerateDraftRequest` con `template_id`, `case_file_id`, `variables` (dict) + Header `Idempotency-Key` (opcional)
- **Proceso** (flujo correcto — sin transacción abierta durante llamada HTTP):
  1. Validar datos de entrada (UUIDs, variables) → 422 si inválidos
  2. Verificar idempotencia: si `Idempotency-Key` ya procesado → retornar respuesta cacheada (200 si éxito, 503 si falla previa)
  3. Si `Idempotency-Key` existe pero con payload diferente → 409 `IDEMPOTENCY_KEY_MISMATCH`
  4. Validar plantilla existe y está activa → 404 o 409
  5. Validar expediente existe → 404
  6. Construir contexto (RF-02.1) → 500 si falla
  7. Validar variables (RF-02.2) → 422 si faltan
  8. Registrar `generation_attempt` en BD con estado `IN_PROGRESS` → liberar transacción
  9. **Llamar a Ollama** (HTTP, fuera de transacción PostgreSQL)
  10. Si Ollama responde con éxito:
      - Crear borrador con contenido generado, estado `GENERADO`
      - Registrar `context_snapshot` serializado en el borrador
      - Actualizar `generation_attempt` con estado `COMPLETED`, `completed_at`
      - Cachear respuesta para idempotencia
  11. Si Ollama falla o timeout:
      - Actualizar `generation_attempt` con estado `FAILED`, `error_code`, `error_message`
      - NO crear borrador
      - Retornar error estructurado (502 `GENERATION_FAILED` o 503 `OLLAMA_UNAVAILABLE`)
- **Salida**: 201 con `DraftResponse` completa (en caso de éxito)
- **Errores**: Ver tabla de errores arriba

**RF-03.2: Construir prompt para Ollama**
- **Entrada**: `GenerationContext` + `body_template`
- **Proceso**:
  1. Renderizar `body_template` con variables del contexto usando Jinja2-like `{{namespace.field}}`
  2. Instrucción: "Genera un documento administrativo basado en la siguiente plantilla y datos. Respetando el formato Markdown proporcionado."
  3. Concatenar plantilla renderizada + datos del expediente + datos del empleado + datos de designación (si aplica)
- **Salida**: Prompt completo para Ollama
- **Nota**: El prompt completo se almacena en `generation_attempts.prompt_content` para trazabilidad

**RF-03.3: Consultar intento de generación**
- **Entrada**: UUID de `generation_attempt`
- **Salida**: 200 con `GenerationAttemptResponse` (id, status, model, started_at, completed_at, error_code, error_message)
- **Errores**: 404 `GENERATION_ATTEMPT_NOT_FOUND`

### RF-04: Ciclo de Vida del Borrador

**RF-04.1: Avanzar estado del borrador**
- **Entrada**: UUID borrador + `action` (enum: `SEND_TO_REVIEW`, `APPROVE`, `REJECT`) + `observations` (opcional) + `expected_version` (obligatorio, para optimistic locking)
- **Proceso**:
  1. Recuperar borrador → 404 si no existe
  2. Validar `expected_version` contra versión persistida → 409 `CONCURRENT_MODIFICATION` si desfase
  3. Validar transición según máquina de estados → 409 si inválida
  4. Actualizar estado, incrementar `version`, registrar `observations`, `updated_by`, `updated_at`
  5. Crear registro en historial de transiciones
- **Salida**: 200 con `DraftResponse` actualizada
- **Transiciones válidas**:
  - `GENERADO` → `EN_REVISION` (SEND_TO_REVIEW)
  - `EN_REVISION` → `APROBADO` (APPROVE)
  - `EN_REVISION` → `RECHAZADO` (REJECT)
  - `RECHAZADO` → `EN_REVISION` (SEND_TO_REVIEW)
- **Idempotencia**: Si se intenta aprobar/rechazar un borrador que ya está en el estado destino → retornar 200 con estado actual (no error)
- **Nota**: El estado `SUPERSEDED` se asigna automáticamente durante la regeneración (RF-05), no mediante este endpoint

**RF-04.2: Historial de transiciones**
- Cada transición crea un registro en `draft_transitions` con: `draft_id`, `from_status`, `to_status`, `action`, `observations`, `performed_by`, `created_at`
- Consultable como lista ordenada por fecha para un borrador dado

### RF-05: Regeneración de Borradores

**RF-05.1: Regenerar borrador**
- **Entrada**: UUID borrador + `observations` (string con observaciones del revisor) + `expected_version` (obligatorio)
- **Proceso** (flujo correcto — sin transacción abierta durante llamada HTTP):
  1. Recuperar borrador original → 404 si no existe
  2. Validar `expected_version` contra versión persistida → 409 `CONCURRENT_MODIFICATION` si desfase
  3. Validar estado: solo se puede regenerar desde `EN_REVISION` o `RECHAZADO` → 409 si inválido
  4. Obtener plantilla versión activa (no la versión original del borrador)
  5. Obtener datos de designación actuales del expediente (no el snapshot anterior)
  6. Registrar `generation_attempt` con estado `IN_PROGRESS` → liberar transacción
  7. **Llamar a Ollama** (fuera de transacción)
  8. Si Ollama responde con éxito:
      - Crear nuevo borrador con:
        - `parent_draft_id` = UUID del borrador original
        - `context_snapshot` = nuevo snapshot (datos actuales, no del original)
        - `template_id` = versión activa de la plantilla
        - `case_file_id` = misma del original
        - `status` = `GENERADO`
        - `content` = contenido generado
        - `generation_number` = generation_number del original + 1
      - Marcar borrador original como `SUPERSEDED`
      - Registrar observaciones en historial del borrador original
      - Actualizar `generation_attempt` con estado `COMPLETED`
  9. Si Ollama falla:
      - Actualizar `generation_attempt` con estado `FAILED`
      - NO crear nuevo borrador
      - Borrador original permanece en su estado actual (no cambia a SUPERSEDED)
      - Retornar error estructurado
- **Salida**: 201 con nuevo `DraftResponse`
- **Errores**: Ver tabla de errores arriba

### RF-06: Edición Manual de Borradores

**RF-06.1: Editar contenido del borrador**
- **Entrada**: UUID borrador + `content` (nuevo contenido Markdown) + `expected_version` (obligatorio)
- **Validaciones**: Estado permite edición (EN_REVISION o RECHAZADO), contenido ≤ 100KB
- **Proceso**:
  1. Recuperar borrador → 404 si no existe
  2. Validar `expected_version` contra versión persistida → 409 `CONCURRENT_MODIFICATION` si desfase
  3. Validar estado permite edición → 409 `INVALID_DRAFT_TRANSITION` si no permite
  4. Actualizar `content`, incrementar `version`, `updated_at`
  5. Registrar en historial de transiciones (acción: `EDIT_CONTENT`)
  6. Conservar `content` original en snapshot si es la primera edición
- **Salida**: 200 con `DraftResponse` actualizada
- **Errores**: 404 `DRAFT_NOT_FOUND`, 409 `INVALID_DRAFT_TRANSITION` si estado no permite edición, 409 `CONCURRENT_MODIFICATION`, 422 `CONTENT_TOO_LARGE`
- **Nota**: Editar un borrador NO cambia su estado. Solo actualiza contenido y versión.

### RF-07: Consultas de Borradores

**RF-07.1: Consultar borrador por ID**
- **Entrada**: UUID de borrador
- **Salida**: 200 con `DraftResponse` completa (incluye `context_snapshot` serializado)
- **Errores**: 404 `DRAFT_NOT_FOUND`

**RF-07.2: Listar borradores de un expediente**
- **Entrada**: UUID expediente + query params: `status` (filtro opcional), `skip`, `limit`
- **Salida**: 200 con `{items: [DraftResponse], total: int, skip: int, limit: int}`
- **Filtros**: `status` exacto si proporcionado; ordenados por `created_at` descendente
- **Errores**: 404 `CASE_FILE_NOT_FOUND` si el expediente no existe

### RF-08: Auditoría y Trazabilidad

**RF-08.1: Registro de transiciones**
- Cada cambio de estado en borradores crea un registro completo con:
  - `draft_id`, `from_status`, `to_status`, `action`, `observations`, `performed_by`, `created_at`
- Consultable por borrador (historial completo)

**RF-08.2: Snapshot de contexto**
- Cada borrador almacena `context_snapshot` con los datos exactos usados en la generación
- Permite trazabilidad: saber exactamente qué datos se usaron para cada borrador
- Snapshot es inmutable una vez creado

**RF-08.3: Cadena de versiones**
- Regeneraciones crean cadena: `previous_draft_id` → siguiente borrador
- Permite reconstruir la historia completa de revisiones de un documento

## Requisitos No Funcionales

### RNF-01: Rendimiento

- Consultas de plantillas y borradores: ≤ 200ms p99
- Generación de borrador (Ollama): ≤ 30 segundos (configurable via `OLLAMA_TIMEOUT`)
- Listados paginados: ≤ 500ms p99 para listas de hasta 1000 registros
- Concurrent requests: Pessimistic locking para edición de borradores

### RNF-02: Persistencia

- Tablas nuevas: `templates`, `drafts`, `draft_transitions`
- Sin migraciones sobre tablas existentes (solo adicionales)
- JSONB para `variables` en plantillas y `context_snapshot` en borradores
- Índices en: `templates.document_type`, `templates.is_active`, `drafts.case_file_id`, `drafts.status`, `drafts.previous_draft_id`

### RNF-03: Seguridad

- Autenticación: Misma infraestructura del incremento 001 (request ID, logging)
- Autorización: No implementada en este incremento (asumida a nivel de infraestructura)
- No se almacenan secretos ni tokens de Ollama en la base de datos
- Variables de plantilla sanitizadas antes de inyectar en prompts

### RNF-04: Observabilidad

- Logs estructurados para cada operación CRUD
- Request ID propagado en todas las respuestas
- Health check de Ollama verificado antes de generar (pre-check)
- Métricas básicas: tiempo de generación, éxito/fallo de Ollama, borradores creados por estado

### RNF-05: Testing

- Cobertura mínima: 85% (mismo umbral que incremento 002)
- Tests unitarios para: servicios de plantilla, borrador, contexto, prompt builder, transiciones
- Tests de integración para: repositorios (templates, drafts), transiciones de estado
- Tests E2E para: flujos completos de generación → revisión → aprobación → publicación
- Tests de frontera: UUIDs inválidos, campos faltantes, contenido excesivo, concurrencia

### RNF-06: Backward Compatibility

- No se modifican modelos, endpoints ni contratos existentes del incremento 002
- Nuevas tablas adicionales sin foreign keys que rompan integridad existente
- Endpoints nuevos bajo `/api/v1/templates` y `/api/v1/drafts` (no `/api/v1/employees` ni `/api/v1/case-files`)

## Diseño de Base de Datos

### Tabla `templates`

```sql
CREATE TABLE templates (
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

CREATE INDEX idx_templates_document_type ON templates(document_type);
CREATE INDEX idx_templates_is_active ON templates(is_active);
CREATE INDEX idx_templates_name ON templates(name);
```

### Tabla `drafts`

```sql
CREATE TABLE drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id UUID NOT NULL REFERENCES templates(id),
    case_file_id UUID NOT NULL REFERENCES case_files(id),
    title VARCHAR(300) NOT NULL,
    content TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'GENERADO',
    version INTEGER NOT NULL DEFAULT 1,
    generation_number INTEGER NOT NULL DEFAULT 1,
    context_snapshot JSONB NOT NULL,
    context_hash VARCHAR(64) NOT NULL,
    variables_used JSONB DEFAULT '{}'::jsonb,
    parent_draft_id UUID REFERENCES drafts(id),
    observations TEXT,
    request_id VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_drafts_case_file_id ON drafts(case_file_id);
CREATE INDEX idx_drafts_status ON drafts(status);
CREATE INDEX idx_drafts_parent_draft_id ON drafts(parent_draft_id);
CREATE INDEX idx_drafts_template_id ON drafts(template_id);
CREATE INDEX idx_drafts_context_hash ON drafts(context_hash);
```

### Tabla `draft_transitions`

```sql
CREATE TABLE draft_transitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id UUID NOT NULL REFERENCES drafts(id),
    from_status VARCHAR(20) NOT NULL,
    to_status VARCHAR(20) NOT NULL,
    action VARCHAR(50) NOT NULL,
    observations TEXT,
    performed_by VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_draft_transitions_draft_id ON draft_transitions(draft_id);
```

### Tabla `generation_attempts`

```sql
CREATE TABLE generation_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_file_id UUID NOT NULL REFERENCES case_files(id),
    template_id UUID NOT NULL REFERENCES templates(id),
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

CREATE INDEX idx_generation_attempts_idempotency_key ON generation_attempts(idempotency_key);
CREATE INDEX idx_generation_attempts_case_file_id ON generation_attempts(case_file_id);
CREATE INDEX idx_generation_attempts_status ON generation_attempts(status);
```

### Tabla `designation_data`

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

CREATE INDEX idx_designation_data_case_file_id ON designation_data(case_file_id);
```

## Diseño de Endpoints

### Plantillas

| Método | Ruta | Descripción | Idempotencia | Concurrencia |
|--------|------|-------------|--------------|--------------|
| POST | `/api/v1/templates` | Crear plantilla | N/A | N/A |
| GET | `/api/v1/templates` | Listar plantillas activas (filtros: document_type, search) | N/A | N/A |
| GET | `/api/v1/templates/{template_id}` | Consultar plantilla por ID | N/A | N/A |
| PATCH | `/api/v1/templates/{template_id}` | Actualizar plantilla (crea nueva versión si cambia contenido) | N/A | N/A |
| POST | `/api/v1/templates/{template_id}/deactivate` | Desactivar plantilla | Idempotente | N/A |

### Datos de Designación

| Método | Ruta | Descripción | Idempotencia | Concurrencia |
|--------|------|-------------|--------------|--------------|
| POST | `/api/v1/case-files/{case_file_id}/designation` | Crear datos de designación | N/A | N/A |
| GET | `/api/v1/case-files/{case_file_id}/designation` | Consultar datos de designación | N/A | N/A |
| PUT | `/api/v1/case-files/{case_file_id}/designation` | Actualizar datos de designación | Idempotente | N/A |

### Borradores

| Método | Ruta | Descripción | Idempotencia | Concurrencia |
|--------|------|-------------|--------------|--------------|
| POST | `/api/v1/drafts/generate` | Generar borrador (template + expediente + variables) | Idempotente via `Idempotency-Key` | Generación concurrente: constraint único |
| GET | `/api/v1/case-files/{case_file_id}/drafts` | Listar borradores de un expediente | N/A | N/A |
| GET | `/api/v1/drafts/{draft_id}` | Consultar borrador por ID | N/A | N/A |
| PATCH | `/api/v1/drafts/{draft_id}/content` | Editar contenido del borrador | N/A | Optimistic locking (`expected_version`) |
| POST | `/api/v1/drafts/{draft_id}/transitions` | Avanzar estado del borrador | Idempotente (mismo estado → 200) | Optimistic locking (`expected_version`) |
| POST | `/api/v1/drafts/{draft_id}/regenerate` | Regenerar borrador con observaciones | N/A | Optimistic locking (`expected_version`) |
| GET | `/api/v1/drafts/{draft_id}/history` | Consultar historial de transiciones | N/A | N/A |

### Intentos de Generación

| Método | Ruta | Descripción | Idempotencia | Concurrencia |
|--------|------|-------------|--------------|--------------|
| GET | `/api/v1/generation-attempts/{attempt_id}` | Consultar intento de generación | N/A | N/A |
| GET | `/api/v1/case-files/{case_file_id}/generation-attempts` | Listar intentos de generación del expediente | N/A | N/A |

**Total endpoints: 15** (5 plantillas + 3 designación + 7 borradores + 2 intentos, menos 1 endpoint duplicado de borradores)

## Estructura de Modelos

### Domain Models

```python
# src/legal_ai/domain/template.py
class Template:
    id: UUID
    name: str
    document_type: DocumentType
    version: int
    organ_emisor: str | None
    normativa: str | None
    description: str | None
    body_template: str
    variables: list[TemplateVariable]
    is_active: bool
    created_at: datetime
    updated_at: datetime

# src/legal_ai/domain/draft.py
class Draft:
    id: UUID
    template_id: UUID
    case_file_id: UUID
    title: str
    content: str | None
    status: DraftStatus
    version: int  # Optimistic locking
    generation_number: int
    context_snapshot: dict
    context_hash: str
    variables_used: dict
    parent_draft_id: UUID | None
    observations: str | None
    request_id: str | None
    created_at: datetime
    updated_at: datetime

class DraftTransition:
    id: UUID
    draft_id: UUID
    from_status: DraftStatus
    to_status: DraftStatus
    action: TransitionAction
    observations: str | None
    performed_by: str | None
    created_at: datetime

# src/legal_ai/domain/generation_attempt.py
class GenerationAttempt:
    id: UUID
    case_file_id: UUID
    template_id: UUID
    idempotency_key: str | None
    model: str
    prompt_hash: str
    prompt_content: str
    status: GenerationStatus
    started_at: datetime
    completed_at: datetime | None
    error_code: str | None
    error_message: str | None
    created_at: datetime

# src/legal_ai/domain/designation_data.py
class DesignationData:
    id: UUID
    case_file_id: UUID
    position_name: str
    organizational_unit: str | None
    start_date: date | None
    legal_basis: str | None
    appointing_authority: str | None
    salary_category: str | None
    work_schedule: str | None
    observations: str | None
    created_at: datetime
    updated_at: datetime
```

### Enums

```python
# src/legal_ai/domain/enums.py (extensión)
class DocumentType(str, Enum):
    RESOLUCION = "RESOLUCION"
    INFORME = "INFORME"
    OFICIO = "OFICIO"
    SOLICITUD = "SOLICITUD"
    ACUERDO = "ACUERDO"
    OTROS = "OTROS"

class DraftStatus(str, Enum):
    GENERADO = "GENERADO"
    EN_REVISION = "EN_REVISION"
    APROBADO = "APROBADO"
    RECHAZADO = "RECHAZADO"
    SUPERSEDED = "SUPERSEDED"

class TransitionAction(str, Enum):
    SEND_TO_REVIEW = "SEND_TO_REVIEW"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    EDIT_CONTENT = "EDIT_CONTENT"

class GenerationStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
```

### Request/Response Schemas

```python
# src/legal_ai/api/schemas/template.py
class CreateTemplateRequest(BaseModel):
    name: str = Field(..., max_length=200)
    document_type: DocumentType
    organ_emisor: str | None = Field(None, max_length=200)
    normativa: str | None = None
    description: str | None = None
    body_template: str
    variables: list[TemplateVariableSchema] = []

class TemplateVariableSchema(BaseModel):
    name: str  # Namespace: employee.*, case_file.*, designation.*, variables.*
    label: str
    type: str  # "text", "date", "number", "select"
    required: bool = False
    default_value: str | None = None

class TemplateResponse(BaseModel):
    id: UUID
    name: str
    document_type: DocumentType
    version: int
    organ_emisor: str | None
    normativa: str | None
    description: str | None
    body_template: str
    variables: list[TemplateVariableSchema]
    is_active: bool
    created_at: datetime
    updated_at: datetime

# src/legal_ai/api/schemas/draft.py
class GenerateDraftRequest(BaseModel):
    template_id: UUID
    case_file_id: UUID
    variables: dict[str, Any] = {}
    # Idempotency-Key se envía como header HTTP

class TransitionDraftRequest(BaseModel):
    action: TransitionAction
    observations: str | None = None
    expected_version: int  # Para optimistic locking

class RegenerateDraftRequest(BaseModel):
    observations: str
    expected_version: int  # Para optimistic locking

class EditDraftContentRequest(BaseModel):
    content: str = Field(..., max_length=100000)
    expected_version: int  # Para optimistic locking

class DraftResponse(BaseModel):
    id: UUID
    template_id: UUID
    case_file_id: UUID
    title: str
    content: str | None
    status: DraftStatus
    version: int
    generation_number: int
    context_snapshot: dict
    context_hash: str
    variables_used: dict
    parent_draft_id: UUID | None
    observations: str | None
    request_id: str | None
    created_at: datetime
    updated_at: datetime

class DraftTransitionResponse(BaseModel):
    id: UUID
    draft_id: UUID
    from_status: DraftStatus
    to_status: DraftStatus
    action: TransitionAction
    observations: str | None
    performed_by: str | None
    created_at: datetime

class GenerationAttemptResponse(BaseModel):
    id: UUID
    case_file_id: UUID
    template_id: UUID
    idempotency_key: str | None
    model: str
    status: GenerationStatus
    started_at: datetime
    completed_at: datetime | None
    error_code: str | None
    error_message: str | None
    created_at: datetime

class DesignationDataResponse(BaseModel):
    id: UUID
    case_file_id: UUID
    position_name: str
    organizational_unit: str | None
    start_date: date | None
    legal_basis: str | None
    appointing_authority: str | None
    salary_category: str | None
    work_schedule: str | None
    observations: str | None
    created_at: datetime
    updated_at: datetime

class CreateDesignationDataRequest(BaseModel):
    position_name: str = Field(..., max_length=200)
    organizational_unit: str | None = Field(None, max_length=200)
    start_date: date | None = None
    legal_basis: str | None = None
    appointing_authority: str | None = Field(None, max_length=200)
    salary_category: str | None = Field(None, max_length=100)
    work_schedule: str | None = Field(None, max_length=100)
    observations: str | None = None
```

## Estructura de Directorios

```
apps/api/src/legal_ai/
├── domain/
│   ├── template.py          # Template model
│   ├── draft.py             # Draft model + DraftTransition model
│   ├── generation_attempt.py # GenerationAttempt model
│   ├── designation_data.py  # DesignationData model
│   └── enums.py             # DocumentType, DraftStatus, TransitionAction, GenerationStatus
├── application/
│   ├── template_service.py  # CRUD plantillas + versionado
│   ├── draft_service.py     # CRUD borradores + ciclo de vida
│   ├── designation_service.py # CRUD datos de designación
│   ├── generation_context.py # Construcción de contexto + validación
│   └── prompt_builder.py    # Renderizado Jinja2 + prompt para Ollama
├── adapters/
│   └── database/
│   ├── template_repository.py
│   │   ├── draft_repository.py
│   │   ├── designation_repository.py
│   │   ├── generation_attempt_repository.py
│   │   └── unit_of_work.py  # Extensión para templates/drafts/designation
├── api/
│   ├── routes/
│   │   ├── templates.py     # Endpoints plantillas
│   │   ├── drafts.py        # Endpoints borradores
│   │   ├── designation.py   # Endpoints datos de designación
│   │   └── generation.py    # Endpoints intentos de generación
│   └── schemas/
│       ├── template.py      # Request/Response plantillas
│       ├── draft.py         # Request/Response borradores
│       ├── designation.py   # Request/Response datos de designación
│       └── generation.py    # Request/Response intentos de generación
└── migrations/
    └── versions/
        └── 003_templates_drafts_and_generation.py  # Alembic migration
```

## Escenarios de Prueba Adicionales

### Tests Unitarios

- `test_template_service.py`: Crear, consultar, listar, actualizar (nueva versión), desactivar plantilla; nombre duplicado; plantilla inactiva; versionado inmutable
- `test_draft_service.py`: Generar borrador, avanzar estados, regenerar, editar contenido, consultar, listar por expediente; transiciones inválidas; borrador inexistente; optimistic locking
- `test_generation_context.py`: Construcción de contexto completo; plantilla inexistente; expediente inexistente; variables faltantes; variables adicionales; datos de designación
- `test_prompt_builder.py`: Renderizado Jinja2 de plantilla con variables; namespaces employee/case_file/designation/variables; prompt completo para Ollama; manejo de variables faltantes; detección de sintaxis inválida
- `test_generation_attempt.py`: Crear intento, actualizar estado, idempotencia via key, ventana temporal
- `test_designation_service.py`: CRUD datos de designación; validación case_type=designacion; campos obligatorios

### Tests de Integración

- `test_template_repository.py`: CRUD completo en base de datos; unique constraint (name, document_type, version); filtrado por document_type; versionado
- `test_draft_repository.py`: CRUD completo; filtros por status; cadena de parent_draft_id; historial de transiciones; optimistic locking
- `test_generation_attempt_repository.py`: CRUD completo; constraint unique en idempotency_key; ventana temporal
- `test_designation_repository.py`: CRUD completo; unique constraint en case_file_id

### Tests de Transiciones

- Todas las transiciones válidas (4)
- Todas las transiciones inválidas (transiciones no permitidas)
- Borrador inexistente
- Concurrent transitions (mismo borrador, transiciones simultáneas)
- Transición idempotente (mismo estado destino → 200 sin cambio)

## Plan de Implementación (Tareas)

### Fase 1: Domain Models + Enums
1. Crear `DocumentType`, `DraftStatus`, `TransitionAction`, `GenerationStatus` enums en `domain/enums.py`
2. Crear `TemplateVariable` y `Template` models en `domain/template.py`
3. Crear `Draft` y `DraftTransition` models en `domain/draft.py`
4. Crear `GenerationAttempt` model en `domain/generation_attempt.py`
5. Crear `DesignationData` model en `domain/designation_data.py`

### Fase 2: Database Migrations
6. Crear migración Alembic `003_templates_drafts_and_generation.py`
7. Tabla `templates` con versionado, JSONB y constraint UNIQUE
8. Tabla `drafts` con version, generation_number, context_hash
9. Tabla `draft_transitions` con foreign keys e índices
10. Tabla `generation_attempts` con constraint UNIQUE en idempotency_key
11. Tabla `designation_data` con constraint UNIQUE en case_file_id

### Fase 3: Repositories
12. Crear `TemplateRepository` con CRUD completo + versionado
13. Crear `DraftRepository` con CRUD, filtros, historial, optimistic locking
14. Crear `GenerationAttemptRepository` con CRUD, idempotencia, ventana temporal
15. Crear `DesignationRepository` con CRUD completo
16. Extender `UnitOfWork` para incluir templates, drafts, generation_attempts, designation_data

### Fase 4: Schemas (Request/Response)
17. Crear schemas para plantillas: `CreateTemplateRequest`, `TemplateVariableSchema`, `TemplateResponse`
18. Crear schemas para borradores: `GenerateDraftRequest`, `DraftResponse`, `TransitionDraftRequest`, `RegenerateDraftRequest`, `EditDraftContentRequest`, `DraftTransitionResponse`
19. Crear schemas para generación: `GenerationAttemptResponse`
20. Crear schemas para designación: `CreateDesignationDataRequest`, `DesignationDataResponse`

### Fase 5: Application Services
21. Crear `TemplateService` con CRUD plantillas + versionado
22. Crear `GenerationContext` con construcción de contexto + validación de variables Jinja2
23. Crear `PromptBuilder` con renderizado Jinja2 y namespaces
24. Crear `DraftService` con generación (flujo Ollama separado), ciclo de vida, regeneración, edición
25. Crear `DesignationService` con CRUD datos de designación

### Fase 6: API Routes
26. Crear `templates.py` con endpoints POST, GET, GET/{id}, PATCH, POST/{id}/deactivate
27. Crear `drafts.py` con endpoints POST/generate (con Idempotency-Key), GET/{id}, PATCH/{id}/content, POST/{id}/transitions, POST/{id}/regenerate, GET/{id}/history
28. Crear `designation.py` con endpoints POST, GET, PUT para datos de designación
29. Crear `generation.py` con endpoints GET/{attempt_id}, GET por case_file

### Fase 7: Tests Unitarios
30. Tests `test_template_service.py`
31. Tests `test_draft_service.py`
32. Tests `test_generation_context.py`
33. Tests `test_prompt_builder.py`
34. Tests `test_generation_attempt.py`
35. Tests `test_designation_service.py`

### Fase 8: Tests de Integración
36. Tests `test_template_repository.py`
37. Tests `test_draft_repository.py`
38. Tests `test_generation_attempt_repository.py`
39. Tests `test_designation_repository.py`
40. Tests de transiciones de estado

### Fase 9: Validación
41. Ruff check + format
42. Mypy
43. Cobertura >= 85%
44. Docker build + up + smoke tests

### Fase 10: Documentación
45. Actualizar tasks.md con progreso
46. Verificar checklist de calidad

## Decisiones de Diseño

### D-01: Snapshot inmutable del contexto
Cada borrador almacena `context_snapshot` con los datos exactos usados al momento de la generación. Esto garantiza trazabilidad: siempre se puede saber qué datos produjeron un borrador específico, incluso si los datos del expediente o empleado cambian después. El `context_hash` (SHA-256) permite verificar integridad.

### D-02: Generación fallida sin creación de borrador
Si Ollama no está disponible o falla, NO se crea un borrador. Se registra el intento fallido en `generation_attempts` con estado `FAILED`. Esto evita entidades incompletas y mantiene la integridad del dominio. El usuario puede reintentar con la misma `Idempotency-Key`.

### D-03: Optimistic locking para borradores
Se utiliza optimistic locking con campo `version` en borradores. Cada operación de escritura (edición, transición, regeneración) requiere `expected_version`. Si hay desfase → 409 `CONCURRENT_MODIFICATION`. Esto es más ligero que pessimistic locking y no mantiene locks durante llamadas HTTP a Ollama.

### D-04: Regeneración crea nuevo borrador
La regeneración no modifica el borrador original; crea uno nuevo con `parent_draft_id` apuntando al original. El borrador original pasa a `SUPERSEDED` solo después de que la nueva generación termine con éxito. Si Ollama falla, el original permanece en su estado actual. `generation_number` permite ordenar versiones.

### D-05: Idempotencia via Idempotency-Key header
El endpoint de generación acepta header `Idempotency-Key`. La clave se almacena en `generation_attempts` con constraint UNIQUE. Comportamiento:
- Misma key + mismo payload → respuesta cacheada (200 si éxito, 503 si falla previa)
- Misma key + payload diferente → 409 `IDEMPOTENCY_KEY_MISMATCH`
- Generación en progreso → 409 `GENERATION_IN_PROGRESS`
- Generación completada → retornar resultado cacheado
- Generación fallida → permitir reintento (eliminar registro anterior)
- Ventana temporal: 24 horas

### D-06: Variables Jinja2-like
Las variables de plantilla usan sintaxis `{{namespace.field}}` con namespaces: `employee`, `case_file`, `designation`, `variables`. No se permiten expresiones arbitrarias ni ejecución de código. Solo interpolación simple de valores. Ejemplo: `{{employee.first_name}}`, `{{designation.position_name}}`.

### D-07: Versionado inmutable de plantillas
Cada modificación de `body_template` o `variables` crea una nueva versión. Constraint UNIQUE en `(name, document_type, version)`. Solo una versión activa por nombre. Las versiones anteriores son inmutables y consultables pero no activas. No se permite DELETE físico.

### D-08: Datos de designación en tabla separada
Los datos de designación se almacenan en `designation_data` vinculada a `case_files` por `case_file_id` (UNIQUE). Solo aplica cuando `case_type` = `designacion`. El `context_snapshot` incluye una copia serializada de estos datos al momento de la generación.

### D-09: Transacción separada de llamada HTTP
El flujo de generación/regeneración sigue: validar → registrar attempt → liberar transacción → llamar Ollama → persistir resultado en nueva transacción. Nunca se mantiene una transacción PostgreSQL abierta durante la llamada HTTP a Ollama.

### D-10: Prompt completo para trazabilidad
El prompt completo se almacena en `generation_attempts.prompt_content` para trazabilidad total. Esta es una decisión consciente que prioriza la auditoría sobre el almacenamiento. trade-off con Principio I documentado en las Clarifications.

## Alcance Excluido

Las siguientes capacidades están **excluidas explícitamente** de este
incremento y no deben generar código ni tareas:

- Publicación oficial de documentos
- Firma digital
- Exportación a PDF
- Exportación a DOCX
- Autenticación y login
- Roles y permisos
- OCR
- RAG (Retrieval-Augmented Generation)
- Embeddings y columnas vectoriales
- Búsqueda vectorial
- Redis
- Colas y workers
- Kubernetes
- Terraform
- Helm
- Frontend

## Checklist de Calidad

Ver `checklists/requirements.md` para la validación completa.

## Criterios de Aceptación Final

- [ ] Todos los requisitos funcionales implementados y verificados
- [ ] Todos los tests pasan (unitarios, integración, E2E)
- [ ] Cobertura >= 85%
- [ ] Ruff check + format OK
- [ ] Mypy OK (0 errores)
- [ ] Docker build + up OK
- [ ] Smoke tests OK (endpoints responden correctamente)
- [ ] Backward compatible (no se rompen endpoints existentes)
- [ ] Auditoría completa (transiciones registradas)
- [ ] Context snapshot inmutable
- [ ] Idempotencia en generación
- [ ] Errores estructurados con códigos definidos
