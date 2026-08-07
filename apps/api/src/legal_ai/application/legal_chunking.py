"""Versioned, deterministic legal-document chunking.

The chunker works on paragraphs and section boundaries.  It deliberately keeps
articles intact even when an article is larger than the advisory chunk limit;
legal references must never be split merely to satisfy a storage hint.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from legal_ai.domain.corpus import sha256_text


class SectionType(StrEnum):
    HEADER = "HEADER"
    TITLE = "TITLE"
    VISTO = "VISTO"
    CONSIDERANDO = "CONSIDERANDO"
    DISPOSITIVE_INTRO = "DISPOSITIVE_INTRO"
    ARTICLE = "ARTICLE"
    CLOSING = "CLOSING"
    AUTHORITY = "AUTHORITY"
    SIGNATURE = "SIGNATURE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class LegalChunk:
    document_id: uuid.UUID | None
    content: str = field(repr=False)
    content_hash: str
    chunk_index: int
    section_type: SectionType
    section_index: int
    paragraph_index: int | None
    article_number: str | None
    token_count: int
    chunking_version: str
    normalization_version: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _Section:
    section_type: SectionType
    section_index: int
    lines: tuple[str, ...]
    article_number: str | None = None


_ARTICLE_RE = re.compile(
    r"^\s*(?:ART[ÍI]CULO|ART\.?)[\s.:-]*(?P<number>(?:[0-9]+|[ÚU]NICO))"
    r"(?:\s*[°ºª])?\s*[-–:.]?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
_MARKERS: tuple[tuple[re.Pattern[str], SectionType], ...] = (
    (re.compile(r"^\s*VISTO\b", re.IGNORECASE), SectionType.VISTO),
    (re.compile(r"^\s*CONSIDERANDO\b", re.IGNORECASE), SectionType.CONSIDERANDO),
    (
        re.compile(r"^\s*(?:DECRETA|RESUELVE|DISPONE)\s*:?\s*$", re.IGNORECASE),
        SectionType.DISPOSITIVE_INTRO,
    ),
    (
        re.compile(
            r"^\s*(?:COMUNÍQUESE|COMUNIQUESE|REGÍSTRESE|REGISTRESE|PUBLÍQUESE|"
            r"PUBLIQUESE|ARCHÍVESE|ARCHIVESE)\b",
            re.IGNORECASE,
        ),
        SectionType.CLOSING,
    ),
    (
        re.compile(
            r"^\s*(?:PRESIDENTE|MINISTRO|MINISTRA|SECRETARIO|SECRETARIA|"
            r"DIRECTOR|DIRECTORA)\b",
            re.IGNORECASE,
        ),
        SectionType.AUTHORITY,
    ),
    (
        re.compile(r"^\s*(?:FIRMA|FIRMADO|FDO\.?|SIGNED|SIGNATURE)\b", re.IGNORECASE),
        SectionType.SIGNATURE,
    ),
)


class LegalChunkingError(ValueError):
    """Stable error for invalid chunking input or configuration."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class LegalChunkingService:
    def __init__(
        self,
        *,
        chunking_version: str = "005-legal-v1",
        normalization_version: str = "005-nfc-v1",
        max_chunk_chars: int = 12_000,
        max_chars: int | None = None,
    ) -> None:
        self.chunking_version = chunking_version
        self.normalization_version = normalization_version
        self.max_chunk_chars = max_chars if max_chars is not None else max_chunk_chars
        if (
            not isinstance(chunking_version, str)
            or not chunking_version.strip()
            or not isinstance(self.max_chunk_chars, int)
            or self.max_chunk_chars <= 0
        ):
            raise LegalChunkingError("CORPUS_CHUNKING_CONFIG_INVALID")

    def chunk_document(
        self,
        document_id: uuid.UUID | None,
        content: str,
        *,
        normalization_version: str | None = None,
        chunking_version: str | None = None,
    ) -> tuple[LegalChunk, ...]:
        return self.chunk(
            content,
            document_id=document_id,
            normalization_version=normalization_version,
            chunking_version=chunking_version,
        )

    def chunk(
        self,
        content: str,
        *,
        document_id: uuid.UUID | None = None,
        normalization_version: str | None = None,
        chunking_version: str | None = None,
    ) -> tuple[LegalChunk, ...]:
        if not isinstance(content, str) or not content.strip():
            raise LegalChunkingError("CORPUS_NORMALIZED_CONTENT_EMPTY")
        effective_chunking_version = chunking_version or self.chunking_version
        if not isinstance(effective_chunking_version, str) or not (
            effective_chunking_version.strip()
        ):
            raise LegalChunkingError("CORPUS_CHUNKING_CONFIG_INVALID")
        effective_normalization_version = (
            normalization_version or self.normalization_version
        )
        if not isinstance(effective_normalization_version, str) or not (
            effective_normalization_version.strip()
        ):
            raise LegalChunkingError("CORPUS_NORMALIZATION_VERSION_INVALID")
        sections = self._sections(content)
        chunks: list[LegalChunk] = []
        for section in sections:
            paragraphs = self._paragraphs(section.lines)
            if not paragraphs:
                continue
            groups = self._groups(paragraphs, section.section_type)
            for paragraph_index, group in groups:
                text = "\n\n".join(group).strip()
                if not text:
                    continue
                chunks.append(
                    LegalChunk(
                        document_id=document_id,
                        content=text,
                        content_hash=sha256_text(text),
                        chunk_index=len(chunks),
                        section_type=section.section_type,
                        section_index=section.section_index,
                        paragraph_index=paragraph_index,
                        article_number=section.article_number,
                        token_count=len(re.findall(r"\S+", text)),
                        chunking_version=effective_chunking_version,
                        normalization_version=effective_normalization_version,
                        metadata={
                            "section_type": section.section_type.value,
                            "article_number": section.article_number,
                            "oversized": len(text) > self.max_chunk_chars,
                            "token_count_informational": True,
                        },
                    )
                )
        if not chunks:
            raise LegalChunkingError("CORPUS_NO_CHUNKS")
        return tuple(chunks)

    def _groups(
        self, paragraphs: list[str], section_type: SectionType
    ) -> list[tuple[int | None, list[str]]]:
        # An article is an indivisible legal unit.  Other sections may be split
        # only between complete paragraphs and never within a paragraph.
        if section_type is SectionType.ARTICLE:
            return [(0, paragraphs)]
        groups: list[tuple[int | None, list[str]]] = []
        current: list[str] = []
        current_length = 0
        start = 0
        for index, paragraph in enumerate(paragraphs):
            projected = current_length + (2 if current else 0) + len(paragraph)
            if current and projected > self.max_chunk_chars:
                groups.append((start, current))
                current = []
                current_length = 0
                start = index
            current.append(paragraph)
            current_length += (2 if len(current) > 1 else 0) + len(paragraph)
        if current:
            groups.append((start, current))
        return groups

    @staticmethod
    def _paragraphs(lines: tuple[str, ...]) -> list[str]:
        paragraphs: list[str] = []
        current: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped:
                current.append(stripped)
            elif current:
                paragraphs.append(" ".join(current))
                current = []
        if current:
            paragraphs.append(" ".join(current))
        return paragraphs

    @classmethod
    def _sections(cls, content: str) -> tuple[_Section, ...]:
        lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        starts: list[tuple[int, SectionType, str | None]] = []
        for index, line in enumerate(lines):
            article = _ARTICLE_RE.match(line)
            if article:
                starts.append(
                    (index, SectionType.ARTICLE, article.group("number").upper())
                )
                continue
            for pattern, section_type in _MARKERS:
                if pattern.search(line):
                    starts.append((index, section_type, None))
                    break
        if not starts:
            return (_Section(SectionType.UNKNOWN, 0, tuple(lines)),)
        sections: list[_Section] = []
        first_start = starts[0][0]
        if any(line.strip() for line in lines[:first_start]):
            preamble = tuple(lines[:first_start])
            nonempty = [line for line in preamble if line.strip()]
            preamble_type = (
                SectionType.TITLE if len(nonempty) == 1 else SectionType.HEADER
            )
            sections.append(_Section(preamble_type, len(sections), preamble))
        for position, (start, section_type, article_number) in enumerate(starts):
            end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
            sections.append(
                _Section(
                    section_type,
                    len(sections),
                    tuple(lines[start:end]),
                    article_number,
                )
            )
        return tuple(sections)

    chunk_text = chunk


LegalChunker = LegalChunkingService
