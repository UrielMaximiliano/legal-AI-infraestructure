"""End-to-end coverage for the phase 10 DOCX/PDF pipeline."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from legal_ai.adapters.renderers.pdf_renderer import WeasyPrintPdfRenderer
from legal_ai.config import settings
from legal_ai.main import app
from tests.contract.test_exports_endpoints import _seed_finalized_draft


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_docx_and_pdf_then_download(client, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings.export, "storage_root", tmp_path)
    draft_id = await _seed_finalized_draft(client)

    for raw_format in ("DOCX", "PDF"):
        if raw_format == "PDF" and not WeasyPrintPdfRenderer.health():
            continue
        created = await client.post(
            f"/api/v1/drafts/{draft_id}/exports",
            json={
                "draft_version": 3,
                "format": raw_format,
                "exported_by": "Editor",
            },
            headers={
                "Idempotency-Key": (f"export-{raw_format.lower()}-{uuid.uuid4().hex}")
            },
        )
        assert created.status_code == 202
        export_id = created.json()["id"]

        status = None
        for _ in range(30):
            metadata = await client.get(f"/api/v1/exports/{export_id}")
            status = metadata.json()["status"]
            if status == "GENERATED":
                break
            await asyncio.sleep(0.2)
        assert status == "GENERATED", {
            "status": status,
            "error_code": metadata.json().get("error_code"),
            "error_message": metadata.json().get("error_message"),
        }

        download = await client.get(f"/api/v1/exports/{export_id}/download")
        assert download.status_code == 200
        assert len(download.content) > 0
