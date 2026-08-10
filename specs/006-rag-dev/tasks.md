# Tasks: RAG jurÃ­dico para borradores de decretos

**Input**: `specs/006-rag-dev/spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md` y `.specify/memory/constitution.md`
**Branch**: `006-rag-dev`
**MVP sugerido**: US1 + US2 + US3 con provider fake, migraciÃ³n 007 y PostgreSQL aislado.

## Phase 1: Setup y baseline del incremento

**Objetivo**: preparar el incremento sin cambiar migraciones 001â€“006 ni contratos existentes.

- [x] T001 Registrar en `specs/006-rag-dev/tasks.md` la matriz de alcance, restricciones crÃ­ticas y gates G1â€“G8 del incremento
- [x] T002 [P] Auditar estructura existente de API, dominio, puertos, adaptadores, migraciones y tests en `apps/api/src/legal_ai/` y `apps/api/tests/`
- [x] T003 [P] Confirmar en `apps/api/pyproject.toml` y `apps/api/uv.lock` las dependencias existentes permitidas para RAG sin agregar LangChain/LlamaIndex
- [x] T004 [P] Capturar baseline de contratos 001â€“005 y lista de migraciones inmutables en `specs/006-rag-dev/quickstart.md`
- [x] T005 Ejecutar `git diff --check` y conservar evidencia del estado inicial en `specs/006-rag-dev/agent-handoff.md`
- [x] T006 Ejecutar la suite vigente de `apps/api/tests/` y documentar cualquier fallo preexistente en `specs/006-rag-dev/agent-handoff.md`

**Gate de fase**: baseline documentado, sin cambios en 001â€“006 y suite 001â€“005 caracterizada.

## Phase 2: FundaciÃ³n, configuraciÃ³n, dominio, puertos, migraciÃ³n 007 y repositorios

**Objetivo**: completar las fases de plan 1â€“2: configuraciÃ³n contractual, entidades inmutables, fake determinista, ORM y round-trip de PostgreSQL.

- [x] T007 [P] AÃ±adir configuraciÃ³n validada de RAG, Ollama generativo, lÃ­mites, modelos, dimensiones, prompt/schema y split en `apps/api/src/legal_ai/config.py`
- [x] T008 [P] AÃ±adir mensajes de error y cÃ³digos pÃºblicos sanitizados para RAG en `apps/api/src/legal_ai/domain/errors.py`
- [x] T009 [P] Modelar estados, disposiciones, modos, hashes, transiciones y reglas de idempotencia en `apps/api/src/legal_ai/domain/rag.py`
- [x] T010 [P] Definir schemas estrictos de request, response, run, sources y `RagStructuredDraftV1` en `apps/api/src/legal_ai/schemas/rag.py`
- [x] T011 [P] Definir puertos de retrieval, generaciÃ³n estructurada, auditorÃ­a, reloj, IDs y evaluaciÃ³n en `apps/api/src/legal_ai/ports/rag.py` y `apps/api/src/legal_ai/ports/structured_generation.py`
- [x] T012 [P] Implementar provider fake determinista, sin Ollama ni contenido sensible, en `apps/api/src/legal_ai/adapters/generation/fake_structured_generation.py`
- [x] T013 [P] Implementar validaciÃ³n JSON Schema/Pydantic cerrada, reglas de campos obligatorios y advertencia de revisiÃ³n humana en `apps/api/src/legal_ai/application/rag_validation.py`
- [x] T014 Crear modelos SQLAlchemy, constraints, Ã­ndices, FKs y mappers allowlist para las cuatro tablas RAG en `apps/api/src/legal_ai/adapters/database/rag_models.py` y `apps/api/src/legal_ai/adapters/database/rag_mappers.py`
- [x] T015 Crear exclusivamente `apps/api/alembic/versions/007_rag_generation_audit.py` con upgrade/downgrade explÃ­citos, sin modificar migraciones 001â€“006
- [x] T016 [P] Implementar repositorios transaccionales de runs, sources, structured drafts y evaluation results en `apps/api/src/legal_ai/adapters/database/rag_repositories.py`
- [x] T017 [P] Cubrir configuraciÃ³n, dominio, schema, transiciones, fake y redacciÃ³n de errores en `apps/api/tests/unit/test_rag_domain.py`, `test_rag_schemas.py` y `test_rag_fake.py`
- [x] T018 Probar `006 -> 007 -> 006 -> 007`, FKs/constraints/Ã­ndices y preservaciÃ³n de tablas 001â€“006 en `apps/api/tests/integration/test_007_migrations.py`
- [x] T019 Ejecutar el gate G1 con `uv run pytest`, Ruff y mypy strict sobre los archivos de la fundaciÃ³n
- [x] T020 Ejecutar el gate G2 sobre PostgreSQL temporal/aislado y corregir cualquier rollback, constraint o mapeo rojo antes de continuar

**Gate G1/G2**: unitarios verdes, Ruff/mypy verdes y round-trip real sin residuos ni cambios 001â€“006.

## Phase 3: US1 â€” RecuperaciÃ³n exacta, polÃ­tica INDEX_90 y contexto citable

**Objetivo de historia**: recuperar evidencia determinista exclusivamente de chunks activos de documentos `REVIEWED` en `INDEX_90`, ensamblar contexto acotado y resolver citas opacas.

**Criterio de prueba independiente**: con fixtures fake de chunks elegibles y no elegibles, la selecciÃ³n es estable, diversificada, limitada por presupuesto y cada `SRC-NNN` resuelve Ãºnicamente a un chunk recuperado.

- [x] T021 [P] [US1] Extraer el nÃºcleo reutilizable de bÃºsqueda exacta desde `apps/api/src/legal_ai/application/semantic_search.py` hacia `apps/api/src/legal_ai/application/rag_retrieval.py` sin cambiar el contrato HTTP 005
- [x] T022 [P] [US1] Implementar query builder allowlist con campos validados de expediente, plantilla y variables en `apps/api/src/legal_ai/application/rag_query.py`
- [x] T023 [US1] Implementar filtro fail-closed de `decreto`, `designacion_transitoria`, `nacion`, `REVIEWED`, generaciÃ³n activa y `INDEX_90` en `apps/api/src/legal_ai/adapters/database/corpus_chunk_repository.py`
- [x] T024 [US1] Implementar pool candidato `min(3*top_k,50)`, orden estable, score mÃ­nimo y diversificaciÃ³n por documento/secciÃ³n en `apps/api/src/legal_ai/application/rag_retrieval.py`
- [x] T025 [US1] Implementar ensamblado de contexto dual por bytes/tokens, lÃ­mites de pÃ¡rrafo, artÃ­culos indivisibles, hash canÃ³nico y `SRC-NNN` en `apps/api/src/legal_ai/application/rag_context.py`
- [x] T026 [P] [US1] AÃ±adir tests de determinismo, empates, filtros, cero elegibles, evidencia insuficiente, redundancia, presupuesto, artÃ­culo indivisible y prompt injection en `apps/api/tests/unit/test_rag_retrieval.py` y `apps/api/tests/unit/test_rag_context.py`
- [x] T027 [P] [US1] AÃ±adir tests de integraciÃ³n PostgreSQL que verifiquen `REVIEWED`/`INDEX_90`, chunks activos, generaciÃ³n activa, documentos/chunks vinculados y ausencia de holdout en `apps/api/tests/integration/test_rag_retrieval_postgres.py`
- [x] T028 [US1] Ejecutar el gate G3 incluyendo los contratos de bÃºsqueda 005 y corregir regresiones antes de integrar generaciÃ³n

**Gate G3**: bÃºsqueda 005 sin regresiones; RAG devuelve solo corpus permitido y contexto determinista/seguro.

## Phase 4: US3 â€” Adaptador generativo estructurado y coordinaciÃ³n de inferencia

**Objetivo de historia**: enviar `/api/chat` con JSON Schema a `qwen3.6:35b`, validar respuestas y coordinar el Ãºnico slot con prioridad interactiva.

**Criterio de prueba independiente**: un fake/MockTransport recibe payload permitido, nunca imprime secretos, acepta una respuesta JSON vÃ¡lida y rechaza/repara una invÃ¡lida como mÃ¡ximo una vez.

- [x] T029 [P] [US3] Implementar `StructuredGenerationProvider` y payload `/api/chat` (`stream=false`, `format` schema, system/user separados) en `apps/api/src/legal_ai/adapters/ollama/structured_generation.py`
- [x] T030 [US3] Implementar allowlist de HTTP local/remoto, Bearer fuera de logs, timeout, retries acotados, traducciÃ³n de errores y descarte de thinking en `apps/api/src/legal_ai/adapters/ollama/structured_generation.py`
- [x] T031 [US3] Integrar `InferenceCoordinator` existente con `INTERACTIVE` para generaciÃ³n y preservar prioridades `SEARCH`/`BATCH_INGESTION` en `apps/api/src/legal_ai/application/inference_coordinator.py`
- [x] T032 [P] [US3] Construir prompt versionado `rag-decree-v1` con evidencia delimitada como datos no confiables y sin tools en `apps/api/src/legal_ai/application/rag_prompt.py`
- [x] T033 [P] [US3] AÃ±adir tests contractuales del payload `/api/chat`, schema, HTTPS/Bearer, HTTP local controlado, timeout/retry y sanitizaciÃ³n en `apps/api/tests/contract/test_ollama_structured_generation.py`
- [x] T034 [P] [US3] AÃ±adir tests del fake, prioridad, monoslot, backpressure y ausencia de interrupciÃ³n de inferencia activa en `apps/api/tests/unit/test_inference_coordinator.py`
- [x] T035 [US3] Ejecutar el gate G4 con provider fake/MockTransport y dejar el smoke Ollama real opt-in en `apps/api/tests/integration/test_ollama_real_opt_in.py`

**Gate G4**: contrato estructurado y degradaciÃ³n sanitizada verdes; ninguna prueba depende de Ollama salvo el smoke explÃ­citamente opt-in.

## Phase 5: US1/US2/US3 â€” OrquestaciÃ³n RAG, auditorÃ­a fail-closed, Draft y API

**Objetivo de historias**: generar un Ãºnico Draft `PENDING_REVIEW` solo tras recuperar, auditar y validar; fallar con evidencia insuficiente o schema/citas invÃ¡lidos sin Draft parcial.

**Criterios de prueba independientes**: E2E fake exitoso con run, fuentes, structured draft y Draft Ãºnicos; E2E de evidencia insuficiente, auditorÃ­a caÃ­da, idempotencia/concurrencia y schema invÃ¡lido deja cero Drafts.

- [x] T036 [P] [US1] Implementar hash canÃ³nico de request/configuraciÃ³n/modelos/prompt y reserva idempotente con mismatch/in-progress en `apps/api/src/legal_ai/application/rag_idempotency.py`
- [x] T037 [US1] Implementar creaciÃ³n y cierre de runs/fuentes fuera de inferencia, transacciones cortas y fail-closed en `apps/api/src/legal_ai/application/rag_audit.py`
- [x] T038 [US1] Implementar `RagGenerationService` con fases retrieval/context/run/generate/validate/finalizaciÃ³n y una sola reparaciÃ³n de schema en `apps/api/src/legal_ai/application/rag_generation.py`
- [x] T039 [US2] Implementar corte temprano `RAG_INSUFFICIENT_EVIDENCE`, warnings sanitizados y prohibiciÃ³n de contenido no respaldado en `apps/api/src/legal_ai/application/rag_generation.py`
- [x] T040 [US3] Implementar validaciÃ³n de citas contra allowlist de sources seleccionadas, cobertura de VISTO/considerandos y rechazo de citas desconocidas en `apps/api/src/legal_ai/application/rag_validation.py`
- [x] T041 [US3] Implementar conversiÃ³n determinista de structured draft a contenido de Draft existente, marcado asistido/no vinculante y estado `PENDING_REVIEW` en `apps/api/src/legal_ai/application/rag_generation.py`
- [x] T042 [US1] Integrar expediente, plantilla, variables escalares allowlist y Draft existente sin cambiar `POST /api/v1/drafts/generate` en `apps/api/src/legal_ai/application/rag_generation.py`
- [x] T043 [US1] Crear endpoint `POST /api/v1/rag/drafts/generate` con headers, request/response y envelope contractual en `apps/api/src/legal_ai/api/routes/rag.py`
- [x] T044 [US1] Crear endpoint autorizado `GET /api/v1/rag/runs/{run_id}` con trazabilidad sin query, prompt, contexto, hashes internos ni contenido completo en `apps/api/src/legal_ai/api/routes/rag.py`
- [x] T045 [P] [US2] AÃ±adir errores HTTP 400/404/409/422/503/504 y request correlation sanitizados en `apps/api/src/legal_ai/api/routes/rag.py`
- [x] T046 [P] [US1] AÃ±adir contrato HTTP y pruebas de idempotencia, Draft pendiente, respuesta sin embeddings y compatibilidad legacy en `apps/api/tests/contract/test_rag_api.py`
- [x] T047 [US1] AÃ±adir E2E fake expedienteâ†’retrievalâ†’contextoâ†’JSONâ†’Draftâ†’review con persistencia PostgreSQL en `apps/api/tests/integration/test_rag_generation_e2e.py`
- [x] T048 [US2] AÃ±adir E2E de evidencia insuficiente, fuentes falsas, auditorÃ­a no persistible, timeout y generaciÃ³n invÃ¡lida con cero Drafts en `apps/api/tests/integration/test_rag_fail_closed.py`
- [x] T049 [US1] AÃ±adir E2E de misma key/payload, key/hash distinto, retry y dos solicitudes concurrentes en `apps/api/tests/integration/test_rag_idempotency.py`
- [x] T050 [US3] Ejecutar el gate G5 y verificar que ningÃºn fallo posterior a retrieval deja Draft huÃ©rfano o aprobado automÃ¡ticamente

**Gate G5**: E2E fake completo y fail-closed; compatibilidad de contratos 001â€“005 preservada.

## Phase 6: US4 â€” EvaluaciÃ³n HOLDOUT_10 sin fuga

**Objetivo de historia**: validar manifiesto y ejecutar benchmark fake/real opt-in sin insertar ni vectorizar los 1.000 PDF reservados.

**Criterio de prueba independiente**: dry-run no llama Ollama ni escribe PostgreSQL; ejecuciÃ³n fake es reproducible; cualquier hash/ID holdout presente en Ã­ndice produce exit code 3.

- [x] T051 [P] [US4] Implementar schemas y validador de manifiesto externo, hashes, split, rutas relativas seguras, symlink escape y IDs Ãºnicos en `apps/api/src/legal_ai/application/rag_evaluation.py`
- [x] T052 [P] [US4] Implementar mÃ©tricas Recall@3/5, Precision@3/5, MRR, schema/secciones/citas/fidelidad/invenciÃ³n y percentiles de latencia en `apps/api/src/legal_ai/application/rag_evaluation.py`
- [x] T053 [US4] Implementar guard de no fuga contra corpus operativo y persistencia Ãºnicamente de hashes/case IDs opacos en `apps/api/src/legal_ai/application/rag_evaluation.py`
- [x] T054 [US4] Implementar CLI `corpus rag-evaluate` dry-run/execute, providers fake/ollama, `--limit`, salida JSON y exit codes 0/2/3/4/5/6 en `apps/api/src/legal_ai/cli/rag_evaluate.py` y `apps/api/src/legal_ai/cli/corpus.py`
- [x] T055 [P] [US4] AÃ±adir manifiesto sintÃ©tico sin PDF real y fixtures externos controlados en `apps/api/tests/fixtures/rag/manifest.json`
- [x] T056 [P] [US4] AÃ±adir pruebas de CLI, validaciÃ³n de manifiesto, dry-run sin IO externo, fake reproducible, rutas/hashes prohibidos y no fuga en `apps/api/tests/contract/test_rag_evaluation_cli.py`
- [x] T057 [US4] AÃ±adir pruebas de integraciÃ³n que demuestren que HOLDOUT_10 no entra a corpus/chunks/embeddings ni a fuentes de generaciÃ³n en `apps/api/tests/integration/test_rag_holdout_leakage.py`
- [x] T058 [US4] Crear manifiesto versionado solo con hashes/rutas externas y documentaciÃ³n de ubicaciÃ³n fuera de Git en `specs/006-rag-dev/holdout-manifest.example.json` y `specs/006-rag-dev/quickstart.md`
- [x] T059 [US4] Ejecutar el gate G6 con dry-run y fake completo; dejar Ollama real solo como aceptaciÃ³n opt-in sin fijar umbrales de calidad

**Gate G6**: cero IDs/hashes holdout en Ã­ndice o fuentes operativas y mÃ©tricas reproducibles sin umbrales inventados.

## Phase 7: US5 â€” Observabilidad, seguridad, readiness y documentaciÃ³n operativa

**Objetivo de historia**: degradar de forma segura ante dependencia caÃ­da/concurrencia y ofrecer health/readiness, logs y mÃ©tricas allowlist.

**Criterio de prueba independiente**: fallos de DB, retrieval, embeddings, generaciÃ³n y auditorÃ­a producen estados diferenciados, logs sin datos sensibles y ningÃºn Draft parcial.

- [x] T060 [P] [US5] Extender readiness con DB, retrieval, embedding model, generation model, dimensiones y documentos elegibles en `apps/api/src/legal_ai/api/routes/health.py`
- [x] T061 [P] [US5] AÃ±adir eventos de auditorÃ­a, mÃ©tricas de latencia/conteo/modelo/contexto y redacciÃ³n de logs en `apps/api/src/legal_ai/observability/rag.py`
- [x] T062 [P] [US5] AÃ±adir lÃ­mites de payload, allowlists, correlation ID, sanitizaciÃ³n y prohibiciÃ³n de prompts/queries/documentos/vectores/tokens/Authorization en `apps/api/src/legal_ai/api/middleware.py`
- [x] T063 [US5] AÃ±adir threat tests de prompt injection, datos sensibles, fuente falsa, payload hostil, stack trace y rutas internas en `apps/api/tests/security/test_rag_security.py`
- [x] T064 [US5] AÃ±adir pruebas de readiness degradado/no disponible, prioridad interactiva y fallos aislados de Ollama/DB/auditorÃ­a en `apps/api/tests/integration/test_rag_readiness.py`
- [x] T065 [P] [US5] Actualizar variables sin secretos, comandos y restricciones en `.env.example`, `README.md` y `specs/006-rag-dev/quickstart.md`
- [x] T066 [P] [US5] Documentar runbook de operaciÃ³n, no fuga, aceptaciÃ³n real opt-in y prohibiciones de servidor en `docs/rag-operations.md`
- [x] T067 [US5] Ejecutar el gate G7: suite completa, cobertura focalizada mÃ­nima vigente, Ruff, mypy strict, uv lock/sync, auditorÃ­a de dependencias, Compose config, secret scan y diff manual

**Gate G7**: suite y verificaciones estÃ¡ticas/operativas verdes; no se modifican servicios remotos ni se copian corpus/secrets.

## Phase 8: AceptaciÃ³n real opt-in y polish final

**Objetivo**: comprobar solo si estÃ¡n disponibles las dependencias externas autorizadas; dejar evidencia reproducible y veredicto sin aprobar automÃ¡ticamente.

- [x] T068 Confirmar en una base aislada conteos de `INDEX_90`/`REVIEWED`/chunks activos/embeddings completos sin tocar la base cargada del servidor en `specs/006-rag-dev/agent-handoff.md`
- [x] T069 Ejecutar probe opt-in sintÃ©tico de `/api/embed` con `qwen3-embedding:4b-q4_K_M` y 2560 dimensiones sin imprimir vectores en `apps/api/tests/integration/test_ollama_real_opt_in.py`
- [x] T070 Ejecutar smoke opt-in de `/api/chat` con `qwen3.6:35b`, `stream=false` y JSON Schema sin almacenar respuestas completas ni Authorization en `apps/api/tests/integration/test_ollama_real_opt_in.py`
- [x] T071 Ejecutar smoke HTTP RAG contra fixtures sintÃ©ticos, revisar fuentes y confirmar Draft `PENDING_REVIEW` en `specs/006-rag-dev/quickstart.md`
- [x] T072 Ejecutar `uv run pytest --cov`, `uv run ruff check`, `uv run mypy`, `uv lock --check`, `uv sync --extra dev`, `docker compose config -q`, `git diff --check` y auditorÃ­a de dependencias en `specs/006-rag-dev/agent-handoff.md`
- [x] T073 Verificar que no existen PDFs, dumps, `.env`, tokens, logs, prompts, consultas, vectores o contenido prohibido en el diff/staging en `specs/006-rag-dev/agent-handoff.md`
- [x] T074 Revisar todos los tasks, el diff y la lista de migraciones para marcar Ãºnicamente lo realmente completado en `specs/006-rag-dev/tasks.md`
- [x] T075 Emitir el veredicto exacto `READY_FOR_HUMAN_RAG_EVALUATION`, `NEEDS_FIXES`, `BLOCKED_CONTRACT` o `BLOCKED_EXTERNAL` y documentar pendientes externos en `specs/006-rag-dev/agent-handoff.md`

**Gate G8**: solo con Ollama/holdout autorizados disponibles; ningÃºn umbral de adopciÃ³n se fija sin revisiÃ³n humana.

## Phase 9: OP-01 — Activación segura del índice staged

**Objetivo**: activar de forma administrativa, auditable, idempotente y reanudable las generaciones ya embebidas, sin invocar Ollama ni modificar el estado de revisión jurídica.

- [x] T076 [P] Añadir contratos y pruebas unitarias fail-closed para inspección determinista, dry-run sin escrituras, idempotencia, reanudación y errores sanitizados en `apps/api/tests/unit/test_corpus_activation.py`
- [x] T077 Extender puertos y repositorios SQLAlchemy con inspección segura de candidatos `INDEX_90`, integridad de embeddings y estado de generación en `apps/api/src/legal_ai/ports/corpus_repositories.py` y adaptadores asociados
- [x] T078 Implementar el servicio transaccional `CorpusActivationService` reutilizando `activate_generation`, `swap_generation` y `update_processing_state` en `apps/api/src/legal_ai/application/corpus_activation.py`
- [x] T079 Exponer `corpus activate-staged-index` con dry-run por defecto y `--execute` protegido por identidad de base esperada en `apps/api/src/legal_ai/cli/corpus.py`
- [x] T080 Añadir pruebas PostgreSQL reales de integridad, rollback, idempotencia, no fuga HOLDOUT y preservación de review en `apps/api/tests/integration/test_corpus_activation_postgres.py`
- [x] T081 Documentar activación separada de revisión jurídica y el procedimiento inicial de muestra de 100 decretos en `docs/runbooks/rag-operations.md` y `specs/006-rag-dev/quickstart.md`
- [x] T082 Ejecutar dry-run y `--execute` exclusivamente sobre `legal_ai_t068_20260810`, verificar los conteos posteriores y registrar evidencia sanitizada en `specs/006-rag-dev/agent-handoff.md`
- [x] T083 Repetir suite completa y gates de PostgreSQL, cobertura, Ruff, mypy strict, uv, Compose, dependencias, diff y secretos en la rama `006-rag-dev`
- [x] T084 Consolidar estado autoritativo, crear el commit autorizado, mergear con `--no-ff`, repetir gates en `main` y hacer push solo tras `MERGED_READY_FOR_SERVER_DEPLOYMENT`

**Gate G9**: activación verde en PostgreSQL temporal y en la copia aislada; revisión jurídica intacta; ninguna escritura sobre la base operativa.

## Dependencias y orden de ejecuciÃ³n

1. Fase 1 baseline.
2. Fase 2 fundaciÃ³n y migraciÃ³n 007; bloquea todas las historias.
3. Fase 3 US1 retrieval/contexto; bloquea generaciÃ³n.
4. Fase 4 US3 proveedor estructurado/coordinaciÃ³n; bloquea orquestaciÃ³n.
5. Fase 5 US1/US2/US3 API y Draft; bloquea evaluaciÃ³n completa.
6. Fase 6 US4 holdout; puede ejecutarse con provider fake sin Ollama.
7. Fase 7 US5 observabilidad y seguridad; bloquea cierre.
8. Fase 8 aceptaciÃ³n real/polish; requiere todos los gates previos.

## Oportunidades de paralelismo

- Fase 1: T002â€“T004 son independientes.
- Fase 2: T007â€“T013, T016â€“T017 pueden trabajar en archivos distintos; T018â€“T020 esperan ORM/migraciÃ³n.
- US1: T021â€“T022, T026â€“T027 son paralelizables por archivo; T024â€“T025 dependen de los puertos y el repositorio.
- US3: T029, T032â€“T034 son paralelizables; T030â€“T031 dependen de los puertos/coordinador.
- OrquestaciÃ³n: T036â€“T037 y T043â€“T046 tienen superficies separables, pero T038â€“T042 requieren sus contratos.
- US4: T051â€“T052, T055â€“T056 son paralelizables; T053â€“T054 dependen del validador.
- US5: T060â€“T063 y T065â€“T066 son paralelizables; T067 espera todo el contenido.

## Estrategia de implementaciÃ³n

1. Completar y verificar la fundaciÃ³n y migraciÃ³n 007 antes de tocar generaciÃ³n.
2. Entregar MVP fake con US1â€“US3 y PostgreSQL aislado.
3. AÃ±adir evaluaciÃ³n holdout sin fuga y luego observabilidad/seguridad.
4. Ejecutar aceptaciÃ³n real solo opt-in; un bloqueo externo no invalida los fakes ni autoriza tocar el servidor.
5. No crear commit, merge, pull ni deploy sin autorizaciÃ³n explÃ­cita posterior.

## Criterios de prueba independientes

- **US1**: retrieval/contexto deterministas; solo `REVIEWED` + `INDEX_90`; citas resolubles.
- **US2**: evidencia insuficiente produce `RAG_INSUFFICIENT_EVIDENCE` y cero Drafts.
- **US3**: schema estricto, una reparaciÃ³n mÃ¡xima, citas allowlist y Draft siempre pendiente.
- **US4**: dry-run/fake reproducibles; cero fuga holdout y mÃ©tricas null cuando no hay ground truth.
- **US5**: prioridad/monoslot, readiness diferenciado, errores sanitizados y cero persistencia parcial.

## ValidaciÃ³n del formato

Todas las tareas usan checkbox `- [ ]`, ID secuencial, marcador `[P]` solo cuando corresponde, etiqueta `[USn]` en fases de historia y ruta de archivo explÃ­cita.
