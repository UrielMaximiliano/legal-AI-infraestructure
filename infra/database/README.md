# Bases aisladas de IMI LEG

Este directorio contiene los bootstraps SQL para el nuevo dominio de IMI LEG.

- `imi-core`: datos transaccionales normalizados y schema reservado para Better
  Auth. No contiene vectores.
- `imi-disposiciones-rag`: corpus exclusivo de disposiciones con pgvector.
  No contiene usuarios, templates ni decretos.

El perfil de IMI LEG es `imi_leg_06b`: `qwen3-embedding:0.6b`,
`halfvec(1024)`, contexto de embedding 2048, contexto RAG 2048, `top_k=8`,
pool 24, score mínimo 0 y generación `qwen3.6:35b` con `num_ctx=16384`.
El perfil legacy de decretos continúa en `legal_ai` con 4B/2560 y no se
modifica.

El esquema legado de `apps/api/alembic` no se modifica con estos scripts. La
separación del runtime requiere migrar explícitamente los repositorios y se
hará en una etapa posterior, después de validar los endpoints privados.

Validación estática:

```powershell
python tools/validate_database_contract.py
```

Para levantar las bases en local:

```powershell
docker compose -f compose.imi-leg.yaml up -d
```

Los volúmenes nuevos son `imi_core_postgres_data`,
`imi_disposiciones_rag_postgres_data` e `imi_leg_export_storage`. No deben
reutilizarse los volúmenes de `postgres_data` del RAG de decretos.
