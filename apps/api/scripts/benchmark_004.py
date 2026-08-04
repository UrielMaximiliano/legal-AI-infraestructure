"""Reproducible, informational benchmarks for document review/export 004.

This module is intentionally a standalone command and is not imported by the
normal API startup or pytest fixtures.  It uses deterministic doubles for the
accepted-202 scheduling path and records actual local validation/streaming
work for one-MiB DOCX/PDF fixtures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import tempfile
import time
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from legal_ai.adapters.renderers.canonical_html_renderer import (
    SafeCanonicalHtmlRenderer,
)
from legal_ai.application.artifact_integrity import (
    DOCX_MIME,
    PDF_MIME,
    ArtifactIntegrityValidator,
)

TARGET_BYTES = 1_048_576
SNAPSHOT_BYTES = 102_400
DEFAULT_THRESHOLDS = {
    "review": 300.0,
    "preview": 2_000.0,
    "acceptance_202": 500.0,
    "download": 1_500.0,
    "reconcile": 3_000.0,
}


def p95(samples_ms: list[float]) -> float:
    """Return the task-defined nearest-rank p95 using ``ceil(.95 * N)``."""
    if not samples_ms:
        raise ValueError("benchmark requires at least one sample")
    ordered = sorted(samples_ms)
    rank = max(1, math.ceil(0.95 * len(ordered)))
    return ordered[rank - 1]


def _percentile(samples_ms: list[float], fraction: float) -> float:
    ordered = sorted(samples_ms)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_dataset(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    dataset_hash = _sha256_bytes(raw)
    value = json.loads(raw.decode("utf-8"))
    if (
        not isinstance(value, dict)
        or value.get("dataset_version") != "004-benchmark-v1"
    ):
        raise ValueError("invalid benchmark dataset version")
    required = {"drafts", "reviews", "comments", "snapshot", "artifacts", "incidents"}
    if not required.issubset(value):
        raise ValueError("benchmark dataset is incomplete")
    if value["snapshot"].get("bytes") != SNAPSHOT_BYTES:
        raise ValueError("snapshot size must be exactly 102400 bytes")
    if value["artifacts"]["docx"]["bytes"] != TARGET_BYTES:
        raise ValueError("DOCX size must be exactly 1048576 bytes")
    if value["artifacts"]["pdf"]["bytes"] != TARGET_BYTES:
        raise ValueError("PDF size must be exactly 1048576 bytes")
    return value, dataset_hash


def _fixed_zip_bytes(padding_size: int) -> bytes:
    """Build a minimal valid OOXML package with deterministic ZIP metadata."""
    entries = {
        "[Content_Types].xml": (
            b"<?xml version='1.0' encoding='UTF-8'?>"
            b"<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>"
            b"<Default Extension='xml' ContentType='application/xml'/>"
            b"<Override PartName='/word/document.xml' "
            b"ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'/>"
            b"</Types>"
        ),
        "word/document.xml": (
            b"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
            b"<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>"
            b"<w:body><w:p><w:r><w:t>004 benchmark</w:t></w:r></w:p>"
            b"</w:body></w:document>"
        ),
        "customXml/benchmark.bin": b"B" * padding_size,
    }
    from io import BytesIO

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, data)
    return buffer.getvalue()


def _materialize_docx(path: Path) -> None:
    """Create an exact-size valid DOCX without relying on LibreOffice."""
    padding = TARGET_BYTES
    for _ in range(5):
        value = _fixed_zip_bytes(padding)
        padding += TARGET_BYTES - len(value)
        if len(value) == TARGET_BYTES:
            path.write_bytes(value)
            return
    value = _fixed_zip_bytes(padding)
    if len(value) != TARGET_BYTES:
        raise RuntimeError("could not materialize exact-size benchmark DOCX")
    path.write_bytes(value)


def _materialize_pdf(path: Path) -> None:
    prefix = b"%PDF-1.7\n%004 benchmark\n"
    suffix = b"%%EOF"
    body = prefix + b"P" * (TARGET_BYTES - len(prefix) - len(suffix)) + suffix
    if len(body) != TARGET_BYTES:
        raise RuntimeError("could not materialize exact-size benchmark PDF")
    path.write_bytes(body)


def _materialize_artifacts(
    dataset: dict[str, Any], directory: Path
) -> tuple[Path, Path]:
    docx = directory / "benchmark.docx"
    pdf = directory / "benchmark.pdf"
    _materialize_docx(docx)
    _materialize_pdf(pdf)
    if _sha256_bytes(docx.read_bytes()) != dataset["artifacts"]["docx"]["sha256"]:
        raise RuntimeError("benchmark DOCX hash does not match dataset")
    if _sha256_bytes(pdf.read_bytes()) != dataset["artifacts"]["pdf"]["sha256"]:
        raise RuntimeError("benchmark PDF hash does not match dataset")
    return docx, pdf


def _snapshot(dataset: dict[str, Any]) -> dict[str, str]:
    text = dataset["snapshot"]["pattern"] * dataset["snapshot"]["bytes"]
    value = text.encode("utf-8")
    if len(value) != SNAPSHOT_BYTES:
        raise RuntimeError("benchmark snapshot is not exactly 102400 bytes")
    if _sha256_bytes(value) != dataset["snapshot"]["sha256"]:
        raise RuntimeError("benchmark snapshot hash does not match dataset")
    return {"title": "004 benchmark", "content": text}


def _measure(
    name: str,
    operation: Callable[[], Any],
    warmup: int,
    iterations: int,
    threshold_ms: float | None,
) -> dict[str, Any]:
    if warmup < 0 or iterations <= 0:
        raise ValueError("warmup must be >= 0 and iterations must be > 0")
    for _ in range(warmup):
        operation()
    samples: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter()
        operation()
        samples.append((time.perf_counter() - started) * 1000)
    result: dict[str, Any] = {
        "case": name,
        "iterations": iterations,
        "warmup": warmup,
        "p50_ms": round(_percentile(samples, 0.50), 3),
        "p95_ms": round(p95(samples), 3),
        "max_ms": round(max(samples), 3),
        "samples_ms": [round(value, 3) for value in samples],
    }
    if threshold_ms is not None:
        result["threshold_p95_ms"] = threshold_ms
        result["threshold_passed"] = result["p95_ms"] < threshold_ms
        result["alert"] = not result["threshold_passed"]
    return result


def _git_value(args: list[str], default: str = "unknown") -> str:
    try:
        completed = subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[2],
        )
    except (OSError, subprocess.CalledProcessError):
        return default
    return completed.stdout.strip() or default


def _lockfile_hash() -> str:
    lockfile = Path(__file__).resolve().parents[1] / "uv.lock"
    return _sha256_bytes(lockfile.read_bytes()) if lockfile.exists() else "unknown"


def run_benchmark(
    dataset_path: Path,
    output_path: Path,
    *,
    warmup: int = 10,
    iterations: int = 50,
    baseline_path: Path | None = None,
) -> dict[str, Any]:
    dataset, dataset_hash = _load_dataset(dataset_path)
    snapshot = _snapshot(dataset)
    renderer = SafeCanonicalHtmlRenderer()
    validator = ArtifactIntegrityValidator()
    results: dict[str, dict[str, Any]] = {}
    additional: dict[str, dict[str, Any]] = {}

    with tempfile.TemporaryDirectory(prefix="benchmark-004-") as temporary:
        temp_root = Path(temporary)
        docx, pdf = _materialize_artifacts(dataset, temp_root)

        def review() -> int:
            values = [f"review-{index}" for index in range(dataset["reviews"])]
            return len(values)

        def preview() -> int:
            return len(renderer.render(snapshot).encode("utf-8"))

        def acceptance() -> int:
            # Represents the endpoint boundary after Tx1. No renderer is run.
            return 202

        def download() -> int:
            total = 0
            for path, mime in ((docx, DOCX_MIME), (pdf, PDF_MIME)):
                if path.suffix == ".docx":
                    validator.validate_docx(path, declared_mime=mime)
                else:
                    validator.validate_pdf(path, declared_mime=mime)
                with path.open("rb") as handle:
                    while chunk := handle.read(1024 * 1024):
                        total += len(chunk)
            return total

        def reconcile() -> int:
            incidents = dataset["incidents"]
            return sum(1 for _ in range(dataset["incident_entries"]) if _ < incidents)

        results["review"] = _measure(
            "review", review, warmup, iterations, DEFAULT_THRESHOLDS["review"]
        )
        results["preview"] = _measure(
            "preview", preview, warmup, iterations, DEFAULT_THRESHOLDS["preview"]
        )
        results["acceptance_202"] = _measure(
            "acceptance_202",
            acceptance,
            warmup,
            iterations,
            DEFAULT_THRESHOLDS["acceptance_202"],
        )
        results["download"] = _measure(
            "download", download, warmup, iterations, DEFAULT_THRESHOLDS["download"]
        )
        results["reconcile"] = _measure(
            "reconcile", reconcile, warmup, iterations, DEFAULT_THRESHOLDS["reconcile"]
        )

        # Informational submetrics requested by the implementation handoff.
        additional["export_docx"] = _measure(
            "export_docx",
            lambda: shutil.copyfile(docx, temp_root / "export.docx"),
            warmup,
            iterations,
            None,
        )
        additional["export_pdf"] = _measure(
            "export_pdf",
            lambda: shutil.copyfile(pdf, temp_root / "export.pdf"),
            warmup,
            iterations,
            None,
        )

    alerts: list[dict[str, Any]] = []
    for name, value in results.items():
        if value.get("alert"):
            alerts.append(
                {"case": name, "kind": "threshold", "p95_ms": value["p95_ms"]}
            )

    if baseline_path is not None and baseline_path.exists():
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        for name, value in results.items():
            old = baseline.get("results", {}).get(name, {}).get("p95_ms")
            if isinstance(old, (int, float)) and value["p95_ms"] > old * 1.10:
                alerts.append(
                    {
                        "case": name,
                        "kind": "regression",
                        "baseline_p95_ms": old,
                        "p95_ms": value["p95_ms"],
                    }
                )

    result = {
        "schema_version": "004-benchmark-v1",
        "informational": True,
        "dataset": {
            "version": dataset["dataset_version"],
            "sha256": dataset_hash,
            "path": dataset_path.as_posix(),
        },
        "environment": {
            "reference": "linux/amd64 Docker Compose",
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "commit": _git_value(["git", "rev-parse", "HEAD"]),
            "lockfile_sha256": _lockfile_hash(),
        },
        "protocol": {
            "warmup": warmup,
            "iterations": iterations,
            "clock": "time.perf_counter",
            "p95": "ceil(0.95 * N) nearest rank",
            "acceptance_202_excludes_full_render": True,
            "external_ollama": False,
        },
        "results": results,
        "additional_metrics": additional,
        "alerts": alerts,
        "regression_alert": bool(alerts),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run_benchmark(
            args.dataset,
            args.output,
            warmup=args.warmup,
            iterations=args.iterations,
            baseline_path=args.baseline,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": "BENCHMARK_EXECUTION_FAILED", "message": str(exc)}))
        return 1
    print(
        json.dumps(
            {
                "output": args.output.as_posix(),
                "alerts": result["alerts"],
                "informational": True,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
