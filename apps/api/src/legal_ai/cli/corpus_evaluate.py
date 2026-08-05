"""Offline evaluation CLI using a versioned, sanitized dataset."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.adapters.ollama_embedding import OllamaEmbeddingAdapter
from legal_ai.application.retrieval_evaluation import EvaluationCase, evaluate_cases
from legal_ai.application.semantic_search import SemanticSearchService
from legal_ai.config import settings
from legal_ai.schemas.semantic_search import SemanticSearchRequest


def _load_dataset(dataset: Path) -> tuple[str, tuple[dict[str, Any], ...]]:
    payload: dict[str, Any] = json.loads(dataset.read_text(encoding="utf-8"))
    version = str(payload.get("dataset_version", "unknown"))
    raw_cases = tuple(
        item for item in payload.get("cases", []) if isinstance(item, dict)
    )
    return version, raw_cases


def run(dataset: Path) -> dict[str, object]:
    version, raw_cases = _load_dataset(dataset)
    cases = tuple(
        EvaluationCase(
            query_id=str(item["query_id"]),
            returned_ids=tuple(str(value) for value in item.get("returned_ids", [])),
            relevant_ids=frozenset(
                str(value) for value in item.get("relevant_ids", [])
            ),
            latency_ms=float(item.get("latency_ms", 0)),
            usefulness_score=item.get("usefulness_score"),
            legally_relevant=item.get("legally_relevant"),
        )
        for item in raw_cases
    )
    return evaluate_cases(cases, dataset_version=version).to_dict()


async def run_ollama(
    dataset: Path, *, include_pending_review: bool = False
) -> dict[str, object]:
    """Run the opt-in evaluation against the configured semantic-search port."""
    version, raw_cases = _load_dataset(dataset)
    ollama = settings.ollama
    provider = OllamaEmbeddingAdapter(
        base_url=ollama.base_url,
        api_token=ollama.api_token,
        model=settings.embedding.model,
        dimensions=settings.embedding.dimensions,
        timeout_seconds=ollama.timeout_seconds,
    )
    service = SemanticSearchService(
        uow_factory=UnitOfWork,
        embedding_provider=provider,
        model=settings.embedding.model,
        dimensions=settings.embedding.dimensions,
        reviewed_only=not include_pending_review,
    )
    cases: list[EvaluationCase] = []
    for index, item in enumerate(raw_cases, start=1):
        query = str(item.get("text", item.get("query_text", ""))).strip()
        if not query:
            raise ValueError("EVALUATION_QUERY_INVALID")
        request = SemanticSearchRequest(
            query=query,
            document_type=str(item.get("document_type", "decreto")),
            document_subtype=str(
                item.get("document_subtype", "designacion_transitoria")
            ),
            jurisdiction=str(item.get("jurisdiction", "nacion")),
            language=(
                str(item["language"]) if item.get("language") is not None else None
            ),
            organization=(
                str(item["organization"])
                if item.get("organization") is not None
                else None
            ),
            review_status="PENDING_REVIEW" if include_pending_review else None,
            top_k=int(item.get("top_k", 5)),
            minimum_score=(
                float(item["minimum_score"])
                if item.get("minimum_score") is not None
                else None
            ),
        )
        started = time.perf_counter()
        response = await service.search(request, request_id=f"evaluation-{index}")
        latency_ms = (time.perf_counter() - started) * 1000
        cases.append(
            EvaluationCase(
                query_id=str(item.get("query_id", f"q{index}")),
                returned_ids=tuple(result.external_id for result in response.results),
                relevant_ids=frozenset(
                    str(value) for value in item.get("relevant_ids", [])
                ),
                latency_ms=latency_ms,
                usefulness_score=item.get("usefulness_score"),
                legally_relevant=item.get("legally_relevant"),
            )
        )
    return evaluate_cases(cases, dataset_version=version).to_dict()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="corpus-evaluate")
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args(argv)
    payload = run(args.dataset)
    print(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
