# Contrato: GET /health/dependencies

**Endpoint**: `GET /health/dependencies`
**Propósito**: Exponer diagnóstico individual de cada dependencia
**Dependencias consultadas**: PostgreSQL, pgvector, Ollama

## Descripción

Endpoint de diagnóstico que ejecuta y muestra el estado individual de
PostgreSQL, pgvector y Ollama. Responde HTTP 200 siempre que el mecanismo
de diagnóstico se complete, aunque alguna dependencia esté caída. Solo
responde HTTP 500 ante un error interno no controlado del propio diagnóstico.

## Respuesta Exitosa

**Código HTTP**: `200`

```json
{
  "status": "ok",
  "timestamp": "2026-07-31T15:00:00Z",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "dependencies": {
    "postgres": {
      "status": "ok",
      "latency_ms": 8.5,
      "error_code": null,
      "message": null
    },
    "pgvector": {
      "status": "ok",
      "latency_ms": 2.1,
      "error_code": null,
      "message": null
    },
    "ollama": {
      "status": "ok",
      "latency_ms": 31.4,
      "error_code": null,
      "message": null
    }
  }
}
```

## Respuesta con Dependencias Parcialmente Caídas

**Código HTTP**: `200`

```json
{
  "status": "partial",
  "timestamp": "2026-07-31T15:00:00Z",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "dependencies": {
    "postgres": {
      "status": "ok",
      "latency_ms": 8.5,
      "error_code": null,
      "message": null
    },
    "pgvector": {
      "status": "ok",
      "latency_ms": 2.1,
      "error_code": null,
      "message": null
    },
    "ollama": {
      "status": "timeout",
      "latency_ms": 5000.0,
      "error_code": "OLLAMA_TIMEOUT",
      "message": "Timeout al conectar con Ollama"
    }
  }
}
```

## Respuesta con pgvector Ausente

**Código HTTP**: `200`

```json
{
  "status": "partial",
  "timestamp": "2026-07-31T15:00:00Z",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "dependencies": {
    "postgres": {
      "status": "ok",
      "latency_ms": 8.5,
      "error_code": null,
      "message": null
    },
    "pgvector": {
      "status": "missing",
      "latency_ms": null,
      "error_code": "PGVECTOR_MISSING",
      "message": "Extensión pgvector no instalada"
    },
    "ollama": {
      "status": "ok",
      "latency_ms": 31.4,
      "error_code": null,
      "message": null
    }
  }
}
```

### Campos Raíz

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `status` | string | sí | Estado agregado: `ok`, `partial`, `error` |
| `timestamp` | string | sí | Fecha UTC en formato ISO 8601 |
| `request_id` | string | sí | UUID v4 de correlación |
| `dependencies` | object | sí | Mapa de dependencias |

### Campos de Dependencia

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `status` | string | sí | Estado individual (ver tabla) |
| `latency_ms` | number \| null | no | Tiempo de respuesta en milisegundos |
| `error_code` | string \| null | no | Código de error estable |
| `message` | string \| null | no | Mensaje técnico breve sin secretos |

### Estados Individuales

| Estado | Latencia | Significado |
|---|---|---|
| `ok` | sí | Dependencia funcionando correctamente |
| `unavailable` | no | Conexión rechazada o no disponible |
| `timeout` | sí | Timeout al conectar |
| `misconfigured` | no | Configuración inválida |
| `invalid_response` | no | Respuesta HTTP no válida o JSON inválido |
| `missing` | no | Extensión ausente (solo pgvector) |
| `unauthorized` | no | Token de autenticación inválido o ausente (solo Ollama) |
| `forbidden` | no | Token válido pero sin permisos (solo Ollama) |
| `rate_limited` | no | Límite de tasa excedido (solo Ollama) |

### Códigos de Error

| error_code | Dependencia | Significado |
|---|---|---|
| `POSTGRES_UNAVAILABLE` | postgres | PostgreSQL no accesible |
| `POSTGRES_QUERY_FAILED` | postgres | Consulta falló |
| `PGVECTOR_MISSING` | pgvector | Extensión no instalada |
| `PGVECTOR_CHECK_FAILED` | pgvector | Verificación falló |
| `OLLAMA_UNAVAILABLE` | ollama | Ollama no accesible |
| `OLLAMA_TIMEOUT` | ollama | Timeout al conectar |
| `OLLAMA_INVALID_RESPONSE` | ollama | Respuesta no válida |
| `OLLAMA_MISCONFIGURED` | ollama | URL inválida o no configurada |
| `OLLAMA_UNAUTHORIZED` | ollama | Token inválido o ausente |
| `OLLAMA_FORBIDDEN` | ollama | Token válido sin permisos |
| `OLLAMA_RATE_LIMITED` | ollama | Límite de tasa excedido |
| `OLLAMA_ENDPOINT_NOT_FOUND` | ollama | Endpoint no encontrado (404) |
| `INTERNAL_DIAGNOSTIC_ERROR` | (general) | Error interno del diagnóstico |

## Headers

| Header | Dirección | Descripción |
|---|---|---|
| `X-Request-ID` | ambos | Identificador de correlación |
| `Content-Type` | respuesta | `application/json` |

## Errores

| Código HTTP | error_code | Descripción |
|---|---|---|
| 200 | (varios) | Diagnóstico completado con éxitos parciales |
| 500 | `INTERNAL_DIAGNOSTIC_ERROR` | Error interno no controlado del diagnóstico |

## Ejemplos de Curl

```bash
# Diagnóstico completo
curl http://localhost:8000/health/dependencies

# Con request ID específico
curl -H "X-Request-ID: diag-123" http://localhost:8000/health/dependencies

# Formateado con jq
curl -s http://localhost:8000/health/dependencies | jq
```
