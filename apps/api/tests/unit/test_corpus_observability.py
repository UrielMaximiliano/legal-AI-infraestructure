from __future__ import annotations

import logging

from legal_ai.observability.corpus_events import CorpusEvent, sanitize_event_fields
from legal_ai.observability.corpus_logging import log_corpus_event, redact_exception
from legal_ai.observability.corpus_metrics import CorpusMetrics


def test_corpus_events_are_allowlisted_and_redacted() -> None:
    payload = sanitize_event_fields(
        {
            "request_id": "request-1",
            "model": "qwen3-embedding:0.6b",
            "dimensions": 1024,
            "raw_content": "secret body",
            "token": "secret",
            "query": "private query",
        }
    )
    assert payload == {
        "request_id": "request-1",
        "model": "qwen3-embedding:0.6b",
        "dimensions": 1024,
    }
    assert "raw_content" not in CorpusEvent("embedding", payload).safe_dict()


def test_corpus_logging_does_not_emit_forbidden_fields(caplog) -> None:
    with caplog.at_level(logging.INFO):
        log_corpus_event(
            "embedding_batch",
            request_id="request-1",
            batch_id="batch-1",
            raw_content="secret",
            Authorization="Bearer secret",
        )
    assert "secret" not in caplog.text
    assert "batch-1" in caplog.text


def test_corpus_metrics_are_deterministic() -> None:
    metrics = CorpusMetrics()
    metrics.increment("embedding_batches", tags={"status": "succeeded"})
    metrics.increment("embedding_batches", tags={"status": "succeeded"}, value=2)
    assert metrics.get("embedding_batches", tags={"status": "succeeded"}) == 3
    assert metrics.snapshot()["embedding_batches"] == 3


def test_exception_redaction_uses_stable_code() -> None:
    class Error(Exception):
        code = "SAFE_ERROR"

    assert redact_exception(Error("secret token")) == "SAFE_ERROR"
