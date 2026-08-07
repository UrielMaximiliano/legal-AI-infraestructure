# Especificación de Infraestructura: Ingesta de Corpus y Recuperación Semántica

**ID de Especificación**: `005-corpus-ingestion-and-semantic-retrieval`
**Creada**: 2026-08-04
**Estado**: `IMPLEMENTATION_EXTERNAL_GATE_CLOSED`
**Entrada**: Descripción del usuario: "Crear un pipeline robusto, trazable y reproducible para ingesta de corpus jurídico y recuperación semántica"

## Resumen ejecutivo *(obligatorio)*

Este incremento habilita la ingesta offline y la búsqueda semántica online de
un corpus local homogéneo de decretos nacionales de designación transitoria.
Debe descubrir, extraer, normalizar, validar, deduplicar, fragmentar e indexar
documentos de forma determinista, reanudable y auditable. Las consultas deben
recuperar fragmentos trazables con filtros obligatorios y sin exponer contenido,
vectores, secretos ni rutas internas.

El incremento se limita a antecedentes de redacción. No integra resultados con
la generación de borradores, no implementa RAG normativo y no modifica los
contratos de los incrementos 001–004. La integración con generación queda
reservada para `006-rag-assisted-document-generation`.

## Clarifications

### Sesión 2026-08-04

- Q: ¿Qué dimensión y endpoint contractual debe usar 005? → A: Para
  `qwen3-embedding:4b-q4_K_M`, la dimensión es 2560 y G1 debe comprobar desde
  Docker/local el perfil de endpoint configurado. `/api/embed` devuelve batches
  nativos cuando está expuesto; `/api/embeddings` devuelve un embedding por
  prompt y la aplicación conserva el batch de forma secuencial. Todo cambio de
  modelo, dimensión o perfil requiere revalidación y reindexación cuando aplique.
- Q: ¿Qué semántica exacta debe tener `corpus ingest PATH` sin `--execute`? → A:
  Dry-run sin persistencia ni solicitudes de embeddings; `--execute` es la única
  autorización explícita para generar y persistir documentos, chunks y vectores.
- Q: ¿Cómo debe auditar 005 las búsquedas semánticas? → A: Mediante
  `semantic_search_runs` minimizada, sin consulta, embedding, contenido, excerpts,
  tokens, autorización, rutas internas ni stack traces.
- Q: ¿Cómo se satisfacen conservación, procedencia y revisión humana? → A: El MVP
  conserva `raw_content` protegido en PostgreSQL, distingue procedencia automática
  y humana, inicia cada documento en `PENDING_REVIEW` y busca solo `REVIEWED` por
  defecto; la evaluación administrativa puede incluir pendientes explícitamente.
- Q: ¿Qué evaluación constitucional y SLO aplica? → A: G3 informa Recall@3/5,
  Precision@3/5, MRR, utilidad jurídica humana y relevancia legal; el primer
  baseline es informativo, no bloquea CI y no inventa umbrales sin evidencia.
- Q: ¿Cómo se coordina el Ollama compartido? → A: Un `InferenceCoordinator` local
  limita a una inferencia activa, con prioridad INTERACTIVE > SEARCH >
  BATCH_INGESTION, cola acotada, timeout, cancelación y fairness entre lotes.
- Q: ¿Qué ocurre si no puede persistirse la auditoría de búsqueda? → A: Política
  fail-closed: no se entregan resultados y se responde HTTP 503 con
  `SEMANTIC_SEARCH_AUDIT_UNAVAILABLE`, tras como máximo un retry transitorio acotado.
- Q: ¿Qué bloquea G1-B y cómo se protege `raw_content`? → A: G1-A ya fijó
  `qwen3-embedding:4b-q4_K_M`/2560 y autoriza `halfvec(2560)`; G1-B solo bloquea la
  aceptación operativa externa. `raw_content` se accede exclusivamente mediante
  repositorio, `CorpusReviewService` o herramientas administrativas autorizadas,
  nunca mediante DTOs, serialización genérica, respuestas, logs o métricas.
- Q: ¿Cómo se separan revisión y coordinación? → A: `CorpusReviewService` concentra
  transiciones/auditoría y el CLI solo lo invoca. `InferenceCoordinationPort` es el
  contrato inyectable y `InferenceCoordinator` su implementación de aplicación.
- Q: ¿Cómo evita la revisión actualizaciones perdidas? → A: Cada documento conserva
  `review_version` desde 1; CLI y servicio exigen `expected_version` y el repositorio
  ejecuta compare-and-swap atómico por id, versión y estado esperado. Exactamente
  una operación concurrente gana y cada transición válida incrementa una vez.

## Declaración del problema *(obligatorio)*

### Estado actual

El sistema ya dispone de API, persistencia relacional y vectorial, ejecución
local reproducible, acceso privado a Ollama, generación de borradores, revisión
humana, exportación, reintentos, reconciliación, observabilidad y auditoría.
Sin embargo, todavía no existe un proceso contractual para convertir un corpus
local en antecedentes jurídicos normalizados, fragmentados, vectorizados y
consultables, ni un dataset reproducible para medir la recuperación.

### Estado deseado

El sistema contará con dos flujos estrictamente separados:

1. Un pipeline offline que procesa archivos locales permitidos, conserva
   trazabilidad, tolera fallas por archivo, evita duplicados, permite reanudar y
   deja cada documento y fragmento en un estado verificable.
2. Un pipeline online que normaliza una consulta, aplica filtros obligatorios,
   obtiene resultados ordenados y trazables, y falla de manera segura cuando el
   proveedor, el modelo o la dimensión contractual no son compatibles.

Ambos flujos utilizarán el proveedor privado autorizado, limitarán la
concurrencia a una inferencia activa y seguirán funcionando de manera
determinista en pruebas mediante doubles, sin depender de su disponibilidad.

### Impacto institucional

- Hace posible localizar antecedentes de redacción de manera consistente y
  auditable antes de incorporar RAG a la generación.
- Reduce el riesgo de usar documentos duplicados, mal clasificados o alterados.
- Permite comparar la calidad de recuperación con métricas reproducibles.
- Contiene el riesgo de fuga de documentos jurídicos, consultas, secretos y
  rutas del host.
- Mantiene operativos los incrementos 001–004 cuando Ollama no está disponible.

## Alcance

### Incluido

- Corpus homogéneo con `document_type=decreto`,
  `document_subtype=designacion_transitoria`, `jurisdiction=nacion`,
  `language=es` y fuente Boletín Oficial de la República Argentina.
- Descubrimiento local de `.txt`, `.json` y `.html` limpio o
  semiestructurado; validación segura de rutas, extensiones y límites.
- Normalización determinista y versionada sin alterar contenido jurídico
  sustantivo.
- Validación contractual de metadatos, deduplicación exacta y reingesta
  idempotente.
- Chunking jurídico por estructura documental, con fallback determinista.
- Embeddings por lotes mediante un proveedor independiente del generador.
- Persistencia relacional y vectorial con dimensión fija y validada.
- Comandos administrativos de ingesta y reindexación, con salida JSON.
- Búsqueda semántica interna con filtros MVP obligatorios.
- Evaluación reproducible de recuperación, health/readiness, auditoría,
  observabilidad y documentación operativa.

### Fuera de alcance

- Google Drive directo, sincronización automática, scraping, crawling,
  scheduling, OCR, PDF y ejecución de HTML o scripts.
- RAG normativo, generación asistida por RAG, modificación de drafts o del
  servicio de generación.
- Re-ranking, BM25, búsqueda híbrida, deduplicación semántica aproximada,
  fine-tuning y MCP.
- Frontend, firma digital, base vectorial cloud, Redis, Celery, Kafka, colas
  externas o nuevos microservicios.
- Cambios a contratos, migraciones o comportamiento de 001–004.

## Escenarios de usuario y pruebas

### Escenario 1 — Ingesta segura y reproducible (Prioridad P1)

Un operador autorizado previsualiza o ejecuta la ingesta de una ruta local. El
sistema procesa los archivos soportados en orden estable, informa resultados y
fallas por etapa, y conserva un `run_id` que permite auditoría y reanudación.

**Prueba independiente**: con un corpus controlado mixto, la ejecución produce
conteos coherentes, documentos y chunks trazables; una segunda ejecución
idéntica no duplica datos ni embeddings.

**Escenarios de aceptación**:

1. **Dado** un corpus válido, **cuando** se ejecuta la ingesta, **entonces** cada
   archivo alcanza `COMPLETED` o registra una falla sanitizada y los documentos
   válidos quedan disponibles para búsqueda.
2. **Dado** un archivo inválido, **cuando** no se solicita `fail-fast`,
   **entonces** el archivo falla aisladamente y los restantes continúan.
3. **Dado** el mismo corpus y configuración, **cuando** se reingiere,
   **entonces** hashes, orden y fragmentos son reproducibles y no hay duplicados.
4. **Dado** un dry-run, **cuando** finaliza, **entonces** se informa el efecto
   esperado sin persistir documentos, chunks, vectores ni cambios de estado.

### Escenario 2 — Recuperación semántica filtrada (Prioridad P1)

Un consumidor interno busca antecedentes de una designación transitoria. La
consulta exige los tres filtros del MVP y devuelve los fragmentos más similares
con contexto y procedencia suficientes para revisión humana.

**Prueba independiente**: una consulta del dataset controlado devuelve los
positivos esperados en orden estable, respeta filtros y nunca expone el vector o
el documento completo.

**Escenarios de aceptación**:

1. **Dada** una consulta válida y filtros compatibles, **cuando** se busca,
   **entonces** se devuelven hasta `top_k` resultados en similitud descendente.
2. **Dada** una consulta sin coincidencias sobre el umbral, **cuando** se busca,
   **entonces** se devuelve una colección vacía válida.
3. **Dado** un filtro obligatorio ausente, **cuando** se busca, **entonces** se
   rechaza la solicitud con error contractual sanitizado.
4. **Dado** un modelo o dimensión incompatible, **cuando** se busca, **entonces**
   no se comparan vectores y se informa claramente la incompatibilidad.

### Escenario 3 — Reindexación sin pérdida (Prioridad P2)

Un operador reindexa documentos seleccionados tras cambiar una versión de
normalización, chunking, modelo o dimensión. Los resultados anteriores siguen
disponibles hasta confirmar el reemplazo y el proceso puede reanudarse.

**Prueba independiente**: una falla inducida durante la reindexación conserva el
índice válido anterior; al reanudar, solo se procesa el trabajo pendiente.

### Escenario 4 — Evaluación reproducible (Prioridad P2)

Un evaluador ejecuta un dataset versionado con consultas, positivos, negativos,
variantes, duplicados y filtros incompatibles, usando embeddings falsos o el
proveedor real opcional.

**Prueba independiente**: dos ejecuciones con fake determinista producen las
mismas métricas y un reporte comparable.

### Casos límite

- Corpus vacío, archivo vacío, JSON malformado, HTML sin texto útil y documento
  sin marcadores jurídicos.
- BOM, Unicode descompuesto, controles inválidos, saltos mixtos y variantes de
  `ARTÍCULO`, `ARTICULO`, `CONSIDERANDO`, `Por ello`, `DECRETA` y `RESUELVE`.
- Artículo o considerando mayor que el límite, cita extensa, expediente, fecha o
  norma cerca del límite de chunk.
- Duplicado por hash, conflicto entre `external_id` y contenido actualizado, y
  repetición parcial dentro del mismo documento.
- Path traversal, symlink que escapa del root, archivo que cambia durante la
  lectura, extensión/MIME incompatible y límites exactos o excedidos en un byte.
- Batch con cantidad incorrecta, vector vacío, NaN, infinito o dimensión errónea.
- Timeout, 401, 403, 429 y error 5xx del proveedor; falla de persistencia después
  de obtener embeddings.
- Empates de similitud, fecha ausente, `top_k` mínimo/máximo y score en límites.

## Requisitos de infraestructura *(obligatorio)*

### Requisitos funcionales

#### Descubrimiento, extracción y normalización

- **RF-001**: El sistema DEBE descubrir únicamente archivos regulares permitidos
  bajo un root autorizado, en orden estable, sin traversal ni escape por symlink.
- **RF-002**: El sistema DEBE admitir inicialmente `.txt`, `.json` y `.html`,
  validar formato/tamaño y tratar todo contenido como no confiable.
- **RF-003**: El sistema DEBE extraer texto sin ejecutar HTML, scripts, enlaces o
  instrucciones presentes en el corpus.
- **RF-004**: La normalización DEBE ser determinista, idempotente y versionada;
  usar Unicode NFC, saltos uniformes, remover BOM/controles inválidos, colapsar
  espacios redundantes y preservar párrafos, acentos, expedientes, fechas,
  normas y organismos.
- **RF-005**: La normalización DEBE retirar artefactos web, navegación y
  encabezados/pies repetitivos configurados, y normalizar variantes estructurales
  sin cambiar significado jurídico.
- **RF-006**: Cada documento DEBE registrar hashes SHA-256 del contenido original
  y normalizado, conservar `raw_content` protegido en PostgreSQL y nunca publicar
  texto completo ni rutas absolutas. “Protegido” significa acceso backend por
  mínimo privilegio y únicamente mediante `CorpusDocumentRepository`,
  `CorpusReviewService` o herramientas administrativas autorizadas; queda excluido
  de DTOs públicos, schemas API/search, serialización genérica, `repr`, logs,
  excepciones, métricas, runs y failures. Los ORM nunca se devuelven desde rutas y
  mappers explícitos separan persistencia, dominio y DTO. Los excerpts provienen
  solo de chunks y respetan su límite contractual.

#### Metadatos y deduplicación

- **RF-007**: Todo documento DEBE validar `external_id`, `document_type`,
  `document_subtype`, `jurisdiction`, `language` y `source_name` mediante valores
  contractuales normalizados; `unknown` solo será válido si se documenta.
- **RF-008**: La búsqueda MVP DEBE requerir `document_type`,
  `document_subtype` y `jurisdiction`.
- **RF-009**: El sistema DEBE deduplicar por hash normalizado y por la combinación
  de fuente e identificador externo, y distinguir un duplicado de una actualización.
- **RF-010**: La reingesta DEBE ser idempotente y solo regenerar embeddings si
  cambia el contenido normalizado, modelo, dimensión, versión de normalización o
  versión de chunking.

#### Chunking jurídico

- **RF-011**: El sistema DEBE reconocer `HEADER`, `TITLE`, `VISTO`,
  `CONSIDERANDO`, `DISPOSITIVE_INTRO`, `ARTICLE`, `CLOSING`, `AUTHORITY`,
  `SIGNATURE` y `UNKNOWN`.
- **RF-012**: Cada artículo DEBE permanecer como unidad cuando sea posible; los
  considerandos extensos solo podrán subdividirse por párrafos completos.
- **RF-013**: Los chunks DEBEN conservar orden, sección, índices estables,
  referencia al documento y versión del algoritmo.
- **RF-014**: El sistema NO DEBE cortar expedientes, citas legales, artículos,
  nombres de normas o fechas, y DEBE aplicar un fallback determinista cuando no
  exista estructura reconocible.
- **RF-015**: El conteo de tokens DEBE ser reproducible y declararse informativo
  cuando no se use un tokenizer exactamente compatible.

#### Embeddings y persistencia

- **RF-016**: La generación de embeddings DEBE estar separada de la generación
  de texto y admitir documentos por lote, consultas, health check y fake
  determinista para pruebas.
- **RF-017**: Las solicitudes al proveedor DEBEN usar autenticación privada,
  timeout explícito, lotes limitados y como máximo una inferencia activa.
- **RF-047**: Un `InferenceCoordinator` local DEBE arbitrar una cola acotada con
  prioridad `INTERACTIVE` > `SEARCH` > `BATCH_INGESTION`, timeout de espera,
  cancelación, métricas y liberación garantizada del slot. La prioridad adelanta
  lotes aún no iniciados, nunca interrumpe una inferencia activa; los batches
  ceden el control entre lotes y ninguna transacción DB permanece abierta durante
  la espera o inferencia. No requiere Redis, Celery ni Kafka y reserva
  `INTERACTIVE` para integración posterior sin modificar 001–004.
- **RF-018**: Solo se reintentarán errores transitorios con backoff acotado; los
  errores contractuales 4xx no se reintentarán, excepto respuestas explícitamente
  transitorias como limitación temporal.
- **RF-019**: Antes de persistir, el sistema DEBE validar cantidad, dimensión,
  valores finitos y vectores no vacíos; ningún batch inválido podrá dejar
  vectores parciales visibles.
- **RF-020**: `EMBEDDING_DIMENSIONS` DEBE coincidir con evidencia reproducible del
  modelo y proveedor; cambiarla requiere migración y reindexación completas.
- **RF-021**: G1-A está cerrado por evidencia local del servidor y fija
  `qwen3-embedding:4b-q4_K_M`, `EMBEDDING_DIMENSIONS=2560` y `halfvec(2560)` para la
  migración 005. G1-B valida únicamente la ruta externa Docker/local →
  HTTPS/Bearer → Funnel/Nginx → Ollama remoto; no bloquea planificación, tasks,
  implementación, migración ni tests con fake, y no reabre el contrato vectorial.
  Sí bloquea la aceptación operativa del proveedor remoto, el cierre completo de
  la integración externa y el smoke real desde Docker/local. Cualquier mismatch se
  rechaza; cambiar modelo o dimensión exige migración y reindexación completas.

#### Ejecución y estados

- **RF-022**: La ingesta DEBE transitar por `DISCOVERED`, `PARSED`, `NORMALIZED`,
  `VALIDATED`, `CHUNKED`, `EMBEDDING`, `INDEXED` y `COMPLETED`, o registrar uno de
  los estados de falla específicos de etapa.
- **RF-023**: Una falla de archivo no abortará el lote salvo `fail-fast`; cada
  fallo DEBE ser sanitizado, clasificable y trazable.
- **RF-024**: El sistema DEBE usar operaciones de persistencia cortas y no
  mantenerlas abiertas durante inferencia; la confirmación de un batch será
  atómica cuando sea viable.
- **RF-025**: Cada ejecución autorizada con `--execute` DEBE aceptar un `run_id`
  idempotente, registrar un snapshot sanitizado de configuración y poder reanudar
  trabajo pendiente. Un dry-run puede mostrar el `run_id` propuesto en su salida,
  pero no lo registra ni crea trabajo reanudable.
- **RF-026**: El comando `corpus ingest PATH` DEBE admitir las opciones de
  metadatos, batch, modelo, dimensión, resume, run-id, limit, fail-fast y salida
  JSON descritas por el solicitante. Sin `--execute`, el comportamiento
  predeterminado DEBE ser dry-run: realiza descubrimiento, parseo, normalización,
  validación de metadatos, chunking, estimación de operaciones y validación de
  configuración. No inserta documentos o chunks, no solicita embeddings, no crea
  ni modifica vectores y no cambia estados persistidos. Solo
  `corpus ingest PATH --execute` autoriza solicitar embeddings y persistir los
  resultados; no se admitirá una opción alternativa ambigua como `--persist`.
- **RF-027**: `corpus reindex` DEBE filtrar por documento y metadatos/versiones,
  admitir dry-run/resume/run-id, conservar el índice válido hasta confirmar el
  reemplazo y permitir rollback lógico.
- **RF-048**: `corpus reindex` sin `--execute` DEBE producir un reporte
  determinista con cero llamadas a Ollama, escrituras DB, `ingestion_runs`,
  `embedding_batches`, generaciones, swaps, cambios de estado o trabajo reanudable.

#### Búsqueda semántica

- **RF-028**: `POST /api/v1/semantic-search` DEBE aceptar consulta, los filtros
  MVP obligatorios y, opcionalmente, `language`, `organization`, `top_k` y
  `minimum_score`, dentro de límites contractuales.
- **RF-029**: La consulta DEBE normalizarse de manera determinista, tener límite
  de longitud y no registrarse completa en logs.
- **RF-030**: La búsqueda DEBE usar similitud coseno, score normalizado y
  documentado, orden descendente y desempate estable por fecha de publicación,
  documento y sección.
- **RF-031**: La respuesta DEBE contener únicamente identificadores, título,
  sección, artículo, excerpt limitado, score, fecha, fuente, organización,
  metadata permitida, modelo y dimensión.
- **RF-032**: La respuesta NO DEBE exponer embeddings, contenido completo, texto
  crudo, rutas, secretos, stack traces ni metadata sensible.
- **RF-033**: La ausencia de resultados será válida; timeout, proveedor no
  disponible y mismatch de modelo/dimensión tendrán errores claros y sanitizados.
- **RF-034**: La auditoría de búsquedas DEBE persistir una fila minimizada en
  `semantic_search_runs` con `id`, `query_hash`, `filters_sanitized`, `top_k`,
  `minimum_score`, `embedding_model`, `embedding_dimensions`, `result_count`,
  `duration_ms`, `status`, `error_code`, `request_id` y `created_at`. No DEBE
  almacenar la consulta completa, su embedding, contenido recuperado, tokens,
  autorización ni rutas internas.
- **RF-049**: La auditoría de búsqueda es fail-closed. El servicio DEBE generar el
  embedding y preparar resultados sin transacción DB abierta, persistir después la
  auditoría y solo entonces responder. Si esa escritura falla o vence su timeout,
  no entrega resultados parciales y responde HTTP 503 con
  `SEMANTIC_SEARCH_AUDIT_UNAVAILABLE`, envelope sanitizado, `request_id` y timestamp;
  admite como máximo un retry acotado cuando el fallo sea claramente transitorio.

#### Modelo de información y migración

- **RF-035**: `corpus_documents` DEBE conservar identidad, clasificación,
  procedencia, `raw_content` protegido, hashes, contenido normalizado, metadata,
  versiones, estados de revisión y timestamps; la fuente más `external_id` será
  única cuando este exista. Debe incluir `source_identifier` sanitizado,
  `provenance_type`, `review_status`, revisor/notas opcionales y versión del pipeline.
- **RF-036**: `corpus_chunks` DEBE conservar documento, sección, posición,
  artículo, contenido, conteo estimado, hash, vector, modelo, dimensión,
  versiones, metadata y timestamps, con orden estable y hashes no duplicados
  dentro del documento cuando corresponda.
- **RF-037**: `ingestion_runs` DEBE conservar identidad, fuente sanitizada,
  estado, modo de ejecución, conteos, tiempos, configuración y resumen de error
  sanitizados únicamente para ejecuciones autorizadas con `--execute`. El dry-run
  no crea una fila y comunica sus estimaciones solo mediante la salida solicitada.
- **RF-038**: `ingestion_failures` DEBE conservar ejecución, fuente sanitizada,
  etapa, código, mensaje, reintentabilidad y timestamp.
- **RF-039**: `embedding_batches` solo se incorporará si resulta necesario para
  reanudabilidad, trazabilidad, retry o procesamiento por lotes.
- **RF-040**: La migración 005 DEBE validar soporte vectorial, crear tablas,
  restricciones e índices con dimensión fija y tener downgrade seguro que solo
  quite objetos de 005 y no elimine la extensión si otros incrementos la usan.

#### Evaluación, salud y documentación

- **RF-041**: El dataset versionado DEBE cubrir consultas esperadas, positivos,
  negativos, variantes, filtros incompatibles, ambigüedad, duplicados y
  documentos sin estructura.
- **RF-042**: La evaluación DEBE informar Recall@3, Recall@5, Precision@3,
  Precision@5, MRR, latencias p50/p95/máxima, promedio de utilidad jurídica humana
  1–5 y porcentaje de resultados legalmente relevantes. El dataset privado y
  versionado conserva `query_id`, `query_text`, documentos esperados/relevantes,
  secciones esperadas, dificultad y notas. Las evaluaciones humanas persisten en
  `human_retrieval_evaluations` sin nombres completos ni datos sensibles.
- **RF-043**: Debe poder ejecutarse con fake determinista y opcionalmente con el
  proveedor real, dejando resultados y configuración documentados.
- **RF-044**: Liveness y readiness DEBEN distinguir base de datos, capacidad
  vectorial, proveedor y compatibilidad modelo/dimensión.
- **RF-045**: La indisponibilidad del proveedor DEBE bloquear nueva ingesta con
  embeddings y nuevas búsquedas, pero no lectura existente ni funciones 001–004.
- **RF-046**: La entrega DEBE documentar investigación de dimensión e índices,
  modelo de datos, quickstart, contratos HTTP/CLI, reindexación, recuperación,
  límites, seguridad, evaluación y configuración sin secretos.
- **RF-050**: La integración SQLAlchemy DEBE usar la dependencia Python oficial
  `pgvector` con `HALFVEC(2560)` y versiones reproducibles. El cierre DEBE ejecutar
  un escaneo de dependencias separado de tests ordinarios; vulnerabilidades altas o
  críticas bloquean salvo excepción documentada y aprobada.
- **RF-051**: El CLI administrativo DEBE soportar
  `corpus review DOCUMENT_ID --approve --reviewed-by "..." --expected-version N`
  y `corpus review DOCUMENT_ID --reject --reason "..." --reviewed-by "..."
  --expected-version N`, donde N es entero positivo obligatorio.
  `CorpusReviewService` DEBE cargar por repositorio/UoW, validar existencia,
  versión esperada y transición, exigir revisor textual y motivo al rechazar,
  actualizar revisión/procedencia, persistir auditoría y producir salida sanitizada.
  Approve/reject son excluyentes; el CLI solo invoca el servicio y nunca manipula
  entidades/ORM/repositorios ni expone contenido original/normalizado. `REVIEWED` y
  `REJECTED` son terminales en el MVP: toda transición posterior devuelve conflicto
  sanitizado y requiere un incremento explícito para habilitar reapertura. El
  repositorio DEBE ejecutar un compare-and-swap atómico con `id`, `review_version`
  y `review_status` esperados; cada transición válida incrementa `review_version`
  exactamente en uno. Cero filas actualizadas DEBE distinguir documento inexistente,
  versión obsoleta y transición inválida sin exponer contenido.
- **RF-052**: La revisión DEBE usar los códigos estables
  `CORPUS_DOCUMENT_NOT_FOUND` (404), `CORPUS_REVIEW_VERSION_MISMATCH` (409),
  `INVALID_CORPUS_REVIEW_TRANSITION` (409), `CORPUS_REVIEW_REASON_REQUIRED` (422) y
  `CORPUS_REVIEWER_REQUIRED` (422). Solo el mismatch puede incluir
  `expected_version`/`current_version`; ningún error contiene texto documental ni
  datos sensibles. La respuesta exitosa incluye documento, estado, versión, revisor
  y timestamp, nunca contenido original o normalizado.

### Requisitos no funcionales

#### Rendimiento

- La búsqueda tendrá timeout configurable, `top_k` contractual y medirá p50,
  p95 y máximo sobre el dataset de referencia.
- Los tamaños de archivo, cantidad de archivos, bytes de entrada del proveedor,
  batch de embeddings y longitud de consulta serán límites configurables y
  probados en el valor exacto y en el primer valor inválido.
- La estrategia de índice comenzará con búsqueda exacta para corpus pequeño; un
  índice aproximado solo se habilitará tras medir tamaño, recall y latencia.

#### Disponibilidad

- Una caída temporal de Ollama no debe corromper ni invalidar datos ya indexados.
- Las ejecuciones interrumpidas deben reanudarse sin repetir trabajo confirmado.
- Las pruebas unitarias y contractuales estándar no dependerán del proveedor real.

#### Seguridad y privacidad

- El corpus nunca se enviará a APIs cloud y jamás se interpretará como
  instrucciones.
- Tokens y secretos provendrán de configuración segura y se redactarán en logs,
  errores, snapshots y métricas.
- No se publicarán contenido completo, consultas completas, vectores, rutas
  absolutas, headers de autorización ni stack traces.
- La validación cubrirá traversal, symlink escape, MIME/extensión, límites,
  timeouts, HTML no ejecutable y errores sanitizados, manteniendo el envelope
  público compatible con 003–004.

#### Escalabilidad

- El procesamiento por lotes debe admitir corpus crecientes sin introducir
  colas externas y respetar una sola inferencia activa.
- La selección entre búsqueda exacta y HNSW se basará en evidencia; IVFFlat no
  se introducirá sin una necesidad medida.
- Modelo y dimensión serán configurables, pero cada índice lógico permanecerá
  homogéneo y todo cambio requerirá reindexación controlada.

## Objetivos de nivel de servicio (SLO) *(obligatorio)*

- **SLO-001 — Reproducibilidad**: el 100% de dos ingestas consecutivas del mismo
  corpus y configuración produce iguales hashes, orden, secciones e índices.
- **SLO-002 — Idempotencia**: el 100% de reingestas sin cambios crea cero
  documentos, chunks o embeddings duplicados.
- **SLO-003 — Aislamiento de fallas**: en un lote con archivos inválidos, el 100%
  de los archivos válidos se procesa salvo `fail-fast` explícito.
- **SLO-004 — Integridad vectorial**: el 100% de vectores persistidos tiene la
  cantidad y dimensión contractual y contiene solo valores finitos.
- **SLO-005 — Recuperación**: G3 genera un baseline informativo versionado con
  Recall@3/5, Precision@3/5, MRR, utilidad jurídica humana y relevancia legal. No
  existe un umbral contractual previo a la primera evaluación real y el resultado
  no bloquea CI inicialmente. Un incremento posterior podrá proponer umbrales
  basados en evidencia y toda regresión se informará con igual dataset/configuración.
- **SLO-006 — Latencia**: el 95% de búsquedas del dataset de referencia termina
  dentro del timeout configurado y se reportan p50, p95 y máximo.
- **SLO-007 — Seguridad**: cero secretos, vectores, rutas absolutas, documentos o
  consultas completas aparecen en respuestas públicas y logs de fixtures.
- **SLO-008 — Recuperabilidad**: el 100% de ejecuciones interrumpidas en puntos de
  prueba reanuda sin perder trabajo confirmado ni publicar batches parciales.
- **SLO-009 — Compatibilidad**: el 100% de pruebas de regresión de 001–004 continúa
  aprobando con el proveedor de embeddings disponible o no disponible.

## Restricciones de costo *(obligatorio)*

### Presupuesto

El incremento debe reutilizar la infraestructura existente: PostgreSQL con
capacidad vectorial, Docker Compose y Ollama externo. No se autoriza un servicio
cloud, una base vectorial adicional, una cola externa ni nueva infraestructura
de GPU. El costo incremental esperado se limita a almacenamiento, cómputo de
base de datos y uso del servidor Ollama ya autorizado.

### Optimización de costo

La reingesta evita embeddings sin cambios; la reindexación es selectiva y
reanudable; los lotes respetan límites de recursos; y los índices aproximados
solo se incorporan cuando mediciones reproducibles justifican su costo.

## Requisitos de cumplimiento

### Marco de gobierno

- Constitución del proyecto v1.0.0, especialmente principios I, III, IV, VI,
  VII, VIII, IX, X, XVI, XVII, XVIII, XIX y XX.
- Minimización, trazabilidad y revisión humana de los antecedentes recuperados.
- Los documentos nacionales son antecedentes de redacción y no deben presentarse
  como normativa provincial aplicable.

### Requisitos de datos

- Conservar procedencia, identidad, hashes, versiones y relación documento–chunk.
- Conservar texto original protegido, versión procesada y fuente; distinguir siempre
  procedencia `AUTOMATED`/`HUMAN_REVIEWED` y revisión `PENDING_REVIEW`/`REVIEWED`/
  `REJECTED`. Todo documento inicia pendiente y la búsqueda normal usa solo revisados.
- No guardar rutas absolutas públicamente ni secretos en tablas, JSON, logs o
  reportes.
- La retención y eliminación seguirán la política general del proyecto; 005 no
  incorpora borrado automático destructivo.

## Criterios de éxito *(obligatorio)*

### Validación de artefactos

- [ ] La migración 005 aplica y revierte sin modificar objetos de 001–004.
- [ ] El corpus homogéneo se ingiere, reingiere y reindexa de forma reproducible.
- [ ] Normalización, metadatos, deduplicación y chunking cumplen sus contratos.
- [ ] Modelo y dimensión están comprobados, documentados y validados estrictamente.

### Validación de seguridad

- [ ] Ningún test de traversal, symlink, HTML, límites o formato evade controles.
- [ ] Logs, salidas JSON, errores y respuestas no contienen datos prohibidos.
- [ ] El proveedor privado recibe autenticación sin exposición del token.
- [ ] El texto original permanece protegido, la revisión humana es auditable y la
      búsqueda normal recupera exclusivamente documentos `REVIEWED`.
- [ ] El escaneo reproducible no informa vulnerabilidades altas/críticas sin una
      excepción documentada y aprobada.

### Validación de rendimiento y calidad

- [ ] La evaluación versionada informa Recall@3/5, Precision@3/5, MRR, p50/p95/
      máximo, utilidad jurídica humana y porcentaje legalmente relevante.
- [ ] Búsqueda exacta constituye el baseline; cualquier HNSW conserva calidad
      aceptable medida y mejora una necesidad documentada.
- [ ] Los límites de archivos, lotes, consultas, `top_k` y timeout se verifican.

### Validación operativa

- [ ] Resume, retry transitorio, rollback lógico y fallas parciales no corrompen datos.
- [ ] El coordinador mantiene una sola inferencia activa, prioridades y fairness sin deadlock.
- [ ] La falla de auditoría devuelve 503 sin exponer resultados parciales.
- [ ] Dos revisores con igual versión producen una sola transición/auditoría y el
      perdedor recibe `CORPUS_REVIEW_VERSION_MISMATCH` sin lost update.
- [ ] Health/readiness distinguen degradación del proveedor sin afectar 001–004.
- [ ] Existen ejemplos reproducibles de ingesta, búsqueda, reindexación y recuperación.
- [ ] Tests con fake son deterministas y la evaluación real es opcional.

## Entidades clave

| Entidad | Propósito | Identidad y reglas clave |
|---|---|---|
| `corpus_documents` | Documento normalizado y su procedencia | UUID; fuente + external_id único cuando exista; hash normalizado indexado |
| `corpus_chunks` | Unidad jurídica recuperable | UUID; pertenece a un documento; orden estable; vector homogéneo |
| `ingestion_runs` | Ejecución auditable y reanudable | `run_id` único; conteos y snapshot sanitizado |
| `ingestion_failures` | Falla aislada por etapa | Vinculada a ejecución; código estable y mensaje sanitizado |
| `embedding_batches` | Batch reanudable opcional | Solo si aporta trazabilidad/retry verificable |
| `semantic_search_runs` | Auditoría histórica minimizada | Conserva hash, filtros y métricas; nunca consulta, vector o contenido completo |
| `human_retrieval_evaluations` | Juicio humano versionado sobre resultados | Evaluador textual seudónimo, score 1–5, relevancia y dataset; sin datos sensibles |

**Schema contractual de `semantic_search_runs`**

| Campo | Tipo contractual | Reglas |
|---|---|---|
| `id` | UUID | Identidad primaria no reutilizable |
| `query_hash` | SHA-256 | Hash de la consulta normalizada; nunca se acompaña por la consulta |
| `filters_sanitized` | Objeto estructurado | `document_type`, `document_subtype` y `jurisdiction` obligatorios; `language` y `organization` opcionales; `review_status=REVIEWED` por defecto o `PENDING_REVIEW` administrativo; allowlist estricta y sin datos sensibles |
| `top_k` | Entero | Dentro del mínimo y máximo contractual |
| `minimum_score` | Decimal opcional | Dentro del rango documentado del score normalizado |
| `embedding_model` | Texto | Modelo efectivo usado para la consulta |
| `embedding_dimensions` | Entero positivo | Debe coincidir con el índice lógico consultado |
| `result_count` | Entero no negativo | Cantidad efectivamente devuelta |
| `duration_ms` | Entero no negativo | Duración total de la operación |
| `status` | Enum contractual | `SUCCEEDED` o `FAILED`; timeout se representa como `FAILED` |
| `error_code` | Texto | Obligatorio solo en `FAILED`; timeout usa `SEMANTIC_SEARCH_TIMEOUT` |
| `request_id` | Identificador trazable | Obligatorio, no vacío; solo correlación con observabilidad |
| `created_at` | Timestamp UTC | Asignado al registrar la ejecución |

La tabla no contiene query completa, embedding de consulta, contenido
documental, excerpts, tokens, `Authorization`, rutas internas ni stack traces.

## Supuestos

- El root del corpus es una ruta local montada o sincronizada previamente y el
  operador tiene permisos legítimos para procesarla.
- El corpus MVP es homogéneo y sus metadatos obligatorios pueden obtenerse del
  archivo, su estructura o parámetros explícitos del comando.
- `source_name` es Boletín Oficial de la República Argentina y `external_id`
  identifica el documento dentro de esa fuente.
- PostgreSQL 16 y la extensión vectorial existente soportan la dimensión que se
  confirme en investigación.
- Ollama permanece externo, privado, con HTTPS/Bearer, una sola inferencia activa
  y timeout máximo aproximado de 300 segundos.
- `token_count` es estimado e informativo salvo evidencia de tokenizer exacto.
- La búsqueda exacta es suficiente para el tamaño inicial; HNSW se evaluará con
  crecimiento medido e IVFFlat queda descartado inicialmente.
- Los umbrales de calidad del baseline se fijarán con el dataset inicial y no
  bloquearán CI hasta disponer de evidencia estable.

## Dependencias

- Capacidades existentes de PostgreSQL 16 y pgvector.
- Ollama externo y disponibilidad del modelo `qwen3-embedding:4b-q4_K_M`.
- Envelope de errores, observabilidad, auditoría y configuración de 003–004.
- Docker Compose y mecanismo de migraciones existentes.
- Investigación reproducible sobre endpoint, dimensión nativa 2560,
  almacenamiento y estrategia de índices.

## Riesgos

| Riesgo | Impacto | Mitigación contractual |
|---|---|---|
| Dimensión asumida o cambiante | Migración inválida o índice inutilizable | Comprobar respuesta real, fijar dimensión y exigir migración + reindexación |
| Normalización altera significado | Antecedente jurídicamente incorrecto | Reglas conservadoras, hashes, versionado y fixtures revisados |
| Chunking rompe unidades jurídicas | Baja recuperación o contexto engañoso | Estructura jurídica primaria, fallback determinista y pruebas reales |
| Proveedor lento o caído | Ingesta/búsqueda no disponibles | Timeout, retry acotado, resume, health y aislamiento de 001–004 |
| Corpus no confiable | Fuga, ejecución o agotamiento de recursos | No ejecutar contenido, límites, sanitización y paths confinados |
| Mezcla de modelos/dimensiones | Scores no comparables | Índice lógico homogéneo y validación antes de persistir/buscar |
| Métricas fluctuantes | Decisiones falsas sobre calidad | Fake reproducible, dataset versionado y evaluación real no bloqueante |
| Reindexación incompleta | Pérdida temporal de búsqueda | Mantener índice válido hasta confirmar reemplazo y rollback lógico |

## Veredicto

`READY_FOR_REANALYSIS`

La especificación delimita actores, flujos, datos, seguridad, observabilidad,
evaluación, compatibilidad y resultados medibles. La implementación mantiene
`qwen3-embedding:4b-q4_K_M`/2560. G1-B quedó validado desde el entorno local contra
HTTPS/Bearer usando el perfil externo documentado `/api/embeddings`, con 200 en
version, show y embeddings, 2560 dimensiones, estabilidad y compatibilidad
documento/query. El proxy no expone `/api/embed`; ese perfil nativo permanece
disponible solo cuando el despliegue lo publique explícitamente.
