# Verificación final de cobertura de hiperparámetros — 2026-08-25

## Resultado

`COVERAGE_COMPLETE`. No se volvieron a ejecutar los 17.000 casos.

- Carpetas/corridas remotas detectadas: **81**
- Artefactos inventariados: **81**
- `artifact_id` únicos: **81**
- Configuraciones únicas de hiperparámetros: **18**
- Corridas FULL de 1.000 casos: **17**
- Configuraciones FULL únicas por hiperparámetros: **16**
- Configuraciones FULL evaluadas: **17/17**
- Configuraciones FULL únicas evaluadas: **16/16**
- Configuraciones omitidas: **0**
- Carpetas no reconciliadas: **0**
- Digest del listado remoto/local normalizado: `f2b435a7945e914a91ff4a890ec449711f1134debf0d2833ac096e7d6d190b5d`

La diferencia entre 17 corridas FULL y 16 configuraciones únicas se debe a C02/C14: tienen el mismo vector de hiperparámetros y comparten `config_hash`, pero sus `output_hash` son distintos. Se reportan como réplica candidata sin `seed` registrada; no como una configuración nueva.

## Configuraciones principales

`embedding_context`, `chunk_size`, `chunk_overlap`, `temperature` y `seed` no están registrados en el inventario remoto; se muestran como `NOT_RECORDED`, sin inferir valores.

| Run | Embedding | RAG ctx | Ollama ctx | top_k | Pool | Threshold | Casos |
|---|---|---:|---:|---:|---:|---:|---:|
| C02 | 4B | 4096 | 16384 | 8 | 24 | 0.00 | 1000 |
| C03 | 4B | 8192 | 32768 | 8 | 24 | 0.00 | 1000 |
| C04 | 4B | 4096 | 16384 | 5 | 15 | 0.65 | 1000 |
| C05 | 0.6B | 2048 | 8192 | 8 | 24 | 0.00 | 1000 |
| C06 | 0.6B | 2048 | 8192 | 5 | 15 | 0.65 | 1000 |
| C07 | 0.6B | 3072 | 16384 | 12 | 36 | 0.00 | 1000 |
| C08 | 0.6B | 2048 | 8192 | 8 | 40 | 0.55 | 1000 |
| C10 | 4B | 2048 | 16384 | 8 | 24 | 0.00 | 1000 |
| C11 | 4B | 2048 | 32768 | 8 | 24 | 0.00 | 1000 |
| C12 | 0.6B | 2048 | 16384 | 8 | 24 | 0.00 | 1000 |
| C13 | 0.6B | 2048 | 32768 | 8 | 24 | 0.00 | 1000 |
| C14 | 4B | 4096 | 16384 | 8 | 24 | 0.00 | 1000 |
| C15 | 4B | 8192 | 16384 | 8 | 24 | 0.00 | 1000 |
| C16 | 4B | 16384 | 16384 | 8 | 24 | 0.00 | 1000 |
| C17 | 0.6B | 4096 | 32768 | 8 | 24 | 0.00 | 1000 |
| C18 | 0.6B | 8192 | 32768 | 8 | 24 | 0.00 | 1000 |
| C19 | 0.6B | 16384 | 32768 | 8 | 24 | 0.00 | 1000 |

## Artefactos excluidos del benchmark principal

- **24 `SMOKE`**: corridas con nombre `*-smoke`, normalmente de 20 casos o de una prueba corta. Aunque algunas estén completas respecto de su propio objetivo, no son FULL de 1.000 casos.
- **32 `DIAGNOSTIC`**: `failed-attempts`, `debug-case7`, bloqueos de warmup, timeouts, errores de red, invalid-residency y carpetas de diagnóstico. Son evidencia operativa, no experimentos completos.
- **7 `PARTIAL`**: ejecuciones interrumpidas o incompletas: C01/v3 con objetivo real de 379 casos, C09 compacto con 103, y corridas 4096/residency con 1–71 casos o 6/20. No cumplen 1.000/1.000.
- **1 `INVALID`**: `benchmark-1000-4096-v2-blocked-warmup`, marcado inválido por el estado de ejecución y sin una corrida válida de 1.000 casos.

Ninguna corrida con `integrity=FULL`, `expected_cases=1000`, `available_cases>=1000` y joins válidos quedó en `SMOKE`, `DIAGNOSTIC`, `PARTIAL` o `INVALID`.

## Artefactos

- [Tabla por `config_hash`](../../benchmark_v2/results/full-host-inventory/hyperparameter_coverage.csv)
- [Tabla compacta de las 17 corridas FULL](../../benchmark_v2/results/full-host-inventory/hyperparameter_coverage_primary_17.csv)
- [Mapa de los 81 artefactos a su hash canónico](../../benchmark_v2/results/full-host-inventory/hyperparameter_artifact_mapping.csv)
- [Reporte machine-readable](../../benchmark_v2/results/full-host-inventory/hyperparameter_coverage_report.json)
- [Reconciliación física](../../benchmark_v2/results/full-host-inventory/artifact_to_logical_run_reconciliation.csv)
