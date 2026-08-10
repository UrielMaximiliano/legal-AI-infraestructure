# Contrato HTTP — RAG Jurídico 006

## POST `/api/v1/rag/drafts/generate`

Genera un borrador jurídico asistido por recuperación. No reemplaza `POST /api/v1/drafts/generate`.

### Headers

| Header | Requerido | Regla |
|---|---|---|
| `Idempotency-Key` | Sí | 16–128 caracteres; nunca se persiste en claro |
| `X-Request-ID` | No | Si falta, el backend genera uno; máximo 128 caracteres |

### Request

```json
{
  "template_id": "uuid",
  "case_file_id": "uuid",
  "variables": {
    "cargo": "...",
    "organismo": "..."
  },
  "retrieval": {
    "top_k": 8,
    "minimum_score": 0.0,
    "organization": null,
    "language": "es"
  }
}
```

Reglas:

- `template_id` y `case_file_id` obligatorios.
- `variables` admite solo claves declaradas por la plantilla y valores escalares textuales acotados.
- `top_k`: 3..20, default 8.
- Los filtros de tipo, subtipo, jurisdicción, revisión y split no son controlables por el cliente: el servidor fija decreto/designación transitoria/nación/REVIEWED/INDEX_90.
- Campos desconocidos son rechazados.
- Query, prompt, raw content, normalized content, embeddings, tokens, Authorization y rutas no son campos aceptados.

### Response `201 Created`

```json
{
  "request_id": "correlation-id",
  "rag_run_id": "uuid",
  "draft": {
    "id": "uuid",
    "template_id": "uuid",
    "case_file_id": "uuid",
    "title": "Borrador asistido — Decreto",
    "content": "representación determinista para revisión",
    "status": "PENDING_REVIEW",
    "version": 1,
    "created_at": "2026-08-07T12:00:00Z",
    "updated_at": "2026-08-07T12:00:00Z"
  },
  "structured_draft": {
    "schema_version": 1,
    "title": "...",
    "visto": [{"text": "...", "citation_ids": ["SRC-001"]}],
    "considerandos": [{"text": "...", "citation_ids": ["SRC-001"]}],
    "dispositive_intro": "Por ello...",
    "articles": [{"number": 1, "text": "...", "citation_ids": ["SRC-002"]}],
    "closing": "Comuníquese...",
    "authority": "...",
    "signature": "PENDIENTE DE FIRMA",
    "sources": [
      {
        "citation_id": "SRC-001",
        "external_id": "12345",
        "title": "Decreto ...",
        "publication_date": "2025-01-01",
        "section_type": "CONSIDERANDO",
        "source_url": "https://..."
      }
    ],
    "warnings": ["BORRADOR NO VINCULANTE — REQUIERE REVISIÓN HUMANA"]
  },
  "retrieval": {
    "result_count": 8,
    "selected_count": 6,
    "embedding_model": "qwen3-embedding:4b-q4_K_M",
    "embedding_dimensions": 2560
  },
  "generation": {
    "model": "qwen3.6:35b",
    "prompt_version": "rag-decree-v1",
    "schema_version": 1
  }
}
```

La respuesta no incluye embeddings, query completa, prompt, texto completo de fuentes, reasoning ni información de autenticación.

### Idempotencia

- Misma key + mismo hash + run exitoso: devuelve el mismo resultado, sin nueva inferencia.
- Misma key + mismo hash + run activo: `409 RAG_GENERATION_IN_PROGRESS`.
- Misma key + hash distinto: `409 RAG_IDEMPOTENCY_KEY_MISMATCH`.
- Run fallido: puede reintentarse con una nueva key; la evidencia del fallo permanece.

### Errores

| HTTP | Código | Semántica |
|---|---|---|
| 400 | `RAG_INVALID_REQUEST` | Payload semánticamente inválido |
| 404 | `CASE_FILE_NOT_FOUND` | Expediente inexistente |
| 404 | `DOCUMENT_TEMPLATE_NOT_FOUND` | Plantilla inexistente |
| 409 | `DOCUMENT_TEMPLATE_INACTIVE` | Plantilla desactivada |
| 409 | `RAG_GENERATION_IN_PROGRESS` | Mismo trabajo ya en ejecución |
| 409 | `RAG_IDEMPOTENCY_KEY_MISMATCH` | Key reutilizada con otro payload |
| 422 | `MISSING_REQUIRED_VARIABLES` | Variables requeridas ausentes |
| 422 | `RAG_INSUFFICIENT_EVIDENCE` | No existen fuentes suficientes |
| 422 | `RAG_OUTPUT_INVALID` | Schema o reglas de citas inválidos después de reparación |
| 503 | `SEMANTIC_SEARCH_AUDIT_UNAVAILABLE` | Auditoría de recuperación no persistible |
| 503 | `RAG_AUDIT_UNAVAILABLE` | Auditoría/generación no persistible |
| 503 | `OLLAMA_UNAVAILABLE` | Proveedor no disponible |
| 504 | `OLLAMA_TIMEOUT` | Timeout acotado |

Envelope:

```json
{
  "error": {
    "code": "RAG_INSUFFICIENT_EVIDENCE",
    "message": "No hay antecedentes revisados suficientes para generar el borrador.",
    "request_id": "correlation-id"
  }
}
```

No se devuelven errores upstream, stack traces ni fragmentos de entrada.

## GET `/api/v1/rag/runs/{run_id}`

Devuelve trazabilidad sanitizada para un actor autorizado.

### Response `200 OK`

```json
{
  "id": "uuid",
  "draft_id": "uuid-or-null",
  "case_file_id": "uuid",
  "template_id": "uuid",
  "status": "SUCCEEDED",
  "models": {
    "embedding": "qwen3-embedding:4b-q4_K_M",
    "dimensions": 2560,
    "generation": "qwen3.6:35b"
  },
  "versions": {"prompt": "rag-decree-v1", "schema": 1},
  "retrieval": {"retrieved": 24, "selected": 8},
  "durations_ms": {
    "retrieval": 120,
    "generation": 8400,
    "validation": 8,
    "total": 8600
  },
  "sources": [
    {
      "citation_id": "SRC-001",
      "document_id": "uuid",
      "chunk_id": "uuid",
      "rank": 1,
      "score": 0.8123456,
      "disposition": "SELECTED"
    }
  ],
  "error_code": null,
  "request_id": "correlation-id",
  "created_at": "2026-08-07T12:00:00Z",
  "finished_at": "2026-08-07T12:00:09Z"
}
```

No devuelve hashes internos, query, prompt, contexto ni contenido documental.

## Readiness

La respuesta de readiness existente agrega un componente `rag_generation`:

```json
{
  "rag_generation": {
    "status": "ready|degraded|unavailable",
    "generation_model": "qwen3.6:35b",
    "embedding_model": "qwen3-embedding:4b-q4_K_M",
    "dimensions": 2560,
    "eligible_reviewed_documents": 1234,
    "error_code": null
  }
}
```

El probe no envía documentos reales ni crea borradores.
