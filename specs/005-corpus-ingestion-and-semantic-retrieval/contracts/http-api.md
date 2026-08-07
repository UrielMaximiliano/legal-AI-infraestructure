# Contrato HTTP — Semantic Search 005

**Status**: `IMPLEMENTATION_EXTERNAL_GATE_CLOSED`

## POST `/api/v1/semantic-search`

Endpoint interno/administrativo. JSON, timeout configurable y envelope existente.

### Request

```json
{
  "query": "designación transitoria de director por vacancia",
  "filters": {
    "document_type": "decreto",
    "document_subtype": "designacion_transitoria",
    "jurisdiction": "nacion"
  },
  "top_k": 10,
  "minimum_score": 0.0
}
```

La API acepta también los tres filtros MVP como campos de primer nivel para
compatibilidad con el CLI y clientes existentes; si se envía el objeto
`filters`, no puede contradecir esos mismos campos.

Reglas: query no vacía y acotada. `document_type=decreto`,
`document_subtype=designacion_transitoria` y `jurisdiction=nacion` son filtros MVP
obligatorios. `language=es` y `organization` son opcionales; `review_status` se
normaliza a `REVIEWED` por defecto. `top_k` es opcional entre 1 y
`SEMANTIC_SEARCH_MAX_TOP_K`; `minimum_score` es opcional entre 0 y 1. Campos extra,
valores no escalares, vacíos, no finitos, demasiado largos o sensibles se rechazan
fail-closed con `INVALID_SEMANTIC_SEARCH_FILTERS`. Incluir `PENDING_REVIEW` requiere
evaluación administrativa explícita y nunca incluye `REJECTED`.

### Success 200

```json
{
  "data": {
    "query_id": "uuid",
    "results": [
      {
        "chunk_id": "uuid",
        "document_id": "uuid",
        "external_id": "BO-123",
        "title": "Decreto ...",
        "section_type": "CONSIDERANDO",
        "section_index": 3,
        "article_number": null,
        "excerpt": "...",
        "similarity_score": 0.82,
        "publication_date": "2025-01-20",
        "source_name": "Boletín Oficial de la República Argentina",
        "source_url": null,
        "organization": null,
        "metadata": {},
        "embedding_model": "qwen3-embedding:4b-q4_K_M",
        "embedding_dimensions": 2560
      }
    ]
  },
  "request_id": "uuid"
}
```

El modelo contractual es `qwen3-embedding:4b-q4_K_M` y la dimensión contractual es
2560. Cualquier respuesta con otra dimensión falla antes de buscar. Resultado
vacío es `results: []` con 200.

Orden: score DESC, publication_date DESC NULLS LAST, document_id ASC,
section_index ASC. Score: `clamp(1 - cosine_distance, 0, 1)`.

### Datos prohibidos

Embedding, query normalizada, contenido completo, raw content, path, token,
Authorization, metadata sensible y stack trace.

Los DTOs públicos son allowlist y se construyen mediante mappers explícitos; nunca
serializan ORM. `raw_content` y `normalized_content` completo no pertenecen a ningún
schema público, excepción, métrica o log. Todo excerpt proviene de `corpus_chunks`
y respeta el límite contractual. 005 no ofrece endpoint de descarga del original.

## Errores

Reutilizar exactamente el envelope público vigente con `request_id` y timestamp.

| HTTP | Código | Condición |
|---:|---|---|
| 422 | `VALIDATION_ERROR` | Shape, query, top_k o score inválido |
| 422 | `INVALID_SEMANTIC_SEARCH_FILTERS` | Filtros ausentes/no permitidos |
| 409 | `EMBEDDING_DIMENSION_MISMATCH` | Vector de query incompatible |
| 503 | `EMBEDDING_PROVIDER_UNAVAILABLE` | Ollama no disponible |
| 503 | `SEMANTIC_INDEX_INCOMPATIBLE` | Modelo/dimensión/índice incompatibles |
| 503 | `DATABASE_ERROR` | Persistencia/búsqueda no disponible |
| 503 | `SEMANTIC_SEARCH_AUDIT_UNAVAILABLE` | No pudo confirmarse la auditoría obligatoria |
| 504 | `SEMANTIC_SEARCH_TIMEOUT` | Deadline global excedido |

La fila minimizada de `semantic_search_runs` solo usa los estados `SUCCEEDED` y
`FAILED`; un timeout se registra como `FAILED` con
`SEMANTIC_SEARCH_TIMEOUT`, y `request_id` siempre es obligatorio. La tabla no tiene
FK a resultados; las FK de documentos/chunks evaluados pertenecen a
`human_retrieval_evaluations`.

Política fail-closed: generar embedding, buscar y preparar resultados; después
persistir y confirmar `semantic_search_runs`; solo entonces responder. Una falla o
timeout de auditoría no devuelve resultados, responde HTTP 503 con
`SEMANTIC_SEARCH_AUDIT_UNAVAILABLE`, mensaje sanitizado, `request_id` y timestamp.
Puede realizarse como máximo un retry acotado ante un error claramente transitorio;
no hay retry indefinido ni transacción DB abierta durante Ollama. Query, vector,
resultados parciales y contenido nunca se filtran por respuesta o logs.

## Health/readiness

Los endpoints existentes incorporan una capability `semantic_retrieval` con DB,
pgvector, provider, modelo y dimensión. La degradación no altera liveness ni
rompe las capacidades de 001–004.

## Catálogo administrativo de revisión

005 no expone un endpoint HTTP público de revisión, pero conserva equivalencias
para el envelope común: `CORPUS_DOCUMENT_NOT_FOUND` (404),
`CORPUS_REVIEW_VERSION_MISMATCH` (409), `INVALID_CORPUS_REVIEW_TRANSITION` (409),
`CORPUS_REVIEW_REASON_REQUIRED` (422) y `CORPUS_REVIEWER_REQUIRED` (422). Solo el
mismatch admite `expected_version`/`current_version`; nunca contenido o datos sensibles.
