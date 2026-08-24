# Protocolo reproducible de benchmark

## 1. Diseño experimental

Cada corrida tiene un identificador único y congela todos los parámetros salvo
el que se quiere estudiar. La secuencia recomendada es:

1. **Bloque Ollama:** mantener RAG, embedding, `top_k` y score fijos; variar
   únicamente el `num_ctx` efectivo enviado a Ollama (por ejemplo 8.192,
   16.384 y 32.768).
2. **Bloque RAG:** fijar Ollama y variar únicamente el contexto RAG y, si
   corresponde, `top_k` o `minimum_score`.
3. **Candidata final:** repetir la mejor configuración de cada modelo sobre
   los mismos 1.000 casos, con los mismos prompts, PDFs y seed.

No se comparan corridas con distinta selección de documentos, distinta versión
de prompts, distinta tabla vectorial o distinto conjunto de casos sin marcarlo
explícitamente.

## 2. Manifiesto obligatorio

Cada carpeta de corrida debe contener al menos:

```text
<run-id>/
├── config.yml             # parámetros efectivos y versión de código
├── manifest.json          # 1.000 casos, PDFs y SHA-256
├── cases/case-NNNN.json   # output bruto, uno por caso
├── evaluation/            # proxy o gold humano, nunca mezclados
└── report/                # CSV/JSON/HTML/PDF derivados
```

`config.yml` debe registrar: modelo generativo, modelo de embedding,
dimensión, base de datos/índice, contexto Ollama, contexto RAG, `top_k`,
`minimum_score`, pool/diversificación, seed, endpoint (sin tokens), commit,
fecha UTC, cantidad objetivo y política de reintentos.

## 3. Qué se compara

La unidad de comparación es el par `case_number` + PDF original. El prompt es
la entrada; el output JSON es la predicción; el PDF no es un prompt adicional
ni una fuente que se vuelve a indexar. Antes de evaluar se verifican:

- 1.000 prompts y 1.000 PDFs esperados;
- hash del PDF y correspondencia de `reference_pdf`;
- ausencia de archivos duplicados o casos faltantes;
- mismo esquema de salida y estado HTTP;
- ausencia de fuga del holdout al índice.

## 4. Métricas y su significado

### 4.1 Fidelidad factual PDF (automática, provisional)

`tools/evaluate_decree_factual_fidelity.py` compara cada output con un caché
congelado de hechos extraídos del PDF. Antes de puntuar exige coincidencia de
`case_number`, nombre y SHA-256 del PDF, y hash del prompt del manifiesto. La
Accuracy proxy es la cobertura media de los campos aplicables; en la variante
extremo a extremo, un output fallido o faltante vale cero.

Precision y Recall se calculan solo sobre afirmaciones materiales tipadas:
normas, fechas, plazos, expedientes y referencias de artículos. Por ello no
detectan todas las invenciones semánticas y se publican con asterisco como
**métricas automáticas provisionales**, nunca como exactitud jurídica.

```powershell
python tools/evaluate_decree_factual_fidelity.py `
  --reference-cache <pdf-gold-facts.auto.jsonl> `
  --prompt-manifest <manifest.json> `
  --prompts-dir <prompts-v2> `
  --run-catalog <run-catalog.json> `
  --outputs-root <benchmark-results> `
  --output-dir <evaluation-output>
```

### 4.2 Gold jurídico (decisión de producción)

`tools/evaluate_decree_benchmark.py` requiere un manifiesto revisado por una
persona. Accuracy es el promedio de ocho campos (1 correcto, 0,5 parcial,
0 incorrecto/ausente): organismo, objeto, persona/cargo, dependencia,
fecha/plazo/vigencia, normas, artículos resolutivos y datos críticos.

Para hechos atómicos:

- **TP:** el hecho está y es correcto;
- **FP:** el output inventa o altera un hecho;
- **FN:** el hecho esperado está ausente.

`Precision = TP / (TP + FP)`; `Recall = TP / (TP + FN)`; `F1` es la media
armónica. Un caso sin anotación es `NOT_CALCULABLE`, nunca cero.

```powershell
python tools/evaluate_decree_benchmark.py `
  --gold <gold-human.jsonl> `
  --outputs <run-1> <run-2> `
  --output-dir <run>/evaluation/legal
```

## 5. Cómo decidir qué configuración gana

La prioridad es calidad jurídica, no velocidad:

1. mayor Accuracy y F1 jurídicos con intervalo de confianza pareado;
2. menor FP (invenciones) y menor tasa de `RAG_INSUFFICIENT_EVIDENCE`;
3. Recall suficiente para no omitir hechos materiales;
4. outputs válidos y citas resolubles como condición de seguridad;
5. latencia, VRAM y consumo solo desempatan configuraciones de calidad
   equivalente.

Para cada comparación se informa el delta contra una configuración base y la
cantidad de casos realmente evaluados. No se elige un modelo porque dos
proxies sean iguales: se revisan los PDFs y la muestra humana antes de
promoverlo.

## 6. Checklist de cierre

- [ ] Corrida y configuración tienen IDs únicos y hash de commit.
- [ ] 1.000/1.000 prompts y PDFs coinciden por caso y hash.
- [ ] El holdout no aparece en la base ni en los embeddings.
- [ ] El proxy está etiquetado `AUTOMATED_PDF_FACTUAL_FIDELITY_V2`.
- [ ] Gold humano cubre los casos usados para Accuracy/Precision/Recall/F1.
- [ ] `NOT_CALCULABLE` no fue convertido a cero.
- [ ] Los índices 2560 y 1024 están aislados.
- [ ] El informe conserva JSON/CSV crudos además de gráficos.
