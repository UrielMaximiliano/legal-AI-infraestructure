"""Run a resumable, sequential RAG benchmark from sanitized Markdown prompts."""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_PROMPT_NAME = re.compile(r"^prompt-(?P<number>[0-9]{4})-(?P<external>[0-9]+)\.md$")


@dataclass(frozen=True)
class BenchmarkCase:
    number: int
    external_id: str
    name: str
    reference_pdf: str
    reference_sha256: str
    object_text: str
    topic: str
    organization: str


def _field(text: str, label: str) -> str:
    match = re.search(rf"^- {re.escape(label)}:\s*`?([^`\r\n]+)`?\s*$", text, re.M)
    if match is None:
        raise ValueError(f"BENCHMARK_PROMPT_FIELD_MISSING:{label}")
    return match.group(1).strip()


def parse_prompt(path: Path) -> BenchmarkCase:
    match = _PROMPT_NAME.fullmatch(path.name)
    if match is None:
        raise ValueError("BENCHMARK_PROMPT_FILENAME_INVALID")
    text = path.read_text(encoding="utf-8")
    object_match = re.search(
        r"^>\s*(.+?)(?=\r?\n\r?\n(?:Área temática|Area tematica):)",
        text,
        re.M | re.S,
    )
    topic_match = re.search(
        r"^(?:Área temática|Area tematica):\s*(.+?)\.\s*$", text, re.M
    )
    organization_match = re.search(r"^Organismo competente:\s*(.+?)\.\s*$", text, re.M)
    if object_match is None or topic_match is None or organization_match is None:
        raise ValueError("BENCHMARK_PROMPT_BODY_INVALID")
    return BenchmarkCase(
        number=int(match.group("number")),
        external_id=match.group("external"),
        name=_field(text, "Nombre"),
        reference_pdf=_field(text, "PDF de referencia"),
        reference_sha256=_field(text, "SHA-256"),
        object_text=" ".join(object_match.group(1).split()),
        topic=" ".join(topic_match.group(1).split()),
        organization=" ".join(organization_match.group(1).split()),
    )


def _atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 600,
) -> tuple[int, dict[str, Any]]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:4096]
        try:
            detail: dict[str, Any] = json.loads(body)
        except json.JSONDecodeError:
            detail = {"error": "BENCHMARK_HTTP_ERROR"}
        return exc.code, detail


def _write_summary(output: Path, records: list[dict[str, Any]]) -> None:
    columns = (
        "case_number",
        "external_id",
        "status",
        "http_status",
        "rag_run_id",
        "retrieved",
        "selected",
        "retrieval_ms",
        "generation_ms",
        "total_ms",
        "error_code",
    )
    with (output / "summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    with (output / "results.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def run(args: argparse.Namespace) -> int:
    prompts = sorted(
        path
        for path in args.prompts.glob("prompt-*.md")
        if (
            (match := _PROMPT_NAME.fullmatch(path.name))
            and int(match.group("number")) >= args.start_case
        )
    )[: args.limit]
    if not prompts:
        raise ValueError("BENCHMARK_PROMPTS_EMPTY")
    output = args.output
    cases_dir = output / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    configuration = {
        "run_id": args.run_id,
        "started_at": datetime.now(UTC).isoformat(),
        "api_base_url": args.api_base_url,
        "template_id": args.template_id,
        "case_file_id": args.case_file_id,
        "requested_cases": len(prompts),
        "start_case": args.start_case,
        "top_k": args.top_k,
        "minimum_score": args.minimum_score,
        "execution": "sequential_monoslot",
        "ground_truth_policy": "reference_pdf_not_sent_to_model",
    }
    _atomic_json(output / "configuration.json", configuration)
    started = time.monotonic()
    records: list[dict[str, Any]] = []
    for index, path in enumerate(prompts, start=1):
        case = parse_prompt(path)
        case_path = cases_dir / f"case-{case.number:04d}.json"
        if case_path.exists():
            records.append(json.loads(case_path.read_text(encoding="utf-8")))
            continue
        request_id = f"benchmark-{args.run_id}-{case.number:04d}"
        payload = {
            "template_id": args.template_id,
            "case_file_id": args.case_file_id,
            "variables": {
                "objeto": case.object_text,
                "area_tematica": case.topic,
                "organismo": case.organization,
                "restriccion": (
                    "No inventar hechos, personas, fechas, montos ni normas."
                ),
            },
            "retrieval": {
                "top_k": args.top_k,
                "minimum_score": args.minimum_score,
                "language": "es",
            },
        }
        request_started = time.monotonic()
        status, response = _request_json(
            f"{args.api_base_url.rstrip('/')}/api/v1/rag/drafts/generate",
            method="POST",
            payload=payload,
            headers={"Idempotency-Key": request_id, "X-Request-ID": request_id},
            timeout=args.timeout,
        )
        run_data: dict[str, Any] = {}
        rag_run_id = response.get("rag_run_id")
        if rag_run_id:
            _, run_data = _request_json(
                f"{args.api_base_url.rstrip('/')}/api/v1/rag/runs/{rag_run_id}",
                timeout=args.timeout,
            )
        durations = run_data.get("durations_ms", {})
        retrieval = response.get("retrieval", run_data.get("retrieval", {}))
        record = {
            "case_number": case.number,
            "external_id": case.external_id,
            "name": case.name,
            "reference_pdf": case.reference_pdf,
            "reference_sha256": case.reference_sha256,
            "status": "SUCCEEDED" if status in {200, 201} else "FAILED",
            "http_status": status,
            "rag_run_id": rag_run_id,
            "draft_id": response.get("draft", {}).get("id"),
            "input": asdict(case),
            "output": response.get("structured_draft"),
            "retrieved": retrieval.get("result_count", retrieval.get("retrieved", 0)),
            "selected": retrieval.get("selected_count", retrieval.get("selected", 0)),
            "sources": run_data.get("sources", []),
            "retrieval_ms": durations.get("retrieval"),
            "generation_ms": durations.get("generation"),
            "total_ms": durations.get(
                "total", max(0, int((time.monotonic() - request_started) * 1000))
            ),
            "error_code": (
                run_data.get("error_code")
                or response.get("error_code")
                or response.get("code")
            ),
            "error_details": response.get("details") if status >= 400 else None,
        }
        _atomic_json(case_path, record)
        records.append(record)
        elapsed = time.monotonic() - started
        rate = index / elapsed if elapsed else 0.0
        _atomic_json(
            output / "progress.json",
            {
                "completed": index,
                "total": len(prompts),
                "succeeded": sum(item["status"] == "SUCCEEDED" for item in records),
                "failed": sum(item["status"] == "FAILED" for item in records),
                "elapsed_seconds": round(elapsed, 1),
                "estimated_remaining_seconds": round((len(prompts) - index) / rate, 1)
                if rate
                else None,
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )
        print(
            f"case={case.number:04d} status={record['status']} "
            f"completed={index}/{len(prompts)} total_ms={record['total_ms']}",
            flush=True,
        )
    _write_summary(output, records)
    return 0 if all(record["status"] == "SUCCEEDED" for record in records) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--template-id", required=True)
    parser.add_argument("--case-file-id", required=True)
    parser.add_argument("--run-id", default=uuid.uuid4().hex[:12])
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--start-case", type=int, default=1)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--minimum-score", type=float, default=0.0)
    parser.add_argument("--timeout", type=int, default=600)
    return parser


def main() -> None:
    raise SystemExit(run(build_parser().parse_args()))


if __name__ == "__main__":
    main()
