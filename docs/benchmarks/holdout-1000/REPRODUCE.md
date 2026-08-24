# Reproducción

## Insumos congelados

- Manifiesto de prompts: `inputs-manifest.json` — SHA-256
  `26b72644e00ee44aff6fcb492aed616d6d4a438b44ed6d5abed3c5541697a930`.
- Caché factual PDF externo — SHA-256
  `6b477c37c21219fdf45e1f1946e59a609a232b7872825d1dc71c3d8575f96d61`.
- Seed de generación de prompts: `20260812`.
- Catálogo: `run-catalog.json`.
- Resultados brutos remotos: `backups/benchmark-results/`.

## Evaluación en el servidor

```bash
cd ~/legal-AI-infraestructure
python3 backups/benchmark-evaluation-v2/input/evaluate_decree_factual_fidelity.py \
  --reference-cache backups/benchmark-evaluation-v2/input/pdf-gold-facts.auto.jsonl \
  --prompt-manifest backups/benchmark-inputs/prompts-v2-20260812/manifest.json \
  --prompts-dir backups/benchmark-inputs/prompts-v2-20260812/prompts \
  --run-catalog backups/benchmark-evaluation-v2/input/run-catalog.json \
  --outputs-root backups/benchmark-results \
  --output-dir backups/benchmark-evaluation-v2/output-v3 \
  --expected-cases 1000
```

## Reporte local

```powershell
python tools/build_holdout_benchmark_report.py `
  --summary docs/benchmarks/holdout-1000/results/benchmark-summary.json `
  --output-dir docs/benchmarks/holdout-1000/report
```

El HTML portable se construye desde `report/artifact.json`, se finaliza con
`tools/finalize_portable_benchmark_report.py` y se valida en viewports de
1.440 y 390 píxeles antes de imprimirlo a PDF.

## Reproducibilidad todavía incompleta

El catálogo histórico no conserva para todas las corridas el digest de la
imagen, digest del modelo, temperatura, `top_p`, versión de Ollama y commit
exacto. Esos campos son obligatorios en nuevas corridas; los resultados
actuales son comparables por sus parámetros RAG/Ollama y por identidad de los
1.000 casos, pero no constituyen una reconstrucción bit a bit.
