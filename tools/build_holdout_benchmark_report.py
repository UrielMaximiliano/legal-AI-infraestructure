#!/usr/bin/env python3
"""Build the canonical report artifact and Markdown decision record."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def _pct(value: Any, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value) * 100, digits)


def _case_sort(value: str) -> int:
    return int(value.removeprefix("C"))


def _model(row: dict[str, Any]) -> str:
    return "4B" if int(row["embedding_dimensions"]) == 2560 else "0.6B"


def _table_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in sorted(rows, key=lambda item: _case_sort(item["case_id"])):
        partial = not bool(row["comparable_full_run"])
        result.append(
            {
                "case": row["case_id"],
                "case_coverage": f"{row['case_id']} · {row['outputs_found']}/{row['expected_cases']}",
                "modelo": _model(row),
                "rag": int(row["rag_context"]),
                "ollama": int(row["ollama_context"]),
                "top_k": int(row["top_k"]),
                "pool": int(row["candidate_pool"]),
                "score_min": float(row["minimum_score"]),
                "parametros": (
                    f"{_model(row)} R{int(row['rag_context'])}/O{int(row['ollama_context'])}/"
                    f"k{int(row['top_k'])}/p{int(row['candidate_pool'])}/"
                    f"s{float(row['minimum_score']):.2f}"
                ),
                "accuracy": _pct(row["factual_fidelity_e2e"]),
                "precision": _pct(row["material_precision"]),
                "recall": _pct(row["material_recall"]),
                "precision_recall": (
                    f"P {_pct(row['material_precision']):.2f}% / "
                    f"R {_pct(row['material_recall']):.2f}%"
                ),
                "exito": _pct(row["success_rate"]),
                "cobertura": (
                    f"{row['outputs_found']}/{row['expected_cases']} · "
                    f"éxito {_pct(row['success_rate']):.1f}%"
                ),
                "estado": "Parcial; no rankea" if partial else "Completo",
            }
        )
    return result


def _chart_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
        key=lambda row: (
            row["quality_rank"] is None,
            int(row["quality_rank"] or 10_000),
            _case_sort(row["case_id"]),
        ),
    )
    result = []
    for row in ordered:
        partial = not bool(row["comparable_full_run"])
        result.append(
            {
                "caso": row["case_id"] + ("†" if partial else ""),
                "accuracy": _pct(row["factual_fidelity_e2e"]),
                "modelo": _model(row),
                "rag": int(row["rag_context"]),
                "ollama": int(row["ollama_context"]),
                "top_k": int(row["top_k"]),
                "score_min": float(row["minimum_score"]),
                "exito": _pct(row["success_rate"]),
            }
        )
    return result


def _markdown_table(rows: list[dict[str, Any]]) -> str:
    headers = [
        "Caso", "Modelo", "RAG", "Ollama", "top_k", "score", "Accuracy*",
        "Precision*", "Recall*", "Éxito", "Cobertura",
    ]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in _table_rows(rows):
        lines.append(
            "| "
            + " | ".join(
                [
                    row["case"], row["modelo"], str(row["rag"]), str(row["ollama"]),
                    str(row["top_k"]), f"{row['score_min']:.2f}",
                    f"{row['accuracy']:.2f}%", f"{row['precision']:.2f}%",
                    f"{row['recall']:.2f}%", f"{row['exito']:.2f}%",
                    row["cobertura"],
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _artifact(summary: dict[str, Any], generated_at: str) -> dict[str, Any]:
    rows = summary["summaries"]
    full = [row for row in rows if row["comparable_full_run"]]
    winner = min(full, key=lambda row: row["quality_rank"])
    best_06 = max(
        (row for row in full if int(row["embedding_dimensions"]) == 1024),
        key=lambda row: row["factual_fidelity_e2e"],
    )
    chart_rows = _chart_rows(rows)
    table_rows = _table_rows(rows)
    pairwise = {
        row["other_case_id"]: row for row in summary.get("pairwise_to_best", [])
    }
    versus_best_06 = pairwise[best_06["case_id"]]
    versus_baseline = pairwise["C01"]

    source_summary = {
        "id": "benchmark_summary",
        "label": "Resumen recalculado de las 19 corridas",
        "path": "docs/benchmarks/holdout-1000/results/benchmark-summary.csv",
        "query": {
            "engine": "duckdb",
            "language": "sql",
            "sql": "SELECT * FROM read_csv_auto('docs/benchmarks/holdout-1000/results/benchmark-summary.csv')",
            "description": "Une cada output con el PDF por caso, nombre y SHA-256; calcula fidelidad factual y afirmaciones materiales.",
            "filters": [
                "1.000 casos esperados por corrida",
                "holdout-prompt-v2; seed 20260812",
                "PDFs del holdout no incluidos en los índices RAG",
                "fallos y faltantes puntúan cero en la métrica extremo a extremo",
            ],
            "metric_definitions": {
                "Accuracy proxy E2E": "Promedio con igual peso de los campos factuales aplicables extraídos del PDF y revelados en la solicitud; fallos y faltantes valen cero.",
                "Precision proxy": "Afirmaciones materiales correctas sobre todas las afirmaciones materiales del output.",
                "Recall proxy": "Afirmaciones materiales recuperadas sobre todas las afirmaciones materiales esperadas.",
            },
            "executed_at": generated_at,
        },
    }
    source_catalog = {
        "id": "run_catalog",
        "label": "Catálogo versionado de parámetros",
        "path": "docs/benchmarks/holdout-1000/run-catalog.json",
        "query": {
            "engine": "duckdb",
            "language": "sql",
            "sql": "SELECT * FROM read_json_auto('docs/benchmarks/holdout-1000/run-catalog.json')",
            "description": "Parámetros efectivos de los 19 experimentos consolidados.",
        },
    }
    sources = [source_summary, source_catalog]
    title = "Benchmark RAG jurídico"
    summary_body = (
        "## Executive Summary\n\n"
        f"- **Mejor punto observado: {winner['case_id']}.** Alcanzó "
        f"**{_pct(winner['factual_fidelity_e2e']):.2f}%** de fidelidad factual extremo a extremo "
        f"con embedding 4B, RAG {winner['rag_context']} y Ollama {winner['ollama_context']}; "
        f"completó {winner['succeeded']}/1.000 casos.\n"
        "- **No hay una victoria amplia dentro de 4B.** Las mejores corridas forman una meseta cercana a 86%. "
        f"Frente a C01, C15 mejora {_pct(versus_baseline['mean_delta']):.2f} puntos, con IC95% "
        f"[{_pct(versus_baseline['ci95_low']):.2f}; {_pct(versus_baseline['ci95_high']):.2f}], "
        "por lo que esa diferencia no es concluyente.\n"
        f"- **Mejor 0.6B: {best_06['case_id']}.** Logró {_pct(best_06['factual_fidelity_e2e']):.2f}% "
        f"con RAG {best_06['rag_context']} y Ollama {best_06['ollama_context']}. "
        f"El 4B líder lo supera por {_pct(versus_best_06['mean_delta']):.2f} puntos "
        f"(IC95% [{_pct(versus_best_06['ci95_low']):.2f}; "
        f"{_pct(versus_best_06['ci95_high']):.2f}]).\n"
        "- **Decisión recomendada:** usar C15 como candidata de calidad y confirmar una muestra jurídica humana "
        "antes de fijarla en producción. C09 queda fuera del ranking porque solo cubre 103/1.000 casos."
    )
    definitions = (
        "## Qué mide el gráfico\n\n"
        "**Accuracy*** es una cobertura factual automática extremo a extremo de 0 a 100: compara el borrador "
        "con un caché congelado de hechos extraídos de los PDFs y unido por `case_number`, nombre, SHA-256 "
        "y hash del prompt. Los fallos y faltantes valen cero. El prompt solo "
        "define qué datos del PDF fueron revelados al sistema; no se usa como verdad de referencia. "
        "**Precision*** penaliza normas, fechas, plazos, expedientes y referencias de artículos adicionales; "
        "**Recall*** mide cuáles de esos identificadores se recuperaron. No detectan toda invención semántica. "
        "El asterisco indica que son métricas automáticas, no una evaluación jurídica humana."
    )
    interpretation = (
        "## La calidad se estabiliza cerca de 86%\n\n"
        "El aumento de contexto no mejora de forma monotónica. Con embedding 4B, RAG 8.192 y Ollama 16.384 "
        "produce el mayor valor observado (C15), pero C01, C02, C03, C14 y C16 permanecen estadísticamente "
        "muy próximos. En 0.6B, aumentar Ollama de 8.192 a 32.768 tampoco garantiza una mejora; la mejor "
        "combinación completa es C19. El principal deterioro no provino del tamaño de contexto sino de perfiles "
        "restrictivos que generaron fallos: C04 tuvo 16 y C06 tuvo 86."
    )
    field_scores = winner.get("field_accuracy_e2e") or {}
    field_detail = (
        "## Qué explica el puntaje de C15\n\n"
        f"Organismo {_pct(field_scores.get('organismo')):.1f}%, objeto "
        f"{_pct(field_scores.get('objeto')):.1f}%, dependencia "
        f"{_pct(field_scores.get('dependencia')):.1f}%, fecha/plazo "
        f"{_pct(field_scores.get('fecha_plazo_vigencia')):.1f}%, normas "
        f"{_pct(field_scores.get('normas_citadas')):.1f}%, artículos "
        f"{_pct(field_scores.get('articulos_resolutivos')):.1f}% y datos críticos "
        f"{_pct(field_scores.get('datos_criticos')):.1f}%. Persona/cargo no se puntúa "
        "automáticamente porque el caché no contiene ese campo con cobertura suficiente."
    )
    next_steps = (
        "## Recomendación para producción\n\n"
        "1. **Candidata:** C15 — embedding 4B/2.560, RAG 8.192, Ollama 16.384, `top_k=8`, pool 24 y score mínimo 0.\n"
        "2. **Control humano:** revisar una muestra estratificada de los 1.000 pares PDF-output y adjudicar "
        "organismo, objeto, cargos, dependencia, plazos, normas, artículos y datos críticos.\n"
        "3. **Regla de promoción:** confirmar que C15 conserve la ventaja en Accuracy jurídica y que no aumente "
        "las invenciones materiales. Hasta entonces, la recomendación es técnica y provisional."
    )
    caveats = (
        "## Límites que cambian la interpretación\n\n"
        "- Se analizaron 19 corridas, pero 18 configuraciones únicas: C02 y C14 son una réplica exacta de parámetros "
        "y sus resultados casi idénticos respaldan la repetibilidad.\n"
        "- La referencia usada es un caché congelado de hechos extraídos de los 1.000 PDFs y ligado a sus SHA-256; "
        "la carpeta binaria original no está actualmente en este checkout.\n"
        "- La extracción automática no comprende por completo equivalencias jurídicas ni puede decidir por sí sola "
        "si una paráfrasis conserva todos los efectos legales.\n"
        "- C09 es parcial (103/1.000) y se muestra para trazabilidad, pero no participa del ranking.\n"
        "- F1 se conserva en los datos técnicos, pero se omite del reporte ejecutivo porque no agrega una decisión "
        "distinta a Precision y Recall para esta audiencia."
    )

    return {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": title,
            "description": "Comparación reproducible de fidelidad factual sobre 1.000 decretos de holdout.",
            "generatedAt": generated_at,
            "charts": [
                {
                    "id": "accuracy_by_case",
                    "title": "Fidelidad factual automática por configuración",
                    "subtitle": "Accuracy E2E, de mejor a peor · Azul: 4B · Naranja: 0.6B · C09† es parcial",
                    "type": "bar",
                    "dataset": "accuracy_by_case",
                    "source": source_summary,
                    "valueFormat": "number",
                    "palette": {"kind": "categorical"},
                    "encodings": {
                        "x": {"field": "caso", "type": "nominal", "label": "Caso"},
                        "y": {"field": "accuracy", "type": "quantitative", "label": "%", "format": "number"},
                        "color": {"field": "modelo", "type": "nominal", "label": "Modelo"},
                        "tooltip": [
                            {"field": "rag", "type": "quantitative", "label": "RAG"},
                            {"field": "ollama", "type": "quantitative", "label": "Ollama"},
                            {"field": "top_k", "type": "quantitative", "label": "top_k"},
                            {"field": "score_min", "type": "quantitative", "label": "Score mínimo"},
                            {"field": "exito", "type": "quantitative", "label": "Éxito (%)"}
                        ]
                    }
                }
            ],
            "tables": [
                {
                    "id": "all_runs",
                    "title": "Las 19 configuraciones y sus resultados",
                    "subtitle": "Valores porcentuales; *métricas automáticas contra referencia PDF",
                    "dataset": "all_runs",
                    "source": source_summary,
                    "density": "compact",
                    "defaultSort": {"field": "case_coverage", "direction": "asc"},
                    "columns": [
                        {"field": "case_coverage", "label": "Caso · cobertura", "type": "text"},
                        {"field": "parametros", "label": "Parámetros", "type": "text"},
                        {"field": "accuracy", "label": "Accuracy*", "format": "number"},
                        {"field": "precision_recall", "label": "Precision* / Recall*", "type": "text"}
                    ]
                }
            ],
            "sources": [source_summary, source_catalog],
            "blocks": [
                {"id": "title", "type": "markdown", "body": f"# {title}"},
                {"id": "executive_summary", "type": "markdown", "body": summary_body, "sourceId": "benchmark_summary"},
                {"id": "definitions", "type": "markdown", "body": definitions, "sourceId": "benchmark_summary"},
                {"id": "accuracy_chart", "type": "chart", "chartId": "accuracy_by_case"},
                {"id": "interpretation", "type": "markdown", "body": interpretation, "sourceId": "benchmark_summary"},
                {"id": "field_detail", "type": "markdown", "body": field_detail, "sourceId": "benchmark_summary"},
                {"id": "runs_table", "type": "table", "tableId": "all_runs"},
                {"id": "next_steps", "type": "markdown", "body": next_steps, "sourceId": "benchmark_summary"},
                {"id": "caveats", "type": "markdown", "body": caveats}
            ]
        },
        "snapshot": {
            "version": 1,
            "generatedAt": generated_at,
            "status": "ready",
            "datasets": {"accuracy_by_case": chart_rows, "all_runs": table_rows},
            "accessIssues": []
        },
        "sources": sources
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--generated-at", default="2026-08-21T21:23:00-03:00")
    args = parser.parse_args()
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    rows = summary["summaries"]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    artifact = _artifact(summary, args.generated_at)
    (args.output_dir / "artifact.json").write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    full = [row for row in rows if row["comparable_full_run"]]
    winner = min(full, key=lambda row: row["quality_rank"])
    decision = (
        "# Benchmark factual del holdout de 1.000 decretos\n\n"
        "## Resultado ejecutivo\n\n"
        f"La mejor estimación puntual es **{winner['case_id']}**: embedding 4B/2.560, "
        f"RAG {winner['rag_context']}, Ollama {winner['ollama_context']}, `top_k={winner['top_k']}`, "
        f"pool {winner['candidate_pool']} y score mínimo {winner['minimum_score']}. Obtuvo "
        f"**{_pct(winner['factual_fidelity_e2e']):.2f}%** de fidelidad factual extremo a extremo "
        f"y {winner['succeeded']}/1.000 outputs exitosos.\n\n"
        "La ventaja sobre otras configuraciones 4B es pequeña: existe una meseta de calidad alrededor de 86%. "
        "Por eso C15 es la candidata técnica, no una certificación jurídica definitiva.\n\n"
        "## Tabla completa\n\n"
        + _markdown_table(rows)
        + "\n\n## Definición de métricas\n\n"
        "- **Accuracy***: fidelidad factual por campos contra hechos derivados del PDF, con fallos y faltantes en cero para el resultado extremo a extremo.\n"
        "- **Precision***: proporción de afirmaciones materiales del output respaldadas por la referencia.\n"
        "- **Recall***: proporción de afirmaciones materiales esperadas que aparecen en el output.\n"
        "- El asterisco marca evaluación automática. La decisión jurídica final requiere adjudicación humana.\n"
    )
    (args.output_dir / "BENCHMARK_DECISION.md").write_text(decision, encoding="utf-8")
    print(f"artifact={args.output_dir / 'artifact.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
