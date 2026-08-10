# 006-rag-dev — handoff autoritativo

**Fecha de evidencia**: 2026-08-10
**Rama**: `main`
**Estado autoritativo**: `MERGED_READY_FOR_SERVER_DEPLOYMENT`

Este documento reemplaza cualquier reporte histórico de `NEEDS_FIXES` o
`BLOCKED_EXTERNAL`. No autoriza despliegue ni escrituras sobre la base operativa.

## Fases y tareas

- Fases 1–8: T001–T075 completas.
- OP-01 e integración: T076–T084 completas.

## Evidencia externa T068/T069

T068 se verificó sobre la copia aislada `legal_ai_t068_20260810`, schema 006,
551 MB. El dump externo `backups/legal_ai_t068_20260810.custom.dump` tiene
SHA-256 `11124bd23fb959f748a68a98039cbf19dc31837538136a932ef1bc55227d4f44` y
no fue copiado al repositorio.

Estado inicial confirmado: 9.000 documentos, 65.916 chunks `INDEX_90`, 65.916
embeddings, cero embeddings pendientes, dimensiones mínimas/máximas 2560, cero
`HOLDOUT_10`, cero `REVIEWED`, 9.000 `PENDING_REVIEW`, cero `ACTIVE`, 65.916
`STAGED` y 9.000 documentos sin `active_generation`.

T069 quedó verde con evidencia externa opt-in: `/ollama/api/embed` exige Bearer
(401 sin credencial, 200 con credencial), modelo
`qwen3-embedding:4b-q4_K_M`, dos vectores de 2560 dimensiones y valores finitos.
`test_real_ollama_embed_contract_opt_in`: 1 passed. El endpoint legacy
`/api/embeddings` también respondió 200 con 2560 dimensiones. No se registraron
credenciales, Authorization ni vectores.

## OP-01 — activación segura

Se agregó `corpus activate-staged-index`, dry-run por defecto, con guard por
nombre exacto de base, generación y batch configurables. El preflight falla
cerrado ante split holdout, estados/generaciones incompatibles, documentos
incompletos, embeddings ausentes, modelo o dimensión incorrectos y valores no
finitos. No llama a Ollama ni recalcula embeddings.

La ejecución bloquea filas en orden determinista y aplica por lote, dentro de
una transacción corta:

1. `activate_generations` (equivalente batch de `activate_generation`);
2. `swap_generations` (equivalente batch de `swap_generation`);
3. `update_processing_states(COMPLETED, EMBEDDED)`.

Una interrupción dejó 500 documentos confirmados; la reanudación activó los
8.500 restantes y demostró recuperación segura. El replay posterior activó cero
documentos y reconoció 9.000 ya activos.

Postcheck de la copia aislada:

- documentos: 9.000; `active_generation=1`: 9.000; NULL: 0;
- chunks: 65.916 `ACTIVE`; 0 `STAGED`; embeddings: 65.916;
- dimensiones min/max: 2560/2560; modelo incorrecto: 0;
- inconsistencias documento/generación: 0;
- `HOLDOUT_10` documentos/chunks: 0/0;
- procesamiento: 9.000 `COMPLETED` + `EMBEDDED`;
- revisión: 9.000 `PENDING_REVIEW`, versión min/max 1/1 y checksum 9.000.

No se ejecutó ninguna escritura contra la base operativa.

## RAG y revisión humana

La recuperación sigue siendo exacta, sin HNSW, y restringida a documentos
`REVIEWED` de `INDEX_90` con chunks de la generación activa. La generación usa
`qwen3.6:35b` por `/api/chat`, `stream=false`, JSON Schema estricto, una única
reparación acotada y citas resolubles allowlist. Auditoría, schema y citas son
fail-closed; no se crea Draft parcial. El Draft se persiste `en_revision`, la
respuesta contractual es `PENDING_REVIEW`, se abre `DocumentReview` y no existe
aprobación/finalización automática.

La evaluación holdout calcula métricas reales desde referencias declaradas y
consulta un guard persistente de no fuga. Los 1.000 PDF permanecen externos y
no se insertan ni vectorizan.

El RAG operativo recuperará cero antecedentes hasta que una persona revise
documentos. El runbook prescribe una muestra inicial de 100 decretos, uno por
uno, con:

```text
corpus review DOCUMENT_ID --approve --reviewed-by "..." --expected-version N
```

No aprobar automáticamente los 9.000 documentos.

## Validación de rama y main

- PostgreSQL/pgvector temporal real: verde.
- Migración: `006 -> 007 -> 006 -> 007`, verde; 001–006 sin cambios.
- OP-01 PostgreSQL: 3 passed (atomicidad, rollback, idempotencia, no fuga y
  preservación de revisión).
- Suite completa: 876 passed, 11 skipped en 195,25 s.
- Suite con cobertura: 876 passed, 11 skipped; 85,02% (mínimo 85%).
- Ruff: verde.
- mypy strict: verde, 190 archivos fuente.
- `uv lock --check` y `uv sync --extra dev`: verdes.
- `docker compose config -q`: verde.
- `pip-audit`: cero vulnerabilidades conocidas; paquete local no publicable se
  omite por no existir en PyPI.
- `git diff --check`: verde.
- Secret scan y archivos prohibidos: cero hallazgos.
- PDFs, dumps, `.env`, tokens, logs, prompts, consultas, vectores, corpus y
  Authorization: no agregados al diff.

## Pendientes operativos posteriores

- Desplegar en el servidor mediante un procedimiento separado, con backup y
  control de cambios; esta pasada no hizo pull, deploy ni reinicios remotos.
- Revisar humanamente una muestra inicial de 100 decretos antes de habilitar
  recuperación útil; no aprobar automáticamente los 9.000.
- Ejecutar la evaluación jurídica del holdout externo y registrar sus métricas
  sin copiar PDF ni corpus al repositorio.
