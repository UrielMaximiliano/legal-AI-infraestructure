"""Compute inferential statistics after artifact-to-run reconciliation.

Only ``PRIMARY_FULL_1000`` enters the principal benchmark matrix. Smoke,
diagnostic, partial, duplicate, recovered, and invalid artifacts are exported
as appendices and do not contribute to rankings or p-values.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
from collections import Counter
from itertools import combinations
from pathlib import Path
from statistics import mean
from typing import Any


SEED = 20260825
BOOTSTRAP = 10_000


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def exact_mcnemar(left: list[bool], right: list[bool]) -> dict[str, Any]:
    left_only = sum(a and not b for a, b in zip(left, right))
    right_only = sum((not a) and b for a, b in zip(left, right))
    discordant = left_only + right_only
    if not discordant:
        p_value = 1.0
    else:
        tail = sum(math.comb(discordant, i) for i in range(min(left_only, right_only) + 1)) / (2.0**discordant)
        p_value = min(1.0, 2.0 * tail)
    return {"b01_left_only": left_only, "b10_right_only": right_only, "discordant": discordant, "p_value": p_value, "test": "McNemar exact two-sided"}


def bootstrap_mean(differences: list[float], *, seed: int, resamples: int) -> dict[str, Any]:
    if not differences:
        return {"status": "NO_SHARED_CASES", "n": 0}
    rng = random.Random(seed)
    n = len(differences)
    distribution = [sum(rng.choices(differences, k=n)) / n for _ in range(resamples)]
    ordered = sorted(distribution)
    estimate = mean(differences)
    lower = (sum(value <= 0 for value in distribution) + 1) / (resamples + 1)
    upper = (sum(value >= 0 for value in distribution) + 1) / (resamples + 1)
    return {
        "status": "CALCULATED",
        "estimate": estimate,
        "delta": estimate,
        "ci_low": ordered[int(0.025 * (len(ordered) - 1))],
        "ci_high": ordered[int(0.975 * (len(ordered) - 1))],
        "p_value": min(1.0, 2.0 * min(lower, upper)),
        "n": n,
        "resamples": resamples,
        "seed": seed,
        "method": "paired_case_bootstrap_percentile",
    }


def holm_bonferroni(p_values: list[float]) -> list[float]:
    ordered = sorted(enumerate(p_values), key=lambda item: item[1])
    adjusted = [1.0] * len(p_values)
    running = 0.0
    for rank, (index, value) in enumerate(ordered):
        running = max(running, min(1.0, (len(p_values) - rank) * value))
        adjusted[index] = running
    return adjusted


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    if total <= 0:
        return None, None
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, center - radius), min(1.0, center + radius)


def case_key(item: dict[str, Any]) -> str:
    """Pair by the same case_id, with a reference-key fallback."""

    case_id = item.get("case_id") or item.get("external_id")
    if case_id:
        return f"case_id:{case_id}"
    return f"reference:{str(item.get('reference_pdf', '')).lower()}:{str(item.get('reference_sha256', '')).lower()}"


def metric_value(item: dict[str, Any], metric: str) -> float | None:
    if metric == "atomic_claim_recall":
        value = item.get("atomic_claims", {}).get("recall")
    elif metric == "prompt_coverage":
        value = item.get("prompt_coverage", {}).get("rate")
    elif metric == "critical_fields_correct":
        value = 1.0 if item.get("critical_fields", {}).get("all_correct") is True else 0.0
    elif metric == "critical_contradiction_free":
        value = 1.0 if not item.get("contradictions", {}).get("critical_count", 0) else 0.0
    elif metric == "critical_omission_free":
        value = 1.0 if not item.get("omissions", {}).get("critical_count", 0) else 0.0
    elif metric == "unsupported_addition_free":
        value = 1.0 if not item.get("unsupported_additions", {}).get("critical_count", 0) else 0.0
    elif metric == "citation_traceability":
        value = item.get("source_faithfulness", {}).get("citation_traceability")
    else:
        value = None
    return float(value) if isinstance(value, (int, float)) else None


CONTINUOUS_METRICS = (
    "atomic_claim_recall",
    "prompt_coverage",
    "critical_fields_correct",
    "critical_contradiction_free",
    "critical_omission_free",
    "unsupported_addition_free",
    "citation_traceability",
)


def config_param_names(row: dict[str, Any]) -> dict[str, Any]:
    cfg = row.get("configuration_json") or {}
    values: dict[str, Any] = {}
    for key in ("embedding_model", "generator_model", "model", "rag_context", "ollama_context", "top_k", "candidate_pool", "minimum_score", "chunk_size", "chunk_overlap", "temperature", "seed"):
        if key in cfg and not isinstance(cfg[key], (dict, list)):
            values[key] = cfg[key]
    name = str(row.get("source_run_dir", ""))
    for key, pattern in (("rag_context", r"rag(\d+)"), ("ollama_context", r"ollama(\d+)"), ("model", r"(?:^|-)s?(0\.6b|4b)(?:-|$)")):
        if key not in values:
            match = re.search(pattern, name, re.IGNORECASE)
            if match:
                values[key] = match.group(1)
    return values


def pair_maps(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> tuple[list[str], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    left_map = {case_key(item): item for item in left}
    right_map = {case_key(item): item for item in right}
    return sorted(set(left_map) & set(right_map)), left_map, right_map


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: row.get(key) for key in fields} for row in rows)


def add_classification(summary: dict[str, Any], reconciliation: dict[str, Any]) -> dict[str, Any]:
    result = dict(summary)
    result.update({key: reconciliation.get(key) for key in ("classification", "logical_run_id", "config_hash", "case_set_hash", "output_hash", "evaluator_hash")})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--bootstrap-resamples", type=int, default=BOOTSTRAP)
    args = parser.parse_args()
    out = args.output_dir or args.results_root
    out.mkdir(parents=True, exist_ok=True)

    inventory = read_json(args.inventory / "runs_inventory.json")
    reconciliation_rows = read_json(args.inventory / "artifact_to_logical_run_reconciliation.json")
    reconciliation = {str(row["artifact_id"]): row for row in reconciliation_rows}
    summaries: dict[str, dict[str, Any]] = {}
    all_records: dict[str, list[dict[str, Any]]] = {}
    for row in inventory:
        artifact_id = str(row["inventory_id"])
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", artifact_id).strip("_")
        summary_path = args.results_root / slug / "summary.json"
        metrics_path = args.results_root / slug / "metrics.jsonl"
        if summary_path.is_file() and metrics_path.is_file() and artifact_id in reconciliation:
            summaries[slug] = add_classification(read_json(summary_path), reconciliation[artifact_id])
            all_records[slug] = read_jsonl(metrics_path)

    def slugs_for(*classes: str) -> set[str]:
        return {slug for slug, summary in summaries.items() if summary.get("classification") in classes}

    primary_slugs = slugs_for("PRIMARY_FULL_1000")
    replica_slugs = slugs_for("REPLICATE_FULL_1000", "RECOVERED_COPY")
    appendix_slugs = set(summaries) - primary_slugs - replica_slugs
    records = {slug: all_records[slug] for slug in primary_slugs}

    primary_rows: list[dict[str, Any]] = []
    for slug in sorted(primary_slugs):
        summary = summaries[slug]
        total = int(summary.get("case_count") or 0)
        low, high = wilson(int(summary.get("legal_pass_count") or 0), total)
        primary_rows.append({
            "artifact_id": summary.get("artifact_id"), "logical_run_id": summary.get("logical_run_id"), "run_id": summary.get("run_id", slug),
            "classification": summary.get("classification"), "config_hash": summary.get("config_hash"), "case_set_hash": summary.get("case_set_hash"),
            "output_hash": summary.get("output_hash"), "evaluator_hash": summary.get("evaluator_hash"), "case_count": total,
            "legal_pass_count": summary.get("legal_pass_count"), "legal_pass_rate": summary.get("legal_pass_rate"), "legal_pass_ci_low": low, "legal_pass_ci_high": high,
            "atomic_claim_recall": summary.get("atomic_claim_recall"), "prompt_coverage_rate": summary.get("prompt_coverage_rate"),
            "critical_fields_correct_rate": summary.get("critical_fields_correct_rate"), "critical_contradiction_rate": summary.get("critical_contradiction_rate"),
            "critical_omission_rate": summary.get("critical_omission_rate"), "unsupported_addition_rate": summary.get("unsupported_addition_rate"),
            "source_faithfulness_status": json.dumps(summary.get("source_faithfulness_status_counts", {}), sort_keys=True),
            "retrieval_status": json.dumps(summary.get("retrieval_reconstruction_status_counts", {}), sort_keys=True),
        })
    primary_rows.sort(key=lambda row: (-float(row.get("legal_pass_rate") or 0), -float(row.get("atomic_claim_recall") or 0), str(row.get("run_id"))))
    for rank, row in enumerate(primary_rows, 1):
        row["rank_legal_pass"] = rank
    write_csv(out / "primary_configuration_metrics.csv", primary_rows)
    write_csv(out / "primary_ranking.csv", primary_rows)

    # Binary endpoint: exact McNemar, paired by the same case_id.
    pair_rows: list[dict[str, Any]] = []
    for left_slug, right_slug in combinations(sorted(records), 2):
        shared, left_map, right_map = pair_maps(records[left_slug], records[right_slug])
        if not shared:
            continue
        left_pass = [bool(left_map[key].get("legal_pass")) for key in shared]
        right_pass = [bool(right_map[key].get("legal_pass")) for key in shared]
        test = exact_mcnemar(left_pass, right_pass)
        rate_a, rate_b = mean(left_pass), mean(right_pass)
        ci_a, ci_b = wilson(sum(left_pass), len(left_pass)), wilson(sum(right_pass), len(right_pass))
        pair_rows.append({
            "run_a": summaries[left_slug].get("run_id", left_slug), "run_b": summaries[right_slug].get("run_id", right_slug),
            "artifact_a": left_slug, "artifact_b": right_slug, "metric": "LegalPass", "n_shared_case_ids": len(shared),
            "legal_pass_rate_a": rate_a, "legal_pass_rate_b": rate_b, "legal_pass_ci95_a_low": ci_a[0], "legal_pass_ci95_a_high": ci_a[1],
            "legal_pass_ci95_b_low": ci_b[0], "legal_pass_ci95_b_high": ci_b[1], "delta_pp_b_minus_a": (rate_b - rate_a) * 100, **test,
        })
    adjusted = holm_bonferroni([float(row["p_value"]) for row in pair_rows])
    for row, value in zip(pair_rows, adjusted):
        row["holm_bonferroni_p_value"] = value
        row["significant_alpha_0_05"] = value < 0.05
        row["winner"] = row["run_b"] if row["delta_pp_b_minus_a"] > 0 else row["run_a"] if row["delta_pp_b_minus_a"] < 0 else "TIE"
    write_csv(out / "pairwise_comparisons.csv", pair_rows)

    # Continuous metrics, including Claims Recall: paired bootstrap (10,000
    # resamples by default) on controlled one-parameter contrasts, then Holm.
    continuous_metrics = ("atomic_claim_recall", "prompt_coverage", "critical_fields_correct", "critical_contradiction_free", "critical_omission_free", "unsupported_addition_free", "citation_traceability")
    controlled: list[dict[str, Any]] = []
    parameter_rows = {slug: config_param_names(next(item for item in inventory if re.sub(r"[^A-Za-z0-9_.-]+", "_", str(item["inventory_id"])).strip("_") == slug)) for slug in records}
    for left_slug, right_slug in combinations(sorted(records), 2):
        left_params, right_params = parameter_rows[left_slug], parameter_rows[right_slug]
        differences = [key for key in sorted(set(left_params) | set(right_params)) if left_params.get(key) != right_params.get(key)]
        if len(differences) != 1:
            continue
        shared, left_map, right_map = pair_maps(records[left_slug], records[right_slug])
        for metric in continuous_metrics:
            paired = [(metric_value(left_map[key], metric), metric_value(right_map[key], metric)) for key in shared]
            paired = [(left, right) for left, right in paired if left is not None and right is not None]
            ci = bootstrap_mean([right - left for left, right in paired], seed=SEED + len(controlled), resamples=args.bootstrap_resamples)
            controlled.append({
                "run_a": summaries[left_slug].get("run_id", left_slug), "run_b": summaries[right_slug].get("run_id", right_slug), "artifact_a": left_slug, "artifact_b": right_slug,
                "parameter": differences[0], "value_a": left_params.get(differences[0]), "value_b": right_params.get(differences[0]), "metric": metric,
                "n_shared_case_ids": len(paired), "delta_b_minus_a": ci.get("delta"), "delta_pp_b_minus_a": (ci.get("delta") or 0) * 100,
                "ci_low": ci.get("ci_low"), "ci_high": ci.get("ci_high"), "p_value": ci.get("p_value"), "resamples": ci.get("resamples", args.bootstrap_resamples),
                "seed": ci.get("seed"), "method": ci.get("method", "paired_case_bootstrap_percentile"),
            })
    p_values = [float(row["p_value"]) for row in controlled if row.get("p_value") is not None]
    adjusted = holm_bonferroni(p_values)
    index = 0
    for row in controlled:
        if row.get("p_value") is not None:
            row["holm_bonferroni_p_value"] = adjusted[index]
            row["significant_alpha_0_05"] = adjusted[index] < 0.05
            index += 1
    write_csv(out / "continuous_controlled_contrasts.csv", controlled)
    write_csv(out / "controlled_contrasts.csv", controlled)

    error_counts: Counter[tuple[str, str]] = Counter()

    def category(text: str) -> str:
        lower = text.lower()
        for label, pattern in (("person", r"persona|nombre|apellido"), ("dni", r"dni|cuil|cuit"), ("date", r"fecha|enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre"), ("amount", r"monto|importe|pesos|\$"), ("duration", r"plazo|vigencia|días|meses|años"), ("legal_norm", r"ley|decreto|resolución|artículo|norma"), ("authority", r"autoridad|facultad|competencia"), ("publication", r"comuníquese|publíquese|archívese")):
            if re.search(pattern, lower):
                return label
        return "other"

    for slug, items in records.items():
        run_id = summaries[slug].get("run_id", slug)
        for item in items:
            for field in ("contradictions", "omissions", "unsupported_additions"):
                for error in item.get(field, {}).get("items", []):
                    error_counts[(run_id, category(str(error.get("text", ""))))] += 1
    write_csv(out / "error_breakdown.csv", [{"run_id": run, "error_category": cat, "count": count} for (run, cat), count in sorted(error_counts.items())])

    appendix_rows = [summary for slug, summary in sorted(summaries.items()) if slug in appendix_slugs]
    replicate_rows = [summary for slug, summary in sorted(summaries.items()) if slug in replica_slugs]
    write_csv(out / "appendix_configuration_metrics.csv", appendix_rows)
    write_csv(out / "stability_replicates.csv", replicate_rows)
    class_rows: list[dict[str, Any]] = []
    classes = ("PRIMARY_FULL_1000", "REPLICATE_FULL_1000", "SMOKE", "DIAGNOSTIC", "PARTIAL", "ARCHIVE_DUPLICATE", "RECOVERED_COPY", "INVALID")
    for classification in classes:
        artifacts = [row for row in reconciliation_rows if row.get("classification") == classification]
        evaluated = [summary for summary in summaries.values() if summary.get("classification") == classification]
        class_rows.append({"classification": classification, "artifact_count": len(artifacts), "evaluated_artifact_count": len(evaluated), "evaluated_case_count": sum(int(row.get("case_count") or 0) for row in evaluated), "in_primary_inference": classification == "PRIMARY_FULL_1000"})
    write_csv(out / "reconciliation_class_summary.csv", class_rows)

    evaluator_hashes = sorted({str(row.get("evaluator_hash")) for row in reconciliation_rows if row.get("evaluator_hash")})
    manifest = {
        "schema_version": "benchmark-v2-statistics-manifest-2", "primary_classification": "PRIMARY_FULL_1000", "primary_count": len(primary_slugs), "replicate_count": len(replica_slugs), "appendix_count": len(appendix_slugs),
        "pairwise_legalpass_comparisons": len(pair_rows), "continuous_controlled_rows": len(controlled), "bootstrap_resamples": args.bootstrap_resamples, "bootstrap_seed": SEED,
        "legalpass_test": "McNemar exact two-sided on paired case_id values", "continuous_test": "paired case bootstrap percentile", "multiple_comparison_correction": "Holm-Bonferroni",
        "evaluator_hashes_in_reconciliation": evaluator_hashes, "retrieval_policy": "NOT_RECONSTRUCTABLE when historical chunk text is absent; retrieval metrics excluded from principal inference",
        "excluded_classifications": ["SMOKE", "DIAGNOSTIC", "PARTIAL", "ARCHIVE_DUPLICATE", "RECOVERED_COPY", "INVALID"],
    }
    (out / "statistics_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"primary_runs": len(primary_slugs), "replicas": len(replica_slugs), "appendix_runs": len(appendix_slugs), "pairwise_comparisons": len(pair_rows), "continuous_controlled_contrasts": len(controlled), "bootstrap_resamples": args.bootstrap_resamples}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
