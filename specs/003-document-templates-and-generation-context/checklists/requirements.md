# Checklist de Requisitos — 003-document-templates-and-generation-context

## Requisitos Funcionales

| ID | Requisito | Estado | Observaciones |
|----|-----------|--------|---------------|
| RF-01.1 | Crear plantilla (con versionado) | ☐ Pendiente | |
| RF-01.2 | Consultar plantilla por ID | ☐ Pendiente | |
| RF-01.3 | Listar plantillas activas | ☐ Pendiente | |
| RF-01.4 | Actualizar plantilla (nueva versión si cambia contenido) | ☐ Pendiente | |
| RF-01.5 | Desactivar plantilla | ☐ Pendiente | |
| RF-01.6 | Obtener versión activa de plantilla | ☐ Pendiente | |
| RF-02.1 | Construir contexto completo (con designation_data) | ☐ Pendiente | |
| RF-02.2 | Validar variables (sintaxis Jinja2) | ☐ Pendiente | |
| RF-03.1 | Generar borrador (flujo Ollama separado) | ☐ Pendiente | |
| RF-03.2 | Construir prompt para Ollama (Jinja2 namespaces) | ☐ Pendiente | |
| RF-03.3 | Consultar intento de generación | ☐ Pendiente | |
| RF-04.1 | Avanzar estado del borrador (sin PUBLISH) | ☐ Pendiente | |
| RF-04.2 | Historial de transiciones | ☐ Pendiente | |
| RF-05.1 | Regenerar borrador (superseded tras éxito) | ☐ Pendiente | |
| RF-06.1 | Editar contenido del borrador (optimistic locking) | ☐ Pendiente | |
| RF-07.1 | Consultar borrador por ID | ☐ Pendiente | |
| RF-07.2 | Listar borradores de expediente | ☐ Pendiente | |
| RF-08.1 | Registro de transiciones | ☐ Pendiente | |
| RF-08.2 | Snapshot de contexto inmutable (con context_hash) | ☐ Pendiente | |
| RF-08.3 | Cadena de versiones (parent_draft_id) | ☐ Pendiente | |

## Requisitos No Funcionales

| ID | Requisito | Estado | Observaciones |
|----|-----------|--------|---------------|
| RNF-01 | Rendimiento (≤200ms consultas, ≤30s generación) | ☐ Pendiente | |
| RNF-02 | Persistencia (5 tablas, JSONB, índices) | ☐ Pendiente | |
| RNF-03 | Seguridad (sin secretos, variables sanitizadas) | ☐ Pendiente | |
| RNF-04 | Observabilidad (logs, request ID, health check) | ☐ Pendiente | |
| RNF-05 | Testing (cobertura >= 85%) | ☐ Pendiente | |
| RNF-06 | Backward compatibility (sin cambios en 002) | ☐ Pendiente | |

## Endpoints

| Método | Ruta | Estado | Observaciones |
|--------|------|--------|---------------|
| POST | `/api/v1/templates` | ☐ Pendiente | |
| GET | `/api/v1/templates` | ☐ Pendiente | |
| GET | `/api/v1/templates/{template_id}` | ☐ Pendiente | |
| PATCH | `/api/v1/templates/{template_id}` | ☐ Pendiente | |
| POST | `/api/v1/templates/{template_id}/deactivate` | ☐ Pendiente | |
| POST | `/api/v1/case-files/{case_file_id}/designation` | ☐ Pendiente | |
| GET | `/api/v1/case-files/{case_file_id}/designation` | ☐ Pendiente | |
| PUT | `/api/v1/case-files/{case_file_id}/designation` | ☐ Pendiente | |
| POST | `/api/v1/drafts/generate` | ☐ Pendiente | Idempotency-Key header |
| GET | `/api/v1/case-files/{case_file_id}/drafts` | ☐ Pendiente | |
| GET | `/api/v1/drafts/{draft_id}` | ☐ Pendiente | |
| PATCH | `/api/v1/drafts/{draft_id}/content` | ☐ Pendiente | expected_version |
| POST | `/api/v1/drafts/{draft_id}/transitions` | ☐ Pendiente | expected_version |
| POST | `/api/v1/drafts/{draft_id}/regenerate` | ☐ Pendiente | expected_version |
| GET | `/api/v1/drafts/{draft_id}/history` | ☐ Pendiente | |
| GET | `/api/v1/generation-attempts/{attempt_id}` | ☐ Pendiente | |
| GET | `/api/v1/case-files/{case_file_id}/generation-attempts` | ☐ Pendiente | |

## Modelos de Dominio

| Modelo | Estado | Observaciones |
|--------|--------|---------------|
| Template (con version) | ☐ Pendiente | |
| TemplateVariable | ☐ Pendiente | |
| Draft (con version, generation_number) | ☐ Pendiente | |
| DraftTransition | ☐ Pendiente | |
| GenerationAttempt | ☐ Pendiente | |
| DesignationData | ☐ Pendiente | |
| DocumentType (enum) | ☐ Pendiente | Reutilizar enum existente |
| DraftStatus (enum: GENERADO, EN_REVISION, APROBADO, RECHAZADO, SUPERSEDED) | ☐ Pendiente | |
| TransitionAction (enum: SEND_TO_REVIEW, APPROVE, REJECT, EDIT_CONTENT) | ☐ Pendiente | |
| GenerationStatus (enum: IN_PROGRESS, COMPLETED, FAILED) | ☐ Pendiente | |

## Schemas (Request/Response)

| Schema | Estado | Observaciones |
|--------|--------|---------------|
| CreateTemplateRequest | ☐ Pendiente | |
| TemplateVariableSchema | ☐ Pendiente | |
| TemplateResponse (con version) | ☐ Pendiente | |
| GenerateDraftRequest | ☐ Pendiente | |
| DraftResponse (con version, generation_number, context_hash) | ☐ Pendiente | |
| TransitionDraftRequest (con expected_version) | ☐ Pendiente | |
| RegenerateDraftRequest (con expected_version) | ☐ Pendiente | |
| EditDraftContentRequest (con expected_version) | ☐ Pendiente | |
| DraftTransitionResponse | ☐ Pendiente | |
| GenerationAttemptResponse | ☐ Pendiente | |
| CreateDesignationDataRequest | ☐ Pendiente | |
| DesignationDataResponse | ☐ Pendiente | |

## Repositories

| Repository | Estado | Observaciones |
|------------|--------|---------------|
| TemplateRepository | ☐ Pendiente | |
| DraftRepository | ☐ Pendiente | |
| GenerationAttemptRepository | ☐ Pendiente | |
| DesignationRepository | ☐ Pendiente | |
| UnitOfWork (extensión) | ☐ Pendiente | |

## Migraciones

| Migración | Estado | Observaciones |
|-----------|--------|---------------|
| 003_templates_drafts_and_generation.py | ☐ Pendiente | 5 tablas nuevas |

## Errores Estructurados

| Código | HTTP | Estado | Observaciones |
|--------|------|--------|---------------|
| DOCUMENT_TEMPLATE_NOT_FOUND | 404 | ☐ Pendiente | |
| DOCUMENT_TEMPLATE_NAME_EXISTS | 409 | ☐ Pendiente | |
| DOCUMENT_TEMPLATE_INACTIVE | 409 | ☐ Pendiente | |
| DOCUMENT_TEMPLATE_CONFLICT | 409 | ☐ Pendiente | |
| CASE_FILE_NOT_FOUND | 404 | ☐ Pendiente | Reutilizar de 002 |
| DESIGNATION_DATA_NOT_FOUND | 404 | ☐ Pendiente | |
| DESIGNATION_DATA_INCOMPLETE | 422 | ☐ Pendiente | |
| CASE_FILE_TYPE_INCOMPATIBLE | 409 | ☐ Pendiente | |
| DRAFT_NOT_FOUND | 404 | ☐ Pendiente | |
| INVALID_DRAFT_TRANSITION | 409 | ☐ Pendiente | |
| DRAFT_ALREADY_APPROVED | 409 | ☐ Pendiente | |
| GENERATION_IN_PROGRESS | 409 | ☐ Pendiente | |
| GENERATION_FAILED | 502 | ☐ Pendiente | |
| OLLAMA_UNAVAILABLE | 503 | ☐ Pendiente | |
| OLLAMA_TIMEOUT | 504 | ☐ Pendiente | |
| CONCURRENT_MODIFICATION | 409 | ☐ Pendiente | |
| VALIDATION_ERROR | 422 | ☐ Pendiente | |
| DATABASE_ERROR | 500 | ☐ Pendiente | |
| MISSING_REQUIRED_VARIABLES | 422 | ☐ Pendiente | |
| CONTENT_TOO_LARGE | 422 | ☐ Pendiente | |
| CONTEXT_BUILD_FAILED | 500 | ☐ Pendiente | |
| IDEMPOTENCY_KEY_MISMATCH | 409 | ☐ Pendiente | |

## Tests

| Tipo | Cantidad Mínima | Estado | Observaciones |
|------|-----------------|--------|---------------|
| Unitarios | 35+ | ☐ Pendiente | |
| Integración | 20+ | ☐ Pendiente | |
| Transiciones | 10+ | ☐ Pendiente | |
| Frontera | 8+ | ☐ Pendiente | |
| **Total** | **73+** | ☐ Pendiente | |

## Validación Final

| Verificación | Estado | Observaciones |
|--------------|--------|---------------|
| Ruff check OK | ☐ Pendiente | |
| Ruff format OK | ☐ Pendiente | |
| Mypy OK | ☐ Pendiente | |
| Cobertura >= 85% | ☐ Pendiente | |
| Docker build OK | ☐ Pendiente | |
| Docker up OK | ☐ Pendiente | |
| Smoke tests OK | ☐ Pendiente | |
| Backward compatible | ☐ Pendiente | |
