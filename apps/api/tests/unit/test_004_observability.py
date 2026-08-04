"""Security and contract tests for 004 structured observability."""

from __future__ import annotations

import json
import logging
import uuid

from legal_ai.observability.logging import (
    current_request_id,
    log_event,
    reset_request_id,
    set_request_id,
)


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_structured_event_has_allowlisted_fields_and_correlation() -> None:
    handler = _Capture()
    logger = logging.getLogger("test.004.observability")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    token = set_request_id("request-004")
    try:
        log_event(
            "export_validation_completed",
            logger=logger,
            export_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
            attempt_id=uuid.UUID("22222222-2222-4222-8222-222222222222"),
            renderer="python-docx",
            duration_ms=12.5,
            size_bytes=1024,
            sha256="a" * 64,
            document_body="no debe registrarse",
            storage_path="C:/secret/absolute/path.docx",
            Authorization="Bearer secret",
        )
    finally:
        reset_request_id(token)
        logger.removeHandler(handler)

    assert current_request_id() is None
    payload = handler.records[0].structured_event
    assert payload["request_id"] == "request-004"
    assert payload["duration_ms"] == 12.5
    assert payload["sha256"] == "a" * 64
    assert "document_body" not in payload
    assert "storage_path" not in payload
    assert "Authorization" not in payload
    json.dumps(payload)


def test_logger_drops_absolute_paths_newlines_and_invalid_hashes() -> None:
    handler = _Capture()
    logger = logging.getLogger("test.004.sanitization")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        log_event(
            "download_integrity_verified",
            logger=logger,
            request_id="ok",
            sha256="not-a-hash",
            renderer="/absolute/path\nsecret",
        )
    finally:
        logger.removeHandler(handler)
    payload = handler.records[0].structured_event
    assert "sha256" not in payload
    assert "renderer" not in payload


def test_request_context_value_round_trips() -> None:
    assert current_request_id() is None
    token = set_request_id("round-trip")
    try:
        assert current_request_id() == "round-trip"
    finally:
        reset_request_id(token)
    assert current_request_id() is None
