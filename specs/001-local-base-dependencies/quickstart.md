# Quickstart: Base Local y Verificación de Dependencias

**Feature**: `001-local-base-dependencies`
**Fecha**: 2026-07-31
**Estado**: Completo

**Alcance**: Este incremento se limita a la verificación de dependencias
base. No procesa ni genera contenido jurídico. La revisión humana
obligatoria aplicará a capacidades jurídicas futuras. No se cargan datos
reales.

## Prerrequisitos

### Windows

- Docker Desktop 4.x o superior
- PowerShell 5.1 o superior
- Git

### Linux (Ubuntu)

- Docker Engine 24.x o superior
- Docker Compose v2
- Git
- bash

### Ambos

- Acceso a un endpoint de Ollama (local o remoto)
- Puerto 5432 disponible (para PostgreSQL)
- Puerto 8000 disponible (para la API)

## Instalación

```bash
# Clonar el repositorio
git clone <url-del-repositorio>
cd legal-AI-infraestructure
```

```powershell
# PowerShell: Copiar archivo de configuración de ejemplo
Copy-Item .env.example .env
```

```bash
# bash: Copiar archivo de configuración de ejemplo
cp .env.example .env
```

```bash
# Editar .env según el entorno (ver sección Configuración)
# No versionar el archivo .env
```

## Configuración

### Variables Mínimas

El archivo `.env` debe contener al menos:

```bash
# Entorno
APP_ENV=development
APP_NAME=legal-ai-api
APP_VERSION=0.1.0

# API
API_HOST=0.0.0.0
API_PORT=8000
LOG_LEVEL=INFO

# PostgreSQL
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=legal_ai
POSTGRES_USER=legal_ai
POSTGRES_PASSWORD=cambiar-en-produccion

# Ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_API_TOKEN=tu-token-aqui
OLLAMA_TIMEOUT_SECONDS=5
```

> **Nota de seguridad**: `OLLAMA_API_TOKEN` es un secret. No incluir
> valores reales en `.env.example` y no versionar el archivo `.env`.

### Configuración de Ollama por Entorno

**Windows con Ollama en el host:**

```bash
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

**Linux con Docker Engine:**

```bash
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

**Ollama en otra máquina:**

```bash
OLLAMA_BASE_URL=http://192.168.1.100:11434
```

**Ollama mediante DNS interno:**

```bash
OLLAMA_BASE_URL=http://ollama.internal:11434
```

## Comandos Comunes

### Iniciar PostgreSQL

```bash
# PowerShell y bash
docker compose up -d postgres
```

### Ejecutar Migraciones

```bash
# PowerShell y bash
docker compose run --rm api alembic upgrade head
```

### Iniciar Todo

```bash
# PowerShell y bash
docker compose up -d
```

### Ver Logs

```bash
# PowerShell y bash
docker compose logs -f
```

### Ejecutar Pruebas

```bash
# PowerShell y bash
docker compose run --rm api pytest
```

### Ejecutar Lint

```bash
# PowerShell y bash
docker compose run --rm api ruff check .
```

### Verificar Formato

```bash
# PowerShell y bash
docker compose run --rm api ruff format --check .
```

### Ejecutar mypy

```bash
# PowerShell y bash
docker compose run --rm api mypy src
```

### Detener

```bash
# PowerShell y bash
docker compose down
```

### Eliminar Contenedores y Volúmenes

```bash
# PowerShell y bash
docker compose down --volumes
```

**ADVERTENCIA**: Este comando elimina todos los datos de PostgreSQL.

### Cambiar Contraseña de PostgreSQL

Cambiar `POSTGRES_PASSWORD` en `.env` no actualiza la contraseña dentro de un volumen PostgreSQL existente. Si se cambió la contraseña y aparece `password authentication failed`:

```bash
# PowerShell y bash (desarrollo vacío, sin datos reales)
docker compose down --volumes --remove-orphans
docker compose up -d postgres
```

> **Nota**: Esta operación es destructiva. Solo usar en desarrollo cuando no
> existan datos persistentes relevantes.

## Verificación

### 1. Health Live

```bash
curl http://localhost:8000/health/live
```

Respuesta esperada:

```json
{
  "status": "ok",
  "service": "legal-ai-api",
  "version": "0.1.0",
  "request_id": "..."
}
```

### 2. Health Ready

```bash
curl http://localhost:8000/health/ready
```

Respuesta esperada (todas las dependencias OK):

```json
{
  "status": "ready",
  "timestamp": "2026-07-31T15:00:00Z",
  "request_id": "..."
}
```

### 3. Health Dependencies

```bash
curl http://localhost:8000/health/dependencies
```

Respuesta esperada:

```json
{
  "status": "ready",
  "timestamp": "2026-07-31T15:00:00Z",
  "request_id": "...",
  "dependencies": {
    "postgres": {
      "status": "ok",
      "latency_ms": 8.5,
      "error_code": null,
      "message": null
    },
    "pgvector": {
      "status": "ok",
      "latency_ms": 2.1,
      "error_code": null,
      "message": null
    },
    "ollama": {
      "status": "ok",
      "latency_ms": 31.4,
      "error_code": null,
      "message": null
    }
  }
}
```

## Diagnóstico de Ollama

### Verificar Conectividad

```bash
# Verificar que Ollama responde (con autenticación Bearer)
curl -H "Authorization: Bearer TU_TOKEN" http://host.docker.internal:11434/api/version
```

### Verificar Versión de Ollama

```bash
# Obtener versión
curl -H "Authorization: Bearer TU_TOKEN" http://host.docker.internal:11434/api/version | jq
```

### Solución de Problemas

**Ollama no accesible desde contenedor:**

1. Verificar que Ollama está ejecutándose en el host
2. Verificar que `OLLAMA_BASE_URL` es correcto
3. Verificar que `extra_hosts` está configurado en Docker Compose
4. Verificar que el firewall no bloquea el puerto

**host.docker.internal no funciona en Linux:**

1. Verificar que Docker Engine soporta `host-gateway`
2. Usar la IP de la gateway de Docker: `docker network inspect bridge`
3. Configurar `OLLAMA_BASE_URL` con la IP correcta

## Troubleshooting

### Errores Comunes

| Error | Causa | Solución |
|---|---|---|
| `POSTGRES_UNAVAILABLE` | PostgreSQL no está ejecutándose | `docker compose up -d postgres` |
| `PGVECTOR_MISSING` | Extensión no instalada | Ejecutar migraciones |
| `OLLAMA_TIMEOUT` | Ollama no responde | Verificar URL y conectividad |
| `OLLAMA_UNAUTHORIZED` | Token inválido o ausente | Verificar `OLLAMA_API_TOKEN` en `.env` |
| `OLLAMA_FORBIDDEN` | Token válido sin permisos | Verificar permisos del token |
| `OLLAMA_MISCONFIGURED` | URL inválida | Verificar `OLLAMA_BASE_URL` en `.env` |
| `CONFIGURATION_INVALID` | Variables faltantes | Revisar archivo `.env` |

### Logs Útiles

```bash
# Ver logs de PostgreSQL
docker compose logs postgres

# Ver logs de la API
docker compose logs api

# Ver logs con filtro
docker compose logs -f api | grep "health"
```

## Diferencias entre Docker Desktop y Docker Engine

| Aspecto | Docker Desktop | Docker Engine |
|---|---|---|
| `host.docker.internal` | Funciona nativo | Requiere `extra_hosts` |
| Rendimiento de volumes | Menor (VM) | Nativo |
| Recursos | Limitados por VM | Ilimitados |
| Red | NAT | Bridge |

## Traslado a Otro Servidor

Para mover el proyecto a otro servidor:

1. Clonar el repositorio
2. Configurar variables de entorno en `.env`
3. Verificar que Docker y Docker Compose están instalados
4. Configurar acceso a Ollama (`OLLAMA_BASE_URL`)
5. Ejecutar `docker compose up -d postgres`
6. Ejecutar migraciones: `docker compose run --rm api alembic upgrade head`
7. Ejecutar `docker compose up -d`

No se requieren cambios de código ni rutas codificadas.
