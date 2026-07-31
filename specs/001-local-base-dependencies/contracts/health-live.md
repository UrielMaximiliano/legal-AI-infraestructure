# Contrato: GET /health/live

**Endpoint**: `GET /health/live`
**Propósito**: Indicar que el proceso HTTP está activo
**Dependencias consultadas**: Ninguna

## Descripción

Endpoint de liveness que verifica únicamente que el proceso de la API está
ejecutándose. No consulta PostgreSQL, pgvector ni Ollama. Debe responder
HTTP 200 mientras el proceso pueda atender solicitudes.

## Respuesta Exitosa

**Código HTTP**: `200`

```json
{
  "status": "ok",
  "service": "legal-ai-api",
  "version": "0.1.0",
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Campos

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `status` | string | sí | Siempre `"ok"` |
| `service` | string | sí | Nombre del servicio |
| `version` | string | sí | Versión de la aplicación |
| `request_id` | string | sí | UUID v4 de correlación |

## Headers

| Header | Dirección | Descripción |
|---|---|---|
| `X-Request-ID` | ambos | Identificador de correlación (generado si no se provee) |
| `Content-Type` | respuesta | `application/json` |

## Errores

No produce errores. Si el proceso está vivo, responde siempre HTTP 200.

## Ejemplos de Curl

```bash
# Request básico
curl http://localhost:8000/health/live

# Con request ID específico
curl -H "X-Request-ID: mi-id-123" http://localhost:8000/health/live
```
