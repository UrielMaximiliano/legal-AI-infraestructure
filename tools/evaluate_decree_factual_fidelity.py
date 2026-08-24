#!/usr/bin/env python3
"""Evaluate factual fidelity of decree drafts against PDF-derived references.

The reference cache must have been extracted from the original holdout PDFs and
must contain ``reference_pdf`` and ``reference_sha256``.  A case is joined by
case number, PDF filename and SHA-256; mismatches fail closed.

This evaluator deliberately distinguishes two layers:

* ``factual_fidelity`` (reported as the automatic Accuracy proxy) is the
  equal-weight mean of applicable legal fields extracted from the PDF.
* Precision/Recall/F1 use only typed material claims (norms, dates, durations,
  expediente identifiers and article references).  They are not computed from
  arbitrary token counts.

The prompt is used only as a disclosure mask: facts intentionally removed from
the request (target decree number/date, signatures and publication boilerplate)
are not expected in the generated draft.  It is not treated as ground truth.
Human legal adjudication remains required before calling these legal metrics.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


EVALUATION_MODE = "AUTOMATED_PDF_FACTUAL_FIDELITY_V2"
PAIRWISE_CONFIDENCE_LEVEL = 0.95
FIELDS = (
    "organismo",
    "objeto",
    "persona_cargo",
    "dependencia",
    "fecha_plazo_vigencia",
    "normas_citadas",
    "articulos_resolutivos",
    "datos_criticos",
)
STOPWORDS = {
    "a", "al", "ante", "con", "contra", "de", "del", "desde", "durante",
    "e", "el", "en", "entre", "es", "esta", "este", "la", "las", "lo",
    "los", "o", "para", "por", "que", "se", "segun", "sin", "su", "sus",
    "un", "una", "y", "decreto", "articulo", "articulos", "nro", "numero",
    "presente", "medida", "mismo", "misma",
}
NOISE_EXACT = {
    "considerando", "la presidenta", "el presidente", "de la nacion argentina",
    "apellido y nombre s", "nombre y apellido", "decreta", "visto", "vistos",
}


def normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", text or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.lower().replace("�", " ")
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _tokens(text: str) -> Counter[str]:
    return Counter(
        token for token in normalize(text).split()
        if len(token) > 2 and token not in STOPWORDS
    )


def token_recall(expected: str, candidate: str) -> float:
    left = _tokens(expected)
    if not left:
        return 0.0
    right = _tokens(candidate)
    return _token_recall_counters(left, right)


def _token_recall_counters(left: Counter[str], right: Counter[str]) -> float:
    if not left:
        return 0.0
    overlap = sum(min(count, right[token]) for token, count in left.items())
    return overlap / sum(left.values())


def _clean_pdf_text(text: str) -> str:
    value = re.sub(r"https?://\S+", " ", text or "")
    value = re.sub(r"\bP[aá]gina\s+\d+\b", " ", value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip(" -—–.;,")


def _iter_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        if value.strip():
            yield value
    elif isinstance(value, list):
        for item in value:
            yield from _iter_values(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_values(item)


def _noise(value: str, field: str) -> bool:
    compact = normalize(value)
    if not compact or compact in NOISE_EXACT:
        return True
    if field == "dependencia":
        if len(compact.split()) < 2:
            return True
        if re.search(r"\b(apellido|nombre s|pagina|linkqr)\b", compact):
            return True
    if field == "articulos_resolutivos" and len(_tokens(value)) < 4:
        return True
    return False


def _deduplicate(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = _clean_pdf_text(raw)
        key = normalize(value)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def flatten_output(output: Any) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        return " ".join(flatten_output(item) for item in output)
    if isinstance(output, dict):
        return " ".join(
            flatten_output(value)
            for key, value in output.items()
            if key not in {"citation_ids", "sources", "source_url", "warnings"}
        )
    return ""


def disclosed_reference_fields(reference: dict[str, Any], prompt: str) -> dict[str, list[str]]:
    candidates = reference.get("field_candidates") or {}
    result: dict[str, list[str]] = {}
    for field in FIELDS:
        values = _deduplicate(_iter_values(candidates.get(field)))
        kept = [
            value for value in values
            if not _noise(value, field) and token_recall(value, prompt) >= 0.42
        ]
        if kept:
            result[field] = kept
    return result


def _words_number(value: str) -> str:
    return normalize(value).replace(" ", "_")


def material_claims(text: str) -> set[str]:
    """Extract typed, normalized material claims from Spanish legal text."""
    claims: set[str] = set()
    source = unicodedata.normalize("NFKC", text or "")
    for kind, number, year in re.findall(
        r"\b(Decreto|Ley|Resoluci[oó]n|Decisi[oó]n\s+Administrativa)\s*"
        r"(?:N(?:ro\.?|[°ºo])?\s*)?(\d{1,6})(?:\s*/\s*(\d{2,4}))?",
        source,
        flags=re.I,
    ):
        claims.add(f"norma:{normalize(kind).replace(' ', '_')}:{int(number)}:{year or '-'}")
    for day, month, year in re.findall(
        r"\b(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
        r"septiembre|octubre|noviembre|diciembre)\s+de\s+(\d{4})\b",
        source,
        flags=re.I,
    ):
        claims.add(f"fecha:{int(day)}:{normalize(month)}:{year}")
    for day, month, year in re.findall(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", source):
        claims.add(f"fecha_num:{int(day)}:{int(month)}:{year}")
    for amount, unit in re.findall(
        r"(?<!\d)\(?(\d{1,5})\)?\s+(d[ií]as?|mes(?:es)?|a[nñ]os?)\b",
        source,
        flags=re.I,
    ):
        claims.add(f"plazo:{int(amount)}:{_words_number(unit)}")
    for identifier in re.findall(
        r"\bExpediente\s+(?:N(?:ro\.?|[°ºo])?\s*)?([A-Z0-9:/.-]{4,})",
        source,
        flags=re.I,
    ):
        claims.add(f"expediente:{normalize(identifier).replace(' ', '')}")
    for article, inciso in re.findall(
        r"\bart[ií]culo\s+(\d{1,4})(?:\s*[,;]?\s*inciso\s+(\d{1,3}))?",
        source,
        flags=re.I,
    ):
        claims.add(f"articulo:{int(article)}:{int(inciso) if inciso else '-'}")
    return claims


def _claim_metrics(reference: set[str], candidate: set[str]) -> dict[str, int | float | None]:
    tp = len(reference & candidate)
    fp = len(candidate - reference)
    fn = len(reference - candidate)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def _fact_score(
    expected_tokens: Counter[str],
    protected: set[str],
    candidate_tokens: Counter[str],
    candidate_claims: set[str],
) -> float:
    score = _token_recall_counters(expected_tokens, candidate_tokens)
    if protected:
        claim_recall = len(protected & candidate_claims) / len(protected)
        score = 0.65 * score + 0.35 * claim_recall
    return score


def _prepare_reference(reference: dict[str, Any], prompt: str) -> dict[str, Any]:
    fields = disclosed_reference_fields(reference, prompt)
    reference_text = " ".join(value for values in fields.values() for value in values)
    prepared_fields = {
        field: [
            {"text": fact, "tokens": _tokens(fact), "claims": material_claims(fact)}
            for fact in facts
        ]
        for field, facts in fields.items()
    }
    return {"fields": prepared_fields, "claims": material_claims(reference_text)}


def evaluate_success(
    reference: dict[str, Any],
    prompt: str,
    output: Any,
    prepared: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate = flatten_output(output)
    prepared = prepared or _prepare_reference(reference, prompt)
    fields = prepared["fields"]
    candidate_tokens = _tokens(candidate)
    candidate_claims = material_claims(candidate)
    field_scores: dict[str, float] = {}
    for field, facts in fields.items():
        field_scores[field] = sum(
            _fact_score(
                fact["tokens"],
                fact["claims"],
                candidate_tokens,
                candidate_claims,
            )
            for fact in facts
        ) / len(facts)
    fidelity = sum(field_scores.values()) / len(field_scores) if field_scores else None
    reference_claims = prepared["claims"]
    claims = _claim_metrics(reference_claims, candidate_claims)
    return {
        "factual_fidelity": fidelity,
        "field_scores": field_scores,
        "applicable_fields": len(field_scores),
        "reference_claims": len(reference_claims),
        "candidate_claims": len(candidate_claims),
        **claims,
    }


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no}: expected object")
            rows.append(value)
    return rows


def _mean(values: Iterable[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    return statistics.fmean(clean) if clean else None


def _percentile(values: Iterable[float | None], percentile: float) -> float | None:
    clean = sorted(float(value) for value in values if value is not None)
    if not clean:
        return None
    position = (len(clean) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return clean[lower]
    return clean[lower] + (clean[upper] - clean[lower]) * (position - lower)


def _ci95(values: Iterable[float | None]) -> tuple[float | None, float | None]:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return None, None
    mean = statistics.fmean(clean)
    if len(clean) == 1:
        return mean, mean
    margin = 1.96 * statistics.stdev(clean) / math.sqrt(len(clean))
    return max(0.0, mean - margin), min(1.0, mean + margin)


def _paired_ci95(values: Iterable[float]) -> tuple[float, float, float]:
    """Return a paired mean delta and normal-approximation 95% interval."""
    clean = [float(value) for value in values]
    if not clean:
        raise ValueError("paired comparison requires at least one delta")
    mean = statistics.fmean(clean)
    if len(clean) == 1:
        return mean, mean, mean
    margin = 1.96 * statistics.stdev(clean) / math.sqrt(len(clean))
    return mean, mean - margin, mean + margin


def _load_catalog(path: Path) -> list[dict[str, Any]]:
    value = _read_json(path)
    runs = value.get("runs") if isinstance(value, dict) else None
    if not isinstance(runs, list) or not runs:
        raise ValueError("run catalog must contain a non-empty runs array")
    identifiers = [str(run.get("case_id")) for run in runs]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("duplicate case_id in run catalog")
    return runs


def _load_reference_cache(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_pdf: dict[str, dict[str, Any]] = {}
    by_hash: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(path):
        pdf = str(row.get("reference_pdf", ""))
        digest = str(row.get("reference_sha256", "")).lower()
        if not pdf or not digest:
            raise ValueError("reference cache row missing PDF or SHA-256")
        if pdf in by_pdf or digest in by_hash:
            raise ValueError(f"duplicate reference in cache: {pdf}")
        by_pdf[pdf] = row
        by_hash[digest] = row
    return by_pdf, by_hash


def _load_prompt_manifest(
    path: Path,
    prompts_dir: Path,
    expected_cases: int,
) -> dict[int, dict[str, Any]]:
    value = _read_json(path)
    records = value.get("records") if isinstance(value, dict) else None
    if not isinstance(records, list):
        raise ValueError("prompt manifest must contain a records array")
    if len(records) != expected_cases:
        raise ValueError(
            f"prompt manifest has {len(records)} records; expected {expected_cases}"
        )
    result: dict[int, dict[str, Any]] = {}
    for record in records:
        match = re.fullmatch(r"HOLDOUT-(\d{4})", str(record.get("case_id") or ""))
        if match is None:
            raise ValueError(f"invalid prompt case_id: {record.get('case_id')!r}")
        number = int(match.group(1))
        if not 1 <= number <= expected_cases or number in result:
            raise ValueError(f"duplicate or out-of-range prompt case: {number}")
        prompt_file = str(record.get("prompt_file") or "")
        prompt_path = prompts_dir / prompt_file
        if not prompt_file or not prompt_path.is_file():
            raise ValueError(f"prompt file missing for case {number}: {prompt_path}")
        prompt_text = prompt_path.read_text(encoding="utf-8").strip()
        if not prompt_text:
            raise ValueError(f"prompt file is empty for case {number}: {prompt_path}")
        result[number] = {
            "case_number": number,
            "reference_pdf": str(record.get("source_pdf") or ""),
            "reference_sha256": str(record.get("source_sha256") or "").lower(),
            "prompt_file": prompt_file,
            "prompt_text": prompt_text,
            "prompt_sha256": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
        }
    if set(result) != set(range(1, expected_cases + 1)):
        raise ValueError("prompt manifest does not cover the expected case range")
    return result


def _load_run_cases(cases_dir: Path, expected_cases: int) -> dict[int, dict[str, Any]]:
    cases: dict[int, dict[str, Any]] = {}
    for path in sorted(cases_dir.glob("case-*.json")):
        record = _read_json(path)
        number = int(record.get("case_number"))
        filename_match = re.fullmatch(r"case-(\d{4})\.json", path.name)
        filename_number = int(filename_match.group(1)) if filename_match else None
        if filename_number != number:
            raise ValueError(f"filename/case_number mismatch in {path}")
        if not 1 <= number <= expected_cases or number in cases:
            raise ValueError(
                f"duplicate or out-of-range case number {number} in {cases_dir}"
            )
        record["_path"] = str(path)
        cases[number] = record
    return cases


def _case_prompt(record: dict[str, Any]) -> str:
    source = record.get("input") or {}
    return str(source.get("prompt_text") or record.get("prompt") or "")


def _duration(record: dict[str, Any]) -> float | None:
    value = record.get("total_ms")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def evaluate_run(
    run: dict[str, Any],
    outputs_root: Path,
    reference_by_pdf: dict[str, dict[str, Any]],
    prompt_cases: dict[int, dict[str, Any]],
    expected_cases: int,
    prepared_cache: dict[tuple[str, str], dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    run_path = outputs_root / str(run["path"])
    cases = _load_run_cases(run_path / "cases", expected_cases)
    rows: list[dict[str, Any]] = []
    invalid_joins = 0
    for number in range(1, expected_cases + 1):
        record = cases.get(number)
        expected = prompt_cases[number]
        pdf = expected["reference_pdf"]
        digest = expected["reference_sha256"]
        prompt = expected["prompt_text"]
        reference = reference_by_pdf.get(pdf)
        if reference is None or str(reference.get("reference_sha256", "")).lower() != digest:
            raise ValueError(f"prompt/PDF cache mismatch for case {number}: {pdf}")
        cache_key = (digest, prompt)
        prepared = prepared_cache.get(cache_key)
        if prepared is None:
            prepared = _prepare_reference(reference, prompt)
            prepared_cache[cache_key] = prepared
        row: dict[str, Any] = {
            "case_id": run["case_id"],
            "case_number": number,
            "status": "MISSING",
            "reference_pdf": pdf,
            "reference_sha256": digest,
            "prompt_sha256": expected["prompt_sha256"],
            "factual_fidelity": 0.0,
            "tp": 0,
            "fp": 0,
            "fn": len(prepared["claims"]),
            "precision": None,
            "recall": None,
            "f1": None,
            "total_ms": None,
            "reason": "missing_output",
        }
        row.update({
            "applicable_fields": len(prepared["fields"]),
            "reference_claims": len(prepared["claims"]),
            "candidate_claims": 0,
        })
        for field in FIELDS:
            row[f"field_{field}"] = 0.0 if field in prepared["fields"] else None
        if record is None:
            rows.append(row)
            continue
        row.update({
            "status": str(record.get("status") or "UNKNOWN"),
            "total_ms": _duration(record),
        })
        record_pdf = str(record.get("reference_pdf") or "")
        record_digest = str(record.get("reference_sha256") or "").lower()
        record_prompt = _case_prompt(record).strip()
        if record_pdf != pdf or record_digest != digest or record_prompt != prompt:
            invalid_joins += 1
            row["status"] = "INVALID_REFERENCE_JOIN"
            row["reason"] = "case_pdf_sha_or_prompt_mismatch"
            rows.append(row)
            continue
        if record.get("status") != "SUCCEEDED":
            row["reason"] = str(record.get("error_code") or "output_not_succeeded")
            rows.append(row)
            continue
        metrics = evaluate_success(
            reference,
            prompt,
            record.get("output") or {},
            prepared=prepared,
        )
        row.update(metrics)
        for field in FIELDS:
            row[f"field_{field}"] = metrics["field_scores"].get(field)
        row["reason"] = None
        rows.append(row)

    succeeded = [row for row in rows if row["status"] == "SUCCEEDED"]
    fidelity_values = [row["factual_fidelity"] for row in succeeded]
    all_values = [row["factual_fidelity"] for row in rows]
    tp = sum(int(row["tp"]) for row in rows)
    fp = sum(int(row["fp"]) for row in rows)
    fn = sum(int(row["fn"]) for row in rows)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else None
    ci_low, ci_high = _ci95(fidelity_values)
    summary = {
        **{key: value for key, value in run.items() if key != "path"},
        "run_path": str(run_path),
        "expected_cases": expected_cases,
        "outputs_found": len(cases),
        "succeeded": len(succeeded),
        "failed": len([row for row in rows if row["status"] not in {"SUCCEEDED", "MISSING"}]),
        "missing": len([row for row in rows if row["status"] == "MISSING"]),
        "invalid_reference_joins": invalid_joins,
        "coverage": len(cases) / expected_cases,
        "success_rate": len(succeeded) / expected_cases,
        "factual_fidelity_conditional": _mean(fidelity_values),
        "factual_fidelity_e2e": _mean(all_values),
        "fidelity_ci95_low": ci_low,
        "fidelity_ci95_high": ci_high,
        "fidelity_p10": _percentile(fidelity_values, 0.10),
        "fidelity_p90": _percentile(fidelity_values, 0.90),
        "material_claims_tp": tp,
        "material_claims_fp": fp,
        "material_claims_fn": fn,
        "material_precision": precision,
        "material_recall": recall,
        "material_f1": f1,
        "latency_p50_ms": _percentile([row["total_ms"] for row in succeeded], 0.50),
        "latency_p95_ms": _percentile([row["total_ms"] for row in succeeded], 0.95),
        "field_accuracy_e2e": {
            field: _mean(row[f"field_{field}"] for row in rows)
            for field in FIELDS
        },
        "comparable_full_run": (
            set(cases) == set(range(1, expected_cases + 1)) and invalid_joins == 0
        ),
    }
    return summary, rows


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows({column: row.get(column) for column in columns} for row in rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-cache", type=Path, required=True)
    parser.add_argument("--prompt-manifest", type=Path, required=True)
    parser.add_argument("--prompts-dir", type=Path, required=True)
    parser.add_argument("--run-catalog", type=Path, required=True)
    parser.add_argument("--outputs-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-cases", type=int, default=1000)
    args = parser.parse_args()

    references, _ = _load_reference_cache(args.reference_cache)
    if len(references) != args.expected_cases:
        raise SystemExit(
            f"reference cache has {len(references)} PDFs; expected {args.expected_cases}"
        )
    prompt_cases = _load_prompt_manifest(
        args.prompt_manifest,
        args.prompts_dir,
        args.expected_cases,
    )
    catalog = _load_catalog(args.run_catalog)
    summaries: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    prepared_cache: dict[tuple[str, str], dict[str, Any]] = {}
    for run in catalog:
        summary, run_rows = evaluate_run(
            run,
            args.outputs_root,
            references,
            prompt_cases,
            args.expected_cases,
            prepared_cache,
        )
        summaries.append(summary)
        rows.extend(run_rows)

    eligible = [row for row in summaries if row["comparable_full_run"]]
    ranking = sorted(
        eligible,
        key=lambda row: (
            -(row["factual_fidelity_e2e"] or 0.0),
            -(row["material_f1"] or 0.0),
            str(row["case_id"]),
        ),
    )
    for position, row in enumerate(ranking, 1):
        row["quality_rank"] = position
    for row in summaries:
        row.setdefault("quality_rank", None)

    rows_by_run = {
        case_id: list(group)
        for case_id, group in itertools.groupby(
            sorted(rows, key=lambda item: (item["case_id"], int(item["case_number"]))),
            key=lambda item: item["case_id"],
        )
    }
    best = ranking[0]
    best_rows = rows_by_run[best["case_id"]]
    pairwise: list[dict[str, Any]] = []
    for other in ranking:
        other_rows = rows_by_run[other["case_id"]]
        deltas = [
            float(left["factual_fidelity"]) - float(right["factual_fidelity"])
            for left, right in zip(best_rows, other_rows, strict=True)
        ]
        mean, low, high = _paired_ci95(deltas)
        pairwise.append({
            "best_case_id": best["case_id"],
            "other_case_id": other["case_id"],
            "mean_delta": mean,
            "ci95_low": low,
            "ci95_high": high,
            "n": len(deltas),
            "method": "paired normal approximation",
        })

    result = {
        "schema_version": "decree-factual-fidelity.v2",
        "evaluation_mode": EVALUATION_MODE,
        "reference": {
            "pdfs": len(references),
            "join": "case_number + reference_pdf + reference_sha256",
            "prompt_role": "disclosure mask only; not ground truth",
        },
        "metric_contract": {
            "accuracy_proxy": "equal-weight mean of applicable PDF-derived factual fields",
            "precision_recall_f1": "exact typed material claims: norms, dates, durations, expedientes and article references",
            "end_to_end": "missing and failed outputs score zero",
            "ranking": "full comparable runs only; factual_fidelity_e2e descending, material_f1 tie-break",
            "legal_metrics": "NOT_HUMAN_ADJUDICATED",
            "confidence_intervals": (
                f"paired {PAIRWISE_CONFIDENCE_LEVEL:.0%} normal-approximation intervals "
                "over the same 1,000 cases"
            ),
        },
        "data_quality": {
            "expected_runs": len(catalog),
            "expected_cases_per_run": args.expected_cases,
            "reference_pdfs": len(references),
            "prompt_manifest_cases": len(prompt_cases),
            "prompt_manifest_sha256": hashlib.sha256(
                args.prompt_manifest.read_bytes()
            ).hexdigest(),
            "reference_cache_sha256": hashlib.sha256(
                args.reference_cache.read_bytes()
            ).hexdigest(),
        },
        "pairwise_to_best": pairwise,
        "summaries": summaries,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "benchmark-summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary_columns = [
        "quality_rank", "case_id", "label", "embedding_model", "embedding_dimensions",
        "rag_context", "ollama_context", "top_k", "candidate_pool", "minimum_score",
        "expected_cases", "outputs_found", "succeeded", "failed", "missing",
        "invalid_reference_joins", "coverage", "success_rate", "factual_fidelity_conditional",
        "factual_fidelity_e2e", "fidelity_ci95_low", "fidelity_ci95_high", "fidelity_p10",
        "fidelity_p90", "material_precision", "material_recall", "material_f1",
        "material_claims_tp", "material_claims_fp", "material_claims_fn", "latency_p50_ms",
        "latency_p95_ms", "comparable_full_run", "run_path",
    ]
    _write_csv(args.output_dir / "benchmark-summary.csv", summaries, summary_columns)
    case_columns = [
        "case_id", "case_number", "status", "reference_pdf", "reference_sha256",
        "prompt_sha256",
        "factual_fidelity", "applicable_fields", "reference_claims", "candidate_claims",
        "tp", "fp", "fn", "precision", "recall", "f1", "total_ms", "reason",
        *[f"field_{field}" for field in FIELDS],
    ]
    _write_csv(args.output_dir / "benchmark-case-metrics.csv", rows, case_columns)
    print(
        f"runs={len(summaries)} references={len(references)} rows={len(rows)} "
        f"output_dir={args.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
