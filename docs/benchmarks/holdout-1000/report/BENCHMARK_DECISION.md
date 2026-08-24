# Benchmark factual del holdout de 1.000 decretos

## Resultado ejecutivo

La mejor estimación puntual es **C15**: embedding 4B/2.560, RAG 8192, Ollama 16384, `top_k=8`, pool 24 y score mínimo 0.0. Obtuvo **86.29%** de fidelidad factual extremo a extremo y 1000/1.000 outputs exitosos.

La ventaja sobre otras configuraciones 4B es pequeña: existe una meseta de calidad alrededor de 86%. Por eso C15 es la candidata técnica, no una certificación jurídica definitiva.

## Tabla completa

| Caso | Modelo | RAG | Ollama | top_k | score | Accuracy* | Precision* | Recall* | Éxito | Cobertura |
|---|---|---|---|---|---|---|---|---|---|---|
| C01 | 4B | 2048 | 8192 | 8 | 0.00 | 86.05% | 43.34% | 56.71% | 100.00% | 1000/1000 · éxito 100.0% |
| C02 | 4B | 4096 | 16384 | 8 | 0.00 | 86.05% | 42.61% | 56.62% | 100.00% | 1000/1000 · éxito 100.0% |
| C03 | 4B | 8192 | 32768 | 8 | 0.00 | 86.05% | 42.50% | 56.80% | 100.00% | 1000/1000 · éxito 100.0% |
| C04 | 4B | 4096 | 16384 | 5 | 0.65 | 84.60% | 43.26% | 56.23% | 98.40% | 1000/1000 · éxito 98.4% |
| C05 | 0.6B | 2048 | 8192 | 8 | 0.00 | 85.65% | 44.89% | 55.76% | 100.00% | 1000/1000 · éxito 100.0% |
| C06 | 0.6B | 2048 | 8192 | 5 | 0.65 | 78.58% | 45.67% | 51.99% | 91.40% | 1000/1000 · éxito 91.4% |
| C07 | 0.6B | 3072 | 16384 | 12 | 0.00 | 85.69% | 44.47% | 55.58% | 99.90% | 1000/1000 · éxito 99.9% |
| C08 | 0.6B | 2048 | 8192 | 8 | 0.55 | 85.46% | 44.72% | 55.54% | 99.70% | 1000/1000 · éxito 99.7% |
| C09 | 0.6B | 1536 | 8192 | 3 | 0.60 | 8.78% | 53.89% | 6.49% | 10.10% | 103/1000 · éxito 10.1% |
| C10 | 4B | 2048 | 16384 | 8 | 0.00 | 85.95% | 43.01% | 56.64% | 100.00% | 1000/1000 · éxito 100.0% |
| C11 | 4B | 2048 | 32768 | 8 | 0.00 | 86.01% | 43.38% | 56.79% | 100.00% | 1000/1000 · éxito 100.0% |
| C12 | 0.6B | 2048 | 16384 | 8 | 0.00 | 85.64% | 44.70% | 55.68% | 100.00% | 1000/1000 · éxito 100.0% |
| C13 | 0.6B | 2048 | 32768 | 8 | 0.00 | 85.49% | 44.70% | 55.56% | 100.00% | 1000/1000 · éxito 100.0% |
| C14 | 4B | 4096 | 16384 | 8 | 0.00 | 86.05% | 42.89% | 56.64% | 100.00% | 1000/1000 · éxito 100.0% |
| C15 | 4B | 8192 | 16384 | 8 | 0.00 | 86.29% | 42.94% | 57.10% | 100.00% | 1000/1000 · éxito 100.0% |
| C16 | 4B | 16384 | 16384 | 8 | 0.00 | 86.09% | 42.62% | 56.97% | 100.00% | 1000/1000 · éxito 100.0% |
| C17 | 0.6B | 4096 | 32768 | 8 | 0.00 | 85.80% | 44.02% | 56.04% | 100.00% | 1000/1000 · éxito 100.0% |
| C18 | 0.6B | 8192 | 32768 | 8 | 0.00 | 85.77% | 44.28% | 55.95% | 100.00% | 1000/1000 · éxito 100.0% |
| C19 | 0.6B | 16384 | 32768 | 8 | 0.00 | 85.85% | 44.30% | 55.96% | 100.00% | 1000/1000 · éxito 100.0% |

## Definición de métricas

- **Accuracy***: fidelidad factual por campos contra hechos derivados del PDF, con fallos y faltantes en cero para el resultado extremo a extremo.
- **Precision***: proporción de afirmaciones materiales del output respaldadas por la referencia.
- **Recall***: proporción de afirmaciones materiales esperadas que aparecen en el output.
- El asterisco marca evaluación automática. La decisión jurídica final requiere adjudicación humana.
