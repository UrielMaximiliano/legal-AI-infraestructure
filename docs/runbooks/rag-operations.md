# Runbook operativo: RAG jurídico 006

Este runbook cubre únicamente el RAG de borradores de decretos. El servicio
recupera datos de `INDEX_90` y documentos `REVIEWED`; `HOLDOUT_10` permanece
fuera de la base operativa y del índice.

## Antes de habilitarlo

- Verificar PostgreSQL, pgvector y readiness de embeddings.
- Verificar que el modelo de embeddings sea
  `qwen3-embedding:4b-q4_K_M` con 2560 dimensiones y que la generación use
  `qwen3.6:35b` por `/api/chat`.
- Configurar la URL generativa remota con HTTPS y Bearer. HTTP solo se admite
  para los hosts locales explícitamente permitidos por el adaptador.
- Aplicar la migración 007 en una base aislada antes de cualquier promoción.
- Mantener el manifiesto holdout y sus PDF en almacenamiento externo controlado;
  el repositorio solo contiene el ejemplo sin contenido real.

## Operación normal

Solicitar `POST /api/v1/rag/drafts/generate` con un `Idempotency-Key` nuevo y
guardar únicamente el `rag_run_id` y el `request_id`. Consultar el run para
diagnóstico; no se exponen prompt, consulta, contexto, vectores ni contenido
completo de documentos.

Un Draft RAG siempre queda pendiente de revisión humana. No aprobar, finalizar
ni exportar automáticamente como consecuencia de una generación exitosa.

## Fallos y diagnóstico

| Señal | Acción |
|---|---|
| `RAG_INSUFFICIENT_EVIDENCE` | Revisar elegibilidad `REVIEWED`/`INDEX_90`; no forzar fuentes. |
| `SEMANTIC_SEARCH_AUDIT_UNAVAILABLE` | Recuperar la disponibilidad de PostgreSQL; no reintentar con corpus alternativo. |
| `OLLAMA_UNAVAILABLE` o `OLLAMA_TIMEOUT` | Verificar readiness, límite de cola y endpoint; repetir con una key nueva. |
| `RAG_OUTPUT_INVALID` | Revisar el run y el contador de reparación; no aumentar el límite automático. |
| `RAG_GENERATION_IN_PROGRESS` | Consultar el run de la operación original; no crear una segunda key concurrente. |

Los errores públicos son códigos estables. No copiar tokens, Authorization,
prompts, consultas, PDFs, texto documental ni dumps a issues, logs o commits.

## Evaluación holdout

El dry-run no llama a Ollama ni escribe PostgreSQL. El provider fake sirve para
validar el pipeline y reproducibilidad; el provider real es opt-in y requiere
autorización explícita. Los resultados solo guardan IDs opacos, hashes,
métricas y latencias. Un hallazgo de fuga bloquea la evaluación.

## Cambios y recuperación

No modificar las migraciones 001–006 ni reiniciar el worker de embeddings desde
este incremento. Para una migración, usar una PostgreSQL temporal y verificar
`006 -> 007 -> 006 -> 007`; cualquier fallo deja el release en espera de
corrección. La aceptación jurídica y cualquier decisión de adopción requieren
revisión humana posterior.

## Activación segura de una generación ya embebida

La activación técnica del índice y la revisión jurídica son operaciones
independientes. Activar chunks no cambia `review_status`, `review_version`,
`reviewed_by` ni `reviewed_at`; por lo tanto, un documento activado continúa
sin ser recuperable por el RAG hasta que una persona lo apruebe.

Ejecutar primero contra una base aislada y declarar su nombre exacto:

```powershell
cd apps/api
uv run corpus activate-staged-index `
  --expected-database legal_ai_t068_20260810
```

El dry-run es el comportamiento por defecto y realiza cero escrituras. Falla
cerrado si detecta `HOLDOUT_10`, generaciones/estados incompatibles, embeddings
ausentes, modelo distinto de `qwen3-embedding:4b-q4_K_M`, dimensiones distintas
de 2560, valores no finitos, documentos incompletos o una base cuyo nombre no
coincide con `--expected-database`.

Solo si el reporte devuelve `status=ready` y `violations=[]`:

```powershell
uv run corpus activate-staged-index `
  --expected-database legal_ai_t068_20260810 `
  --execute
```

La ejecución bloquea y confirma cada documento en una transacción corta,
reutiliza `activate_generation`, `swap_generation` y
`update_processing_state`, no llama a Ollama y no recalcula embeddings. Puede
repetirse: documentos ya activos se omiten y una interrupción se reanuda con el
mismo comando. No ejecutar contra la base operativa sin una autorización nueva.

## Revisión humana inicial

No aprobar en bloque los 9.000 documentos. Seleccionar una muestra inicial de
100 decretos, revisar contenido y metadatos jurídicos, y aprobar uno por uno con
control optimista de versión:

```powershell
uv run corpus review DOCUMENT_ID --approve `
  --reviewed-by "IDENTIDAD_DEL_REVISOR" `
  --expected-version N
```

Registrar la selección y el criterio fuera del repositorio si contienen datos
del corpus. Un conflicto de versión requiere volver a leer el documento; nunca
se debe forzar ni incrementar la versión manualmente.
