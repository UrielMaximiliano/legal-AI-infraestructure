"""Filesystem-integrity integration checks for the download boundary."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.config import settings
from legal_ai.domain.enums import ExportStatus
from legal_ai.main import app
from tests.contract.test_download_endpoints import _seed_docx_export


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unsafe_path_and_corruption_do_not_transition_export(
    client, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(settings.export, "storage_root", tmp_path)
    export_id = await _seed_docx_export(client, tmp_path)
    async with UnitOfWork() as uow:
        await uow.document_exports.update_status(
            export_id,
            ExportStatus.GENERATED,
            storage_path="../outside.docx",
        )

    traversal = await client.get(f"/api/v1/exports/{export_id}/download")
    assert traversal.status_code == 409
    assert traversal.json()["error_code"] == "EXPORT_FILE_CORRUPTED"

    export_id = await _seed_docx_export(client, tmp_path)
    async with UnitOfWork() as uow:
        export = await uow.document_exports.get_by_id(export_id)
        assert export is not None and export.storage_path
        from legal_ai.adapters.storage.local_artifact_storage import (
            LocalArtifactStorage,
        )

        path = LocalArtifactStorage(tmp_path).resolve_relative(export.storage_path)
        path.write_bytes(b"not-a-docx")
    corrupted = await client.get(f"/api/v1/exports/{export_id}/download")
    assert corrupted.status_code == 409
    assert corrupted.json()["error_code"] == "EXPORT_FILE_CORRUPTED"
    async with UnitOfWork() as uow:
        export = await uow.document_exports.get_by_id(export_id)
    assert export is not None and export.status == ExportStatus.GENERATED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_symlinked_artifact_is_blocked_when_supported(
    client, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(settings.export, "storage_root", tmp_path)
    export_id = await _seed_docx_export(client, tmp_path)
    async with UnitOfWork() as uow:
        export = await uow.document_exports.get_by_id(export_id)
        assert export is not None and export.storage_path
        from legal_ai.adapters.storage.local_artifact_storage import (
            LocalArtifactStorage,
        )

        path = LocalArtifactStorage(tmp_path).resolve_relative(export.storage_path)
        target = path.with_name("target.docx")
        target.write_bytes(path.read_bytes())
        path.unlink()
        try:
            path.symlink_to(target)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks are unavailable on this host")
    response = await client.get(f"/api/v1/exports/{export_id}/download")
    assert response.status_code == 409
    assert response.json()["error_code"] == "EXPORT_FILE_CORRUPTED"
