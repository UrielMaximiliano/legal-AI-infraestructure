#!/usr/bin/env python3
"""Compute a reproducible, provisional PDF-to-output alignment benchmark.

This is an automated screening layer, not a replacement for legal
adjudication. It extracts reference facts from InfoLEG PDFs with pypdf and
compares them with the structured candidate output. Results are explicitly
labelled ``AUTOMATED_PROVISIONAL_TEXT_ALIGNMENT``; human TP/FP/FN review is
still required before calling them legal Accuracy, Precision, or Recall.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

from pypdf import PdfReader


STOPWORDS = {
    "a", "al", "ante", "con", "contra", "de", "del", "desde", "durante", "e",
    "el", "en", "entre", "es", "esta", "este", "la", "las", "lo", "los", "para",
    "por", "que", "se", "su", "sus", "un", "una", "y", "o", "u", "como", "del",
    "dicho", "dicha", "presente", "medida", "mismo", "misma", "segun", "según",
    "decreto", "articulo", "articulos", "art", "nro", "nros", "numero", "numeros",
}
FIELD_NAMES = (
    "organismo", "objeto", "persona_cargo", "dependencia", "fecha_plazo_vigencia",
    "normas_citadas", "articulos_resolutivos", "datos_criticos",
)


def normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", text or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.lower().replace("�", " ")
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def tokens(text: str) -> set[str]:
    return {token for token in normalize(text).split() if len(token) > 2 and token not in STOPWORDS}


def overlap(expected: str, candidate: str, threshold: float = 0.65) -> bool:
    left = tokens(expected)
    right = tokens(candidate)
    if not left:
        return False
    if normalize(expected) in normalize(candidate):
        return True
    return len(left & right) / len(left) >= threshold


def read_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def clean_lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]


def extract_reference(text: str) -> dict[str, Any]:
    lines = clean_lines(text)
    joined = "\n".join(lines)
    decree_index = next((i for i, line in enumerate(lines) if re.search(r"\bDecreto\b", line, re.I)), 0)
    authority = ""
    for line in reversed(lines[:decree_index]):
        letters = re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", "", line)
        if len(letters) >= 8 and letters.upper() == letters:
            authority = line
            break
    title_parts: list[str] = []
    for line in lines[decree_index + 1 :]:
        if re.match(r"^(Bs\.?\s*As\.?|Buenos Aires)", line, re.I):
            break
        if line.upper() not in {"VISTO:", "VISTOS:", "CONSIDERANDO:", "CONSIDERANDO"}:
            title_parts.append(line)
        if len(" ".join(title_parts)) > 700:
            break
    date = next((line for line in lines if re.match(r"^(Bs\.?\s*As\.?|Buenos Aires)", line, re.I)), "")

    body = joined[joined.upper().find("DECRETA") :] if "DECRETA" in joined.upper() else joined
    article_matches = list(
        re.finditer(
            r"\b(?:Art(?:í|i)culo|Art\.)\s*(\d+)\s*[º°ª]?\s*[–—-]?\s*(.*?)(?=\b(?:Art(?:í|i)culo|Art\.)\s*\d+\b|\bANEXO\b|$)",
            body,
            re.I | re.S,
        )
    )
    articles = {
        int(match.group(1)): re.sub(r"\s+", " ", match.group(2)).strip()
        for match in article_matches
        if match.group(2).strip()
    }

    norm_matches = re.findall(
        r"\b(?:Decreto|Ley|Resoluci[oó]n|Decisi[oó]n Administrativa)\s*(?:N[°ºo]\s*)?([0-9]+(?:/[0-9]{2,4})?)",
        joined,
        re.I,
    )
    norms = sorted({normalize(value) for value in norm_matches if value})

    critical_patterns = [
        r"[^.]{0,80}\bpr[oó]rrog\w*\b[^.]{0,140}",
        r"[^.]{0,80}\bdesignaci[oó]n\w*\b[^.]{0,140}",
        r"[^.]{0,80}\bces\w*\b[^.]{0,140}",
        r"[^.]{0,80}\b\d+\s+d[ií]as?\b[^.]{0,100}",
        r"[^.]{0,80}\bExpediente\b[^.]{0,120}",
    ]
    critical = []
    for pattern in critical_patterns:
        critical.extend(re.findall(pattern, joined, re.I))
    critical = list(dict.fromkeys(re.sub(r"\s+", " ", value).strip() for value in critical))[:20]

    organizations = [
        line for line in lines
        if len(re.sub(r"[^A-Za-z]", "", line)) >= 10
        and re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", "", line).upper()
        == re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", "", line)
    ][:12]
    facts: list[dict[str, str]] = []
    if authority:
        facts.append({"fact_id": "organismo", "field": "organismo", "text": authority})
    if title_parts:
        facts.append({"fact_id": "objeto", "field": "objeto", "text": " ".join(title_parts)})
    if date:
        facts.append({"fact_id": "fecha", "field": "fecha_plazo_vigencia", "text": date})
    for index, organization in enumerate(organizations):
        facts.append({"fact_id": f"dependencia-{index}", "field": "dependencia", "text": organization})
    for index, norm in enumerate(norms):
        facts.append({"fact_id": f"norma-{index}", "field": "normas_citadas", "text": norm})
    for number, article in sorted(articles.items()):
        facts.append({"fact_id": f"articulo-{number}", "field": "articulos_resolutivos", "text": article})
    for index, item in enumerate(critical):
        facts.append({"fact_id": f"critico-{index}", "field": "datos_criticos", "text": item})
    return {
        "authority": authority,
        "object": " ".join(title_parts),
        "date": date,
        "organizations": organizations,
        "norms": norms,
        "articles": articles,
        "critical": critical,
        "facts": facts,
    }


def flatten(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(flatten(item) for item in value)
    if isinstance(value, dict):
        return " ".join(flatten(item) for key, item in value.items() if key not in {"citation_ids", "sources"})
    return ""


def candidate_facts(output: dict[str, Any]) -> tuple[str, dict[int, str]]:
    articles: dict[int, str] = {}
    for article in output.get("articles", []) or []:
        if isinstance(article, dict) and article.get("number") is not None:
            articles[int(article["number"])] = str(article.get("text", ""))
    return flatten(output), articles


def field_score(reference: dict[str, Any], candidate_text: str, candidate_articles: dict[int, str], field: str) -> float:
    if field == "organismo":
        expected = reference["authority"]
        candidate = candidate_text
    elif field == "objeto":
        expected = reference["object"]
        candidate = candidate_text
    elif field == "fecha_plazo_vigencia":
        expected = reference["date"] + " " + " ".join(reference["critical"])
        candidate = candidate_text
    elif field == "dependencia":
        expected = " ".join(reference["organizations"])
        candidate = candidate_text
    elif field == "normas_citadas":
        expected = " ".join(reference["norms"])
        candidate = candidate_text
    elif field == "articulos_resolutivos":
        if not reference["articles"]:
            return 0.0
        values = [1.0 if number in candidate_articles and overlap(text, candidate_articles[number]) else 0.0 for number, text in reference["articles"].items()]
        ratio = sum(values) / len(values)
        return 1.0 if ratio >= 0.8 else 0.5 if ratio >= 0.4 else 0.0
    elif field == "datos_criticos":
        expected = " ".join(reference["critical"])
        candidate = candidate_text
    else:
        return 0.0
    if not tokens(expected):
        return 0.0
    if overlap(expected, candidate, threshold=0.8):
        return 1.0
    if overlap(expected, candidate, threshold=0.4):
        return 0.5
    return 0.0


def evaluate_case(case_path: Path, pdf_root: Path, reference_cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    record = json.loads(case_path.read_text(encoding="utf-8"))
    reference_pdf = str(record.get("reference_pdf", ""))
    pdf_path = pdf_root / reference_pdf
    row: dict[str, Any] = {
        "run": case_path.parent.parent.name,
        "case_number": int(record.get("case_number", 0)),
        "reference_pdf": reference_pdf,
        "reference_pdf_exists": pdf_path.exists(),
        "status": record.get("status"),
        "mode": "AUTOMATED_PROVISIONAL_TEXT_ALIGNMENT",
        "accuracy": None,
        "tp": None,
        "fp": None,
        "fn": None,
        "precision": None,
        "recall": None,
        "f1": None,
        "reason": None,
    }
    if record.get("status") != "SUCCEEDED":
        row["reason"] = "output_not_succeeded"
        return row
    if not pdf_path.exists():
        row["reason"] = "reference_pdf_missing"
        return row
    if reference_pdf not in reference_cache:
        text = read_pdf(pdf_path)
        reference_cache[reference_pdf] = extract_reference(text)
    reference = reference_cache[reference_pdf]
    candidate_text, candidate_articles = candidate_facts(record.get("output", {}))
    scores = {field: field_score(reference, candidate_text, candidate_articles, field) for field in FIELD_NAMES}
    expected = reference["facts"]
    tp = sum(1 for fact in expected if overlap(fact["text"], candidate_text, threshold=0.65))
    fn = len(expected) - tp
    candidate_units = [candidate_articles[number] for number in candidate_articles]
    fp = sum(1 for unit in candidate_units if unit and not any(overlap(fact["text"], unit, threshold=0.65) for fact in expected))
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else None
    row.update({
        "accuracy": sum(scores.values()) / len(FIELD_NAMES),
        "field_scores": scores,
        "gold_fact_count": len(expected),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    })
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf-root", type=Path, required=True)
    parser.add_argument("--outputs", type=Path, nargs="+", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    cases = [path for source in args.outputs for path in source.glob("case-*.json")]
    if not cases:
        raise SystemExit("no direct case-*.json files found; pass each run's cases/ directory")
    cache: dict[str, dict[str, Any]] = {}
    rows = [evaluate_case(path, args.pdf_root, cache) for path in sorted(cases)]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "schema_version": "decree-pdf-proxy.v1",
        "evaluation_mode": "AUTOMATED_PROVISIONAL_TEXT_ALIGNMENT",
        "legal_metrics_status": "PROVISIONAL_NOT_HUMAN_ADJUDICATED",
        "caveats": [
            "PDF facts are extracted automatically with pypdf.",
            "TP/FP/FN use normalized token alignment and are not legal judgments.",
            "Human review is required before production decisions or legal Accuracy claims.",
        ],
        "pdfs_loaded": len(cache),
        "rows": rows,
    }
    (args.output_dir / "pdf-proxy-evaluation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (args.output_dir / "pdf-gold-facts.auto.jsonl").open("w", encoding="utf-8") as handle:
        for reference_pdf, reference in sorted(cache.items()):
            pdf_path = args.pdf_root / reference_pdf
            digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
            handle.write(json.dumps({
                "reference_pdf": reference_pdf,
                "reference_sha256": digest,
                "facts": reference["facts"],
                "field_candidates": {
                    "organismo": reference["authority"],
                    "objeto": reference["object"],
                    "fecha_plazo_vigencia": reference["date"],
                    "dependencia": reference["organizations"],
                    "normas_citadas": reference["norms"],
                    "articulos_resolutivos": reference["articles"],
                    "datos_criticos": reference["critical"],
                },
            }, ensure_ascii=False) + "\n")
    columns = ["run", "case_number", "reference_pdf", "reference_pdf_exists", "status", "accuracy", "tp", "fp", "fn", "precision", "recall", "f1", "reason"]
    with (args.output_dir / "pdf-proxy-evaluation.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows({column: row.get(column) for column in columns} for row in rows)
    print(f"rows={len(rows)} pdfs_loaded={len(cache)} output_dir={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
