# Investigación: Corpus ingestion y semantic retrieval

**Fecha**: 2026-08-04
**Estado**: modelo y dimensión confirmados empíricamente en Ollama; conectividad
externa end-to-end pendiente.

## R1 — Modelo y endpoint Ollama

**Decisión**: usar el tag exacto `qwen3-embedding:0.6b` y `POST /api/embed`
con `input` string o array, `truncate=false` y `keep_alive` acotado/omitido.

**Evidencia**:

- La [ficha oficial de Ollama](https://ollama.com/library/qwen3-embedding%3A0.6b)
  publica el tag, tamaño aproximado 639 MB, 596M parámetros y Q8_0.
- La [API oficial de embeddings](https://docs.ollama.com/api/embed) define
  `POST /api/embed`, batches en `input`, `truncate`, `dimensions`, `keep_alive` y
  respuesta `embeddings: number[][]`.
- El [repositorio oficial Qwen3-Embedding](https://github.com/QwenLM/Qwen3-Embedding)
  declara para 0.6B contexto 32K, 1024 dimensiones nativas, capacidad
  multilingüe e instruction-aware.

**Rationale**: es el contrato actual documentado y evita reutilizar el adaptador
generativo. `truncate=false` impide pérdida silenciosa de contenido.

**Alternativas**: `/api/embeddings` está superseded; OpenAI-compatible agrega una
capa innecesaria; un modelo diferente rompe el alcance.

### Hallazgos y límites

- **Dimensión contractual**: 1024. Una ejecución empírica en el servidor Ollama
  confirmó dos vectores uniformes de 1024 valores, no vacíos y sin NaN o
  infinitos observados. No existe una reducción dimensional en alcance.
- **Batch**: soportado contractualmente mediante array de textos; el límite real
  se fija por `OLLAMA_EMBEDDING_BATCH_SIZE` y `CORPUS_MAX_FILE_SIZE_BYTES` tras
  benchmark.
- **Vacío**: la aplicación rechaza strings vacíos antes de llamar; no depende del
  comportamiento variable del servidor.
- **Versión mínima**: la documentación actual no identifica una versión mínima
  confiable para `dimensions`; registrar `/api/version` y convertir la versión
  probada en mínimo operativo.
- **Modelo único cargado**: con `OLLAMA_MAX_LOADED_MODELS=1`, una carga de
  embeddings puede desalojar al generador. Omitir keep-alive largo y coordinar
  ingesta; no ejecutar en paralelo.

## R2 — Probe empírico de dimensión (Gate G1)

**Decisión**: crear un comando administrativo reproducible, opt-in y separado de
pytest, por ejemplo `corpus probe-embedding --output json`.

Debe:

1. Consultar `/api/version` y detalles del modelo/tag/digest sin imprimir URL ni token.
2. Enviar dos textos sintéticos no sensibles como batch sin `dimensions`.
3. Validar dos vectores, igualdad de longitud, finitud y estabilidad entre dos ejecuciones.
4. Confirmar documento, query y batch con exactamente 1024 valores.
5. Confirmar estabilidad y compatibilidad cruzada.
6. Emitir JSON sanitizado: versión, tag/digest, native_dimensions,
   requested_dimensions, vector_count, latencia, soporte y timestamp.
7. Fallar cerrado si hay mismatch o campo desconocido.

**Decisión contractual**: fijar `OLLAMA_EMBEDDING_MODEL=qwen3-embedding:0.6b`,
`EMBEDDING_DIMENSIONS=1024` y `vector(1024)`. La dimensión ya no está pendiente.
G1-A está cerrado y autoriza implementación, migración y tests fake. G1-B no reabre
el contrato ni bloquea esos trabajos; solo bloquea aceptación operativa remota,
cierre externo completo y smoke real desde Docker/local.

<a id="g1-evidence-0-6b"></a>

### Evidencia empírica de dimensión — servidor Ollama

Se ejecutó correctamente `POST http://127.0.0.1:11434/api/embed` en el servidor
Ollama con `qwen3-embedding:0.6b` y dos textos sintéticos en español jurídico.
Resultado: `vector_count=2`, dimensión uniforme 1024, vectores no vacíos y sin
NaN o infinitos observados. No se conservaron vectores, token, autorización,
rutas internas ni contenido real.

**Conclusión**: el modelo y la dimensión contractual quedan confirmados. Esta
prueba no valida por sí sola la ruta externa utilizada por la aplicación.

### Ejecución empírica superseded — modelo 8B — 2026-08-04

Se ejecutó un probe contra el endpoint HTTPS configurado usando exclusivamente
textos sintéticos. La evidencia sanitizada se conserva en
[g1-result-2026-08-04.json](evidence/g1-result-2026-08-04.json).

Esta ejecución corresponde a `qwen3-embedding:8b-q8_0` y no aporta evidencia
para cerrar G1 del nuevo modelo 0.6B. Se conserva únicamente como historial.

Resultados históricos alcanzados:

- TLS y autenticación funcionan para `GET /api/version`, `POST /api/show` y
  `GET /api/tags`.
- Ollama reportó versión `0.32.5`.
- El tag instalado es `qwen3-embedding:8b-q8_0`, digest
  `9704fd987c12aa746934ea9f99dc85527c83c6e4b98b3a10b94689332ee866bb`,
  tamaño 8.047.106.087 bytes, formato GGUF, familia qwen3, 7.6B y Q8_0.
- El modelo declara capability `embedding`.
- `POST /api/embed` respondió HTTP 404 con error sanitizado `not found`.
- La latencia cliente informativa fue 1.245,652 ms para version, 1.678,095 ms
  para show y 1.436,531 ms para la respuesta 404 de embed; no son un SLA.
- El fallback solicitado sobre `127.0.0.1:11434` no pudo ejecutarse: el host
  remoto no es accesible por SSH desde esta estación (puerto 22 agotó timeout).

Por lo tanto no se ejecutaron las pruebas dependientes de embeddings: dimensión
nativa, 1024, estabilidad, documento/query, batch, errores ni keep-alive. No es
válido inferir esos resultados a partir de la ficha documental.

**Decisión vigente**: la evidencia del modelo 8B permanece superseded. Para 0.6B,
modelo y dimensión ya están fijados; solo queda abierto el subgate externo.

**Subgate G1-B de conectividad pendiente**: el probe debe ejecutarse desde el entorno local de
005 —preferentemente desde su contenedor Docker— usando `OLLAMA_BASE_URL` y
`Authorization: Bearer`, y atravesar la ruta real aplicación local → HTTPS →
Tailscale Funnel/Nginx → Ollama remoto → modelo. Debe verificar desde ese origen
`/api/version`, `/api/show`, `/api/embed`, autenticación, dimensión nativa,
`dimensions=1024`, batch, estabilidad, latencia y compatibilidad documento/query.

**Acción pendiente**: corregir el enrutamiento externo de `/api/embed` y
repetir el probe desde Docker/local. Solo si existe un fallo TLS se permite un
probe auxiliar en el servidor contra `http://127.0.0.1:11434`; ese resultado
sirve para aislar Ollama del proxy, pero no cierra G1 porque no valida la ruta de
producción de la aplicación. No desactivar verificación TLS.

## R3 — pgvector y estrategia de índice

**Decisión**: `vector(1024)`, operador coseno `<=>`, exact search inicial y B-tree
para filtros. `similarity_score = clamp(1 - distance, 0, 1)`.

**Evidencia**: la [documentación oficial de pgvector](https://github.com/pgvector/pgvector)
indica exact search por defecto con recall perfecto, HNSW/IVFFlat como aproximados,
`<=>` para coseno, límite general de 16.000 dimensiones para `vector`, costo de
`4 * dimensions + 8` bytes y límite HNSW de 2.000 dimensiones para `vector`.

**Implicación 1024**: puede almacenarse como `vector(1024)` y es compatible con
HNSW `vector` por estar debajo del límite de 2000 dimensiones. Cada vector ocupa
al menos 4.104 bytes sin contar fila/índices. Exact search permanece como baseline.

**Alternativas**:

- HNSW: compatible dimensionalmente; solo se habilita tras G2 por volumen/calidad.
- IVFFlat: requiere entrenamiento/listas y puede perder recall; fuera del MVP.
- `halfvec`/subvector/binario: optimizaciones futuras con evaluación y re-ranking;
  no deben introducirse sin evidencia.

**Operación**: B-tree compuesto para filtros, `ANALYZE` después de cargas,
`EXPLAIN (ANALYZE, BUFFERS)` en benchmark y comparación ANN contra exact.

**Integración Python**: usar la dependencia oficial `pgvector` y su tipo SQLAlchemy
`Vector(1024)`, fijados reproduciblemente en `pyproject.toml` y lockfile. No usar
SQL vectorial manual. La extensión PostgreSQL existente sigue siendo la autoridad
de almacenamiento; la librería aporta mapping, serialización y validación ORM.

## R4 — PostgreSQL, concurrencia y atomicidad

**Decisión**: constraints/índices como árbitros de idempotencia, upsert selectivo,
row lock sobre el run/documento al reanudar y transacciones cortas.

**Evidencia**: PostgreSQL documenta que
[`ON CONFLICT DO UPDATE`](https://www.postgresql.org/docs/current/sql-insert.html)
garantiza un resultado atómico insert-or-update, y que
[`SELECT ... FOR UPDATE`](https://www.postgresql.org/docs/current/explicit-locking.html)
bloquea escritores competidores hasta terminar la transacción.

**Patrón**:

- Nunca mantener lock o sesión transaccional durante Ollama.
- Resolver identidad/estado en Tx1, inferir fuera, confirmar batch en Tx2.
- `uq_corpus_documents_source_external`: unique parcial `(source_name,
  external_id) WHERE ingestion_status <> 'FAILED'`; las filas fallidas se conservan
  como histórico/reintento sin bloquear la identidad vigente.
- `uq_corpus_documents_identity_active`: unique parcial `(source_identifier,
  raw_content_hash, normalized_content_hash) WHERE active_generation IS NOT NULL
  AND ingestion_status <> 'FAILED'`; staging e histórico inactivo no colisionan.
- Unique de hash por documento/generación y run_id global.
- Reindexación por generación staging + swap lógico atómico.
- Un constraint trigger diferible ejecutable en PostgreSQL valida al commit que
  `active_generation` exista, que solo haya una generación con chunks `ACTIVE` y
  que ningún chunk `ACTIVE` quede fuera de la generación apuntada. Se elimina con
  su función y triggers en el downgrade, y permite rollback del swap en una sola
  transacción.

La auditoría `semantic_search_runs` permanece minimizada: solo admite las seis
claves de filtros contractuales, `SUCCEEDED` o `FAILED`, y exige `request_id`. Un
timeout no es un tercer estado: se registra como `FAILED` con
`SEMANTIC_SEARCH_TIMEOUT`; `human_retrieval_evaluations` es la única tabla que
mantiene FK a documentos y chunks evaluados.

## R5 — Chunking jurídico

**Decisión**: parser de líneas/párrafos determinista con precedencia de patrones:
TITLE/HEADER → VISTO → CONSIDERANDO → intro dispositiva → ARTICLE → cierre →
autoridad/firma. Un artículo es unidad; considerandos largos se dividen por
párrafos; fallback agrupa párrafos completos dentro del límite.

**Rationale**: satisface el principio VII y preserva significado/orden. Los
patrones aceptan acentos, ordinales `°/º`, `Art.` y mayúsculas/minúsculas sin
reescribir texto sustantivo.

**Alternativas**: caracteres fijos rompe unidades; tokenización propietaria crea
dependencia; overlap amplio duplica señales. Se usa overlap cero por defecto y
solo contexto de encabezado estructurado como metadata.

## R6 — Seguridad del corpus

**Decisión**: root configurado, paths relativos, resolución canónica, rechazo de
symlinks, extensiones allowlist, límite antes/durante lectura y parsers sin
ejecución ni acceso a red.

**Rationale**: el corpus es no confiable; HTML es dato. Los mensajes públicos
usan identificadores sanitizados y nunca path absoluto/contenido. Prompt
injection no se procesa en 005 y se abordará al integrar generación en 006.

## R7 — Arquitectura existente

El grafo del repositorio confirma arquitectura por `domain`, `application`,
`ports`, `adapters`, `api`, `cli`; `UnitOfWork` async; `HealthService` con DB,
pgvector y Ollama; configuración Pydantic; handlers uniformes. 005 extiende esos
puntos sin cambiar contratos previos.

## R8 — Conservación y revisión humana

**Decisión**: conservar `raw_content` protegido en PostgreSQL junto con hashes y
versión normalizada. Todo documento nace `AUTOMATED`/`PENDING_REVIEW`; aprobación o
rechazo administrativo lo convierte en `HUMAN_REVIEWED`. La búsqueda normal filtra
`REVIEWED`; solo una evaluación administrativa opt-in puede incluir pendientes.
Esto maximiza reproducibilidad y evita depender de paths mutables sin exponer texto
original o normalizado completo por API/logs.

La protección usa credenciales backend y roles DB mínimos, acceso exclusivo por
repositorio/servicio/herramienta autorizada y mappers explícitos; no existe endpoint
público de descarga ni serialización directa de ORM. No se agrega cifrado de columna
en 005. Tests buscan fugas de `raw_content`, `normalized_content`, `Authorization`,
`token` y `storage_path` en respuestas públicas y structured logs.

La revisión usa optimistic locking explícito: `review_version` comienza en 1 y el
repositorio ejecuta compare-and-swap por id, versión y estado esperado. Esta opción
evita locks de larga duración, permite distinguir conflictos contractuales y asegura
que dos revisores concurrentes no produzcan lost update ni doble auditoría.

## R9 — Métricas y baseline G3

**Decisión**: G3 calcula Recall@3/5, Precision@3/5, MRR, p50/p95/máximo, promedio
de utilidad jurídica 1–5 y porcentaje legalmente relevante. El fixture con queries
permanece privado/controlado y la evaluación humana usa identificadores seudónimos.
El primer baseline es informativo, carece de umbral contractual previo y no bloquea
CI; un incremento posterior podrá proponer umbrales con evidencia real.

## R10 — Coordinación del Ollama compartido

**Decisión**: coordinador async local con un slot, cola acotada y prioridad
`INTERACTIVE` > `SEARCH` > `BATCH_INGESTION`. La prioridad solo adelanta trabajo no
iniciado; los batches hacen yield y fairness acotada evita monopolio. Timeout,
cancelación y error liberan el slot. No se introduce infraestructura distribuida ni
se modifica generación; `INTERACTIVE` queda reservado para integración posterior.

## R11 — Seguridad de dependencias

**Decisión**: ejecutar `pip-audit` o la herramienta ya adoptada en una tarea/CI
reproducible separada de tests unitarios. Vulnerabilidades críticas o altas bloquean
el cierre salvo excepción documentada y aprobada. El resultado se documenta sin
descargar bases de vulnerabilidades durante tests ordinarios.

## Conclusión

No quedan incógnitas contractuales para reanalizar. La investigación fija el modelo
0.6B, 1024 dimensiones, `pgvector` Python, revisión humana, evaluación constitucional,
coordinación local y auditoría fail-closed. G1-B continúa como aceptación operativa
externa pendiente, sin volver incierto el contrato vectorial. Estado actual:
`IMPLEMENTATION_EXTERNAL_GATE_PENDING`.

## R12 – Evidencia de fases 5–18

La implementación mantiene `corpus ingest` en dry-run por defecto y habilita
`--execute` únicamente con configuración contractual, persistencia de staging,
batches deterministas, inferencia fuera de transacciones y swap atómico. El
puerto de deduplicación persistida sigue siendo estrictamente read-only en
dry-run. Las pruebas cubren upsert tipado y concurrente, discovery con fallos
aislados, persistencia de runs/failures/batches, resume, reindexación, búsqueda
exacta filtrada, health, observabilidad y evaluación fake.

## G1-B â€” Probe externo ejecutado

El probe sanitizado se ejecutÃ³ desde el entorno local contra la URL HTTPS
configurada, usando Bearer sin imprimir el token ni vectores. `/api/version` y
`/api/show` respondieron 200, pero `/api/embed` respondiÃ³ 404
(`G1_EMBED_FAILED`). La dimensiÃ³n contractual sigue fijada en 1024, pero G1-B
permanece `BLOCKED_EXTERNAL` hasta que la ruta Funnel/Nginx exponga el endpoint
contractual y se realice el retest desde Docker/local. No se acepta localhost,
mock ni fake para cerrar este gate.

## Dependency audit evidence

The reproducible dependency audit on 2026-08-05 used
`uv run --with pip-audit pip-audit` and reported no known vulnerabilities. The
sanitized evidence is `evidence/pip-audit-2026-08-05.json`; it contains no
credentials or corpus content.

## G2/G3/G4 evidence

The local PostgreSQL explain baseline and a rollback-safe 5,000-row synthetic
comparison are recorded in `evidence/g2-exact-explain.txt` and
`evidence/g2-index-evaluation.json`. The temporary HNSW benchmark reached
recall@20=1.0, but exact cosine search remains the MVP baseline and HNSW is not
enabled by migration or application. The
versioned fake evaluation baseline is informational and non-blocking in
`evidence/g3-quality-baseline.json`. The validated operational limits and
timeouts are recorded without inventing an SLA in
`evidence/g4-operational-limits.json`.
