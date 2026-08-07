from __future__ import annotations

import pytest

from legal_ai.adapters.embeddings.fake_embedding import FakeEmbeddingProvider
from legal_ai.application.embedding_batch import EmbeddingBatchProcessor
from legal_ai.application.inference_coordinator import InferenceCoordinator
from legal_ai.embedding_contract import EMBEDDING_DIMENSIONS


@pytest.mark.asyncio
async def test_embedding_batch_validates_and_uses_coordinator() -> None:
    coordinator = InferenceCoordinator(max_queue_size=1)
    try:
        processor = EmbeddingBatchProcessor(
            FakeEmbeddingProvider(), coordinator, dimensions=EMBEDDING_DIMENSIONS
        )
        vectors = await processor.embed(("primer texto", "segundo texto"))
        assert len(vectors) == 2
        assert all(len(vector) == EMBEDDING_DIMENSIONS for vector in vectors)
    finally:
        await coordinator.close()


@pytest.mark.asyncio
async def test_embedding_batch_rejects_empty_input_and_bad_provider_count() -> None:
    coordinator = InferenceCoordinator(max_queue_size=1)
    try:
        processor = EmbeddingBatchProcessor(
            FakeEmbeddingProvider(), coordinator, dimensions=EMBEDDING_DIMENSIONS
        )
        with pytest.raises(ValueError, match="INPUT"):
            await processor.embed(())

        class ShortProvider(FakeEmbeddingProvider):
            async def embed_documents(self, texts):
                return [[0.0] * EMBEDDING_DIMENSIONS]

        short = EmbeddingBatchProcessor(
            ShortProvider(), coordinator, dimensions=EMBEDDING_DIMENSIONS
        )
        with pytest.raises(ValueError, match="COUNT"):
            await short.embed(("uno", "dos"))
    finally:
        await coordinator.close()
