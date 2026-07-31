# Investigación Técnica: Base Local y Verificación de Dependencias

**Feature**: `001-local-base-dependencies`
**Fecha**: 2026-07-31
**Estado**: Completo

## Decisiones de Stack

### Python 3.12

**Decisión**: Python 3.12 como lenguaje de la aplicación.

**Justificación**: Ecosistema ML/AI maduro, tipado estricto, soporte nativo
para async/await, compatibilidad con FastAPI y SQLAlchemy 2.x. Constitución
del proyecto lo fija como requisito.

**Alternativas consideradas**:
- Python 3.11: Compatible pero sin mejoras de tipado de 3.12.
- Python 3.13: Versión demasiado reciente, ecosistema no consolidado.

### FastAPI + Uvicorn

**Decisión**: FastAPI como framework HTTP, Uvicorn como servidor ASGI.

**Justificación**: Soporte nativo para async/await, validación automática
mediante Pydantic, generación de OpenAPI, rendimiento comprobado. La
constitución lo fija como stack base.

**Alternativas consideradas**:
- Flask: Sin soporte async nativo, menos adecuado para health checks concurrentes.
- Django: Excesivamente pesado para este incremento, opinionado sobre ORM.

### Pydantic v2 + pydantic-settings

**Decisión**: Pydantic v2 para validación de schemas, pydantic-settings para
configuración tipada.

**Justificación**: Validación estricta en tiempo de ejecución, serialización
JSON nativa, integración directa con FastAPI. pydantic-settings permite
configuración mediante variables de entorno con validación incorporada.

**Alternativas consideradas**:
- dataclasses + manual validation: Más trabajo, menos integración con FastAPI.
- Marshmallow: Menor integración con FastAPI, más verboso.

### SQLAlchemy 2.x + asyncpg

**Decisión**: SQLAlchemy 2.x con interfaz asíncrona, asyncpg como driver.

**Justificación**: ORM maduro, soporte async completo en 2.x, integración
con Alembic, asyncpg es el driver async más rápido para PostgreSQL. La
constitución fija SQLAlchemy y asyncpg.

**Alternativas consideradas**:
- Tortoise ORM: Menor madurez, menos integración con Alembic.
- psycopg3: Alternativa válida pero asyncpg tiene mejor rendimiento en benchmarks.

### Alembic

**Decisión**: Alembic para migraciones versionadas.

**Justificación**: Integración nativa con SQLAlchemy, soporte para migraciones
expresas, ampliamente adoptado. La especificación requiere migraciones
versionadas desde el primer incremento.

**Alternativas consideradas**:
- yoyo-migrations: Menor integración con SQLAlchemy.
- Migraciones manuales: Sin control de版本, error prone.

### HTTPX AsyncClient

**Decisión**: HTTPX como cliente HTTP asíncrono para Ollama.

**Justificación**: Soporte async nativo, API similar a requests, timeouts
configurables, cierre correcto de recursos. Más moderno que aiohttp para
este caso de uso.

**Alternativas consideradas**:
- aiohttp: Más complejo, API menos intuitiva.
- httpx sync: Sin beneficio async, bloqueante.

### pytest + pytest-asyncio + pytest-cov

**Decisión**: pytest como framework de pruebas, pytest-asyncio para pruebas
async, pytest-cov para cobertura.

**Justificación**: Estándar de la industria Python, soporte completo para
async, plugins extensibles. La constitución requiere pruebas proporcionales
al riesgo.

**Alternativas consideradas**:
- unittest: Más verboso, menos plugins, sin soporte nativo async.

### Ruff

**Decisión**: Ruff para linting y formateo.

**Justificación**: Más rápido que flake8 + black + isort combinados,
un solo herramienta para linting y formateo, reglas extensibles. La
constitución requiere linting y formateo automático.

**Alternativas consideradas**:
- flake8 + black + isort: Tres herramientas separadas, más lento.
- pylint: Más lento, más verboso.

### mypy

**Decisión**: mypy para verificación estática de tipos.

**Justificación**: Estándar para Python tipado, integración con Pydantic,
detección de errores en tiempo de compilación. La constitución requiere
tipado estricto.

**Alternativas consideradas**:
- pyright: Alternativa válida pero mypy tiene mayor adopción.
- pytype: Menor mantenimiento.

### uv

**Decisión**: uv para gestión de dependencias y lockfile.

**Justificación**: Más rápido que pip + pip-tools, genera uv.lock
reproducible, soporte para pyproject.toml. La constitución requiere
versiones reproducibles y lockfiles.

**Alternativas consideradas**:
- pip + pip-tools: Más lento, dos herramientas separadas.
- poetry: Más pesado, menos rápido.
- pdm: Menor adopción.

### Docker + Docker Compose v2

**Decisión**: Docker para contenedores, Docker Compose v2 para
orquestación local.

**Justificación**: Estándar de la industria, portable entre Windows y
Linux, soporte para health checks, volúmenes nombrados. La constitución
fija Docker Compose para desarrollo local.

**Alternativas consideradas**:
- Podman: Compatible pero menor adopción en el equipo.
- docker-compose v1: Deprecado.

### PostgreSQL con pgvector

**Decisión**: Imagen `pgvector/pgvector:0.8.0-pg16` para PostgreSQL con
pgvector.

**Justificación**: Versión explícita, compatible con amd64, mantenida,
incluye pgvector preinstalado. La especificación requiere verificación
real de pgvector.

**Alternativas consideradas**:
- PostgreSQL official + extensión manual: Más pasos, menos reproducible.
- pgvector/pgvector:latest: Sin versión fija, riesgo de breaking changes.

## Decisiones de Arquitectura

### Separación de Health Checks

**Decisión**: Tres endpoints separados: `/health/live`, `/health/ready`,
`/health/dependencies`.

**Justificación**: Liveness no debe consultar dependencias (Kubernetes
lo reiniciaría si dependencias fallan). Readiness indica preparación
para tráfico. Dependencies expone diagnóstico detallado para operadores.

**Alternativas consideradas**:
- Un solo endpoint genérico: Ambiguo entre liveness y readiness.
- Dos endpoints (live + ready): Sin diagnóstico individual para operadores.

### Concurrencia de Verificaciones

**Decisión**: PostgreSQL y pgvector se verifican secuencialmente (pgvector
depende de PostgreSQL). Ollama se verifica en paralelo con el flujo de
base de datos.

**Justificación**: pgvector requiere una conexión PostgreSQL válida para
consultar el catálogo de extensiones. Verificarlos en paralelo sería
redundante. Ollama es independiente y puede verificarse en paralelo.

**Alternativas consideradas**:
- Todo en paralelo: Redundante para pgvector, consume recursos innecesarios.
- Todo secuencial: Más lento, sin beneficio para Ollama.

### Configuración Tipada

**Decisión**: pydantic-settings con validación en tiempo de arranque.

**Justificación**: Error temprano de configuración, tipado estricto,
integración con .env.example. La especificación requiere detección de
configuración inválida.

**Alternativas consideradas**:
- configparser: Sin tipado, sin validación automática.
- Variables de entorno crudas: Sin validación, error tardío.

### Request ID

**Decisión**: Middleware que genera UUID v4 si no se provee
`X-Request-ID`, sanitiza valores recibidos.

**Justificación**: Trazabilidad de solicitudes, correlación con logs,
requisito de la especificación. UUID v4 es estándar y no requiere
coordinación.

**Alternativas consideradas**:
- ULID: Más complejo, sin beneficio para este caso.
- NanoID: Más corto pero menos estándar.

### Logging Estructurado

**Decisión**: Logging con campos estructurados (timestamp, level, logger,
message, request_id, event, duration_ms, service, environment).

**Justificación**: Diagnóstico facilitado, correlación con request_id,
compatibilidad con herramientas de observabilidad futuras. La constitución
requiere logs estructurados sin secretos.

**Alternativas consideradas**:
- Logging plain text: Más difícil de parsear.
- structlog: Más complejo, innecesario para este incremento.

## Decisiones de Portabilidad

### Contrato de Ollama

**Decisión**: Utilizar `GET {OLLAMA_BASE_URL}/api/version` como health check
de Ollama, con autenticación Bearer mediante `OLLAMA_API_TOKEN`.

**Justificación**: El endpoint `/api/version` es una operación liviana que no
ejecuta generación ni embeddings. Retorna JSON con un campo `version` como
string no vacío. La autenticación Bearer es el mecanismo estándar de la API
externa de Ollama. `OLLAMA_BASE_URL` puede incluir un prefijo de path
(ej. `https://example.internal/ollama`); el cliente construye la URL
completa concatenando `/api/version` sin perder el prefijo ni duplicar barras.

**Configuración canónica**:
```
OLLAMA_BASE_URL=<URL_CONFIGURABLE>        # Obligatorio, sin default
OLLAMA_API_TOKEN=<SECRET>                 # Obligatorio, secret
OLLAMA_TIMEOUT_SECONDS=5                  # Default 5, rango (0, 30]
```

**Reglas por entorno**:
- Production: HTTPS obligatorio.
- Development y test: HTTP permitido explícitamente.
- Dependencia inaccesible: la API inicia y readiness informa `not_ready`.
- Configuración estructural inválida: puede impedir el arranque con error sanitizado.

**Seguridad del token**:
- No debe incluirse en imágenes Docker.
- No debe aparecer en `.env.example` salvo como placeholder.
- No debe registrarse en logs ni devolverse en errores.
- Debe poder rotarse sin modificar código.

**Alternativas consideradas**:
- `GET /api/tags`: Retorna lista de modelos, operación más pesada innecesaria para health.
- `GET /api/ps`: Retorna modelos en ejecución, no apropiado para health.
- Generación de prueba: Costosa, innecesaria, bloquea un slot de inferencia.

### Contenedores Linux OCI

**Decisión**: Todas las imágenes son Linux amd64, ejecutables en Docker
Desktop (Windows) y Docker Engine (Linux).

**Justificación**: Windows como entorno de desarrollo, Linux como entorno
de ejecución. Docker Compose actúa como contrato portable.

**Alternativas consideradas**:
- Windows containers: No compatible con PostgreSQL Linux images.
- Multi-arch: Complejidad innecesaria para este incremento.

### host-gateway

**Decisión**: Utilizar `extra_hosts: "host.docker.internal:host-gateway"`
en Docker Compose para accesibilidad de Ollama en Linux.

**Justificación**: Permite que `host.docker.internal` funcione tanto en
Docker Desktop (Windows/Mac) como en Docker Engine (Linux) con soporte
para host-gateway.

**Alternativas consideradas**:
- IP fija 172.17.0.1: No portable, depende de configuración Docker.
- network_mode: host: Pierde aislamiento de red.

### Variables de Entorno

**Decisión**: Toda configuración mediante variables de entorno, sin
valores codificados.

**Justificación**: Portabilidad entre hosts, sin cambios de código,
compatible con Docker Compose, Kubernetes y cualquier entorno.

**Alternativas consideradas**:
- Archivos de configuración por entorno: Más complejo, requiere montaje.
- Configuración inline: No portable, requiere reconstrucción.

## Riesgos Identificados

| Riesgo | Mitigación |
|---|---|
| host.docker.internal no disponible en Linux | Usar `extra_hosts` con `host-gateway` |
| Gateway Docker diferente | Configurar `OLLAMA_BASE_URL` por entorno |
| pgvector no habilitado | Verificación explícita en health check |
| Credenciales inconsistentes | Validación en arranque con pydantic-settings |
| Dependencia de Ollama real en pruebas | Mocks/fakes para la mayoría de tests |
| Exposición de secretos en logs | Filtro explícito, revisión de código |
| Health checks costosos | Timeout independiente por dependencia |
| Diferencias Windows/Linux | Contenedores Linux OCI como contrato |
| Rutas específicas del host | Usar pathlib, rutas de contenedor |
| CRLF vs LF | .gitattributes, editorconfig |
| Bind mounts lentos en Docker Desktop | Solo para desarrollo, no para producción |
| UID/GID en Linux | Ejecutar como usuario no root |
| Archivos generados como root | USER en Dockerfile |
| Señales SIGTERM | Uvicorn con shutdown automático |
| Healthchecks sin herramientas | Usar Python para verificación |
| Imágenes sin soporte amd64 | Verificar platform en Dockerfile |
| Compose v1 vs v2 | Documentar requisito de Compose v2 |
