import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from legal_ai.adapters.filesystem_corpus import FilesystemCorpusReader
from legal_ai.application.corpus_ingestion import (
    CorpusIngestionConfiguration,
    CorpusIngestionService,
)
from legal_ai.domain.corpus import CorpusDeduplicationRecord


@dataclass
class LookupSpy:
    records: tuple[CorpusDeduplicationRecord, ...] = ()
    calls: int = 0

    async def lookup(self, *, identities, normalized_content_hashes):
        self.calls += 1
        return self.records


@pytest.mark.asyncio
async def test_dry_run_does_not_require_a_uow(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_text("ARTÍCULO 1°.- Uno", encoding="utf-8")
    report = await CorpusIngestionService(FilesystemCorpusReader()).dry_run(
        str(tmp_path)
    )
    assert report.execution_mode == "DRY_RUN"
    assert report.files_valid == 1


@pytest.mark.asyncio
async def test_execute_is_available_for_phase_11(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_text("ARTÍCULO 1°.- Uno", encoding="utf-8")
    with pytest.raises(ValueError, match="EMBEDDING_CONTRACT_INVALID"):
        await CorpusIngestionService(FilesystemCorpusReader()).run(
            str(tmp_path),
            execute=True,
            configuration=CorpusIngestionConfiguration(dimensions=768),
        )


@pytest.mark.asyncio
async def test_execute_validates_the_reader_before_persistence() -> None:
    class FailingReader(FilesystemCorpusReader):
        async def discover_report(self, *args, **kwargs):
            raise AssertionError("reader must not be touched")

    with pytest.raises(AssertionError, match="reader must not be touched"):
        await CorpusIngestionService(FailingReader()).run(
            "does-not-exist", execute=True
        )


@pytest.mark.asyncio
async def test_dry_run_estimates_duplicate_normalized_documents(tmp_path: Path) -> None:
    content = "ARTÍCULO 1°.- Uno"
    (tmp_path / "one.txt").write_text(content, encoding="utf-8")
    (tmp_path / "two.txt").write_text(content, encoding="utf-8")

    report = await CorpusIngestionService(FilesystemCorpusReader()).dry_run(
        str(tmp_path)
    )

    assert report.documents_duplicate_estimate == 1
    assert report.documents_new_estimate == 1


@pytest.mark.asyncio
async def test_dry_run_reports_sanitized_failures_and_fail_fast(tmp_path: Path) -> None:
    (tmp_path / "valid.txt").write_text("ARTÍCULO 1°.- Uno", encoding="utf-8")
    (tmp_path / "empty.txt").write_text("", encoding="utf-8")
    report = await CorpusIngestionService(FilesystemCorpusReader()).dry_run(
        str(tmp_path), fail_fast=True
    )
    assert report.status == "failed"
    assert report.files_invalid == 1
    assert report.failures[0].error_code == "CORPUS_FILE_EMPTY"
    assert str(tmp_path) not in report.model_dump_json()


@pytest.mark.asyncio
async def test_dry_run_rejects_invalid_configuration_and_limit(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_text("ARTÍCULO 1°.- Uno", encoding="utf-8")
    service = CorpusIngestionService(FilesystemCorpusReader())
    with pytest.raises(ValueError, match="EMBEDDING_CONTRACT_INVALID"):
        await service.dry_run(
            str(tmp_path),
            configuration=CorpusIngestionConfiguration(dimensions=768),
        )
    with pytest.raises(ValueError, match="CORPUS_LIMIT_INVALID"):
        await service.dry_run(str(tmp_path), limit=0)


@pytest.mark.asyncio
async def test_dry_run_batch_size_changes_estimate_without_side_effects(
    tmp_path: Path,
) -> None:
    for index in range(3):
        (tmp_path / f"{index}.txt").write_text(
            f"ARTÍCULO {index + 1}°.- Texto", encoding="utf-8"
        )
    service = CorpusIngestionService(FilesystemCorpusReader())
    small = await service.dry_run(
        str(tmp_path), configuration=CorpusIngestionConfiguration(batch_size=1)
    )
    large = await service.dry_run(
        str(tmp_path), configuration=CorpusIngestionConfiguration(batch_size=99)
    )
    assert small.batch_size == 1
    assert small.estimated_batch_count > large.estimated_batch_count
    assert small.request_id == large.request_id


@pytest.mark.asyncio
async def test_dry_run_max_chunks_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_text(
        "ARTÍCULO 1°.- Uno\nARTÍCULO 2°.- Dos", encoding="utf-8"
    )
    report = await CorpusIngestionService(FilesystemCorpusReader()).dry_run(
        str(tmp_path), configuration=CorpusIngestionConfiguration(max_chunks=1)
    )
    assert report.status == "failed"
    assert report.failures[-1].error_code == "CORPUS_MAX_CHUNKS_EXCEEDED"
    assert report.failures[-1].details["max_chunks"] == 1


@pytest.mark.asyncio
async def test_dry_run_reports_identity_and_content_outcomes(tmp_path: Path) -> None:
    (tmp_path / "one.json").write_text(
        json.dumps({"external_id": "same", "content": "ARTÍCULO 1°.- Uno"}),
        encoding="utf-8",
    )
    (tmp_path / "two.json").write_text(
        json.dumps({"external_id": "same", "content": "ARTÍCULO 1°.- Dos"}),
        encoding="utf-8",
    )
    report = await CorpusIngestionService(FilesystemCorpusReader()).dry_run(
        str(tmp_path)
    )
    assert report.deduplication["NEW"] == 1
    assert report.deduplication["SAME_ID_CHANGED_CONTENT"] == 1
    assert report.documents_new_estimate == 1
    assert report.documents_duplicate_estimate == 0


@pytest.mark.asyncio
async def test_dry_run_uses_persisted_read_only_deduplication(tmp_path: Path) -> None:
    (tmp_path / "one.json").write_text(
        json.dumps({"external_id": "persisted", "content": "ARTÃCULO 1Â°.- Uno"}),
        encoding="utf-8",
    )
    from legal_ai.application.corpus_normalization import CorpusNormalizationService

    normalized_hash = (
        CorpusNormalizationService()
        .normalize("ARTÃCULO 1Â°.- Uno")
        .normalized_content_hash
    )
    lookup = LookupSpy(
        records=(
            CorpusDeduplicationRecord(
                source_name="filesystem",
                external_id="persisted",
                normalized_content_hash=normalized_hash,
            ),
        )
    )
    report = await CorpusIngestionService(
        FilesystemCorpusReader(), deduplication_lookup=lookup
    ).dry_run(str(tmp_path))
    assert lookup.calls == 1
    assert report.deduplication["SAME_ID_SAME_CONTENT"] == 1
    assert report.documents_new_estimate == 0


@pytest.mark.asyncio
async def test_dry_run_lookup_failure_is_sanitized_and_not_all_new(
    tmp_path: Path,
) -> None:
    (tmp_path / "one.txt").write_text("ARTÃCULO 1Â°.- Uno", encoding="utf-8")

    class FailingLookup:
        async def lookup(self, **kwargs):
            raise RuntimeError("postgres password=/secret/path")

    report = await CorpusIngestionService(
        FilesystemCorpusReader(), deduplication_lookup=FailingLookup()
    ).dry_run(str(tmp_path))
    assert report.status == "failed"
    assert report.documents_new_estimate == 0
    assert report.failures[-1].error_code == "CORPUS_DEDUP_LOOKUP_UNAVAILABLE"
    assert "password" not in report.model_dump_json()


@pytest.mark.asyncio
async def test_dry_run_all_invalid_files_returns_failures_without_global_error(
    tmp_path: Path,
) -> None:
    (tmp_path / "bad.json").write_text("{not-json", encoding="utf-8")
    (tmp_path / "bad.txt").write_bytes(b"\xff\xfe\x00\x00")
    report = await CorpusIngestionService(FilesystemCorpusReader()).dry_run(
        str(tmp_path)
    )
    assert report.files_valid == 0
    assert {failure.error_code for failure in report.failures} >= {
        "CORPUS_PARSE_FAILED",
        "CORPUS_ENCODING_INVALID",
    }


@pytest.mark.asyncio
async def test_dry_run_mixed_parse_encoding_and_valid_files_isolates_failures(
    tmp_path: Path,
) -> None:
    (tmp_path / "valid.txt").write_text("ARTÃCULO 1Â°.- VÃ¡lido", encoding="utf-8")
    (tmp_path / "invalid.json").write_text("{not-json", encoding="utf-8")
    (tmp_path / "invalid.txt").write_bytes(b"\xff\xfe\x00\x00")
    report = await CorpusIngestionService(FilesystemCorpusReader()).dry_run(
        str(tmp_path)
    )
    assert report.files_valid == 1
    assert report.files_invalid == 2
    assert {failure.error_code for failure in report.failures} == {
        "CORPUS_PARSE_FAILED",
        "CORPUS_ENCODING_INVALID",
    }


@pytest.mark.asyncio
async def test_dry_run_chunk_limit_exact_and_plus_one_are_deterministic(
    tmp_path: Path,
) -> None:
    for index in range(2):
        (tmp_path / f"{index}.txt").write_text(
            f"ARTÃCULO {index + 1}Â°.- Texto", encoding="utf-8"
        )
    service = CorpusIngestionService(FilesystemCorpusReader())
    baseline = await service.dry_run(str(tmp_path))
    exact = await service.dry_run(
        str(tmp_path),
        configuration=CorpusIngestionConfiguration(
            max_chunks=baseline.chunks_estimated
        ),
    )
    over = await service.dry_run(
        str(tmp_path),
        configuration=CorpusIngestionConfiguration(
            max_chunks=baseline.chunks_estimated - 1
        ),
    )
    assert exact.status == "completed"
    assert exact.chunks_estimated == baseline.chunks_estimated
    assert over.status == "failed"
    assert over.failures[-1].error_code == "CORPUS_MAX_CHUNKS_EXCEEDED"
    assert over.failures[-1].details["observed_chunks"] == baseline.chunks_estimated
