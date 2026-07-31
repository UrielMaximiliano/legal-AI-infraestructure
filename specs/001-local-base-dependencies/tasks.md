# Tareas: Base Local y Verificación de Dependencias

**Entrada**: Plan técnico de `/specs/001-local-base-dependencies/plan.md`
**Prerrequisitos**: plan.md, spec.md, research.md, data-model.md, contracts/

**Organización**: Tareas agrupadas por fase de implementación siguiendo la
jerarquía de dependencias (Setup → Config → Dominio → Adaptadores →
Application → HTTP → Observability → Migraciones → Docker → Pruebas → Polish)

## Formato: `[ID] [P?] Descripción`

- **[ID]**: Número secuencial de tarea (T001, T002, T003...)
- **[P]**: Puede ejecutarse en paralelo (archivos distintos, sin dependencias)
- **[Descripción]**: Acción clara con ruta exacta del archivo

---

## Fase 1: Setup del Proyecto

**Propósito**: Estructura base, dependencias y configuración de herramientas

- [x] T001 Crear `apps/api/pyproject.toml` con dependencias del proyecto y scripts
- [x] T002 Ejecutar `uv sync` para generar `uv.lock` y verificar resolución
- [x] T003 Crear `apps/api/.python-version` con `3.12`
- [x] T004 Crear `apps/api/ruff.toml` con configuración de linting y formato
- [x] T005 Crear `apps/api/mypy.ini` con configuración de tipado estático
- [x] T006 Crear `apps/api/pytest.ini` con configuración de pruebas
- [x] T007 Crear `.editorconfig` en la raíz del repositorio

**Checkpoint**: Proyecto inicializado, `uv sync` exitoso

---

## Fase 2: Configuración Tipada

**Propósito**: Configuración de la aplicación con pydantic-settings

- [x] T008 Crear `apps/api/src/legal_ai/__init__.py` con versión del paquete
- [x] T009 Crear `apps/api/src/legal_ai/config.py` con `AppConfig`, `PostgreSQLConfig`, `OllamaConfig` (incluyendo `OLLAMA_API_TOKEN` como obligatorio sin default)
- [x] T010 Crear `.env.example` en la raíz con todas las variables documentadas (incluir `OLLAMA_API_TOKEN=<PLACEHOLDER>`, `OLLAMA_BASE_URL` sin valor por defecto)
- [x] T011 Crear `apps/api/src/legal_ai/config/__init__.py` (si se usa paquete de configuración)

**Checkpoint**: Configuración validada, `.env.example` documentado

---

## Fase 3: Dominio y Modelos

**Propósito**: Modelos de dominio y schemas Pydantic para health checks

- [x] T012 [P] Crear `apps/api/src/legal_ai/domain/__init__.py`
- [x] T013 [P] Crear `apps/api/src/legal_ai/domain/health.py` con `DependencyHealth`, `HealthStatus`, `HealthResponse`
- [x] T014 [P] Crear `apps/api/src/legal_ai/schemas/__init__.py`
- [x] T015 [P] Crear `apps/api/src/legal_ai/schemas/health.py` con schemas Pydantic para los 3 endpoints
- [x] T016 [P] Crear `apps/api/src/legal_ai/schemas/errors.py` con schema de error estructurado

**Checkpoint**: Modelos de dominio y schemas definidos

---

## Fase 4: Puertos (Interfaces)

**Propósito**: Interfaces abstractas para adaptadores de dependencias

- [x] T017 [P] Crear `apps/api/src/legal_ai/ports/__init__.py`
- [x] T018 [P] Crear `apps/api/src/legal_ai/ports/database_health.py` con `DatabaseHealthPort`
- [x] T019 [P] Crear `apps/api/src/legal_ai/ports/ollama_health.py` con `OllamaHealthPort`

**Checkpoint**: Interfaces definidas, separación de concerns clara

---

## Fase 5: Adaptadores

**Propósito**: Implementaciones concretas de verificación de dependencias

- [x] T020 Crear `apps/api/src/legal_ai/adapters/__init__.py`
- [x] T021 Crear `apps/api/src/legal_ai/adapters/database/__init__.py`
- [x] T022 Crear `apps/api/src/legal_ai/adapters/database/engine.py` con SQLAlchemy async engine
- [x] T023 Crear `apps/api/src/legal_ai/adapters/database/health.py` con `PostgreSQLHealthAdapter`
- [x] T024 Crear `apps/api/src/legal_ai/adapters/ollama/__init__.py`
- [x] T025 Crear `apps/api/src/legal_ai/adapters/ollama/client.py` con HTTPX AsyncClient (headers `Authorization: Bearer`, `OLLAMA_API_TOKEN` desde config)
- [x] T026 Crear `apps/api/src/legal_ai/adapters/ollama/health.py` con `OllamaHealthAdapter` (health check: `GET /api/version`, Bearer auth, estados: ok, unavailable, timeout, misconfigured, invalid_response, unauthorized, forbidden, rate_limited)

**Checkpoint**: Adaptadores implementados, PostgreSQL y Ollama verificables

---

## Fase 6: Servicio de Aplicación

**Propósito**: Lógica de orquestación de health checks

- [x] T027 Crear `apps/api/src/legal_ai/application/__init__.py`
- [x] T028 Crear `apps/api/src/legal_ai/application/health_service.py` con `HealthService`

**Checkpoint**: Lógica de health checks separada de controladores HTTP

---

## Fase 7: Observabilidad

**Propósito**: Logging estructurado y middleware de request context

- [x] T029 [P] Crear `apps/api/src/legal_ai/observability/__init__.py`
- [x] T030 [P] Crear `apps/api/src/legal_ai/observability/logging.py` con configuración de logging estructurado
- [x] T031 [P] Crear `apps/api/src/legal_ai/observability/request_context.py` con middleware `request_id`

**Checkpoint**: Observabilidad mínima configurada

---

## Fase 8: Capa HTTP

**Propósito**: Controladores y router de FastAPI

- [x] T032 Crear `apps/api/src/legal_ai/api/__init__.py`
- [x] T033 Crear `apps/api/src/legal_ai/api/router.py` con router principal
- [x] T034 Crear `apps/api/src/legal_ai/api/routes/__init__.py`
- [x] T035 Crear `apps/api/src/legal_ai/api/routes/health.py` con controladores de los 3 endpoints
- [x] T036 Crear `apps/api/src/legal_ai/main.py` con FastAPI app y lifespan

**Checkpoint**: API funcional con los 3 endpoints de health check

---

## Fase 9: Migraciones

**Propósito**: Alembic configurado con primera migración

- [x] T037 Crear `apps/api/alembic.ini` con configuración de Alembic
- [x] T038 Crear `apps/api/alembic/env.py` con soporte async
- [x] T039 Crear `apps/api/alembic/script.py.mako` con template de migración
- [x] T040 Crear `apps/api/alembic/versions/001_enable_pgvector.py` con `CREATE EXTENSION IF NOT EXISTS vector`

**Checkpoint**: Migraciones versionadas, primera migración lista

---

## Fase 10: Docker

**Propósito**: Contenedores y orquestación local

- [x] T041 Crear `apps/api/Dockerfile` multi-stage (builder + runtime)
- [x] T042 Crear `compose.yaml` en la raíz con servicios `api` y `postgres`
- [x] T043 Crear `.gitignore` en la raíz
- [x] T044 Crear `.dockerignore` en la raíz
- [x] T045 Crear `scripts/dev.ps1` wrapper PowerShell (opcional)
- [x] T046 Crear `scripts/dev.sh` wrapper bash (opcional)

**Checkpoint**: `docker compose up -d` funcional

---

## Fase 11: Pruebas Unitarias

**Propósito**: Pruebas de componentes aislados con mocks/fakes

- [x] T047 Crear `apps/api/tests/__init__.py`
- [x] T048 Crear `apps/api/tests/conftest.py` con fixtures compartidos
- [x] T049 Crear `apps/api/tests/unit/__init__.py`
- [x] T050 Crear `apps/api/tests/unit/test_config.py` con validación de configuración
- [x] T051 Crear `apps/api/tests/unit/test_health_service.py` con pruebas del servicio con fakes
- [x] T052 Crear `apps/api/tests/unit/test_schemas.py` con validación de schemas Pydantic
- [x] T053 Crear `apps/api/tests/unit/test_request_context.py` con pruebas de middleware

**Checkpoint**: Pruebas unitarias pasan sin dependencias externas

---

## Fase 12: Pruebas Contractuales

**Propósito**: Validación de contratos HTTP de los 3 endpoints

- [x] T054 Crear `apps/api/tests/contract/__init__.py`
- [x] T055 Crear `apps/api/tests/contract/test_health_live.py` con contrato de `/health/live`
- [x] T056 Crear `apps/api/tests/contract/test_health_ready.py` con contrato de `/health/ready`
- [x] T057 Crear `apps/api/tests/contract/test_health_dependencies.py` con contrato de `/health/dependencies` (estados agregados: ok, partial, error; estados individuales con auth: unauthorized, forbidden, rate_limited)

**Checkpoint**: Contratos HTTP validados

---

## Fase 13: Pruebas de Integración

**Propósito**: Pruebas con PostgreSQL real y migraciones

- [x] T058 Crear `apps/api/tests/integration/__init__.py`
- [x] T059 Crear `apps/api/tests/integration/test_postgres.py` con conexión real
- [x] T060 Crear `apps/api/tests/integration/test_migrations.py` con verificación de migración

**Checkpoint**: Pruebas de integración pasan con `docker compose up -d postgres`

---

## Fase 14: Pruebas del Adaptador Ollama

**Propósito**: Pruebas del adaptador con mocks para todos los escenarios
incluyendo autenticación Bearer y códigos HTTP específicos

- [x] T061 Crear `apps/api/tests/unit/test_ollama_adapter.py` con mocks para:
  - Respuesta exitosa (GET /api/version, JSON con version string no vacío)
  - Timeout
  - Conexión rechazada
  - HTTP 401 (unauthorized)
  - HTTP 403 (forbidden)
  - HTTP 404 (endpoint not found)
  - HTTP 429 (rate limited)
  - HTTP 502 (bad gateway / unavailable)
  - HTTP 504 (gateway timeout / unavailable)
  - JSON inválido
  - Estructura inesperada (sin campo version)
  - URL inválida (misconfigured)
  - Cancelación
  - Verificar que Authorization Bearer se envía correctamente
  - Verificar que OLLAMA_API_TOKEN no se expone en errores

**Checkpoint**: Adaptador Ollama probado con todos los escenarios

---

## Fase 15: Validación y Polish

**Propósito**: Verificación final, documentación y calidad

- [x] T062 Ejecutar `uv run ruff check .` y corregir issues
- [x] T063 Ejecutar `uv run ruff format --check .` y corregir formato
- [x] T064 Ejecutar `uv run mypy src` y corregir errores de tipo
- [x] T065 Ejecutar `uv run pytest --cov=src/legal_ai --cov-report=term-missing` y verificar cobertura >= 85%
- [x] T066 Crear `README.md` en la raíz con documentación completa
- [x] T067 Verificar quickstart.md ejecutando los comandos documentados
- [x] T068 Ejecutar `docker compose down --volumes` y verificar limpieza

**Checkpoint**: Todos los checks pasan, documentación completa

---

## Dependencias y Orden de Ejecución

### Dependencias entre Fases

- **Fase 1 (Setup)**: Sin dependencias — iniciar inmediatamente
- **Fase 2 (Config)**: Depende de Fase 1
- **Fase 3 (Dominio)**: Depende de Fase 1
- **Fase 4 (Puertos)**: Depende de Fase 3
- **Fase 5 (Adaptadores)**: Depende de Fase 2, Fase 4
- **Fase 6 (Servicio)**: Depende de Fase 3, Fase 4, Fase 5
- **Fase 7 (Observabilidad)**: Depende de Fase 1 — puede ejecutarse en paralelo con Fases 3-6
- **Fase 8 (HTTP)**: Depende de Fase 6, Fase 7
- **Fase 9 (Migraciones)**: Depende de Fase 2
- **Fase 10 (Docker)**: Depende de Fase 1
- **Fase 11 (Pruebas Unitarias)**: Depende de Fase 6, Fase 7
- **Fase 12 (Pruebas Contractuales)**: Depende de Fase 8
- **Fase 13 (Pruebas Integración)**: Depende de Fase 9, Fase 10
- **Fase 14 (Pruebas Ollama)**: Depende de Fase 5
- **Fase 15 (Polish)**: Depende de todas las fases anteriores

### Reglas de Paralelismo

**Pueden ejecutarse en paralelo (archivos distintos, sin dependencias):**
- T012-T016 (modelos de dominio y schemas)
- T017-T019 (puertos)
- T029-T031 (observabilidad)
- T045-T046 (scripts opcionales)

**NO pueden ejecutarse en paralelo:**
- Tareas que modifican el mismo archivo
- Tareas con dependencias de salida (una tarea necesita el resultado de otra)
- Tareas dentro de la misma fase secuencial

### Puntos de Validación

| Fase | Checkpoint | Comando |
|---|---|---|
| 1 | Setup completo | `uv sync` |
| 2 | Config validada | `python -c "from legal_ai.config import AppConfig"` |
| 8 | API funcional | `uvicorn legal_ai.main:app` |
| 10 | Docker funcional | `docker compose up -d` |
| 11 | Pruebas unitarias | `uv run pytest tests/unit/` |
| 12 | Pruebas contractuales | `uv run pytest tests/contract/` |
| 13 | Pruebas integración | `docker compose run --rm api uv run pytest tests/integration/` |
| 15 | Validación completa | `uv run ruff check . && uv run mypy src && uv run pytest` |

---

## Notas

- [P] tareas = archivos distintos, sin dependencias dentro de la misma fase
- Tareas organizadas por fase de implementación siguiendo jerarquía de dependencias
- Ejecutar validación en puntos de checkpoint para detectar errores tempranos
- Commitear después de cada fase o grupo lógico de tareas
- Detenerse en checkpoints para validar antes de continuar
- Evitar: tareas vagas, conflictos de archivos, violar dependencias entre fases

## Alcance Excluido

Las siguientes capacidades están fuera del alcance de este incremento y NO
deben generar código ni tareas:

- Generación de contenido jurídico
- OCR (reconocimiento óptico de caracteres)
- Embeddings y búsqueda semántica
- RAG (Retrieval-Augmented Generation)
- Redis
- Frontend
- Kubernetes
- Terraform
- Helm
- CI/CD completo
- Autenticación de usuarios
- Fine-tuning
- MCP (Model Context Protocol)
- Agentes autónomos

La revisión humana obligatoria aplicará a capacidades jurídicas futuras.
