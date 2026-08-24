# legal-AI-infraestructure

Las variables contractuales de Ollama para embeddings son `OLLAMA_EMBEDDING_BASE_URL`,
`OLLAMA_EMBEDDING_TOKEN` y `OLLAMA_EMBEDDING_TIMEOUT_SECONDS`. Los nombres
`OLLAMA_BASE_URL`, `OLLAMA_API_TOKEN` y `OLLAMA_TIMEOUT_SECONDS` se mantienen
únicamente como aliases explícitos de compatibilidad con 001-004.
La referencia histórica a `OLLAMA_API_TOKEN` en el párrafo operativo de 005 significa
ese alias; las instalaciones nuevas deben usar `OLLAMA_EMBEDDING_TOKEN`.

## Incremento 005: ingesta y recuperación semántica

La configuración contractual usa `qwen3-embedding:4b-q4_K_M` con `EMBEDDING_DIMENSIONS=2560`
(`halfvec(2560)`). La búsqueda filtra `REVIEWED` por defecto y la ingesta es dry-run
salvo que se indique explícitamente `--execute`. `OLLAMA_API_TOKEN` se suministra
únicamente por el entorno; nunca se registra ni se persiste. La ruta de producción
es local Docker → HTTPS/Bearer → Ollama remoto. Configure
`OLLAMA_EMBEDDING_ENDPOINT=/api/embed` para batch nativo o
`/api/embeddings` para el proxy externo legado (batch secuencial a nivel de
aplicación); no existe fallback implícito.

## Incremento 004: revisión humana y exportación documental

El incremento 004 agrega revisión humana, finalización write-once, preview y
exportación local de documentos aprobados. Es compatible con la máquina de
estados de 003 y no agrega autenticación, colas, Redis, scheduler ni
almacenamiento cloud.

### Flujo operativo

1. Abrir una revisión para el `draft_version` actual.
2. Agregar/resolver comentarios y aprobar la revisión cerrada.
3. Finalizar el draft una sola vez; `final_snapshot` y su SHA-256 quedan
   inmutables.
4. Obtener preview HTML con
   `GET /api/v1/drafts/{draft_id}/preview?draft_version={n}`.
5. Crear DOCX o PDF con `POST /api/v1/drafts/{draft_id}/exports`.
6. Consultar metadata/attempts y descargar con
   `GET /api/v1/exports/{export_id}/download`.

HTML es únicamente preview y representación intermedia no persistida. DOCX y
PDF son los únicos artefactos persistidos y descargables. Las exportaciones se
generan desde `final_snapshot`; Ollama se ejecuta fuera del proceso de
exportación y su indisponibilidad no afecta descargas de artefactos ya
generados.

### Endpoints 004

- Reviews: current, create, comments, update comment, submit, approve,
  request-changes e history.
- Draft: `POST /api/v1/drafts/{draft_id}/finalize` y preview HTML.
- Exports: create, list, metadata, attempts, download, retry y regenerate.
- Administrativo: `document-exports reconcile` (no existe DELETE HTTP).

Las mutaciones exigen `expected_version` cuando corresponde. Creación, retry y
regeneración usan `Idempotency-Key`; retry reutiliza el mismo `DocumentExport`,
mientras regenerate crea uno nuevo y enlaza `parent_export_id`. `GENERATED` y
`SUPERSEDED` son descargables.

Los errores JSON mantienen el envelope de 003 e incluyen `request_id` y
timestamp UTC RFC 3339. Las descargas verifican ruta, MIME, estructura y
SHA-256 antes de iniciar streaming. Range no está soportado: responde
`416 RANGE_NOT_SUPPORTED` con `Accept-Ranges: none`.

### Límites y almacenamiento

Los límites configurables están expresados en bytes binarios en
[`.env.example`](.env.example): contenido editable y snapshot 2 MiB,
preview 5 MiB, DOCX 20 MiB y PDF 30 MiB. DOCX aplica además límites de ZIP
anti-bomb. El almacenamiento es local bajo `EXPORT_STORAGE_ROOT`, usa rutas
relativas basadas en UUID/version, permisos mínimos, temporales en el mismo
directorio y rename atómico.

### Reconciliación

```bash
document-exports reconcile --actor ops-admin --draft-id <draft-id>
document-exports reconcile --actor ops-admin --incident-type ORPHAN_FILE \
  --older-than P7D
document-exports reconcile --actor ops-admin --run-id <run-id> --execute
```

El modo dry-run es el predeterminado. `--execute` solo elimina temporales,
huérfanos elegibles y attempts FAILED fuera de retención; conserva registros
sin archivo, archivos corruptos, el último artefacto válido y recursos con
procesamiento activo. La salida JSON contiene `run_id`, candidatos,
eliminados, omitidos, conflictos y errores.

### Observabilidad y seguridad

Los eventos estructurados contienen únicamente identificadores técnicos,
formato/versiones, duraciones, tamaños, hashes y códigos sanitizados. No se
registran DNI, CUIL, nombres completos, actores fuera de auditoría, contenido,
`final_snapshot`, tokens, headers Authorization, rutas absolutas ni
`storage_path`.

### Validación local

```bash
cd apps/api
uv run pytest
uv run ruff check src tests scripts
uv run mypy src/legal_ai
uv run python scripts/benchmark_004.py \
  --dataset tests/fixtures/benchmark_004_dataset.json \
  --warmup 10 --iterations 50 \
  --output artifacts/benchmarks/004.json
```

Los benchmarks son manuales e informativos; no forman parte del CI estándar ni
son un gate de release. El protocolo usa Linux/amd64 en Docker, Python 3.12,
PostgreSQL 16, dataset sintético sin PII, p50/p95/máximo y alertas por
regresión superior al 10 %. La aceptación HTTP 202 no mide la generación
completa de DOCX/PDF.

Para el entorno operativo y el smoke completo, consultar
[specs/004-document-review-and-export/quickstart.md](specs/004-document-review-and-export/quickstart.md).

## Incremento 005: corpus y búsqueda semántica

```bash
corpus ingest ./corpus
corpus ingest ./corpus --execute --run-id <opaque-run-id>
corpus reindex --document-id <uuid>
corpus reindex --document-id <uuid> --execute --run-id <opaque-run-id>
```

La ingesta dry-run no solicita embeddings ni escribe PostgreSQL. La ejecución y
reindexación usan `qwen3-embedding:4b-q4_K_M` con 2560 dimensiones, generaciones
STAGED y swap atómico. La búsqueda `POST /api/v1/semantic-search` exige los
filtros MVP y devuelve solo documentos `REVIEWED` por defecto; su auditoría es
fail-closed. Consulte [docs/corpus-semantic-retrieval.md](docs/corpus-semantic-retrieval.md)
para límites, evaluación y seguridad.

## Benchmark de generación

El protocolo para comparar las 1.000 salidas contra sus PDFs de referencia está
documentado en [docs/benchmarks/benchmark-protocol.md](docs/benchmarks/benchmark-protocol.md).
La evaluación automática PDF-proxy es solo provisional; las métricas jurídicas
requieren gold facts y revisión humana. Las corridas 4B (`halfvec(2560)`) y
0.6B (`halfvec(1024)`) se mantienen aisladas.
