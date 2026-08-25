# Reglas del evaluador de claims

## Fuente de verdad

El evaluador nunca construye `gold` a partir del output. Cada dimensión debe
recibir una anotación explícita en una lista o en un sobre con las claves
`claims`, `entities` y `contradictions`. También se aceptan los alias
`atomic_claims`, `legal_entities`, `conflicts` y las claves `gold_*`.

Una dimensión ausente, `null` o con ítems inválidos es `NOT_CALCULABLE`; no es
un cero. Una lista vacía es una anotación válida: permite medir que el output
no haya inventado elementos (`FP`).

Ejemplo mínimo de gold:

```json
{
  "claims": [
    {"claim_id": "c1", "subject": "locatario", "predicate": "paga", "object": "renta"}
  ],
  "entities": [
    {"entity_id": "e1", "text": "Ministerio de Justicia", "type": "ORGANIZATION"}
  ],
  "contradictions": [
    {"id": "x1", "claim_a": "c1", "claim_b": "c2", "reason": "valores incompatibles"}
  ]
}
```

## Extracción

* Claims: una frase o cláusula es una unidad atómica; el texto se separa por
  puntuación, saltos de línea y coordinaciones seleccionadas. Un objeto
  estructurado puede declarar `subject`, `predicate`, `object` y `polarity`.
* Entidades: se detectan instrumentos jurídicos (`Ley`, `Decreto`,
  `Resolución`, etc.), expedientes/causas, tribunales, organizaciones y
  personas tituladas. La extracción es una heurística reproducible, no una
  decisión jurídica.
* Contradicciones: se aceptan pares anotados explícitamente. En texto libre se
  proponen pares solo si comparten sujeto y predicado y difieren en objeto o
  polaridad (incluida negación); no se marca como contradicción la mera
  coexistencia de dos frases.

La normalización para comparar quita mayúsculas, acentos y puntuación, y
colapsa espacios. Los identificadores que no vienen en la entrada son hashes
deterministas del contenido.

## Scoring

La correspondencia es uno-a-uno y exacta sobre la representación normalizada:

* `TP`: un elemento predicho coincide con un elemento de gold.
* `FP`: un elemento predicho no tiene pareja en gold.
* `FN`: un elemento de gold no fue predicho.
* `NOT_CALCULABLE`: no existe gold evaluable para esa dimensión.

`precision = TP / (TP + FP)`, `recall = TP / (TP + FN)` y `F1` es su media
armónica. Cuando el denominador no existe, la métrica es `null`, no cero.
Los veredictos por elemento aparecen en `verdicts`; los contadores incluyen
las cuatro claves de estado.
