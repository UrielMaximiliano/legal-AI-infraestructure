# Checklist de calidad: Ingesta de Corpus y Recuperación Semántica

**Propósito**: Validar integridad y calidad antes de la planificación
**Creada**: 2026-08-04
**Feature**: [spec.md](../spec.md)

## Calidad del contenido

- [x] No incluye decisiones de implementación ajenas a las restricciones explícitas
- [x] Está enfocada en valor para usuarios y necesidades institucionales
- [x] Está escrita para partes interesadas no técnicas
- [x] Todas las secciones obligatorias están completas

## Integridad de requisitos

- [x] No quedan marcadores `[NEEDS CLARIFICATION]`
- [x] Los requisitos son verificables y no ambiguos
- [x] Los criterios de éxito son medibles
- [x] Los criterios de éxito describen resultados verificables
- [x] Los escenarios de aceptación están definidos
- [x] Los casos límite están identificados
- [x] El alcance está claramente delimitado
- [x] Las dependencias y los supuestos están identificados
- [x] El original protegido, la versión procesada, procedencia y revisión humana están definidos
- [x] Precision@K y utilidad jurídica humana forman parte de G3 sin umbral inventado
- [x] El coordinador de inferencia define exclusión mutua, prioridad, fairness y cancelación
- [x] La integración ORM usa la dependencia Python oficial pgvector de forma reproducible
- [x] El cierre exige escaneo de vulnerabilidades críticas/altas o excepción aprobada
- [x] La auditoría de búsqueda tiene una política fail-closed verificable
- [x] El dry-run de reindexación garantiza cero efectos persistentes y cero Ollama
- [x] G1-A fija 1024 y G1-B bloquea solo aceptación operativa externa
- [x] CorpusReviewService separa dominio de revisión e integración CLI
- [x] raw_content tiene acceso mínimo, mappers explícitos y pruebas contra fugas
- [x] FakeEmbeddingProvider e InferenceCoordinator tienen suites separadas
- [x] InferenceCoordinationPort e InferenceCoordinator tienen nombres no ambiguos
- [x] corpus_documents persiste review_version positivo con default 1
- [x] El CLI exige expected_version positivo en toda revisión
- [x] El repositorio define compare-and-swap atómico por id, versión y estado
- [x] El mismatch de versión usa un código estable y details allowlist
- [x] Dos revisores concurrentes producen un ganador, una auditoría y sin lost update
- [x] Las pruebas de revisión están separadas de las pruebas de ingesta

## Preparación de la feature

- [x] Los requisitos funcionales tienen resultados observables
- [x] Los escenarios cubren los flujos principales
- [x] La feature define resultados medibles
- [x] No se filtran detalles de código o estructura interna no requeridos

## Notas

- Validación inicial ejecutada el 2026-08-04, iteración 1.
- Aclaraciones consolidadas mediante `$speckit-clarify` el 2026-08-04;
  validación final ejecutada en iteración 3.
- Los 34 controles están aprobados y los artefactos quedan en
  `READY_FOR_REANALYSIS`.
