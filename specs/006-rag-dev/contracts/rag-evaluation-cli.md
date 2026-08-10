# Contrato CLI — Evaluación RAG 006

## Comandos

```text
corpus rag-evaluate MANIFEST_PATH
corpus rag-evaluate MANIFEST_PATH --execute --provider fake
corpus rag-evaluate MANIFEST_PATH --execute --provider ollama --limit N
```

## Semántica por defecto

Sin `--execute`, el comando es dry-run:

- valida manifiesto y hashes;
- confirma que ningún holdout está indexado;
- valida configuración y disponibilidad de archivos;
- calcula cantidad de casos y operaciones estimadas;
- no llama a embeddings ni generación;
- no escribe en PostgreSQL;
- no crea archivos persistentes.

## Manifiesto

```json
{
  "dataset_version": "holdout-10-v1",
  "split": "HOLDOUT_10",
  "source": "infoleg-decretos-nacionales",
  "cases": [
    {
      "case_id": "HOLDOUT-0001",
      "relative_path": "pdf/0001.pdf",
      "sha256": "64-char-lowercase-sha256",
      "external_id": "opaque-id"
    }
  ]
}
```

`relative_path` solo se usa internamente y nunca aparece en logs, DB o salida pública. Se rechazan rutas absolutas, traversal, symlink escape, hashes inválidos, IDs duplicados y archivos faltantes.

## Providers

- `fake`: determinista, requerido en CI, no usa Ollama.
- `ollama`: opt-in, usa los modelos contractuales y requiere conectividad real.

No existe fallback automático de `ollama` a `fake`.

## Salida JSON

```json
{
  "dataset_version": "holdout-10-v1",
  "mode": "DRY_RUN|EXECUTE",
  "provider": "fake|ollama",
  "case_count": 1000,
  "completed": 1000,
  "failed": 0,
  "leakage_detected": 0,
  "metrics": {
    "recall_at_3": null,
    "recall_at_5": null,
    "precision_at_3": null,
    "precision_at_5": null,
    "mrr": null,
    "schema_valid_rate": 1.0,
    "required_sections_rate": 1.0,
    "citation_precision": 1.0,
    "unsupported_claim_rate": 0.0,
    "invented_citation_rate": 0.0,
    "latency_ms": {"p50": 0, "p95": 0, "max": 0}
  },
  "human_evaluation": {
    "evaluated": 0,
    "legal_usefulness_average": null,
    "legally_relevant_rate": null
  },
  "request_id": "correlation-id"
}
```

Métricas sin verdad de referencia suficiente se informan como `null`, nunca como cero inventado.

## Exit codes

| Código | Significado |
|---|---|
| 0 | Ejecución o dry-run completos |
| 2 | Argumentos/manifiesto inválidos |
| 3 | Fuga detectada: un holdout está indexado |
| 4 | Dependencia no disponible |
| 5 | Evaluación parcial con casos fallidos |
| 6 | Persistencia de auditoría no disponible |

## Seguridad

La salida y los logs no incluyen PDFs, texto extraído completo, prompts, respuestas completas, embeddings, tokens, Authorization, secretos, rutas absolutas ni stack traces.
