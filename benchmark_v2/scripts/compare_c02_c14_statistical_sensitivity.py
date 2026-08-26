"""Compare statistical-only Benchmark V2 scenario A (C02) and B (C14).

Both scenario directories are generated from the existing per-case JSONL
outputs.  This script only reads CSVs and writes a comparison table; it never
calls generation or the legal evaluator.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def bool_value(value: Any) -> bool:
    return str(value).lower() in {"true", "1", "yes"}


def changed(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return str(a) != str(b)
    try:
        return abs(float(a) - float(b)) > 1e-12
    except (TypeError, ValueError):
        return str(a) != str(b)


def pair_key(row: dict[str, str]) -> tuple[str, str]:
    return tuple(sorted((row["config_hash_a"], row["config_hash_b"])))


def normalized_delta(row: dict[str, str]) -> float | None:
    value = as_float(row.get("delta_pp_b_minus_a"))
    if value is None:
        return None
    return value if row["config_hash_a"] <= row["config_hash_b"] else -value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-a", type=Path, required=True)
    parser.add_argument("--scenario-b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    a = args.scenario_a
    b = args.scenario_b
    rows: list[dict[str, Any]] = []

    rank_a = {row["config_hash"]: row for row in read_csv(a / "statistical_ranking.csv")}
    rank_b = {row["config_hash"]: row for row in read_csv(b / "statistical_ranking.csv")}
    common_hashes = sorted(set(rank_a) & set(rank_b))
    for config_hash in common_hashes:
        left, right = rank_a[config_hash], rank_b[config_hash]
        rank_changed = changed(left.get("rank_observed"), right.get("rank_observed"))
        rows.append({
            "scope": "ranking", "key": config_hash, "scenario_a_value": left.get("run"), "scenario_b_value": right.get("run"),
            "scenario_a_rank": left.get("rank_observed"), "scenario_b_rank": right.get("rank_observed"),
            "scenario_a_legalpass": left.get("legal_pass_rate"), "scenario_b_legalpass": right.get("legal_pass_rate"),
            "scenario_a_tier": left.get("tier"), "scenario_b_tier": right.get("tier"),
            "scenario_a_pareto": left.get("is_pareto_optimal"), "scenario_b_pareto": right.get("is_pareto_optimal"),
            "changed": rank_changed, "material_change": False,
            "interpretation": "descriptive rank may change because the same config_hash has different saved outputs; this row is not a causal conclusion",
        })

    best_a = max(rank_a.values(), key=lambda row: (as_float(row.get("legal_pass_rate")) or 0.0, -(int(row.get("rank_observed") or 999))))
    best_b = max(rank_b.values(), key=lambda row: (as_float(row.get("legal_pass_rate")) or 0.0, -(int(row.get("rank_observed") or 999))))
    rows.append({
        "scope": "best_observed", "key": "best_observed", "scenario_a_value": best_a.get("run"), "scenario_b_value": best_b.get("run"),
        "scenario_a_config_hash": best_a.get("config_hash"), "scenario_b_config_hash": best_b.get("config_hash"),
        "scenario_a_legalpass": best_a.get("legal_pass_rate"), "scenario_b_legalpass": best_b.get("legal_pass_rate"),
        "changed": best_a.get("config_hash") != best_b.get("config_hash"), "material_change": best_a.get("config_hash") != best_b.get("config_hash"),
        "interpretation": "BEST OBSERVED changes only if the configuration hash at the top changes",
    })

    tier_a = {key for key, row in rank_a.items() if row.get("tier") == "1"}
    tier_b = {key for key, row in rank_b.items() if row.get("tier") == "1"}
    rows.append({
        "scope": "tiers", "key": "tier_1_membership", "scenario_a_value": ";".join(sorted(tier_a)), "scenario_b_value": ";".join(sorted(tier_b)),
        "changed": tier_a != tier_b, "material_change": tier_a != tier_b,
        "interpretation": "Tier 1 is non-distinguishability from the best after Holm, not equivalence",
    })
    pareto_a = {key for key, row in rank_a.items() if bool_value(row.get("is_pareto_optimal"))}
    pareto_b = {key for key, row in rank_b.items() if bool_value(row.get("is_pareto_optimal"))}
    rows.append({
        "scope": "pareto_front", "key": "pareto_membership", "scenario_a_value": ";".join(sorted(pareto_a)), "scenario_b_value": ";".join(sorted(pareto_b)),
        "changed": pareto_a != pareto_b, "material_change": pareto_a != pareto_b,
        "interpretation": "descriptive multi-objective screen; not statistical superiority",
    })

    pair_a = {pair_key(row): row for row in read_csv(a / "legalpass_pairwise_matrix.csv")}
    pair_b = {pair_key(row): row for row in read_csv(b / "legalpass_pairwise_matrix.csv")}
    sig_a = {key for key, row in pair_a.items() if bool_value(row.get("significant_alpha_0_05"))}
    sig_b = {key for key, row in pair_b.items() if bool_value(row.get("significant_alpha_0_05"))}
    rows.append({
        "scope": "pairwise_significance", "key": "holm_significant_pairs", "scenario_a_value": ";".join("|".join(key) for key in sorted(sig_a)),
        "scenario_b_value": ";".join("|".join(key) for key in sorted(sig_b)), "changed": sig_a != sig_b, "material_change": sig_a != sig_b,
        "interpretation": "primary LegalPass significance set after Holm",
    })
    for key in sorted(set(pair_a) & set(pair_b)):
        left, right = pair_a[key], pair_b[key]
        p_changed = changed(left.get("holm_p_value"), right.get("holm_p_value"))
        sig_changed = bool_value(left.get("significant_alpha_0_05")) != bool_value(right.get("significant_alpha_0_05"))
        rows.append({
            "scope": "pairwise_holm_p", "key": "|".join(key), "scenario_a_value": left.get("holm_p_value"), "scenario_b_value": right.get("holm_p_value"),
            "scenario_a_raw_p": left.get("p_value"), "scenario_b_raw_p": right.get("p_value"), "changed": p_changed,
            "material_change": sig_changed, "interpretation": "Holm-adjusted p-value; material only when significance decision changes",
        })

    controlled_a = read_csv(a / "hyperparameter_controlled_contrasts.csv")
    controlled_b = read_csv(b / "hyperparameter_controlled_contrasts.csv")
    control_key = lambda row: (pair_key(row), row["parameter"], row["metric"])
    controls_a = {control_key(row): row for row in controlled_a}
    controls_b = {control_key(row): row for row in controlled_b}
    primary_sig_a = {key for key, row in controls_a.items() if bool_value(row.get("primary_significant_alpha_0_05"))}
    primary_sig_b = {key for key, row in controls_b.items() if bool_value(row.get("primary_significant_alpha_0_05"))}
    rows.append({
        "scope": "controlled_contrasts", "key": "primary_significance_set", "scenario_a_value": ";".join(str(key) for key in sorted(primary_sig_a)),
        "scenario_b_value": ";".join(str(key) for key in sorted(primary_sig_b)), "changed": primary_sig_a != primary_sig_b,
        "material_change": primary_sig_a != primary_sig_b, "interpretation": "binary metrics use McNemar; continuous metrics use paired bootstrap",
    })
    for key in sorted(set(controls_a) & set(controls_b)):
        left, right = controls_a[key], controls_b[key]
        sig_changed = bool_value(left.get("primary_significant_alpha_0_05")) != bool_value(right.get("primary_significant_alpha_0_05"))
        rows.append({
            "scope": "controlled_contrast", "key": "|".join(map(str, key)), "scenario_a_value": left.get("primary_delta_pp_b_minus_a"),
            "scenario_b_value": right.get("primary_delta_pp_b_minus_a"), "scenario_a_raw_p": left.get("primary_p_value"),
            "scenario_b_raw_p": right.get("primary_p_value"), "scenario_a_holm_p": left.get("holm_primary_p_value"),
            "scenario_b_holm_p": right.get("holm_primary_p_value"), "changed": changed(left.get("primary_delta_pp_b_minus_a"), right.get("primary_delta_pp_b_minus_a")),
            "material_change": sig_changed, "interpretation": "effect direction may shift slightly with the canonical output; material only when the adjusted decision changes",
        })

    effect_a = {(row["parameter"], row["metric"]): row for row in read_csv(a / "hyperparameter_effect_summary.csv")}
    effect_b = {(row["parameter"], row["metric"]): row for row in read_csv(b / "hyperparameter_effect_summary.csv")}
    effect_sig_a = {(key) for key, row in effect_a.items() if int(row.get("holm_significant_contrasts") or 0) > 0}
    effect_sig_b = {(key) for key, row in effect_b.items() if int(row.get("holm_significant_contrasts") or 0) > 0}
    rows.append({
        "scope": "hyperparameter_conclusion", "key": "significant_effect_families", "scenario_a_value": ";".join(map(str, sorted(effect_sig_a))),
        "scenario_b_value": ";".join(map(str, sorted(effect_sig_b))), "changed": effect_sig_a != effect_sig_b, "material_change": effect_sig_a != effect_sig_b,
        "interpretation": "no causal attribution beyond controlled contrasts",
    })
    for key in sorted(set(effect_a) & set(effect_b)):
        left, right = effect_a[key], effect_b[key]
        rows.append({
            "scope": "effect_summary", "key": "|".join(key), "scenario_a_value": left.get("median_delta"), "scenario_b_value": right.get("median_delta"),
            "changed": changed(left.get("median_delta"), right.get("median_delta")),
            "material_change": int(left.get("holm_significant_contrasts") or 0) != int(right.get("holm_significant_contrasts") or 0),
            "interpretation": "descriptive effect summary",
        })

    material_rows = [row for row in rows if bool(row.get("material_change"))]
    status = "CHANGED" if material_rows else "ROBUST_TO_CANONICAL_REPRESENTATIVE_SELECTION"
    rows.insert(0, {
        "scope": "sensitivity_status", "key": "C02_vs_C14_canonical_selection", "scenario_a_value": "C02", "scenario_b_value": "C14",
        "changed": bool(material_rows), "material_change": bool(material_rows), "status": status,
        "interpretation": "C14 is a candidate replicate with unknown seed, not a confirmed controlled replicate; scenario B is statistical sensitivity only",
    })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_csv(args.output, rows)
    manifest_path = a / "analysis_manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["c02_c14_sensitivity"] = {
            "scenario_a": "C02 canonical representative",
            "scenario_b": "C14 alternate output for same config_hash",
            "status": status,
            "material_changes": len(material_rows),
            "comparison_csv": args.output.name,
            "controlled_replicate_claim": "not_claimed; seed is NOT_RECORDED",
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print({"status": status, "rows": len(rows), "material_changes": len(material_rows), "best_a": best_a["run"], "best_b": best_b["run"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
