# Holdout de 1.000 decretos — evaluación consolidada

Esta carpeta reúne la evaluación comparable de **19 corridas** sobre los mismos
1.000 casos. Son **18 configuraciones únicas**: C02 y C14 repiten exactamente
los hiperparámetros y funcionan como réplica de estabilidad.

## Resultado de decisión

- **Candidata por semejanza factual:** C15 — embedding 4B/2.560, RAG 8.192,
  Ollama 16.384, `top_k=8`, pool 24 y score mínimo 0.
- **Accuracy proxy E2E:** 86,285%; completó 1.000/1.000 outputs.
- **Mejor 0.6B:** C19, con 85,852%.
- **Delta pareado C15−C19:** +0,433 puntos porcentuales; IC95%
  [+0,110; +0,756].
- C15 no se separa concluyentemente de C01, C02, C03, C14 ni C16: esas
  corridas forman una meseta 4B alrededor de 86%.

La recomendación es técnica y provisional. El evaluador automático no puede
certificar equivalencia jurídica ni detectar todas las invenciones.

## Mapa de artefactos

| Archivo | Propósito |
|---|---|
| `inputs-manifest.json` | Vincula 1.000 prompts con PDF, SHA-256 y caso. |
| `run-catalog.json` | Parámetros efectivos y ruta de las 19 corridas. |
| `results/benchmark-summary.json` | Fuente canónica: métricas, calidad de datos e IC pareados. |
| `results/benchmark-summary.csv` | Tabla plana para análisis y gráficos. |
| `results/benchmark-case-metrics.csv` | Evidencia por corrida y documento; no es necesaria para leer el reporte. |
| `report/artifact.json` | Contrato reproducible del reporte HTML. |
| `report/BENCHMARK_DECISION.md` | Resumen legible y tabla completa. |
| `METHODOLOGY.md` | Definiciones, fórmulas y límites. |
| `REPRODUCE.md` | Comandos y hashes de insumos. |
| `DATA_QUALITY.md` | Cobertura, joins, fallos y riesgos. |

Los outputs brutos y el caché factual permanecen fuera de Git por volumen y
contenido jurídico. Sus hashes se registran en `benchmark-summary.json`.
