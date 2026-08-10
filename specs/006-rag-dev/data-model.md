# Modelo de datos: RAG Jurídico 006

**Migración prevista**: `007_rag_generation_audit.py`
**Base**: esquema Alembic `006`

## Principios

- PostgreSQL sigue siendo fuente de verdad.
- Las tablas 001–006 no se redefinen ni renombran.
- Los prompts y consultas completas no se persisten en las nuevas tablas.
- Los textos recuperados permanecen en `corpus_chunks`; las relaciones guardan IDs, orden y métricas.
- El JSON estructurado validado sí se persiste porque es el borrador generado y debe ser revisable/auditable.
- Todos los nombres de FK, unique, check e índices son explícitos y coinciden en Alembic/ORM.

## Enumeraciones contractuales

### `RagGenerationStatus`

- `PENDING`
- `RETRIEVING`
- `GENERATING`
- `VALIDATING`
- `SUCCEEDED`
- `FAILED`

Transiciones:

```text
PENDING -> RETRIEVING -> GENERATING -> VALIDATING -> SUCCEEDED
   |            |             |            |
   +----------->+------------>+-----------> FAILED
```

`SUCCEEDED` y `FAILED` son terminales. Una transición rechazada no modifica el objeto.

### `RagSourceDisposition`

- `SELECTED`
- `EXCLUDED_BUDGET`
- `EXCLUDED_DIVERSITY`
- `EXCLUDED_SCORE`

### `RagEvaluationMode`

- `FAKE`
- `REAL`
- `HUMAN`

## Tabla `rag_generation_runs`

Una fila por ejecución lógica. Los reintentos de reparación se cuentan dentro del mismo run.

| Campo | Tipo | Reglas |
|---|---|---|
| `id` | UUID | PK |
| `generation_attempt_id` | UUID nullable | FK nombrada a `generation_attempts.id`, `ON DELETE SET NULL` |
| `draft_id` | UUID nullable | FK nombrada a `drafts.id`, `ON DELETE SET NULL`; solo presente en `SUCCEEDED` |
| `case_file_id` | UUID | FK nombrada a `case_files.id`, `ON DELETE RESTRICT` |
| `template_id` | UUID | FK nombrada a `document_templates.id`, `ON DELETE RESTRICT` |
| `idempotency_key_hash` | char(64) nullable | SHA-256 lowercase; nunca guardar la clave original |
| `request_hash` | char(64) | SHA-256 lowercase del request canónico |
| `query_hash` | char(64) | SHA-256 lowercase de la consulta normalizada |
| `context_hash` | char(64) nullable | SHA-256 lowercase del contexto canónico |
| `prompt_hash` | char(64) nullable | SHA-256 lowercase del prompt final |
| `status` | varchar(20) | enum contractual |
| `embedding_model` | varchar(128) | no vacío |
| `embedding_dimensions` | integer | exactamente 2560 |
| `generation_model` | varchar(128) | no vacío; contractual `qwen3.6:35b` |
| `prompt_version` | varchar(64) | no vacío |
| `schema_version` | integer | > 0 |
| `top_k` | integer | 3..20 |
| `candidate_pool_size` | integer | `top_k..50` |
| `minimum_score` | numeric(6,5) nullable | 0..1 |
| `retrieved_count` | integer | >= 0 |
| `selected_count` | integer | >= 0 y <= retrieved_count |
| `context_bytes` | integer | >= 0 |
| `context_tokens_estimate` | integer | >= 0 |
| `schema_repair_count` | integer | 0..1 |
| `retrieval_duration_ms` | integer nullable | >= 0 |
| `generation_duration_ms` | integer nullable | >= 0 |
| `validation_duration_ms` | integer nullable | >= 0 |
| `total_duration_ms` | integer nullable | >= 0 |
| `error_code` | varchar(80) nullable | requerido solo en `FAILED`; allowlist sanitizada |
| `request_id` | varchar(128) | no vacío; correlación |
| `created_at` | timestamptz | NOT NULL, server default now |
| `updated_at` | timestamptz | NOT NULL, server default now |
| `finished_at` | timestamptz nullable | requerido en terminales |

Constraints:

- Todos los hashes cumplen `^[0-9a-f]{64}$` cuando no son NULL.
- `SUCCEEDED` exige `draft_id`, `context_hash`, `prompt_hash`, `finished_at`, `selected_count > 0` y `error_code IS NULL`.
- `FAILED` exige `finished_at`, `error_code` no vacío y `draft_id IS NULL`.
- Estados no terminales exigen `finished_at IS NULL` y `draft_id IS NULL`.
- `selected_count <= retrieved_count`.
- Unique parcial `uq_rag_runs_idempotency_active` sobre `idempotency_key_hash` donde hash no sea NULL y status no sea FAILED. La validación de payload ocurre antes de reutilizar.

Índices:

- `ix_rag_runs_case_created(case_file_id, created_at DESC)`.
- `ix_rag_runs_status_created(status, created_at)`.
- `ix_rag_runs_request_id(request_id)`.

## Tabla `rag_retrieved_sources`

Registra todos los candidatos evaluados y su disposición, sin copiar contenido.

| Campo | Tipo | Reglas |
|---|---|---|
| `id` | UUID | PK |
| `run_id` | UUID | FK nombrada a `rag_generation_runs.id`, `ON DELETE CASCADE` |
| `document_id` | UUID | FK nombrada a `corpus_documents.id`, `ON DELETE RESTRICT` |
| `chunk_id` | UUID | FK nombrada a `corpus_chunks.id`, `ON DELETE RESTRICT` |
| `citation_id` | varchar(32) | formato `SRC-001`; único por run |
| `retrieval_rank` | integer | > 0; único por run |
| `context_rank` | integer nullable | > 0; único por run cuando existe |
| `similarity_score` | numeric(8,7) | 0..1 |
| `disposition` | varchar(32) | enum contractual |
| `section_type` | varchar(40) | snapshot minimizado, no vacío |
| `generation` | integer | > 0 |
| `content_hash` | char(64) | hash del chunk usado |
| `created_at` | timestamptz | NOT NULL, server default now |

Constraints:

- Unique `(run_id, chunk_id)`.
- Unique `(run_id, retrieval_rank)`.
- Unique `(run_id, citation_id)`.
- Unique parcial `(run_id, context_rank)` donde `context_rank IS NOT NULL`.
- `SELECTED` exige `context_rank`; otros estados exigen `context_rank IS NULL`.
- El repositorio valida además que el chunk pertenece al documento, está `ACTIVE`, coincide con `active_generation`, su documento es `REVIEWED` y `evaluation_split=INDEX_90`.

## Tabla `rag_structured_drafts`

Una salida estructurada validada por Draft.

| Campo | Tipo | Reglas |
|---|---|---|
| `id` | UUID | PK |
| `run_id` | UUID | FK única a `rag_generation_runs.id`, `ON DELETE RESTRICT` |
| `draft_id` | UUID | FK única a `drafts.id`, `ON DELETE CASCADE` |
| `schema_version` | integer | > 0 |
| `content_json` | JSONB | objeto validado; no NULL |
| `content_hash` | char(64) | SHA-256 del JSON canónico |
| `citation_count` | integer | > 0 |
| `warning_count` | integer | >= 0 |
| `created_at` | timestamptz | NOT NULL, server default now |

`content_json` debe validar en aplicación contra [rag-structured-draft.schema.json](contracts/rag-structured-draft.schema.json). La DB aplica checks estructurales básicos (`jsonb_typeof='object'`) y unicidad; la validación semántica pertenece al dominio.

## Tabla `rag_evaluation_results`

Resultados de evaluación sin insertar el documento holdout en el corpus.

| Campo | Tipo | Reglas |
|---|---|---|
| `id` | UUID | PK |
| `evaluation_run_id` | UUID | identificador del run de benchmark |
| `case_id` | varchar(128) | ID opaco del manifiesto, no ruta |
| `holdout_sha256` | char(64) | identifica el PDF reservado sin copiar contenido |
| `mode` | varchar(16) | `FAKE`, `REAL` o `HUMAN` |
| `configuration_hash` | char(64) | configuración canónica |
| `rag_run_id` | UUID nullable | FK a `rag_generation_runs.id`, `ON DELETE SET NULL` |
| `schema_valid` | boolean | NOT NULL |
| `required_sections_present` | boolean | NOT NULL |
| `citation_precision` | numeric(6,5) nullable | 0..1 |
| `source_faithfulness_score` | numeric(6,5) nullable | 0..1 |
| `unsupported_claim_count` | integer | >= 0 |
| `invented_citation_count` | integer | >= 0 |
| `legal_usefulness_score` | smallint nullable | 1..5 |
| `legally_relevant` | boolean nullable | evaluación humana |
| `correction_count` | integer nullable | >= 0 |
| `evaluator_id` | varchar(128) nullable | requerido para modo HUMAN |
| `comments` | varchar(2000) nullable | sanitizados; no contenido completo |
| `duration_ms` | integer | >= 0 |
| `created_at` | timestamptz | NOT NULL, server default now |

Unique `(evaluation_run_id, case_id, mode, configuration_hash)`.

Para agregados de recuperación (Recall@K, Precision@K y MRR), el runner produce un resumen JSON versionado; si luego se requiere consulta histórica relacional, se planificará una tabla de evaluación-run separada. El MVP evita persistir entradas completas o expectativas sensibles.

## Schema lógico `RagStructuredDraftV1`

```text
RagStructuredDraftV1
├── schema_version = 1
├── title
├── visto[]
│   ├── text
│   └── citation_ids[]
├── considerandos[]
│   ├── text
│   └── citation_ids[]
├── dispositive_intro
├── articles[]
│   ├── number
│   ├── text
│   └── citation_ids[]
├── closing
├── authority
├── signature
├── sources[]
│   ├── citation_id
│   ├── external_id
│   ├── title
│   ├── publication_date
│   ├── section_type
│   └── source_url?
└── warnings[]
```

Reglas:

- `additionalProperties=false` en todos los objetos.
- Ningún texto requerido vacío después de trim.
- Toda citation ID usada en secciones aparece exactamente una vez en `sources`.
- Toda source corresponde a `rag_retrieved_sources.disposition=SELECTED` del mismo run.
- Al menos una cita respalda VISTO o considerandos cuando el run es exitoso.
- `warnings` siempre contiene la advertencia de borrador no vinculante/revisión humana.
- `signature` es un bloque pendiente; no representa firma real ni aprobación.

## Relaciones

```text
case_files 1 ── * rag_generation_runs * ── 1 document_templates
                         |
                         +── 0..1 drafts
                         +── * rag_retrieved_sources * ── 1 corpus_documents
                         |                             `── 1 corpus_chunks
                         +── 0..1 rag_structured_drafts ── 1 drafts
                         `── * rag_evaluation_results
```

## Concurrencia e idempotencia

- El servicio obtiene/crea el run idempotente en una transacción corta.
- Dos solicitudes concurrentes con la misma key/hash producen un ganador; la otra reutiliza resultado o recibe `RAG_GENERATION_IN_PROGRESS`.
- Misma key con hash distinto produce `RAG_IDEMPOTENCY_KEY_MISMATCH`.
- El Draft y `rag_structured_drafts` se insertan en la misma transacción que marca el run `SUCCEEDED`.
- Un rollback final deja el run no exitoso; una operación de recuperación lo marca `FAILED` de forma explícita.

## Downgrade

Orden de eliminación:

1. índices de evaluación y fuentes;
2. `rag_evaluation_results`;
3. `rag_structured_drafts`;
4. `rag_retrieved_sources`;
5. `rag_generation_runs`.

El downgrade no elimina ni modifica corpus, embeddings, drafts, intentos, revisión ni tablas 001–006.
