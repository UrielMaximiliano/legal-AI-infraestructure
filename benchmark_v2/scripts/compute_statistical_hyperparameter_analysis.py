"""Statistical analysis of the frozen Benchmark V2 outputs.

This script deliberately works at the logical hyperparameter-configuration
grain.  It uses one canonical representative for each unique FULL config and
keeps C02/C14 as a reproducibility candidate because their config_hash is
identical but their output_hash values differ and seed is not recorded.

No generation, retrieval, or evaluator code is called here.  The evaluator
hash and rules version are read from the already saved metrics.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
from collections import defaultdict
from itertools import combinations, product
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable

try:  # The workspace runtime has NumPy; the repository Python may not.
    import numpy as np
except ImportError:  # pragma: no cover - exercised only in minimal runtimes.
    np = None


BOOTSTRAP = 10_000
SEED = 20260825
PRIMARY_CLASS = "PRIMARY_FULL_1000"
PARAMETERS = ("embedding_model", "rag_context", "ollama_context", "top_k", "pool", "threshold")
CONTINUOUS_METRICS = (
    "claims_recall",
    "prompt_coverage",
    "critical_fields_score",
    "critical_contradiction_free",
    "critical_omission_free",
    "unsupported_addition_free",
    "citation_traceability",
)
BINARY_METRICS = (
    "critical_fields_score",
    "critical_contradiction_free",
    "critical_omission_free",
    "unsupported_addition_free",
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(row for row in rows)


def number(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "" or str(value).upper() in {"NOT_RECORDED", "NONE", "NULL"}:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def integer(value: Any, default: int | None = None) -> int | None:
    parsed = number(value)
    return int(parsed) if parsed is not None else default


def run_order(run: str) -> int:
    match = re.search(r"(\d+)$", str(run))
    return int(match.group(1)) if match else 9999


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    if total <= 0:
        return None, None
    p = successes / total
    denominator = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / denominator
    radius = z * math.sqrt(p * (1.0 - p) / total + z * z / (4.0 * total * total)) / denominator
    return max(0.0, center - radius), min(1.0, center + radius)


def exact_mcnemar(left: list[bool], right: list[bool]) -> dict[str, Any]:
    # b: A passes and B fails; c: A fails and B passes.
    b = sum(a and not c for a, c in zip(left, right))
    c = sum((not a) and c for a, c in zip(left, right))
    n = b + c
    if not n:
        p = 1.0
    else:
        p = min(1.0, 2.0 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / (2.0**n))
    return {"b_a_pass_b_fail": b, "c_a_fail_b_pass": c, "discordant": n, "p_value": p, "test": "McNemar exact two-sided"}


def binary_metric_mcnemar(left: list[dict[str, Any]], right: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    shared, left_map, right_map = paired_maps(left, right)
    left_values = [bool(metric_value(left_map[key], metric)) for key in shared]
    right_values = [bool(metric_value(right_map[key], metric)) for key in shared]
    result = exact_mcnemar(left_values, right_values)
    rate_a = sum(left_values) / len(left_values) if left_values else None
    rate_b = sum(right_values) / len(right_values) if right_values else None
    ci_a = wilson(sum(left_values), len(left_values))
    ci_b = wilson(sum(right_values), len(right_values))
    result.update({
        "metric": metric, "n_shared_case_ids": len(shared), "rate_a": rate_a, "rate_b": rate_b,
        "delta_pp_b_minus_a": None if rate_a is None or rate_b is None else (rate_b - rate_a) * 100.0,
        "ci95_a_low": ci_a[0], "ci95_a_high": ci_a[1], "ci95_b_low": ci_b[0], "ci95_b_high": ci_b[1],
    })
    return result


def holm(p_values: list[float]) -> list[float]:
    if not p_values:
        return []
    ordered = sorted(enumerate(p_values), key=lambda item: item[1])
    adjusted = [1.0] * len(p_values)
    running = 0.0
    for rank, (index, p_value) in enumerate(ordered):
        running = max(running, min(1.0, (len(p_values) - rank) * p_value))
        adjusted[index] = running
    return adjusted


def paired_bootstrap(differences: list[float], seed: int, resamples: int) -> dict[str, Any]:
    if not differences:
        return {"status": "NO_SHARED_CASES", "n": 0}
    n = len(differences)
    if np is not None:
        values = np.asarray(differences, dtype=float)
        rng = np.random.default_rng(seed)
        distribution_chunks = []
        for start in range(0, resamples, 1000):
            size = min(1000, resamples - start)
            indices = rng.integers(0, n, size=(size, n))
            distribution_chunks.append(values[indices].mean(axis=1))
        distribution = np.concatenate(distribution_chunks)
        estimate = float(values.mean())
        lower, upper = np.quantile(distribution, [0.025, 0.975])
        p = min(1.0, 2.0 * min(float((distribution <= 0).mean()), float((distribution >= 0).mean())))
        return {
            "status": "CALCULATED", "estimate": estimate, "ci_low": float(lower), "ci_high": float(upper),
            "p_value": p, "n": n, "resamples": resamples, "seed": seed,
            "method": "paired_case_bootstrap_percentile", "engine": "numpy_vectorized",
        }
    # Portable fallback.  It is intentionally deterministic but slower.
    import random
    rng = random.Random(seed)
    distribution = [sum(rng.choices(differences, k=n)) / n for _ in range(resamples)]
    ordered = sorted(distribution)
    p = min(1.0, 2.0 * min(sum(value <= 0 for value in distribution) / resamples, sum(value >= 0 for value in distribution) / resamples))
    return {
        "status": "CALCULATED", "estimate": mean(differences), "ci_low": ordered[int(0.025 * (resamples - 1))],
        "ci_high": ordered[int(0.975 * (resamples - 1))], "p_value": p, "n": n,
        "resamples": resamples, "seed": seed, "method": "paired_case_bootstrap_percentile", "engine": "stdlib_fallback",
    }


def rankdata(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        end = index + 1
        while end < len(order) and values[order[end]] == values[order[index]]:
            end += 1
        rank = (index + 1 + end) / 2.0
        for pos in order[index:end]:
            ranks[pos] = rank
        index = end
    return ranks


def wilcoxon_signed_rank(differences: list[float]) -> dict[str, Any]:
    nonzero = [float(value) for value in differences if value != 0]
    n = len(nonzero)
    if not n:
        return {"statistic": 0.0, "p_value": 1.0, "n_nonzero": 0, "test": "Wilcoxon signed-rank normal approximation"}
    absolute = [abs(value) for value in nonzero]
    ranks = rankdata(absolute)
    w_plus = sum(rank for rank, value in zip(ranks, nonzero) if value > 0)
    mean_w = n * (n + 1) / 4.0
    tie_counts = defaultdict(int)
    for value in absolute:
        tie_counts[value] += 1
    tie_correction = sum(count**3 - count for count in tie_counts.values())
    variance = (n * (n + 1) * (2 * n + 1) - tie_correction / 2.0) / 24.0
    if variance <= 0:
        p = 1.0
    else:
        correction = 0.5 if w_plus > mean_w else -0.5 if w_plus < mean_w else 0.0
        z = (w_plus - mean_w - correction) / math.sqrt(variance)
        p = math.erfc(abs(z) / math.sqrt(2.0))
    return {
        "statistic_w_plus": w_plus, "statistic_w_minus": n * (n + 1) / 2.0 - w_plus,
        "p_value": min(1.0, max(0.0, p)), "n_nonzero": n,
        "test": "Wilcoxon signed-rank normal approximation with continuity correction",
    }


def cohen_dz(differences: list[float]) -> float | None:
    if len(differences) < 2:
        return None
    center = mean(differences)
    variance = sum((value - center) ** 2 for value in differences) / (len(differences) - 1)
    return center / math.sqrt(variance) if variance > 0 else None


def case_key(item: dict[str, Any]) -> str:
    return str(item.get("case_id") or item.get("external_id") or item.get("reference_pdf") or "")


def metric_value(item: dict[str, Any], metric: str) -> float | None:
    if metric == "claims_recall":
        value = item.get("atomic_claims", {}).get("recall")
    elif metric == "prompt_coverage":
        value = item.get("prompt_coverage", {}).get("rate")
    elif metric == "critical_fields_score":
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


def config_value(row: dict[str, str], parameter: str) -> Any:
    if parameter == "embedding_model":
        raw = str(row.get("embedding_model", "")).lower()
        if "0.6b" in raw:
            return "0.6B"
        if "4b" in raw:
            return "4B"
        return row.get("embedding_model")
    if parameter == "rag_context":
        return integer(row.get("rag_context"))
    if parameter == "ollama_context":
        return integer(row.get("ollama_context"))
    if parameter == "top_k":
        return integer(row.get("top_k"))
    if parameter == "pool":
        return integer(row.get("pool"))
    if parameter == "threshold":
        return number(row.get("threshold"))
    return row.get(parameter)


def select_representative(members: list[dict[str, Any]], preferred: str | None = None) -> dict[str, Any]:
    """Select a canonical physical output without calling it a replicate."""
    ordered = sorted(members, key=lambda item: run_order(item["run"]))
    return next((item for item in ordered if item["run"] == preferred), None) or ordered[0]


def dominates(left: dict[str, Any], right: dict[str, Any], objectives: Iterable[str]) -> bool:
    values_left = [float(left[name]) for name in objectives]
    values_right = [float(right[name]) for name in objectives]
    return all(a >= b for a, b in zip(values_left, values_right)) and any(a > b for a, b in zip(values_left, values_right))


def paired_maps(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> tuple[list[str], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    left_map = {case_key(item): item for item in left}
    right_map = {case_key(item): item for item in right}
    shared = sorted(set(left_map) & set(right_map))
    return shared, left_map, right_map


def summarize_records(items: list[dict[str, Any]]) -> dict[str, Any]:
    legal = [bool(item.get("legal_pass")) for item in items]
    values: dict[str, float | None] = {}
    for metric in CONTINUOUS_METRICS:
        metric_values = [metric_value(item, metric) for item in items]
        metric_values = [value for value in metric_values if value is not None]
        values[metric] = mean(metric_values) if metric_values else None
    low, high = wilson(sum(legal), len(legal))
    return {
        "case_count": len(items), "legal_pass_count": sum(legal), "legal_pass_rate": mean(legal) if legal else None,
        "legal_pass_ci95_low": low, "legal_pass_ci95_high": high, **values,
        "critical_omission_rate": None if values["critical_omission_free"] is None else 1.0 - values["critical_omission_free"],
        "critical_contradiction_rate": None if values["critical_contradiction_free"] is None else 1.0 - values["critical_contradiction_free"],
        "unsupported_addition_rate": None if values["unsupported_addition_free"] is None else 1.0 - values["unsupported_addition_free"],
    }


def failure_decomposition_rows(config: dict[str, Any], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Decompose tracked critical-error flags without changing LegalPass."""
    flag_names = ("omission", "contradiction", "addition", "fields")
    patterns: dict[tuple[bool, bool, bool, bool], dict[str, int]] = defaultdict(lambda: {"case_count": 0, "legal_pass_count": 0, "legal_fail_count": 0})
    for item in items:
        flags = (
            bool(item.get("omissions", {}).get("critical_count", 0)),
            bool(item.get("contradictions", {}).get("critical_count", 0)),
            bool(item.get("unsupported_additions", {}).get("critical_count", 0)),
            item.get("critical_fields", {}).get("all_correct") is False,
        )
        bucket = patterns[flags]
        bucket["case_count"] += 1
        if bool(item.get("legal_pass")):
            bucket["legal_pass_count"] += 1
        else:
            bucket["legal_fail_count"] += 1
    rows: list[dict[str, Any]] = []
    total = len(items)
    tracked_union = sum(count["case_count"] for flags, count in patterns.items() if any(flags))
    for flags, count in sorted(patterns.items(), key=lambda entry: (not any(entry[0]), entry[0])):
        active = [name for name, enabled in zip(flag_names, flags) if enabled]
        pattern = "+".join(active) if active else "none_tracked"
        rows.append({
            "run": config["run"], "config_hash": config["config_hash"], "pattern": pattern,
            "omission": flags[0], "contradiction": flags[1], "addition": flags[2], "fields_incorrect": flags[3],
            "case_count": count["case_count"], "rate": count["case_count"] / total if total else None,
            "legal_pass_count": count["legal_pass_count"], "legal_fail_count": count["legal_fail_count"],
            "tracked_error_union_count": tracked_union, "tracked_error_union_rate": tracked_union / total if total else None,
            "denominator": total, "interpretation": "exact combination of tracked flags; remaining LegalPass failures may involve other critical rules",
        })
    return rows


def pair_bootstrap_metrics(left: list[dict[str, Any]], right: list[dict[str, Any]], seed: int, resamples: int) -> dict[str, dict[str, Any]]:
    shared, left_map, right_map = paired_maps(left, right)
    diffs: dict[str, list[float]] = {}
    for metric in CONTINUOUS_METRICS:
        pairs = [(metric_value(left_map[key], metric), metric_value(right_map[key], metric)) for key in shared]
        diffs[metric] = [right_value - left_value for left_value, right_value in pairs if left_value is not None and right_value is not None]
    results: dict[str, dict[str, Any]] = {}
    if np is not None and diffs and all(diffs.values()):
        metric_names = list(diffs)
        n = len(diffs[metric_names[0]])
        if all(len(diffs[name]) == n for name in metric_names):
            values = np.asarray([diffs[name] for name in metric_names], dtype=float).T
            rng = np.random.default_rng(seed)
            chunks = []
            for start in range(0, resamples, 1000):
                size = min(1000, resamples - start)
                indices = rng.integers(0, n, size=(size, n))
                chunks.append(values[indices].mean(axis=1))
            distributions = np.concatenate(chunks, axis=0)
            for index, metric in enumerate(metric_names):
                distribution = distributions[:, index]
                estimate = float(values[:, index].mean())
                low, high = np.quantile(distribution, [0.025, 0.975])
                p = min(1.0, 2.0 * min(float((distribution <= 0).mean()), float((distribution >= 0).mean())))
                results[metric] = {
                    "status": "CALCULATED", "estimate": estimate, "ci_low": float(low), "ci_high": float(high),
                    "p_value": p, "n": n, "resamples": resamples, "seed": seed,
                    "method": "paired_case_bootstrap_percentile", "engine": "numpy_vectorized",
                    "wilcoxon": wilcoxon_signed_rank(diffs[metric]), "cohen_dz": cohen_dz(diffs[metric]),
                }
            return results
    for index, metric in enumerate(CONTINUOUS_METRICS):
        result = paired_bootstrap(diffs[metric], seed + index, resamples)
        result["wilcoxon"] = wilcoxon_signed_rank(diffs[metric])
        result["cohen_dz"] = cohen_dz(diffs[metric])
        results[metric] = result
    return results


def spearman(values_a: list[float], values_b: list[float]) -> float | None:
    if len(values_a) != len(values_b) or len(values_a) < 2:
        return None
    rank_a = rankdata(values_a)
    rank_b = rankdata(values_b)
    center_a, center_b = mean(rank_a), mean(rank_b)
    numerator = sum((a - center_a) * (b - center_b) for a, b in zip(rank_a, rank_b))
    denominator = math.sqrt(sum((a - center_a) ** 2 for a in rank_a) * sum((b - center_b) ** 2 for b in rank_b))
    return numerator / denominator if denominator else None


def escape(value: Any) -> str:
    return html.escape(str(value))


def write_svg_outputs(out: Path, ranking: list[dict[str, Any]], pairwise: list[dict[str, Any]], effects: list[dict[str, Any]], configs: list[dict[str, Any]]) -> list[str]:
    figure_dir = out / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    width, row_height, left = 1100, 34, 210
    height = 100 + row_height * len(ranking)
    max_rate = max(float(row["legal_pass_rate"]) for row in ranking) if ranking else 1.0
    scale = 700 / max(max_rate, 0.001)
    bars = []
    for index, row in enumerate(ranking):
        y = 55 + index * row_height
        rate = float(row["legal_pass_rate"])
        low = float(row["legal_pass_ci95_low"])
        high = float(row["legal_pass_ci95_high"])
        bars.append(f'<text x="10" y="{y + 18}" font-size="16">{escape(row["run"])}</text>')
        bars.append(f'<rect x="{left}" y="{y + 5}" width="{rate * scale:.1f}" height="22" fill="#245b8a"/>')
        bars.append(f'<line x1="{left + low * scale:.1f}" x2="{left + high * scale:.1f}" y1="{y + 16}" y2="{y + 16}" stroke="#111" stroke-width="3"/>')
        bars.append(f'<text x="{left + 710}" y="{y + 21}" font-size="15">{rate * 100:.1f}% [{low * 100:.1f}, {high * 100:.1f}]</text>')
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"><rect width="100%" height="100%" fill="white"/><text x="10" y="25" font-size="20" font-weight="bold">Benchmark V2 LegalPass por configuración única</text>{"".join(bars)}</svg>'
    (figure_dir / "legalpass_ranking.svg").write_text(svg, encoding="utf-8")
    names.append("legalpass_ranking.svg")

    labels = [row["run"] for row in ranking]
    pair_lookup = {(row["config_a"], row["config_b"]): row for row in pairwise}
    cell = 28
    grid_left, grid_top = 190, 120
    grid_width = grid_left + cell * len(labels) + 100
    grid_height = grid_top + cell * len(labels) + 50
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{grid_width}" height="{grid_height}"><rect width="100%" height="100%" fill="white"/><text x="10" y="25" font-size="20" font-weight="bold">Matriz de diferencias LegalPass (B - A, pp)</text>']
    for j, label in enumerate(labels):
        parts.append(f'<text transform="translate({grid_left + j * cell + 18},{grid_top - 8}) rotate(-60)" font-size="11">{escape(label)}</text>')
    for i, label in enumerate(labels):
        parts.append(f'<text x="{grid_left - 38}" y="{grid_top + i * cell + 19}" font-size="11">{escape(label)}</text>')
        for j in range(len(labels)):
            delta = 0.0
            if i != j:
                row = pair_lookup.get((labels[i], labels[j]))
                if row:
                    delta = float(row["delta_pp_b_minus_a"])
                else:
                    row = pair_lookup.get((labels[j], labels[i]))
                    if row:
                        delta = -float(row["delta_pp_b_minus_a"])
            intensity = min(255, int(abs(delta) * 12))
            color = f"rgb({255 if delta < 0 else 255 - intensity},{255 - intensity if delta < 0 else 255},{255 - intensity})"
            parts.append(f'<rect x="{grid_left + j * cell}" y="{grid_top + i * cell}" width="{cell - 1}" height="{cell - 1}" fill="{color}" stroke="#ddd"/><text x="{grid_left + j * cell + 4}" y="{grid_top + i * cell + 17}" font-size="9">{delta:.1f}</text>')
    parts.append("</svg>")
    (figure_dir / "legalpass_pairwise_heatmap.svg").write_text("".join(parts), encoding="utf-8")
    names.append("legalpass_pairwise_heatmap.svg")

    effect_parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="440"><rect width="100%" height="100%" fill="white"/><text x="10" y="25" font-size="20" font-weight="bold">Efectos controlados: mediana de delta en métricas de éxito</text>']
    chosen = [row for row in effects if row.get("metric") in {"claims_recall", "critical_omission_free", "unsupported_addition_free"}]
    chosen = chosen[:18]
    for index, row in enumerate(chosen):
        y = 45 + index * 20
        delta = number(row.get("median_delta"), 0.0) or 0.0
        effect_parts.append(f'<text x="10" y="{y + 13}" font-size="12">{escape(row.get("parameter"))} / {escape(row.get("metric"))}</text>')
        x = 360 + min(250, max(-250, delta * 700))
        effect_parts.append(f'<line x1="610" x2="610" y1="{y}" y2="{y + 16}" stroke="#999"/><rect x="{min(610, x):.1f}" y="{y + 2}" width="{abs(x - 610):.1f}" height="12" fill="#3a7f52"/><text x="630" y="{y + 13}" font-size="12">{delta * 100:.1f} pp</text>')
    effect_parts.append("</svg>")
    (figure_dir / "controlled_effects.svg").write_text("".join(effect_parts), encoding="utf-8")
    names.append("controlled_effects.svg")
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--coverage-primary", type=Path, required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--v1-summary", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bootstrap-resamples", type=int, default=BOOTSTRAP)
    parser.add_argument("--preferred-representative", default=None, help="Run label to select for its config_hash, e.g. C14 for sensitivity scenario B")
    args = parser.parse_args()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    reconciliation_rows = {row["artifact_id"]: row for row in read_csv(args.reconciliation)}
    mapping_rows = read_csv(args.mapping)
    coverage_rows = {row["run"]: row for row in read_csv(args.coverage_primary)}
    primary_mappings = [row for row in mapping_rows if row.get("classification") == PRIMARY_CLASS]
    if len(primary_mappings) != 17:
        raise RuntimeError(f"Expected 17 PRIMARY_FULL_1000 artifacts, found {len(primary_mappings)}")

    configs_by_hash: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for mapping in primary_mappings:
        run = mapping["catalog_run"]
        if run not in coverage_rows:
            raise RuntimeError(f"Missing coverage row for {run}")
        artifact_id = mapping["artifact_id"]
        if artifact_id not in reconciliation_rows:
            raise RuntimeError(f"Missing reconciliation row for {artifact_id}")
        coverage = coverage_rows[run]
        reconciliation = reconciliation_rows[artifact_id]
        config = {
            "run": run, "artifact_id": artifact_id, "config_hash": mapping["config_hash"],
            "logical_run_id": reconciliation.get("logical_run_id"), "output_hash": mapping.get("output_hash"),
            "evaluator_hash": reconciliation.get("evaluator_hash"), "source_path_remote": mapping.get("source_path_remote"),
            "model": coverage.get("model"), "embedding_model_full": coverage.get("embedding_model"),
            "embedding_model": config_value(coverage, "embedding_model"), "embedding_context": coverage.get("embedding_context"),
            "rag_context": config_value(coverage, "rag_context"), "ollama_context": config_value(coverage, "ollama_context"),
            "chunk_size": coverage.get("chunk_size"), "chunk_overlap": coverage.get("chunk_overlap"),
            "top_k": config_value(coverage, "top_k"), "pool": config_value(coverage, "pool"),
            "threshold": config_value(coverage, "threshold"), "temperature": coverage.get("temperature"), "seed": coverage.get("seed"),
        }
        configs_by_hash[config["config_hash"]].append(config)

    # Lowest C-label is the canonical representative by default.  A preferred
    # label is supported only for the C02/C14 statistical sensitivity check.
    configs: list[dict[str, Any]] = []
    replicate_groups: list[list[dict[str, Any]]] = []
    for members in configs_by_hash.values():
        members.sort(key=lambda item: run_order(item["run"]))
        configs.append(select_representative(members, args.preferred_representative))
        if len(members) > 1:
            replicate_groups.append(members)
    configs.sort(key=lambda item: run_order(item["run"]))
    if len(configs) != 16:
        raise RuntimeError(f"Expected 16 unique FULL configs, found {len(configs)}")
    records: dict[str, list[dict[str, Any]]] = {}
    for config in configs:
        metrics_path = args.results_root / config["artifact_id"] / "metrics.jsonl"
        if not metrics_path.is_file():
            raise RuntimeError(f"Missing saved metrics: {metrics_path}")
        items = read_jsonl(metrics_path)
        if len(items) != 1000:
            raise RuntimeError(f"Expected 1000 cases for {config['run']}, found {len(items)}")
        if len({case_key(item) for item in items}) != 1000:
            raise RuntimeError(f"Duplicate case_id values in {config['run']}")
        records[config["run"]] = items

    ranking: list[dict[str, Any]] = []
    for config in configs:
        row = dict(config)
        row.update(summarize_records(records[config["run"]]))
        row["legal_precision"] = "NOT_RECORDED"
        row["retrieval_metrics"] = "NOT_RECONSTRUCTABLE"
        ranking.append(row)
    ranking.sort(key=lambda row: (-float(row["legal_pass_rate"]), -float(row["claims_recall"]), run_order(row["run"])))
    for rank, row in enumerate(ranking, 1):
        row["rank_observed"] = rank

    pairwise: list[dict[str, Any]] = []
    configs_by_run = {config["run"]: config for config in configs}
    for run_a, run_b in combinations([config["run"] for config in configs], 2):
        left, right = records[run_a], records[run_b]
        shared, left_map, right_map = paired_maps(left, right)
        left_pass = [bool(left_map[key].get("legal_pass")) for key in shared]
        right_pass = [bool(right_map[key].get("legal_pass")) for key in shared]
        test = exact_mcnemar(left_pass, right_pass)
        rate_a, rate_b = mean(left_pass), mean(right_pass)
        ci_a, ci_b = wilson(sum(left_pass), len(left_pass)), wilson(sum(right_pass), len(right_pass))
        differences = [parameter for parameter in PARAMETERS if configs_by_run[run_a][parameter] != configs_by_run[run_b][parameter]]
        pairwise.append({
            "config_a": run_a, "config_b": run_b, "config_hash_a": configs_by_run[run_a]["config_hash"], "config_hash_b": configs_by_run[run_b]["config_hash"],
            "n_shared_case_ids": len(shared), "legal_pass_rate_a": rate_a, "legal_pass_rate_b": rate_b,
            "legal_pass_ci95_a_low": ci_a[0], "legal_pass_ci95_a_high": ci_a[1], "legal_pass_ci95_b_low": ci_b[0], "legal_pass_ci95_b_high": ci_b[1],
            "delta_pp_b_minus_a": (rate_b - rate_a) * 100.0, "changed_parameters": ";".join(differences),
            "identifiable_single_parameter": len(differences) == 1, **test,
        })
    adjusted = holm([float(row["p_value"]) for row in pairwise])
    for row, adjusted_p in zip(pairwise, adjusted):
        row["holm_p_value"] = adjusted_p
        row["significant_alpha_0_05"] = adjusted_p < 0.05
        row["winner"] = row["config_b"] if row["delta_pp_b_minus_a"] > 0 else row["config_a"] if row["delta_pp_b_minus_a"] < 0 else "TIE"
        row["statistical_interpretation"] = "significant_difference_after_Holm" if adjusted_p < 0.05 else "not_statistically_distinguishable_after_Holm"

    # Ranking tiers are non-significance groupings, not equivalence claims.
    best = ranking[0]["run"]
    for row in ranking:
        row["best_observed"] = row["run"] == best
        comparison = next((item for item in pairwise if {item["config_a"], item["config_b"]} == {row["run"], best}), None)
        row["not_distinguishable_from_best"] = row["run"] == best or comparison is None or not comparison["significant_alpha_0_05"]
        row["statistically_superior_to_best"] = False
        if comparison and comparison["significant_alpha_0_05"]:
            row["statistically_superior_to_best"] = comparison["winner"] == best
    tier_one = {row["run"] for row in ranking if row["not_distinguishable_from_best"]}
    for row in ranking:
        row["tier"] = 1 if row["run"] in tier_one else 2
        row["tier_definition"] = "observed-rate grouping; non-significance is not equivalence"

    # One-parameter controlled contrasts only.  This is the guard against
    # attributing a change to a parameter when multiple parameters moved.
    controlled: list[dict[str, Any]] = []
    config_sequence = [config["run"] for config in configs]
    for run_a, run_b in combinations(config_sequence, 2):
        left_config, right_config = configs_by_run[run_a], configs_by_run[run_b]
        changed = [parameter for parameter in PARAMETERS if left_config[parameter] != right_config[parameter]]
        if len(changed) != 1:
            continue
        parameter = changed[0]
        bootstrap_results = pair_bootstrap_metrics(records[run_a], records[run_b], SEED + len(controlled) * 37, args.bootstrap_resamples)
        for metric in CONTINUOUS_METRICS:
            result = bootstrap_results[metric]
            wilcoxon_result = result.get("wilcoxon", {})
            binary_result = binary_metric_mcnemar(records[run_a], records[run_b], metric) if metric in BINARY_METRICS else {}
            primary_p_value = binary_result.get("p_value", result.get("p_value"))
            primary_test = "McNemar exact two-sided" if metric in BINARY_METRICS else "paired bootstrap percentile"
            controlled.append({
                "config_a": run_a, "config_b": run_b, "config_hash_a": left_config["config_hash"], "config_hash_b": right_config["config_hash"],
                "parameter": parameter, "value_a": left_config[parameter], "value_b": right_config[parameter], "metric": metric,
                "n_shared_case_ids": result.get("n"), "delta_b_minus_a": result.get("estimate"), "delta_pp_b_minus_a": None if result.get("estimate") is None else result["estimate"] * 100.0,
                "ci_low": result.get("ci_low"), "ci_high": result.get("ci_high"), "p_value": result.get("p_value"),
                "wilcoxon_statistic_w_plus": wilcoxon_result.get("statistic_w_plus"), "wilcoxon_p_value": wilcoxon_result.get("p_value"),
                "cohen_dz": result.get("cohen_dz"), "resamples": result.get("resamples", args.bootstrap_resamples), "seed": result.get("seed"),
                "method": result.get("method"), "bootstrap_engine": result.get("engine"), "primary_test": primary_test,
                "primary_p_value": primary_p_value, "primary_delta_pp_b_minus_a": binary_result.get("delta_pp_b_minus_a", result.get("estimate", 0.0) * 100.0),
                "binary_b_a_pass_b_fail": binary_result.get("b_a_pass_b_fail"), "binary_c_a_fail_b_pass": binary_result.get("c_a_fail_b_pass"),
                "binary_discordant": binary_result.get("discordant"), "binary_ci95_a_low": binary_result.get("ci95_a_low"),
                "binary_ci95_a_high": binary_result.get("ci95_a_high"), "binary_ci95_b_low": binary_result.get("ci95_b_low"),
                "binary_ci95_b_high": binary_result.get("ci95_b_high"), "holm_family": f"continuous_{parameter}",
            })
    for family in sorted({row["holm_family"] for row in controlled}):
        family_rows = [row for row in controlled if row["holm_family"] == family and row.get("p_value") is not None]
        primary_adjusted_p = holm([float(row["primary_p_value"]) for row in family_rows])
        adjusted_p = holm([float(row["p_value"]) for row in family_rows])
        wilcoxon_p = holm([float(row["wilcoxon_p_value"]) for row in family_rows if row.get("wilcoxon_p_value") is not None])
        wi = 0
        for row, primary_value, value in zip(family_rows, primary_adjusted_p, adjusted_p):
            row["holm_primary_p_value"] = primary_value
            row["primary_significant_alpha_0_05"] = primary_value < 0.05
            row["holm_bootstrap_p_value"] = value
            row["bootstrap_significant_alpha_0_05"] = value < 0.05
            if row.get("wilcoxon_p_value") is not None:
                row["holm_wilcoxon_p_value"] = wilcoxon_p[wi]
                row["wilcoxon_significant_alpha_0_05"] = wilcoxon_p[wi] < 0.05
                wi += 1

    effects: list[dict[str, Any]] = []
    for parameter in PARAMETERS:
        for metric in CONTINUOUS_METRICS:
            rows = [row for row in controlled if row["parameter"] == parameter and row["metric"] == metric and row.get("delta_b_minus_a") is not None]
            if not rows:
                effects.append({"parameter": parameter, "metric": metric, "n_contrasts": 0, "status": "NOT_IDENTIFIABLE_IN_CURRENT_GRID"})
                continue
            significant = sum(bool(row.get("primary_significant_alpha_0_05")) for row in rows)
            bootstrap_significant = sum(bool(row.get("bootstrap_significant_alpha_0_05")) for row in rows)
            effects.append({
                "parameter": parameter, "metric": metric, "n_contrasts": len(rows), "median_delta": median(float(row["delta_b_minus_a"]) for row in rows),
                "min_delta": min(float(row["delta_b_minus_a"]) for row in rows), "max_delta": max(float(row["delta_b_minus_a"]) for row in rows),
                "holm_significant_contrasts": significant, "holm_significant_bootstrap_contrasts": bootstrap_significant,
                "contrast_pairs": ";".join(f"{row['config_a']}>{row['config_b']}" for row in rows), "status": "CALCULATED",
            })

    # C02/C14 reproducibility appendix; no seed is inferred.
    c02_group = next((members for members in replicate_groups if {item["run"] for item in members} == {"C02", "C14"}), None)
    reproducibility: list[dict[str, Any]] = []
    if c02_group:
        c02 = next(item for item in c02_group if item["run"] == "C02")
        c14 = next(item for item in c02_group if item["run"] == "C14")
        left, right = read_jsonl(args.results_root / c02["artifact_id"] / "metrics.jsonl"), read_jsonl(args.results_root / c14["artifact_id"] / "metrics.jsonl")
        shared, left_map, right_map = paired_maps(left, right)
        left_pass = [bool(left_map[key].get("legal_pass")) for key in shared]
        right_pass = [bool(right_map[key].get("legal_pass")) for key in shared]
        mcnemar = exact_mcnemar(left_pass, right_pass)
        n11 = sum(a and b for a, b in zip(left_pass, right_pass))
        n00 = sum((not a) and (not b) for a, b in zip(left_pass, right_pass))
        po = (n11 + n00) / len(shared)
        p_a = sum(left_pass) / len(shared)
        p_b = sum(right_pass) / len(shared)
        pe = p_a * p_b + (1.0 - p_a) * (1.0 - p_b)
        kappa = (po - pe) / (1.0 - pe) if pe < 1.0 else None
        for metric in ("legal_pass",) + CONTINUOUS_METRICS:
            if metric == "legal_pass":
                reproducibility.append({
                    "replicate_a": "C02", "replicate_b": "C14", "config_hash": c02["config_hash"], "metric": "LegalPass",
                    "n_shared_case_ids": len(shared), "rate_a": sum(left_pass) / len(shared), "rate_b": sum(right_pass) / len(shared),
                    "delta_pp_b_minus_a": (sum(right_pass) / len(shared) - sum(left_pass) / len(shared)) * 100.0,
                    "agreement_rate": po, "cohen_kappa": kappa, **mcnemar,
                    "seed_status": "NOT_RECORDED", "interpretation": "candidate replicate with identical hyperparameters and distinct output_hash",
                })
            else:
                paired = [(metric_value(left_map[key], metric), metric_value(right_map[key], metric)) for key in shared]
                paired = [(a, b) for a, b in paired if a is not None and b is not None]
                bootstrap_result = paired_bootstrap([b - a for a, b in paired], SEED + 5000 + len(reproducibility), args.bootstrap_resamples)
                binary_result = binary_metric_mcnemar(left, right, metric) if metric in BINARY_METRICS else {}
                reproducibility.append({
                    "replicate_a": "C02", "replicate_b": "C14", "config_hash": c02["config_hash"], "metric": metric,
                    "n_shared_case_ids": len(paired), "rate_a": mean(a for a, _ in paired), "rate_b": mean(b for _, b in paired),
                    "delta_pp_b_minus_a": (bootstrap_result.get("estimate") or 0.0) * 100.0, "ci_low": bootstrap_result.get("ci_low"), "ci_high": bootstrap_result.get("ci_high"),
                    "p_value": bootstrap_result.get("p_value"), "resamples": bootstrap_result.get("resamples"), "seed": bootstrap_result.get("seed"),
                    "primary_test": "McNemar exact two-sided" if metric in BINARY_METRICS else "paired bootstrap percentile",
                    "primary_p_value": binary_result.get("p_value", bootstrap_result.get("p_value")),
                    "primary_delta_pp_b_minus_a": binary_result.get("delta_pp_b_minus_a", (bootstrap_result.get("estimate") or 0.0) * 100.0),
                    "binary_b_a_pass_b_fail": binary_result.get("b_a_pass_b_fail"), "binary_c_a_fail_b_pass": binary_result.get("c_a_fail_b_pass"),
                    "binary_discordant": binary_result.get("discordant"), "binary_ci95_a_low": binary_result.get("ci95_a_low"),
                    "binary_ci95_a_high": binary_result.get("ci95_a_high"), "binary_ci95_b_low": binary_result.get("ci95_b_low"),
                    "binary_ci95_b_high": binary_result.get("ci95_b_high"),
                    "seed_status": "NOT_RECORDED", "interpretation": "paired output stability; not an independent configuration",
                })

    # Pairwise identifiability and a Pareto screen are descriptive diagnostics.
    identifiability: list[dict[str, Any]] = []
    for row in pairwise:
        identifiability.append({"config_a": row["config_a"], "config_b": row["config_b"], "changed_parameters": row["changed_parameters"], "identifiable_single_parameter": row["identifiable_single_parameter"], "interpretation": "controlled contrast" if row["identifiable_single_parameter"] else "confounded; no isolated attribution"})
    objectives = ("legal_pass_rate", "claims_recall", "prompt_coverage", "critical_fields_score", "critical_contradiction_free", "critical_omission_free", "unsupported_addition_free", "citation_traceability")
    for row in ranking:
        dominated_by = []
        for other in ranking:
            if other["run"] == row["run"]:
                continue
            if dominates(other, row, objectives):
                dominated_by.append(other["run"])
        row["is_pareto_optimal"] = not dominated_by
        row["dominated_by"] = ";".join(dominated_by)

    # Secondary V1/V2 reconciliation, if the already saved V1 summary is available.
    v1_rows: list[dict[str, Any]] = []
    v1_spearman = None
    if args.v1_summary and args.v1_summary.is_file():
        v1 = {row["case_id"]: row for row in read_csv(args.v1_summary)}
        for row in ranking:
            # C14 is the alternate physical output for the C02
            # hyperparameter vector; retain the V1 comparison at the
            # logical-config grain rather than using a different V1 row.
            aliases = sorted(configs_by_hash.get(row["config_hash"], []), key=lambda item: run_order(item["run"]))
            v1_label = aliases[0]["run"] if aliases else row["run"]
            previous = v1.get(v1_label)
            if not previous:
                continue
            v1_rows.append({
                "run": row["run"], "v2_legalpass_rate": row["legal_pass_rate"], "v2_rank": row["rank_observed"],
                "v1_factual_fidelity_e2e": previous.get("factual_fidelity_e2e"), "v1_material_precision": previous.get("material_precision"),
                "v1_material_recall": previous.get("material_recall"), "v1_material_f1": previous.get("material_f1"), "v1_quality_rank": previous.get("quality_rank"), "v1_source_run": v1_label,
            })
        if len(v1_rows) >= 2:
            v1_spearman = spearman([float(row["v2_legalpass_rate"]) for row in v1_rows], [float(row["v1_factual_fidelity_e2e"]) for row in v1_rows])

    failure_rows: list[dict[str, Any]] = []
    for config in configs:
        failure_rows.extend(failure_decomposition_rows(config, records[config["run"]]))

    # Write machine-readable outputs.
    ranking_fields = ["rank_observed", "run", "config_hash", "logical_run_id", "artifact_id", "source_path_remote", "model", "embedding_model", "embedding_model_full", "embedding_context", "rag_context", "ollama_context", "chunk_size", "chunk_overlap", "top_k", "pool", "threshold", "temperature", "seed", "case_count", "legal_pass_count", "legal_pass_rate", "legal_pass_ci95_low", "legal_pass_ci95_high", "claims_recall", "prompt_coverage", "critical_fields_score", "critical_omission_rate", "critical_contradiction_rate", "unsupported_addition_rate", "citation_traceability", "legal_precision", "retrieval_metrics", "best_observed", "not_distinguishable_from_best", "statistically_superior_to_best", "tier", "tier_definition", "is_pareto_optimal", "dominated_by"]
    write_csv(out / "statistical_ranking.csv", [{key: row.get(key) for key in ranking_fields} for row in ranking])
    write_csv(out / "legalpass_pairwise_matrix.csv", pairwise)
    write_csv(out / "hyperparameter_controlled_contrasts.csv", controlled)
    write_csv(out / "hyperparameter_effect_summary.csv", effects)
    write_csv(out / "c02_c14_reproducibility.csv", reproducibility)
    write_csv(out / "identifiability_matrix.csv", identifiability)
    write_csv(out / "pareto_front.csv", [{key: row.get(key) for key in ranking_fields} for row in ranking if row["is_pareto_optimal"]])
    write_csv(out / "v1_vs_v2.csv", v1_rows)
    write_csv(out / "legalpass_failure_decomposition.csv", failure_rows)

    significant_pairs = [row for row in pairwise if row["significant_alpha_0_05"]]
    significant_continuous = [row for row in controlled if row.get("primary_significant_alpha_0_05")]
    figure_names = write_svg_outputs(out, ranking, pairwise, effects, configs)
    representative_policy = (
        f"preferred representative {args.preferred_representative} when present, otherwise lowest C-label per config_hash"
        if args.preferred_representative
        else "lowest C-label per config_hash; C02 is the canonical representative for the C02/C14 config_hash"
    )
    manifest = {
        "schema_version": "benchmark-v2-statistical-hyperparameter-analysis-1", "evaluator_policy": "frozen; no evaluator changes or recalculation",
        "evaluator_hashes": sorted({config["evaluator_hash"] for config in configs}), "evaluator_version": "benchmark-v2-legal-core-2-calibrated",
        "rules_version": "typed-critical-v2-template-aware", "primary_artifacts": 17, "primary_unique_configs": len(configs),
        "representative_policy": representative_policy + "; C02/C14 are candidate replicates with unknown seed",
        "replicate_candidate_groups": [[item["run"] for item in group] for group in replicate_groups], "case_pairing": "same case_id; all primary representatives have 1000 shared cases",
        "legalpass_test": "McNemar exact two-sided", "legalpass_pairwise_count": len(pairwise), "legalpass_holm_family": "all 120 pairwise comparisons",
        "continuous_test": "paired bootstrap percentile, 10000 resamples; Wilcoxon signed-rank reported as sensitivity test; Cohen dz",
        "binary_metric_policy": "critical_fields_score, critical_contradiction_free, critical_omission_free, and unsupported_addition_free use exact McNemar as the primary paired test; bootstrap/Wilcoxon/dz are complementary only",
        "continuous_holm_family": "within changed parameter across its controlled metric rows; primary p-values are Holm-adjusted",
        "bootstrap_seed": SEED, "bootstrap_resamples": args.bootstrap_resamples,
        "retrieval_policy": "SourceFaithfulness and AEC@k NOT_RECONSTRUCTABLE; excluded from principal inference",
        "legal_precision_policy": "NOT_RECORDED; no proxy invented", "mixed_logistic": "NOT_FIT; no mixed-effects runtime and current grid has confounding",
        "statistical_correction": "binary critical metrics use exact McNemar as primary; representative terminology is canonical, not deterministic; failure decomposition added; no base legal outputs changed",
        "failure_decomposition": "legalpass_failure_decomposition.csv; exact combinations of omission, contradiction, unsupported addition, and fields flags",
        "significant_legalpass_pairs_after_holm": len(significant_pairs), "significant_continuous_rows_after_holm": len(significant_continuous),
        "v1_v2_spearman_factual_fidelity_vs_legalpass": v1_spearman, "figures": figure_names,
    }
    (out / "analysis_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    best_row = ranking[0]
    report_path = out / "analysis_summary.json"
    report_path.write_text(json.dumps({"best": best_row, "significant_pairs": significant_pairs, "significant_continuous": significant_continuous, "controlled_pair_count": len({(row['config_a'], row['config_b']) for row in controlled}), "effects": effects, "v1_spearman": v1_spearman}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"primary_unique_configs": len(configs), "pairwise": len(pairwise), "controlled_rows": len(controlled), "controlled_pairs": len({(row['config_a'], row['config_b']) for row in controlled}), "significant_legalpass_after_holm": len(significant_pairs), "significant_continuous_after_holm": len(significant_continuous), "best_observed": best_row["run"], "best_legalpass": best_row["legal_pass_rate"], "v1_spearman": v1_spearman}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
