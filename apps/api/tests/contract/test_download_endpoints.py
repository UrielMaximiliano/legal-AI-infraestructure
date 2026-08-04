"""Download contract coverage for integrity and HTTP range behavior."""

from __future__ import annotations

import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.adapters.storage.local_artifact_storage import LocalArtifactStorage
from legal_ai.application.artifact_integrity import ArtifactIntegrityValidator
from legal_ai.config import settings
from legal_ai.domain.document_export import DocumentExport
from legal_ai.domain.enums import ExportFormat, ExportStatus
from legal_ai.main import app
from tests.contract.test_exports_endpoints import _seed_finalized_draft


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _seed_docx_export(client: AsyncClient, root: Path) -> uuid.UUID:
    draft_id = await _seed_finalized_draft(client)
    fixture = Path(__file__).parents[1] / "fixtures" / "valid_document.docx"
    storage = LocalArtifactStorage(root)
    validator = ArtifactIntegrityValidator()
    async with UnitOfWork() as uow:
        draft = await uow.drafts.get_by_id(draft_id)
        review = await uow.reviews.get_latest_for_draft(draft_id)
        assert draft is not None and review is not None and draft.final_snapshot_sha256
        relative = storage.build_relative_path(
            draft.case_file_id, draft.id, "DOCX", 1, f"{draft.id}_v1.docx"
        )
        destination = storage.resolve_relative(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fixture, destination)
        digest = validator.validate_docx(destination)
        export_id = uuid.uuid4()
        now = datetime.now(UTC)
        await uow.document_exports.create(
            DocumentExport(
                id=export_id,
                draft_id=draft.id,
                draft_version=draft.version,
                review_id=review.id,
                export_version=1,
                format=ExportFormat.DOCX,
                status=ExportStatus.GENERATED,
                file_name=f"{draft.id}_v1.docx",
                source_snapshot_sha256=draft.final_snapshot_sha256,
                exported_by="Editor",
                created_at=now,
                updated_at=now,
                storage_path=relative,
                content_sha256=digest,
                completed_at=now,
            )
        )
    return export_id


@pytest.mark.contract
@pytest.mark.asyncio
async def test_download_validates_hash_and_returns_required_headers(
    client, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(settings.export, "storage_root", tmp_path)
    export_id = await _seed_docx_export(client, tmp_path)

    response = await client.get(f"/api/v1/exports/{export_id}/download")
    assert response.status_code == 200
    assert response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["accept-ranges"] == "none"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["etag"].startswith('"sha256:')
    assert int(response.headers["content-length"]) == len(response.content)

    conditional = await client.get(
        f"/api/v1/exports/{export_id}/download",
        headers={"If-None-Match": response.headers["etag"]},
    )
    assert conditional.status_code == 304
    assert conditional.headers["accept-ranges"] == "none"
    assert conditional.content == b""


@pytest.mark.contract
@pytest.mark.asyncio
async def test_range_is_rejected_before_file_access(
    client, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(settings.export, "storage_root", tmp_path)
    export_id = await _seed_docx_export(client, tmp_path)
    response = await client.get(
        f"/api/v1/exports/{export_id}/download",
        headers={"Range": "bytes=0-10"},
    )
    assert response.status_code == 416
    assert response.json()["error_code"] == "RANGE_NOT_SUPPORTED"
    assert response.json()["error"]["request_id"]
    assert response.headers["accept-ranges"] == "none"
    assert "content-range" not in response.headers


@pytest.mark.integration
@pytest.mark.asyncio
async def test_missing_and_corrupt_files_have_deterministic_public_errors(
    client, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(settings.export, "storage_root", tmp_path)
    export_id = await _seed_docx_export(client, tmp_path)
    async with UnitOfWork() as uow:
        export = await uow.document_exports.get_by_id(export_id)
        assert export is not None and export.storage_path
        destination = LocalArtifactStorage(tmp_path).resolve_relative(
            export.storage_path
        )
        destination.unlink()

    missing = await client.get(f"/api/v1/exports/{export_id}/download")
    assert missing.status_code == 410
    assert missing.json()["error_code"] == "EXPORT_FILE_NOT_FOUND"

    export_id = await _seed_docx_export(client, tmp_path)
    async with UnitOfWork() as uow:
        export = await uow.document_exports.get_by_id(export_id)
        assert export is not None and export.storage_path
        destination = LocalArtifactStorage(tmp_path).resolve_relative(
            export.storage_path
        )
        destination.write_bytes(b"corrupt")
    corrupt = await client.get(f"/api/v1/exports/{export_id}/download")
    assert corrupt.status_code == 409
    assert corrupt.json()["error_code"] == "EXPORT_FILE_CORRUPTED"
