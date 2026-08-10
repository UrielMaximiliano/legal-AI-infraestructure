"""Administrative corpus CLI; dry-run is the safe default."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.corpus_document_repository import (
    SQLAlchemyCorpusDeduplicationLookup,
)
from legal_ai.adapters.database.engine import create_engine
from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.adapters.filesystem_corpus import (
    CorpusReaderError,
    FilesystemCorpusReader,
)
from legal_ai.adapters.ollama_embedding import OllamaEmbeddingAdapter
from legal_ai.application.corpus_activation import CorpusActivationService
from legal_ai.application.corpus_ingestion import (
    CorpusIngestionConfiguration,
    CorpusIngestionService,
)
from legal_ai.application.corpus_reindex import CorpusReindexService
from legal_ai.application.corpus_review import CorpusReviewService
from legal_ai.application.inference_coordinator import InferenceCoordinator
from legal_ai.application.rag_evaluation import RagEvaluationManifestError
from legal_ai.cli.corpus_evaluate import run as run_evaluation
from legal_ai.cli.corpus_evaluate import run_ollama as run_ollama_evaluation
from legal_ai.cli.corpus_probe import probe as run_probe
from legal_ai.cli.rag_evaluate import run as run_rag_evaluation
from legal_ai.config import CorpusConfig, settings
from legal_ai.embedding_contract import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL
from legal_ai.schemas.corpus_activation import CorpusActivationRequest
from legal_ai.schemas.corpus_reindex import CorpusReindexRequest
from legal_ai.schemas.corpus_review import CorpusReviewRequest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="corpus")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest")
    ingest.add_argument("path")
    ingest.add_argument("--document-type", default="decreto")
    ingest.add_argument("--document-subtype", default="designacion_transitoria")
    ingest.add_argument("--jurisdiction", default="nacion")
    ingest.add_argument("--language", default="es")
    ingest.add_argument("--source-name", default="filesystem")
    ingest.add_argument("--batch-size", type=int)
    ingest.add_argument("--embedding-model", default=EMBEDDING_MODEL)
    ingest.add_argument(
        "--embedding-dimensions", type=int, default=EMBEDDING_DIMENSIONS
    )
    ingest.add_argument("--execute", action="store_true")
    ingest.add_argument("--resume", action="store_true")
    ingest.add_argument("--run-id")
    ingest.add_argument("--limit", type=int)
    ingest.add_argument("--fail-fast", action="store_true")
    ingest.add_argument("--output", choices=("json",), default="json")
    review = commands.add_parser("review")
    review.add_argument("document_id")
    review.add_argument("--approve", action="store_true")
    review.add_argument("--reject", action="store_true")
    review.add_argument("--reason")
    review.add_argument("--reviewed-by", required=True)
    review.add_argument("--expected-version", required=True, type=int)
    review.add_argument("--request-id")
    reindex = commands.add_parser("reindex")
    reindex.add_argument("--document-id", action="append", dest="document_ids")
    reindex.add_argument("--document-type", default="decreto")
    reindex.add_argument("--document-subtype", default="designacion_transitoria")
    reindex.add_argument("--jurisdiction", default="nacion")
    reindex.add_argument("--language")
    reindex.add_argument("--organization")
    reindex.add_argument("--batch-size", type=int, default=16)
    reindex.add_argument("--execute", action="store_true")
    reindex.add_argument("--resume", action="store_true")
    reindex.add_argument("--run-id")
    activate = commands.add_parser("activate-staged-index")
    activate.add_argument("--expected-database", required=True)
    activate.add_argument("--generation", type=int, default=1)
    activate.add_argument("--batch-size", type=int, default=100)
    activate.add_argument("--execute", action="store_true")
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--dataset", required=True)
    evaluate.add_argument("--provider", choices=("fake", "ollama"), default="fake")
    evaluate.add_argument("--include-pending-review", action="store_true")
    evaluate.add_argument("--human-evaluations", action="store_true")
    evaluate.add_argument("--output", choices=("json",), default="json")
    probe = commands.add_parser("probe-embedding")
    probe.add_argument("--base-url")
    probe.add_argument("--token")
    probe.add_argument("--endpoint", choices=("/api/embed", "/api/embeddings"))
    probe.add_argument("--timeout", type=float, default=10.0)
    probe.add_argument("--output", choices=("json",), default="json")
    rag_evaluate = commands.add_parser("rag-evaluate")
    rag_evaluate.add_argument("manifest_path")
    rag_evaluate.add_argument("--execute", action="store_true")
    rag_evaluate.add_argument("--provider", choices=("fake", "ollama"), default="fake")
    rag_evaluate.add_argument("--limit", type=int)
    return parser


async def _run_ingest(args: argparse.Namespace) -> int:
    if args.resume and (not args.execute or not args.run_id):
        raise ValueError("CORPUS_RESUME_REQUIRES_EXECUTE_AND_RUN_ID")
    # CorpusConfig validates the canonical file limits and extension policy.
    limits = CorpusConfig()
    if args.batch_size is not None and not 0 < args.batch_size <= 256:
        raise ValueError("CORPUS_BATCH_SIZE_INVALID")
    reader = FilesystemCorpusReader(
        max_file_size_bytes=limits.max_input_bytes,
        max_files=limits.max_files,
        allowed_extensions=limits.allowed_extensions,
    )
    await reader.discover_report(args.path)
    configuration = CorpusIngestionConfiguration(
        model=args.embedding_model,
        dimensions=args.embedding_dimensions,
        source_name=args.source_name,
        document_type=args.document_type,
        document_subtype=args.document_subtype,
        jurisdiction=args.jurisdiction,
        language=args.language,
        batch_size=(
            args.batch_size
            if args.batch_size is not None
            else limits.embedding_batch_size
        ),
        max_chunks=limits.max_chunks,
    )
    engine = create_engine()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            provider = None
            coordinator = None
            if args.execute:
                ollama = settings.ollama
                provider = OllamaEmbeddingAdapter(
                    base_url=ollama.base_url,
                    api_token=ollama.api_token,
                    model=configuration.model,
                    dimensions=configuration.dimensions,
                    timeout_seconds=limits.embedding_timeout_seconds,
                    endpoint=ollama.endpoint,
                )
                coordinator = InferenceCoordinator(
                    max_queue_size=limits.max_queue_size,
                    wait_timeout=float(limits.wait_timeout_seconds),
                )
            service = CorpusIngestionService(
                reader,
                deduplication_lookup=SQLAlchemyCorpusDeduplicationLookup(session),
                embedding_provider=provider,
                inference_coordinator=coordinator,
            )
            report = await service.run(
                args.path,
                configuration=configuration,
                execute=args.execute,
                limit=args.limit,
                fail_fast=args.fail_fast,
                run_id=args.run_id,
                resume=args.resume,
            )
            if not args.execute:
                # The lookup is read-only; explicitly roll back its read
                # transaction so this path cannot accidentally publish writes.
                await session.rollback()
    finally:
        await engine.dispose()
    payload = report.model_dump(mode="json")
    payload["counts"] = report.counts
    print(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    return 0 if report.status != "failed" else 2


async def _run_review(args: argparse.Namespace) -> int:
    try:
        document_id = uuid.UUID(args.document_id)
    except (AttributeError, ValueError):
        raise ValueError("CORPUS_DOCUMENT_ID_INVALID") from None
    request = CorpusReviewRequest(
        document_id=document_id,
        approve=args.approve,
        reject=args.reject,
        reason=args.reason,
        reviewed_by=args.reviewed_by,
        expected_version=args.expected_version,
    )
    async with UnitOfWork() as uow:
        result = await CorpusReviewService(uow).review(
            request, request_id=args.request_id
        )
    print(
        json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


async def _run_reindex(args: argparse.Namespace) -> int:
    if args.resume and not args.execute:
        raise ValueError("CORPUS_REINDEX_RESUME_REQUIRES_EXECUTE")
    try:
        document_ids = tuple(uuid.UUID(value) for value in (args.document_ids or ()))
    except (TypeError, ValueError):
        raise ValueError("CORPUS_DOCUMENT_ID_INVALID") from None
    request = CorpusReindexRequest(
        document_ids=document_ids,
        document_type=args.document_type,
        document_subtype=args.document_subtype,
        jurisdiction=args.jurisdiction,
        language=args.language,
        organization=args.organization,
        batch_size=args.batch_size,
        run_id=args.run_id,
        resume=args.resume,
    )
    service = CorpusReindexService(uow_factory=UnitOfWork)
    report = await (
        service.execute(request) if args.execute else service.dry_run(request)
    )
    print(
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if report.status != "failed" else 2


async def _run_activate_staged_index(args: argparse.Namespace) -> int:
    request = CorpusActivationRequest(
        expected_database=args.expected_database,
        generation=args.generation,
        batch_size=args.batch_size,
    )
    service = CorpusActivationService(uow_factory=UnitOfWork)
    report = await (
        service.execute(request) if args.execute else service.dry_run(request)
    )
    print(
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


async def _run_evaluate(args: argparse.Namespace) -> int:
    payload = (
        run_evaluation(Path(args.dataset))
        if args.provider == "fake"
        else await run_ollama_evaluation(
            Path(args.dataset), include_pending_review=args.include_pending_review
        )
    )
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


async def _run_probe(args: argparse.Namespace) -> int:
    base_url = args.base_url or settings.ollama.base_url
    token = args.token or settings.ollama.api_token
    endpoint = args.endpoint or settings.ollama.endpoint
    payload = await run_probe(base_url, token, args.timeout, endpoint)
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "ingest":
            return asyncio.run(_run_ingest(args))
        if args.command == "review":
            return asyncio.run(_run_review(args))
        if args.command == "reindex":
            return asyncio.run(_run_reindex(args))
        if args.command == "activate-staged-index":
            return asyncio.run(_run_activate_staged_index(args))
        if args.command == "evaluate":
            return asyncio.run(_run_evaluate(args))
        if args.command == "probe-embedding":
            return asyncio.run(_run_probe(args))
        if args.command == "rag-evaluate":
            return run_rag_evaluation(
                args.manifest_path,
                execute=args.execute,
                provider=args.provider,
                limit=args.limit,
            )
    except OSError:
        code = "CORPUS_PATH_INVALID"
        print(
            json.dumps(
                {"error": {"code": code}},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2
    except RagEvaluationManifestError as exc:
        code = exc.code
        exit_code = {
            "RAG_HOLDOUT_LEAKAGE_DETECTED": 3,
            "RAG_EXTERNAL_PROVIDER_NOT_CONFIGURED": 4,
            "RAG_EVALUATION_PARTIAL": 5,
            "RAG_AUDIT_UNAVAILABLE": 6,
        }.get(code, 2)
        print(
            json.dumps(
                {"error": {"code": code}},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return exit_code
    except (CorpusReaderError, ValueError) as exc:
        code = getattr(exc, "code", str(exc))
        print(
            json.dumps(
                {"error": {"code": code}},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
