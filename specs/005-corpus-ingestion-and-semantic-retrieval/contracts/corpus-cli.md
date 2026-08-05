# Contrato CLI — Corpus 005

**Status**: `IMPLEMENTATION_EXTERNAL_GATE_PENDING`

## Convenciones

- Comando raíz: `corpus`.
- stdout contiene únicamente JSON cuando `--output json`.
- stderr no contiene contenido, token ni path absoluto.
- Exit codes: 0 éxito/partial aceptado, 1 fallo operativo reintentable, 2 uso o
  validación no reintentable.

## `corpus ingest PATH`

Opciones: `--document-type`, `--document-subtype`, `--jurisdiction`, `--language`,
`--source-name`, `--batch-size`, `--embedding-model`,
`--embedding-dimensions`, `--execute`, `--resume`, `--run-id`, `--limit`,
`--fail-fast`, `--output json`.

### Dry-run predeterminado

Sin `--execute`: discovery, path validation, parse, normalize, metadata validate,
deduplicate simulation, chunk, estimate y configuración. No llama Ollama, no
abre transacción de escritura, no crea runs y no modifica DB.

Salida incluye `mode: dry-run`, source sanitizado, configuración no secreta,
conteos/estimaciones y fallas de archivo sanitizadas.

### `--execute`

Es la única autorización de efectos: crea run, persiste staging, solicita
embeddings, confirma batches, activa chunks y registra fallas. `--resume` exige
`--execute` y `--run-id`; un snapshot incompatible falla cerrado.

No existe `--persist`. Repetir el mismo `run_id` sin `--resume` devuelve conflicto.

La implementación ejecuta esta autorización por batches deterministas: la
persistencia inicial de documentos/chunks y batches ocurre en transacciones
cortas; la espera, inferencia, retry y backoff ocurren fuera de ellas; cada
batch se confirma atómicamente y la generación solo se activa mediante swap al
completar todos los embeddings. Un fallo deja el run reanudable y no publica una
generación incompleta. El proveedor real requiere G1-B; los tests ordinarios usan
`FakeEmbeddingProvider` explícito.

## `corpus reindex`

Opciones: `--document-id`, `--document-subtype`, `--jurisdiction`,
`--embedding-model`, `--embedding-dimensions`, `--normalization-version`,
`--chunking-version`, `--batch-size`, `--execute`, `--resume`, `--run-id`,
`--output json`.

También es dry-run por defecto. Con execute crea generación staging, procesa,
valida y hace swap lógico solo al completar. La generación anterior permanece
activa ante fallas. Un cambio de modelo, dimensión, versión de normalización o
versión de chunking exige reindexación completa o generación nueva con swap;
nunca se mezclan configuraciones en el índice lógico activo.

Sin `--execute` produce un reporte determinista y garantiza cero llamadas a Ollama,
escrituras DB, `ingestion_runs`, `embedding_batches`, generaciones, swaps, cambios
de estado y trabajo reanudable.

## `corpus review DOCUMENT_ID`

Comando administrativo mínimo. Formas mutuamente excluyentes:

- `corpus review DOCUMENT_ID --approve --reviewed-by "..." --expected-version N`
- `corpus review DOCUMENT_ID --reject --reason "..." --reviewed-by "..." --expected-version N`

Todo documento inicia `AUTOMATED`/`PENDING_REVIEW`. Aprobar produce
`HUMAN_REVIEWED`/`REVIEWED`; rechazar exige motivo sanitizado y produce
`HUMAN_REVIEWED`/`REJECTED`. Approve/reject son excluyentes y `reviewed_by` textual
es obligatorio. `expected_version` también es obligatorio y entero positivo.
`CorpusReviewService` valida existencia, versión, transición y auditoría mediante
repositorio/UoW; el CLI solo invoca el
servicio. `REVIEWED` y `REJECTED` son terminales en el MVP; una transición posterior
falla como conflicto con salida JSON sanitizada.
La salida nunca contiene `raw_content`, contenido
normalizado completo, paths ni identidad sensible del revisor. La búsqueda normal
solo usa `REVIEWED`; `--include-pending-review` se admite únicamente en
`corpus evaluate` administrativo y nunca en búsqueda normal.

Éxito JSON incluye exclusivamente `document_id`, `review_status`, `review_version`,
`reviewed_by` y `reviewed_at`, además del envelope/correlación común.

| Exit/HTTP equivalente | Código | Condición/details permitidos |
|---:|---|---|
| 404 | `CORPUS_DOCUMENT_NOT_FOUND` | Documento inexistente |
| 409 | `CORPUS_REVIEW_VERSION_MISMATCH` | Versión obsoleta; solo `expected_version` y `current_version` |
| 409 | `INVALID_CORPUS_REVIEW_TRANSITION` | Estado terminal o incompatible |
| 422 | `CORPUS_REVIEW_REASON_REQUIRED` | Reject sin motivo válido |
| 422 | `CORPUS_REVIEWER_REQUIRED` | Revisor ausente o inválido |

Los errores nunca incluyen contenido, ORM, paths, secretos o datos sensibles.

## `corpus probe-embedding`

Comando opt-in para validar G1-B con el contrato ya fijado. Opciones: `--model
qwen3-embedding:0.6b`, `--expected-dimensions 1024`, `--repeat 3`, `--output
json`. Se ejecuta desde Docker/local contra `OLLAMA_BASE_URL`, usa textos
sintéticos y nunca imprime inputs, URL completa, Authorization o token.

Salida: versión Ollama, tag/digest, dimensión nativa, dimensión solicitada,
cantidad de vectores, finitud, estabilidad, latencias, soporte y timestamp.

## `corpus evaluate`

Opciones: `--dataset`, `--provider fake|ollama`, `--include-pending-review`,
`--human-evaluations`, `--output json`. Fake es default; Ollama requiere opt-in.
Reporta versión, Recall@3/5, Precision@3/5, MRR, p50/p95/máximo, utilidad jurídica
promedio y porcentaje legalmente relevante. El fixture privado conserva query y
relevancia esperada; la salida pública no las reproduce ni identifica personas.
El primer baseline es informativo, sin umbral contractual y no bloquea CI estándar.

## Ejemplo de resumen JSON

```json
{
  "run_id": "uuid-o-propuesto",
  "mode": "dry-run",
  "status": "completed",
  "counts": {
    "discovered": 10,
    "valid": 9,
    "failed": 1,
    "estimated_chunks": 63,
    "estimated_embeddings": 63
  },
  "failures": [{"source_identifier": "file-009", "error_code": "CORPUS_PARSE_FAILED"}]
}
```
