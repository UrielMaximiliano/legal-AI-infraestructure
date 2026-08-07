# Quickstart de validación — Incremento 005

Este documento define escenarios de validación para la implementación futura.
No autoriza ejecutar una ingesta real sin revisar límites y Gate G1.

## Prerrequisitos

- Rama `005-corpus-ingestion-and-semantic-retrieval`.
- Python 3.12 y dependencias de desarrollo de `apps/api`.
- PostgreSQL 16 + pgvector del Docker Compose existente.
- Fixtures sin datos personales.
- Para pruebas reales: endpoint Ollama autorizado y credenciales por entorno.

## 1. Gate G1

La dimensión ya fue confirmada en el servidor: dos vectores válidos de 2560 para
`qwen3-embedding:4b-q4_K_M`. Ejecutar desde Docker/local el probe end-to-end con el
perfil configurado (`/api/embed` nativo o `/api/embeddings` legacy) y
guardar su JSON sanitizado. Confirmar versión, tag/digest, Bearer, exactamente
2560 valores, batch, finitud, estabilidad, latencia y documento/query.

Resultado esperado: conectividad externa validada sin cambiar el contrato 2560.
Si falla, mantener G1-B abierto y no aceptar la integración operativa; las tareas
pueden diseñarse con `halfvec(2560)`.

**Estado**: `IMPLEMENTATION_EXTERNAL_GATE_CLOSED`. La evidencia
del perfil 0.6B/8B queda superseded; la evidencia vigente del servidor confirma
4B/2560.
El perfil externo `/api/embeddings` ya fue validado desde Docker/local con
HTTPS/Bearer y respuestas 200. Consultar
[research.md](research.md#g1-b--probe-externo-ejecutado) y la
[evidencia](evidence/g1-e2e-result.json). Un probe auxiliar en
`127.0.0.1:11434` puede diagnosticar un fallo TLS/proxy, pero no sustituye la
ruta externa. G1-B está cerrado para ese perfil; cambiar a `/api/embed` requiere
repetir el probe. G1-A ya cerró modelo/dimensión: implementación, migración
`halfvec(2560)` y tests fake pueden continuar antes de G1-B.

## 2. Migración

Aplicar upgrade hasta 005, inspeccionar tablas/constraints/índices y hacer
downgrade a 004. Verificar que pgvector y objetos 001–004 permanecen. Reaplicar
005. No usar una dimensión placeholder.

## 3. Dry-run sin efectos

Ejecutar `corpus ingest <fixture> --output json` sin `--execute`. Comparar antes y
después los conteos de todas las tablas 005 y verificar cero requests al fake de
embeddings. Debe reportar discovery, parse, normalize, metadata, chunks y estimados.

`corpus ingest PATH` es dry-run por defecto y no crea runs, failures, batches,
generaciones ni modifica archivos. `corpus ingest PATH --execute` ejecuta la
ingesta por batches con provider configurado; la inferencia ocurre fuera de
transacciones y solo una generación completa se publica mediante swap atómico.

## 4. Ingesta ejecutada y resume

Con fake determinista, ejecutar con `--execute --run-id <uuid>`. Interrumpir tras
un batch confirmado, reanudar y verificar que no se repite el batch ni aparecen
duplicados. Reingestar sin cambios y comprobar cero re-embeddings.

Confirmar que `raw_content` queda protegido en PostgreSQL, nunca aparece en salida
o logs y que el documento nace `AUTOMATED`/`PENDING_REVIEW`. Ejecutar
`corpus review <DOCUMENT_ID> --approve --reviewed-by reviewer-fixture
--expected-version 1` y otro caso `--reject --reason "fixture inválido"
--reviewed-by reviewer-fixture --expected-version 1`; verificar
servicio de aplicación, procedencia, revisor, control de versión y timestamps.

Ejecutar dos approve y un escenario approve/reject concurrentes con igual versión:
exactamente uno confirma e incrementa a 2; el perdedor recibe
`CORPUS_REVIEW_VERSION_MISMATCH`. Repetir con versión menor/mayor, documento ausente
y estado terminal; comprobar códigos estables, rollback, auditoría única y cero raw.

Validar que ORM/raw nunca se serializan directamente y buscar `raw_content`,
`normalized_content`, `Authorization`, `token` y `storage_path` en respuestas
públicas, CLI, excepciones y structured logs. Solo excerpts acotados de chunks son
admisibles; no existe endpoint público de descarga del original.

## 5. Seguridad del reader

Probar traversal, symlink, extensión falsa, HTML con scripts, archivo límite y
límite+1. Ninguna salida/log contiene path absoluto o contenido.

## 6. Búsqueda

Ingerir fixture controlado y llamar `POST /api/v1/semantic-search` según
[http-api.md](contracts/http-api.md). Verificar la combinación obligatoria
`document_type=decreto`, `document_subtype=designacion_transitoria` y
`jurisdiction=nacion`, y que omitir cualquiera de esos tres filtros falla antes de
Ollama. Verificar además filtros opcionales, score, desempate, resultado vacío,
mismatch y auditoría minimizada. Confirmar que solo recupera `REVIEWED` por defecto.
Simular caída/timeout de la escritura de auditoría y esperar
503 `SEMANTIC_SEARCH_AUDIT_UNAVAILABLE`, sin resultados parciales.

Con dos ingestas y una búsqueda concurrentes, comprobar una sola llamada activa a
Ollama, prioridad SEARCH sobre el siguiente batch, yield, timeout/cancelación,
liberación del slot y ausencia de transacciones DB durante la espera/inferencia.

## 7. Reindexación

Primero ejecutar sin `--execute` y comprobar cero llamadas Ollama, escrituras DB,
runs, batches, generaciones, swaps, estados o trabajo reanudable, con reporte
determinista. Luego crear generación nueva, inducir falla y comprobar que la anterior sigue activa.
Reanudar, completar swap y verificar que cada búsqueda usa una sola generación,
modelo y dimensión.

## 8. Evaluación

Ejecutar dataset privado versionado primero con fake y luego, opcionalmente, con
Ollama. Guardar Recall@3/5, Precision@3/5, MRR, p50/p95/máximo, promedio de utilidad
jurídica y porcentaje legalmente relevante. Registrar evaluación humana 1–5 con
evaluadores seudónimos. El primer baseline G3 es informativo, sin umbral previo y no
bloquea CI. Comparar cualquier ANN futura contra exact search.

## 9. Validación final

- Ruff, format check, mypy y pytest con cobertura ≥85%.
- Tests unitarios/contractuales sin Ollama real.
- Migración round-trip y tests de integración pgvector.
- Dependencia oficial Python `pgvector` fijada y lockfile reproducible.
- `pip-audit` (o herramienta adoptada) sin vulnerabilidades críticas/altas, salvo
  excepción documentada y aprobada; no ejecutarlo como parte del unit test ordinario.
- Suite completa 001–004 con provider de embeddings caído.
- `git diff --check` y escaneo de secretos/logs.
- Verificar contratos [CLI](contracts/corpus-cli.md), [HTTP](contracts/http-api.md)
  y [modelo de datos](data-model.md).
