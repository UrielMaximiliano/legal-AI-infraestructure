# Plan Técnico: Base Local y Verificación de Dependencias

**Branch**: `001-local-base-dependencies` | **Fecha**: 2026-07-31 | **Spec**: [spec.md](./spec.md)
**Entrada**: Especificación de `/specs/001-local-base-dependencies/spec.md`

## Resumen

Primer incremento ejecutable del proyecto legal-AI-infraestructure. Establece
la base técnica local mediante Docker Compose con una API FastAPI que verifica
PostgreSQL con pgvector y un endpoint configurable de Ollama. Expone tres
endpoints de health check diferenciados, ejecuta migraciones versionadas con
Alembic y funciona de manera portable entre Windows y Linux.

## Contexto Técnico

**Proveedor Cloud**: Ninguno (on-premise)
**Herramienta IaC**: Docker Compose v2 (este incremento)
**Versión Python**: 3.12
**Framework HTTP**: FastAPI + Uvicorn
**Validación**: Pydantic v2 + pydantic-settings
**Base de datos**: PostgreSQL 16 con pgvector 0.8.0
**Driver**: SQLAlchemy 2.x + asyncpg
**Migraciones**: Alembic
**Cliente HTTP**: HTTPX AsyncClient
**Gestión de dependencias**: uv
**Linting/Formato**: Ruff
**Tipado estático**: mypy
**Pruebas**: pytest + pytest-asyncio + pytest-cov
**Contenedores**: Docker + Docker Compose v2
**Entornos**: Windows (desarrollo) → Linux (ejecución)

## Verificación de Principios

### Principio I — Seguridad y Privacidad por Diseño

- ✅ No se envían datos jurídicos a Ollama en este incremento
- ✅ No se almacenan secretos en Git
- ✅ No se exponen credenciales en logs o respuestas
- ✅ `OLLAMA_API_TOKEN` se gestiona como secret, no se incluye en imágenes
- ✅ Se aplica mínimo privilegio en contenedores (usuario no root)
- ✅ Las dependencias se fijan mediante versiones

### Principio V — Salida Estructurada y Validable

- ✅ Los endpoints devuelven JSON conforme a schemas versionados
- ✅ Los schemas se validan mediante Pydantic
- ✅ Los errores usan códigos estables

### Principio X — Arquitectura Modular

- ✅ Separación entre capa HTTP, aplicación, dominio, adaptadores
- ✅ Lógica de health checks separada de controladores
- ✅ Adaptadores reemplazables para PostgreSQL y Ollama

### Principio XII — Desarrollo Local Reproducible

- ✅ Docker Compose para levantar dependencias
- ✅ Archivo `.env.example` sin secretos
- ✅ Comandos documentados para instalar, iniciar, probar, migrar

### Principio XVI — Pruebas

- ✅ Pruebas unitarias con mocks/fakes
- ✅ Pruebas de integración con PostgreSQL real
- ✅ Pruebas contractuales de schemas
- ✅ La mayoría de pruebas no depende de Ollama real

### Principio XX — Criterio de Simplicidad

- ✅ Sin Redis, sin Celery, sin frontend
- ✅ Sin Kubernetes, Terraform ni Helm
- ✅ Sin RAG, embeddings ni generación
- ✅ PostgreSQL con pgvector como fuente principal

## Arquitectura del Incremento

### Separación de Capas

```
┌─────────────────────────────────────────────────────┐
│                    HTTP Layer                        │
│  FastAPI Router → Health Controllers                 │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│                Application Layer                     │
│  HealthService → Dependency Checks                   │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│                   Ports Layer                        │
│  DatabaseHealthPort, OllamaHealthPort                │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│                 Adapters Layer                        │
│  PostgreSQLHealthAdapter, OllamaHealthAdapter        │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│              Infrastructure Layer                    │
│  SQLAlchemy Engine, HTTPX Client, Alembic            │
└─────────────────────────────────────────────────────┘
```

### Endpoints

| Endpoint | Método | Responsabilidad | Código HTTP |
|---|---|---|---|
| `/health/live` | GET | Liveness (proceso activo) | 200 |
| `/health/ready` | GET | Readiness (dependencias) | 200/503 |
| `/health/dependencies` | GET | Diagnóstico individual | 200/500 |

### Flujo de Verificación

```
/health/ready o /health/dependencies
         │
         ├──► PostgreSQL (SELECT 1)
         │         │
         │         └──► pgvector (SELECT extname FROM pg_extension)
         │
         └──► Ollama (GET /api/version)  ←── en paralelo
```

PostgreSQL y pgvector se verifican secuencialmente (pgvector depende de
PostgreSQL). Ollama se verifica en paralelo con el flujo de base de datos.

## Estructura del Proyecto

```
apps/
└── api/
    ├── src/
    │   └── legal_ai/
    │       ├── __init__.py
    │       ├── main.py              # FastAPI app + lifespan
    │       ├── config.py            # pydantic-settings
    │       ├── api/
    │       │   ├── __init__.py
    │       │   ├── router.py        # Router principal
    │       │   └── routes/
    │       │       ├── __init__.py
    │       │       └── health.py    # Controladores de health
    │       ├── application/
    │       │   ├── __init__.py
    │       │   └── health_service.py # Lógica de verificación
    │       ├── domain/
    │       │   ├── __init__.py
    │       │   └── health.py        # Modelos de dominio
    │       ├── ports/
    │       │   ├── __init__.py
    │       │   ├── database_health.py # Interfaz PostgreSQL
    │       │   └── ollama_health.py   # Interfaz Ollama
    │       ├── adapters/
    │       │   ├── __init__.py
    │       │   ├── database/
    │       │   │   ├── __init__.py
    │       │   │   ├── engine.py    # SQLAlchemy engine
    │       │   │   └── health.py    # Adaptador PostgreSQL
    │       │   └── ollama/
    │       │       ├── __init__.py
    │       │       ├── client.py    # HTTPX client
    │       │       └── health.py    # Adaptador Ollama
    │       ├── observability/
    │       │   ├── __init__.py
    │       │   ├── logging.py       # Logging estructurado
    │       │   └── request_context.py # Middleware request_id
    │       └── schemas/
    │           ├── __init__.py
    │           └── health.py        # Schemas Pydantic
    ├── alembic/
    │   ├── env.py
    │   ├── script.py.mako
    │   └── versions/
    │       └── 001_enable_pgvector.py
    ├── tests/
    │   ├── __init__.py
    │   ├── conftest.py
    │   ├── unit/
    │   │   ├── __init__.py
    │   │   ├── test_config.py
    │   │   ├── test_health_service.py
    │   │   └── test_schemas.py
    │   ├── integration/
    │   │   ├── __init__.py
    │   │   ├── test_postgres.py
    │   │   └── test_migrations.py
    │   └── contract/
    │       ├── __init__.py
    │       └── test_health_endpoints.py
    ├── pyproject.toml
    ├── uv.lock
    ├── alembic.ini
    └── Dockerfile
```

En la raíz del repositorio:

```
├── compose.yaml
├── .env.example
├── .gitignore
├── .dockerignore
├── .editorconfig
├── README.md
└── scripts/
    ├── dev.ps1        # Wrapper PowerShell (opcional)
    └── dev.sh         # Wrapper bash (opcional)
```

## Stack Definitivo

| Componente | Tecnología | Versión |
|---|---|---|
| Lenguaje | Python | 3.12 |
| Framework HTTP | FastAPI | 0.115.x |
| Servidor ASGI | Uvicorn | 0.34.x |
| Validación | Pydantic | 2.x |
| Configuración | pydantic-settings | 2.x |
| ORM | SQLAlchemy | 2.x |
| Driver PostgreSQL | asyncpg | 0.30.x |
| Migraciones | Alembic | 1.14.x |
| Cliente HTTP | HTTPX | 0.28.x |
| Pruebas | pytest | 8.x |
| Async tests | pytest-asyncio | 0.25.x |
| Cobertura | pytest-cov | 6.x |
| Linting | Ruff | 0.9.x |
| Tipado | mypy | 1.14.x |
| Dependencias | uv | 0.5.x |
| Base de datos | PostgreSQL | 16 |
| pgvector | pgvector | 0.8.0 |
| Contenedor DB | pgvector/pgvector | 0.8.0-pg16 |
| Contenedor API | Python | 3.12-slim |
| Orquestación | Docker Compose | v2 |

## Estrategia de Configuración

### Variables de Entorno

Configuración tipada mediante `pydantic-settings`. Validación en tiempo
de arranque con errores claros.

```python
class AppConfig(BaseSettings):
    APP_ENV: str = "development"
    APP_NAME: str = "legal-ai-api"
    APP_VERSION: str = "0.1.0"
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    LOG_LEVEL: str = "INFO"

class PostgreSQLConfig(BaseSettings):
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "legal_ai"
    POSTGRES_USER: str = "legal_ai"
    POSTGRES_PASSWORD: str = "change-me"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

class OllamaConfig(BaseSettings):
    OLLAMA_BASE_URL: str  # Requerido, sin default. Ej: http://host.docker.internal:11434/ollama
    OLLAMA_API_TOKEN: str  # Requerido. Token Bearer para autenticación.
    OLLAMA_TIMEOUT_SECONDS: int = Field(default=5, gt=0, le=30)
```

### Validación

- `OLLAMA_BASE_URL` es obligatoria, sin valor por defecto; debe usar esquema `http` o `https`
- `OLLAMA_API_TOKEN` es obligatorio; no se imprime en logs ni se devuelve en errores
- `OLLAMA_TIMEOUT_SECONDS` debe ser > 0 y <= 30
- Errores de configuración se detectan en arranque
- No se imprimen credenciales en logs
- `OLLAMA_API_TOKEN` debe llegar mediante variable de entorno o secret del orquestador
- No debe incluirse en imágenes Docker ni en `.env.example` salvo como placeholder

### Pool de Conexiones PostgreSQL

- SQLAlchemy comparte un único engine con pool de conexiones.
- `pool_size` y `max_overflow` son configurables mediante variables de entorno
  y no codificados en lógica de dominio.
- Valores conservadores por defecto: `pool_size=5`, `max_overflow=10`.
- El engine se cierra correctamente durante el lifespan de FastAPI.
- Los health checks NO deben agotar el pool; se usa una conexión independiente
  o se verifica con una operación liviana.
- Los valores definitivos quedan sujetos a medición durante la implementación.

## Estrategia de Migraciones

### Flujo Explícito

```
1. docker compose up -d postgres
2. docker compose run --rm api uv run alembic upgrade head
3. docker compose up -d
```

### Primera Migración

```python
# 001_enable_pgvector.py
def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

def downgrade() -> None:
    # No eliminar la extensión vector en downgrade
    # porque puede ser destructivo en fases futuras
    pass
```

### Restricciones

- Las migraciones NO se ejecutan automáticamente al iniciar la API
- La API asume que las migraciones ya fueron aplicadas
- El downgrade no elimina la extensión vector (precaución)

## Diseño del Cliente Ollama

### Cliente HTTP Asíncrono

```python
class OllamaHealthAdapter:
    def __init__(self, base_url: str, api_token: str, timeout: float):
        self.client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_token}"},
        )

    async def check(self) -> DependencyHealth:
        try:
            response = await self.client.get("/api/version")
            # Validar: HTTP 2xx, JSON, campo 'version' como string no vacío
        except httpx.TimeoutException:
            return DependencyHealth(status="timeout", ...)
        except httpx.ConnectError:
            return DependencyHealth(status="unavailable", ...)
        finally:
            await self.client.aclose()
```

### Endpoint Seleccionado

`GET /api/version` — Información de versión del servicio Ollama. Operación
liviana que no ejecuta generación ni embeddings. Retorna JSON con el campo
`version` como string no vacío. Autenticación Bearer requerida.

### Estados Manejados

| Error | Estado | error_code |
|---|---|---|
| Timeout | `timeout` | `OLLAMA_TIMEOUT` |
| Conexión rechazada | `unavailable` | `OLLAMA_UNAVAILABLE` |
| HTTP 401 | `unauthorized` | `OLLAMA_UNAUTHORIZED` |
| HTTP 403 | `forbidden` | `OLLAMA_FORBIDDEN` |
| HTTP 404 | `unavailable` | `OLLAMA_ENDPOINT_NOT_FOUND` |
| HTTP 429 | `unavailable` | `OLLAMA_RATE_LIMITED` |
| HTTP 502/504 | `unavailable` | `OLLAMA_UNAVAILABLE` |
| JSON inválido | `invalid_response` | `OLLAMA_INVALID_RESPONSE` |
| URL inválida | `misconfigured` | `OLLAMA_MISCONFIGURED` |

## Decisiones de Portabilidad

### Contenedores Linux OCI

Todas las imágenes son Linux amd64. Docker Desktop (Windows) y Docker
Engine (Linux) ejecutan los mismos contenedores.

### host-gateway

Docker Compose incluye `extra_hosts: "host.docker.internal:host-gateway"`
para que `host.docker.internal` funcione tanto en Docker Desktop como en
Docker Engine.

### Sin Lógica de Host

- No se usan rutas absolutas del host
- Se usa `pathlib` para rutas internas
- No hay lógica condicional por sistema operativo
- No se depende de PowerShell o bash para la aplicación

### Volúmenes Nombrados

PostgreSQL usa volumen nombrado para persistencia. No se usan bind mounts
para datos en ejecución estable.

## Comandos Comunes

| Acción | Comando |
|---|---|
| Iniciar PostgreSQL | `docker compose up -d postgres` |
| Ejecutar migraciones | `docker compose run --rm api uv run alembic upgrade head` |
| Iniciar todo | `docker compose up -d` |
| Ver logs | `docker compose logs -f` |
| Ejecutar pruebas | `docker compose run --rm api uv run pytest` |
| Lint | `docker compose run --rm api uv run ruff check .` |
| Formato | `docker compose run --rm api uv run ruff format --check .` |
| mypy | `docker compose run --rm api uv run mypy src` |
| Detener | `docker compose down` |
| Limpiar datos | `docker compose down --volumes` |

## Estrategia de Pruebas

### Pruebas Unitarias

- Validación de configuración (timeout inválido, URL inválida)
- Composición del estado general
- Sanitización de errores
- Generación y validación de request_id
- Health service con fakes
- Códigos de error
- Comportamiento ante dependencias parciales

### Pruebas Contractuales

- Schema de `/health/live`
- Schema de `/health/ready`
- Schema de `/health/dependencies`
- Códigos HTTP correctos
- Header `X-Request-ID`
- Timestamp UTC ISO 8601
- `latency_ms` en milisegundos
- Ausencia de secretos

### Pruebas de Integración

- Conexión real con PostgreSQL
- Verificación real de pgvector
- Migración Alembic
- Comportamiento cuando falta la migración
- Persistencia de datos (smoke test)

### Pruebas del Adaptador Ollama

- Respuesta exitosa
- Timeout
- Conexión rechazada
- HTTP no exitoso
- JSON inválido
- Estructura inesperada
- URL inválida
- Cancelación

### Cobertura

- Mínimo 85% sobre código de aplicación relevante
- No usar cobertura como sustituto de escenarios importantes

## Decisiones Arquitectónicas

| # | Decisión | Justificación |
|---|---|---|
| 1 | SQLAlchemy async + asyncpg | Driver async más rápido para PostgreSQL |
| 2 | HTTPX AsyncClient compartido | Cliente moderno, soporte async, timeouts configurables |
| 3 | Lifespan de FastAPI | Gestión correcta de recursos (client, engine) |
| 4 | Alembic explícito | Migraciones versionadas, integración con SQLAlchemy |
| 5 | pgvector como extensión | Extensión de PostgreSQL, no requiere servicio separado |
| 6 | Sin Redis | No existe necesidad concreta en este incremento |
| 7 | 3 endpoints diferenciados | Liveness, readiness y diagnóstico con responsabilidades claras |
| 8 | Concurrencia selectiva | PostgreSQL+pgvector secuencial, Ollama en paralelo |
| 9 | Docker Compose portable | Contrato entre Windows (desarrollo) y Linux (ejecución) |
| 10 | uv | Gestión de dependencias rápida, lockfile reproducible |
| 11 | Contenedores Linux | Unidad portable, compatible con Kubernetes futuro |
| 12 | Variables de entorno | Portabilidad entre hosts sin cambios de código |
| 13 | host-gateway | Accesibilidad de Ollama en Linux sin IP fija |
| 14 | Sin scripts esenciales | Wrappers opcionales, comandos canónicos en Docker Compose |
| 15 | Bearer auth para Ollama | Token configurable, rotable sin cambio de código |
| 16 | GET /api/version como health | Endpoint liviano, sin generación ni embeddings |

## Riesgos

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| host.docker.internal no disponible en Linux | Media | Alto | `extra_hosts` con `host-gateway` |
| Gateway Docker diferente | Baja | Medio | Configurar `OLLAMA_BASE_URL` por entorno |
| pgvector no habilitado | Baja | Alto | Verificación explícita en health check |
| Credenciales inconsistentes | Media | Alto | Validación en arranque con pydantic-settings |
| Token de Ollama no configurado | Media | Alto | `OLLAMA_API_TOKEN` obligatorio, error en arranque si falta |
| Token de Ollama revocado | Baja | Medio | Health check informa `unauthorized`, sin crash |
| Dependencia de Ollama real en pruebas | Media | Medio | Mocks/fakes para la mayoría de tests |
| Exposición de secretos en logs | Baja | Crítico | Filtro explícito, revisión de código |
| Health checks costosos | Baja | Medio | Timeout independiente por dependencia |
| Diferencias Windows/Linux | Media | Medio | Contenedores Linux OCI como contrato |
| Bind mounts lentos en Docker Desktop | Alta | Bajo | Solo para desarrollo, no para producción |
| UID/GID en Linux | Media | Bajo | Ejecutar como usuario no root |
| Archivos generados como root | Baja | Medio | USER en Dockerfile |
| Señales SIGTERM | Baja | Medio | Uvicorn con shutdown automático |
| Healthchecks sin herramientas | Baja | Bajo | Usar Python para verificación |
| Imágenes sin soporte amd64 | Baja | Alto | Verificar platform en Dockerfile |
| Compose v1 vs v2 | Baja | Bajo | Documentar requisito de Compose v2 |

## Validación de Constitución

| Principio | Estado | Evidencia |
|---|---|---|
| I. Seguridad y Privacidad | ✅ | Sin envío de datos, sin secretos en Git |
| V. Salida Estructurada | ✅ | JSON schemas Pydantic, códigos de error |
| X. Arquitectura Modular | ✅ | Separación de capas, adaptadores |
| XII. Desarrollo Local | ✅ | Docker Compose, .env.example, comandos |
| XVI. Pruebas | ✅ | Unitarias, contractuales, integración |
| XX. Simplicidad | ✅ | Sin Redis, sin frontend, sin RAG |

## Artefactos Generados

| Archivo | Descripción |
|---|---|
| `plan.md` | Este archivo |
| `research.md` | Investigación y decisiones de stack |
| `data-model.md` | Modelos de datos y schemas |
| `contracts/health-live.md` | Contrato GET /health/live |
| `contracts/health-ready.md` | Contrato GET /health/ready |
| `contracts/health-dependencies.md` | Contrato GET /health/dependencies |
| `quickstart.md` | Guía de inicio rápido |

## Preguntas Pendientes

Ninguna. Todas las decisiones de la especificación aclarada fueron
incorporadas en el plan.

## Conflictos con Constitución o Especificación

Ninguno detectado. El plan es consistente con la constitución, los
principios IaC y la especificación aclarada.

## Alcance de Este Incremento

Este incremento se limita a la verificación local de dependencias base.
Las siguientes capacidades están **excluidas explícitamente** y no deben
generar código ni tareas:

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

La revisión humana obligatoria (Principio II) aplicará a capacidades
jurídicas futuras. Este incremento no procesa ni genera contenido jurídico
y no se cargan datos reales.

## Estado del Plan

**El plan está listo para generar tareas.**
