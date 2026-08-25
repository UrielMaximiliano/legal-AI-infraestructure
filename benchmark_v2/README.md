# Benchmark v2: contrato común de datos

Este directorio contiene únicamente el contrato de datos compartido por los
benchmarks. No modifica el runner ni el código de producción. Un resultado
publicable es un sobre JSON con el mismo esquema para todas las dimensiones que
se quieran comparar: modelo, embedding, contexto, `top_k`, seed, hardware u
otras dimensiones futuras.

## Reproducibilidad

Cada corrida debe conservar metadata suficiente para volver a identificarla:

```json
{
  "schema_version": "benchmark-v2.result.v1",
  "run_id": "demo-001",
  "status": "FULL",
  "metadata": {
    "run_id": "demo-001",
    "dataset": {
      "name": "holdout",
      "version": "2026-08",
      "sha256": "<64 hex chars>"
    },
    "code": {"commit": "<git sha>"},
    "generated_at_utc": "2026-08-25T12:00:00Z",
    "seed": 20260825,
    "dimensions": {
      "embedding_model": "example-4b",
      "embedding_dimensions": 2560,
      "context_tokens": 8192
    }
  },
  "expected_count": 1000,
  "records": [{"case_id": "case-0001", "score": 0.9}]
}
```

`dataset.sha256` identifica el conjunto de entrada; `records_sha256` y
`result_sha256` son calculados por `validate_result`; `seed`, commit y fecha UTC
permiten auditar cómo se produjo la corrida. Los hashes son SHA-256 en
minúsculas y se calculan sobre JSON canónico (UTF-8, claves ordenadas, sin
espacios innecesarios).

La función `benchmark_v2.results.schema.build_result` valida y completa el
sobre. `validate_result` también acepta productores que llamen al array
`results`, `rows` o `cases`, pero normaliza siempre a `records`.

## FULL y PARTIAL

`FULL` significa que la corrida cubre exactamente `expected_count` registros.
`PARTIAL` es una corrida válida pero incompleta (por ejemplo, un smoke test o
una ejecución interrumpida); debe conservar los registros disponibles y su
metadata. Si se declara `FULL` con una cantidad distinta, la validación falla.
Una corrida `PARTIAL` no debe entrar silenciosamente en un ranking de corridas
completas.

## Formatos de almacenamiento

`benchmark_v2.data.io` ofrece `read_records`/`write_records` y helpers
específicos para JSONL y CSV. Ambos formatos son de la biblioteca estándar y no
requieren instalar nada. Parquet es opcional: se usa `pyarrow` si está
disponible o `pandas` con un engine Parquet; sin ellos se obtiene un error claro
(`OptionalDependencyError`) y se puede continuar con JSONL/CSV.

Los writers pueden recibir `metadata=...`. La metadata se guarda en un sidecar
determinista `<archivo>.metadata.json`, incluyendo su propio hash. Para evitar
recalcular o copiar datos equivalentes, `HashCache` y `cache_records` almacenan
el archivo bajo `<sha256>.<formato>`; si el contenido cambia, cambia la clave.

```python
from benchmark_v2.data.io import HashCache, read_records, write_records

write_records("results.jsonl", rows, metadata=run_metadata)
cache = HashCache(".benchmark-cache")
cached_path = cache.put("results.jsonl")
rows_again = read_records(cached_path)
```

## Contrato multidimensional

`metadata.dimensions` es un mapa abierto de coordenadas escalares, no una lista
fija de columnas. Se pueden agregar dimensiones sin cambiar el schema: por
ejemplo `embedding_dimensions=1024`, `retrieval_top_k=8`, `ollama_num_ctx=32768`
o `hardware="cpu"`. Un registro puede incluir además su propio mapa
`dimensions` para resultados combinados o diseños factoriales. La identidad de
una observación debe expresarse con `record_id`, `case_id` o `id`; los IDs
duplicados son rechazados.

El JSON Schema normativo está en [`configs/schema.json`](configs/schema.json).
La prueba de contrato en [`tests/data_contract_test.py`](tests/data_contract_test.py)
verifica determinismo, cobertura, formatos sin dependencia opcional, cache por
hash y dimensiones múltiples.


