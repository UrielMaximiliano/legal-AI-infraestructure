# Auditoría del benchmark factual real

Fecha de esta auditoría: 2026-08-25. Checkout auditado: `82f95fa05b930d7e620377fbe4e270f1e8cb782c` (`merge: add reproducible holdout benchmark evaluation`). La evidencia primaria es la carpeta [holdout-1000](../benchmarks/holdout-1000/), los evaluadores de [`tools/`](../../tools/) y el [protocolo](../benchmarks/benchmark-protocol.md). Distingo entre lo comprobable en este checkout y lo que el reporte declara sobre insumos externos.

## Dictamen

- Hay **19 corridas**, **18 tuplas de parámetros únicas**: C02 y C14 son una réplica exacta de parámetros, aunque apuntan a rutas distintas.
- La mejor puntuación automática es C15: embedding `qwen3-embedding:4b-q4_K_M` de 2.560 dimensiones, RAG 8.192, Ollama 16.384, `top_k=8`, pool 24 y score mínimo 0.0. Obtuvo **86,285% E2E**, con 1.000/1.000 outputs exitosos.
- La mejor corrida 0.6B es C19, con **85,852%**. La diferencia pareada C15−C19 es **+0,433 puntos porcentuales**, IC95% **[+0,110; +0,756]**, sobre los mismos 1.000 casos.
- La evidencia es un proxy automático de alineación factual con hechos extraídos; no es accuracy jurídica. Persona/cargo no tiene referencia automática suficiente y queda sin puntuar. Hace falta adjudicación humana sobre los ocho campos y hechos atómicos TP/FP/FN antes de promover una configuración.

## Qué existe y qué no existe en este checkout

| Artefacto | Estado verificable |
|---|---|
| `inputs-manifest.json` | Presente; JSON con 1.000 registros, seed 20260812, 0 fallos y 1.000 `PASS`. |
| `run-catalog.json` | Presente; catálogo JSON v1 con 19 corridas y sus parámetros efectivos. |
| `results/benchmark-summary.json` | Presente; JSON v2 con métricas agregadas, calidad de datos e intervalos pareados. |
| `results/benchmark-summary.csv` | Presente; 19 filas, una por corrida. |
| `results/benchmark-case-metrics.csv` | Presente; 19.000 filas, una por corrida y caso. |
| `report/artifact.json`, HTML, PDF, PNG y `BENCHMARK_DECISION.md` | Presentes; el artefacto reporta generación `2026-08-21T21:23:00-03:00` y usa el CSV de resumen y el catálogo como fuentes. |
| PDFs del holdout, caché factual JSONL, prompts individuales y `cases/case-NNNN.json` | **No presentes** en el checkout. Las rutas de outputs y del caché son externas según [REPRODUCE.md](../benchmarks/holdout-1000/REPRODUCE.md). |
| `config.yml` por corrida | **No presente**. Solo existe la plantilla [run-manifest.example.yml](../benchmarks/run-manifest.example.yml). |

Por tanto, las cifras consolidadas, joins y hashes publicados pueden auditarse contra los JSON/CSV versionados; no es posible volver a ejecutar aquí la evaluación ni comprobar de forma independiente los bytes de los PDFs, el caché factual, el contenido de los prompts, los outputs brutos o la exclusión física del holdout del índice.

## Inputs y contratos JSON

### Manifiesto de prompts

[`inputs-manifest.json`](../benchmarks/holdout-1000/inputs-manifest.json) tiene estas propiedades de nivel superior: `version=holdout-prompt-v2`, `seed=20260812`, `generation_method="GPT-5.6-designed deterministic factual extraction and prompt template"`, `source_prompts_preserved=true`, `count=1000`, `failures=0`, `quality.pass=1000` y `quality.review=0`. Cada registro contiene `case_id` (`HOLDOUT-0001`…`HOLDOUT-1000`), `prompt_file`, PDF de referencia, SHA-256, páginas, caracteres extraídos, identificador objetivo redactado, organismo, objeto, cantidad de hechos, requisitos operativos y `quality_status`.

El JSON no contiene el texto de cada prompt ni los bytes de los PDFs. El primer registro es `200924.pdf`, 3 páginas, SHA-256 `e571a5144894ba01f211ed5a4bb2bbfbaed055d4a4e10b6c5aa3fb12a97f54d1`; el último es `427875.pdf`, 1 página, SHA-256 `c9cdb2d215790716880bf7eb87c0737fa887e166158b0566a6ae5b0e47a517e5`. El SHA-256 del manifiesto publicado en [REPRODUCE.md](../benchmarks/holdout-1000/REPRODUCE.md) es `26b72644e00ee44aff6fcb492aed616d6d4a438b44ed6d5abed3c5541697a930`, consistente con el archivo local.

### Catálogo de corridas

[`run-catalog.json`](../benchmarks/holdout-1000/run-catalog.json) declara `schema_version=legal-ai-benchmark-run-catalog.v1`, `expected_cases=1000`, `prompt_version=holdout-prompt-v2`, `prompt_seed=20260812` y modelo generativo `qwen3.6:35b`. En cada corrida registra embedding, dimensiones, contexto RAG, contexto Ollama, `top_k`, pool, `minimum_score`, bloque experimental y una ruta externa `path`.

| Caso | Bloque | Embedding | Dim. | RAG | Ollama | top_k | pool | score min |
|---|---|---|---:|---:|---:|---:|---:|---:|
| C01 | base | 4B q4_K_M | 2560 | 2048 | 8192 | 8 | 24 | 0.00 |
| C02 | base | 4B q4_K_M | 2560 | 4096 | 16384 | 8 | 24 | 0.00 |
| C03 | base | 4B q4_K_M | 2560 | 8192 | 32768 | 8 | 24 | 0.00 |
| C04 | retrieval_profile | 4B q4_K_M | 2560 | 4096 | 16384 | 5 | 15 | 0.65 |
| C05 | retrieval_profile | 0.6B | 1024 | 2048 | 8192 | 8 | 24 | 0.00 |
| C06 | retrieval_profile | 0.6B | 1024 | 2048 | 8192 | 5 | 15 | 0.65 |
| C07 | retrieval_profile | 0.6B | 1024 | 3072 | 16384 | 12 | 36 | 0.00 |
| C08 | retrieval_profile | 0.6B | 1024 | 2048 | 8192 | 8 | 40 | 0.55 |
| C09 | retrieval_profile | 0.6B | 1024 | 1536 | 8192 | 3 | 12 | 0.60 |
| C10 | A_ollama | 4B q4_K_M | 2560 | 2048 | 16384 | 8 | 24 | 0.00 |
| C11 | A_ollama | 4B q4_K_M | 2560 | 2048 | 32768 | 8 | 24 | 0.00 |
| C12 | A_ollama | 0.6B | 1024 | 2048 | 16384 | 8 | 24 | 0.00 |
| C13 | A_ollama | 0.6B | 1024 | 2048 | 32768 | 8 | 24 | 0.00 |
| C14 | B_rag | 4B q4_K_M | 2560 | 4096 | 16384 | 8 | 24 | 0.00 |
| C15 | B_rag | 4B q4_K_M | 2560 | 8192 | 16384 | 8 | 24 | 0.00 |
| C16 | B_rag | 4B q4_K_M | 2560 | 16384 | 16384 | 8 | 24 | 0.00 |
| C17 | B_rag | 0.6B | 1024 | 4096 | 32768 | 8 | 24 | 0.00 |
| C18 | B_rag | 0.6B | 1024 | 8192 | 32768 | 8 | 24 | 0.00 |
| C19 | B_rag | 0.6B | 1024 | 16384 | 32768 | 8 | 24 | 0.00 |

Las rutas externas efectivamente catalogadas son: C01 `archive/20260818-superseded-and-diagnostics/benchmark-1000-8192-v3`; C02 `benchmark-1000-4096-v2`; C03 `benchmark-1000-8192-v4`; C04 `benchmark-1000-precision-v1`; C05 `benchmark-1000-06b-balanced`; C06 `benchmark-1000-06b-precision`; C07 `benchmark-1000-06b-recall`; C08 `benchmark-1000-06b-diverse`; C09 `benchmark-1000-06b-compact`; C10 `benchmark-sensitivity-s4b-a2-ollama16384-rag2048`; C11 `benchmark-sensitivity-s4b-a3-ollama32768-rag2048`; C12 `benchmark-sensitivity-v2-s06b-a2-ollama16384-rag2048`; C13 `benchmark-sensitivity-v2-s06b-a3-ollama32768-rag2048`; C14 `benchmark-sensitivity-v2-s4b-b1-ollama16384-rag4096`; C15 `benchmark-sensitivity-v2-s4b-b2-ollama16384-rag8192`; C16 `benchmark-sensitivity-v2-s4b-b3-ollama16384-rag16384`; C17 `benchmark-sensitivity-v2-s06b-b1-rag4096-ollama32768`; C18 `benchmark-sensitivity-v2-s06b-b2-rag8192-ollama32768`; C19 `benchmark-sensitivity-v2-s06b-b3-rag16384-ollama32768`.

La réplica C02/C14 efectivamente conserva la misma tupla `4B/2560/RAG4096/Ollama16384/top_k8/pool24/score0`; sus resultados son muy próximos pero no idénticos. El catálogo no registra por corrida temperatura, `top_p`, versión de Ollama, digest de imagen/modelo, commit exacto, retries o concurrencia; el propio [REPRODUCE.md](../benchmarks/holdout-1000/REPRODUCE.md) califica la reconstrucción bit a bit como incompleta.

## Cobertura y estado de outputs

El recuento de [`benchmark-case-metrics.csv`](../benchmarks/holdout-1000/results/benchmark-case-metrics.csv) coincide con el resumen: 19.000 filas esperadas, **18.103 outputs encontrados**, **17.995 `SUCCEEDED`**, **108 `FAILED`**, **897 `MISSING`** y **0 `INVALID_REFERENCE_JOIN`**. Los fallos son 106 `RAG_INSUFFICIENT_EVIDENCE` y 2 `RAG_OUTPUT_INVALID`.

| Caso | Encontrados | Succeeded | Failed | Missing | Accuracy E2E | Precision | Recall | ¿Rankea? |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| C01 | 1000 | 1000 | 0 | 0 | 86.049% | 43.339% | 56.712% | sí, 6 |
| C02 | 1000 | 1000 | 0 | 0 | 86.054% | 42.614% | 56.621% | sí, 4 |
| C03 | 1000 | 1000 | 0 | 0 | 86.051% | 42.503% | 56.803% | sí, 5 |
| C04 | 1000 | 984 | 16 | 0 | 84.597% | 43.263% | 56.232% | sí, 17 |
| C05 | 1000 | 1000 | 0 | 0 | 85.646% | 44.887% | 55.764% | sí, 13 |
| C06 | 1000 | 914 | 86 | 0 | 78.579% | 45.670% | 51.994% | sí, 18 |
| C07 | 1000 | 999 | 1 | 0 | 85.694% | 44.466% | 55.581% | sí, 12 |
| C08 | 1000 | 997 | 3 | 0 | 85.457% | 44.719% | 55.535% | sí, 16 |
| C09 | 103 | 101 | 2 | 897 | 8.778% | 53.890% | 6.489% | no |
| C10 | 1000 | 1000 | 0 | 0 | 85.954% | 43.012% | 56.643% | sí, 8 |
| C11 | 1000 | 1000 | 0 | 0 | 86.009% | 43.381% | 56.792% | sí, 7 |
| C12 | 1000 | 1000 | 0 | 0 | 85.642% | 44.695% | 55.684% | sí, 14 |
| C13 | 1000 | 1000 | 0 | 0 | 85.485% | 44.701% | 55.558% | sí, 15 |
| C14 | 1000 | 1000 | 0 | 0 | 86.055% | 42.886% | 56.643% | sí, 3 |
| C15 | 1000 | 1000 | 0 | 0 | **86.285%** | 42.942% | 57.100% | sí, 1 |
| C16 | 1000 | 1000 | 0 | 0 | 86.091% | 42.617% | 56.975% | sí, 2 |
| C17 | 1000 | 1000 | 0 | 0 | 85.798% | 44.023% | 56.038% | sí, 10 |
| C18 | 1000 | 1000 | 0 | 0 | 85.775% | 44.285% | 55.947% | sí, 11 |
| C19 | 1000 | 1000 | 0 | 0 | **85.852%** | 44.302% | 55.958% | sí, 9 |

C09 tiene exactamente los casos 1–103 presentes; 104–1000 están ausentes. C04 tuvo 16 `RAG_INSUFFICIENT_EVIDENCE`; C06, 86; C07, un `RAG_OUTPUT_INVALID`; C08, dos `RAG_INSUFFICIENT_EVIDENCE` y un `RAG_OUTPUT_INVALID`; C09, dos `RAG_INSUFFICIENT_EVIDENCE`.

**Importante sobre “full”.** El código no define `comparable_full_run` como “1.000 éxitos”: lo define como conjunto de números de caso completo y cero joins inválidos (`set(cases)==1..1000 && invalid_joins==0`). Por eso C04, C06, C07 y C08 rankean aunque tengan fallos; sus fallos entran como cero en Accuracy E2E. C09 es la única corrida excluida porque solo tiene 103 archivos.

## Joins y controles realmente aplicados

El flujo del evaluador [`tools/evaluate_decree_factual_fidelity.py`](../../tools/evaluate_decree_factual_fidelity.py) es:

1. Carga el caché factual JSONL y exige PDF y SHA-256 no vacíos, sin PDF duplicado ni hash duplicado; después exige exactamente 1.000 referencias.
2. Carga el manifiesto y exige 1.000 registros, `HOLDOUT-####` únicos dentro de 1..1000, y que exista cada `prompt_file` en el directorio externo de prompts. Calcula `prompt_sha256` del texto leído.
3. Carga cada corrida desde `path/cases/case-*.json`; exige que el número del nombre `case-NNNN.json` coincida con `case_number`, sea único y esté en 1..1000.
4. Para cada caso cruza manifiesto y caché por PDF y SHA-256. El output solo se acepta si coincide exactamente en `reference_pdf`, `reference_sha256` y prompt (`_case_prompt(record).strip()`). Un mismatch se marca `INVALID_REFERENCE_JOIN` y no se puntúa.
5. En este dataset se observan 0 joins inválidos. La exclusión del holdout del índice y la igualdad de los PDFs con sus bytes no pueden verificarse desde este checkout porque esos insumos son externos.

Hay dos límites de este control que conviene conservar explícitos: el evaluador no compara un posible `case_id` dentro del JSON de output con el `case_id` del catálogo (el run se identifica por la carpeta/ruta del catálogo), y no valida contra bytes de PDF locales; valida contra el caché factual y su SHA publicado. Tampoco hay configs por corrida locales que permitan confirmar parámetros no incluidos en el catálogo.

## Cálculo de métricas

### Accuracy proxy

- El esquema tiene ocho campos: `organismo`, `objeto`, `persona_cargo`, `dependencia`, `fecha_plazo_vigencia`, `normas_citadas`, `articulos_resolutivos` y `datos_criticos`.
- Para cada campo, el caché ofrece candidatos. Se deduplican y se descartan ruido; solo se conservan hechos con `token_recall >= 0,42` contra el prompt. El prompt es una máscara de divulgación, no la verdad de referencia.
- Los tokens se normalizan, excluyen stopwords y términos de longitud menor o igual a 2. La cobertura de un hecho es el solapamiento multiconjunto de tokens dividido por los tokens esperados.
- Si el hecho contiene un claim tipado, su score es `0,65 × cobertura_tokens + 0,35 × recall_claims`; de lo contrario queda solo la cobertura de tokens. Se promedian los hechos de cada campo y luego, con igual peso, los campos aplicables.
- `factual_fidelity_conditional` promedia solo filas `SUCCEEDED`. `factual_fidelity_e2e` promedia las 1.000 filas, con faltantes y fallos inicializados en cero. La razón de que C09 pase de 86,906% condicional a 8,778% E2E es precisamente esa penalización.
- El caché actual no produce hechos aplicables de `persona_cargo`: su valor es `null` en las 19 filas de resumen. Hay 232 outputs exitosos con cero claims materiales tipados; contribuyen a Accuracy de campos, pero no al denominador agregado de Recall material.

### Precision, Recall y F1 materiales

El extractor implementado reconoce, por expresiones regulares, cinco familias tipadas: normas `Decreto/Ley/Resolución/Decisión Administrativa`, fechas en texto o numéricas, duraciones en días/meses/años, identificadores de `Expediente` y `artículo` con inciso opcional. Los claims se normalizan y se comparan como conjuntos:

```text
TP = referencia ∩ candidato
FP = candidato − referencia
FN = referencia − candidato
Precision = TP / (TP + FP)
Recall = TP / (TP + FN)
F1 = 2 × Precision × Recall / (Precision + Recall)
```

Para faltantes y fallos, el evaluator crea `candidate_claims=0` y suma todos los claims de referencia como FN. Los agregados publicados son por corrida, no un promedio simple de los porcentajes por caso. Esto mide identificadores tipados; una invención semántica fuera de esas regex puede escapar.

### Intervalos, ranking y latencia

- El ranking incluye corridas `comparable_full_run`, ordena `factual_fidelity_e2e` descendente, luego `material_f1` descendente y luego `case_id`.
- Los deltas contra C15 usan las 1.000 filas alineadas por número de caso, incluida la penalización E2E, y `media ± 1,96 × sd / √1000` (aproximación normal pareada). Los intervalos publicados para C15 frente a C01, C02, C03, C14 y C16 contienen cero; por eso forman una meseta estadística alrededor de 86%.
- Los campos `fidelity_ci95_low/high` de cada resumen individual se calculan sobre `fidelity_values` de outputs exitosos, no sobre los faltantes/fallos E2E. No deben interpretarse como IC del E2E cuando una corrida tiene fallos; los intervalos `pairwise_to_best` sí usan las 1.000 diferencias E2E.
- `latency_p50_ms` y `latency_p95_ms` se calculan desde `total_ms` solo de outputs exitosos. No hay latencia local recomputable sin los JSON brutos.

## Reporte y consistencia interna

El [summary JSON](../benchmarks/holdout-1000/results/benchmark-summary.json), el CSV de resumen y el CSV por caso son internamente consistentes en conteos: 19, 19.000, 18.103, 17.995, 108, 897 y 0 joins inválidos. El `artifact.json` declara `accessIssues=[]`, toma el CSV como fuente de `benchmark_summary` y el catálogo como fuente de parámetros, y el HTML/PDF/PNG son derivados de ese artefacto. `BENCHMARK_DECISION.md` redondea las cifras del JSON (por ejemplo C15 86,29%) sin cambiar el orden ni la decisión.

La recomendación técnica coincide con los datos: C15 es el máximo puntual; C19 es el máximo 0.6B; C05 tiene mejor Precision/F1 material que C15 pero menor Accuracy E2E. Ninguna de estas métricas es gold jurídico humano.

## Reproducibilidad y pendientes concretos

Para cerrar la auditoría reproducible faltan, por cada run, `config.yml` efectivo con commit, modelo/digest, temperatura, `top_p`, versión de Ollama, retries/concurrencia y demás campos de la plantilla; además del bundle o acceso durable a prompts, PDFs, caché factual, outputs brutos y evidencia de índices aislados. El hash publicado del caché factual externo es `6b477c37c21219fdf45e1f1946e59a609a232b7872825d1dc71c3d8575f96d61`.

La siguiente etapa debe ser una muestra estratificada con revisión humana de C15, C19, C05 y una línea base 4B, puntuando organismo, objeto, persona/cargo, dependencia, fecha/plazo/vigencia, normas, artículos y datos críticos, además de TP/FP/FN y acuerdo entre revisores. Hasta contar con esa adjudicación, C15 queda documentada como **candidata técnica provisional**, no como configuración jurídicamente validada.
