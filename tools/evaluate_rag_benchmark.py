"""Evaluate RAG benchmark outputs against reserved PDF references."""

# ruff: noqa: E501 -- embedded HTML is intentionally kept readable as a template.

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import re
import statistics
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pypdf import PdfReader

STOPWORDS = {
    "a",
    "al",
    "ante",
    "bajo",
    "con",
    "contra",
    "de",
    "del",
    "desde",
    "durante",
    "e",
    "el",
    "en",
    "entre",
    "es",
    "esta",
    "la",
    "las",
    "lo",
    "los",
    "o",
    "para",
    "por",
    "que",
    "se",
    "sin",
    "sobre",
    "su",
    "sus",
    "un",
    "una",
    "y",
}
ENTITY_PATTERNS = (
    re.compile(
        r"\b(?:ley|decreto|resolucion|disposicion)\s+(?:n[°ºo]\s*)?\d+[/-]\d{2,4}\b",
        re.I,
    ),
    re.compile(r"\bexpediente\s+(?:n[°ºo]\s*)?[A-Z0-9./-]{4,}\b", re.I),
    re.compile(r"\b\d{2}/\d{2}/\d{4}\b"),
    re.compile(r"\b\d{2}-\d{8}-\d\b"),
    re.compile(r"\$\s*[\d.,]+"),
)


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def tokens(value: str) -> set[str]:
    return {
        token
        for token in normalize(value).split()
        if len(token) > 2 and token not in STOPWORDS
    }


def f1(left: set[str], right: set[str]) -> tuple[float, float, float]:
    if not left and not right:
        return 1.0, 1.0, 1.0
    overlap = len(left & right)
    precision = overlap / len(left) if left else 0.0
    recall = overlap / len(right) if right else 0.0
    score = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, score


def entities(value: str) -> set[str]:
    found: set[str] = set()
    for pattern in ENTITY_PATTERNS:
        found.update(normalize(match.group(0)) for match in pattern.finditer(value))
    return found


def extract_pdf(path: Path, expected_sha256: str) -> str:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError(f"PDF_HASH_MISMATCH:{path.name}")
    return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


def render_output(output: dict[str, Any]) -> str:
    parts: list[str] = [output.get("title", "")]
    for key in ("visto", "considerandos"):
        parts.extend(item.get("text", "") for item in output.get(key, []))
    parts.append(output.get("dispositive_intro", ""))
    parts.extend(item.get("text", "") for item in output.get("articles", []))
    parts.extend(output.get(key, "") for key in ("closing", "authority", "signature"))
    return "\n".join(part for part in parts if part)


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def retrieval_proxy(
    sources: list[dict[str, Any]], reference_tokens: set[str], k: int
) -> tuple[float, float, int]:
    relevant = []
    for source in sources:
        title_tokens = tokens(str(source.get("title", "")))
        relevant.append(len(title_tokens & reference_tokens) >= 2)
    total_relevant = sum(relevant)
    at_k = sum(relevant[:k])
    precision = at_k / min(k, len(sources)) if sources else 0.0
    recall = at_k / total_relevant if total_relevant else 0.0
    return precision, recall, total_relevant


def evaluate_case(case: dict[str, Any], pdf_root: Path) -> dict[str, Any]:
    base = {
        "case_number": case["case_number"],
        "external_id": case["external_id"],
        "name": case["name"],
        "status": case["status"],
        "error_code": case.get("error_code"),
        "total_ms": case.get("total_ms"),
    }
    reference = extract_pdf(pdf_root / case["reference_pdf"], case["reference_sha256"])
    if case["status"] != "SUCCEEDED" or not case.get("output"):
        return {**base, "accuracy": 0.0, "evaluable": False}
    output = case["output"]
    generated = render_output(output)
    prompt = case["input"]
    prompt_text = " ".join(
        [prompt["object_text"], prompt["topic"], prompt["organization"]]
    )
    entity_p, entity_r, entity_f1 = f1(
        entities(generated), entities(reference) | entities(prompt_text)
    )
    _, _, content_f1 = f1(tokens(generated), tokens(reference))
    _, _, prompt_f1 = f1(tokens(generated), tokens(prompt_text))
    title_is_decree = "decreto" in normalize(str(output.get("title", "")))
    required = (
        bool(output.get("title")),
        bool(output.get("visto")),
        bool(output.get("considerandos")),
        bool(output.get("dispositive_intro")),
        bool(output.get("articles")),
        bool(output.get("closing")),
        bool(output.get("authority")),
        bool(output.get("signature")),
        title_is_decree,
    )
    structure = sum(required) / len(required)
    source_ids = {item["citation_id"] for item in output.get("sources", [])}
    cited_groups: list[list[str]] = []
    for key in ("visto", "considerandos", "articles"):
        cited_groups.extend(
            item.get("citation_ids", []) for item in output.get(key, [])
        )
    used_ids = {citation for group in cited_groups for citation in group}
    citation_validity = len(used_ids & source_ids) / len(used_ids) if used_ids else 0.0
    citation_coverage = (
        sum(bool(group) for group in cited_groups) / len(cited_groups)
        if cited_groups
        else 0.0
    )
    citation_score = (citation_validity + citation_coverage) / 2
    accuracy = 100 * (
        0.35 * entity_f1
        + 0.20 * content_f1
        + 0.15 * prompt_f1
        + 0.15 * structure
        + 0.15 * citation_score
    )
    source_list = list(output.get("sources", []))
    p3, r3, relevant = retrieval_proxy(source_list, tokens(reference), 3)
    p5, r5, _ = retrieval_proxy(source_list, tokens(reference), 5)
    p8, r8, _ = retrieval_proxy(source_list, tokens(reference), 8)
    return {
        **base,
        "evaluable": True,
        "accuracy": round(accuracy, 2),
        "entity_precision": round(entity_p, 4),
        "entity_recall": round(entity_r, 4),
        "entity_f1": round(entity_f1, 4),
        "content_f1": round(content_f1, 4),
        "prompt_fidelity_f1": round(prompt_f1, 4),
        "structure_score": round(structure, 4),
        "citation_validity": round(citation_validity, 4),
        "citation_coverage": round(citation_coverage, 4),
        "precision_at_3_proxy": round(p3, 4),
        "precision_at_5_proxy": round(p5, 4),
        "precision_at_8_proxy": round(p8, 4),
        "recall_at_3_proxy": round(r3, 4),
        "recall_at_5_proxy": round(r5, 4),
        "recall_at_8_proxy": round(r8, 4),
        "proxy_relevant_sources": relevant,
        "hallucinated_entities": sorted(
            entities(generated) - entities(reference) - entities(prompt_text)
        ),
        "missing_reference_entities": sorted(entities(reference) - entities(generated)),
        "title_is_decree": title_is_decree,
    }


def average(rows: Iterable[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get("evaluable") and key in row]
    return round(statistics.fmean(values), 4) if values else None


def write_html(path: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    def band(value: float) -> tuple[str, str]:
        if value >= 80:
            return "Sólido", "good"
        if value >= 60:
            return "Aceptable", "warn"
        if value >= 40:
            return "A mejorar", "low"
        return "Crítico", "bad"

    def card(label: str, value: float, explanation: str) -> str:
        status, css_class = band(value)
        return (
            f"<article class='card {css_class}'><span>{html.escape(label)}</span>"
            f"<strong>{value:.1f}%</strong><b>{status}</b>"
            f"<small>{html.escape(explanation)}</small>"
            f"<div class='bar'><i style='width:{min(100, max(0, value)):.1f}%'></i></div></article>"
        )

    cards = "".join(
        (
            card(
                "Calidad integral",
                summary["accuracy_end_to_end"],
                "Incluye respuestas correctas, incompletas y fallos técnicos.",
            ),
            card(
                "Calidad cuando responde",
                summary["accuracy_average"],
                "Evalúa solamente los decretos que el sistema logró generar.",
            ),
            card(
                "Éxito técnico",
                summary["technical_success_rate"],
                "Porcentaje de solicitudes que terminaron con una respuesta válida.",
            ),
            card(
                "Fidelidad factual y normativa",
                summary["entity_f1_average"] * 100,
                "Coincidencia de personas, organismos, normas, fechas y referencias.",
            ),
            card(
                "Estructura jurídica",
                summary["structure_average"] * 100,
                "Respeta secciones y forma típica de un decreto.",
            ),
            card(
                "Citas verificables",
                summary["citation_validity_average"] * 100,
                "Las fuentes citadas pertenecen al contexto recuperado.",
            ),
        )
    )
    body_rows = "".join(
        "<tr>"
        f"<td>{row['case_number']:04d}</td><td>{html.escape(row['name'])}</td>"
        f"<td class='num score'>{row['accuracy']:.1f}%</td>"
        f"<td>{'OK' if row['status'] == 'SUCCEEDED' else html.escape(str(row.get('error_code')))}</td>"
        f"<td class='num'>{(row.get('entity_f1') or 0) * 100:.1f}%</td>"
        f"<td class='num'>{(row.get('structure_score') or 0) * 100:.1f}%</td>"
        f"<td class='num'>{(row.get('precision_at_5_proxy') or 0) * 100:.1f}%</td>"
        f"<td class='num'>{(row.get('recall_at_5_proxy') or 0) * 100:.1f}%</td>"
        f"<td class='num'>{(row.get('total_ms') or 0) / 1000:.2f}s</td>"
        "</tr>"
        for row in rows
    )
    overall_status, overall_class = band(summary["accuracy_end_to_end"])
    friendly_errors = {
        "RAG_OUTPUT_INVALID": "Salida del modelo inválida después de la reparación",
        "SEMANTIC_SEARCH_AUDIT_UNAVAILABLE": "Auditoría de búsqueda no disponible",
    }
    failure_rows = "".join(
        "<tr>"
        f"<td>{html.escape(friendly_errors.get(code, code))}</td>"
        f"<td class='num'>{count}</td>"
        f"<td class='num'>{100 * count / summary['cases']:.1f}%</td>"
        "</tr>"
        for code, count in sorted(
            summary["error_code_breakdown"].items(),
            key=lambda item: (-item[1], item[0]),
        )
    )
    path.write_text(
        f"""<!doctype html><html lang='es'><meta charset='utf-8'>
<title>Evaluación del asistente jurídico</title>
<style>
:root{{--ink:#162033;--muted:#596579;--paper:#fff;--bg:#f1f5f9;--line:#d9e1ea}}
*{{box-sizing:border-box}}body{{font:15px system-ui;margin:0;color:var(--ink);background:var(--bg)}}
main{{max-width:1440px;margin:auto;padding:36px}}h1{{margin:0 0 6px;font-size:34px}}h2{{margin-top:34px}}
.lead{{font-size:18px;color:var(--muted);max-width:1000px}}.verdict{{padding:18px 22px;border-radius:12px;background:white;border-left:8px solid #d97706;margin:22px 0}}
.verdict strong{{font-size:20px}}.verdict.bad{{border-color:#dc2626}}.verdict.low{{border-color:#d97706}}.verdict.warn{{border-color:#eab308}}.verdict.good{{border-color:#16a34a}}
.cards{{display:grid;grid-template-columns:repeat(3,minmax(210px,1fr));gap:14px;margin:24px 0}}
.card{{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:18px;display:flex;flex-direction:column;gap:6px}}
.card span{{color:var(--muted);font-weight:600}}.card strong{{font-size:30px}}.card b{{font-size:13px}}.card small{{min-height:42px;color:var(--muted)}}
.bar{{height:7px;background:#e5e7eb;border-radius:9px;overflow:hidden;margin-top:8px}}.bar i{{display:block;height:100%;background:#dc2626}}.low .bar i{{background:#d97706}}.warn .bar i{{background:#eab308}}.good .bar i{{background:#16a34a}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}.panel{{background:white;border:1px solid var(--line);border-radius:12px;padding:18px}}.panel li{{margin:8px 0}}
.config{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}}.config div{{background:#eaf0f6;padding:11px;border-radius:8px}}.config b{{display:block}}
.table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:12px}}table{{width:100%;border-collapse:collapse;background:white;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid #e5e7e9;text-align:left}}
th{{background:#172033;color:white;position:sticky;top:0}}.num{{text-align:right}}.score{{font-weight:700}}
.foot{{color:var(--muted);font-size:13px;line-height:1.55}}@media(max-width:900px){{.cards,.grid,.config{{grid-template-columns:1fr}}main{{padding:20px}}}}
</style><main>
<h1>Evaluación del asistente jurídico</h1>
<p class='lead'>Comparación automática entre decretos generados por el RAG y sus PDF oficiales de referencia. Los PDF se usan únicamente para medir el resultado: nunca se entregan al modelo.</p>
<section class='verdict {overall_class}'><strong>Diagnóstico general: {overall_status}</strong><br>La estructura jurídica y las citas son fuertes, pero la fidelidad de hechos y normas todavía necesita mejorar antes de usar el sistema en producción sin revisión humana.</section>
<div class='cards'>{cards}</div>
<div class='grid'><section class='panel'><h2>Qué está funcionando bien</h2><ul><li>Los decretos generados respetan mayormente la estructura jurídica.</li><li>Las citas indicadas se pueden resolver contra los antecedentes recuperados.</li><li>El proceso es reproducible y registra cada caso de forma independiente.</li></ul></section>
<section class='panel'><h2>Qué debemos mejorar</h2><ul><li>Coincidencia de nombres, fechas, organismos y normas con el decreto original.</li><li>Cobertura: recuperar una mayor parte de la información relevante.</li><li>Robustez técnica para que todos los prompts produzcan una salida válida.</li></ul></section></div>
<h2>Por qué fallaron algunos casos</h2><section class='panel'><p>Los fallos se contabilizan con calidad integral igual a cero. Se separan los errores de formato del modelo de los problemas de infraestructura para evitar conclusiones engañosas.</p><table><thead><tr><th>Causa</th><th>Casos</th><th>Sobre el total</th></tr></thead><tbody>{failure_rows}</tbody></table></section>
<h2>Configuración evaluada</h2><section class='config'><div><b>Generación</b>qwen3.6:35b</div><div><b>Embeddings</b>qwen3-embedding:4b</div><div><b>Vector</b>2.560 dimensiones</div><div><b>Contexto</b>8.192 tokens</div><div><b>Recuperación</b>Top 8 antecedentes</div><div><b>Inferencia</b>1 solicitud simultánea</div><div><b>Corpus</b>9.000 decretos</div><div><b>Chunks</b>65.916 fragmentos</div></section>
<h2>Resultados por decreto</h2><div class='table-wrap'><table><thead><tr><th>Caso</th><th>Decreto original</th><th>Calidad total</th><th>Resultado técnico</th><th>Fidelidad factual</th><th>Estructura jurídica</th><th>Precisión recuperación*</th><th>Cobertura recuperación*</th><th>Tiempo</th></tr></thead><tbody>{body_rows}</tbody></table></div>
<section class='panel foot'><h2>Cómo leer las métricas</h2><p><b>Calidad integral</b> cuenta también los fallos técnicos como cero. <b>Calidad cuando responde</b> analiza solo salidas válidas. <b>Fidelidad factual</b> compara hechos, normas, nombres y fechas. <b>Precisión</b> estima cuánto de lo recuperado fue útil; <b>cobertura</b>, cuánto del original logró cubrir. Estas dos últimas son aproximaciones léxicas y no sustituyen una evaluación jurídica humana. Latencia p50: {summary['latency_p50_ms'] / 1000:.2f}s; p95: {summary['latency_p95_ms'] / 1000:.2f}s.</p><p>Escala visual: verde 80–100; amarillo 60–79; naranja 40–59; rojo menor a 40.</p></section>
</main></html>""",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--pdf-root", type=Path, required=True)
    args = parser.parse_args()
    case_files = sorted((args.results / "cases").glob("case-*.json"))
    rows = [
        evaluate_case(json.loads(path.read_text(encoding="utf-8")), args.pdf_root)
        for path in case_files
    ]
    latencies = [float(row["total_ms"]) for row in rows if row.get("total_ms")]
    summary = {
        "cases": len(rows),
        "evaluable_cases": sum(bool(row.get("evaluable")) for row in rows),
        "technical_success_rate": round(
            100 * sum(row["status"] == "SUCCEEDED" for row in rows) / len(rows), 2
        ),
        "accuracy_average": average(rows, "accuracy"),
        "accuracy_end_to_end": round(
            statistics.fmean(float(row["accuracy"]) for row in rows), 4
        ),
        "entity_f1_average": average(rows, "entity_f1"),
        "content_f1_average": average(rows, "content_f1"),
        "prompt_fidelity_average": average(rows, "prompt_fidelity_f1"),
        "structure_average": average(rows, "structure_score"),
        "citation_validity_average": average(rows, "citation_validity"),
        "precision_at_5_proxy_average": average(rows, "precision_at_5_proxy"),
        "recall_at_5_proxy_average": average(rows, "recall_at_5_proxy"),
        "latency_p50_ms": percentile(latencies, 0.5),
        "latency_p95_ms": percentile(latencies, 0.95),
        "accuracy_formula": {
            "entity_f1": 0.35,
            "content_f1": 0.20,
            "prompt_fidelity_f1": 0.15,
            "structure": 0.15,
            "citations": 0.15,
        },
        "retrieval_metric_status": "LEXICAL_PROXY_NOT_HUMAN_GROUND_TRUTH",
        "error_code_breakdown": {
            code: sum(row.get("error_code") == code for row in rows)
            for code in sorted(
                {
                    str(row["error_code"])
                    for row in rows
                    if row.get("error_code")
                }
            )
        },
    }
    (args.results / "evaluation-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    columns = sorted({key for row in rows for key in row})
    with (args.results / "evaluation.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    write_html(args.results / "accuracy-report.html", summary, rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
