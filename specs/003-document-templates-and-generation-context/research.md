# Investigación Técnica: Plantillas de Documentos y Contexto de Generación

**Feature**: `003-document-templates-and-generation-context`
**Fecha**: 2026-07-31
**Estado**: Completo

## Decisiones de Rendering y Seguridad

### Jinja2 con SandboxedEnvironment (Rendering Seguro)

**Decisión**: Utilizar un `SandboxedEnvironment` de Jinja2 para el renderizado de plantillas
con interpolación de variables restringida a los namespaces definidos
(`employee`, `case_file`, `designation`, `variables`).

**Justificación**: Jinja2 es el estándar para renderizado de plantillas en Python.
El `SandboxedEnvironment` impide la ejecución arbitraria de código dentro de
las plantillas, proporcionando aislamiento seguro. Las plantillas son definidas
por usuarios y deben tratarse como entrada no confiable. Se configuran
filtros y tests de seguridad explícitos para evitar acceso a atributos
privados o métodos peligrosos.

**Alternativas consideradas**:
- Substitución con regex: Rechazada por frágil, sin manejo de errores para
  variables faltantes, vulnerable a inyección si los patrones no son
  estrictos.
- `string.Template` de stdlib: Rechazada por falta de soporte de namespaces,
  sin manejo de tipos, sin filtros de seguridad.
- Parser personalizado: Rechazada por complejidad injustificada, reinventar
  rueda, alto riesgo de bugs, sin ecosistema de pruebas.

**Seguridad adicional**:
- Deshabilitar acceso a `._` (atributos privados) en el entorno sandboxed.
- Deshabilitar llamadas a métodos arbitrarios.
- Validar que el `body_template` renderizado no exceda 100KB.
- Loggear intentos de acceso a variables fuera de namespaces permitidos.

### Sintaxis de Variables en Plantillas

**Decisión**: Utilizar sintaxis Jinja2-like `{{namespace.field}}` con cuatro
namespaces: `employee`, `case_file`, `designation`, `variables`.

**Justificación**: Sintaxis familiar para desarrolladores Python, ampliamente
documentada, bien soportada por el ecosistema Jinja2. Los namespaces
proporcionan separación clara entre dominios de datos y evitan colisiones
de nombres. Ejemplo: `{{employee.first_name}}`, `{{case_file.title}}`,
`{{designation.position_name}}`, `{{variables.fecha_resolucion}}`.

**Alternativas consideradas**:
- Sintaxis de llave simple `{field}`: Rechazada por ambigüedad con JSON,
  colisiones con otras sintaxis de template.
- Prefijo `@field`: Rechazada por no ser estándar, requiere documentación
  adicional, menor familiaridad.
- Sintaxis tipo `${variable}`: Rechazada por asociación con shell scripting,
  menos clara para el dominio legal.

## Decisiones de Integridad y Persistencia

### SHA-256 para Hash de Contexto

**Decisión**: Utilizar `hashlib.sha256` de la stdlib de Python para calcular
el hash del `context_snapshot`.

**Justificación**: Estándar de la industria, sin dependencias externas,
determinístico, ampliamente understood y verificable. El hash se almacena
en `context_hash` (VARCHAR(64)) y permite verificar que el snapshot de
contexto no ha sido alterado después de la creación del borrador. Se
serializa el JSON con `json.dumps(..., sort_keys=True, separators=(',', ':'))`
para garantizar determinismo.

**Alternativas consideradas**:
- MD5: Rechazada por debilidad criptográfica, no recomendada para
  integridad de datos, susceptible a colisiones.
- Blake3: Considerada pero no incluida en stdlib de Python, requiere
  dependencia externa, sin beneficio significativo para este caso de uso.
- CRC32: Rechazada por no ser hash criptográfico, alta probabilidad
  de colisiones.

### Inmutabilidad del Context Snapshot

**Decisión**: El `context_snapshot` se almacena como JSONB en la tabla
`drafts` y **nunca se actualiza** después de la creación del borrador.
El `context_hash` (SHA-256) se calcula una vez y se almacena junto
al snapshot.

**Justificación**: Los snapshots inmutables garantizan reproducibilidad
y auditabilidad. Cada borrador captura exactamente los datos que se
usaron en la generación, permitiendo trazabilidad completa. El hash
SHA-256 permite verificar que el snapshot no ha sido modificado
posteriormente, protegiendo contra manipulación accidental o deliberada.

**Alternativas consideradas**:
- Snapshot mutable: Rechazada por perder trazabilidad, imposible
  reconstruir datos exactos de generación.
- Snapshot con versionado: Rechazada por complejidad innecesaria,
  el borrador ya tiene su propio campo `version`.
- Solo hash sin contenido: Rechazada por el usuario eligió almacenamiento
  completo para máxima trazabilidad.

### Almacenamiento Completo del Prompt

**Decisión**: Almacenar el prompt completo en `generation_attempts.prompt_content`
(columna TEXT). El hash SHA-256 se almacena en `prompt_hash` para verificación
de integridad.

**Justificación**: El usuario eligió explícitamente el almacenamiento completo
del prompt para máxima trazabilidad. Esto permite inspeccionar exactamente
qué se envió a Ollama en cada intento de generación. El trade-off con el
Principio I (almacenamiento mínimo) está documentado y aceptado por decisión
explícita del usuario. El hash permite detectar corrupción sin necesidad
de comparar textos completos.

**Alternativas consideradas**:
- Solo hash del prompt: Rechazada por decisión explícita del usuario
  de almacenamiento completo.
- Hash + preview (primeros N caracteres): Rechazada por decisión
  explícita del usuario de almacenamiento completo.

## Decisiones de Concurrencia

### Optimistic Locking con Version Check

**Decisión**: Actualización condicional con verificación de versión:
`UPDATE ... SET version = version + 1, ... WHERE id = :id AND version = :expected_version`.
Si 0 filas afectadas, elevar error `CONCURRENT_MODIFICATION`.

**Justificación**: Patrón estándar para aplicaciones web con concurrencia
moderada. No mantiene locks de base de datos durante llamadas HTTP.
Compatible con conexiones asíncronas y pools de conexiones. Ya utilizado
en el incremento 002 para `case_files`, proporcionando consistencia
en el patrón de concurrencia del proyecto.

**Alternativas consideradas**:
- Pessimistic locking (`SELECT FOR UPDATE`): Rechazada por mantener
  locks durante llamadas HTTP, riesgo de deadlocks, agotamiento de
  conexiones del pool.
- Advisory locks de PostgreSQL: Rechazadas por complejidad adicional,
 requiere coordinación explícita, no escalable horizontalmente.
- ETags / If-Match a nivel HTTP: Mismo concepto que optimistic locking
  pero a nivel HTTP, innecesario cuando ya se tiene el patrón a nivel
  de base de datos.

**Patrón de implementación**:
```sql
UPDATE drafts
SET status = :new_status, version = version + 1, updated_at = now()
WHERE id = :draft_id AND version = :expected_version;
-- Si rowcount = 0 → CONCURRENT_MODIFICATION
```

### Idempotencia con Constraint UNIQUE

**Decisión**: Header HTTP `Idempotency-Key` almacenado en
`generation_attempts.idempotency_key` con constraint UNIQUE. Ventana
de 24 horas a nivel de aplicación.

**Justificación**: Patrón HTTP estándar de idempotencia. El constraint
UNIQUE previene condiciones de carrera a nivel de base de datos.
La limpieza de claves expiradas se realiza por aplicación con una
ventana de 24 horas. Permite reintentos seguros de generación sin
crear borradores duplicados.

**Alternativas consideradas**:
- Redis-based: Rechazada por no estar en el alcance del proyecto
  (sin Redis en el stack actual).
- Database-only sin UNIQUE: Rechazada por condiciones de carrera
  posibles entre dos requests concurrentes con la misma key.
- Campo en request body: Rechazada por no ser el estándar HTTP,
  los headers son el mecanismo estándar para idempotencia.

**Flujo de verificación**:
1. Si `Idempotency-Key` no presente → procesar normalmente.
2. Si la key existe con payload idéntico → retornar respuesta cacheada.
3. Si la key existe con payload diferente → 409 `IDEMPOTENCY_KEY_MISMATCH`.
4. Si la key no existe → insertar con constraint UNIQUE, procesar.

## Decisiones de Integración con Ollama

### Flujo de Dos Fases (Transacción Separada de HTTP)

**Decisión**: Transacción de dos fases para generación: (1) Validar +
registrar intento en transacción corta, (2) Llamar a Ollama fuera de
transacción, (3) Persistir resultado en nueva transacción.

**Justificación**: Nunca mantener una transacción de PostgreSQL abierta
durante una llamada HTTP a Ollama. Esto previene transacciones de
larga duración y agotamiento del pool de conexiones. Si Ollama tarda
30 segundos, la conexión de BD no queda bloqueada durante ese tiempo.
El intento se registra como `IN_PROGRESS` antes de la llamada, y se
actualiza a `COMPLETED` o `FAILED` después.

**Alternativas consideradas**:
- Transacción única: Rechazada por mantener conexión de BD durante
  llamada HTTP externa, riesgo de agotamiento del pool, transacciones
  de larga duración, poor performance bajo carga.
- Cola async (Redis/Celery): Rechazada por no estar en alcance
  del proyecto, sin infraestructura de colas disponible.

**Flujo detallado**:
```
1. BEGIN TRANSACTION
2. Validar plantilla activa, expediente existe
3. Construir contexto, validar variables
4. INSERT generation_attempt (status=IN_PROGRESS)
5. COMMIT
--- fuera de transacción ---
6. POST http://ollama/api/generate (con timeout 30s)
--- nueva transacción ---
7. BEGIN TRANSACTION
8a. Si éxito: CREATE draft (status=GENERADO) + UPDATE attempt (COMPLETED)
8b. Si fallo: UPDATE attempt (FAILED, error_code, error_message)
9. COMMIT
```

## Decisiones de Ciclo de Vida

### Máquina de Estados del Borrador (5 Estados)

**Decisión**: 5 estados posibles: `GENERADO`, `EN_REVISION`, `APROBADO`,
`RECHAZADO`, `SUPERSEDED`. 4 transiciones válidas documentadas.
El estado `SUPERSEDED` es terminal y se asigna automáticamente cuando
una regeneración crea un nuevo borrador con éxito.

**Justificación**: Cubre el ciclo de vida completo sin complejidad innecesaria.
El estado `PUBLICADO` queda excluido de este incremento para mantener
el alcance acotado. La publicación oficial se implementará en un
incremento posterior.

**Transiciones válidas**:
```
GENERADO → EN_REVISION (enviar a revisión)
EN_REVISION → APROBADO (revisor aprueba)
EN_REVISION → RECHAZADO (revisor rechaza)
RECHAZADO → EN_REVISION (re-apertura tras edición/regeneración)
Cualquier estado → SUPERSEDED (asignado automáticamente tras regeneración exitosa)
```

**Restricciones**:
- `SUPERSEDED` solo se asigna cuando la regeneración exitosa crea un
  nuevo borrador.
- Si la regeneración falla, el borrador original permanece en su estado
  actual (no cambia a SUPERSEDED).
- `APROBADO` es semi-terminal: no admite transiciones excepto la
  asignación automática a SUPERSEDED por regeneración.
- Las transiciones idempotentes (intentar avanzar al mismo estado
  destino) retornan 200 sin error.

**Alternativas consideradas**:
- Estado `PUBLICADO`: Excluido deliberadamente del alcance, se
  implementará en incremento futuro.
- Estados más granulares (ej. `EN_EDICION`, `PENDIENTE_APROBACION`):
  Rechazados por complejidad innecesaria, los estados actuales
  cubren todos los flujos requeridos.
- Menos estados (sin `RECHAZADO`): Rechazado por necesidad de
  distinguir entre borrador en revisión y rechazado con observaciones.

### Extensión del Catálogo de Errores (16 Nuevos Códigos)

**Decisión**: Extender el catálogo de errores del incremento 001 con
16 nuevos códigos. Mantener la misma convención de mapeo HTTP y
estructura de respuesta de error.

**Justificación**: Backward-compatible con el incremento 001. Consistente
con el patrón existente de errores estructurados. Los nuevos códigos
cubren todos los escenarios de error del incremento 003.

**Nuevos códigos de error**:

| Código | HTTP | Descripción |
|--------|------|-------------|
| `DOCUMENT_TEMPLATE_NOT_FOUND` | 404 | Plantilla no encontrada |
| `DOCUMENT_TEMPLATE_NAME_EXISTS` | 409 | Nombre de plantilla duplicado |
| `DOCUMENT_TEMPLATE_INACTIVE` | 409 | Plantilla desactivada |
| `DOCUMENT_TEMPLATE_CONFLICT` | 409 | Conflicto de versión de plantilla |
| `DESIGNATION_DATA_NOT_FOUND` | 404 | Datos de designación no encontrados |
| `DESIGNATION_DATA_INCOMPLETE` | 422 | Datos de designación incompletos |
| `CASE_FILE_TYPE_INCOMPATIBLE` | 409 | Tipo de expediente incompatible |
| `DRAFT_NOT_FOUND` | 404 | Borrador no encontrado |
| `INVALID_DRAFT_TRANSITION` | 409 | Transición de estado no válida |
| `DRAFT_ALREADY_APPROVED` | 409 | Borrador ya aprobado |
| `GENERATION_IN_PROGRESS` | 409 | Generación en progreso |
| `GENERATION_FAILED` | 502 | Error en generación por Ollama |
| `OLLAMA_UNAVAILABLE` | 503 | Servicio Ollama no disponible |
| `OLLAMA_TIMEOUT` | 504 | Timeout en llamada a Ollama |
| `CONCURRENT_MODIFICATION` | 409 | Conflicto de concurrencia |
| `CONTENT_TOO_LARGE` | 422 | Contenido excede 100KB |

**Nota**: `CASE_FILE_NOT_FOUND` y `DOCUMENT_TEMPLATE_NOT_FOUND` se
reutilizan del catálogo existente cuando aplica. Los códigos nuevos
son adicionales, no reemplazan los existentes.

**Alternativas consideradas**:
- Formato de error diferente: Rechazado por inconsistencia con el
  incremento 001, rompería backward-compatibility.
- Códigos numéricos: Rechazados por menor legibilidad, los códigos
  textuales son el estándar del proyecto.

## Decisiones de Diseño de Datos

### Versionado Inmutable de Plantillas

**Decisión**: Cada modificación de `body_template` o `variables` crea
una nueva versión. Las versiones anteriores son inmutables. Solo una
versión por `name` tiene `is_active = true`.

**Justificación**: Garantiza que los borradores existentes mantengan
referencia a la versión exacta de la plantilla usada en su generación.
El versionado por contenido evita crear versiones innecesarias cuando
solo cambian metadatos.

**Reglas**:
- Cambio en `body_template` o `variables` → nueva versión.
- Cambio solo en metadatos (`name`, `organ_emisor`, etc.) → actualizar
  versión actual.
- Constraint UNIQUE: `(name, document_type, version)`.
- Consulta por defecto retorna versión activa (`is_active = true`).

### Snapshot del Contexto como JSONB

**Decisión**: El `context_snapshot` se serializa como JSONB y almacena
sub-objetos: `template`, `case_file`, `employee`, `designation` (si aplica),
`variables`.

**Justificación**: JSONB permite consultas eficientes sobre datos
anidados sin necesidad de tablas adicionales. El snapshot captura
exactamente los datos usados en la generación, incluyendo la versión
de la plantilla y los datos del expediente en el momento de la
generación. Esto es esencial para trazabilidad y auditoría.

**Estructura del snapshot**:
```json
{
  "template": {
    "id": "uuid",
    "name": "...",
    "document_type": "...",
    "version": 1,
    "body_template": "..."
  },
  "case_file": {
    "id": "uuid",
    "title": "...",
    "description": "...",
    "case_type": "...",
    "status": "..."
  },
  "employee": {
    "id": "uuid",
    "first_name": "...",
    "last_name": "...",
    "cuil": "...",
    "department": "..."
  },
  "designation": {
    "position_name": "...",
    "organizational_unit": "...",
    "start_date": "...",
    "legal_basis": "...",
    "appointing_authority": "...",
    "salary_category": "...",
    "work_schedule": "...",
    "observations": "..."
  },
  "variables": {
    "fecha_resolucion": "...",
    "numero_expediente": "..."
  }
}
```

## Riesgos Identificados

| Riesgo | Mitigación |
|---|---|
| Jinja2 permite ejecución arbitraria de código | SandboxedEnvironment + filtros de seguridad explícitos |
| Variables faltantes en plantilla silenciosas | Validación estricta antes de renderizar, error `MISSING_REQUIRED_VARIABLES` |
| Prompt injection a través de variables | Sanitización de variables antes de inyectar en prompt, logging de intentos sospechosos |
| Transacciones de larga duración durante llamada Ollama | Patrón de dos fases: transacción corta + HTTP fuera de transacción |
| Condiciones de carrera en idempotencia | Constraint UNIQUE en `idempotency_key`, verificación antes de insertar |
| Concurrencia en edición de borradores | Optimistic locking con campo `version`, error `CONCURRENT_MODIFICATION` |
| Snapshot de contexto corrupto | SHA-256 hash para verificación de integridad |
| Ollama no disponible durante generación | Timeout configurable, intento registrado como FAILED, error estructurado |
| Regeneración fallida pierde borrador original | Borrador original permanece en su estado actual hasta éxito confirmado |
| Templates con variables maliciosas | SandboxedEnvironment + validación de sintaxis `{{namespace.field}}` |
| Creación concurrente del mismo borrador | Constraint único o lock corto, último en completar gana |
| Errores de rendering en plantillas | Manejo de excepciones Jinja2, error `CONTEXT_BUILD_FAILED` |
| Datos de designación incompletos | Validación antes de generar, error `DESIGNATION_DATA_INCOMPLETE` |
| Accumulación de intentos de generación | Limpieza de intentos expirados (>24h) en ventana de idempotencia |
| Diferencias de serialización JSON (orden de keys) | `json.dumps(sort_keys=True)` para determinismo en hash |
| Memory pressure por prompts grandes | Validación de tamaño máximo del prompt, límite en `prompt_content` |
