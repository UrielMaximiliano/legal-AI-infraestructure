# Quickstart de validación — 004-document-review-and-export

Este documento describe cómo validar la implementación cuando las tareas se
ejecuten. No instala dependencias ni implementa el incremento.

## Prerrequisitos

- Docker Compose y Python 3.12.
- PostgreSQL 16/pgvector levantado por `compose.yaml`.
- El árbol de 003 aplicado y un caso, plantilla y draft de prueba sin datos
  personales reales.
- La imagen API contiene `python-docx`, WeasyPrint y las bibliotecas Pango
  requeridas, o los tests usan fakes de los tres renderers.

## 1. Configurar storage

En `.env` de desarrollo:

```dotenv
EXPORT_STORAGE_ROOT=/var/lib/legal-ai/exports
DOCX_GENERATION_TIMEOUT_SECONDS=30
PDF_GENERATION_TIMEOUT_SECONDS=60
MAX_DOCX_SIZE_BYTES=20971520
MAX_PDF_SIZE_BYTES=31457280
MAX_PREVIEW_SIZE_BYTES=5242880
MAX_FINAL_SNAPSHOT_BYTES=2097152
MAX_EDITABLE_CONTENT_BYTES=2097152
EXPORT_IDEMPOTENCY_WINDOW_HOURS=24
EXPORT_FAILED_ATTEMPT_RETENTION_DAYS=180
EXPORT_TEMP_RETENTION_HOURS=24
EXPORT_ORPHAN_RETENTION_DAYS=7
```

Los valores son binarios y se validan como bytes: contenido editable y
`final_snapshot` 2 MiB = 2.097.152 bytes, preview HTML 5 MiB = 5.242.880 bytes,
DOCX 20 MiB = 20.971.520 bytes y PDF 30 MiB = 31.457.280 bytes. La validación
DOCX limita además el contenido descomprimido a 50 MiB = 52.428.800 bytes. Los
tests deben cubrir el límite exacto, el límite + 1 byte y contenido UTF-8
multibyte. Los endpoints documentales heredados de 003 conservan 100 KiB; la
configuración de 004 eleva solo el límite efectivo de runtime.

El Compose monta un volumen privado en ese root y la API corre como usuario
no root. No se monta el directorio como volumen público.

## 2. Aplicar la migración

```bash
docker compose up -d postgres
docker compose run --rm api alembic upgrade head
docker compose run --rm api alembic current
# Esperado: 004
```

Para probar rollback sobre una base de datos de prueba vacía:

```bash
docker compose run --rm api alembic downgrade 003
docker compose run --rm api alembic upgrade 004
```

La prueba de downgrade debe ejecutarse después de un backup y nunca sobre
datos que se quieran conservar.

## 3. Flujo humano mínimo

1. Generar un draft con los endpoints de 003.
2. Enviar el draft a revisión y abrir la revisión para su versión actual.
3. Crear y resolver comentarios; verificar que cada cambio aparece en
   `/reviews/{review_id}/history`.
4. Enviar la revisión a decisión y aprobarla con
   `human_review_confirmed=true`.
5. Finalizar:

```bash
curl -X POST http://localhost:8000/api/v1/drafts/{draft_id}/finalize \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: quickstart-finalize' \
  -d '{
    "expected_version": 6,
    "finalized_by": "legal.editor@organismo",
    "finalization_notes": "Verificado para exportación"
  }'
```

Verificar que el estado jurídico sigue `APROBADO`, la versión aumentó una vez,
el hash del snapshot está presente y una segunda solicitud idéntica devuelve
`200` sin otro incremento.

## 4. Preview efímero

```bash
curl -i 'http://localhost:8000/api/v1/drafts/{draft_id}/preview?draft_version=7'
```

Comprobar `Content-Type`, `ETag`, `Cache-Control: no-store`, ausencia de
scripts/iframes/URLs remotas y que no aparece ningún archivo nuevo en el
volumen de exportaciones.

## 5. Crear y descargar exportaciones

```bash
curl -i -X POST http://localhost:8000/api/v1/drafts/{draft_id}/exports \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: quickstart-docx-0001' \
  -d '{"draft_version":7,"format":"DOCX","exported_by":"legal.editor@organismo"}'

curl -i -X POST http://localhost:8000/api/v1/drafts/{draft_id}/exports \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: quickstart-pdf--000001' \
  -d '{"draft_version":7,"format":"PDF","exported_by":"legal.editor@organismo"}'
```

La primera respuesta es `202` y contiene una exportación `GENERATING` y un
attempt `PROCESSING`; el estado puede consultarse por
`GET /api/v1/exports/{id}`. Un fallo posterior queda como `FAILED` y se
consulta mediante metadata/attempts. Tras
`GENERATED`:

```bash
curl -i -L \
  http://localhost:8000/api/v1/exports/{export_id}/download \
  -o artifact.bin
```

Comprobar `Content-Disposition`, `Content-Length`, ETag y `private, no-store`.
No se debe devolver `storage_path`. Una solicitud con header `Range` debe
responder `416` con `RANGE_NOT_SUPPORTED`, envelope JSON con `request_id` y
`timestamp`, y `Accept-Ranges: none`; no debe iniciar streaming, leer el archivo completo ni
devolver `Content-Range`.

El envelope público de error reutilizado de 003 es:

```json
{
  "error": {
    "code": "EXPORT_FILE_CORRUPTED",
    "message": "The exported file failed integrity validation.",
    "details": {},
    "request_id": "...",
    "timestamp": "2026-08-03T21:00:00Z"
  }
}
```

El servidor genera `timestamp` en UTC, RFC 3339 y con sufijo `Z`.

Cada generación DOCX/PDF se ejecuta en un proceso hijo aislado iniciado con
`spawn`, uno por operación. Solo se transfieren datos serializables y la ruta
temporal segura. Si vence el timeout de 30 s para DOCX o 60 s para PDF, el
proceso se termina, se espera una gracia breve, se fuerza `kill` si continúa
activo, se ejecuta `join`, se eliminan temporales y se registra
`GENERATION_TIMEOUT`; el artefacto vencido no se publica y el proceso no se
reutiliza.

## 6. Retry y regeneración

Para un export `FAILED`, conservar la misma clave y llamar:

```bash
curl -i -X POST http://localhost:8000/api/v1/exports/{export_id}/retry \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: quickstart-docx-0001' \
  -d '{"exported_by":"legal.editor@organismo"}'
```

El listado de attempts debe mostrar el primer `FAILED` y el nuevo número.

Para regenerar:

```bash
curl -i -X POST http://localhost:8000/api/v1/exports/{export_id}/regenerate \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: quickstart-regenerate-1' \
  -d '{"expected_version":1,"exported_by":"legal.editor@organismo"}'
```

La nueva fila usa `parent_export_id`, un `export_version` mayor y un nuevo hash. El
artefacto previo pasa a `SUPERSEDED` solo después del éxito; se puede
regenerar aunque se quite o corrompa el archivo previo.

## 7. Reconciliación administrativa

```bash
document-exports reconcile --actor ops-admin --draft-id {draft_id}
document-exports reconcile --actor ops-admin --incident-type ORPHAN_FILE \
  --older-than P7D
document-exports reconcile --actor ops-admin --run-id {run_id} --execute
```

La primera ejecución es dry-run. Solo `--execute` elimina temporales,
huérfanos elegibles o attempts fallidos de más de 180 días. Los registros sin
archivo y archivos corruptos se reportan y se omiten. Verificar JSON con
`run_id`, `candidates`, `deleted`, `omitted`, `conflicts` y `errors`.

## 8. Benchmarks informativos

Los benchmarks no forman parte de la suite unitaria ni del CI estándar. En el
entorno de referencia Linux/Docker, con PostgreSQL 16 levantado, ejecutar:

```bash
cd apps/api
uv run python scripts/benchmark_004.py \
  --dataset tests/fixtures/benchmark_004_dataset.json \
  --warmup 10 --iterations 50 \
  --output artifacts/benchmarks/004.json
```

El runner mide por separado revisión (`<300 ms`), preview de 100 KiB
(`<2.000 ms`), aceptación `202` (`<500 ms`), descarga de 1 MiB
(1.048.576 bytes; `<1.500 ms`) y reconcile dry-run (`<3.000 ms`), todos como
p95 informativo.
Registra muestras, entorno, commit, dataset, umbrales y alertas de regresión.
La aceptación usa un fake después de Tx1 y no incluye la generación completa
DOCX/PDF. Un umbral excedido alerta, pero no bloquea el comando ni el CI.

## 9. Tests y herramientas

```bash
cd apps/api
pytest tests/unit tests/contract -m 'not integration' --cov=legal_ai
pytest tests/integration/test_004_migrations.py -m integration
pytest tests/integration/test_export_pipeline.py -m integration
ruff check src tests
ruff format --check src tests
mypy src/legal_ai
```

La matriz debe cubrir fakes de renderers en todos los tests deterministas y un
smoke opcional con WeasyPrint dentro de Docker. El gate obligatorio de mypy para
004 es `mypy apps/api/src/legal_ai` ejecutado desde la raíz del repositorio (o
`mypy src/legal_ai` desde `apps/api`). El comando `mypy apps/api/src/legal_ai
apps/api/tests` puede ejecutarse de forma informativa y falla por deuda técnica
preexistente en tests; esos errores no se ocultan, no se declaran resueltos y
quedan fuera del alcance de 004. No se requiere LibreOffice.

## 10. Validación Docker final

```bash
docker compose config --quiet
docker compose build api
docker compose up -d
docker compose exec api alembic upgrade head
docker compose exec api python -c \
  "from legal_ai.adapters.renderers.pdf_renderer import PdfRenderer; print(PdfRenderer.health())"
```

El smoke final abre una revisión, aprueba/finaliza, previsualiza HTML mediante
`GET /api/v1/drafts/{draft_id}/preview?draft_version={n}`, crea exportaciones
DOCX y PDF y descarga ambos artefactos. HTML es solo preview no persistido;
DOCX y PDF son los únicos formatos exportables. Los logs deben contener IDs,
estados, tamaños, hashes y duraciones, nunca el documento completo, prompt,
secreto o ruta absoluta.

## 11. Observabilidad y limitaciones conocidas

Los eventos estructurados de 004 se escriben en stdout como JSON y contienen
únicamente `request_id`, `run_id`, identificadores UUID, formato/versiones,
renderer, duraciones, tamaños, hashes y códigos sanitizados. No se registran
actores fuera del contexto de auditoría, DNI, CUIL, contenido del draft,
`final_snapshot`, tokens, `Authorization`, `storage_path`, rutas absolutas ni
stack traces.

La indisponibilidad de Ollama es una dependencia externa de la generación de
drafts y del readiness general, no de la preview ni del pipeline de
exportación desde `final_snapshot`. No se resuelve en este incremento el
problema TLS de Tailscale Funnel/Nginx. Las descargas de artefactos ya
`GENERATED` o `SUPERSEDED` continúan dependiendo únicamente de PostgreSQL y el
filesystem local.

El benchmark informativo se ejecuta manualmente con el comando de la sección 8
y registra dataset/hash, entorno, warm-up, iteraciones, p50, p95, máximo y
alertas. Sus resultados no bloquean pytest/CI ni son límites contractuales.
