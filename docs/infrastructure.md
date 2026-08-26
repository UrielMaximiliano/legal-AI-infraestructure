# Infraestructura de Legal AI

## Idea central

El proyecto es una API modular para gestionar expedientes y borradores jurídicos,
buscar normativa por similitud semántica y generar borradores asistidos por RAG.

La ejecución local vive en Docker:

1. `api` expone FastAPI en `:8000`.
2. `postgres` guarda el dominio, los documentos, los chunks y los vectores.
3. Ollama aporta embeddings y generación estructurada desde fuera del contenedor.
4. Un volumen local conserva los DOCX/PDF exportados.

### Mapa visual

- [Arquitectura de runtime](diagrams/legal-ai-architecture.html)
- [Flujo de ingesta, búsqueda y RAG](diagrams/rag-pipeline.html)

## Cómo funciona

### 1. API y dominio

`legal_ai.main` crea la aplicación FastAPI, registra routers, middleware de
seguridad/request-id y handlers de errores. Las rutas llaman servicios de
aplicación; éstos usan el dominio y repositorios SQLAlchemy a través de un
`UnitOfWork`.

Sirve para mantener separadas las decisiones de negocio de HTTP y PostgreSQL.

Código clave: [`main.py`](../apps/api/src/legal_ai/main.py),
[`router.py`](../apps/api/src/legal_ai/api/router.py) y
[`unit_of_work.py`](../apps/api/src/legal_ai/adapters/database/unit_of_work.py).

### 2. Datos transaccionales y vectoriales

PostgreSQL concentra dos responsabilidades:

- entidades del producto: empleados, expedientes, templates, drafts, revisiones,
  intentos de generación y exportaciones;
- corpus RAG: documentos, chunks, estados de ingesta, embeddings y auditoría de
  búsquedas.

`pgvector` permite calcular distancia coseno dentro de la misma base. El índice
  operativo sólo considera chunks `ACTIVE` y documentos `REVIEWED`; RAG además
  exige la partición `INDEX_90`.

La conexión es asíncrona, con pool conservador (`pool_size=5`,
`max_overflow=10`) y migraciones gestionadas por Alembic.

Código clave: [`engine.py`](../apps/api/src/legal_ai/adapters/database/engine.py),
[`pgvector_search.py`](../apps/api/src/legal_ai/adapters/database/pgvector_search.py)
y [`alembic/`](../apps/api/alembic/).

### 3. Ingesta y búsqueda semántica

El comando `corpus ingest` empieza en dry-run. Sólo con `--execute` escribe en
PostgreSQL y solicita embeddings. El flujo crea una generación `STAGED`, valida
los vectores y hace el swap a `ACTIVE` de forma atómica.

La ruta `POST /api/v1/semantic-search` embebe la consulta, aplica filtros permitidos y
devuelve resultados sanitizados. Los filtros inválidos fallan cerrado.

Para operar corpus:

```bash
corpus ingest ./corpus
corpus ingest ./corpus --execute --run-id <opaque-run-id>
corpus reindex --document-id <uuid> --execute --run-id <opaque-run-id>
```

Código clave: [`corpus.py`](../apps/api/src/legal_ai/cli/corpus.py),
[`corpus_activation.py`](../apps/api/src/legal_ai/application/corpus_activation.py)
y [`semantic_search.py`](../apps/api/src/legal_ai/api/routes/semantic_search.py).

### 4. RAG y generación

`POST /api/v1/rag/drafts/generate` combina cuatro pasos:

1. construye la consulta jurídica;
2. recupera chunks elegibles desde pgvector;
3. arma contexto con citas `SRC-NNN`;
4. llama a Ollama con JSON Schema y crea un draft pendiente de revisión humana.

Ollama se separa en dos usos:

- embeddings: `qwen3-embedding:4b-q4_K_M`, 2.560 dimensiones, `/api/embed`;
- generación: `qwen3.6:35b`, `/api/chat`, `stream=false` y salida estructurada.

El draft no se aprueba ni exporta automáticamente: la revisión humana sigue
siendo obligatoria.

Código clave: [`rag_generation.py`](../apps/api/src/legal_ai/application/rag_generation.py),
[`rag_retrieval.py`](../apps/api/src/legal_ai/application/rag_retrieval.py),
[`structured_generation.py`](../apps/api/src/legal_ai/adapters/ollama/structured_generation.py)
y [`ollama_embedding.py`](../apps/api/src/legal_ai/adapters/ollama_embedding.py).

### 5. Revisión y exportación

El ciclo de documentos es:

`case file → draft → review → approve/finalize → DOCX/PDF`.

Los artefactos se escriben bajo `EXPORT_STORAGE_ROOT` en un volumen local. Las
descargas verifican MIME, estructura y SHA-256 antes de hacer streaming.

## Operación mínima

| Necesidad | Dónde mirar |
|---|---|
| Arrancar servicios | [`compose.yaml`](../compose.yaml) |
| Migrar base | `apps/api/alembic` + `alembic.ini` |
| Liveness | `GET /health/live` |
| Readiness | `GET /health/ready` |
| Dependencias | `GET /health/dependencies` |
| Reindexar corpus | [`docs/runbooks/corpus-reindex.md`](runbooks/corpus-reindex.md) |
| Embeddings | [`docs/runbooks/ollama-embeddings.md`](runbooks/ollama-embeddings.md) |
| Operar RAG | [`docs/runbooks/rag-operations.md`](runbooks/rag-operations.md) |

La readiness depende de PostgreSQL, `pgvector` y Ollama. Al apagar la API, el
lifespan cierra el coordinador RAG.

## Límites importantes

- No hay Redis, colas ni scheduler implícitos: el despliegue actual es API +
  PostgreSQL + Ollama externo + volumen de exportaciones.
- Los tokens de Ollama sólo llegan por variables de entorno y no deben aparecer
  en logs.
- Los prompts, vectores, documentos completos y credenciales no forman parte de
  las respuestas públicas del RAG.

## Referencias técnicas

- [FastAPI: lifespan y middleware](https://fastapi.tiangolo.com/advanced/events/)
- [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Ollama API](https://github.com/ollama/ollama/blob/main/docs/api.md)
