# Research: RAG Jurídico 006

**Fecha**: 2026-08-07
**Estado**: COMPLETE

## R1 — Endpoint generativo y salida estructurada

**Decisión**: usar `POST /api/chat` con `stream=false` y el JSON Schema completo en `format`.

**Fundamento**: Ollama documenta que `/api/chat` admite un JSON Schema en `format`; esto permite exigir una estructura antes de aplicar la segunda validación Pydantic/dominio. `qwen3.6:35b` está publicado para chat y es el modelo instalado en el servidor.

**Alternativas consideradas**:

- `/api/generate`: ya existe en el cliente legacy, pero el contrato conversacional system/user y el esquema explícito son más claros con chat.
- `format="json"`: exige JSON válido pero no la estructura jurídica completa.
- Parsear texto libre: rechazado por la constitución.

**Evidencia primaria**:

- Ollama Chat API: `https://docs.ollama.com/api/chat`
- Ollama Structured Outputs: `https://docs.ollama.com/capabilities/structured-outputs`
- Modelo: `https://ollama.com/library/qwen3.6:35b`

## R2 — Adaptador nuevo frente al cliente legacy

**Decisión**: crear un puerto `StructuredGenerationProvider` y un adaptador Ollama específico; no extender silenciosamente el comportamiento de `application/ollama_client.py`.

**Fundamento**: el cliente existente usa `/api/generate`, devuelve texto y soporta contratos 003/004. Un adaptador separado preserva compatibilidad y permite validar schema, thinking, estadísticas y errores sin acoplar el dominio a Ollama.

**Alternativas consideradas**:

- Modificar `OllamaClient.generate`: riesgo de regresión y mezcla de contratos.
- Reemplazar el endpoint legacy: fuera de alcance.

## R3 — Reutilización de recuperación 005

**Decisión**: extraer el núcleo de recuperación a `RetrievalService`; `SemanticSearchService` y `RagGenerationService` lo consumen con políticas diferentes.

**Fundamento**: el servicio actual ya implementa embedding de consulta, búsqueda exacta, filtros y auditoría. Duplicarlo produciría divergencias. El núcleo debe devolver candidatos internos y métricas; cada fachada mantiene su respuesta y auditoría.

**Alternativas consideradas**:

- Llamar internamente al endpoint HTTP 005: añade red, serialización y acoplamiento innecesario.
- Duplicar SQL/embedding: rechazado por riesgo de inconsistencia.

## R4 — Política del corpus

**Decisión**: recuperación fail-closed sobre `REVIEWED`, generación activa e `INDEX_90`.

**Fundamento**: la constitución exige corpus controlado y revisión humana. El holdout debe ser invisible para medir generalización. El filtro de split debe comprobarse en consulta SQL y en un guard de evaluación.

**Alternativas consideradas**:

- Permitir `PENDING_REVIEW`: aumenta cobertura pero viola la política aprobada.
- Cargar holdout y filtrarlo solo en aplicación: riesgo de fuga; se mantiene fuera de la base operativa.

## R5 — Estrategia exacta y diversificación

**Decisión**: mantener exact cosine search, recuperar un pool de hasta `3 × top_k` y diversificar determinísticamente con máximo 2 chunks por documento.

**Fundamento**: 005 estableció exact search como baseline y no justificó HNSW. La diversificación simple reduce que un único decreto monopolice el contexto sin introducir re-ranking por LLM.

**Alternativas consideradas**:

- HNSW: diferido hasta evidencia de volumen/latencia.
- Re-ranker: fuera del MVP; agrega modelo, latencia y superficie de error.
- Un chunk por documento: puede perder VISTO y artículo complementarios.

## R6 — Presupuesto de contexto

**Decisión**: presupuesto dual configurable por bytes y tokens estimados, con default conservador de 65.536 bytes/16.384 tokens estimados.

**Fundamento**: la ventana publicada del modelo no debe usarse como objetivo operativo. Reservar capacidad para instrucciones, expediente, schema y respuesta reduce truncamientos y latencia. Los límites se ajustarán con medición real.

**Alternativas consideradas**:

- Usar toda la ventana del modelo: costoso, lento y frágil.
- Solo límite por caracteres: menos reproducible con Unicode y tokenización.

## R7 — Prevención de prompt injection

**Decisión**: tratar cada chunk como dato no confiable, encerrarlo en un sobre estructurado con citation ID y prohibir tools/acciones durante generación.

**Fundamento**: el corpus puede contener texto imperativo legítimo o malicioso. Las instrucciones system declaran que el bloque de evidencia nunca contiene órdenes. El validador solo acepta citation IDs emitidos por el backend.

**Alternativas consideradas**:

- Limpieza por palabras prohibidas: insuficiente y propensa a falsos positivos.
- Confiar en el prompt: insuficiente sin validación posterior.

## R8 — Salida y reparación

**Decisión**: JSON Schema cerrado, Pydantic estricto, validación de dominio y una única reparación automática de schema.

**Fundamento**: el schema del proveedor reduce errores, pero la aplicación sigue siendo autoridad. Una reparación acotada mejora disponibilidad sin loops y conserva auditabilidad.

**Alternativas consideradas**:

- Cero reparaciones: más simple pero desperdicia respuestas corregibles.
- Reintentos ilimitados: riesgo de costo, latencia y no determinismo.

## R9 — Persistencia y fail-closed

**Decisión**: crear el run antes de inferencia, confirmarlo, ejecutar inferencia sin transacción y persistir salida válida + Draft en una transacción corta final.

**Fundamento**: conserva evidencia de fallos sin mantener locks durante GPU. Si la persistencia final falla, no se devuelve un borrador. Los vínculos de fuentes se registran antes o junto al cierre del run con invariantes explícitas.

**Alternativas consideradas**:

- Una transacción para todo: rechazado por timeout/locks.
- Crear Draft antes de validar: produce borradores parciales.

## R10 — Idempotencia

**Decisión**: hash canónico de `case_file_id`, `template_id`, variables, versiones de prompt/schema, modelos, filtros y límites; combinar con `Idempotency-Key`.

**Fundamento**: cambiar configuración RAG cambia materialmente la salida. La clave sola no distingue payloads y el payload solo no expresa intención de reintento.

**Alternativas consideradas**:

- Reutilizar exactamente el hash 003: no incluye recuperación/modelos.
- Deduplicar solo por expediente: impediría regeneraciones legítimas.

## R11 — Coordinación del único slot

**Decisión**: usar `InferencePriority.INTERACTIVE` para generación, `SEARCH` para embedding de consulta y `BATCH_INGESTION` para embeddings masivos.

**Fundamento**: esas prioridades ya existen. La generación no interrumpe una inferencia activa, pero precede a trabajos batch pendientes. No se introduce otro coordinador.

**Alternativas consideradas**:

- Concurrencia paralela: contradice el monoslot real.
- Detener batches de forma destructiva: innecesario y riesgoso.

## R12 — Evaluación holdout

**Decisión**: manifiesto versionado con hashes y rutas relativas externas; extracción de expectativas offline; nunca insertar ni vectorizar el holdout en la base operativa.

**Fundamento**: el holdout debe representar decretos no vistos. La evaluación compara estructura, campos y contenido contra el PDF reservado, además de revisión humana. Los textos completos permanecen fuera de Git y de logs.

**Alternativas consideradas**:

- Insertar holdout con flag: aumenta riesgo de fuga accidental.
- Comparación puramente semántica por otro LLM: costosa y puede ocultar errores; solo complemento opcional.

## R13 — Métricas y umbrales

**Decisión**: producir baseline sin declarar aprobación automática.

**Fundamento**: la constitución exige medición sobre un conjunto común y revisión humana. Se registran Recall@3/5, Precision@3/5, MRR, schema validity, cobertura de citas, citas inválidas, secciones, invenciones, utilidad jurídica y latencias.

**Alternativas consideradas**:

- Umbrales inventados antes del baseline: rechazado.
- Solo evaluación subjetiva: insuficiente para comparar configuraciones.

## R14 — Migración

**Decisión**: migración `007` aunque el incremento funcional sea 006.

**Fundamento**: la migración 006 ya está ocupada por el cambio a `halfvec(2560)`. La numeración de migraciones es secuencial e independiente del número funcional.

**Alternativas consideradas**:

- Modificar migración 006: destruiría reproducibilidad de bases ya actualizadas.

## R15 — Dependencias nuevas

**Decisión**: no agregar una dependencia RAG/orquestador. Usar stdlib, Pydantic, httpx, SQLAlchemy y componentes existentes.

**Fundamento**: el pipeline es lineal y auditable. LangChain/LlamaIndex añadirían abstracción y dependencias sin resolver una necesidad actual.

**Alternativas consideradas**:

- LangChain/LlamaIndex: diferidos; no justifican el costo para este flujo.

## Resultado

Todas las decisiones necesarias para diseño están resueltas. No quedan marcadores `NEEDS CLARIFICATION`.
