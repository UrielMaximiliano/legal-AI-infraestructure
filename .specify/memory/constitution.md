# Legal-AI-Infraestructure Constitution

<!-- Sync Impact Report -->
<!-- Version change: N/A → 1.0.0 (initial adoption) -->
<!-- Modified principles: N/A (initial creation) -->
<!-- Added sections: I-XX (20 principles) + Governance -->
<!-- Removed sections: N/A -->
<!-- Deferred items: None -->
<!-- End Sync Impact Report -->

## Core Principles

### I. Seguridad y Privacidad por Diseño

- Los documentos jurídicos, expedientes, datos personales, DNI, CUIL, legajos y demás información sensible NO deben enviarse a proveedores externos de IA.
- La inferencia y los embeddings deben realizarse mediante el endpoint privado de Ollama autorizado.
- Ningún secreto, token, contraseña, certificado o archivo `.env` debe almacenarse en Git.
- El frontend NUNCA debe acceder directamente a Ollama, PostgreSQL o Redis.
- Toda comunicación con modelos debe pasar por la API backend.
- Los logs NO deben registrar documentos completos, prompts completos con datos personales, DNI, CUIL, contraseñas ni secretos.
- Deben aplicarse validación de entrada, límites de tamaño, timeouts, reintentos controlados y manejo explícito de errores.
- Las dependencias deben fijarse mediante versiones reproducibles y someterse a análisis de vulnerabilidades.
- Debe aplicarse el principio de mínimo privilegio en aplicación, base de datos, contenedores y Kubernetes.

**Rationale**: La protección de datos judiciales y personales es legalmente obligatoria y éticamente innegociable. Cualquier fuga tiene consecuencias severas.

### II. Asistencia, No Decisión Autónoma

- El sistema genera borradores y sugerencias; NO emite, aprueba ni firma actos administrativos.
- Toda salida debe considerarse un borrador no vinculante.
- La revisión humana es OBLIGATORIA antes de exportar, aprobar o utilizar un documento.
- NO debe existir aprobación automática basada únicamente en la salida del modelo.
- El sistema debe mostrar advertencias cuando falten datos, fuentes o fundamentos verificables.
- Una respuesta técnicamente válida NO debe asumirse jurídicamente correcta.

**Rationale**: La IA asiste pero no reemplaza el criterio jurídico humano. La responsabilidad legal recae en personas, no en software.

### III. Trazabilidad y Auditoría

Cada generación debe registrar, como mínimo:

- Identificador del caso.
- Usuario solicitante.
- Fecha y hora.
- Datos de entrada relevantes (aplicando minimización).
- Documentos y chunks recuperados.
- Puntajes y orden de recuperación.
- Modelo de embeddings utilizado.
- Modelo generativo utilizado.
- Versión del prompt.
- Parámetros relevantes.
- Borrador generado.
- Validaciones ejecutadas.
- Versión corregida por el usuario.
- Estado final.
- Eventos de aprobación o rechazo.

Los registros de auditoría NO deben poder modificarse silenciosamente.

**Rationale**: Sin trazabilidad completa, no hay rendición de cuentas ni posibilidad de auditar decisiones asistidas por IA.

### IV. Fuentes y Prohibición de Invención

- Toda afirmación jurídica generada debe poder vincularse con datos del caso, antecedentes recuperados o normativa indexada.
- El modelo NO debe inventar leyes, decretos, expedientes, artículos, competencias, autoridades, partidas presupuestarias ni hechos.
- Cuando una fuente no esté disponible, el sistema debe indicarlo explícitamente.
- Las fuentes recuperadas deben conservar su identificador, jurisdicción, fecha y referencia oficial.
- Los documentos nacionales utilizados para el MVP son antecedentes de referencia y NO deben presentarse como normativa provincial aplicable.
- La normativa y los antecedentes jurisprudenciales o administrativos deben gestionarse como corpus lógicamente separados.

**Rationale**: La invención de fuentes jurídicas es un riesgo catastrófico que puede causar daño legal real a usuarios y al estado.

### V. Salida Estructurada y Validable

- El LLM NO debe devolver como resultado principal texto libre destinado directamente a PDF.
- Debe devolver JSON conforme a schemas versionados.
- Los schemas deben validarse mediante tipos estrictos antes de almacenar o mostrar el resultado.
- Las secciones jurídicas obligatorias deben representarse explícitamente, incluyendo cuando corresponda: título, VISTO, CONSIDERANDOS, autoridad, parte dispositiva, artículos, fuentes y advertencias.
- La generación del contenido jurídico debe permanecer separada del renderizado a HTML, DOCX o PDF.
- Un error de schema debe producir una regeneración controlada o una respuesta explícita de error, nunca una aceptación silenciosa.

**Rationale**: La salida estructurada permite validación automática, trazabilidad y separación de responsabilidades entre generación y presentación.

### VI. Corpus Controlado y Calidad de Datos

- El primer corpus debe limitarse a un único subtipo documental: designación transitoria de personal.
- NO deben mezclarse inicialmente designaciones, licencias, renuncias, contrataciones, ascensos u otros actos.
- Los documentos deben conservar texto original, fuente, metadatos y versión procesada.
- La limpieza NO debe modificar el significado jurídico.
- Todo documento debe poder rastrearse hasta su fuente original.
- Los documentos duplicados, incompletos o mal clasificados deben detectarse y marcarse.
- Los primeros documentos del corpus deben recibir revisión manual.
- Los datos derivados automáticamente deben distinguirse de los datos revisados por una persona.

**Rationale**: Un corpus desordenado produce recuperación deficiente y generación poco confiable. La calidad del input determina la calidad del output.

### VII. Chunking Jurídico

- Los documentos deben dividirse prioritariamente por unidades semánticas y jurídicas, NO por una cantidad arbitraria de caracteres.
- Deben reconocerse estructuras como VISTO, CONSIDERANDO, "Por ello", artículos, anexos, firma y autoridad.
- NO debe cortarse un artículo o fundamento en la mitad salvo que una limitación técnica documentada lo requiera.
- Debe conservarse el orden, documento de origen, tipo de sección y posición de cada chunk.
- Además de chunks por sección, puede almacenarse una representación del documento completo para recuperar antecedentes integrales.

**Rationale**: El chunking jurídico preserva la integridad semántica necesaria para recuperar contexto relevante y coherente.

### VIII. RAG Antes que Fine-Tuning

- El MVP debe implementarse con embeddings, recuperación y prompting estructurado.
- NO debe incorporarse fine-tuning hasta demostrar mediante evaluación que RAG y prompting son insuficientes.
- MCP no forma parte del MVP inicial.
- Un agente autónomo no forma parte del MVP inicial.
- La selección del modelo debe basarse en pruebas reproducibles de calidad, cumplimiento del schema, latencia y consumo de recursos.
- Los nombres y dimensiones de modelos NO deben codificarse rígidamente en múltiples componentes; deben configurarse y registrarse.

**Rationale**: RAG es más seguro, auditable y mantenible que fine-tuning para el dominio jurídico donde la precisión de fuentes es crítica.

### IX. Evaluación Obligatoria

La calidad del sistema debe medirse con un conjunto de evaluación versionado.

La recuperación debe evaluarse mediante métricas como:

- Precision@K.
- Recall@K.
- Mean Reciprocal Rank.
- Calificación humana de utilidad jurídica.

La generación debe evaluar:

- Validez del JSON.
- Presencia de secciones obligatorias.
- Fidelidad a las fuentes.
- Normativa inventada.
- Trazabilidad.
- Tiempo de respuesta.
- Cantidad y tipo de correcciones humanas.
- Utilidad percibida por Legal y Técnica.

NO debe afirmarse que un modelo o estrategia funciona mejor sin resultados medidos sobre el mismo conjunto de evaluación.

**Rationale**: Sin métricas objetivas, las decisiones técnicas se basan en opiniones, no en evidencia.

### X. Arquitectura Modular

El sistema debe separar claramente:

- API.
- Dominio jurídico.
- Ingesta.
- Parsing.
- Chunking.
- Embeddings.
- Recuperación.
- Generación.
- Validación.
- Persistencia.
- Auditoría.
- Integración con Ollama.
- Interfaz.
- Infraestructura.

La lógica de dominio NO debe depender directamente de FastAPI, PostgreSQL, Redis, Ollama o Kubernetes.

Las integraciones externas deben estar detrás de interfaces o adaptadores reemplazables.

Debe evitarse una abstracción prematura, pero también deben evitarse módulos monolíticos con responsabilidades mezcladas.

**Rationale**: La modularidad permite testing, reemplazo de componentes y evolución independiente sin efectos colaterales.

### XI. Stack Base

Las decisiones técnicas iniciales son:

- Python 3.12 para API, workers y pipeline de IA.
- FastAPI para la API HTTP.
- Pydantic para schemas y validación.
- PostgreSQL con pgvector para datos relacionales y vectores.
- Alembic para migraciones.
- Redis para colas o coordinación asíncrona cuando sea necesario.
- Frontend React o Next.js (elección definitiva en plan técnico).
- Docker Compose para desarrollo local.
- Contenedores OCI versionados para despliegue.
- Kubernetes para el entorno del servidor.
- Terraform para declarar recursos propios del proyecto.
- Helm para empaquetar y desplegar workloads Kubernetes.
- Ollama como servicio externo configurable mediante `OLLAMA_BASE_URL`.

Una desviación del stack debe documentarse mediante una decisión arquitectónica (ADR) y explicar su beneficio.

**Rationale**: Stack definido reduce la fricción de decisión y asegura compatibilidad entre componentes.

### XII. Desarrollo Local Reproducible

- Un desarrollador debe poder levantar las dependencias locales mediante Docker Compose.
- PostgreSQL, pgvector, Redis, API y workers deben poder ejecutarse localmente.
- Ollama puede ser local o remoto según configuración.
- Debe existir un archivo `.env.example` sin secretos.
- El proyecto debe ofrecer comandos claros para instalar, iniciar, probar, migrar, ingerir y evaluar.
- NO deben requerirse cambios manuales no documentados para ejecutar el proyecto.
- Los datos de ejemplo NO deben contener información personal real.

**Rationale**: La reproducibilidad elimina "works on my machine" y acelera la incorporación de nuevos desarrolladores.

### XIII. Despliegue Aislado

- En Kubernetes, el proyecto debe utilizar namespace propio.
- Debe poseer ServiceAccounts, RBAC, ConfigMaps, secretos, almacenamiento y políticas propios.
- PostgreSQL y Redis NO deben exponerse públicamente.
- Ollama debe consumirse exclusivamente mediante su endpoint autorizado.
- Terraform NO debe administrar Ollama, GPU, drivers NVIDIA, nodos, clúster ni recursos de otros proyectos.
- Deben definirse requests y limits.
- Los procesos de ingesta y embeddings deben poder limitar su concurrencia para no saturar el Ollama compartido.
- Las solicitudes interactivas de generación deben tener prioridad operativa sobre ingestas masivas.

**Rationale**: El aislamiento previene interferencias con otros proyectos y protege recursos compartidos.

### XIV. Infrastructure as Code y SDD

- La infraestructura debe definirse mediante Terraform y Helm.
- Los cambios manuales en producción deben evitarse y, cuando sean inevitables, documentarse y reconciliarse con el código.
- El estado Terraform debe ser independiente por entorno.
- Los recursos persistentes deben protegerse contra destrucción accidental.
- Los planes Terraform deben revisarse antes de aplicar.
- El código generado por agentes de IA debe someterse a `terraform fmt`, validate, linting, análisis de seguridad y revisión humana.
- **IaC Spec Kit** debe utilizarse para especificar infraestructura, NO para definir comportamiento funcional del RAG.
- **GitHub Spec Kit** debe utilizarse para las capacidades funcionales y técnicas de la aplicación.
- Las especificaciones son documentos vivos y deben actualizarse cuando cambien requisitos o decisiones.

**Rationale**: IaC asegura consistencia entre entornos y permite auditoría de cambios de infraestructura.

### XV. Calidad de Código

- Usar tipado estricto en todo el código Python.
- Mantener funciones y módulos con responsabilidades claras.
- Evitar duplicación significativa.
- No capturar excepciones de forma genérica sin registrar y traducir correctamente el error.
- No utilizar valores mágicos cuando corresponda configuración.
- Aplicar linting y formateo automático.
- Mantener documentación de APIs y decisiones relevantes.
- El código debe priorizar legibilidad y mantenibilidad sobre soluciones innecesariamente sofisticadas.
- Los comentarios deben explicar decisiones, no repetir literalmente el código.

**Rationale**: Código limpio reduce defectos, facilita mantenimiento y mejora la experiencia de desarrollo.

### XVI. Pruebas

Toda capacidad debe incluir pruebas proporcionales al riesgo:

- Pruebas unitarias para parsing, normalización, schemas y reglas de dominio.
- Pruebas de integración para PostgreSQL, pgvector, Redis y Ollama mediante adaptadores.
- Pruebas contractuales para schemas JSON y APIs.
- Pruebas de migraciones.
- Pruebas de recuperación sobre dataset controlado.
- Pruebas de seguridad para entradas inválidas y límites.
- Smoke tests para Docker Compose y Kubernetes.

Las pruebas NO deben depender indiscriminadamente del Ollama compartido. Deben existir mocks, fakes o fixtures para la mayoría de los tests, reservando pruebas reales del modelo para integración y evaluación.

**Rationale**: Pruebas proporcionales al riesgo maximizan cobertura útil sin sobrecarga innecesaria.

### XVII. Observabilidad y Resiliencia

- Todos los servicios deben exponer health checks y readiness checks.
- Deben diferenciarse fallos de aplicación, base de datos, Redis y Ollama.
- Las llamadas a Ollama deben tener timeout, reintentos limitados y circuit breaker o mecanismo equivalente cuando sea necesario.
- La aplicación debe conservar información suficiente para diagnosticar errores sin registrar datos sensibles.
- Deben medirse latencia, errores, tamaño del contexto, uso por modelo y duración de los trabajos.
- Un fallo del modelo NO debe corromper datos ni producir un documento aprobado.
- Los jobs deben ser idempotentes cuando resulte posible.

**Rationale**: Observabilidad permite detectar, diagnosticar y resolver problemas antes de que afecten usuarios.

### XVIII. Control de Cambios y Versionado

Deben versionarse explícitamente:

- Schemas JSON.
- Prompts.
- Modelos utilizados.
- Configuración de embeddings.
- Estrategias de chunking.
- Migraciones de base de datos.
- Imágenes de contenedor.
- Especificaciones.
- Conjuntos de evaluación.

Cada borrador debe poder reproducirse razonablemente conociendo las versiones registradas.

**Rationale**: El versionado explícito permite reproducibilidad, rollback y auditoría de cambios que afectan la calidad del sistema.

### XIX. Desarrollo Incremental

La implementación debe avanzar por incrementos pequeños y verificables.

Orden inicial obligatorio:

1. Base del repositorio y entorno local.
2. Health checks y conexión a PostgreSQL, Redis y Ollama.
3. Modelo de datos y migraciones.
4. Corpus inicial curado.
5. Parsing y chunking jurídico.
6. Embeddings e indexación.
7. Recuperación y evaluación.
8. Generación estructurada.
9. Revisión humana e interfaz.
10. Despliegue Kubernetes.
11. Seguridad, backups y observabilidad operativa.

NO deben implementarse varias fases mayores simultáneamente sin haber validado la anterior.

**Rationale**: El desarrollo incremental reduce riesgo, permite feedback temprano y evita acumulación de deuda técnica.

### XX. Criterio de Simplicidad

- Implementar la solución más simple que satisfaga los requisitos medidos.
- No introducir microservicios adicionales, bases vectoriales separadas, orquestadores complejos, agentes autónomos o fine-tuning sin una necesidad demostrada.
- PostgreSQL con pgvector será la fuente principal de persistencia del MVP.
- Redis solo debe utilizarse cuando exista una necesidad concreta de cola, coordinación o caché.
- Las optimizaciones prematuras deben evitarse.
- Toda complejidad nueva debe justificar qué riesgo o métrica mejora.

**Rationale**: La simplicidad reduce costos, facilita mantenimiento y minimiza superficie de ataque.

## Stack Tecnológico

| Componente | Tecnología | Justificación |
|---|---|---|
| Lenguaje | Python 3.12 | Ecosistema ML/AI, tipado, FastAPI |
| API | FastAPI | Async, OpenAPI, validación automática |
| Schemas | Pydantic | Validación estricta, serialización |
| Base de datos | PostgreSQL + pgvector | Relacional + vectores en un solo sistema |
| Migraciones | Alembic | Control de esquema versionado |
| Colas | Redis | Coordinación asíncrona, caché |
| Frontend | React/Next.js | A definir en plan técnico |
| Dev local | Docker Compose | Reproducibilidad |
| Despliegue | Kubernetes + Helm | Orquestación, escalabilidad |
| IaC | Terraform | Declarativo, auditable |
| Inferencia | Ollama (externo) | Endpoint privado, sin envío de datos |

## Governance

Esta constitución prevalece sobre decisiones ad hoc, prompts de implementación y código generado.

Toda especificación y plan debe verificar explícitamente su cumplimiento con cada principio.

Una excepción a cualquier principio debe documentarse con:

- Contexto de la excepción.
- Alternativas consideradas.
- Riesgos asociados.
- Responsable de la excepción.
- Fecha de revisión programada.

Los cambios a la constitución deben quedar registrados en Git con mensaje descriptivo.

Los cambios incompatibles o que reduzcan garantías de seguridad, auditoría o revisión humana requieren revisión explícita antes de merge.

El proyecto debe mantener un historial de decisiones arquitectónicas mediante ADR (Architecture Decision Records) cuando una decisión tenga impacto transversal.

### Versioning Policy

- **MAJOR**: Remoción o redefinición de principios existentes.
- **MINOR**: Adición de nuevos principios o expansión material de guidance.
- **PATCH**: Aclaraciones, correcciones de redacción, refinamientos no semánticos.

### Compliance Review

- Todas las pull requests deben verificar cumplimiento con esta constitución.
- Los code reviews deben incluir verificación explícita de principios relevantes.
- El checklist de review debe referenciar los principios aplicables al cambio.

### Amendment Process

1. Proponer cambio via PR con descripción del rationale.
2. Documentar impacto en principios existentes.
3. Actualizar versión según reglas de semver.
4. Registrar fecha de modificación.
5. Obtener aprobación de al menos un revisor.

**Version**: 1.0.0 | **Ratified**: 2026-07-31 | **Last Amended**: 2026-07-31
