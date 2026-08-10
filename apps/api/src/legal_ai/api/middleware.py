"""Cross-cutting request limits and sanitization for RAG HTTP calls."""

from __future__ import annotations

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from legal_ai.config import settings


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
