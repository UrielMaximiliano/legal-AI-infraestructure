# Plan de Implementación: RAG Jurídico para Borradores de Decretos

**Branch**: `006-rag-dev` | **Fecha**: 2026-08-07 | **Spec**: [spec.md](spec.md)
**Estado**: `READY_FOR_TASKS`
**Base**: incremento 005 integrado en `c81aac4`; migración actual `006`

## Resumen

Implementar un pipeline RAG auditable que reutilice la recuperación semántica exacta del incremento 005, ensamble contexto jurídico con citas y genere un borrador JSON mediante `qwen3.6:35b`. El resultado se valida antes de crear un `Draft`, conserva vínculos a documentos/chunks y entra al flujo existente de revisión humana. El corpus de recuperación será únicamente `INDEX_90`; los 1.000 PDF `HOLDOUT_10` permanecerán fuera de PostgreSQL y se usarán para evaluación sin fuga.

## Contexto técnico

| Área | Decisión |
|---|---|
| Runtime | Python 3.12, async |
| API | FastAPI, Pydantic v2 |
| Persistencia | PostgreSQL 16, SQLAlchemy 2 async, Alembic |
| Recuperación | pgvector, exact cosine search, `halfvec(2560)` |
| Embeddings | `qwen3-embedding:4b-q4_K_M`, `/api/embed`, 2560 dimensiones |
| Generación | `qwen3.6:35b`, `/api/chat`, salida JSON Schema, `stream=false` |
| Coordinación | `InferenceCoordinator`, un slot; `INTERACTIVE` antes de `SEARCH` y `BATCH_INGESTION` |
| Corpus | 9.000 documentos `INDEX_90`, 65.916 chunks; solo `REVIEWED` y generación activa |
| Holdout | 1.000 PDF fuera de la base operativa y del índice |
| Tests | pytest, pytest-asyncio, PostgreSQL real, fakes deterministas |
| Calidad | Ruff, mypy strict, cobertura focalizada y suite integral |
| Migración nueva | `007_rag_generation_audit.py`; no modificar 001–006 |
| Infraestructura | Docker Compose local; Ollama interno/remoto configurable; sin GPU asignada a API |

## Gate constitucional

### Evaluación previa al diseño

| Principio | Cumplimiento |
|---|---|
| Seguridad y privacidad | Ollama autorizado, backend-only, redacción estricta y ninguna persistencia de prompts completos |
| Asistencia, no decisión | Todo resultado es borrador no vinculante y queda `PENDING_REVIEW` |
| Trazabilidad | Run, fuentes, modelos, versiones, parámetros y validaciones quedan auditados |
| Prohibición de invención | Citas resolubles, evidencia mínima y rechazo fail-closed |
| Salida estructurada | JSON Schema versionado antes de persistir el borrador |
| Corpus controlado | Solo decretos nacionales `INDEX_90` y `REVIEWED`; holdout excluido |
| Chunking jurídico | Reutiliza chunks 005 y preserva unidades jurídicas en el contexto |
| RAG antes que fine-tuning | Sin fine-tuning, agentes ni MCP |
| Evaluación obligatoria | Dataset holdout versionado y métricas automáticas/humanas |
| Arquitectura modular | Dominio, puertos, aplicación, adaptadores y API separados |
| Reproducibilidad | Configuración explícita, fakes y Docker Compose |
| Desarrollo incremental | Gates por fase; la generación real se habilita después de retrieval/contexto/validación |
| Simplicidad | Sin Redis, HNSW, nuevo servicio ni base vectorial adicional |

**Gate previo**: PASS. No hay excepciones constitucionales.

## Arquitectura objetivo

```text
POST /api/v1/rag/drafts/generate
        |
        v
RagGenerationService
  |-- valida expediente + plantilla + variables + idempotencia
  |-- RagQueryBuilder (consulta minimizada)
  |-- RetrievalService
  |     |-- EmbeddingProvider.embed_query
  |     `-- ExactVectorSearchRepository
  |-- ContextAssembler (diversidad + presupuesto + citation_id)
  |-- crea RagGenerationRun IN_PROGRESS y confirma transacción
  |-- InferenceCoordinator.INTERACTIVE
  |     `-- OllamaChatProvider.generate_structured
  |-- StructuredDraftValidator
  |     |-- JSON Schema/Pydantic
  |     |-- citas resolubles
  |     `-- reglas anti-invención verificables
  `-- transacción final: auditoría + RagStructuredDraft + Draft PENDING_REVIEW
```

### Decisiones de integración

1. Crear un endpoint RAG nuevo y preservar sin cambios `POST /api/v1/drafts/generate`.
2. Extraer el núcleo de recuperación de `SemanticSearchService` a un servicio interno reutilizable. El endpoint 005 mantiene exactamente su contrato y auditoría fail-closed.
3. Implementar un puerto generativo estructurado separado del `OllamaClient` legacy. El adaptador usa `/api/chat` con JSON Schema; no se agrega fallback silencioso a `/api/generate`.
4. El contexto contiene texto de chunks porque el generador necesita evidencia legible; los vectores nunca se envían al generador.
5. Los chunks se delimitan como datos no confiables, con `citation_id` generado por el backend. Ningún texto recuperado puede cambiar instrucciones del sistema.
6. No mantener transacciones abiertas durante embeddings o generación.
7. El run se crea antes de inferencia y se finaliza en una transacción corta. El borrador solo se crea cuando salida y citas son válidas.

## Estrategia de recuperación

- Filtros obligatorios: `document_type=decreto`, `document_subtype=designacion_transitoria`, `jurisdiction=nacion`, `review_status=REVIEWED`, `evaluation_split=INDEX_90`.
- Línea base: distancia coseno exacta sobre la generación activa.
- `top_k` por defecto 8, mínimo 3 y máximo 20.
- Recuperar inicialmente más candidatos que el contexto final (`candidate_pool = min(3 * top_k, 50)`) y seleccionar de forma determinista.
- Diversificación inicial: máximo 2 chunks por documento y máximo 1 por combinación documento/sección, salvo que no alcance la evidencia mínima.
- Orden estable: score descendente, fecha descendente, documento, sección, párrafo y chunk.
- `minimum_score` configurable; cero es válido para baseline, pero toda ejecución registra el valor usado.
- Un preflight debe confirmar que existen documentos `REVIEWED` elegibles. Cero elegibles bloquea el smoke real, no los tests fake.

## Estrategia de contexto

- Presupuesto configurable por bytes y tokens estimados; no asumir que la ventana teórica completa es utilizable.
- Reservar espacio para instrucciones, expediente, schema y salida.
- Incluir metadatos mínimos: cita opaca, título, identificador oficial, fecha, sección, artículo y extracto.
- No incluir rutas, embeddings, metadata privada ni documentos completos.
- Truncar solo en límites de párrafo. Un artículo o referencia jurídica indivisible se incluye completo o se descarta con motivo auditado.
- Canonicalizar el contexto para que el mismo input y configuración produzcan el mismo `context_hash`.

## Estrategia de generación

- Modelo: `qwen3.6:35b`.
- Endpoint: `/api/chat`, `stream=false`, `format=<JSON Schema>`.
- Prompt versionado inicial: `rag-decree-v1`.
- Roles:
  - `system`: reglas jurídicas, schema, no invención, contexto como datos.
  - `user`: datos validados del caso y solicitud.
  - bloque de evidencia delimitado: fuentes con citation IDs.
- Temperatura inicial conservadora y configurable; registrar parámetros efectivos.
- Validación doble: JSON/schema estricto y reglas de dominio/citas.
- Una sola reparación automática de schema; la reparación recibe errores estructurados y el mismo contexto, y se audita como segundo intento.
- Nunca persistir reasoning/thinking, prompt completo ni Authorization.

## Estrategia de persistencia

La migración 007 agrega cuatro tablas descritas en [data-model.md](data-model.md):

- `rag_generation_runs`
- `rag_retrieved_sources`
- `rag_structured_drafts`
- `rag_evaluation_results`

Los eventos se vinculan con entidades 003–005 mediante FKs explícitas. `rag_generation_runs` guarda hashes y métricas, no consultas ni prompts completos. `rag_retrieved_sources` conserva la procedencia exacta. `rag_structured_drafts` conserva el JSON validado y su hash, asociado uno-a-uno al `draft`. La evaluación humana y automática se registra separadamente.

## Contratos

- [HTTP RAG](contracts/http-api.md)
- [CLI de evaluación](contracts/rag-evaluation-cli.md)
- [JSON Schema del borrador](contracts/rag-structured-draft.schema.json)

## Fases de implementación y gates

### Fase 1 — Configuración, dominio y puertos

- Agregar configuración RAG y generativa con límites estrictos.
- Modelar estados, errores, run, fuentes y salida estructurada.
- Definir puertos de retrieval, generación estructurada, auditoría y reloj/IDs para tests.
- Implementar `FakeStructuredGenerationProvider` determinista.

**Gate G1**: unit tests de configuración, dominio, schema y fake; Ruff/mypy verdes.

### Fase 2 — Migración y repositorios

- Crear migración Alembic 007 y modelos ORM equivalentes.
- Implementar repositorios y mappers allowlist.
- Probar upgrade 006→007, downgrade 007→006 y segundo upgrade en PostgreSQL temporal.
- Verificar que corpus, embeddings y tablas 001–006 se preservan.

**Gate G2**: round-trip real, equivalencia ORM/PostgreSQL y rollback sin residuos.

### Fase 3 — Retrieval reutilizable y ensamblado de contexto

- Extraer un `RetrievalService` común sin alterar el contrato 005.
- Añadir filtro fail-closed `evaluation_split=INDEX_90` para RAG.
- Implementar query builder, diversificación, citation IDs y presupuesto.
- Probar determinismo, evidencia insuficiente, chunks indivisibles e inyección en fuentes.

**Gate G3**: búsqueda 005 sin regresiones y contexto RAG determinista/seguro.

### Fase 4 — Adaptador Ollama generativo

- Implementar `/api/chat` con JSON Schema, HTTPS/Bearer remoto y HTTP local controlado.
- Integrar `InferenceCoordinator.INTERACTIVE`.
- Implementar matriz de timeout/retry y sanitización.
- Probar con fake/MockTransport; smoke real opt-in contra `qwen3.6:35b`.

**Gate G4**: contrato estructurado, errores sanitizados, monoslot y prioridad verificados.

### Fase 5 — Orquestación RAG y API

- Implementar `RagGenerationService` y endpoint.
- Integrar expediente, plantilla, variables, idempotencia y creación de Draft.
- Persistir run/fuentes/salida de forma fail-closed.
- Implementar una reparación de schema y errores contractuales.
- Añadir GET de run para trazabilidad autorizada.

**Gate G5**: E2E fake crea un único borrador pendiente; todos los fallos dejan cero borradores parciales.

### Fase 6 — Evaluación holdout

- Crear manifiesto versionado con hashes de los 1.000 PDF sin copiarlos al repositorio.
- Implementar extractor/evaluador offline sin insertar holdout en corpus/chunks.
- Ejecutar evaluación fake completa y muestra real controlada.
- Reportar métricas de recuperación, estructura, citas, fidelidad, invención, utilidad y latencia.

**Gate G6**: prueba automática demuestra cero IDs/hash holdout en índice y resultados reproducibles.

### Fase 7 — Observabilidad, seguridad y documentación

- Health/readiness por dependencia.
- Logs y métricas allowlist.
- Threat tests: prompt injection, datos sensibles, fuentes falsas, payload hostil.
- Actualizar README, `.env.example`, quickstart y runbooks.

**Gate G7**: suite completa, cobertura ≥85%, Ruff, mypy, lock, auditoría de dependencias, Compose y secret scan verdes.

### Fase 8 — Aceptación real

- Confirmar embeddings INDEX_90 completos y holdout ausente.
- Ejecutar smoke Docker/local→Ollama para embeddings y chat.
- Ejecutar casos jurídicos revisados por humano.
- Documentar baseline; no fijar umbral de aprobación sin revisión jurídica.

**Gate final**: `READY_FOR_HUMAN_RAG_EVALUATION`. La adopción productiva requiere decisión humana posterior.

## Testing

### Unitario

- Query builder y normalización.
- Selección/diversificación/presupuesto de contexto.
- Hashes, estados y transiciones.
- JSON Schema y validación de citas.
- Fake generator, retries e idempotencia.
- Redacción de logs y errores.

### Contractual

- Request/response/error del endpoint RAG.
- Compatibilidad del endpoint de drafts existente.
- Payload `/api/chat` y respuesta estructurada.
- CLI de evaluación y manifiesto holdout.

### Integración PostgreSQL

- Migración 006↔007.
- FKs, constraints, uniques e índices.
- Persistencia fail-closed.
- Idempotencia y concurrencia.
- Fuentes vinculadas a chunks activos.
- Ausencia de holdout.

### E2E

- Fake: expediente→retrieval→contexto→JSON→Draft→review.
- Real opt-in: embeddings 4B + búsqueda exacta + chat 35B.
- Fallos de Ollama, auditoría y schema.
- Prioridad interactiva mientras existe carga batch.

## Configuración prevista

```dotenv
OLLAMA_GENERATION_BASE_URL=http://host.docker.internal:11434
OLLAMA_GENERATION_ENDPOINT=/api/chat
OLLAMA_GENERATION_MODEL=qwen3.6:35b
OLLAMA_GENERATION_TOKEN=<PLACEHOLDER>
OLLAMA_GENERATION_TIMEOUT_SECONDS=300
RAG_PROMPT_VERSION=rag-decree-v1
RAG_SCHEMA_VERSION=1
RAG_TOP_K=8
RAG_CANDIDATE_POOL_SIZE=24
RAG_MINIMUM_SCORE=0.0
RAG_MAX_CONTEXT_BYTES=65536
RAG_MAX_CONTEXT_TOKENS_ESTIMATE=16384
RAG_MAX_CHUNKS_PER_DOCUMENT=2
RAG_SCHEMA_REPAIR_ATTEMPTS=1
RAG_REQUIRE_REVIEWED=true
RAG_REQUIRED_EVALUATION_SPLIT=INDEX_90
```

Los límites son defaults de desarrollo y deberán validarse en G8; no son SLA ni garantía de capacidad.

## Estructura de código prevista

```text
apps/api/src/legal_ai/
├── api/routes/rag.py
├── application/
│   ├── rag_generation.py
│   ├── rag_retrieval.py
│   ├── rag_context.py
│   └── rag_evaluation.py
├── domain/rag.py
├── schemas/rag.py
├── ports/
│   ├── rag.py
│   └── structured_generation.py
├── adapters/
│   ├── ollama/structured_generation.py
│   ├── generation/fake_structured_generation.py
│   └── database/
│       ├── rag_models.py
│       ├── rag_mappers.py
│       └── rag_repositories.py
└── cli/rag_evaluate.py

apps/api/alembic/versions/007_rag_generation_audit.py
apps/api/tests/{unit,contract,integration}/...
```

La estructura es orientativa; el agente debe reutilizar módulos existentes cuando mantenga responsabilidades claras y no debe duplicar infraestructura 005.

## Riesgos y mitigaciones

| Riesgo | Mitigación / gate |
|---|---|
| Cero documentos `REVIEWED` elegibles | Preflight y bloqueo explícito del smoke real |
| Prompt injection desde corpus | Contexto delimitado como datos, sin tools y tests adversariales |
| Citas inventadas | Allowlist de citation IDs y rechazo antes de persistir |
| JSON inválido | JSON Schema + Pydantic + una reparación auditada |
| Saturación del único slot | Coordinador existente y prioridad `INTERACTIVE` |
| Fuga del holdout | Holdout fuera de DB, guard automatizado por hash/ID |
| Regresión 003–005 | Endpoint nuevo, refactor cubierto por contratos existentes |
| Contexto demasiado grande | Presupuesto configurable y selección determinista |
| Transacción durante inferencia | Separación explícita de fases y tests de UoW |

## Gate constitucional posterior al diseño

PASS. El diseño mantiene RAG antes que fine-tuning, revisión humana obligatoria, salida estructurada, trazabilidad de fuentes, corpus controlado, arquitectura modular, inferencia privada y complejidad mínima. No requiere excepción ni ADR transversal en esta fase.

## Pendientes antes de implementación

1. Ejecutar `$speckit-tasks` para producir tareas numeradas y dependencias.
2. Verificar en la base destino el conteo real de documentos `INDEX_90` con `review_status=REVIEWED`.
3. Confirmar mediante probe opt-in que el proxy autorizado publica `/api/chat` para `qwen3.6:35b` y acepta JSON Schema.
4. No mezclar el desarrollo local con el worker de embeddings en ejecución; el pull del servidor se hará después del merge aprobado.

## Veredicto

`READY_FOR_TASKS`
