"""Cross-cutting request limits and sanitization for RAG HTTP calls."""

from __future__ import annotations

import hmac

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from legal_ai.config import settings


class ServiceTokenMiddleware(BaseHTTPMiddleware):
    """Require the private BFF service token when one is configured."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        expected = settings.service.service_token
        path = request.url.path
        if expected and path.startswith("/api/v1/"):
            authorization = request.headers.get("authorization", "")
            supplied = authorization.removeprefix("Bearer ").strip()
            if not supplied:
                return self._error(request, 401, "SERVICE_AUTH_REQUIRED")
            if not hmac.compare_digest(supplied, expected):
                return self._error(request, 403, "SERVICE_AUTH_INVALID")
        return await call_next(request)

    @staticmethod
    def _error(request: Request, status_code: int, code: str) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={
                "error_code": code,
                "message": "La solicitud no tiene credenciales de servicio válidas.",
                "request_id": getattr(request.state, "request_id", None),
            },
        )


class ImiRuntimeBoundaryMiddleware(BaseHTTPMiddleware):
    """Fail closed for routes that still belong to the legacy database."""

    _LEGACY_PREFIXES = (
        "/api/v1/drafts",
        "/api/v1/generation-attempts",
        "/api/v1/reviews",
        "/api/v1/semantic-search",
        "/api/v1/exports",
    )

    @staticmethod
    def _is_imi_draft_read_path(path: str) -> bool:
        """Allow the IMI Core-backed collection and detail reads."""
        if path == "/api/v1/drafts":
            return True
        prefix = "/api/v1/drafts/"
        if not path.startswith(prefix):
            return False
        parts = path.removeprefix(prefix).split("/")
        return len(parts) == 1 or (len(parts) == 2 and parts[1] == "document")

    @staticmethod
    def _is_imi_draft_document_path(path: str) -> bool:
        prefix = "/api/v1/drafts/"
        if not path.startswith(prefix):
            return False
        parts = path.removeprefix(prefix).split("/")
        return len(parts) == 2 and parts[1] == "document"

    @staticmethod
    def _is_imi_manual_draft_path(path: str) -> bool:
        """Allow manual draft creation to write only to IMI Core."""
        return path == "/api/v1/drafts"

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if settings.rag_profile.code != "imi_leg_06b":
            return await call_next(request)
        path = request.url.path
        imi_core_path = (
            (request.method == "GET" and self._is_imi_draft_read_path(path))
            or (
                request.method == "PATCH"
                and self._is_imi_draft_document_path(path)
            )
            or (
                request.method == "POST"
                and self._is_imi_manual_draft_path(path)
            )
        )
        legacy_path = (
            (path.startswith(self._LEGACY_PREFIXES) and not imi_core_path)
            or (
                path.startswith("/api/v1/case-files/")
                and path.endswith(("/designation", "/generation-attempts"))
            )
        )
        if legacy_path:
            return JSONResponse(
                status_code=501,
                content={
                    "error_code": "IMI_CORE_ROUTE_NOT_IMPLEMENTED",
                    "message": (
                        "La ruta solicitada todavía no está migrada a imi_leg_core."
                    ),
                    "request_id": getattr(request.state, "request_id", None),
                },
            )
        return await call_next(request)


class RagSecurityMiddleware(BaseHTTPMiddleware):
    """Enforce bounded JSON input without recording request contents or secrets."""

    _RAG_PREFIX = "/api/v1/rag/"

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path.startswith(self._RAG_PREFIX) and request.method == "POST":
            content_type = request.headers.get("content-type", "").split(";", 1)[0]
            if content_type != "application/json":
                return self._error(request, 415, "RAG_CONTENT_TYPE_INVALID")
            raw_length = request.headers.get("content-length")
            if raw_length is not None:
                try:
                    content_length = int(raw_length)
                except ValueError:
                    return self._error(request, 400, "RAG_CONTENT_LENGTH_INVALID")
                if (
                    content_length < 0
                    or content_length > settings.rag.max_request_bytes
                ):
                    return self._error(request, 413, "RAG_REQUEST_TOO_LARGE")
            body = await request.body()
            if len(body) > settings.rag.max_request_bytes:
                return self._error(request, 413, "RAG_REQUEST_TOO_LARGE")
        return await call_next(request)

    @staticmethod
    def _error(request: Request, status_code: int, code: str) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=status_code,
            content={
                "error_code": code,
                "message": "La solicitud RAG no cumple los límites de seguridad.",
                "request_id": request_id,
            },
        )
