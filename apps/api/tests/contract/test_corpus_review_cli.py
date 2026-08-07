from __future__ import annotations

import uuid

import pytest

from legal_ai.cli.corpus import build_parser


def test_review_cli_requires_expected_version_and_reviewer() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["review", str(uuid.uuid4()), "--approve"])


def test_review_cli_accepts_approve_and_reject_shapes() -> None:
    parser = build_parser()
    approved = parser.parse_args(
        [
            "review",
            str(uuid.uuid4()),
            "--approve",
            "--reviewed-by",
            "reviewer",
            "--expected-version",
            "1",
        ]
    )
    rejected = parser.parse_args(
        [
            "review",
            str(uuid.uuid4()),
            "--reject",
            "--reason",
            "not applicable",
            "--reviewed-by",
            "reviewer",
            "--expected-version",
            "2",
        ]
    )
    assert approved.approve is True and approved.expected_version == 1
    assert rejected.reject is True and rejected.reason == "not applicable"
