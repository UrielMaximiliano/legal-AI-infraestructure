"""Headless PDF renderer from canonical HTML with external resources disabled."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from legal_ai.domain.errors import InvalidFinalizationError, RendererExecutionError


class WeasyPrintPdfRenderer:
    """Render canonical HTML without depending on DOCX or LibreOffice."""

    name = "weasyprint"
    version = "63"
    timeout_seconds = 60

    @staticmethod
    def health() -> bool:
        try:
            import weasyprint  # type: ignore[import-untyped]

            return bool(str(weasyprint.__version__))
        except (ImportError, OSError):
            return False

    def render(self, html: str, output_path: Path) -> None:
        if not isinstance(html, str) or not html.strip():
            raise InvalidFinalizationError(details={"field": "html"})
        try:
            from weasyprint import HTML
            from weasyprint.urls import (  # type: ignore[import-untyped]
                default_url_fetcher,
            )

            def fetcher(url: str) -> dict[str, object]:
                scheme = urlparse(url).scheme.lower()
                if scheme not in {"", "data", "about"}:
                    raise ValueError("external resource disabled")
                return dict(default_url_fetcher(url))

            output_path.parent.mkdir(parents=True, exist_ok=True)
            HTML(string=html, url_fetcher=fetcher).write_pdf(str(output_path))
        except InvalidFinalizationError:
            raise
        except Exception as exc:
            raise RendererExecutionError() from exc
