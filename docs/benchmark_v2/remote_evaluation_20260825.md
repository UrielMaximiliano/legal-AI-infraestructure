# Benchmark V2 — evaluación sobre outputs reales

Fecha de ejecución: 2026-08-25. Fuente remota: `pc-rtx5090`, snapshot de
`backups/benchmark-results` y `backups/benchmark-evaluation-v2`.

## Alcance y trazabilidad

Se reconstruyó el join por `reference_pdf + reference_sha256` entre los
case files históricos y `pdf-gold-facts.auto.jsonl`. La corrida C03 contiene
1.000/1.000 casos `SUCCEEDED`; el join fue completo y no se enviaron PDFs ni
gold al modelo durante la generación histórica.

La evaluación V2 aplica el prompt como máscara de divulgación. Por eso un dato
redactado del pedido no se penaliza como omisión, pero una fecha, monto,
expediente o norma que aparece en el draft sin respaldo en prompt/gold se
reporta como adición no soportada. `LegalPass=1` exige simultáneamente cero
contradicciones críticas, cero omisiones críticas, cero adiciones críticas y
todos los campos críticos divulgados correctos.

## Primera evidencia end-to-end

Caso 0001 (`200924.pdf`, SHA-256 verificado):

| Métrica | Resultado |
|---|---:|
| PromptCoverage | 76,47% |
| Atomic Claims recall | 100% |
| Contradicciones críticas | 0 |
| Omisiones críticas | 0 |
| Adiciones no soportadas | 7 |
| Source citation traceability | 100% |
| Candidate source/reference alignment | 0% |
| Source Faithfulness | NOT_RECONSTRUCTABLE |
| LegalPass | 0 |

El output contiene los tres artículos funcionales y las citas `SRC-003` y
`SRC-016`. También contiene un expediente y fechas no divulgados, una fórmula
de autoridad no provista y un cierre/publicación que el prompt prohibía. La
traza histórica sólo conserva IDs, ranks y scores de chunks, no el texto de
cada chunk; por eso la fidelidad textual no se convierte artificialmente en
cero ni se usa para bloquear el resto de las métricas.

## Escalamiento C03 — 4B RAG 8k

| Casos evaluados | LegalPass rate | Atomic Claims recall | Contradicción crítica | Omisión crítica | Adición no soportada |
|---:|---:|---:|---:|---:|---:|
| 1 | 0,00% | 100,00% | 0,00% | 0,00% | 100,00% |
| 10 | 0,00% | 86,70% | 20,00% | 90,00% | 90,00% |
| 100 | 0,00% | 87,23% | 11,00% | 85,00% | 95,00% |
| 1.000 | 0,80% | 87,27% | 15,50% | 79,10% | 92,10% |

La integridad de datos fue `FULL` en las cuatro escalas. La parte de
recuperación/fidelidad textual fue `NOT_RECONSTRUCTABLE` en 1, 10, 100 y
1.000 casos, con trazabilidad de citas calculable por caso.

## Comparación C02 vs C03 sobre 1.000 casos

| Configuración | LegalPass rate V2 | Atomic Claims recall | Contradicción crítica | Omisión crítica | Adición no soportada |
|---|---:|---:|---:|---:|---:|
| C02 — 4B RAG 4k | 1,50% | 87,30% | 15,80% | 77,90% | 90,80% |
| C03 — 4B RAG 8k | 0,80% | 87,27% | 15,50% | 79,10% | 92,10% |

Como control histórico, el resumen V3 remoto reportaba para C02/C03 cobertura
y éxito de generación de 100%, factual fidelity aproximada de 0,861 y
material F1 de 0,486. Esas métricas tokenizadas no sustituyen LegalPass: la
segunda evaluación revela fallos jurídicos críticos que el agregado histórico
no separaba.

## Artefactos reproducibles

- [evaluador legal core](../../benchmark_v2/evaluators/legal_core/evaluator.py)
- [runner de outputs remotos](../../benchmark_v2/scripts/evaluate_remote_run.py)
- [resultado C03 — caso 1](../../benchmark_v2/results/remote-8192-v4-20260825/limit-0001/summary.json)
- [resultado C03 — 10 casos](../../benchmark_v2/results/remote-8192-v4-20260825/limit-0010/summary.json)
- [resultado C03 — 100 casos](../../benchmark_v2/results/remote-8192-v4-20260825/limit-0100/summary.json)
- [resultado C03 — 1.000 casos](../../benchmark_v2/results/remote-8192-v4-20260825/limit-1000/summary.json)
- [resultado C02 — 1.000 casos](../../benchmark_v2/results/remote-4096-v2-20260825/limit-1000/summary.json)

El snapshot raw y las credenciales permanecen fuera del repositorio, bajo el
directorio temporal local usado para la auditoría. No se modificó el host
remoto ni los datos de producción.
