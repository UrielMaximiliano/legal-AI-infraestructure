# Calidad de datos

## Controles superados

- 19 corridas y 19.000 filas esperadas.
- 1.000 casos, PDFs y hashes únicos en el manifiesto.
- Rango de casos exacto 1..1.000, sin duplicados.
- Join estricto por caso + PDF + SHA-256 + prompt.
- 0 joins inválidos.
- Índices aislados: 4B/2.560 y 0.6B/1.024.
- PDFs del holdout excluidos del índice de antecedentes.

## Cobertura observada

| Estado | Cantidad |
|---|---:|
| Esperados | 19.000 |
| Outputs encontrados | 18.103 |
| Exitosos | 17.995 |
| Fallidos | 108 |
| Faltantes | 897 |

C04 tuvo 16 fallos; C06, 86; C07, 1; C08, 3. C09 quedó parcial
(101 éxitos, 2 fallos y 897 faltantes) y no participa del ranking.

## Riesgos de medición

- El caché factual contiene extracción automática y errores de OCR; no
  reemplaza el PDF binario ni una anotación jurídica.
- 232 evaluaciones exitosas no tienen claims materiales tipados de referencia;
  contribuyen a Accuracy de campos, pero no al denominador de Recall material.
- Accuracy mide cobertura de hechos aplicables, no clasificación clásica.
- Precision solo penaliza claims tipados; una entidad inventada fuera de esas
  familias puede escapar al contador de FP.
- C01 proviene de un archivo histórico; se conserva porque comparte manifiesto,
  esquema y joins, pero no se usa como única línea base de producción.

## Regla de uso

Los resultados sirven para seleccionar candidatas. No deben comunicarse como
porcentaje de validez jurídica hasta completar adjudicación humana y acuerdo
entre revisores.
