"""Unit tests for canonical HTML, artifact renderers and process supervision."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from legal_ai.adapters.renderers.canonical_html_renderer import (
    SafeCanonicalHtmlRenderer,
)
from legal_ai.adapters.renderers.docx_renderer import PythonDocxRenderer
from legal_ai.adapters.renderers.pdf_renderer import WeasyPrintPdfRenderer
from legal_ai.application.artifact_integrity import (
    DOCX_MIME,
    ArtifactIntegrityValidator,
)
from legal_ai.application.renderer_supervisor import RendererSupervisor
from legal_ai.config import settings
from legal_ai.domain.errors import (
    ExportSizeExceededError,
    GenerationTimeoutError,
    InvalidFinalizationError,
    RendererExecutionError,
)


def _snapshot(source_text: str = "Contenido aprobado") -> dict[str, Any]:
    return {
        "draft_id": "11111111-1111-4111-8111-111111111111",
        "source_draft_version": 1,
        "source_text": source_text,
        "document": {
            "title": "Resolución de prueba",
            "locale": "es-AR",
            "institutional_header": "Institución",
            "visto": ["VISTO el expediente"],
            "considerando": ["CONSIDERANDO la documentación"],
            "por_ello": "Por ello se resuelve.",
            "articles": [{"number": 1, "text": "Artículo primero"}],
            "signatures": ["Firma"],
        },
    }


def test_html_is_deterministic_and_escapes_active_content() -> None:
    renderer = SafeCanonicalHtmlRenderer()
    source = '<script>alert("x")</script><iframe src="x">'
    result = renderer.render(_snapshot(source))
    assert result == renderer.render(_snapshot(source))
    assert "<script>" not in result
    assert "<iframe" not in result
    assert "remote" not in result
    assert "&lt;script&gt;" in result
    assert "ARTÍCULO 1°" in result


def test_html_limit_is_measured_in_utf8_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    renderer = SafeCanonicalHtmlRenderer()
    monkeypatch.setattr(settings.export, "max_preview_size_bytes", 10_000_000)
    rendered = renderer.render(_snapshot("á" * 100))
    limit = len(rendered.encode("utf-8"))
    monkeypatch.setattr(settings.export, "max_preview_size_bytes", limit)
    assert renderer.render(_snapshot("á" * 100)) == rendered
    monkeypatch.setattr(settings.export, "max_preview_size_bytes", limit - 1)
    with pytest.raises(ExportSizeExceededError):
        renderer.render(_snapshot("á" * 100))


def test_docx_renderer_writes_institutional_document(tmp_path: Path) -> None:
    output = tmp_path / "11111111-1111-4111-8111-111111111111_v1.docx"
    PythonDocxRenderer().render(_snapshot(), output)
    assert output.is_file()
    assert output.stat().st_size > 0
    assert (
        ArtifactIntegrityValidator().validate_docx(
            output, declared_mime=DOCX_MIME
        )
    )
    assert PythonDocxRenderer.timeout_seconds == 30


def test_docx_renderer_rejects_missing_required_snapshot_fields(
    tmp_path: Path,
) -> None:
    with pytest.raises(InvalidFinalizationError):
        PythonDocxRenderer().render({}, tmp_path / "output.docx")


def test_pdf_health_is_replaceable() -> None:
    assert isinstance(WeasyPrintPdfRenderer.health(), bool)
    assert WeasyPrintPdfRenderer.timeout_seconds == 60


def test_pdf_renderer_rejects_missing_canonical_html(tmp_path: Path) -> None:
    with pytest.raises(InvalidFinalizationError):
        WeasyPrintPdfRenderer().render("", tmp_path / "output.pdf")


class _SuccessRenderer:
    def render(self, input_data: dict[str, Any], output_path: Path) -> None:
        output_path.write_bytes(str(input_data["value"]).encode())


class _FailingRenderer:
    def render(self, input_data: dict[str, Any], output_path: Path) -> None:
        raise RuntimeError("internal renderer detail")


class _SleepingRenderer:
    def render(self, input_data: dict[str, Any], output_path: Path) -> None:
        time.sleep(5)
        output_path.write_bytes(b"late")


class _RecordedProcess:
    def __init__(self, **kwargs: Any) -> None:
        self.alive = True
        self.exitcode = None
        self.calls: list[str] = []

    def start(self) -> None:
        self.calls.append("start")

    def join(self, timeout: float | None = None) -> None:
        self.calls.append("join")

    def is_alive(self) -> bool:
        return self.alive

    def terminate(self) -> None:
        self.calls.append("terminate")

    def kill(self) -> None:
        self.calls.append("kill")
        self.alive = False


def test_supervisor_success_uses_child_and_joins(tmp_path: Path) -> None:
    output = tmp_path / "out.docx"
    result = RendererSupervisor().run(
        _SuccessRenderer(), {"value": "ok"}, output, timeout_seconds=5
    )
    assert result == output
    assert output.read_bytes() == b"ok"


def test_supervisor_sanitizes_child_exception_and_cleans_output(tmp_path: Path) -> None:
    output = tmp_path / "out.pdf"
    with pytest.raises(RendererExecutionError):
        RendererSupervisor().run(_FailingRenderer(), {}, output, timeout_seconds=5)
    assert not output.exists()


def test_supervisor_timeout_terminates_and_cleans_child(tmp_path: Path) -> None:
    output = tmp_path / "out.pdf"
    with pytest.raises(GenerationTimeoutError):
        RendererSupervisor(grace_seconds=0.05).run(
            _SleepingRenderer(), {}, output, timeout_seconds=1
        )
    assert not output.exists()


def test_supervisor_timeout_sequence_is_terminate_grace_kill_join(
    tmp_path: Path,
) -> None:
    created: list[_RecordedProcess] = []

    def factory(**kwargs: Any) -> _RecordedProcess:
        process = _RecordedProcess(**kwargs)
        created.append(process)
        return process

    with pytest.raises(GenerationTimeoutError):
        RendererSupervisor(
            grace_seconds=0.01, process_factory=factory
        ).run(_SuccessRenderer(), {}, tmp_path / "out.pdf", timeout_seconds=1)
    assert created[0].calls == ["start", "join", "terminate", "join", "kill", "join"]
