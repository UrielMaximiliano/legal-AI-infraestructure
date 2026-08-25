# Evaluación completa del benchmark V2 — 2026-08-25

## Estado y criterio de inclusión

La evaluación se completó sobre el snapshot local de los resultados recuperados del host RTX 5090. Se conservaron los resultados calculados con el evaluador anterior como referencia histórica, pero el reporte principal usa exclusivamente la recomputación con:

- `evaluator_version`: `benchmark-v2-legal-core-2-calibrated`
- `rules_version`: `typed-critical-v2-template-aware`
- un único `evaluator_hash` para todas las configuraciones principales
- `case_set_hash` común para las 17 configuraciones canónicas de 1.000 casos

Los artefactos físicos no se trataron como experimentos independientes.

| Clasificación | Artefactos | Casos evaluados | Inferencia principal |
|---|---:|---:|---|
| `PRIMARY_FULL_1000` | 17 | 17.000 | Sí |
| `REPLICATE_FULL_1000` | 0 | 0 | Estabilidad: no disponible |
| `SMOKE` | 24 | 444 | Apéndice |
| `DIAGNOSTIC` | 32 | 510 | Apéndice |
| `PARTIAL` | 7 | 1.199 | Exploratorio |
| `ARCHIVE_DUPLICATE` | 0 | 0 | Excluido |
| `RECOVERED_COPY` | 0 | 0 | Estabilidad: no disponible |
| `INVALID` | 1 | 1 | Excluido |
| **Total** | **81** | **19.154** | — |

La reconciliación completa está en `benchmark_v2/results/full-host-inventory/artifact_to_logical_run_reconciliation.csv`. La verificación posterior de cobertura encontró 18 vectores únicos de hiperparámetros: 16 FULL y 2 parciales. Las 17 corridas FULL incluyen C02 y C14, que comparten exactamente el mismo vector de hiperparámetros pero tienen outputs distintos; se conservan como corridas separadas y réplica candidata sin `seed` registrada. El detalle está en `docs/benchmark_v2/hyperparameter_coverage_20260825.md`. El snapshot tiene 19.483 archivos, 862.579.563 bytes y 28 grupos de contenido repetido; esos grupos corresponden principalmente a archivos internos compartidos y no se convirtieron automáticamente en duplicados de experimentos.

## Auditoría de LegalPass

Se revisaron 40 casos estratificados. El conjunto permitido quedó documentado como:

`prompt + gold/facts/evidencia permitida + reglas explícitas de plantilla o contrato`.

Las fórmulas jurídicas estándar de cierre/publicación ya no se marcan como adiciones críticas por defecto. Sólo se marcan cuando el contrato las prohíbe explícitamente. En cambio, los valores tipados inventados —DNI, monto, fecha, norma, expediente, persona, cargo o condición— continúan siendo errores críticos.

Los sanity/challenge tests pasaron todos: identidad, paráfrasis jurídica equivalente, monto alterado, DNI alterado, fecha material alterada, negación invertida, modalidad deóntica alterada y omisión crítica. También pasaron los dos controles de fórmula de plantilla: permitida por defecto y prohibida por contrato.

El detalle está en `benchmark_v2/results/all-runs-20260825/evaluator-calibration/audit.json`; la muestra está en `sample.jsonl`.

## Resultados principales

Las 17 configuraciones principales quedaron entre 5,9% y 9,0% de `LegalPassRate`, con media de 7,5%. Los intervalos reportados son Wilson 95% por configuración. El ranking completo está en `benchmark_v2/results/all-runs-20260825/calibrated-legal-core-2-final/stats/primary_ranking.csv`.

| Posición | Configuración | LegalPassRate | IC 95% | Claims Recall |
|---:|---|---:|---:|---:|
| 1 | `sensitivity-v2-s06b-a2-recovery-1` | 9,0% | 7,4–10,9% | 87,37% |
| 2 | `benchmark1000-06b-diverse-recovery-2` | 8,9% | 7,3–10,8% | 87,08% |
| 3 | `benchmark1000-06b-balanced` | 8,7% | 7,1–10,6% | 87,40% |
| 17 | `benchmark1000-8192-v4` | 5,9% | 4,6–7,5% | 87,27% |

En promedio, `Claims Recall` fue 86,86%; la omisión crítica quedó en 77,99–81,90% y las adiciones no soportadas en 36,70–56,70%. Estos últimos resultados son posteriores a la calibración; no deben compararse directamente con los resultados del evaluador anterior sin considerar el cambio de versión.

Para LegalPass se calcularon 136 comparaciones pareadas sobre los mismos `case_id`, con McNemar exacto bilateral. Se aplicó Holm-Bonferroni a los p-valores. Sólo una comparación quedó significativa después de Holm: `sensitivity-v2-s06b-a2-ollama16384-rag2048` frente a `benchmark1000-8192-v4`, diferencia de +3,1 puntos porcentuales para la primera. Para Claims Recall y métricas continuas se calcularon 154 filas de contrastes controlados, con bootstrap pareado de 10.000 remuestras y Holm.

## Retrieval y trazabilidad

Los chunks históricos no contienen texto reconstruible. Por eso `SourceFaithfulness` y `AEC@k` se mantienen como `NOT_RECONSTRUCTABLE`. Esto no bloqueó LegalPass, Claims Recall, campos críticos, contradicciones, omisiones ni adiciones. La trazabilidad de IDs se conserva como dimensión separada.

## Orca/OpenCode

Orca fue utilizado para aislamiento, orquestación de pods y worktrees. El launcher de Orca devolvió `Access is denied`; por ese motivo OpenCode fue ejecutado directamente dentro de los worktrees. No se atribuye a Orca la ejecución de esos procesos.

## Artefactos reproducibles

- Reconciliación: `benchmark_v2/results/full-host-inventory/artifact_to_logical_run_reconciliation.csv`
- Manifest del snapshot: `benchmark_v2/results/full-host-inventory/snapshot_manifest.json`
- Auditoría del evaluador: `benchmark_v2/results/all-runs-20260825/evaluator-calibration/audit.json`
- Métricas por configuración: `benchmark_v2/results/all-runs-20260825/calibrated-legal-core-2-final/configuration_metrics.csv`
- Manifest del evaluador: `benchmark_v2/results/all-runs-20260825/calibrated-legal-core-2-final/evaluator_manifest.json`
- Ranking principal: `benchmark_v2/results/all-runs-20260825/calibrated-legal-core-2-final/stats/primary_ranking.csv`
- Comparaciones pareadas: `benchmark_v2/results/all-runs-20260825/calibrated-legal-core-2-final/stats/pairwise_comparisons.csv`
- Bootstrap continuo: `benchmark_v2/results/all-runs-20260825/calibrated-legal-core-2-final/stats/continuous_controlled_contrasts.csv`
- Manifest estadístico: `benchmark_v2/results/all-runs-20260825/calibrated-legal-core-2-final/stats/statistics_manifest.json`
