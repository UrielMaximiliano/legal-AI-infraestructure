"""CLI entry point for leakage-safe RAG holdout evaluation."""

from __future__ import annotations

import asyncio
import json

from legal_ai.application.rag_evaluation import (
    evaluate_manifest,
    find_operational_holdout_leaks,
    load_manifest,
)


def run(path: str, *, execute: bool, provider: str, limit: int | None) -> int:
    manifest, _root = load_manifest(path, limit=limit)
    leakage_detected = asyncio.run(find_operational_holdout_leaks(manifest))
    payload = evaluate_manifest(
        path,
        execute=execute,
        provider=provider,
        limit=limit,
        leakage_detected=leakage_detected,
    )
    print(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    return 0
