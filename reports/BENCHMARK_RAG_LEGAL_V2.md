# Benchmark RAG legal V2 — auditoría, diseño y ejecución

Fecha de generación: 2026-08-25
Estado de esta ejecución: **NOT_CALCULABLE**
Resumen de ejecución: [`benchmark_v2/results/diagnostic-20260825/summary.json`](../benchmark_v2/results/diagnostic-20260825/summary.json)

## Conclusión ejecutiva

La corrida diagnóstica no calcula métricas V2 porque no recibió una tabla de casos. Esto es deliberado: el checkout no contiene los PDFs holdout, prompts, respuestas crudas, gold estructurado ni caché de recuperación necesarios para reconstruir la corrida completa.

No se publica un score global de “calidad legal”. Las dimensiones se reportan por separado y solo cuando sus referencias y artefactos están disponibles. Un valor ausente se conserva como `NOT_CALCULABLE`, nunca se convierte en cero ni se usa para ordenar configuraciones.

## Alcance y preservación

- Se creó un árbol independiente `benchmark_v2/` para contratos, evaluadores, runner, estadísticas, pruebas y resultados.
- El benchmark v1 (`docs/benchmarks/holdout-1000/`) y el código de producción no forman parte de la ruta de ejecución V2.
- El diseño cubre modelo Ollama, embedding, contexto, `top_k`, semilla, hardware, latencia/coste y cualquier dimensión adicional declarada en metadata.
- La comparación válida entre configuraciones exige los mismos `case_id`, referencias, política de exclusión y esquema de evaluación.

## Auditoría de v1

Fuente tabular: [`docs/benchmarks/holdout-1000/results/benchmark-summary.csv`](../docs/benchmarks/holdout-1000/results/benchmark-summary.csv).
19 ejecuciones tabuladas sobre 18 configuraciones; 19,000 casos esperados; 18,103 salidas encontradas; 17,995 exitosas; 108 fallidas; 897 ausentes; 0 joins de referencia inválidos.

Estos números son cobertura/ejecución y fidelidad factual proxy del benchmark existente; no son exactitud jurídica humana. La metodología v1 usa claims materiales, solapamiento/fidelidad y sus intervalos, no adjudicación legal independiente.

| Configuración v1 | Cobertura | Fidelidad E2E proxy | F1 claims materiales |
|---|---:|---:|---:|
| C09 — 0.6B compacto parcial | 10.300% | 8.778% | 11.584% |
| C15 — 4B RAG 8k fijo 16k | 100.000% | 86.285% | 49.019% |
| C19 — 0.6B RAG 16k fijo 32k | 100.000% | 85.852% | 49.452% |

Gráfico histórico disponible: [`accuracy-all-cases.png`](../docs/benchmarks/holdout-1000/report/accuracy-all-cases.png). No se presenta como resultado V2.

## Matriz multidimensional V2

| Dimensión | Estado observado | Qué se interpreta |
|---|---|---|
| semantic | NOT_CALCULABLE (0 casos) | ROUGE-L/chrF deterministas; BERTScore opcional |
| claims | NOT_CALCULABLE (0 casos) | claims, entidades y contradicciones con TP/FP/FN |
| legal_fields | NOT_CALCULABLE (0 casos) | norma, fecha, plazo, expediente y referencias; configurable |
| retrieval | NOT_CALCULABLE (0 casos) | Recall@k, MRR, nDCG, calidad/procedencia y leakage |
| faithfulness | NOT_CALCULABLE (0 casos) | claims soportados frente a evidencia RAG trazable |
| structure | NOT_CALCULABLE (0 casos) | JSON/schema, completitud, citas, evidencia, latencia y coste |
| statistics | PENDIENTE / requiere insumo | paired bootstrap/BCa, Wilcoxon, Holm y FULL–PARTIAL |
| human | PENDIENTE / requiere insumo | doble revisión ciega y adjudicación; plantilla sin scores rellenados |

El estado de dimensiones anterior resume solo los registros observados en esta corrida. `CALCULATED` significa que la dimensión pudo evaluarse con su referencia; `NOT_CALCULABLE` significa que faltó un insumo o contrato; `PARTIAL` significa que solo una parte de la dimensión fue calculable.

## Política FULL vs PARTIAL

- **FULL**: exactamente `expected_count` casos, IDs únicos, joins válidos y artefactos requeridos presentes.
- **PARTIAL**: casos válidos pero cobertura menor o cantidad esperada no declarada. Se conserva para diagnóstico y sensibilidad, no para ranking de corridas completas.
- **NOT_CALCULABLE**: no existe una base suficiente para producir métricas honestas. La corrida debe dejar manifest, razón y artefactos vacíos reproducibles.
- La comparación FULL–PARTIAL se expresa como delta por métrica y por caso emparejado; no como un promedio global opaco.

## Integridad, leakage y joins

Estado de las aserciones del runner: **NOT_CALCULABLE**.
IDs duplicados: `0`; joins inválidos: `0`; candidatos que contienen la referencia declarada: `0`.
Razones `NOT_CALCULABLE`: `input_cases_unavailable`.
Cuando no se dispone del texto excluido, el runner lo declara explícitamente como chequeo no calculable; no afirma ausencia de leakage por falta de evidencia.

## Evaluación humana

La plantilla [`human_eval_template.jsonl`](../benchmark_v2/results/diagnostic-20260825/human_eval_template.jsonl) deja en blanco dos revisiones independientes para organismo, objeto, persona/cargo, dependencia, fecha/plazo/vigencia, normas, artículos resolutivos, datos críticos, claims TP/FP/FN, faithfulness, utilidad y notas. La adjudicación debe registrar desacuerdos y conservar el ID de caso; no se debe imputar una etiqueta automática por similitud textual.

## Reproducibilidad

```powershell
& 'apps/api/.venv/Scripts/python.exe' benchmark_v2/scripts/run_benchmark.py `
  --cases <casos.jsonl> `
  --out-dir benchmark_v2/results/run-<id> `
  --run-id <id> --expected-count 1000 --seed 20260825 --human-sample 100
& 'apps/api/.venv/Scripts/python.exe' benchmark_v2/scripts/generate_report.py `
  --summary benchmark_v2/results/run-<id>/summary.json `
  --output reports/BENCHMARK_RAG_LEGAL_V2.md
```

El manifest conserva commit, semilla, timestamp, hash de entrada y hashes de registros. `metrics.jsonl` es la salida canónica por caso; `metrics.csv` facilita inspección tabular; Parquet queda como formato opcional cuando existe `pyarrow` o un engine equivalente.

## Limitaciones y próximos insumos

La ejecución completa V2 requiere montar fuera del repositorio el holdout original, su hash, prompts, respuestas Ollama, contexto recuperado, referencias gold, configuración de exclusión y trazas de coste/latencia. Hasta que esos artefactos estén disponibles, el resultado correcto es `NOT_CALCULABLE`, no una cifra de calidad inferida desde v1.
