"""Generate the Spanish benchmark-v2 audit and results report."""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _pct(value: Any) -> str:
    if value in (None, ""):
        return "—"
    try:
        return f"{float(value) * 100:.3f}%"
    except (TypeError, ValueError):
        return str(value)


def _v1_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _v1_table(rows: list[dict[str, str]]) -> str:
    wanted = {row.get("case_id"): row for row in rows}
    lines = [
        "| Configuración v1 | Cobertura | Fidelidad E2E proxy | F1 claims materiales |",
        "|---|---:|---:|---:|",
    ]
    for case_id in ("C09", "C15", "C19"):
        row = wanted.get(case_id)
        if row is None:
            continue
        lines.append(
            f"| {case_id} — {row.get('label', 'sin etiqueta')} | "
            f"{_pct(row.get('coverage'))} | {_pct(row.get('factual_fidelity_e2e'))} | "
            f"{_pct(row.get('material_f1'))} |"
        )
    if len(lines) == 2:
        lines.append("| No disponible | — | — | — |")
    return "\n".join(lines)


def _v1_counts(rows: list[dict[str, str]]) -> str:
    expected = sum(int(row.get("expected_cases") or 0) for row in rows)
    found = sum(int(row.get("outputs_found") or 0) for row in rows)
    succeeded = sum(int(row.get("succeeded") or 0) for row in rows)
    failed = sum(int(row.get("failed") or 0) for row in rows)
    missing = sum(int(row.get("missing") or 0) for row in rows)
    invalid = sum(int(row.get("invalid_reference_joins") or 0) for row in rows)
    run_config_text = (
        "19 ejecuciones tabuladas sobre 18 configuraciones"
        if len(rows) == 19
        else f"{len(rows)} filas de ejecución/configuración tabuladas"
    )
    return (
        f"{run_config_text}; {expected:,} casos esperados; "
        f"{found:,} salidas encontradas; {succeeded:,} exitosas; {failed:,} fallidas; "
        f"{missing:,} ausentes; {invalid:,} joins de referencia inválidos."
    )


def _dimension_rows(summary: dict[str, Any]) -> str:
    descriptions = {
        "semantic": "ROUGE-L/chrF deterministas; BERTScore opcional",
        "claims": "claims, entidades y contradicciones con TP/FP/FN",
        "legal_fields": "norma, fecha, plazo, expediente y referencias; configurable",
        "retrieval": "Recall@k, MRR, nDCG, calidad/procedencia y leakage",
        "faithfulness": "claims soportados frente a evidencia RAG trazable",
        "structure": "JSON/schema, completitud, citas, evidencia, latencia y coste",
        "statistics": "paired bootstrap/BCa, Wilcoxon, Holm y FULL–PARTIAL",
        "human": "doble revisión ciega y adjudicación; plantilla sin scores rellenados",
    }
    statuses = summary.get("dimensions", {})
    lines = [
        "| Dimensión | Estado observado | Qué se interpreta |",
        "|---|---|---|",
    ]
    for dimension, description in descriptions.items():
        state = statuses.get(dimension)
        if state == {}:
            state_text = "NOT_CALCULABLE (0 casos)"
        elif state is None:
            state_text = "PENDIENTE / requiere insumo"
        elif isinstance(state, dict):
            state_text = ", ".join(f"{key}={value}" for key, value in sorted(state.items()))
        else:
            state_text = str(state)
        lines.append(f"| {dimension} | {state_text} | {description} |")
    return "\n".join(lines)


def build_report(summary: dict[str, Any], *, v1_rows: list[dict[str, str]], summary_path: Path) -> str:
    status = summary.get("status", "NOT_CALCULABLE")
    observed = summary.get("observed_count", 0)
    expected = summary.get("expected_count")
    reasons = summary.get("not_calculable_reasons") or []
    leakage = summary.get("leakage_checks") or {}
    if status == "NOT_CALCULABLE":
        execution = (
            "La corrida diagnóstica no calcula métricas V2 porque no recibió una tabla de casos. "
            "Esto es deliberado: el checkout no contiene los PDFs holdout, prompts, respuestas crudas, "
            "gold estructurado ni caché de recuperación necesarios para reconstruir la corrida completa."
        )
    elif status == "PARTIAL":
        execution = (
            f"La corrida observó {observed} casos de {expected if expected is not None else 'cantidad no declarada'}; "
            "se conserva como PARTIAL y no debe mezclarse con FULL."
        )
    else:
        execution = f"La corrida declara FULL con {observed} casos y cobertura exacta del esperado."

    reason_text = ", ".join(f"`{item}`" for item in reasons) or "ninguna"
    leakage_status = leakage.get("status", "NOT_CALCULABLE")
    return f"""# Benchmark RAG legal V2 — auditoría, diseño y ejecución

Fecha de generación: 2026-08-25
Estado de esta ejecución: **{status}**
Resumen de ejecución: [`{summary_path.as_posix()}`](../{summary_path.as_posix()})

## Conclusión ejecutiva

{execution}

No se publica un score global de “calidad legal”. Las dimensiones se reportan por separado y solo cuando sus referencias y artefactos están disponibles. Un valor ausente se conserva como `NOT_CALCULABLE`, nunca se convierte en cero ni se usa para ordenar configuraciones.

## Alcance y preservación

- Se creó un árbol independiente `benchmark_v2/` para contratos, evaluadores, runner, estadísticas, pruebas y resultados.
- El benchmark v1 (`docs/benchmarks/holdout-1000/`) y el código de producción no forman parte de la ruta de ejecución V2.
- El diseño cubre modelo Ollama, embedding, contexto, `top_k`, semilla, hardware, latencia/coste y cualquier dimensión adicional declarada en metadata.
- La comparación válida entre configuraciones exige los mismos `case_id`, referencias, política de exclusión y esquema de evaluación.

## Auditoría de v1

Fuente tabular: [`docs/benchmarks/holdout-1000/results/benchmark-summary.csv`](../docs/benchmarks/holdout-1000/results/benchmark-summary.csv).
{_v1_counts(v1_rows)}

Estos números son cobertura/ejecución y fidelidad factual proxy del benchmark existente; no son exactitud jurídica humana. La metodología v1 usa claims materiales, solapamiento/fidelidad y sus intervalos, no adjudicación legal independiente.

{_v1_table(v1_rows)}

Gráfico histórico disponible: [`accuracy-all-cases.png`](../docs/benchmarks/holdout-1000/report/accuracy-all-cases.png). No se presenta como resultado V2.

## Matriz multidimensional V2

{_dimension_rows(summary)}

El estado de dimensiones anterior resume solo los registros observados en esta corrida. `CALCULATED` significa que la dimensión pudo evaluarse con su referencia; `NOT_CALCULABLE` significa que faltó un insumo o contrato; `PARTIAL` significa que solo una parte de la dimensión fue calculable.

## Política FULL vs PARTIAL

- **FULL**: exactamente `expected_count` casos, IDs únicos, joins válidos y artefactos requeridos presentes.
- **PARTIAL**: casos válidos pero cobertura menor o cantidad esperada no declarada. Se conserva para diagnóstico y sensibilidad, no para ranking de corridas completas.
- **NOT_CALCULABLE**: no existe una base suficiente para producir métricas honestas. La corrida debe dejar manifest, razón y artefactos vacíos reproducibles.
- La comparación FULL–PARTIAL se expresa como delta por métrica y por caso emparejado; no como un promedio global opaco.

## Integridad, leakage y joins

Estado de las aserciones del runner: **{leakage_status}**.
IDs duplicados: `{leakage.get('duplicate_count', 0)}`; joins inválidos: `{leakage.get('invalid_joins', 0)}`; candidatos que contienen la referencia declarada: `{leakage.get('candidate_contains_reference', 0)}`.
Razones `NOT_CALCULABLE`: {reason_text}.
Cuando no se dispone del texto excluido, el runner lo declara explícitamente como chequeo no calculable; no afirma ausencia de leakage por falta de evidencia.

## Evaluación humana

La plantilla [`human_eval_template.jsonl`](../{summary_path.parent.as_posix()}/human_eval_template.jsonl) deja en blanco dos revisiones independientes para organismo, objeto, persona/cargo, dependencia, fecha/plazo/vigencia, normas, artículos resolutivos, datos críticos, claims TP/FP/FN, faithfulness, utilidad y notas. La adjudicación debe registrar desacuerdos y conservar el ID de caso; no se debe imputar una etiqueta automática por similitud textual.

## Reproducibilidad

```powershell
& 'apps/api/.venv/Scripts/python.exe' benchmark_v2/scripts/run_benchmark.py `
  --cases <casos.jsonl> `
  --out-dir benchmark_v2/results/run-<id> `
  --run-id <id> --expected-count 1000 --seed 20260825 --human-sample 100
& 'apps/api/.venv/Scripts/python.exe' benchmark_v2/scripts/generate_report.py `
  --summary benchmark_v2/results/run-<id>/summary.json `
  --output reports/BENCHMARK_RAG_LEGAL_V2.md
```

El manifest conserva commit, semilla, timestamp, hash de entrada y hashes de registros. `metrics.jsonl` es la salida canónica por caso; `metrics.csv` facilita inspección tabular; Parquet queda como formato opcional cuando existe `pyarrow` o un engine equivalente.

## Limitaciones y próximos insumos

La ejecución completa V2 requiere montar fuera del repositorio el holdout original, su hash, prompts, respuestas Ollama, contexto recuperado, referencias gold, configuración de exclusión y trazas de coste/latencia. Hasta que esos artefactos estén disponibles, el resultado correcto es `NOT_CALCULABLE`, no una cifra de calidad inferida desde v1.
"""


def _write_html(markdown: str, output: Path) -> None:
    body = html.escape(markdown)
    document = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Benchmark RAG legal V2</title>
<style>body {{ font-family: Arial, sans-serif; margin: 32px; color: #202124; }}
pre {{ white-space: pre-wrap; line-height: 1.45; font-size: 11px; }}
h1 {{ color: #17365d; }}</style></head><body><h1>Benchmark RAG legal V2</h1><pre>{body}</pre></body></html>
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--v1-summary",
        type=Path,
        default=Path("docs/benchmarks/holdout-1000/results/benchmark-summary.csv"),
    )
    parser.add_argument("--html-output", type=Path)
    args = parser.parse_args(argv)
    summary = _read_json(args.summary)
    report = build_report(summary, v1_rows=_v1_rows(args.v1_summary), summary_path=args.summary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    if args.html_output:
        _write_html(report, args.html_output)
    print(f"report={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
