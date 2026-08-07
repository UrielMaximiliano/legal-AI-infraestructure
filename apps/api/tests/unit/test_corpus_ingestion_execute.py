from __future__ import annotations

from pathlib import Path

import pytest

from legal_ai.adapters.filesystem_corpus import FilesystemCorpusReader
from legal_ai.application.corpus_ingestion import (
    CorpusIngestionConfiguration,
    CorpusIngestionService,
)


@pytest.mark.asyncio
async def test_execute_configuration_and_resume_validation_happen_before_writes(
    tmp_path: Path,
) -> None:
    service = CorpusIngestionService(FilesystemCorpusReader(tmp_path))
    with pytest.raises(ValueError, match="EMBEDDING_CONTRACT"):
        await service.run(
            str(tmp_path),
            execute=True,
            configuration=CorpusIngestionConfiguration(dimensions=768),
        )
    with pytest.raises(ValueError, match="RUN_ID"):
        await service.run(str(tmp_path), execute=True, resume=True)


@pytest.mark.asyncio
async def test_execute_rejects_invalid_batch_limit_without_provider_call(
    tmp_path: Path,
) -> None:
    service = CorpusIngestionService(FilesystemCorpusReader(tmp_path))
    with pytest.raises(ValueError, match="CONFIGURATION"):
        await service.run(
            str(tmp_path),
            execute=True,
            configuration=CorpusIngestionConfiguration(batch_size=0),
        )
