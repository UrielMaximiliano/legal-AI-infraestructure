"""Resumable 90% corpus embedding runner for the local test corpus.

This operational command deliberately targets only chunks tagged ``INDEX_90``.
It never touches the ``HOLDOUT_10`` split and uses the database's nullable
embedding as its checkpoint, so a stopped run can be resumed safely.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.corpus_models import CorpusChunkModel
from legal_ai.adapters.database.engine import create_engine
from legal_ai.adapters.ollama_embedding import (
    OllamaEmbeddingAdapter,
    OllamaEmbeddingError,
)
from legal_ai.config import settings
from legal_ai.embedding_contract import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL

INDEX_SPLIT = "INDEX_90"
HOLDOUT_SPLIT = "HOLDOUT_10"
EMBEDDING_WORKER_TIMEOUT_SECONDS = 120.0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Embed only the INDEX_90 staged corpus chunks (resumable)."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=4,
        help="Sequential requests per database transaction (default: 4).",
    )
    parser.add_argument(
        "--max-chunks",
        type=int,
        default=None,
        help="Optional bounded run for a pilot or maintenance window.",
    )
    return parser


def _split_predicate() -> Any:
    return CorpusChunkModel.metadata_json["evaluation_split"].as_string() == INDEX_SPLIT


async def _pending_count(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(CorpusChunkModel)
        .where(
            CorpusChunkModel.generation == 1,
            CorpusChunkModel.state == "STAGED",
            CorpusChunkModel.embedding.is_(None),
            _split_predicate(),
        )
    )
    return int(result.scalar_one())


async def _embed_with_recovery(
    adapter: OllamaEmbeddingAdapter,
    rows: Sequence[Any],
) -> list[list[float]]:
    """Embed one batch without abandoning the long-running checkpoint job.

    The external legacy endpoint processes one prompt at a time. A transient
    timeout must not terminate the whole corpus run, so a failed multi-row
    request is retried row-by-row and every request gets a bounded retry loop.
    """

    async def request(texts: list[str], label: str) -> list[list[float]]:
        last_error: OllamaEmbeddingError | None = None
        for attempt in range(5):
            try:
                return await adapter.embed_documents(texts)
            except OllamaEmbeddingError as exc:
                last_error = exc
                print(
                    f"request_retry label={label} attempt={attempt + 1} "
                    f"code={exc.code}",
                    flush=True,
                )
                if attempt < 4:
                    await asyncio.sleep(min(60.0, 2.0**attempt))
        if last_error is not None:
            raise last_error
        raise RuntimeError("EMBEDDING_REQUEST_FAILED")

    texts = [str(row.content) for row in rows]
    try:
        return await request(texts, "batch")
    except OllamaEmbeddingError as exc:
        if len(rows) == 1:
            raise
        print(
            f"batch_fallback size={len(rows)} code={exc.code}",
            flush=True,
        )
        vectors: list[list[float]] = []
        for index, text in enumerate(texts):
            vectors.extend(await request([text], f"item-{index}"))
        return vectors


async def _embed(*, batch_size: int, max_chunks: int | None) -> None:
    if batch_size <= 0 or batch_size > 32:
        raise ValueError("BATCH_SIZE_INVALID")
    if max_chunks is not None and max_chunks <= 0:
        raise ValueError("MAX_CHUNKS_INVALID")

    engine = create_engine()
    adapter = OllamaEmbeddingAdapter(
        base_url=settings.ollama.base_url,
        api_token=settings.ollama.api_token,
        model=EMBEDDING_MODEL,
        dimensions=EMBEDDING_DIMENSIONS,
        # The public proxy allows up to five minutes.  This long-running
        # worker uses a larger per-request budget than the interactive API so
        # one unusually long legal chunk does not terminate the full run.
        timeout_seconds=max(
            EMBEDDING_WORKER_TIMEOUT_SECONDS,
            float(settings.ollama.timeout_seconds),
        ),
        endpoint=settings.ollama.endpoint,
        context_length=settings.ollama.embedding_context_length,
        max_retries=2,
    )
    processed = 0
    started = time.perf_counter()
    try:
        while max_chunks is None or processed < max_chunks:
            remaining = (
                batch_size
                if max_chunks is None
                else min(batch_size, max_chunks - processed)
            )
            async with AsyncSession(engine, expire_on_commit=False) as session:
                rows = (
                    await session.execute(
                        select(CorpusChunkModel.id, CorpusChunkModel.content)
                        .where(
                            CorpusChunkModel.generation == 1,
                            CorpusChunkModel.state == "STAGED",
                            CorpusChunkModel.embedding.is_(None),
                            _split_predicate(),
                        )
                        .order_by(
                            CorpusChunkModel.document_id,
                            CorpusChunkModel.generation,
                            CorpusChunkModel.section_index,
                            CorpusChunkModel.paragraph_index,
                            CorpusChunkModel.id,
                        )
                        .limit(remaining)
                    )
                ).all()
            if not rows:
                break

            vectors = await _embed_with_recovery(adapter, rows)
            if len(vectors) != len(rows):
                raise RuntimeError("EMBEDDING_COUNT_MISMATCH")

            persisted = 0
            async with (
                AsyncSession(engine, expire_on_commit=False) as session,
                session.begin(),
            ):
                for row, vector in zip(rows, vectors, strict=True):
                    result = await session.execute(
                        update(CorpusChunkModel)
                        .where(
                            CorpusChunkModel.id == row.id,
                            CorpusChunkModel.generation == 1,
                            CorpusChunkModel.state == "STAGED",
                            CorpusChunkModel.embedding.is_(None),
                            _split_predicate(),
                        )
                        .values(
                            embedding=vector,
                            embedding_model=EMBEDDING_MODEL,
                            embedding_dimensions=EMBEDDING_DIMENSIONS,
                        )
                    )
                    persisted += int(getattr(result, "rowcount", 0) or 0)
            processed += persisted
            if processed == 0:
                raise RuntimeError("EMBEDDING_CHECKPOINT_STALLED")
            if processed % 100 < batch_size:
                async with AsyncSession(engine, expire_on_commit=False) as session:
                    pending = await _pending_count(session)
                elapsed = time.perf_counter() - started
                print(
                    f"progress processed={processed} pending={pending} "
                    f"elapsed_s={elapsed:.1f}",
                    flush=True,
                )

        async with AsyncSession(engine, expire_on_commit=False) as session:
            pending = await _pending_count(session)
            holdout_embedded = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(CorpusChunkModel)
                        .where(
                            CorpusChunkModel.metadata_json["evaluation_split"].as_string()
                            == HOLDOUT_SPLIT,
                            CorpusChunkModel.embedding.is_not(None),
                        )
                    )
                ).scalar_one()
            )
        if holdout_embedded != 0:
            raise RuntimeError("HOLDOUT_EMBEDDING_GUARD_FAILED")
        print(
            f"complete processed={processed} pending={pending} "
            f"holdout_embedded={holdout_embedded} model={EMBEDDING_MODEL} "
            f"dimensions={EMBEDDING_DIMENSIONS}",
            flush=True,
        )
    finally:
        await engine.dispose()


def main() -> None:
    args = _parser().parse_args()
    asyncio.run(_embed(batch_size=args.batch_size, max_chunks=args.max_chunks))


if __name__ == "__main__":
    main()
