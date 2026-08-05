"""Safe source reader contract (filesystem adapter is implemented later)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Protocol


def sanitize_source_identifier(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("CORPUS_SOURCE_IDENTIFIER_INVALID")
    identifier = PurePosixPath(value.replace("\\", "/")).as_posix()
    if (
        not identifier.strip()
        or identifier.startswith("/")
        or identifier.startswith("//")
        or re.fullmatch(r"[A-Za-z]:/.*", identifier) is not None
        or ".." in PurePosixPath(identifier).parts
        or any(ord(character) < 32 or ord(character) == 127 for character in identifier)
        or len(identifier) > 512
    ):
        raise ValueError("CORPUS_SOURCE_IDENTIFIER_INVALID")
    return identifier


class CorpusSourceReader(Protocol):
    async def discover(self, root: str) -> Sequence[str]: ...
    async def read(self, source_identifier: str) -> str: ...
