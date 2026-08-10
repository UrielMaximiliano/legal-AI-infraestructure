# Especificación: Generación de Decretos Asistida por RAG

**Spec ID**: `006-retrieval-augmented-generation`
**Created**: 2026-08-07
**Status**: READY_FOR_PLANNING
**Input**: Construir un RAG jurídico sobre el corpus de decretos nacionales del incremento 005, usando el 90% indexado para recuperar antecedentes y el 10% reservado para evaluar la generación de borradores.

## Resumen ejecutivo

Este incremento agrega generación asistida por recuperación para producir borradores estructurados de decretos nacionales. El sistema recuperará fragmentos jurídicos pertinentes del corpus `INDEX_90`, construirá un contexto trazable y solicitará al modelo generativo un borrador JSON validable. Cada afirmación jurídica relevante deberá vincularse con antecedentes recuperados y toda salida permanecerá sujeta a revisión humana.

El conjunto `HOLDOUT_10` no participará en la recuperación ni en el entrenamiento. Se conservará fuera del índice para evaluar, sin fuga de información, cuánto se aproxima el borrador generado a documentos oficiales no vistos.

## Declaración del problema

### Estado actual

El incremento 005 permite ingerir, normalizar, segmentar, vectorizar y buscar semánticamente decretos. También existe un flujo de plantillas, expedientes, borradores y revisión humana, pero la generación actual no incorpora automáticamente antecedentes recuperados ni conserva una relación auditable entre cada borrador y sus fuentes.

### Estado deseado

Un operador autorizado podrá solicitar un borrador de decreto a partir de un expediente, una plantilla y variables validadas. El sistema recuperará antecedentes comparables, ensamblará un contexto acotado, generará una respuesta estructurada, verificará su formato y sus citas, persistirá la trazabilidad y entregará un borrador marcado como no vinculante y pendiente de revisión.

### Impacto institucional

- Reduce el tiempo necesario para localizar antecedentes pertinentes.
- Hace auditable qué documentos influyeron en cada borrador.
- Permite medir la fidelidad de la generación contra 1.000 decretos reservados.
- Reduce el riesgo de normas, hechos o autoridades inventadas.
- Mantiene la decisión jurídica y aprobación final bajo control humano.

## Alcance

### Incluido

- Generación RAG de borradores de decretos nacionales.
- Recuperación sobre chunks activos de documentos `REVIEWED` pertenecientes a `INDEX_90`.
- Consulta semántica derivada de datos validados del expediente y la plantilla.
- Selección, diversificación y presupuesto de contexto deterministas.
- Salida JSON versionada con secciones jurídicas explícitas.
- Citas a documentos y chunks recuperados.
- Validación estructural, de cobertura de citas y de contenido prohibido.
- Auditoría completa y minimizada de recuperación y generación.
- Idempotencia, reintentos controlados y coordinación con el único slot de inferencia.
- Evaluación sin fuga usando los 1.000 documentos de `HOLDOUT_10`.
- Integración con el flujo existente de borradores y revisión humana.
- Ejecución local reproducible y prueba real opcional contra el Ollama autorizado.

### Fuera de alcance

- Fine-tuning o entrenamiento de modelos.
- Agentes autónomos, MCP o navegación web durante la generación.
- Incorporar `HOLDOUT_10` al índice de recuperación.
- Aprobación, firma, publicación o exportación automática del acto.
- RAG sobre leyes, resoluciones, jurisprudencia u otros tipos documentales.
- HNSW u otro índice aproximado sin una decisión posterior basada en evidencia.
- OCR, scraping o nueva ingesta documental.
- Frontend nuevo.
- Reemplazar el sistema de revisión humana de los incrementos 003 y 004.

## Escenarios de usuario y pruebas

### Escenario 1 — Generar un borrador con antecedentes trazables (P1)

Un operador solicita un borrador para un expediente válido. El sistema recupera antecedentes pertinentes, genera un decreto estructurado y devuelve las fuentes utilizadas.

**Aceptación independiente**:

1. Dado un expediente, plantilla y variables válidos, cuando se solicita generación RAG, entonces se crea un borrador pendiente de revisión con esquema válido y al menos una fuente si existe evidencia suficiente.
2. Cada fuente devuelta identifica documento, chunk, sección, orden y puntaje sin exponer embeddings ni contenido completo.
3. El borrador indica de forma visible que es asistido, no vinculante y requiere revisión humana.
4. La misma clave idempotente y el mismo payload no generan un segundo intento ni un segundo borrador.

### Escenario 2 — Fallar de forma segura ante evidencia insuficiente (P1)

Un operador solicita un decreto para el cual el corpus no aporta antecedentes suficientes.

**Aceptación independiente**:

1. Si no se alcanza la evidencia mínima configurada, no se genera texto jurídico presentado como fundado.
2. La respuesta informa `RAG_INSUFFICIENT_EVIDENCE` y enumera únicamente advertencias sanitizadas.
3. No se inventan leyes, artículos, competencias, autoridades, fechas ni hechos ausentes del expediente o de fuentes recuperadas.

### Escenario 3 — Validar y revisar la salida estructurada (P1)

El modelo devuelve una propuesta que debe validarse antes de persistirse como borrador.

**Aceptación independiente**:

1. La respuesta contiene título, VISTO, considerandos, parte dispositiva, artículos, cierre, autoridad, firma, fuentes y advertencias conforme al schema vigente.
2. Una respuesta inválida puede regenerarse una única vez con instrucciones de corrección; si continúa inválida, el intento falla sin crear borrador.
3. Una cita desconocida o no recuperada causa rechazo de la salida.
4. Un borrador válido entra al flujo existente de revisión y nunca queda aprobado automáticamente.

### Escenario 4 — Evaluar contra el holdout sin fuga (P2)

Un evaluador ejecuta un benchmark con documentos oficiales reservados.

**Aceptación independiente**:

1. Los 1.000 PDF de `HOLDOUT_10` permanecen fuera de las tablas y búsquedas usadas por el RAG.
2. El evaluador deriva entradas y referencias esperadas sin persistir el texto del holdout en el índice.
3. Se registran fidelidad a fuentes, validez del schema, secciones presentes, citas inválidas, utilidad jurídica humana y latencias.
4. Los resultados distinguen evaluación determinista con fake y evaluación real con modelos autorizados.

### Escenario 5 — Degradación y concurrencia seguras (P2)

La base, el proveedor de embeddings o el modelo generativo no están disponibles, o el slot está ocupado por embeddings masivos.

**Aceptación independiente**:

1. La generación interactiva recibe prioridad sobre nuevos batches, sin interrumpir una inferencia ya iniciada.
2. Un fallo de recuperación, auditoría o generación no produce un borrador parcial.
3. Los errores públicos no incluyen prompts, consultas, documentos, rutas, tokens, vectores ni stack traces.
4. Los health checks distinguen recuperación disponible, modelo de embeddings disponible y modelo generativo disponible.

### Casos límite

- Resultados redundantes del mismo documento o de la misma sección.
- Un chunk demasiado largo para el presupuesto de contexto.
- Artículos o referencias normativas que no caben completos.
- Fuentes con puntajes iguales.
- Modelo que envuelve JSON en Markdown o agrega texto fuera del objeto.
- Respuesta JSON truncada, vacía o con campos desconocidos.
- Citas duplicadas, desconocidas o que no respaldan el texto citado.
- Expediente o plantilla modificados durante una generación.
- Reintento después de timeout o caída del proveedor.
- Cancelación del cliente mientras la inferencia ya comenzó.
- Cero documentos elegibles porque ninguno está `REVIEWED`.

## Requisitos funcionales

### Recuperación y contexto

- **FR-001**: El sistema DEBE recuperar exclusivamente chunks activos de la generación activa de documentos `REVIEWED` incluidos en `INDEX_90`.
- **FR-002**: El sistema DEBE excluir `HOLDOUT_10` de toda recuperación operativa y prueba que pretenda medir ausencia de fuga.
- **FR-003**: La consulta de recuperación DEBE construirse solo con campos validados y permitidos del expediente, plantilla y variables.
- **FR-004**: Los filtros `document_type=decreto`, `jurisdiction=nacion` y el subtipo aprobado DEBEN aplicarse de forma fail-closed.
- **FR-005**: La selección DEBE ser determinista ante puntajes iguales y limitar redundancia por documento y sección.
- **FR-006**: El contexto DEBE respetar un presupuesto configurable y preservar indivisibles los artículos y referencias jurídicas cuando sea posible.
- **FR-007**: Cada fragmento del contexto DEBE poseer un identificador de cita opaco que pueda resolverse al documento y chunk recuperados.
- **FR-008**: Si la evidencia mínima no se satisface, la generación DEBE detenerse con `RAG_INSUFFICIENT_EVIDENCE`.

### Generación y validación

- **FR-009**: La generación DEBE usar el modelo contractual `qwen3.6:35b` y registrar nombre, versión de prompt y parámetros relevantes.
- **FR-010**: La recuperación DEBE mantener el contrato `qwen3-embedding:4b-q4_K_M`, 2560 dimensiones y `halfvec(2560)`.
- **FR-011**: La salida principal DEBE ser JSON estricto conforme a un schema versionado.
- **FR-012**: El schema DEBE representar explícitamente título, VISTO, considerandos, introducción dispositiva, artículos, cierre, autoridad, firma, fuentes y advertencias.
- **FR-013**: El sistema DEBE rechazar campos desconocidos, secciones obligatorias vacías y referencias a fuentes no recuperadas.
- **FR-014**: El sistema DEBE permitir como máximo una regeneración automática por error de schema y DEBE registrar ambos intentos.
- **FR-015**: Todo borrador creado DEBE quedar en estado pendiente de revisión y marcado como asistido/no vinculante.
- **FR-016**: El contenido estructurado validado DEBE convertirse de forma determinista al formato de borrador existente sin mezclar generación con renderizado DOCX/PDF.

### Auditoría, persistencia e idempotencia

- **FR-017**: Cada ejecución DEBE registrar un run con hashes minimizados de entrada, modelo generativo, modelo de embeddings, versiones, estado, latencias, conteos y código de error sanitizado.
- **FR-018**: Cada run exitoso DEBE vincular los documentos y chunks recuperados, orden, puntaje y uso o descarte en el contexto.
- **FR-019**: Si la auditoría de recuperación o generación no puede persistirse, el sistema DEBE fallar cerrado sin devolver ni persistir un borrador parcial.
- **FR-020**: La idempotencia DEBE considerar expediente, plantilla, variables, configuración RAG y versiones de prompt/modelos.
- **FR-021**: Ninguna transacción DEBE permanecer abierta durante embeddings, espera del coordinador, generación, timeout, backoff o retry.
- **FR-022**: Un fallo posterior a la recuperación DEBE dejar un intento auditable y no un borrador huérfano.

### Seguridad y operación

- **FR-023**: El backend será el único componente autorizado para acceder a los modelos.
- **FR-024**: Los documentos recuperados DEBEN tratarse como datos no confiables y nunca como instrucciones para el modelo.
- **FR-025**: Logs y errores NO DEBEN contener prompts completos, consultas completas, texto documental completo, embeddings, tokens, Authorization, secretos, rutas internas ni stack traces públicos.
- **FR-026**: El coordinador DEBE conservar un único slot de inferencia y priorizar generación/búsqueda interactiva sobre trabajo batch pendiente.
- **FR-027**: Timeouts y reintentos DEBEN ser acotados, deterministas por clase de error y seguros para idempotencia.
- **FR-028**: Readiness DEBE distinguir base de datos, recuperación, modelo de embeddings y modelo generativo.
- **FR-029**: El endpoint existente de generación no RAG DEBE conservar compatibilidad.

### Evaluación

- **FR-030**: Debe existir un dataset de evaluación versionado derivado del holdout sin incorporar sus contenidos al índice.
- **FR-031**: La evaluación DEBE medir Recall@K, Precision@K y MRR de recuperación cuando exista verdad de referencia.
- **FR-032**: La evaluación DEBE medir validez del JSON, presencia de secciones, cobertura de citas, citas inválidas, fidelidad a fuentes y al expediente, y tasa de invención.
- **FR-033**: La evaluación humana DEBE registrar utilidad jurídica, correcciones requeridas y aprobación/rechazo sin almacenar datos sensibles innecesarios.
- **FR-034**: Las métricas de generación DEBEN incluir latencia p50/p95/máxima y tasa de éxito/fallo.
- **FR-035**: No se DEBEN declarar umbrales de calidad aprobados hasta medir una línea base reproducible.

## Requisitos no funcionales

### Rendimiento

- La configuración inicial admitirá entre 3 y 20 resultados recuperados, con valor por defecto 8.
- El contexto enviado al generador estará limitado por bytes y tokens estimados configurables.
- La evaluación separará latencia de embeddings, búsqueda, ensamblado, generación y validación.
- La búsqueda exacta seguirá siendo la línea base hasta que evidencia posterior justifique otro índice.

### Disponibilidad

- Un fallo del modelo generativo no debe afectar búsqueda semántica ni funcionalidades 001–005.
- Un fallo del proveedor de embeddings debe impedir nuevas consultas RAG, pero no debe corromper borradores existentes.
- Los intentos fallidos deben poder reintentarse con idempotencia estable.

### Seguridad y privacidad

- Toda inferencia utilizará exclusivamente el endpoint Ollama autorizado.
- HTTPS y Bearer serán obligatorios para rutas remotas; HTTP solo se permitirá en endpoints locales explícitamente admitidos.
- La API aplicará límites de tamaño, allowlists, sanitización y correlación por `request_id`.
- Los borradores y fuentes solo estarán disponibles para actores autorizados por el sistema existente.

### Escalabilidad

- El MVP conservará un único slot de inferencia y backpressure explícito.
- El diseño permitirá cambiar límites de contexto y top-k sin cambiar el schema persistente.
- Un cambio de modelo de embeddings, dimensión, normalización o chunking exige reindexación; un cambio de modelo generativo o prompt exige nueva versión de generación, no reindexación.

## Criterios de éxito

- **SC-001**: El 100% de las respuestas exitosas valida contra el schema JSON vigente.
- **SC-002**: El 100% de las citas devueltas se resuelve a un documento y chunk realmente recuperados.
- **SC-003**: Cero documentos de `HOLDOUT_10` aparecen en el índice o en fuentes de una generación operativa.
- **SC-004**: Cero borradores RAG se crean cuando recuperación, auditoría o validación final falla.
- **SC-005**: El 100% de los borradores RAG queda pendiente de revisión y contiene la advertencia no vinculante.
- **SC-006**: Repetir una solicitud con la misma clave idempotente y payload produce un único run efectivo y un único borrador.
- **SC-007**: Los tests de seguridad no detectan prompts, consultas, contenido completo, vectores, tokens ni secretos en logs o respuestas de error.
- **SC-008**: El benchmark reporta Recall@3/5, Precision@3/5, MRR, validez estructural, fidelidad, invenciones, utilidad humana y latencia sin inventar umbrales.
- **SC-009**: Las funcionalidades 001–005 conservan sus contratos y su suite sin regresiones.
- **SC-010**: Un operador puede reproducir localmente un flujo fake completo y ejecutar de forma opcional un smoke real contra los dos modelos autorizados.

## Entidades clave

- **RagGenerationRun**: ejecución auditable de recuperación, armado de contexto, generación y validación.
- **RagRetrievedSource**: vínculo ordenado entre un run y un documento/chunk recuperado, con puntaje y decisión de inclusión.
- **RagPromptVersion**: identificación inmutable de la plantilla de sistema, contrato de salida y estrategia de contexto.
- **RagStructuredDraft**: salida JSON validada asociada al borrador existente.
- **RagEvaluationCase**: entrada versionada derivada de un documento holdout y sus expectativas, sin indexarlo.
- **RagEvaluationResult**: métricas automáticas y evaluación humana de un caso/modelo/configuración.

## Supuestos y decisiones

- El corpus operativo contiene 9.000 decretos `INDEX_90` y 65.916 chunks, pero solo los documentos `REVIEWED` serán elegibles.
- Los 1.000 PDF de `HOLDOUT_10` permanecen fuera de la base operativa y se conservan en almacenamiento de evaluación controlado.
- El modelo generativo contractual es `qwen3.6:35b` y el modelo de embeddings contractual es `qwen3-embedding:4b-q4_K_M` con 2560 dimensiones.
- El subtipo inicial sigue siendo `designacion_transitoria`; ampliar subtipos requiere otro incremento o aclaración contractual.
- El RAG se integra con borradores, expedientes, plantillas y revisión humana existentes sin cambiar su semántica.
- La línea base usa búsqueda vectorial exacta y top-k 8; diversificación y presupuesto de contexto son deterministas.
- Los resultados de calidad iniciales son informativos. La aprobación de umbrales requiere revisión humana posterior.

## Dependencias

- Incrementos 001–005 aplicados y sin regresiones.
- Migración 006 y corpus `INDEX_90` disponibles.
- Endpoint de embeddings operativo con `qwen3-embedding:4b-q4_K_M` y 2560 dimensiones.
- Endpoint de generación operativo con `qwen3.6:35b`.
- PostgreSQL con pgvector y chunks activos completamente embebidos antes del benchmark final.
- Acceso controlado a los 1.000 PDF holdout para evaluación.

## Riesgos

- Pocos documentos podrían ser elegibles si el estado `REVIEWED` no refleja la curación real.
- La ausencia de un índice aproximado puede elevar latencia; se medirá antes de optimizar.
- Un contexto excesivo puede degradar calidad o superar límites del modelo.
- Los decretos recuperados pueden contener texto que parezca una instrucción al modelo.
- La comparación con holdout puede producir métricas engañosas si la extracción de expectativas no se revisa.
- El modelo generativo puede devolver JSON inválido o fuentes inventadas.
- El único slot de inferencia obliga a coordinar embeddings batch y generación interactiva.

## Veredicto

`READY_FOR_PLANNING`
