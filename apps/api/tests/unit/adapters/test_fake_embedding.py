import asyncio
import math

import pytest

from legal_ai.adapters.embeddings.fake_embedding import (
    FakeEmbeddingError,
    FakeEmbeddingProvider,
)


@pytest.mark.asyncio
async def test_deterministic_documents_query_batch_and_dimension() -> None:
    provider = FakeEmbeddingProvider()
    first = await provider.embed_documents(["texto jurídico", "otro texto"])
    second = await provider.embed_documents(["texto jurídico", "otro texto"])
    assert first == second
    assert len(first) == 2 and len(first[0]) == 2560
    assert await provider.embed_query("texto jurídico") == first[0]
    assert all(math.isfinite(value) for value in first[0])


@pytest.mark.asyncio
async def test_configurable_failures_timeout_and_invalid_dimension() -> None:
    with pytest.raises(ValueError):
        FakeEmbeddingProvider(dimensions=768)
    with pytest.raises(FakeEmbeddingError):
        await FakeEmbeddingProvider(failure="FAKE_FAILURE").embed_documents(["x"])
    with pytest.raises(FakeEmbeddingError):
        await FakeEmbeddingProvider().embed_documents([])
    with pytest.raises(FakeEmbeddingError):
        await FakeEmbeddingProvider().embed_query("")
    for invalid in ("empty", "wrong_dimension", "nan", "infinite"):
        with pytest.raises(FakeEmbeddingError):
            await FakeEmbeddingProvider(invalid_vector=invalid).embed_query("x")
    provider = FakeEmbeddingProvider(delay_seconds=0.01)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(provider.embed_query("x"), timeout=0.001)
    timeout_provider = FakeEmbeddingProvider(delay_seconds=0.001, timeout_error=True)
    with pytest.raises(FakeEmbeddingError, match="FAKE_EMBEDDING_TIMEOUT"):
        await timeout_provider.embed_query("x")
