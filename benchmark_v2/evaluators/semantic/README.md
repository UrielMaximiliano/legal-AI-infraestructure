# Evaluadores semánticos de Benchmark v2

El contrato canónico de entrada por caso es:

```json
{
  "case_id": "case-001",
  "candidate": "respuesta generada",
  "references": ["respuesta de referencia"]
}
```

`evaluate_case` devuelve un registro con `case_id`, `status`, la declaración de
normalización, cantidad de referencias y un bloque por métrica (`rouge_l`,
`chrf`, `bertscore`). Cada bloque tiene su propio `status`, `score`,
`precision`, `recall`, `f1` y `reason`. Las métricas léxicas eligen el máximo
F1 entre las referencias provistas y el primer índice en caso de empate; no se
crean referencias ni se rellenan scores faltantes. Una referencia ausente,
vacía o inválida produce `NOT_CALCULABLE` y `score: null`.

La normalización `unicode-nfkc-casefold-whitespace/v1` aplica Unicode NFKC,
casefold y colapsa espacios. Conserva puntuación y acentos porque pueden ser
jurídicamente relevantes. ROUGE-L usa LCS sobre tokens separados por espacio y
F1; chrF usa n-gramas de caracteres 1..6, conserva espacios normalizados y
F-beta con beta=2. Son señales de solapamiento/similitud, no verifican verdad,
entailment, jurisdicción, vigencia, citas, omisiones ni validez jurídica.

BERTScore se integra mediante la dependencia opcional `bert-score`. Su
configuración por defecto fija `bert-base-multilingual-cased`, `lang=es`, sin
IDF ni rescaling; se deben registrar además las versiones de paquete y modelo
para comparar corridas. Si la dependencia no está instalada o el backend falla,
el bloque queda explícitamente en `NOT_CALCULABLE` (nunca se reemplaza por cero)
y las métricas ROUGE-L/chrF continúan disponibles.

## Fuentes y limitaciones

- [BERTScore: Evaluating Text Generation with BERT (Zhang et al., 2020)](https://arxiv.org/abs/1904.09675)
- [ROUGE: A Package for Automatic Evaluation of Summaries (Lin, 2004)](https://aclanthology.org/W04-1013/)
- [chrF: character n-gram F-score for automatic MT evaluation (Popović, 2015)](https://aclanthology.org/W15-3049/)

Las fuentes describen métricas generales de generación/traducción; no
garantizan validez para español jurídico ni para una jurisdicción concreta.
Textos largos, varias referencias, negaciones, números, excepciones y cambios
de vigencia requieren análisis jurídico o factual adicional.
