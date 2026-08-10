# Quickstart de validación: RAG Jurídico 006

Esta guía define cómo demostrar el incremento una vez implementado. No debe ejecutarse todavía contra la base cargada del servidor mientras el worker de embeddings esté activo.

## 1. Prerrequisitos

- Rama `006-rag-dev` o rama de implementación derivada.
- Docker y Docker Compose.
- Python/uv configurados en `apps/api`.
- PostgreSQL de prueba aislado; nunca usar la base real cargada para tests de downgrade.
- Para smoke real: Ollama autorizado con:
  - `qwen3-embedding:4b-q4_K_M`;
  - `qwen3.6:35b`;
  - `/api/embed` y `/api/chat` accesibles;
  - credencial Bearer configurada fuera de Git.
- Para holdout: carpeta externa con los 1.000 PDF y manifiesto; no copiar PDF al repositorio.

## 2. Configuración local

Copiar `.env.example` a `.env` y completar secretos localmente. Variables esperadas:

```dotenv
OLLAMA_EMBEDDING_MODEL=qwen3-embedding:4b-q4_K_M
EMBEDDING_DIMENSIONS=2560
OLLAMA_GENERATION_MODEL=qwen3.6:35b
OLLAMA_GENERATION_ENDPOINT=/api/chat
RAG_PROMPT_VERSION=rag-decree-v1
RAG_SCHEMA_VERSION=1
RAG_TOP_K=8
RAG_REQUIRED_EVALUATION_SPLIT=INDEX_90
```

Nunca pegar tokens en comandos que queden en history, logs o evidencia.

## 3. Instalación y validaciones estáticas

Desde `apps/api`:

```powershell
uv sync --extra dev
uv lock --check
uv run ruff check src tests
uv run mypy src/legal_ai
```

Esperado: todos los comandos finalizan con código 0.

## 4. PostgreSQL aislado y migración

Los tests PostgreSQL de 006 exigen `RAG_TEST_DATABASE_URL` y rechazan la base
por defecto `legal_ai`; la URL debe apuntar a una base temporal dedicada. Sin
esa variable, los tests se omiten y no constituyen evidencia de un gate verde.

El readiness RAG cuenta únicamente documentos activos `REVIEWED` de `INDEX_90`.
Si el corpus operativo contiene cero `REVIEWED`, el resultado esperado es
`RAG_NO_REVIEWED_INDEX_90_DOCUMENTS` y la generación no debe crear Draft.

Levantar dependencias locales con una base vacía o clon de test sin corpus real:

```powershell
docker compose up -d postgres
docker compose run --rm api alembic upgrade 007
```

Ejecutar los tests de migración que creen su propio esquema/base temporal:

```powershell
cd apps/api
uv run pytest tests/integration/test_007_migrations.py -q
```

El test debe probar `006 -> 007 -> 006 -> 007`, preservar fixtures 001–006 y eliminar todos los objetos 007 en downgrade.

## 5. Gate de corpus

En una copia de la base con corpus:

```sql
SELECT
  count(DISTINCT d.id) AS eligible_documents,
  count(c.id) AS eligible_chunks,
  count(c.id) FILTER (WHERE c.embedding IS NULL) AS missing_embeddings
FROM corpus_documents d
JOIN corpus_chunks c
  ON c.document_id = d.id
 AND c.generation = d.active_generation
WHERE d.review_status = 'REVIEWED'
  AND c.state = 'ACTIVE'
  AND c.metadata->>'evaluation_split' = 'INDEX_90';
```

Esperado para smoke real:

- `eligible_documents > 0`;
- `eligible_chunks > 0`;
- `missing_embeddings = 0`.

Si el split está en metadata documental en la implementación final, adaptar únicamente la ubicación del filtro, no su semántica.

## 6. Tests focalizados fake

```powershell
cd apps/api
uv run pytest `
  tests/unit/test_rag_domain.py `
  tests/unit/test_rag_context.py `
  tests/unit/test_rag_generation.py `
  tests/contract/test_rag_api.py `
  tests/contract/test_ollama_structured_generation.py `
  -q
```

Escenarios mínimos:

- recuperación y contexto deterministas;
- citation IDs resolubles;
- JSON válido e inválido;
- una reparación de schema;
- evidencia insuficiente;
- auditoría fail-closed;
- idempotencia y concurrencia;
- prompt injection en chunks;
- cero contenido sensible en logs/errores;
- Draft siempre pendiente de revisión.

## 7. E2E fake

```powershell
docker compose up -d postgres api
docker compose exec api pytest tests/integration/test_rag_generation_e2e.py -q
```

Validar:

1. Se crea un run `SUCCEEDED`.
2. Sus fuentes apuntan a chunks activos `REVIEWED` de `INDEX_90`.
3. Se crea una sola salida estructurada y un solo Draft.
4. El Draft queda `PENDING_REVIEW`.
5. Repetir con la misma idempotency key no crea filas adicionales.
6. Fallar auditoría o schema crea cero Drafts.

## 8. Dry-run del holdout

```powershell
cd apps/api
uv run corpus rag-evaluate "C:\ruta\externa\manifest.json"
```

Esperado:

- `mode=DRY_RUN`;
- `case_count=1000`;
- `leakage_detected=0`;
- cero llamadas a Ollama;
- cero escrituras PostgreSQL;
- ninguna ruta absoluta en la salida.

## 9. Evaluación fake

```powershell
uv run corpus rag-evaluate "C:\ruta\externa\manifest.json" --execute --provider fake
```

Esperado: resultado reproducible, schema válido y métricas presentes o `null` cuando no exista ground truth. Nunca inventar un cero.

## 10. Probe real de modelos

Ejecutar solo cuando la ruta autorizada esté disponible. El probe debe usar textos sintéticos y no imprimir vectores ni respuestas completas.

Validar embeddings:

- HTTP 200;
- dos inputs producen dos vectores;
- cada vector tiene 2560 valores finitos.

Validar chat:

- HTTP 200;
- modelo reportado `qwen3.6:35b`;
- `message.content` parsea como JSON;
- valida contra `contracts/rag-structured-draft.schema.json`;
- Bearer es requerido en endpoint remoto.

Un probe localhost confirma capacidad del servidor, pero el smoke de aceptación remota debe atravesar la ruta real de la aplicación.

## 11. Smoke HTTP RAG

```powershell
$headers = @{
  "Content-Type" = "application/json"
  "Idempotency-Key" = "rag-smoke-00000001"
  "X-Request-ID" = "rag-smoke-00000001"
}

$body = @{
  template_id = "00000000-0000-0000-0000-000000000000"
  case_file_id = "00000000-0000-0000-0000-000000000000"
  variables = @{ cargo = "valor sintético"; organismo = "organismo sintético" }
  retrieval = @{ top_k = 8; minimum_score = 0.0; language = "es" }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/rag/drafts/generate `
  -Headers $headers `
  -Body $body
```

Reemplazar UUID por fixtures de test, nunca por datos personales reales en evidencia compartida.

## 12. Validación integral

```powershell
cd apps/api
uv run pytest --cov=src/legal_ai --cov-report=term-missing
uv run ruff check src tests
uv run mypy src/legal_ai
uv lock --check
cd ../..
docker compose config -q
git diff --check
```

Además:

- escanear secretos y contenido prohibido;
- comprobar que no cambió ninguna migración 001–006;
- comprobar que el endpoint legacy de draft conserva sus contratos;
- inspeccionar que no haya PDF, dumps, `.env`, tokens o logs staged;
- ejecutar auditoría de dependencias antes del cierre.

## 13. Promoción al servidor

Solo después de tests, revisión, commit y merge a `main`:

1. Esperar que termine el worker de embeddings.
2. Confirmar backup y worktree limpio en el servidor.
3. Hacer `git fetch origin` y fast-forward/merge aprobado a `main`.
4. Reconstruir la imagen.
5. Aplicar migración 007 con backup verificable.
6. Ejecutar readiness y smoke real.

No hacer pull ni reiniciar servicios del servidor durante el desarrollo local de 006.

## 14. Activar un índice staged ya embebido

La activación es administrativa y no equivale a revisión jurídica. Probar
primero sobre la copia aislada:

```powershell
cd apps/api
uv run corpus activate-staged-index `
  --expected-database legal_ai_t068_20260810
uv run corpus activate-staged-index `
  --expected-database legal_ai_t068_20260810 `
  --execute
```

El primer comando es un dry-run sin escrituras. El segundo es idempotente y
reanudable, no invoca Ollama, no recalcula vectores y no modifica
`review_status` ni `review_version`. Verificar luego 9.000 documentos con
`active_generation=1`, 65.916 chunks `ACTIVE`, cero `STAGED`, embeddings y
dimensiones intactos, y cero inconsistencias documento/generación.

Después, seleccionar y revisar humanamente una muestra inicial de 100 decretos;
no aprobar los 9.000 en bloque:

```powershell
uv run corpus review DOCUMENT_ID --approve `
  --reviewed-by "IDENTIDAD_DEL_REVISOR" `
  --expected-version N
```
