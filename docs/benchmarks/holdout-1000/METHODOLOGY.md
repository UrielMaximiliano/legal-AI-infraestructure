# Metodología de evaluación

## Unidad experimental

Para cada una de las 19 corridas se esperan los mismos 1.000 pares:

```text
PDF excluido del índice → prompt derivado del PDF → output JSON del RAG
```

El prompt es entrada y máscara de divulgación; no es la respuesta correcta.
La referencia automática es un caché congelado de hechos extraídos del PDF.
Cada caso falla cerrado si no coinciden número de caso, nombre del PDF,
SHA-256 del PDF y contenido del prompt del manifiesto.

## Accuracy proxy extremo a extremo

Se evalúan los campos aplicables disponibles en la referencia: organismo,
objeto, dependencia, fecha/plazo/vigencia, normas citadas, artículos
resolutivos y datos críticos. Persona/cargo no se puntúa automáticamente porque
el caché actual no lo cubre de forma suficiente.

Para cada hecho se calcula cobertura léxica normalizada. Cuando contiene una
afirmación material tipada, el score del hecho es:

```text
score_hecho = 0,65 × cobertura_tokens + 0,35 × recall_claims
score_campo = promedio(score_hecho)
accuracy_caso = promedio(score_campo aplicable)
accuracy_E2E = suma(accuracy_caso; fallos/faltantes=0) / 1.000
```

Los hechos PDF solo se consideran aplicables si fueron revelados en el prompt
(`token_recall ≥ 0,42`). Esto evita exigir número/fecha objetivo, firmas o
boilerplate deliberadamente ocultados. Los pesos y el umbral son reglas
heurísticas aún no calibradas con anotación humana.

## Precision y Recall materiales

Se extraen claims exactos de cinco familias: normas, fechas, plazos,
expedientes y números de artículo.

```text
Precision = TP / (TP + FP)
Recall    = TP / (TP + FN)
```

TP es un identificador correcto, FP uno adicional no respaldado y FN uno
esperado ausente. Los fallos agregan FN; los faltantes se reconstruyen desde el
manifiesto y también agregan FN. Estas métricas no validan el significado del
artículo ni entidades semánticas no tipadas.

## Comparación estadística

Las configuraciones completas se ordenan por Accuracy proxy E2E. El intervalo
de cada delta se calcula sobre las 1.000 diferencias pareadas, usando
aproximación normal al 95%:

```text
IC95%(delta) = media(delta_i) ± 1,96 × sd(delta_i) / √1000
```

Si el intervalo contiene cero, no se declara una diferencia concluyente. C09
queda fuera del ranking porque solo obtuvo 101 éxitos, 2 fallos y 897 faltantes.

## Qué no demuestra

No es accuracy jurídica certificada, no prueba causalmente cuánto aportó el
RAG y no penaliza todas las alucinaciones. La promoción a producción requiere
una muestra estratificada revisada por especialistas sobre los ocho campos y
hechos atómicos TP/FP/FN.
