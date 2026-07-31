# Contrato: GET /health/ready

**Endpoint**: `GET /health/ready`
**Propósito**: Indicar si la aplicación está preparada para atender operaciones
**Dependencias consultadas**: PostgreSQL, pgvector, Ollama

## Descripción

Endpoint de readiness que verifica si la aplicación está preparada para
atender operaciones que requieren sus dependencias obligatorias. Consulta
PostgreSQL, pgvector y Ollama. Retorna HTTP 200 cuando todas las dependencias
están disponibles, o HTTP 503 cuando alguna falla.

## Respuesta Exitosa (ready)

**Código HTTP**: `200`

```json
{
  "status": "ready",
  "timestamp": "2026-07-31T15:00:00Z",
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

## Respuesta de No Preparado (not_ready)

**Código HTTP**: `503`

```json
{
  "status": "not_ready",
  "timestamp": "2026-07-31T15:00:00Z",
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Campos

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `status` | string | sí | `ready`, `degraded` o `not_ready` |
| `timestamp` | string | sí | Fecha UTC en formato ISO 8601 |
| `request_id` | string | sí | UUID v4 de correlación |

### Estados

| Estado | Código HTTP | Significado |
|---|---|---|
| `ready` | 200 | Todas las dependencias obligatorias disponibles |
| `degraded` | 200 | Reservado para futuro (dependencia opcional falla) |
| `not_ready` | 503 | Alguna dependencia obligatoria falla |

### Dependencias Evaluadas

| Dependencia | Obligatoria | Condición not_ready |
|---|---|---|
| PostgreSQL | sí | Conexión fallida |
| pgvector | sí | Extensión ausente |
| Ollama | sí | Endpoint inaccesible, timeout, no autorizado o prohibido |
| Configuración | sí | Variables requeridas faltantes o inválidas |

## Headers

| Header | Dirección | Descripción |
|---|---|---|
| `X-Request-ID` | ambos | Identificador de correlación |
| `Content-Type` | respuesta | `application/json` |

## Errores

| Código HTTP | error_code | Descripción |
|---|---|---|
| 503 | `POSTGRES_UNAVAILABLE` | PostgreSQL no accesible |
| 503 | `PGVECTOR_MISSING` | Extensión pgvector ausente |
| 503 | `OLLAMA_UNAVAILABLE` | Ollama no accesible |
| 503 | `OLLAMA_TIMEOUT` | Timeout al conectar con Ollama |
| 503 | `OLLAMA_UNAUTHORIZED` | Token de autenticación inválido o ausente |
| 503 | `OLLAMA_FORBIDDEN` | Token válido pero sin permisos |
| 503 | `OLLAMA_MISCONFIGURED` | Configuración de Ollama inválida |
| 503 | `CONFIGURATION_INVALID` | Configuración de aplicación inválida |
| 500 | `INTERNAL_DIAGNOSTIC_ERROR` | Error interno no controlado |

## Ejemplos de Curl

```bash
# Verificar readiness
curl http://localhost:8000/health/ready

# Verificar con verbose
curl -v http://localhost:8000/health/ready
```
