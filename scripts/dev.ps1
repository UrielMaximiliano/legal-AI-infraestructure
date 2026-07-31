#!/usr/bin/env pwsh
# Wrapper para desarrollo local

param(
    [string]$Action = "up"
)

switch ($Action) {
    "up" {
        docker compose up -d postgres
        Write-Host "PostgreSQL iniciado"
    }
    "migrate" {
        docker compose run --rm api alembic upgrade head
    }
    "start" {
        docker compose up -d
    }
    "test" {
        docker compose run --rm api pytest
    }
    "lint" {
        docker compose run --rm api ruff check .
    }
    "format" {
        docker compose run --rm api ruff format .
    }
    "typecheck" {
        docker compose run --rm api mypy src
    }
    "down" {
        docker compose down
    }
    "clean" {
        docker compose down --volumes
        Write-Host "Contenedores y volúmenes eliminados"
    }
    default {
        Write-Host "Acciones disponibles: up, migrate, start, test, lint, format, typecheck, down, clean"
    }
}
