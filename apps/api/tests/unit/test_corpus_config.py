import pytest
from pydantic import ValidationError

from legal_ai.config import CorpusConfig, EmbeddingConfig, SemanticSearchConfig


def test_contract_defaults() -> None:
    assert EmbeddingConfig().model == "qwen3-embedding:0.6b"
    assert EmbeddingConfig().dimensions == 1024
    assert SemanticSearchConfig().reviewed_only is True


def test_limits_reject_invalid_values() -> None:
    with pytest.raises(ValidationError):
        CorpusConfig(OLLAMA_EMBEDDING_BATCH_SIZE=0)
    with pytest.raises(ValidationError):
        SemanticSearchConfig(SEMANTIC_SEARCH_MAX_TOP_K=0)


def test_overrides() -> None:
    config = CorpusConfig(CORPUS_MAX_BATCH_FILES=12, CORPUS_MAX_FILE_SIZE_BYTES=2048)
    assert config.max_files == 12
    assert config.max_input_bytes == 2048


def test_legacy_names_remain_explicitly_supported() -> None:
    config = CorpusConfig(CORPUS_EMBEDDING_BATCH_SIZE=12, CORPUS_MAX_INPUT_BYTES=2048)
    assert config.embedding_batch_size == 12
    assert config.max_input_bytes == 2048
