#!/usr/bin/env bash
# Wrapper para desarrollo local

set -e

ACTION="${1:-up}"

case "$ACTION" in
    up)
        docker compose up -d postgres
        echo "PostgreSQL iniciado"
        ;;
    migrate)
        docker compose run --rm api alembic upgrade head
        ;;
    start)
        docker compose up -d
        ;;
    test)
        docker compose run --rm api pytest
        ;;
    lint)
        docker compose run --rm api ruff check .
        ;;
    format)
        docker compose run --rm api ruff format .
        ;;
    typecheck)
        docker compose run --rm api mypy src
        ;;
    down)
        docker compose down
        ;;
    clean)
        docker compose down --volumes
        echo "Contenedores y volúmenes eliminados"
        ;;
    *)
        echo "Acciones disponibles: up, migrate, start, test, lint, format, typecheck, down, clean"
        exit 1
        ;;
esac
