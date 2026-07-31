"""Middleware de request context para request_id."""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_REQUEST_ID_HEADER = "X-Request-ID"
_MAX_REQUEST_ID_LENGTH = 128


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Middleware que genera o valida request_id para cada solicitud."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        raw_id = request.headers.get(_REQUEST_ID_HEADER, "")
        request_id = self._sanitize_request_id(raw_id)
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers[_REQUEST_ID_HEADER] = request_id
        return response

    @staticmethod
    def _sanitize_request_id(raw_id: str) -> str:
        """Sanitiza y valida el request_id recibido."""
        if not raw_id or len(raw_id) > _MAX_REQUEST_ID_LENGTH:
            return str(uuid.uuid4())
        # Permitir solo caracteres alfanuméricos, guiones y guiones bajos
        sanitized = "".join(c for c in raw_id if c.isalnum() or c in ("-", "_"))
        return sanitized if sanitized else str(uuid.uuid4())
