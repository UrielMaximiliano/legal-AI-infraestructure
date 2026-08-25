"""Audit evaluator labels on a stratified sample and deterministic challenges."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Allow this file to be invoked directly from the repository root, matching
# the other benchmark scripts.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from benchmark_v2.evaluators.legal_core import EVALUATOR_VERSION, RULES_VERSION, evaluate_case


def load_jsonl(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            if isinstance(item, dict):
                result[(str(item.get("reference_pdf", "")).lower(), str(item.get("reference_sha256", "")).lower())] = item
    return result


def files(row: dict[str, Any]) -> list[Path]:
    run_dir = Path(str(row["source_run_dir"]))
    nested = sorted((run_dir / "cases").glob("case-*.json"))
    return nested or sorted(run_dir.glob("case-*.json"))


def synthetic(text: str, *, prompt: str | None = None, contract_prohibition: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    prompt_text = prompt or "El Ministerio de Justicia debe autorizar la contratación conforme al Decreto 1234/2020, para DNI 12345678, por $1000, con vigencia el 1 de marzo de 2025."
    case = {"external_id": "CALIBRATION-0001", "input": {"external_id": "CALIBRATION-0001", "prompt_text": prompt_text}, "output": {"articles": [{"number": 1, "text": text}]}, "sources": [{"citation_id": "SRC-001", "chunk_id": "calibration"}]}
    gold: dict[str, Any] = {"reference_pdf": "calibration.pdf", "reference_sha256": "c" * 64, "field_candidates": {"organismo": "Ministerio de Justicia", "objeto": "debe autorizar la contratación", "normas_citadas": ["Decreto 1234/2020"], "fecha_plazo_vigencia": ["1 de marzo de 2025"], "articulos_resolutivos": {"1": "autorizar la contratación"}, "monto": ["1000"], "dni": ["DNI 12345678"]}}
    if contract_prohibition:
        gold["prohibited_formulas"] = ["comuniquese"]
    return case, gold


def challenges() -> list[dict[str, Any]]:
    original_text = "El Ministerio de Justicia debe autorizar la contratación conforme al Decreto 1234/2020, para DNI 12345678, por $1000, con vigencia el 1 de marzo de 2025."
    paraphrase_text = "Conforme al Decreto 1234/2020, el Ministerio de Justicia debe autorizar la contratación: DNI 12345678, monto $1000 y vigencia desde el 1 de marzo de 2025."
    cases: list[tuple[str, str, bool]] = [
        ("original_equals_original", original_text, True),
        ("legal_paraphrase", paraphrase_text, True),
        ("amount_altered", original_text.replace("$1000", "$2000"), False),
        ("dni_altered", original_text.replace("12345678", "87654321"), False),
        ("material_date_altered", original_text.replace("1 de marzo de 2025", "2 de marzo de 2025"), False),
        ("negation_inverted", original_text, False),
        ("deontic_modality_altered", original_text.replace("debe autorizar", "puede autorizar"), False),
        ("critical_omission", original_text.replace("El Ministerio de Justicia ", ""), False),
    ]
    output: list[dict[str, Any]] = []
    for name, text, expected in cases:
        prompt = None
        if name == "negation_inverted":
            prompt = "El Ministerio de Justicia no debe autorizar la contratación conforme al Decreto 1234/2020, para DNI 12345678, por $1000, con vigencia el 1 de marzo de 2025."
        case, gold = synthetic(text, prompt=prompt)
        result = evaluate_case(case, gold)
        output.append({"challenge": name, "expected_pass": expected, "observed_pass": bool(result["legal_pass"]), "meets_expectation": bool(result["legal_pass"]) == expected, "legal_pass_reasons": result["legal_pass_reasons"], "contradiction_kinds": [item.get("kind") for item in result["contradictions"]["items"]], "unsupported_kinds": [item.get("kind") for item in result["unsupported_additions"]["items"]]})
    formula_case, formula_gold = synthetic(original_text + " COMUNIQUESE.")
    formula = evaluate_case(formula_case, formula_gold)
    prohibited_case, prohibited_gold = synthetic(original_text + " COMUNIQUESE.", contract_prohibition=True)
    prohibited = evaluate_case(prohibited_case, prohibited_gold)
    output.extend([
        {"challenge": "standard_formula_allowed_by_default", "expected_pass": True, "observed_pass": bool(formula["legal_pass"]), "meets_expectation": bool(formula["legal_pass"]), "unsupported_kinds": [item.get("kind") for item in formula["unsupported_additions"]["items"]]},
        {"challenge": "standard_formula_contract_prohibited", "expected_pass": False, "observed_pass": bool(prohibited["legal_pass"]), "meets_expectation": not bool(prohibited["legal_pass"]), "unsupported_kinds": [item.get("kind") for item in prohibited["unsupported_additions"]["items"]]},
    ])
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("benchmark_v2/results/all-runs-20260825/evaluator-calibration"))
    parser.add_argument("--sample-size", type=int, default=40)
    parser.add_argument("--seed", type=int, default=20260825)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    inventory_path = args.inventory / "artifact_to_logical_run_reconciliation.json"
    rows = json.loads(inventory_path.read_text(encoding="utf-8")) if inventory_path.is_file() else json.loads((args.inventory / "runs_inventory.json").read_text(encoding="utf-8"))
    gold = load_jsonl(args.gold)
    rng = random.Random(args.seed)
    by_class: dict[str, list[tuple[dict[str, Any], Path]]] = {}
    for row in rows:
        classification = str(row.get("classification") or ("PRIMARY_FULL_1000" if row.get("integrity") == "FULL" else row.get("integrity", "UNKNOWN")))
        by_class.setdefault(classification, []).extend((row, path) for path in files(row))
    classes = sorted(by_class)
    selected: list[tuple[str, dict[str, Any], Path]] = []
    per_class = max(1, args.sample_size // max(1, len(classes)))
    for classification in classes:
        candidates = by_class[classification][:]
        rng.shuffle(candidates)
        selected.extend((classification, row, path) for row, path in candidates[:per_class])
    if len(selected) < args.sample_size:
        remaining = [(classification, row, path) for classification, candidates in by_class.items() for row, path in candidates if (classification, row, path) not in selected]
        rng.shuffle(remaining)
        selected.extend(remaining[: args.sample_size - len(selected)])
    sample_rows: list[dict[str, Any]] = []
    unsupported_kinds: Counter[str] = Counter()
    omission_fields: Counter[str] = Counter()
    for classification, row, path in selected[: args.sample_size]:
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        key = (str(case.get("reference_pdf", "")).lower(), str(case.get("reference_sha256", "")).lower())
        reference = gold.get(key)
        if reference is None:
            continue
        result = evaluate_case(case, reference)
        for item in result["unsupported_additions"]["items"]:
            unsupported_kinds[str(item.get("kind"))] += 1
        for item in result["omissions"]["items"]:
            omission_fields[str(item.get("field"))] += 1
        sample_rows.append({"classification": classification, "artifact_id": row.get("artifact_id", row.get("inventory_id")), "case_file": path.name, "case_id": result.get("case_id"), "legal_pass": result.get("legal_pass"), "legal_pass_reasons": result.get("legal_pass_reasons"), "unsupported_additions": result.get("unsupported_additions"), "omissions": result.get("omissions"), "contradictions": result.get("contradictions"), "evaluator_version": result.get("evaluator_version")})
    (args.output_dir / "sample.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in sample_rows), encoding="utf-8")
    sanity = challenges()
    audit = {"schema_version": "benchmark-v2-evaluator-calibration-1", "evaluator_version": EVALUATOR_VERSION, "rules_version": RULES_VERSION, "evaluator_sha256": hashlib.sha256(Path(__file__).resolve().parents[2].joinpath("benchmark_v2/evaluators/legal_core/evaluator.py").read_bytes()).hexdigest(), "sample_size_requested": args.sample_size, "sample_size_evaluated": len(sample_rows), "strata": {key: sum(row["classification"] == key for row in sample_rows) for key in classes}, "unsupported_kind_counts": dict(unsupported_kinds), "omission_field_counts": dict(omission_fields), "sanity_challenges": sanity, "sanity_all_pass": all(item["meets_expectation"] for item in sanity), "allowed_information_set": ["prompt", "gold field candidates/facts", "explicit contract/template rules"], "retrieval_status": "NOT_RECONSTRUCTABLE when historical chunk text is absent", "recompute_required": True}
    (args.output_dir / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"sample_size_evaluated": len(sample_rows), "sanity_all_pass": audit["sanity_all_pass"], "unsupported_kind_counts": dict(unsupported_kinds), "evaluator_version": EVALUATOR_VERSION}, sort_keys=True))
    return 0 if audit["sanity_all_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
