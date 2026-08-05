import pytest
from pydantic import ValidationError

from legal_ai.config import EmbeddingConfig


def test_model_and_dimension_are_fixed() -> None:
    with pytest.raises(ValidationError):
        EmbeddingConfig(OLLAMA_EMBEDDING_MODEL="other:model")
    with pytest.raises(ValidationError):
        EmbeddingConfig(EMBEDDING_DIMENSIONS=768)
