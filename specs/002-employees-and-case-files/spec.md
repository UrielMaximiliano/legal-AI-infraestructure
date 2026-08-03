# Especificación: Gestión Base de Empleados y Expedientes Administrativos

**ID de Especificación**: `002-employees-and-case-files`
**Creada**: 2026-07-31
**Estado**: Borrador
**Entrada**: Descripción del usuario: "Gestión base de empleados y expedientes administrativos"

## Resumen Ejecutivo

Este incremento construye el núcleo transaccional mínimo del Gestor de
Expedientes IMI. Permite registrar empleados y gestionar expedientes
administrativos asociados a ellos, incluyendo estados, transiciones controladas
e historial auditable. La plataforma ya dispone de FastAPI, PostgreSQL 16,
pgvector, SQLAlchemy async, Alembic, Docker Compose, health checks,
integración con Ollama, request ID, logging, pruebas y cobertura del
incremento 001.

**Declaración de alcance**: Este incremento gestiona empleados y expedientes
administrativos. No procesa ni genera contenido jurídico. La revisión humana
obligatoria (Principio II de la constitución) aplicará a capacidades jurídicas
futuras. No se cargan datos personales reales. No se utilizan embeddings ni
columnas vectoriales.

## Declaración del Problema

### Estado Actual

La plataforma dispone de la base técnica verificada (incremento 001): API
FastAPI, PostgreSQL 16 con pgvector, migraciones Alembic, health checks,
integración con Ollama, request ID, logging y pruebas con cobertura >= 85%.
Sin embargo, no existe ninguna funcionalidad de negocio. No hay entidades de
dominio, ni endpoints transaccionales, ni lógica de estados, ni historial
auditable.

### Estado Deseado

El personal de Legal y Técnica del IMI puede registrar empleados con datos
administrativos básicos, crear y consultar expedientes asociados a esos
empleados, ejecutar transiciones de estado controladas, y consultar el
historial completo de cambios de cada expediente. Todo con trazabilidad
mediante request ID, timestamps UTC y errores estructurados.

### Impacto del Negocio

Sin este incremento, no hay forma de gestionar la información básica del
personal ni el ciclo de vida de los expedientes administrativos. Este
incremento establece la base sobre la cual se construirán capacidades
jurídicas futuras (generación de documentos, RAG, embeddings).

## Escenarios de Usuario y Pruebas

### Historia de Usuario Principal

Como personal de Legal y Técnica del IMI,
quiero registrar empleados y gestionar expedientes administrativos con estados
controlados e historial auditable,
para mantener un registro ordenado y trazable de la gestión administrativa.

### Flujo de Estados del Expediente

El expediente administra una máquina de estados con las siguientes transiciones
permitidas:

```
draft -> under_review
under_review -> in_process
under_review -> draft
in_process -> submitted
in_process -> under_review
submitted -> approved
submitted -> rejected
rejected -> under_review
approved -> archived
rejected -> archived
```

**Reglas de la máquina de estados:**

- `archived` es un estado terminal; no admite transiciones posteriores.
- `approved` no puede volver a `draft`.
- No se permiten saltos arbitrarios entre estados.
- Toda transición exitosa genera un registro en el historial.
- Una transición inválida retorna error de dominio sin modificar el estado.
- No se cierra automáticamente un expediente sin una transición explícita.
- El historial se registra únicamente cuando la transición se ejecuta
  correctamente.

**Regla de `closed_at`:**

- `closed_at` inicia en null.
- Solo se asigna cuando `to_status` = `archived`.
- El valor debe ser la fecha y hora UTC de la transición.
- `approved` y `rejected` no cierran técnicamente el expediente; representan
  resoluciones, pero todavía permiten la transición final a `archived`.
- `archived` es el único estado terminal.
- Una vez asignado `closed_at`, no puede modificarse.
- No existe reapertura en este incremento.
- Una transición fallida no modifica `closed_at`.

**Transiciones que actualizan `closed_at`:**

| Transición | `closed_at` |
|-----------|-------------|
| `approved` → `archived` | timestamp UTC |
| `rejected` → `archived` | timestamp UTC |
| Cualquier otra | null (sin cambios) |

**Response:**
- `CaseFileResponse` debe incluir `closed_at`.
- Antes de `archived` debe ser null.
- Después de `archived` debe contener timestamp UTC en formato ISO 8601.

### Escenarios de Aceptación

**Escenario 1 — Crear empleado**

Dado que el sistema está disponible,
cuando un usuario envía los datos mínimos de un empleado (número de legajo,
nombre, apellido, tipo y número de documento),
entonces el sistema crea el empleado con `active=true`,
y devuelve el empleado creado con su `id` UUID.

**Escenario 2 — Evitar legajo duplicado**

Dado que existe un empleado con número de legajo `LEG-001`,
cuando un usuario intenta crear otro empleado con legajo `LEG-001`,
entonces el sistema retorna error `EMPLOYEE_NUMBER_CONFLICT`,
y no crea ningún registro.

**Escenario 3 — Consultar empleado por ID**

Dado que existe un empleado con ID `abc-123`,
cuando un usuario consulta `GET /api/v1/employees/abc-123`,
entonces el sistema devuelve el empleado completo con todos sus campos.

**Escenario 4 — Listar empleados con paginación**

Dado que existen 25 empleados registrados,
cuando un usuario consulta `GET /api/v1/employees?page=2&page_size=10`,
entonces el sistema devuelve los empleados 11 a 20,
y el objeto de paginación indica `total=25`, `page=2`, `page_size=10`.

**Escenario 5 — Buscar empleados**

Dado que existen empleados en distintos departamentos,
cuando un usuario filtra por `department=Legal` y `active=true`,
entonces solo se devuelven empleados activos del departamento Legal.

**Escenario 6 — Actualizar datos del empleado**

Dado que existe un empleado activo,
cuando un usuario envía un PATCH con campos permitidos (nombre, apellido,
posición, departamento, email, teléfono),
entonces el sistema actualiza esos campos,
y `updated_at` se actualiza a la fecha actual en UTC.

**Escenario 7 — Desactivar empleado**

Dado que existe un empleado activo,
cuando un usuario ejecuta `POST /api/v1/employees/{id}/deactivate`,
entonces el empleado queda con `active=false`,
y no puede recibir nuevos expedientes.

**Escenario 8 — Desactivar empleado ya inactivo (idempotente)**

Dado que existe un empleado ya inactivo,
cuando un usuario ejecuta `POST /api/v1/employees/{id}/deactivate`,
entonces el sistema retorna respuesta exitosa consistente,
sin crear efectos duplicados ni modificar el estado.

**Escenario 9 — Crear expediente para empleado activo**

Dado que existe un empleado activo con ID `emp-001`,
cuando un usuario crea un expediente asociado a ese empleado,
entonces el expediente se crea con estado `draft`,
se registra en el historial la creación inicial (`from_status=null`, `to_status=draft`),
y `case_number` se genera automáticamente de forma única.

**Escenario 10 — Rechazar expediente para empleado inactivo**

Dado que existe un empleado inactivo,
cuando un usuario intenta crear un expediente para ese empleado,
entonces el sistema retorna error `EMPLOYEE_INACTIVE`,
y no crea ningún registro.

**Escenario 11 — Ejecutar transición válida**

Dado que existe un expediente en estado `draft`,
cuando un usuario solicita la transición a `under_review`,
entonces el expediente cambia a `under_review`,
se registra en el historial `from_status=draft`, `to_status=under_review`,
y `updated_at` se actualiza.

**Escenario 12 — Rechazar transición inválida**

Dado que existe un expediente en estado `draft`,
cuando un usuario solicita la transición directamente a `approved`,
entonces el sistema retorna error `INVALID_STATUS_TRANSITION`,
el expediente permanece en `draft`,
y no se genera registro en el historial.

**Escenario 13 — Consultar historial cronológico**

Dado que un expediente tiene 3 transiciones registradas,
cuando un usuario consulta `GET /api/v1/case-files/{id}/history`,
entonces el sistema devuelve los 3 registros ordenados cronológicamente,
con `from_status`, `to_status`, `changed_at`, `changed_by` y `reason` cuando
existe.

**Escenario 14 — Rechazar operación sobre entidad inexistente**

Dado que no existe un empleado con ID `no-existe`,
cuando un usuario consulta `GET /api/v1/employees/no-existe`,
entonces el sistema retorna error `EMPLOYEE_NOT_FOUND` con HTTP 404.

**Escenario 15 — Evitar duplicados por claves únicas**

Dado que existe un expediente con número `EXP-2026-001`,
cuando un usuario intenta crear otro expediente con el mismo número,
entonces el sistema retorna error `CASE_NUMBER_CONFLICT`,
y no crea ningún registro.

**Escenario 16 — Actualizar expediente en estado draft**

Dado que un expediente está en estado `draft`,
cuando un usuario envía un PATCH con título o descripción,
entonces el sistema actualiza esos campos.

**Escenario 17 — Rechazar actualización en estado terminal**

Dado que un expediente está en estado `archived`,
cuando un usuario intenta modificar título o descripción,
entonces el sistema retorna error `CASE_FILE_ARCHIVED`.

## Requisitos Funcionales

### Empleados

#### RF-001 — Crear Empleado

El sistema DEBE permitir crear un empleado mediante
`POST /api/v1/employees`.

**Request body:**
```json
{
  "employee_number": "LEG-000123",
  "first_name": "Ana",
  "last_name": "Pérez",
  "document_type": "dni",
  "document_number": "30111222",
  "cuil": "27-30111222-5",
  "email": "ana.perez@example.test",
  "phone": "+5493794000000",
  "position": "Asesora legal",
  "department": "Legal y Técnica"
}
```

| Campo | Requerido | Descripción |
|-------|-----------|-------------|
| `employee_number` | sí | Número de legajo único |
| `first_name` | sí | Nombre |
| `last_name` | sí | Apellido |
| `document_type` | sí | Tipo de documento (enum: DNI, LC, LE, CI, pasaporte) |
| `document_number` | sí | Número de documento |
| `cuil` | no | CUIL opcional |
| `email` | no | Email opcional |
| `phone` | no | Teléfono opcional |
| `position` | no | Cargo opcional |
| `department` | no | Departamento opcional |

**Reglas del request:**
- `employee_number` lo proporciona el cliente.
- `employee_number` es único globalmente.
- `employee_number` es inmutable después de crear el empleado.
- No reutilizar `employee_number` aunque el empleado esté inactivo.
- `first_name` y `last_name` deben quedar no vacíos después de trim.
- `document_type` debe pertenecer al enum permitido.
- `document_number` debe normalizarse según `document_type`.
- `document_number` debe ser único.
- `cuil`, si existe, debe almacenarse normalizado sin separadores.
- `cuil`, si existe, debe validarse y ser único.
- `email` debe normalizarse en minúsculas.
- `phone` debe normalizarse a un formato consistente cuando sea posible.
- `position` y `department` deben aplicar trim.
- No aceptar campos desconocidos.

**Campos asignados por el servidor:**
- `active` inicia en `true`.
- `id` es un UUID generado por el servidor.
- `created_at` y `updated_at` se establecen en UTC.

**Response exitosa (HTTP 201):**
- Devolver `EmployeeResponse` completo.
- `active` = true.
- Timestamps en UTC con formato ISO 8601.

**Errores:**
- `EMPLOYEE_NUMBER_CONFLICT` → 409
- `EMPLOYEE_DOCUMENT_CONFLICT` → 409
- `VALIDATION_ERROR` → 422
- `DATABASE_ERROR` → 500

**Privacidad:**
- No registrar `document_number`, `cuil`, `email` o `phone` completos.
- Usar únicamente datos ficticios en tests y fixtures.

#### RF-002 — Consultar Empleado por ID

El sistema DEBE permitir consultar un empleado por su `id` UUID mediante
`GET /api/v1/employees/{employee_id}`.

**Comportamiento:**

| Caso | HTTP | Body |
|------|------|------|
| `employee_id` con formato UUID inválido | 422 | `{ "error_code": "VALIDATION_ERROR", "field": "employee_id", ... }` |
| UUID válido pero empleado no existe | 404 | `{ "error_code": "EMPLOYEE_NOT_FOUND", ... }` |
| Empleado existe | 200 | `EmployeeResponse` completo |

**Criterio general aplicable a todos los endpoints con UUID:**
- Errores de sintaxis o formato del path → 422.
- Recurso sintácticamente válido pero inexistente → 404.
- Aplicar la misma convención en: employees, case-files, history,
  transitions, deactivate.
- No devolver 200 con null.
- No convertir UUID inválido en 404.

#### RF-003 — Listar Empleados

El sistema DEBE permitir listar empleados mediante
`GET /api/v1/employees`.

**Query params:**

| Parámetro | Tipo | Default | Descripción |
|-----------|------|---------|-------------|
| `page` | integer | 1 | Página actual (mínimo 1) |
| `page_size` | integer | 20 | Tamaño de página (mínimo 1, máximo 100) |
| `query` | string | — | Búsqueda parcial case-insensitive |
| `active` | boolean | — | Filtrar por estado activo |
| `department` | string | — | Filtrar por departamento |

**Reglas de búsqueda:**
- `query` busca de forma case-insensitive y parcial sobre:
  `employee_number`, `first_name`, `last_name`, `document_number`.
- `query` vacío o compuesto solo por espacios se trata como ausente.
- `department` se compara de forma case-insensitive.
- Los filtros se combinan con AND.

**Orden determinista:**
`created_at` DESC, `id` DESC.

**Formato de respuesta:**
```json
{
  "page": 1,
  "page_size": 20,
  "total": 0,
  "items": []
}
```

**Reglas de paginación:**
- Devolver `total` exacto.
- Si `page` excede el rango, devolver HTTP 200 con `items=[]` y `total`
  conservado.
- No agregar `sort` ni `order` configurables en este incremento.

**Validación de query params:**
- `page` debe ser integer >= 1.
- `page_size` debe ser integer entre 1 y 100.
- `active` debe ser boolean válido.
- `department` debe normalizarse con trim.
- `query` debe normalizarse con trim; vacío o solo espacios se trata
  como ausente.

**Errores de validación:**
- Cualquier query param con formato o valor inválido → HTTP 422,
  `VALIDATION_ERROR`.
- No ejecutar la consulta con valores corregidos silenciosamente.
- No ignorar parámetros inválidos.
- No reemplazar valores inválidos por defaults silenciosamente.
- No devolver 404 por listado vacío.

#### RF-005 — Actualizar Empleado

El sistema DEBE permitir actualizar campos de un empleado mediante
`PATCH /api/v1/employees/{employee_id}`.

**Request body:**
```json
{
  "first_name": "...",
  "last_name": "...",
  "email": "...",
  "phone": "...",
  "position": "...",
  "department": "..."
}
```

| Campo | Requerido | Descripción |
|-------|-----------|-------------|
| `first_name` | no | Nombre actualizado |
| `last_name` | no | Apellido actualizado |
| `email` | no | Email actualizado (null para limpiar) |
| `phone` | no | Teléfono actualizado (null para limpiar) |
| `position` | no | Cargo actualizado (null para limpiar) |
| `department` | no | Departamento actualizado (null para limpiar) |

**Validación del path:**
- Si `employee_id` no tiene formato UUID válido → HTTP 422,
  `VALIDATION_ERROR`.
- No consultar la base de datos.
- No intentar aplicar el PATCH.

**Validación de existencia:**
- Si `employee_id` tiene formato UUID válido pero el empleado no existe
  → HTTP 404, `EMPLOYEE_NOT_FOUND`.

**Validación del body:**
- Todos los campos permitidos son opcionales.
- Debe enviarse al menos uno.
- Body vacío → HTTP 422 / `VALIDATION_ERROR`.
- Campos desconocidos → HTTP 422 / `VALIDATION_ERROR`.
- `first_name` y `last_name` no pueden quedar vacíos después de trim.
- `email`, `phone`, `position` y `department` pueden enviarse como null
  para limpiar el campo.

**Campos permitidos:**
`first_name`, `last_name`, `email`, `phone`, `position`, `department`.

**Campos prohibidos (no modificables):**
`employee_number`, `document_type`, `document_number`, `cuil`, `active`,
`id`, `created_at`, `updated_at`.

**Response exitosa (HTTP 200):**
- Devolver `EmployeeResponse` completo.
- `updated_at` actualizado en UTC.

**Criterio general:**
- UUID inválido → 422.
- Recurso inexistente → 404.
- Payload inválido → 422.
- Actualización exitosa → 200.
- No validar path y body en paralelo.
- Aplicar primero la validación sintáctica del path y luego continuar
  con el procesamiento del request.

**Privacidad:**
- No registrar `document_number`, `cuil`, `email` o `phone` completos.

#### RF-006 — EmployeeResponse

El schema de respuesta de empleado (`EmployeeResponse`) DEBE contener
únicamente los siguientes campos:

| Campo | Tipo | Requerido |
|-------|------|-----------|
| `id` | UUID | sí |
| `employee_number` | string | sí |
| `first_name` | string | sí |
| `last_name` | string | sí |
| `document_type` | enum | sí |
| `document_number` | string | sí |
| `cuil` | string/null | no |
| `email` | string/null | no |
| `phone` | string/null | no |
| `position` | string/null | no |
| `department` | string/null | no |
| `active` | boolean | sí |
| `created_at` | ISO 8601 UTC | sí |
| `updated_at` | ISO 8601 UTC | sí |

**Reglas del schema:**
- Usar el mismo schema de respuesta para: POST (crear), GET (consultar),
  PATCH (actualizar), POST (desactivar).
- `cuil`, `email`, `phone`, `position` y `department` pueden ser null.
- Timestamps en UTC con formato ISO 8601.
- No incluir `case_files_count` ni relaciones embebidas.
- No incluir campos internos del ORM (sa_instance_state, etc.).
- No incluir `version` porque employees no usa control de concurrencia
  optimista en este incremento.
- Nombres técnicos en inglés.

#### RF-006b — Desactivar Empleado

El sistema DEBE permitir desactivar un empleado mediante
`POST /api/v1/employees/{employee_id}/deactivate`.

**Request:**
- Sin body de solicitud.
- `employee_id` únicamente en path.
- `X-Request-ID` opcional en header.

**Validación del path:**
- Si `employee_id` no tiene formato UUID válido → HTTP 422,
  `VALIDATION_ERROR`.
- No consultar la base de datos.
- No ejecutar cambios.

**Validación de existencia:**
- Si `employee_id` tiene formato UUID válido pero el empleado no existe
  → HTTP 404, `EMPLOYEE_NOT_FOUND`.

**Idempotencia:**

| Caso | HTTP | `active` | `updated_at` |
|------|------|----------|--------------|
| Empleado activo | 200 | `false` | se actualiza |
| Empleado ya inactivo | 200 | `false` (sin cambio) | sin cambios |

**Response exitosa (HTTP 200):**
- Devolver la representación completa del empleado (`EmployeeResponse`).
- Si estaba activo: `active=false`, `updated_at` actualizado en UTC.
- Si ya estaba inactivo: sin cambios adicionales, devolver recurso actual.
- No tratarlo como error.
- No usar `EMPLOYEE_ALREADY_INACTIVE`.
- No modificar `updated_at` si no hubo cambio persistente.

**Reglas adicionales:**
- La operación DEBE ser idempotente.
- No bloquear la operación por expedientes existentes.
- Los expedientes existentes permanecen consultables.
- No permitir nuevos expedientes para empleados inactivos.
- No crear historial adicional en este incremento.
- No se requiere `reason`.
- No se usa HTTP 204 porque el cliente necesita confirmar el estado
  resultante.

#### RF-007 — Unicidad de Legajo

El campo `employee_number` DEBE ser único en la base de datos. Un intento
de crear un empleado con un `employee_number` existente DEBE retornar error
`EMPLOYEE_NUMBER_CONFLICT`.

#### RF-008 — Unicidad y Normalización de Documento

La combinación de `document_type` y `document_number` DEBE ser única. Un
intent de crear un empleado con un documento ya registrado DEBE retornar
error `EMPLOYEE_DOCUMENT_CONFLICT`.

**Normalización de `document_number` según `document_type`:**

**Reglas comunes:**
- Aplicar trim al inicio y al final.
- Rechazar valor vacío después de trim.
- No completar ceros automáticamente.
- No inferir ni corregir números.
- No eliminar caracteres internos silenciosamente.
- No aplicar formatos institucionales no confirmados.

**DNI:**
- Aceptar únicamente dígitos ASCII del 0 al 9.
- Rechazar puntos, guiones, espacios internos y letras.
- Almacenar como string para no perder posibles ceros iniciales.
- No exigir exactamente 8 dígitos en este incremento.

**LC, LE y CI:**
- Aceptar caracteres alfanuméricos.
- Rechazar espacios internos y símbolos.
- Normalizar letras a mayúsculas.
- Almacenar el valor normalizado.

**Pasaporte:**
- Aceptar caracteres alfanuméricos.
- Rechazar espacios internos y símbolos.
- Normalizar letras a mayúsculas.
- No imponer cantidad fija de letras o dígitos.

**Unicidad:**
- Comparar `document_number` después de normalizar.
- La unicidad debe aplicarse sobre la combinación:
  `document_type` + `document_number` normalizado.
- Dos tipos documentales diferentes pueden compartir el mismo número.
- `document_type` y `document_number` son inmutables después de crear
  el empleado.

**Errores:**
- Formato inválido → `VALIDATION_ERROR` / HTTP 422.
- Duplicado de `document_type` + `document_number` normalizado →
  `EMPLOYEE_DOCUMENT_CONFLICT` / HTTP 409.

**Privacidad:**
- No registrar `document_number` completo.
- No incluirlo en mensajes de error.
- Usar únicamente valores ficticios en pruebas.

#### RF-009 — Normalización de CUIL

Si se proporciona `cuil`, DEBE almacenarse normalizado (sin guiones ni
espacios). El sistema DEBE aceptar formatos con o sin separadores y
almacenar la versión limpia.

#### RF-010 — No Eliminación Física

No DEBE existir un endpoint DELETE para empleados. La desactivación se
realiza mediante `active=false`. Los empleados con expedientes asociados NO
pueden eliminarse físicamente.

### Expedientes

#### RF-011 — Crear Expediente

El sistema DEBE permitir crear un expediente asociado a un empleado activo.

**Request body:**
```json
{
  "employee_id": "...",
  "title": "...",
  "case_type": "...",
  "description": "..."
}
```

| Campo | Requerido | Descripción |
|-------|-----------|-------------|
| `employee_id` | sí | UUID del empleado asociado |
| `title` | sí | Título del expediente |
| `case_type` | sí | Tipo de expediente (StrEnum: `designacion`, `licencia`, `renuncia`, `contratacion`, `otro`) |
| `description` | no | Descripción opcional del expediente |

**Reglas del request:**
- `case_number` no se recibe del cliente; lo genera el servidor con formato
  `CF-<UUID-completo>`.
- `opened_at` lo asigna el servidor en UTC.
- `status` inicial = `draft`.
- `version` inicial = 1.
- `created_at` y `updated_at` los asigna el servidor.
- `closed_at` inicia en null.
- No aceptar `reason` en este endpoint.
- No aceptar `status`, `version`, `opened_at` o `case_number` enviados
  por el cliente.

**Validaciones:**
- `employee_id` debe referenciar un empleado existente y activo.
- Si `employee_id` no tiene formato UUID válido → `VALIDATION_ERROR` /
  HTTP 422. No consultar la base de datos. No generar `case_number`. No
  crear expediente. No crear historial.
- Si el empleado no existe → `EMPLOYEE_NOT_FOUND` / HTTP 404.
- Si el empleado está inactivo → `EMPLOYEE_INACTIVE` / HTTP 422.
- `title` no puede quedar vacío después de trim.
- `description`, si existe, debe normalizarse (trim).
- `case_type` debe pertenecer al StrEnum definido (`designacion`,
  `licencia`, `renuncia`, `contratacion`, `otro`). Valor inválido →
  `VALIDATION_ERROR` / HTTP 422.
- La creación del expediente y el registro inicial del historial DEBEN
  ser atómicos.

**Criterio general:**
- UUID inválido en body → 422.
- UUID válido pero recurso inexistente → 404.
- Recurso existente pero no habilitado para la operación → 422.
- Creación exitosa → 201.
- No tratar un UUID sintácticamente inválido como recurso inexistente.

**Historial inicial:**
- `from_status` = null.
- `to_status` = `draft`.
- `changed_by` = `"system"` (constante técnica; no se recibe en el
  request; la identidad autenticada reemplazará este valor en un
  incremento futuro).
- `reason` = null.
- `request_id` se toma del contexto HTTP, si existe.
- `changed_at` = timestamp UTC de la creación.

**Response exitosa (HTTP 201):**
- Devolver `CaseFileResponse` completo.
- Incluir `case_number` generado.
- Incluir `status` = `draft`.
- Incluir `version` = 1.
- Incluir `opened_at`, `created_at` y `updated_at`.
- Incluir `closed_at` = null.

#### RF-011a — CaseFileResponse

El schema de respuesta de expediente (`CaseFileResponse`) DEBE contener
únicamente los siguientes campos:

| Campo | Tipo | Requerido |
|-------|------|-----------|
| `id` | UUID | sí |
| `case_number` | string | sí |
| `employee_id` | UUID | sí |
| `title` | string | sí |
| `description` | string/null | no |
| `case_type` | enum | sí |
| `status` | enum | sí |
| `version` | integer | sí |
| `opened_at` | ISO 8601 UTC | sí |
| `created_at` | ISO 8601 UTC | sí |
| `updated_at` | ISO 8601 UTC | sí |
| `closed_at` | ISO 8601 UTC/null | no |

**Reglas del schema:**
- Usar el mismo schema de respuesta para: POST (crear), GET (consultar),
  PATCH (actualizar), POST (transicionar).
- `employee_id` es una referencia simple (UUID), no un objeto embebido.
- No incluir `employee_name` ni objeto `employee` embebido.
- `description` y `closed_at` pueden ser null.
- Timestamps en UTC con formato ISO 8601.
- `version` DEBE estar presente porque se utiliza para control de
  concurrencia optimista.
- `case_number` es inmutable.
- `employee_id` es inmutable después de la creación.
- No incluir historial embebido.
- No incluir campos internos del ORM.
- Nombres técnicos en inglés.

#### RF-012 — Consultar Expediente por ID

El sistema DEBE permitir consultar un expediente por su `id` UUID mediante
`GET /api/v1/case-files/{case_file_id}`.

**Comportamiento:**

| Caso | HTTP | Body |
|------|------|------|
| `case_file_id` con formato UUID inválido | 422 | `{ "error_code": "VALIDATION_ERROR", "field": "case_file_id", ... }` |
| UUID válido pero expediente no existe | 404 | `{ "error_code": "CASE_FILE_NOT_FOUND", ... }` |
| Expediente existe | 200 | `CaseFileResponse` completo |

**Criterio general:**
- UUID inválido → 422.
- Recurso inexistente → 404.
- Recurso existente → 200.
- No devolver 200 con null.
- No convertir UUID inválido en 404.

#### RF-013 — Listar Expedientes

El sistema DEBE permitir listar expedientes mediante
`GET /api/v1/case-files`.

**Query params:**

| Parámetro | Tipo | Default | Descripción |
|-----------|------|---------|-------------|
| `page` | integer | 1 | Página actual (mínimo 1) |
| `page_size` | integer | 20 | Tamaño de página (mínimo 1, máximo 100) |
| `query` | string | — | Búsqueda parcial case-insensitive |
| `employee_id` | UUID | — | Filtrar por empleado |
| `status` | enum | — | Filtrar por estado |
| `case_type` | enum | — | Filtrar por tipo de caso |
| `opened_from` | datetime | — | Fecha de apertura desde |
| `opened_to` | datetime | — | Fecha de apertura hasta |

**Reglas de búsqueda:**
- `query` busca de forma case-insensitive y parcial sobre:
  `case_number`, `title`.
- Los filtros se combinan con AND.
- `opened_from` y `opened_to` se interpretan en UTC.
- Si ambos existen, `opened_from` no puede ser posterior a `opened_to`.

**Orden determinista:**
`created_at` DESC, `id` DESC.

**Formato de respuesta:**
```json
{
  "page": 1,
  "page_size": 20,
  "total": 0,
  "items": []
}
```

**Reglas de paginación:**
- Devolver `total` exacto.
- Si `page` excede el rango, devolver HTTP 200 con `items=[]` y `total`
  conservado.
- No agregar `sort` ni `order` configurables en este incremento.

**Validación de query params:**
- `page` debe ser integer >= 1.
- `page_size` debe ser integer entre 1 y 100.
- `employee_id` debe tener formato UUID válido.
- `status` debe pertenecer al enum definido.
- `case_type` debe pertenecer al StrEnum definido.
- `opened_from` y `opened_to` deben ser datetimes válidos.
- `opened_from` no puede ser posterior a `opened_to`.
- `query` debe normalizarse con trim; vacío o solo espacios se trata
  como ausente.

**Errores de validación:**
- Cualquier query param con formato o valor inválido → HTTP 422,
  `VALIDATION_ERROR`.
- No ejecutar la consulta con valores corregidos silenciosamente.
- No ignorar parámetros inválidos.
- No reemplazar valores inválidos por defaults silenciosamente.
- No devolver 404 por listado vacío.

El sistema DEBE permitir filtrar expedientes por: `employee_id`, `status`,
`case_type`, `opened_from` (fecha), `opened_to` (fecha), `query` (número o
título). Los filtros DEBEN combinarse con lógica AND.

#### RF-015 — Actualizar Expediente

El sistema DEBE permitir actualizar campos de un expediente mediante
`PATCH /api/v1/case-files/{case_file_id}`.

**Request body:**
```json
{
  "title": "...",
  "description": "...",
  "expected_version": 1
}
```

| Campo | Requerido | Descripción |
|-------|-----------|-------------|
| `title` | no | Nuevo título del expediente |
| `description` | no | Nueva descripción (null para limpiar) |
| `expected_version` | sí | Versión actual conocida del cliente |

**Validación del path:**
- Si `case_file_id` no tiene formato UUID válido → HTTP 422,
  `VALIDATION_ERROR`.
- No consultar la base de datos.
- No procesar el body.
- No realizar cambios.

**Validación de existencia:**
- Si `case_file_id` tiene formato UUID válido pero el expediente no existe
  → HTTP 404, `CASE_FILE_NOT_FOUND`.

**Validación de estado:**
- Si el expediente está `archived` → HTTP 409, `CASE_FILE_ARCHIVED`.
- No modificar ningún campo.
- No incrementar `version`.

**Concurrencia optimista:**
- `expected_version` es obligatorio.
- Si `expected_version` no coincide con la versión persistida → HTTP 409,
  `CONCURRENT_MODIFICATION`.
- No aplicar cambios.

**Validación del body:**
- `title` es opcional.
- `description` es opcional.
- Debe enviarse al menos uno.
- Body vacío → HTTP 422 / `VALIDATION_ERROR`.
- Campos desconocidos → HTTP 422 / `VALIDATION_ERROR`.
- `title` no puede quedar vacío después de trim.
- `description` puede ser null para limpiar el campo.

**Campos permitidos:**
`title`, `description`, `expected_version`.

**Campos prohibidos (no modificables):**
`case_number`, `employee_id`, `case_type`, `status`, `version`,
`opened_at`, `closed_at`, `created_at`, `updated_at`.

**Response exitosa (HTTP 200):**
- Devolver `CaseFileResponse` completo.
- Incrementar `version` en 1.
- Actualizar `updated_at` en UTC.
- No crear historial porque no hay cambio de estado.

**Criterio general:**
- UUID inválido → 422.
- Recurso inexistente → 404.
- Expediente archivado → 409.
- Conflicto de versión → 409.
- Payload inválido → 422.
- Actualización exitosa → 200.
- Aplicar primero la validación sintáctica del path y después procesar
  el body.

#### RF-016 — Transición de Estado

El sistema DEBE exponer un endpoint específico para transiciones:
`POST /api/v1/case-files/{case_file_id}/transitions`.

**Request body:**
```json
{
  "status": "under_review",
  "expected_version": 1,
  "changed_by": "usuario-local",
  "reason": "Motivo opcional"
}
```

| Campo | Requerido | Descripción |
|-------|-----------|-------------|
| `status` | sí | Estado destino deseado |
| `expected_version` | sí | Versión actual conocida del cliente (control de concurrencia) |
| `changed_by` | sí | Identificador del autor de la acción |
| `reason` | no | Justificación opcional de la transición |
| `case_file_id` | path | Identificador del caso |

**Reglas del request:**
- `status` es obligatorio.
- `expected_version` es obligatorio.
- `changed_by` es obligatorio.
- `reason` es opcional.
- `case_file_id` se recibe por path.
- `X-Request-ID` es opcional en header.
- No aceptar `from_status` enviado por el cliente.
- No aceptar `version` nueva enviada por el cliente.
- No permitir transición al mismo estado.

**Validación del path:**
- Si `case_file_id` no tiene formato UUID válido → HTTP 422,
  `VALIDATION_ERROR`.
- No consultar la base de datos.
- No intentar ejecutar la transición.
- No crear historial.

**Validación de existencia:**
- Si `case_file_id` tiene formato UUID válido pero el expediente no
  existe → HTTP 404, `CASE_FILE_NOT_FOUND`.
- No crear historial.

**Validación del body:**
- `status` obligatorio.
- `expected_version` obligatorio.
- `changed_by` obligatorio.
- `reason` opcional.
- Errores de formato o campos inválidos → HTTP 422 / `VALIDATION_ERROR`.

**Reglas de dominio (post-validación):**

| Caso | HTTP | error_code |
|------|------|------------|
| UUID inválido en path | 422 | `VALIDATION_ERROR` |
| Expediente no existe | 404 | `CASE_FILE_NOT_FOUND` |
| Transición no permitida | 409 | `INVALID_STATUS_TRANSITION` |
| Expediente archivado | 409 | `CASE_FILE_ARCHIVED` |
| `expected_version` no coincide | 409 | `CONCURRENT_MODIFICATION` |
| Payload inválido | 422 | `VALIDATION_ERROR` |

**Criterio general:**
- Path inválido → 422.
- Recurso inexistente → 404.
- Conflicto de estado o concurrencia → 409.
- Payload inválido → 422.
- No combinar varios errores en una misma respuesta.
- Aplicar validación determinista antes de ejecutar cualquier cambio
  persistente.

**Response exitosa (HTTP 200):**
- Devolver únicamente `CaseFileResponse` completo.
- `status` actualizado al destino.
- `version` incrementado en 1.
- `updated_at` actualizado.
- `closed_at` actualizado únicamente cuando la regla de transición lo
  requiera.
- No incluir objeto `transition`, historial embebido, `from_status`
  adicional ni `changed_at` adicional fuera de los campos propios del
  expediente.
- El registro de historial se persiste de forma atómica pero no se incluye
  en la respuesta.
- El historial se consulta exclusivamente en:
  `GET /api/v1/case-files/{case_file_id}/history`.

**Atomicidad:**
La operación DEBE ejecutarse en una única transacción:
1. validar existencia del caso;
2. validar `expected_version` contra el valor persistido;
3. validar que la transición sea legal según la máquina de estados;
4. actualizar `status`;
5. incrementar `version`;
6. actualizar timestamps (`updated_at`, y `closed_at` si aplica);
7. insertar registro en `case_status_history`;
8. confirmar transacción.

Si falla cualquier paso, hacer rollback completo.

**Errores:**
- `CASE_FILE_NOT_FOUND` → 404
- `INVALID_STATUS_TRANSITION` → 409
- `CASE_FILE_ARCHIVED` → 409
- `CONCURRENT_MODIFICATION` → 409
- `VALIDATION_ERROR` → 422
- `DATABASE_ERROR` → 500

**Historial (`case_status_history`):**
- `from_status` se obtiene del estado persistido (no del request).
- `to_status` se obtiene del campo `status` del request.
- `changed_by` se toma del body.
- `reason` se toma del body.
- `request_id` se toma del contexto HTTP.
- Una transición fallida NO genera registro en historial.

#### RF-017 — Historial de Estados

El sistema DEBE exponer el endpoint
`GET /api/v1/case-files/{case_file_id}/history` que devuelve todos los
registros de historial del expediente.

**Response exitosa (HTTP 200):**
```json
{
  "items": [
    {
      "id": "...",
      "case_file_id": "...",
      "from_status": null,
      "to_status": "draft",
      "changed_at": "...",
      "changed_by": "...",
      "reason": null,
      "request_id": "..."
    }
  ]
}
```

**Campos de cada item:**

| Campo | Tipo | Requerido |
|-------|------|-----------|
| `id` | UUID | sí |
| `case_file_id` | UUID | sí |
| `from_status` | string/null | no |
| `to_status` | string | sí |
| `changed_at` | ISO 8601 UTC | sí |
| `changed_by` | string | sí |
| `reason` | string/null | no |
| `request_id` | string/null | no |

**Reglas:**
- `from_status` puede ser null únicamente en el registro inicial.
- `reason` puede ser null.
- `request_id` puede ser null.
- Timestamps en UTC con formato ISO 8601.
- Ordenar cronológicamente por `changed_at` ascendente.
- Usar `id` ascendente como criterio secundario para orden determinista.
- No incluir datos del empleado ni el expediente embebido.
- No permitir edición ni eliminación del historial (append-only).
- No agregar paginación en este incremento.

**Comportamiento por caso:**

| Caso | HTTP | Body |
|------|------|------|
| Expediente no existe | 404 | `{ "error_code": "CASE_FILE_NOT_FOUND", ... }` |
| Expediente existe, sin registros | 200 | `{ "items": [] }` |
| Expediente existe, con registros | 200 | `{ "items": [...] }` |

**Validación del path:**
- Si `case_file_id` no tiene formato UUID válido → HTTP 422,
  `VALIDATION_ERROR`.
- No devolver `CASE_FILE_NOT_FOUND` para un UUID sintácticamente inválido.

#### RF-018 — Unicidad de Número de Expediente

El campo `case_number` DEBE ser único en la base de datos (constraint UNIQUE).
El formato DEBE ser `CF-<UUID-completo>`. El campo es inmutable: no puede
modificarse después de la creación. Un intento de crear un expediente con un
`case_number` existente DEBE retornar error `CASE_NUMBER_CONFLICT`.

#### RF-019 — Control de Concurrencia

El sistema DEBE soportar control de concurrencia mediante campo `version`
entero en la entidad expediente. Cada actualización DEBE verificar que la
versión enviada coincida con la versión actual. Si hay desfase, DEBE retornar
error `CONCURRENT_MODIFICATION`.

### Paginación

#### RF-020 — Paginación Estándar

Todos los endpoints de listado DEBEN soportar paginación con parámetros:
`page` (entero >= 1, default 1), `page_size` (entero, default 20, máximo
100). La respuesta DEBE incluir: `items` (array), `total` (entero), `page`
(entero), `page_size` (entero). El orden DEBE ser determinista. Si `page`
excede el rango, devolver HTTP 200 con `items=[]` y `total` conservado.

### Errores

#### RF-021 — Errores Estructurados

Todos los errores DEBEN seguir la estructura:
`{ "error_code": "...", "message": "...", "field": "...", "request_id": "..." }`.
Los códigos de error DEBEN ser estables y no depender del texto del mensaje.
Los stack traces, SQL, credenciales y datos internos NO DEBEN exponerse.

**Estructura de respuesta de error:**

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `error_code` | string | Código estable del error |
| `message` | string | Mensaje descriptivo seguro |
| `field` | string/null | Campo en conflicto (solo aplica a ciertos errores) |
| `request_id` | string/null | ID de trazabilidad de la petición |

**Mapeo HTTP uniforme para todos los endpoints:**

| Código de error | HTTP |
|-----------------|------|
| `EMPLOYEE_NOT_FOUND` | 404 |
| `CASE_FILE_NOT_FOUND` | 404 |
| `EMPLOYEE_NUMBER_CONFLICT` | 409 |
| `EMPLOYEE_DOCUMENT_CONFLICT` | 409 |
| `CASE_NUMBER_CONFLICT` | 409 |
| `INVALID_STATUS_TRANSITION` | 409 |
| `CASE_FILE_ARCHIVED` | 409 |
| `CONCURRENT_MODIFICATION` | 409 |
| `EMPLOYEE_INACTIVE` | 422 |
| `VALIDATION_ERROR` | 422 |
| `DATABASE_ERROR` | 500 |

**Criterios de mapeo:**
- 404: recurso no encontrado.
- 409: el estado actual del recurso impide completar la operación, o existe
  un conflicto de unicidad.
- 422: el payload o una regla semántica de entrada no puede procesarse.
- 500: error interno no controlado.
- No se usa 400 para errores de dominio ya tipificados.
- El mismo código de error siempre devuelve el mismo HTTP en todos los
  endpoints.

**Uso de `field`:**
- `EMPLOYEE_DOCUMENT_CONFLICT`: `field` indica `"document_number"` o
  `"cuil"` según el campo en conflicto.
- `EMPLOYEE_NUMBER_CONFLICT`: `field` = `"employee_number"`.
- `CASE_NUMBER_CONFLICT`: `field` = `"case_number"`.
- `VALIDATION_ERROR`: `field` indica el campo con problema.
- Otros errores: `field` puede ser null.
- Nunca incluir el valor real del campo en conflicto en el mensaje.

**Formato de `VALIDATION_ERROR`:**

Cuando el body contiene uno o más campos inválidos, la respuesta DEBE
seguir este formato:

```json
{
  "error_code": "VALIDATION_ERROR",
  "message": "La solicitud contiene datos inválidos",
  "errors": [
    {
      "field": "first_name",
      "code": "required",
      "message": "El campo es obligatorio"
    },
    {
      "field": "email",
      "code": "invalid_format",
      "message": "El formato del correo electrónico no es válido"
    }
  ],
  "request_id": "..."
}
```

**Reglas de `errors`:**
- Devolver todos los errores de validación determinística del request.
- Mantener orden estable según el orden de los campos del schema.
- No repetir errores equivalentes para el mismo campo.
- No incluir `document_number`, `cuil`, `email` o `phone` completos en
  mensajes.
- No devolver stack traces ni detalles SQL.
- Campos desconocidos deben generar un error con `code` = `"extra_forbidden"`.
- Body vacío debe devolver errores para los campos obligatorios.
- Conflictos de unicidad no forman parte de `VALIDATION_ERROR`:
  `EMPLOYEE_NUMBER_CONFLICT` → 409, `EMPLOYEE_DOCUMENT_CONFLICT` → 409.

**Política uniforme para body vacío (`{}`):**

Si el body está vacío y faltan campos obligatorios, devolver HTTP 422 con
la lista de errores para todos los campos obligatorios faltantes. No
devolver un único error genérico. No aplicar valores por defecto salvo que
el contrato los defina expresamente. No ejecutar lógica de dominio. No
consultar la base de datos cuando la validación del request ya falló.

| Endpoint | Campos obligatorios faltantes |
|----------|------------------------------|
| `POST /employees` | `employee_number`, `first_name`, `last_name`, `document_type`, `document_number` |
| `POST /case-files` | `employee_id`, `title`, `case_type` |
| `POST /transitions` | `status`, `expected_version`, `changed_by` |
| `PATCH /employees/{id}` |-error body: `at_least_one_field_required` |
| `PATCH /case-files/{id}` | `expected_version` + error body: `at_least_one_field_required` |

## Requisitos No Funcionales

### Seguridad (RNF-001)

- No usar datos personales reales en tests, fixtures ni documentación.
- Evitar registrar DNI, CUIL, email o teléfono completos en logs.
- Sanitizar logs para no exponer información sensible.
- Cada operación DEBE incluir `request_id` para trazabilidad.
- Timestamps DEBEN expresarse en UTC.
- No implementar autorización en este incremento; documentar que será
  obligatoria antes de producción.

### Privacidad (RNF-002)

- Tests con identidades ficticias.
- No cargar datos personales reales en fixtures.
- No registrar documentos completos en logs.

### Rendimiento (RNF-003)

- La paginación DEBE limitar la cantidad de registros devueltos.
- Los filtros DEBEN aprovechar índices en la base de datos.
- Las transiciones DEBEN ejecutarse en una transacción atómica.

### Persistencia (RNF-004)

- PostgreSQL con SQLAlchemy 2 async.
- Migraciones Alembic explícitas y versionadas.
- Constraints y unique indexes en base de datos.
- Foreign keys para integridad referencial.
- Índices para búsquedas frecuentes (nombre, apellido, legajo, documento,
  estado, empleado_id).
- Transacción atómica para cambio de estado + registro de historial.

### Observabilidad (RNF-005)

- Cada operación DEBE incluir `request_id`.
- Los errores DEBEN registrarse con contexto técnico sin secretos.
- Los logs DEBEN ser estructurados o consistentes.

### Compatibilidad (RNF-006)

- Desarrollo en Windows con PowerShell y Docker Desktop.
- Ejecución en contenedores Linux.
- No codificar rutas absolutas ni depender de IPs o nombres internos.
- No modificar los contratos de health existentes del incremento 001.

### Testabilidad (RNF-007)

- Pruebas unitarias para lógica de dominio (transiciones, normalización).
- Pruebas de integración con PostgreSQL real.
- Pruebas contractuales para schemas de respuesta.
- Cobertura mínima del 85%.

## Reglas de Negocio

### RB-001

El `employee_number` debe ser único. No se permite duplicación de legajos.

### RB-002

La combinación `document_type` + `document_number` debe ser única.

### RB-003

El `cuil` se almacena normalizado (sin guiones ni espacios).

### RB-004

No se eliminan físicamente empleados. La desactivación es mediante
`active=false`.

### RB-005

La desactivación de un empleado no se bloquea por tener expedientes. La
operación es idempotente.

### RB-006

El estado inicial de todo expediente es `draft`.

### RB-007

`archived` es un estado terminal. No admite transiciones posteriores.

### RB-008

`approved` no puede volver a `draft`.

### RB-009

No se permiten saltos arbitrarios entre estados.

### RB-010

Toda transición exitosa genera un registro en el historial.

### RB-011

Una transición fallida no genera historial.

### RB-012

El historial es append-only. No se puede editar ni eliminar.

### RB-013

No se cierra automáticamente un expediente sin transición explícita.

### RB-014

No se permite DELETE físico en endpoints de empleados o expedientes.

### RB-015

El `case_number` es inmutable. No puede modificarse después de la creación.

### RB-016

Los endpoints de health check existentes no deben modificarse.

### RB-019

Los endpoints de health check permanecen sin cambios en este incremento:
- `GET /health/live`
- `GET /health/ready`
- `GET /health/dependencies`

No agregar campos de empleados o expedientes. No crear nuevos health
endpoints. No modificar status codes, schemas, códigos de error o
comportamiento. No introducir consultas a tablas de dominio dentro de
health. No hacer que readiness dependa de que existan empleados o
expedientes. Mantener pruebas contractuales existentes como regresión
obligatoria.

**Comportamiento de `GET /health/ready`:**
- Verifica conectividad con PostgreSQL y capacidad de ejecutar una
  consulta técnica mínima.
- Verifica disponibilidad de pgvector según el contrato existente.
- NO verifica existencia de tablas de negocio (`employees`, `case_files`,
  `case_status_history`).
- NO verifica presencia de datos o cantidad de registros.
- Las tablas se validan mediante Alembic y pruebas de migración, no
  mediante readiness.

**Respuesta de readiness:**
- Dependencias obligatorias disponibles → HTTP 200, `status="ready"`.
- PostgreSQL, pgvector u Ollama no disponibles → HTTP 503,
  `status="not_ready"`.
- Mantener exactamente los códigos, campos y estructura definidos en el
  incremento 001.
- No agregar campos nuevos (`postgres`, `employees`, `case_files`,
  `error`) salvo que ya formen parte del contrato existente.
- La información detallada por dependencia corresponde a
  `GET /health/dependencies` y no debe duplicarse dentro de
  `/health/ready`.

### RB-017

No se implementa autenticación en este incremento. Se documenta que será
obligatoria antes de producción.

### RB-018

No se usan embeddings ni columnas vectoriales en este incremento. pgvector
permanece instalado pero no se utiliza.

## Objetivos de Nivel de Servicio (SLOs)

- Creación de empleado: respuesta dentro de 2 segundos.
- Consulta de empleado por ID: respuesta dentro de 1 segundo.
- Listado con paginación: respuesta dentro de 2 segundos para hasta 10,000
  registros.
- Creación de expediente: respuesta dentro de 2 segundos.
- Transición de estado: respuesta dentro de 1 segundo.
- Consulta de historial: respuesta dentro de 1 segundo.
- Cero datos personales reales expuestos en logs o respuestas.

## Criterios de Éxito

### Validación Funcional

- [ ] Se pueden crear empleados y consultarlos por ID
- [ ] Se evita duplicación de legajos (`EMPLOYEE_NUMBER_CONFLICT`)
- [ ] Se evita duplicación de documentos (`EMPLOYEE_DOCUMENT_CONFLICT`)
- [ ] Se pueden listar empleados con paginación correcta
- [ ] Se pueden buscar empleados por nombre, legajo o documento
- [ ] Se pueden actualizar campos permitidos del empleado
- [ ] Se puede desactivar un empleado (idempotente)
- [ ] La desactivación de empleado ya inactivo retorna éxito sin duplicar efectos
- [ ] Se crea expediente para empleado activo con estado `draft`
- [ ] No se crea expediente para empleado inactivo (`EMPLOYEE_INACTIVE`)
- [ ] No se crea expediente para empleado inexistente (`EMPLOYEE_NOT_FOUND`)
- [ ] Se ejecutan transiciones válidas con registro en historial
- [ ] Se rechazan transiciones inválidas (`INVALID_STATUS_TRANSITION`)
- [ ] El historial se consulta en orden cronológico
- [ ] No se modifican expedientes en estado `archived`
- [ ] Se evita duplicación de números de expediente
- [ ] El control de concurrencia detecta modificaciones simultáneas
- [ ] Los errores son estructurados con códigos estables
- [ ] No se exponen stack traces, SQL ni credenciales

### Validación de Pruebas

- [ ] Pruebas unitarias para lógica de transiciones
- [ ] Pruebas de integración con PostgreSQL real
- [ ] Pruebas contractuales para schemas de respuesta
- [ ] Cobertura >= 85%
- [ ] Pruebas sin datos personales reales

### Validación Operativa

- [ ] Migraciones Alembic ejecutables desde base vacía
- [ ] Health endpoints existentes funcionan correctamente
- [ ] Integración con Ollama no se ve afectada
- [ ] ruff check, ruff format y mypy aprobados
- [ ] Docker Compose operativo con postgres y api
- [ ] Desarrollo funciona en Windows, ejecución en Linux

## Casos Límite

- Crear empleado con campos opcionales nulos o vacíos.
- Crear empleado con `cuil` con formatos variados (guiones, espacios, sin
  separadores).
- Crear expediente con `description` vacía.
- Ejecutar transición desde estado `archived`.
- Ejecutar transición que no existe en la máquina de estados.
- Crear expediente para empleado que fue desactivado después de la consulta.
- Listar expedientes cuando no hay ninguno registrado.
- Filtrar empleados con combinaciones de filtros que no devuelven resultados.
- Paginación con `page` mayor al total de páginas.
- Paginación con `page_size` mayor al máximo permitido.
- Actualización concurrente del mismo expediente desde dos solicitudes.
- Transición con `changed_by` vacío o nulo.
- Historial con muchos registros (rendimiento de consulta).

## Supuestos

- PostgreSQL 16 con pgvector ya está disponible (incremento 001).
- La API FastAPI ya está funcionando con health checks (incremento 001).
- Docker Compose ya está configurado (incremento 001).
- No se requiere autenticación para este incremento.
- El `case_number` se genera automáticamente por el servidor con formato
  `CF-<UUID-completo>` (identificador técnico único, inmutable, no secuencial,
  no incluye año). Constraint UNIQUE en base de datos.
- El `document_type` es un enum con valores predefinidos (DNI, LC, LE, CI,
  pasaporte).
- El `case_type` es un StrEnum fijo con cinco valores definidos en esta
  especificación: `designacion`, `licencia`, `renuncia`, `contratacion`,
  `otro`.
- Los datos de prueba usan identidades ficticias.
- La paginación default es 20 ítems por página, máximo 100.
- El orden por defecto de empleados es por `created_at` descendente,
  `id` descendente.
- El orden por defecto de expedientes es por `created_at` descendente,
  `id` descendente.

## Alcance Excluido

Las siguientes capacidades están **excluidas explícitamente** de este
incremento y no deben generar código ni tareas:

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
- Kubernetes
- Terraform
- Helm
- Redis
- Colas y workers
- Generación de contenido jurídico
- Exportación de documentos

## Dependencias

- Incremento 001 completado y validado
- PostgreSQL 16 con pgvector habilitado
- FastAPI con health checks funcionando
- Docker Compose con servicios postgres y api
- Constitución del proyecto (`.specify/memory/constitution.md`)
- Principios IaC (`.specify/memory/principles.md`)

## Notas

- Este es el segundo incremento del proyecto, construyendo sobre la base
  técnica verificada del incremento 001.
- La máquina de estados está diseñada para ciclos de revisión administrativa
  típicos de organismos públicos.
- El campo `version` para control de concurrencia se incluye porque la
  gestión de expedientes implica múltiples usuarios potenciales
  modificando el mismo registro.
- El historial append-only cumple con el Principio III (Trazabilidad y
  Auditoría) de la constitución.
- No se implementa eliminación física (DELETE) para mantener la integridad
  de datos y la trazabilidad.
- La especificación evita deliberadamente prescribir librerías o frameworks
  específicos más allá de los ya fijados en la constitución.

## Clarifications

### Session 2026-07-31

- Q: ¿Qué formato usa `case_number`? → A: Identificador técnico único
  generado por servidor con formato `CF-<UUID-completo>`. Inmutable, no
  secuencial, no incluye año, no simula numeración administrativa oficial.
  Constraint UNIQUE en base de datos. Ante colisión excepcional, regenerar
  antes de persistir.

- Q: ¿Se mantiene `EMPLOYEE_HAS_CASE_FILES`? → A: No. Se elimina. La
  desactivación no se bloquea por expedientes. La operación es idempotente.
  Un empleado inactivo no recibe nuevos expedientes. Los expedientes
  existentes permanecen consultables y operables.

- Q: ¿Qué mapeo HTTP usa cada código de error? → A: Convención REST
  estándar. 404 para NOT_FOUND, 409 para CONFLICT y estado inválido, 422
  para reglas semánticas de entrada, 500 para errores internos. Mismo
  código HTTP siempre para el mismo error, en todos los endpoints.

- Q: ¿Qué contrato tiene el endpoint de desactivación? → A: Request sin
  body. Response 200 con empleado completo, `active=false`, `updated_at`
  actualizado. Operación idempotente. Si ya inactivo, retorna 200 con
  recurso actual.

- Q: ¿Qué contrato tiene el endpoint de transición? → A: Body con
  `status`, `expected_version` (obligatorio), `changed_by` (obligatorio),
  `reason` (opcional). Response 200 con expediente completo y `version`
  incrementado. Atomicidad en transacción. `from_status` se obtiene del
  persistido, no del request.

- Q: ¿Qué campos devuelve EmployeeResponse? → A: `id`, `employee_number`,
  `first_name`, `last_name`, `document_type`, `document_number`, `cuil`,
  `email`, `phone`, `position`, `department`, `active`, `created_at`,
  `updated_at`. Cuil, email, phone, position y department pueden ser null.
  Timestamps ISO 8601 UTC. Mismo schema para crear, consultar, actualizar
  y desactivar. No incluir `version` ni `case_files_count`.

- Q: ¿Qué campos devuelve CaseFileResponse? → A: `id`, `case_number`,
  `employee_id`, `title`, `description`, `case_type`, `status`, `version`,
  `opened_at`, `created_at`, `updated_at`, `closed_at`. Description y
  closed_at pueden ser null. Timestamps ISO 8601 UTC. `version` presente
  para control de concurrencia. `case_number` y `employee_id` inmutables.
  Mismo schema para crear, consultar, actualizar y transicionar.

- Q: ¿Qué campos devuelve HistoryResponse? → A: Objeto con `items` (array
  de objetos). Cada item: `id`, `case_file_id`, `from_status` (null en
  creación), `to_status`, `changed_at` (ISO 8601 UTC), `changed_by`,
  `reason` (null opcional), `request_id` (null opcional). Orden: cronológico
  ascendente por `changed_at`, secundario por `id` ascendente. Sin paginación.
  200 con `items=[]` si existe sin registros. 404 si no existe.

- Q: ¿Qué campos acepta el request para crear expediente? → A:
  `employee_id` (requerido), `title` (requerido), `case_type` (requerido),
  `description` (opcional). El servidor genera `case_number`, `opened_at`,
  `status`=draft, `version`=1, `created_at`, `updated_at`, `closed_at`=null.
  No aceptar `status`, `version`, `opened_at`, `case_number` del cliente.
  Response 201 con CaseFileResponse completo. Creación + historial atómicos.

- Q: ¿Qué campos acepta el request para actualizar expediente? → A:
  `title` (opcional), `description` (opcional, null para limpiar),
  `expected_version` (obligatorio). Al menos uno de title/description
  requerido. Concurrencia optimista con expected_version. No modificar
  archived. Response 200 con CaseFileResponse completo y version
  incrementado. No crear historial (no hay cambio de estado).

- Q: ¿Qué campos acepta el request para crear empleado? → A:
  `employee_number` (requerido, único, inmutable), `first_name` (requerido),
  `last_name` (requerido), `document_type` (requerido, enum), `document_number`
  (requerido, único), `cuil` (opcional, normalizado, único), `email`
  (opcional, minúsculas), `phone` (opcional), `position` (opcional),
  `department` (opcional). `active`=true, `id`=UUID, timestamps en UTC.
  Response 201 con EmployeeResponse completo.

- Q: ¿Qué campos acepta el request para actualizar empleado? → A:
  `first_name`, `last_name`, `email`, `phone`, `position`, `department`
  (todos opcionales, al menos uno requerido). No modificar employee_number,
  document_type, document_number, cuil, active, id, created_at, updated_at.
  Sin expected_version. Desactivación usa POST /deactivate. Response 200
  con EmployeeResponse completo.

- Q: ¿Qué query params usan los endpoints de listado? → A: Empleados:
  `page`, `page_size`, `query`, `active`, `department`. Expedientes: `page`,
  `page_size`, `query`, `employee_id`, `status`, `case_type`, `opened_from`,
  `opened_to`. Paginación: default 20, max 100. Orden: created_at DESC,
  id DESC. Total exacto. Si page excede rango: 200 con items=[]. Sin sort
  configurable.

- Q: ¿Qué devuelve el endpoint de transiciones? → A: Solo CaseFileResponse
  completo con status, version (incrementado) y updated_at actualizados.
  No incluir transition, history embebido ni from_status adicional. El
  historial se persiste atómicamente pero se consulta en /history por
  separado.

- Q: ¿Cómo se normaliza document_number según document_type? → A: Trim +
  rechazar vacío. DNI: solo dígitos (string). LC/LE/CI: alfanumérico,
  mayúsculas. Pasaporte: alfanumérico, mayúsculas. Unicidad sobre
  document_type + document_number normalizado. No completar ceros, no
  inferir, no eliminar caracteres internos.

- Q: ¿En qué transiciones se actualiza closed_at? → A: Solo cuando
  to_status = archived. Valor = timestamp UTC de la transición. approved
  y rejected no cierran; son resoluciones que permiten llegar a archived.
  Una vez asignado, no puede modificarse. No existe reapertura.

- Q: ¿La lista de códigos de error está completa? → A: Sí, 11 códigos.
  EMPLOYEE_DOCUMENT_CONFLICT cubre document_number y cuil duplicados. El
  payload incluye campo técnico "field" que identifica el campo en conflicto.
  No incluir valor real en el mensaje. No agregar CUIL_CONFLICT ni
  EMPLOYEE_ALREADY_ACTIVE (deactivate es idempotente, no es error).

- Q: ¿Qué devuelve GET /history si el expediente no existe? → A: 404 con
  CASE_FILE_NOT_FOUND. 200 con items=[] si existe sin registros. 200 con
  items=[...] si existe con historial. UUID sintácticamente inválido →
  422 VALIDATION_ERROR, no 404.

- Q: ¿Qué devuelve GET /employees/{id} si el empleado no existe? → A: 404
  con EMPLOYEE_NOT_FOUND. UUID inválido → 422 VALIDATION_ERROR. Misma
  convención para todos los endpoints con UUID: sintaxis → 422, recurso
  inexistente → 404. No devolver 200 con null.

- Q: ¿Qué devuelve POST /transitions si el UUID es inválido? → A: 422
  VALIDATION_ERROR sin consultar BD. 404 si no existe. 409 para
  transición inválida, archived o concurrent_modification. 422 para
  payload inválido. No combinar errores. Validación determinista antes
  de ejecutar cambios.

- Q: ¿Qué devuelve POST /deactivate si el UUID es inválido? → A: 422
  VALIDATION_ERROR sin consultar BD. 404 si no existe. 200 si activo
  (cambia a false) o ya inactivo (sin cambio). Idempotente. No bloquear
  por expedientes. No usar EMPLOYEE_ALREADY_INACTIVE.

- Q: ¿Qué devuelve PATCH /employees/{id} si el UUID es inválido? → A: 422
  VALIDATION_ERROR sin consultar BD. 404 si no existe. 422 si body vacío
  o campos desconocidos. 200 con EmployeeResponse si exitoso. Validar
  path primero, luego body.

- Q: ¿Qué devuelve PATCH /case-files/{id} si el UUID es inválido? → A: 422
  VALIDATION_ERROR sin consultar BD. 404 si no existe. 409 si archived.
  409 si expected_version no coincide. 422 si body vacío o campos
  desconocidos. 200 con CaseFileResponse si exitoso.

- Q: ¿Qué devuelve GET /case-files/{id} si el UUID es inválido? → A: 422
  VALIDATION_ERROR. 404 si no existe. 200 con CaseFileResponse si existe.
  Misma convención uniforme para todos los endpoints con UUID.

- Q: ¿Qué devuelven los endpoints de listado si los query params son
  inválidos? → A: 422 VALIDATION_ERROR. No ejecutar consulta, no ignorar
  params, no reemplazar por defaults. 200 si todo es válido (incluso con
  items=[]).

- Q: ¿Qué devuelve POST /case-files si employee_id es UUID inválido? → A:
  422 VALIDATION_ERROR sin consultar BD. 404 si no existe. 422 si
  inactivo. 201 si exitoso. No tratar UUID inválido como inexistente.

- Q: ¿Qué formato usa VALIDATION_ERROR? → A: Objeto con error_code,
  message, errors (array de objetos con field, code, message), request_id.
  Devolver todos los errores determinísticos. Orden estable. No incluir
  valores sensibles. Campos desconocidos → code="extra_forbidden".
  Conflictos de unicidad → 409 separados.

- Q: ¿Qué devuelve un endpoint si el body está vacío? → A: 422 con lista
  de errores para campos obligatorios faltantes. PATCH sin campos → error
  "at_least_one_field_required". No error genérico. No valores por defecto.
  No consultar BD si validación ya falló.

- Q: ¿Se modifican los endpoints de health check? → A: No. Los tres
  endpoints (live, ready, dependencies) permanecen sin cambios. No agregar
  campos de dominio. No crear nuevos health endpoints. Pruebas de regresión
  obligatorias.

- Q: ¿Qué verifica health/ready? → A: Conexión PostgreSQL + pgvector. No
  verifica tablas de negocio, presencia de datos ni funcionamiento de
  endpoints. Las tablas se validan con Alembic y pruebas de migración.

- Q: ¿Qué devuelve health/ready si PostgreSQL no está disponible? → A: HTTP
  503 con status="not_ready". Mismo schema del incremento 001. No agregar
  campos nuevos. Info detallada va en /health/dependencies.

- Q: ¿Qué valor usa changed_by en el historial inicial de creación? → A:
  `"system"` (constante técnica). No se recibe en CaseFileCreateRequest.
  No inferir usuario. No usar datos personales. La identidad autenticada
  reemplazará este valor en un incremento futuro.

- Q: ¿Qué valores tiene case_type? → A: StrEnum fijo con cinco valores:
  `designacion`, `licencia`, `renuncia`, `contratacion`, `otro`. No es
 modifiable. No hay endpoint de administración de tipos.
