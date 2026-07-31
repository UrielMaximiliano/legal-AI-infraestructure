# Modelo de Datos: Base Local y Verificación de Dependencias

**Feature**: `001-local-base-dependencies`
**Fecha**: 2026-07-31
**Estado**: Completo

## Estructuras de Configuración

### AppConfig

Configuración principal de la aplicación.

| Campo | Tipo | Requerido | Default | Descripción |
|---|---|---|---|---|
| `APP_ENV` | str | sí | `development` | Entorno de ejecución |
| `APP_NAME` | str | sí | `legal-ai-api` | Nombre del servicio |
| `APP_VERSION` | str | sí | `0.1.0` | Versión de la aplicación |
| `API_HOST` | str | sí | `0.0.0.0` | Host del servidor |
| `API_PORT` | int | sí | `8000` | Puerto del servidor |
| `LOG_LEVEL` | str | sí | `INFO` | Nivel de logging |

### PostgreSQLConfig

Configuración de conexión a PostgreSQL.

| Campo | Tipo | Requerido | Default | Descripción |
|---|---|---|---|---|
| `POSTGRES_HOST` | str | sí | `postgres` | Host de PostgreSQL |
| `POSTGRES_PORT` | int | sí | `5432` | Puerto de PostgreSQL |
| `POSTGRES_DB` | str | sí | `legal_ai` | Nombre de la base |
| `POSTGRES_USER` | str | sí | `legal_ai` | Usuario de conexión |
| `POSTGRES_PASSWORD` | str | sí | `change-me` | Contraseña |

**Campo derivado**: `DATABASE_URL` se construye internamente como
`postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}`.

### OllamaConfig

Configuración de conexión a Ollama.

| Campo | Tipo | Requerido | Default | Descripción |
|---|---|---|---|---|
| `OLLAMA_BASE_URL` | str | sí | — | Endpoint de Ollama (obligatorio, sin default) |
| `OLLAMA_API_TOKEN` | str | sí | — | Token Bearer para autenticación (obligatorio, sin default) |
| `OLLAMA_TIMEOUT_SECONDS` | int | sí | `5` | Timeout en segundos |

**Restricciones**:
- `OLLAMA_TIMEOUT_SECONDS` debe ser > 0 y <= 30.
- `OLLAMA_BASE_URL` debe usar esquema `http` o `https`.
- `OLLAMA_API_TOKEN` debe llegar mediante variable de entorno o secret.
- `OLLAMA_API_TOKEN` no debe incluirse en imágenes Docker ni exponerse en errores.

## Modelos de Salud

### HealthStatus (estados individuales)

Enumeración de estados posibles para una dependencia.

```
ok | unavailable | timeout | misconfigured | invalid_response | missing | unauthorized | forbidden | rate_limited
```

### ReadinessStatus (estados generales de readiness)

Enumeración de estados generales de readiness para `/health/ready`.

```
ready | degraded | not_ready
```

### AggregateStatus (estados agregados de diagnóstico)

Enumeración de estados agregados para `/health/dependencies`.

```
ok | partial | error
```

- `ok`: todas las dependencias disponibles.
- `partial`: diagnóstico completado con una o más dependencias fallidas.
- `error`: fallo interno del mecanismo de diagnóstico.

### DependencyHealth

Resultado de la verificación de una dependencia individual.

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `status` | HealthStatus | sí | Estado de la dependencia |
| `latency_ms` | float \| null | no | Tiempo de respuesta en ms |
| `error_code` | str \| null | no | Código de error sanitizado |
| `message` | str \| null | no | Mensaje técnico breve |

### HealthDependenciesResponse

Respuesta completa del endpoint `/health/dependencies`.

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `status` | AggregateStatus | sí | Estado agregado: `ok`, `partial`, `error` |
| `timestamp` | str | sí | Fecha UTC ISO 8601 |
| `request_id` | str | sí | Identificador de correlación |
| `dependencies.postgres` | DependencyHealth | sí | Estado de PostgreSQL |
| `dependencies.pgvector` | DependencyHealth | sí | Estado de pgvector |
| `dependencies.ollama` | DependencyHealth | sí | Estado de Ollama |

### HealthLiveResponse

Respuesta del endpoint `/health/live`.

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `status` | str | sí | Siempre `"ok"` |
| `service` | str | sí | Nombre del servicio |
| `version` | str | sí | Versión de la aplicación |
| `request_id` | str | sí | Identificador de correlación |

### HealthReadyResponse

Respuesta del endpoint `/health/ready`.

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `status` | ReadinessStatus | sí | Estado general |
| `timestamp` | str | sí | Fecha UTC ISO 8601 |
| `request_id` | str | sí | Identificador de correlación |

## Códigos de Error

| Código | Descripción |
|---|---|
| `POSTGRES_UNAVAILABLE` | PostgreSQL no accesible |
| `POSTGRES_QUERY_FAILED` | Consulta a PostgreSQL falló |
| `PGVECTOR_MISSING` | Extensión pgvector no instalada |
| `PGVECTOR_CHECK_FAILED` | Verificación de pgvector falló |
| `OLLAMA_UNAVAILABLE` | Ollama no accesible |
| `OLLAMA_TIMEOUT` | Timeout al conectar con Ollama |
| `OLLAMA_INVALID_RESPONSE` | Respuesta de Ollama no válida |
| `OLLAMA_MISCONFIGURED` | Configuración de Ollama inválida |
| `OLLAMA_UNAUTHORIZED` | Token de autenticación inválido o ausente |
| `OLLAMA_FORBIDDEN` | Token válido pero sin permisos |
| `OLLAMA_RATE_LIMITED` | Límite de tasa excedido |
| `OLLAMA_ENDPOINT_NOT_FOUND` | Endpoint no encontrado (HTTP 404) |
| `CONFIGURATION_INVALID` | Configuración de la aplicación inválida |
| `INTERNAL_DIAGNOSTIC_ERROR` | Error interno del diagnóstico |

## Transiciones de Estado

### Readiness General

```
[init] → not_ready
not_ready → ready (todas las dependencias OK)
ready → not_ready (alguna dependencia obligatoria falla)
```

Nota: `degraded` queda reservado para capacidades futuras donde una
dependencia opcional pueda fallar sin impedir la operación principal.

### Diagnóstico Agregado

```
[unchecked] → ok (todas las dependencias OK)
[unchecked] → partial (una o más dependencias fallidas)
[unchecked] → error (fallo interno del diagnóstico)
```

### Dependencia Individual

```
[unchecked] → ok
[unchecked] → unavailable
[unchecked] → timeout
[unchecked] → misconfigured
[unchecked] → invalid_response
[unchecked] → missing (solo pgvector)
[unchecked] → unauthorized (solo Ollama)
[unchecked] → forbidden (solo Ollama)
[unchecked] → rate_limited (solo Ollama)
```
