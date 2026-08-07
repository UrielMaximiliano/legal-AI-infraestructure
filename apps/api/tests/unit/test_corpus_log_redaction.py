from __future__ import annotations

import logging

from legal_ai.observability.corpus_events import sanitize_event_fields
from legal_ai.observability.corpus_logging import log_corpus_event, redact_exception


def test_corpus_log_redaction_removes_content_vectors_and_paths(caplog) -> None:
    with caplog.at_level(logging.INFO):
        log_corpus_event(
            "search",
            request_id="request-id",
            query="private query",
            raw_content="document body",
            normalized_content="normal body",
            vector=[0.1, 0.2],
            storage_path="C:\\private\\corpus.txt",
            stack_trace="trace",
            result_count=2,
        )
    assert "private query" not in caplog.text
    assert "document body" not in caplog.text
    assert "corpus.txt" not in caplog.text
    assert "0.1" not in caplog.text
    assert "result_count" in caplog.text
    assert sanitize_event_fields({"Authorization": "Bearer secret"}) == {}
    assert redact_exception(RuntimeError("secret")) == "CORPUS_OPERATION_FAILED"
