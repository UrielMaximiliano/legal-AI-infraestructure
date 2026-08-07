"""Deterministic, idempotent normalization for legal corpus text."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from legal_ai.domain.corpus import sha256_text


class CorpusNormalizationError(ValueError):
    """Sanitized normalization error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class NormalizationConfig:
    version: str = "005-nfc-v1"
    headers: tuple[str, ...] = ()
    footers: tuple[str, ...] = ()
    remove_web_artifacts: bool = True


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    raw_content: str = field(repr=False)
    normalized_content: str = field(repr=False)
    raw_content_hash: str
    normalized_content_hash: str
    normalization_version: str
    transformation_report: dict[str, int | bool]


_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x80-\x9f]")
_WEB_ARTIFACT_RE = re.compile(
    r"^(?:skip\s+to\s+(?:main\s+)?content|menu|navigation|home|share|print|"
    r"cookie\s+(?:policy|settings)|subscribe|search)$",
    re.IGNORECASE,
)


class CorpusNormalizationService:
    """Pure service; no filesystem, database, or logging side effects."""

    def __init__(self, config: NormalizationConfig | None = None) -> None:
        self.config = config or NormalizationConfig()

    def normalize(
        self, raw_content: str, *, config: NormalizationConfig | None = None
    ) -> NormalizationResult:
        if not isinstance(raw_content, str) or not raw_content.strip():
            raise CorpusNormalizationError("CORPUS_RAW_CONTENT_EMPTY")
        cfg = config or self.config
        if not cfg.version.strip():
            raise CorpusNormalizationError("CORPUS_NORMALIZATION_VERSION_INVALID")
        raw_hash = sha256_text(raw_content)
        text = unicodedata.normalize("NFC", raw_content)
        bom_removed = text.startswith("\ufeff")
        text = text.lstrip("\ufeff")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        controls_removed = len(_CONTROL_RE.findall(text))
        text = _CONTROL_RE.sub("", text)
        lines: list[str] = []
        configured_headers = {self._canonical_line(v) for v in cfg.headers if v.strip()}
        configured_footers = {self._canonical_line(v) for v in cfg.footers if v.strip()}
        web_removed = 0
        for line in text.split("\n"):
            line = line.replace("\t", " ")
            line = re.sub(r"[ ]{2,}", " ", line).strip()
            canonical = self._canonical_line(line)
            if canonical in configured_headers or canonical in configured_footers:
                web_removed += 1
                continue
            if (
                cfg.remove_web_artifacts
                and canonical
                and _WEB_ARTIFACT_RE.fullmatch(line)
            ):
                web_removed += 1
                continue
            lines.append(line)
        # Normalize the spelling variant without touching article numbers or
        # legal substance.  This makes the operation idempotent.
        normalized = "\n".join(lines)
        normalized = re.sub(
            r"\bARTICULO\b", "ARTÍCULO", normalized, flags=re.IGNORECASE
        )
        normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
        if not normalized:
            raise CorpusNormalizationError("CORPUS_NORMALIZED_CONTENT_EMPTY")
        report: dict[str, int | bool] = {
            "bom_removed": bom_removed,
            "controls_removed": controls_removed,
            "web_or_configured_lines_removed": web_removed,
            "line_endings_normalized": raw_content
            != raw_content.replace("\r\n", "\n").replace("\r", "\n"),
        }
        return NormalizationResult(
            raw_content=raw_content,
            normalized_content=normalized,
            raw_content_hash=raw_hash,
            normalized_content_hash=sha256_text(normalized),
            normalization_version=cfg.version,
            transformation_report=report,
        )

    @staticmethod
    def _canonical_line(value: str) -> str:
        return " ".join(unicodedata.normalize("NFC", value).casefold().split())

    normalize_text = normalize


CorpusNormalizer = CorpusNormalizationService
