# Validación adversarial de Benchmark v2

Fecha de la validación: 2026-08-25. La prueba ejecutable está en
[`benchmark_v2/tests/test_validation.py`](../../benchmark_v2/tests/test_validation.py)
y lee únicamente los artefactos versionados de
[`holdout-1000`](../benchmarks/holdout-1000/). No crea PDFs, prompts, cachés,
outputs ni otra evidencia de benchmark. Las mutaciones adversariales son
copias en memoria de filas reales y sólo comprueban que un join alterado sea
rechazado.

## Resultado verificable en este checkout

| Control | Resultado | Evidencia local | Diagnóstico accionable |
|---|---:|---|---|
| Identidad de PDF | 1.000 nombres y 1.000 SHA-256 únicos | `inputs-manifest.json` | Mantener el PDF binario fuera del checkout; antes de publicar una corrida, volver a calcular cada SHA sobre los bytes originales. |
| Hash del manifiesto | `26b72644e00ee44aff6fcb492aed616d6d4a438b44ed6d5abed3c5541697a930` | `inputs-manifest.json` y `data_quality.prompt_manifest_sha256` | Comparar este digest en cada ejecución y bloquear si cambia sin una nueva versión del dataset. |
| Fuga de PDF | Sin PDFs crudos en `holdout-1000`; sólo existe el PDF final del reporte | Árbol local | La ausencia de los PDFs impide demostrar desde este checkout que el índice RAG los excluyó. Ejecutar el control de exclusión en el entorno que materializa el corpus. |
| Prompt | 1.000 `prompt_file` únicos; los CSV sólo conservan `prompt_sha256`, estable entre las 19 corridas | Manifiesto y `benchmark-case-metrics.csv` | Conservar los prompts en un almacén controlado y verificar `sha256(prompt_text)` antes de evaluar; no incluir texto de prompt en resultados o reportes. |
| Joins PDF/hash/prompt | 0 `INVALID_REFERENCE_JOIN` y 0 inconsistencias contra el manifiesto | 19.000 filas de métricas | Tratar cualquier mismatch de nombre, SHA o prompt como no puntuable; no repararlo por posición. |
| Duplicados | Sin duplicados de `case_id`, PDF, SHA, prompt file, corrida ni `(run, case_number)` | Manifiesto, catálogo y métricas | Mantener las claves únicas como aserciones de carga; un duplicado debe abortar la evaluación. |
| Cobertura | 19 corridas × 1.000 filas de caso; C09 tiene 103 outputs y 897 faltantes | Resumen y métricas | Contar `MISSING` como cero E2E y reportar denominadores. No interpretar 103/1.000 como corrida completa. |
| FULL/PARTIAL | 18 corridas comparables; C09 `comparable_full_run=false`, sin ranking | `benchmark-summary.json` | Conservar `quality_rank=null` para parciales y excluirlas del ranking. |
| Schema | `status ∈ {FULL, PARTIAL}`, hashes de 64 hex, campos obligatorios y cardinalidad FULL verificados | `benchmark_v2/configs/schema.json` + runtime validator | Validar el envelope antes de persistirlo y rechazar FULL con cardinalidad incorrecta. |
| Ground truth | El prompt es una máscara de divulgación, no ground truth; métricas legales no adjudicadas por humanos | `benchmark-summary.json` y reporte | No llamar accuracy jurídica a este proxy. Adjudicar una muestra experta de claims, fechas, normas, cargos, jurisdicción y abstenciones antes de una decisión legal. |

## Hallazgos que cambian la interpretación

### 1. No es posible revalidar los bytes externos

El checkout versiona el manifiesto, el catálogo, el resumen y las métricas,
pero no contiene los PDFs fuente, el caché factual, los prompts ni los JSON de
outputs. Por ello la prueba puede demostrar que las referencias versionadas
son únicas y que todos los joins locales son coherentes, pero no puede
demostrar de forma independiente:

- que cada PDF materializado coincide con su `source_sha256`;
- que el texto de cada prompt coincide con `prompt_sha256`;
- que el caché factual se obtuvo exclusivamente de esos PDFs;
- que los PDFs de holdout fueron excluidos físicamente del índice de
  recuperación.

Acción requerida: ejecutar el evaluador en un entorno con permisos sobre esos
insumos, guardar el digest de cada fuente y adjuntar un manifiesto de
materialización (ruta, bytes, SHA-256, versión del corpus y fecha). El hash
publicado del caché (`reference_cache_sha256`) debe recalcularse allí; la
prueba local no inventa una comprobación de bytes ausentes.

### 2. C09 es parcial y queda correctamente separada

Todas las corridas tienen una fila por cada número de caso, incluso cuando el
output falta. La cobertura se calcula sobre outputs encontrados, no sobre el
número de filas del CSV. C09 tiene 103 outputs, 101 éxitos, 2 fallos y 897
faltantes; queda fuera del ranking y mantiene `quality_rank=null`. Las otras 18
corridas cubren 1.000/1.000 casos. En C04, C06, C07 y C08 hay fallos pero la
cobertura es completa: el protocolo actual las conserva como comparables y
asigna cero E2E a los fallos.

Acción requerida: decidir antes del siguiente reporte si “comparable” seguirá
significando cobertura de casos + cero joins inválidos, o si además exigirá un
umbral de éxito. No mezclar ambas definiciones en tablas o conclusiones.

### 3. El proxy no es un conjunto gold jurídico

`reference_claims` y los campos factuales provienen de extracción automática
de PDFs; el prompt sólo selecciona qué información se revela. El summary
declara `NOT_HUMAN_ADJUDICATED`. Esto permite diagnosticar recuperación,
fallos, claims materiales y estabilidad, pero no prueba exactitud jurídica
completa, equivalencia de paráfrasis, vigencia normativa o suficiencia de una
cita.

Acción requerida: congelar un conjunto gold adjudicado por expertos y publicar
por campo la cobertura de claims, precisión de citas, conflictos de autoridad,
abstención y acuerdo interanotador. Mantener el proxy PDF como métrica
diagnóstica, no como sustituto del gold.

### 4. C02 y C14 repiten la misma tupla

El catálogo contiene 19 corridas pero 18 tuplas de parámetros únicas: C02 y
C14 comparten embedding, dimensiones, contextos, `top_k`, pool y score mínimo.
Esto puede servir como réplica de estabilidad, pero no debe contarse como una
comparación independiente de configuración.

Acción requerida: marcar explícitamente las réplicas en el catálogo y, para
inferencias futuras, reportar la unidad experimental y el agrupamiento por
tupla.

## Qué cubre la suite

`test_validation.py` comprueba:

1. nombres y SHA-256 de PDFs sin contenido PDF crudo comprometido;
2. digest del manifiesto y formato de hashes;
3. ausencia de texto de prompts/ground truth en la superficie versionada y
   estabilidad del hash de prompt por caso;
4. rechazo de mutaciones en PDF, SHA y prompt de un join real;
5. unicidad de IDs, archivos, hashes, corridas y filas por caso;
6. joins contra el manifiesto, conteos de `SUCCEEDED`, `FAILED` y `MISSING`, y
   cobertura por corrida;
7. exclusión de C09 del ranking FULL/PARTIAL;
8. campos normativos del JSON Schema y límites de ground truth declarados;
9. enforcement runtime de `FULL`/`PARTIAL` usando IDs de casos reales.

Ejecutar desde la raíz del checkout:

```bash
python -m pytest benchmark_v2/tests/data_contract_test.py benchmark_v2/tests/test_validation.py
```

La prueba falla de manera accionable indicando la corrida, caso y clave del
join afectada; no modifica ningún dato de entrada.
