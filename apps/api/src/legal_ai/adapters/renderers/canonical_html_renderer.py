"""Deterministic, self-contained HTML rendering for preview and PDF input."""

from __future__ import annotations

import hashlib
import html
import json
from collections.abc import Iterable
from typing import Any

from legal_ai.config import settings
from legal_ai.domain.errors import ExportSizeExceededError, RendererExecutionError


class SafeCanonicalHtmlRenderer:
    """Render only escaped canonical values and no external resources."""

    name = "canonical-html"
    version = "1.0"

    def render(self, snapshot: dict[str, Any]) -> str:
        try:
            document = snapshot.get("document") or {}
            title = self._text(document.get("title", "Documento"))
            header = self._text(document.get("institutional_header", ""))
            locale = self._text(document.get("locale", "es-AR"))
            source_text = self._text(snapshot.get("source_text", ""))
            sections = self._section("VISTO", document.get("visto", []))
            sections += self._section(
                "CONSIDERANDO", document.get("considerando", [])
            )
            por_ello = self._text(document.get("por_ello", ""))
            articles = self._articles(document.get("articles", []))
            signatures = self._signatures(document.get("signatures", []))
            institution = (
                f'<header class="institutional">{header}</header>' if header else ""
            )
            body = "".join(
                (
                    institution,
                    f"<h1>{title}</h1>",
                    sections,
                    (
                        f"<section><h2>POR ELLO</h2><p>{por_ello}</p></section>"
                        if por_ello
                        else ""
                    ),
                    articles,
                    f'<section class="source-text"><p>{source_text}</p></section>',
                    signatures,
                )
            )
            result = (
                '<!doctype html><html lang="'
                + html.escape(locale, quote=True)
                + '"><head><meta charset="utf-8">'
                '<meta name="generator" content="legal-ai-canonical-html">'
                '<style>body{font-family:Arial,sans-serif;font-size:11pt;'
                "line-height:1.5;margin:2.5cm 2cm 2.5cm 3cm;text-align:justify;}"
                "h1{font-size:12pt;text-align:center;font-weight:700;}"
                "h2{font-size:11pt;font-weight:700;}.institutional{text-align:center;}"
                'p{margin:0 0 6pt;} .signature{display:inline-block;min-width:6cm;'
                'margin:2cm 1cm 0 0;text-align:center;}</style></head><body>'
                + body
                + "</body></html>"
            )
            size = len(result.encode("utf-8"))
            if size > settings.export.max_preview_size_bytes:
                raise ExportSizeExceededError(
                    size, settings.export.max_preview_size_bytes
                )
            return result
        except ExportSizeExceededError:
            raise
        except (TypeError, ValueError, AttributeError) as exc:
            raise RendererExecutionError() from exc

    @staticmethod
    def digest(html_text: str) -> str:
        return hashlib.sha256(html_text.encode("utf-8")).hexdigest()

    @staticmethod
    def _text(value: Any) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return str(html.escape(value, quote=True)).replace("\n", "<br>")

    def _section(self, heading: str, values: Any) -> str:
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, Iterable):
            values = []
        paragraphs = "".join(f"<p>{self._text(value)}</p>" for value in values)
        return f"<section><h2>{heading}</h2>{paragraphs}</section>"

    def _articles(self, values: Any) -> str:
        if not isinstance(values, Iterable) or isinstance(values, (str, bytes)):
            return ""
        rendered: list[str] = []
        for index, value in enumerate(values, start=1):
            if isinstance(value, dict):
                number = value.get("number", index)
                text = value.get("text", value.get("content", ""))
            else:
                number, text = index, value
            rendered.append(
                f'<section class="article"><h2>ARTÍCULO {self._text(number)}°</h2>'
                f"<p>{self._text(text)}</p></section>"
            )
        return "".join(rendered)

    def _signatures(self, values: Any) -> str:
        if not isinstance(values, Iterable) or isinstance(values, (str, bytes)):
            return ""
        return '<section class="signatures">' + "".join(
            f'<span class="signature">{self._text(value)}</span>' for value in values
        ) + "</section>"
