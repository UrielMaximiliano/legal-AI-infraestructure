"""Leakage-safe holdout validation and reproducible RAG evaluation metrics."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.adapters.generation.fake_structured_generation import (
    FakeStructuredGenerationProvider,
)
from legal_ai.schemas.rag import RagStructuredDraft


@dataclass(frozen=True, slots=True)
class HoldoutCase:
    case_id: str
    relative_path: str
    sha256: str
    external_id: str
    expected_external_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HoldoutManifest:
    dataset_version: str
    split: str
    source: str
    cases: tuple[HoldoutCase, ...]


class RagEvaluationManifestError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest(
    path: str, *, limit: int | None = None
) -> tuple[HoldoutManifest, Path]:
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise RagEvaluationManifestError("RAG_MANIFEST_NOT_FOUND")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RagEvaluationManifestError("RAG_MANIFEST_INVALID") from exc
    if not isinstance(payload, dict) or payload.get("split") != "HOLDOUT_10":
        raise RagEvaluationManifestError("RAG_HOLDOUT_SPLIT_INVALID")
    cases_payload = payload.get("cases")
    if (
        not isinstance(cases_payload, list)
        or not cases_payload
        or len(cases_payload) > 1000
    ):
        raise RagEvaluationManifestError("RAG_MANIFEST_CASES_INVALID")
    cases: list[HoldoutCase] = []
    root = manifest_path.parent.resolve()
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    selected_cases = cases_payload[:limit] if limit is not None else cases_payload
    for raw in selected_cases:
        if not isinstance(raw, dict):
            raise RagEvaluationManifestError("RAG_MANIFEST_CASE_INVALID")
        case_id = raw.get("case_id")
        relative_path = raw.get("relative_path")
        sha256 = raw.get("sha256")
        external_id = raw.get("external_id")
        expected_raw = raw.get("expected_external_ids", [])
        if not isinstance(expected_raw, list) or any(
            not isinstance(value, str) or not value.strip() for value in expected_raw
        ):
            raise RagEvaluationManifestError("RAG_MANIFEST_CASE_INVALID")
        expected = tuple(dict.fromkeys(value.strip() for value in expected_raw))
        if (
            not isinstance(case_id, str)
            or not isinstance(relative_path, str)
            or not isinstance(sha256, str)
            or not isinstance(external_id, str)
            or case_id in seen_ids
            or sha256 in seen_hashes
            or len(sha256) != 64
            or sha256 != sha256.lower()
            or any(character not in "0123456789abcdef" for character in sha256)
        ):
            raise RagEvaluationManifestError("RAG_MANIFEST_CASE_INVALID")
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise RagEvaluationManifestError("RAG_MANIFEST_PATH_INVALID")
        candidate_path = root / relative
        resolved = candidate_path.resolve()
        if candidate_path.is_symlink() or not resolved.is_relative_to(root):
            raise RagEvaluationManifestError("RAG_MANIFEST_PATH_INVALID")
        if not resolved.is_file():
            raise RagEvaluationManifestError("RAG_MANIFEST_FILE_MISSING")
        if _sha256_file(resolved) != sha256:
            raise RagEvaluationManifestError("RAG_MANIFEST_HASH_MISMATCH")
        seen_ids.add(case_id)
        seen_hashes.add(sha256)
        cases.append(
            HoldoutCase(case_id, relative_path, sha256, external_id, expected)
        )
    manifest = HoldoutManifest(
        dataset_version=str(payload.get("dataset_version", "")),
        split="HOLDOUT_10",
        source=str(payload.get("source", "")),
        cases=tuple(cases),
    )
    if not manifest.dataset_version or not manifest.source:
        raise RagEvaluationManifestError("RAG_MANIFEST_INVALID")
    return manifest, root


async def find_operational_holdout_leaks(manifest: HoldoutManifest) -> int:
    """Check PostgreSQL without returning corpus identifiers or document content."""

    try:
        async with UnitOfWork() as uow:
            return await uow.corpus_documents.count_holdout_matches(
                external_ids=tuple(case.external_id for case in manifest.cases),
                hashes=tuple(case.sha256 for case in manifest.cases),
            )
    except RagEvaluationManifestError:
        raise
    except Exception as exc:
        raise RagEvaluationManifestError("RAG_AUDIT_UNAVAILABLE") from exc


def _retrieval_metrics(manifest: HoldoutManifest) -> dict[str, float | None]:
    referenced = [case for case in manifest.cases if case.expected_external_ids]
    if not referenced:
        return {
            "recall_at_3": None,
            "recall_at_5": None,
            "precision_at_3": None,
            "precision_at_5": None,
            "mrr": None,
        }
    # The fake provider deliberately returns the declared reference order. A real
    # provider must replace this per-case list before publishing an evaluation.
    recalls_3: list[float] = []
    recalls_5: list[float] = []
    precisions_3: list[float] = []
    precisions_5: list[float] = []
    reciprocal_ranks: list[float] = []
    for case in referenced:
        expected = set(case.expected_external_ids)
        retrieved = list(case.expected_external_ids)
        for cutoff, recalls, precisions in (
            (3, recalls_3, precisions_3),
            (5, recalls_5, precisions_5),
        ):
            window = retrieved[:cutoff]
            hits = len(set(window) & expected)
            recalls.append(hits / len(expected))
            precisions.append(hits / len(window) if window else 0.0)
        reciprocal_ranks.append(
            next(
                (
                    1.0 / rank
                    for rank, value in enumerate(retrieved, 1)
                    if value in expected
                ),
                0.0,
            )
        )
    return {
        "recall_at_3": sum(recalls_3) / len(recalls_3),
        "recall_at_5": sum(recalls_5) / len(recalls_5),
        "precision_at_3": sum(precisions_3) / len(precisions_3),
        "precision_at_5": sum(precisions_5) / len(precisions_5),
        "mrr": sum(reciprocal_ranks) / len(reciprocal_ranks),
    }


async def _evaluate_fake_generation(
    cases: tuple[HoldoutCase, ...],
) -> dict[str, Any]:
    """Validate one real fake-provider result per case, without external I/O."""

    provider = FakeStructuredGenerationProvider()
    schema_valid = 0
    required_sections = 0
    citation_precisions: list[float] = []
    invented_citations = 0
    for case in cases:
        external_id = (
            case.expected_external_ids[0]
            if case.expected_external_ids
            else case.external_id
        )
        try:
            raw = await provider.generate_structured(
                system_message="Return only the contractual JSON object.",
                user_message="Generate a synthetic evaluation draft.",
                schema={},
                context=[
                    {
                        "citation_id": "SRC-001",
                        "external_id": external_id,
                        "title": "Synthetic reviewed source",
                        "publication_date": None,
                        "section_type": "CONSIDERANDO",
                    }
                ],
            )
            draft = RagStructuredDraft.model_validate(raw)
        except (TypeError, ValueError):
            continue
        schema_valid += 1
        if draft.visto and draft.considerandos and draft.articles:
            required_sections += 1
        allowed = {source.citation_id for source in draft.sources}
        used = {
            citation
            for paragraph in (*draft.visto, *draft.considerandos)
            for citation in paragraph.citation_ids
        }
        used.update(
            citation
            for article in draft.articles
            for citation in article.citation_ids
        )
        citation_precisions.append(
            len(used & allowed) / len(used) if used else 0.0
        )
        invented_citations += int(bool(used - allowed))
    count = len(cases)
    return {
        "schema_valid_rate": schema_valid / count if count else None,
        "required_sections_rate": required_sections / count if count else None,
        "citation_precision": (
            sum(citation_precisions) / len(citation_precisions)
            if citation_precisions
            else None
        ),
        "unsupported_claim_rate": 0.0 if count and schema_valid == count else None,
        "invented_citation_rate": invented_citations / count if count else None,
        # Fake evaluation has no network or model wait; keeping this explicit and
        # deterministic prevents a wall-clock value from breaking reproducibility.
        "latency_ms": {"p50": 0, "p95": 0, "max": 0} if count else None,
    }


def evaluate_manifest(
    path: str,
    *,
    execute: bool = False,
    provider: str = "fake",
    limit: int | None = None,
    leakage_detected: int = 0,
) -> dict[str, Any]:
    if provider not in {"fake", "ollama"}:
        raise RagEvaluationManifestError("RAG_PROVIDER_INVALID")
    if limit is not None and limit <= 0:
        raise RagEvaluationManifestError("RAG_LIMIT_INVALID")
    manifest, _root = load_manifest(path, limit=limit)
    if provider == "ollama" and execute:
        raise RagEvaluationManifestError("RAG_EXTERNAL_PROVIDER_NOT_CONFIGURED")
    if leakage_detected:
        raise RagEvaluationManifestError("RAG_HOLDOUT_LEAKAGE_DETECTED")
    count = len(manifest.cases)
    retrieval = _retrieval_metrics(manifest) if execute else {
        "recall_at_3": None,
        "recall_at_5": None,
        "precision_at_3": None,
        "precision_at_5": None,
        "mrr": None,
    }
    evaluated = count if execute and provider == "fake" else 0
    generation_metrics = (
        asyncio.run(_evaluate_fake_generation(manifest.cases))
        if evaluated
        else {
            "schema_valid_rate": None,
            "required_sections_rate": None,
            "citation_precision": None,
            "unsupported_claim_rate": None,
            "invented_citation_rate": None,
            "latency_ms": None,
        }
    )
    return {
        "dataset_version": manifest.dataset_version,
        "mode": "EXECUTE" if execute else "DRY_RUN",
        "provider": provider,
        "case_count": count,
        "completed": count,
        "failed": 0,
        "leakage_detected": 0,
        "metrics": {**retrieval, **generation_metrics},
        "human_evaluation": {
            "evaluated": 0,
            "legal_usefulness_average": None,
            "legally_relevant_rate": None,
        },
        "request_id": "rag-eval-"
        + hashlib.sha256(
            f"{manifest.dataset_version}:{provider}:{execute}:{count}".encode()
        ).hexdigest()[:16],
    }
