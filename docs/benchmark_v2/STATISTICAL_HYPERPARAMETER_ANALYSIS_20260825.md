# Benchmark V2 — análisis estadístico de hiperparámetros

Fecha de corte: 2026-08-25. Este análisis usa exclusivamente los outputs V2 ya guardados. No se generaron casos nuevos, no se reejecutó el evaluador y no se modificó ninguna regla.

## Resultado ejecutivo

La unidad inferencial correcta es la configuración de hiperparámetros, no la carpeta física. Hay 17 artefactos `PRIMARY_FULL_1000`, pero 16 `config_hash` únicos: C02 y C14 son dos outputs de la misma configuración, con distinto `output_hash` y `seed=NOT_RECORDED`. Por eso C02 es el representante canónico seleccionado para la inferencia principal y C14 queda en el apéndice de reproducibilidad como `CANDIDATE_REPLICATE_WITH_UNKNOWN_SEED`, no como réplica experimental controlada.

**BEST OBSERVED:** C12 (`0.6B`, RAG 2048, Ollama 16384, `top_k=8`, pool 24, threshold 0.00).

- LegalPass: **9.0%** (90/1000), IC95% Wilson **[7.4%, 10.9%]**.
- Fue estadísticamente superior sólo a C03 luego de Holm: Δ **+3.1 pp**, McNemar exacto `p=0.000194`, Holm `p=0.0233`.
- No fue estadísticamente distinguible de las otras 14 configuraciones. Esto no prueba equivalencia; indica que el contraste pareado no separó sus tasas al nivel ajustado.
- C12 es Pareto-óptima en el escenario canónico C02; el frente Pareto cambia bajo el sensitivity check C14 porque ese mismo `config_hash` tiene outputs distintos.

**Recomendación de producción:** C12 es el mejor candidato observado para continuar la experimentación y para un eventual uso asistido human-in-the-loop. Con LegalPass de 9.0%, no se recomienda generación autónoma de decretos: la revisión jurídica humana debe ser obligatoria. C05/C08 se conservan como alternativas de costo/error. No declarar una superioridad causal universal: la única diferencia LegalPass significativa, C03 vs C12, está confounded por embedding, RAG y Ollama simultáneamente.

## Datos y congelamientos

- Fuente: `calibrated-legal-core-2-final`, 1.000 casos por representante y emparejamiento por el mismo `case_id`.
- Evaluador: `benchmark-v2-legal-core-2-calibrated`.
- Reglas: `typed-critical-v2-template-aware`.
- `evaluator_hash`: `13644bdc6bc0761d6d22b59dff5c4013132442d8ec56c3258075f524b0893166` para los representantes primarios.
- Retrieval: `SourceFaithfulness` y `AEC@k` quedan como `NOT_RECONSTRUCTABLE` porque no existe el texto histórico de los chunks. No bloquean LegalPass, claims, campos, contradicciones, omisiones ni adiciones.
- `Legal Precision` no está registrada como métrica independiente; se deja `NOT_RECORDED` y no se inventa un proxy.
- Orca se usó para aislamiento/orquestación de pods y worktrees; OpenCode se ejecutó directamente por el fallo de permisos del launcher de Orca. El reporte no afirma que Orca haya ejecutado los procesos.

## Tabla compacta de las 16 configuraciones únicas FULL

| Run | Embedding | RAG ctx | Ollama ctx | top_k | Pool | Threshold | Casos |
|---|---:|---:|---:|---:|---:|---:|---:|
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
| C15 | 4B | 8192 | 16384 | 8 | 24 | 0.00 | 1000 |
| C16 | 4B | 16384 | 16384 | 8 | 24 | 0.00 | 1000 |
| C17 | 0.6B | 4096 | 32768 | 8 | 24 | 0.00 | 1000 |
| C18 | 0.6B | 8192 | 32768 | 8 | 24 | 0.00 | 1000 |
| C19 | 0.6B | 16384 | 32768 | 8 | 24 | 0.00 | 1000 |

El `model` generador es `qwen3.6:35b` en las filas FULL. `embedding_context`, `chunk_size`, `chunk_overlap`, `temperature` y `seed` no están registrados en el inventario; no se imputan ni se analizan.

## Ranking principal

Las tasas de error son tasas críticas: menor es mejor. `Fields` es `critical_fields.all_correct`; no es Legal Precision.

| Rank | Run | LegalPass [IC95%] | Claims Recall | Fields | Omisiones | Contradicciones | Adiciones | Tier | Pareto |
|---:|---|---:|---:|---:|---:|---:|---:|---:|:---:|
| 1 | C12 | 9.0% [7.4, 10.9] | 87.369% | 18.3% | 79.0% | 18.8% | 43.8% | 1 | Sí |
| 2 | C08 | 8.9% [7.3, 10.8] | 87.076% | 18.3% | 78.7% | 17.9% | 41.7% | 1 | Sí |
| 3 | C05 | 8.7% [7.1, 10.6] | 87.396% | 18.6% | 78.0% | 17.6% | 41.8% | 1 | Sí |
| 4 | C13 | 8.5% [6.9, 10.4] | 87.201% | 17.9% | 79.2% | 17.4% | 41.8% | 1 | Sí |
| 5 | C18 | 8.3% [6.7, 10.2] | 87.465% | 17.3% | 79.0% | 18.7% | 44.2% | 1 | Sí |
| 6 | C07 | 8.3% [6.7, 10.2] | 87.181% | 18.0% | 78.7% | 18.8% | 43.5% | 1 | No |
| 7 | C19 | 8.0% [6.5, 9.8] | 87.739% | 18.1% | 79.1% | 17.9% | 46.4% | 1 | Sí |
| 8 | C06 | 7.7% [6.2, 9.5] | 80.060% | 15.4% | 81.9% | 15.1% | 36.7% | 1 | Sí |
| 9 | C17 | 7.6% [6.1, 9.4] | 87.329% | 17.9% | 78.7% | 18.3% | 46.0% | 1 | No |
| 10 | C04 | 7.0% [5.6, 8.8] | 86.199% | 17.5% | 79.9% | 18.6% | 49.6% | 1 | No |
| 11 | C11 | 6.9% [5.5, 8.6] | 87.544% | 17.9% | 78.9% | 18.9% | 52.3% | 1 | Sí |
| 12 | C15 | 6.7% [5.3, 8.4] | 87.345% | 18.0% | 78.7% | 18.6% | 54.5% | 1 | No |
| 13 | C10 | 6.7% [5.3, 8.4] | 87.330% | 17.6% | 79.2% | 19.1% | 53.5% | 1 | No |
| 14 | C02 | 6.2% [4.9, 7.9] | 87.295% | 18.8% | 77.9% | 19.3% | 56.2% | 1 | Sí |
| 15 | C16 | 6.1% [4.8, 7.8] | 87.442% | 18.3% | 78.3% | 19.3% | 56.7% | 1 | Sí |
| 16 | C03 | 5.9% [4.6, 7.5] | 87.275% | 18.0% | 79.1% | 19.1% | 55.9% | 2 | No |

## Métodos estadísticos

Para cada configuración:

`LegalPassRate = Σ LegalPass_i / n`, con `n=1000`.

El IC95% individual es Wilson:

`(p + z²/(2n) ± z·sqrt(p(1-p)/n + z²/(4n²))) / (1 + z²/n)`, con `z=1.959964`.

Para Cxx vs Cyy se usaron exactamente los mismos `case_id`. LegalPass es binario y pareado: McNemar exacto bilateral, con `b = A pasa/B falla`, `c = A falla/B pasa`, `Δpp = 100·(p_B-p_A)`. Se aplicó Holm a las 120 comparaciones (`16·15/2`).

Para Claims Recall y las métricas continuas se usó bootstrap pareado por caso, 10.000 remuestras, percentiles 2.5/97.5%, semilla reproducible, más Wilcoxon signed-rank y Cohen `d_z`. Para `critical_fields_score`, `critical_contradiction_free`, `critical_omission_free` y `unsupported_addition_free`, que son variables binarias por decreto, el test primario es McNemar exacto; bootstrap/Wilcoxon/Cohen quedan como análisis complementarios. Holm se aplicó dentro de cada familia de parámetro modificado. Los `p=0.0000` del bootstrap significan que ninguna remuestra cruzó cero; con 10.000 remuestras se reportan como límite Monte Carlo, no como probabilidad matemática exactamente cero.

La agrupación Tier 1 significa “no distinguible del mejor tras Holm”; no significa equivalencia ni igualdad de distribución. La frontera de Pareto es descriptiva sobre LegalPass, Claims Recall, Prompt Coverage, campos correctos y tasas libres de errores críticos.

## Contrastes controlados e identificabilidad

Sólo se conservaron pares donde cambia exactamente un parámetro entre `embedding_model`, `rag_context`, `ollama_context`, `top_k`, `pool` y `threshold`. Hubo 21 pares controlados: 3 de embedding, 13 de RAG y 5 de Ollama. No hubo pares aislados para `top_k`, `pool` o `threshold`; esos efectos no son identificables en la grilla actual.

El resultado más consistente aparece en `unsupported_addition_free` al comparar 0.6B contra 4B con los otros parámetros controlados. Como es binaria y pareada, se usa McNemar exacto bilateral:

| Par | Cambio | b | c | Δ free-additions | IC Wilson A/B | raw p | Holm p |
|---|---|---:|---:|---:|---:|
| C03 → C18 | 4B → 0.6B | 98 | 215 | +11.7 pp | [41.1,47.2] / [52.7,58.9] | 3.27e-11 | 6.86e-10 |
| C10 → C12 | 4B → 0.6B | 115 | 212 | +9.7 pp | [43.4,49.6] / [53.1,59.2] | 8.95e-08 | 1.70e-06 |
| C11 → C13 | 4B → 0.6B | 111 | 216 | +10.5 pp | [44.6,50.8] / [55.1,61.2] | 6.63e-09 | 1.33e-07 |

Los tres contrastes permanecen significativos con McNemar exacto y Holm dentro de la familia embedding. En los tres contrastes controlados disponibles, el embedding 0.6B estuvo asociado con una reducción de adiciones críticas no soportadas de aproximadamente 9.7–11.7 puntos porcentuales. Esto no demuestra que 0.6B sea universalmente superior ni demuestra un efecto causal general sobre LegalPass.

Para RAG y Ollama no hubo efectos continuos significativos después de Holm en las familias controladas. En RAG, por ejemplo, el delta mediano de Claims Recall fue aproximadamente +0.136 pp entre los pares en la orientación guardada, sin evidencia ajustada de un efecto consistente. La falta de pares aislados impide atribuir efectos a `top_k`, pool o threshold.

La comparación LegalPass C03 vs C12 fue significativa pero confounded: cambia simultáneamente embedding 4B→0.6B, RAG 8192→2048 y Ollama 32768→16384. Por lo tanto no se presenta como un efecto causal de un solo hiperparámetro.

## Metodología matemática formal

### LegalPass y CriticalErrorRate

Para el decreto `i` y la configuración `c`:

`Yᵢc^pass = 1` si pasa todos los controles críticos; `0` en otro caso.

`p̂_c = (1/N) · Σᵢ Yᵢc^pass`, con `N=1000`.

`CriticalErrorRate_c = 1 − p̂_c`.

Ejemplo C12: `90/1000 = 0.09 = 9.0%`; por lo tanto `CriticalErrorRate = 91.0%`. Esto significa que el 91% incumplió al menos una condición crítica del evaluador V2; no significa que el 91% sea completamente inútil.

### Intervalo Wilson

Para una proporción binaria, con `z=1.959964` para 95%:

`CI_Wilson = [p̂ + z²/(2n) ± z·√(p̂(1−p̂)/n + z²/(4n²))] / [1 + z²/n]`.

Mide la incertidumbre de una tasa binaria sin usar la aproximación normal simple. Para C12, el resultado es **[7.4%, 10.9%]**.

### Diferencia absoluta

Para A y B:

`Δ_A,B = p̂_A − p̂_B`, expresada en puntos porcentuales (`pp`).

Ejemplo: C12 `9.0%` frente a C03 `5.9%` da `Δ=+3.1 pp`. En los CSV de pares la orientación se guarda como `delta_pp_b_minus_a`; el signo se interpreta siempre junto con `config_a` y `config_b`.

### McNemar exacto

Para outcomes binarios pareados:

| | B PASS | B FAIL |
|---|---:|---:|
| A PASS | n11 | b |
| A FAIL | c | n00 |

`b = A pasa y B falla`; `c = A falla y B pasa`. La hipótesis nula es `H₀: b=c`, es decir, igual probabilidad de ganar en los casos discordantes. La aproximación clásica es `χ²=(b−c)²/(b+c)`, pero el benchmark usa el test exacto bilateral basado en `X~Binomial(b+c,0.5)`.

Ejemplo C12 vs C03: `b=49`, `c=18`, `Δ=+3.1 pp`, `raw p=0.000194`, `Holm p=0.0233`.

`unsupported_addition_free` pertenece a `{0,1}` por decreto. Por eso su inferencia principal —incluidos los tres contrasts de embedding— es McNemar exacto, no Wilcoxon ni Cohen `d_z`.

### Bootstrap pareado

Para una métrica continua, `d_i=Y_iA−Y_iB` y `d̄=(1/N)Σᵢd_i`. En cada una de las 10.000 remuestras pareadas:

`Δ*(r) = (1/N) Σᵢ∈Sᵣ (Y_iA−Y_iB)`.

El IC es `[Q₀.₀₂₅(Δ*), Q₀.₉₇₅(Δ*)]`. Si cruza cero, no hay diferencia estadísticamente demostrable para esa métrica bajo ese contraste. Se usó para Claims Recall y como análisis complementario de las flags binarias.

### Wilcoxon signed-rank

Para `d_i=X_i−Y_i`, se eliminan ceros, se rankea `|d_i|` y se calculan `W⁺=Σ rank(|d_i|)·I(d_i>0)` y `W⁻=Σ rank(|d_i|)·I(d_i<0)`. La hipótesis nula es que la distribución de diferencias está centrada en cero. Se reporta sólo para métricas continuas/ordinales apropiadas; no es el test principal de outcomes binarios.

### Cohen `d_z`

`d_z=d̄/s_d`, donde `s_d=√[Σᵢ(d_i−d̄)²/(N−1)]`. Mide el tamaño de efecto estandarizado de diferencias pareadas continuas. No se usa como tamaño de efecto principal para `unsupported_addition_free` ni otras flags binarias.

### Holm-Bonferroni

Ordenados `p_(1)≤…≤p_(m)`, se comparan con `α/(m−k+1)`, `α=0.05`, preservando la monotonía de los p ajustados. La decisión reportada es `Holm adjusted p < 0.05`, no `raw p < 0.05`. LegalPass usa una familia de 120 pares; los contrasts continuos/binaries usan la familia del parámetro controlado.

### Cohen κ para C02/C14

`κ=(p_o−p_e)/(1−p_e)`, con `p_o=(n11+n00)/N` y `p_e` obtenido de las marginales. Para C02/C14: acuerdo observado **96.4%** y `κ=0.708`. El acuerdo bruto puede ser alto y κ menor por el desbalance PASS/FAIL.

### Spearman V1 vs V2

`ρ_s=Corr(rank(X),rank(Y))`; sin empates también `ρ_s=1−6Σd_i²/[n(n²−1)]`. El resultado primario es `ρ=-0.733`, una asociación monotónica inversa descriptiva entre el proxy histórico y LegalPass V2, no una relación causal ni prueba de que V1 sea matemáticamente incorrecto.

### Dominancia de Pareto y tiers

Se usa el vector descriptivo `f(c)=(LegalPass, ClaimsRecall, PromptCoverage, FieldsCorrect, −Contradictions, −Omissions, −Additions)`. A domina B si `f_j(A)≥f_j(B)` para todo `j` y es estrictamente mayor en al menos un componente. Pareto-óptima no significa estadísticamente mejor.

Tier 1 significa “no distinguible del BEST OBSERVED después de Holm”. No significa equivalencia; para equivalencia haría falta un margen y un test de equivalencia predefinidos, que no forman parte de este diseño.

## Sensitivity check C02/C14

Se recalculó sólo la capa estadística con dos escenarios: A selecciona C02 como representante canónico; B selecciona C14 para el mismo `config_hash`. C14 sigue siendo `CANDIDATE_REPLICATE_WITH_UNKNOWN_SEED`, no una réplica controlada.

Resultado: **CHANGED**, pero el cambio está acotado a resultados descriptivos del representante.

- BEST OBSERVED: **no cambia**, continúa C12 con 9.0%.
- Tiers: **no cambian**; C03 permanece como único miembro de Tier 2.
- Significancia LegalPass: **no cambia**; queda sólo C03 vs C12 tras Holm.
- Significancia de los tres contrasts de embedding y conclusión RAG/Ollama: **no cambian**.
- Ranking descriptivo: el `config_hash` C02/C14 pasa de rank 14 a rank 10; los ranks cercanos se desplazan.
- Pareto: **sí cambia**; el `config_hash` C02/C14 deja de estar en el frente cuando se usa C14.
- Recomendación: **no cambia**; C12 sigue siendo candidato para uso asistido, nunca para generación autónoma.
- V1 vs V2: el escenario A conserva `ρ=-0.733`; el escenario B da `ρ=-0.707` porque cambia la tasa V2 del mismo config hash. No cambia la interpretación de mismatch descriptivo.

La conclusión correcta es, por lo tanto, que la inferencia principal es robusta en BEST OBSERVED, tiers, significancias y recomendación, pero el frente Pareto y la posición descriptiva del config hash son sensibles al output físico elegido.

## Interpretación de LegalPass y descomposición de fallas

En C12, el `91.0%` de CriticalErrorRate se descompone por combinaciones exactas de flags:

| Patrón exacto | Casos | Porcentaje |
|---|---:|---:|
| Omisión + fields incorrectos | 377 | 37.7% |
| Omisión + adición + fields incorrectos | 258 | 25.8% |
| Omisión + contradicción + fields incorrectos | 65 | 6.5% |
| Omisión + contradicción + adición + fields incorrectos | 90 | 9.0% |
| Adición solamente | 66 | 6.6% |
| Contradicción + adición | 16 | 1.6% |
| Contradicción solamente | 11 | 1.1% |
| Fields incorrectos solamente | 15 | 1.5% |
| Contradicción + fields incorrectos | 4 | 0.4% |
| Adición + fields incorrectos | 6 | 0.6% |
| Sin flag rastreada | 90 | 9.0% |

En C12: omisiones afectan 79.0%, contradicciones 18.8%, adiciones críticas 43.8% y fields incorrectos 81.7%. Las cuatro flags explican los 910 fallos de LegalPass de C12; el patrón sin flag corresponde a sus 90 pases. El CSV también contiene esta descomposición para las 16 configuraciones. Como referencia descriptiva no inferencial, al apilar los 16×1000 registros las tasas de flags son 79.02% omisión, 18.34% contradicción, 47.79% adición y 82.13% fields incorrectos.

La compuerta LegalPass es estricta: fallar una sola condición crítica basta para no pasar. Por eso un 9% de LegalPass no debe traducirse en “91% de decretos completamente inútiles”; sí exige revisión jurídica humana obligatoria.

## Reproducibilidad C02/C14

C02 y C14 comparten `config_hash=30eddf760e02…`, pero tienen `output_hash` distintos y `seed=NOT_RECORDED`. No entran como dos configuraciones en rankings ni p-values.

- LegalPass: C02 **6.2%**, C14 **7.0%**, Δ **+0.8 pp**.
- Acuerdo caso a caso: **96.4%**; Cohen κ **0.708**.
- McNemar exacto: `b=14`, `c=22`, discordantes=36, `p=0.243`.
- Claims Recall: Δ **+0.080 pp**, IC bootstrap **[-0.267, +0.421] pp**, `p=0.6334`.
- No se infiere seed ni se llama a esto una réplica independiente confirmada; es una `CANDIDATE_REPLICATE_WITH_UNKNOWN_SEED`.

## V1 vs V2: comparación secundaria

Se cruzó el summary V1 ya guardado con los mismos labels C02–C19, excluyendo C01 y C09 por no ser configuraciones FULL principales. La correlación de Spearman entre `V1 factual_fidelity_e2e` y LegalPass V2 fue **ρ=-0.733** sobre 16 configuraciones. Esta cifra no es una validación de regresión: V1 y V2 usan definiciones, evaluadores y métricas distintas, y no se debe interpretar como degradación causal.

## Archivos generados

- [statistical_ranking.csv](../../benchmark_v2/results/all-runs-20260825/calibrated-legal-core-2-final/stats/statistical_analysis_corrected/statistical_ranking.csv)
- [legalpass_pairwise_matrix.csv](../../benchmark_v2/results/all-runs-20260825/calibrated-legal-core-2-final/stats/statistical_analysis_corrected/legalpass_pairwise_matrix.csv)
- [hyperparameter_controlled_contrasts.csv](../../benchmark_v2/results/all-runs-20260825/calibrated-legal-core-2-final/stats/statistical_analysis_corrected/hyperparameter_controlled_contrasts.csv)
- [hyperparameter_effect_summary.csv](../../benchmark_v2/results/all-runs-20260825/calibrated-legal-core-2-final/stats/statistical_analysis_corrected/hyperparameter_effect_summary.csv)
- [c02_c14_reproducibility.csv](../../benchmark_v2/results/all-runs-20260825/calibrated-legal-core-2-final/stats/statistical_analysis_corrected/c02_c14_reproducibility.csv)
- [c02_c14_sensitivity_analysis.csv](../../benchmark_v2/results/all-runs-20260825/calibrated-legal-core-2-final/stats/statistical_analysis_corrected/c02_c14_sensitivity_analysis.csv)
- [legalpass_failure_decomposition.csv](../../benchmark_v2/results/all-runs-20260825/calibrated-legal-core-2-final/stats/statistical_analysis_corrected/legalpass_failure_decomposition.csv)
- [identifiability_matrix.csv](../../benchmark_v2/results/all-runs-20260825/calibrated-legal-core-2-final/stats/statistical_analysis_corrected/identifiability_matrix.csv)
- [pareto_front.csv](../../benchmark_v2/results/all-runs-20260825/calibrated-legal-core-2-final/stats/statistical_analysis_corrected/pareto_front.csv)
- [v1_vs_v2.csv](../../benchmark_v2/results/all-runs-20260825/calibrated-legal-core-2-final/stats/statistical_analysis_corrected/v1_vs_v2.csv)
- [analysis_manifest.json](../../benchmark_v2/results/all-runs-20260825/calibrated-legal-core-2-final/stats/statistical_analysis_corrected/analysis_manifest.json)

Figuras:

- [ranking LegalPass](../../benchmark_v2/results/all-runs-20260825/calibrated-legal-core-2-final/stats/statistical_analysis_corrected/figures/legalpass_ranking.svg)
- [matriz pareada](../../benchmark_v2/results/all-runs-20260825/calibrated-legal-core-2-final/stats/statistical_analysis_corrected/figures/legalpass_pairwise_heatmap.svg)
- [efectos controlados](../../benchmark_v2/results/all-runs-20260825/calibrated-legal-core-2-final/stats/statistical_analysis_corrected/figures/controlled_effects.svg)

## Veredicto de validación

**Listo para compartir con caveats.** Las tasas principales, denominadores, emparejamiento por caso, corrección por multiplicidad y exclusión de duplicados/repeticiones están trazados a outputs V2 congelados. Las correcciones de esta revisión fueron exclusivamente estadísticas y documentales: selección canónica C02/C14, test binario McNemar, sensitivity check y descomposición de fallas. Las limitaciones materiales son: no hay Legal Precision independiente, Retrieval no es reconstruible, seed/temperature/chunk settings no están registrados, y varios hiperparámetros están confounded o no tienen contraste aislado. No se ejecutó ningún análisis causal ni se usaron SMOKE, DIAGNOSTIC, PARTIAL o INVALID para la inferencia principal. Con LegalPass=9.0%, el uso recomendado es human-in-the-loop con revisión jurídica obligatoria; no generación autónoma.
